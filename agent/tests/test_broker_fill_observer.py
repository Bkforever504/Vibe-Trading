from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from scripts.broker_fill_observer import (
    ObservationBounds,
    observe_fills,
    run_once,
    validate_base_url,
    validate_request,
)


NOW = datetime(2026, 8, 24, 16, 0, tzinfo=timezone.utc)


def test_request_boundary_allows_only_get_on_fixed_read_endpoints() -> None:
    validate_request("GET", "/v2/account/activities/FILL")
    validate_request("get", "/v2/orders")
    validate_base_url("https://paper-api.alpaca.markets")
    validate_base_url("https://api.alpaca.markets/")

    for method in ("POST", "PATCH", "DELETE", "PUT"):
        with pytest.raises(ValueError, match="GET-only"):
            validate_request(method, "/v2/orders")
    with pytest.raises(ValueError, match="endpoint"):
        validate_request("GET", "/v2/positions")
    with pytest.raises(ValueError, match="endpoint"):
        validate_request("GET", "https://evil.example/v2/orders")
    with pytest.raises(ValueError, match="base"):
        validate_base_url("https://evil.example")


def test_observer_normalizes_and_links_unique_fill_without_identifiers() -> None:
    calls: list[dict] = []

    def fetcher(*, method, endpoint, params, timeout):
        calls.append({"method": method, "endpoint": endpoint, "params": dict(params), "timeout": timeout})
        if endpoint == "/v2/orders":
            return [
                {
                    "id": "broker-order-secret",
                    "client_order_id": "client-order-secret",
                    "account_id": "account-secret",
                    "symbol": "SPY",
                    "side": "buy",
                    "qty": "2",
                    "filled_qty": "2",
                    "status": "filled",
                }
            ]
        return [
            {
                "id": "fill-secret",
                "order_id": "broker-order-secret",
                "account_id": "account-secret",
                "activity_type": "FILL",
                "symbol": "SPY",
                "side": "buy",
                "qty": "2",
                "price": "651.25",
                "transaction_time": "2026-08-24T15:35:03Z",
                "commission": "0.06",
                "regulatory_fee": "0.01",
            }
        ]

    report = observe_fills(
        fetcher=fetcher,
        plans=[
            {
                "detection_id": "pd-safe-plan",
                "symbol": "SPY",
                "direction": "bullish",
                "trigger_bar_ts": "2026-08-24T15:30:00Z",
            }
        ],
        now=NOW,
        bounds=ObservationBounds(lookback_days=2, max_pages=2, page_size=100, timeout_seconds=7.0),
    )

    assert report["status"] == "ok"
    assert report["summary"] == {
        "fill_count": 1,
        "partial_fill_count": 0,
        "matched_count": 1,
        "ambiguous_count": 0,
        "unmatched_count": 0,
        "skipped_malformed_count": 0,
    }
    fill = report["fills"][0]
    assert fill == {
        "symbol": "SPY",
        "side": "buy",
        "quantity": 2.0,
        "price": 651.25,
        "filled_at": "2026-08-24T15:35:03Z",
        "fill_state": "fill",
        "fees": 0.07,
        "fee_status": "reported",
        "linkage": {
            "status": "matched",
            "detection_id": "pd-safe-plan",
            "method": "symbol_direction_causal_time_window_v1",
            "candidate_count": 1,
            "lag_seconds": 303.0,
        },
        "source": {
            "provider": "alpaca",
            "label": "alpaca_account_activity_fill",
            "method": "GET",
            "endpoint": "/v2/account/activities/FILL",
        },
        "execution_enabled": False,
        "can_submit_orders": False,
    }
    serialized = json.dumps(report)
    for secret in ("broker-order-secret", "client-order-secret", "account-secret", "fill-secret"):
        assert secret not in serialized
    for forbidden_field in ('"account_id"', '"order_id"', '"client_order_id"', '"activity_id"'):
        assert forbidden_field not in serialized
    assert all(call["method"] == "GET" for call in calls)
    assert all(call["timeout"] == 7.0 for call in calls)
    activity_call = next(call for call in calls if call["endpoint"].endswith("/FILL"))
    assert activity_call["params"]["page_size"] == 100
    assert activity_call["params"]["after"] == "2026-08-22T16:00:00Z"
    assert report["execution_enabled"] is False
    assert report["can_submit_orders"] is False


def test_linkage_keeps_ambiguous_and_unmatched_explicit() -> None:
    def fetcher(*, method, endpoint, params, timeout):
        del method, params, timeout
        if endpoint == "/v2/orders":
            return []
        return [
            {
                "id": "one",
                "symbol": "QQQ",
                "side": "sell",
                "qty": "1",
                "price": "570",
                "transaction_time": "2026-08-24T15:40:00Z",
            },
            {
                "id": "two",
                "symbol": "IWM",
                "side": "buy",
                "qty": "1",
                "price": "230",
                "transaction_time": "2026-08-24T15:45:00Z",
            },
        ]

    plans = [
        {"detection_id": "qqq-a", "symbol": "QQQ", "direction": "bearish", "trigger_bar_ts": "2026-08-24T15:30:00Z"},
        {"detection_id": "qqq-b", "symbol": "QQQ", "direction": "short", "trigger_bar_ts": "2026-08-24T15:31:00Z"},
    ]
    report = observe_fills(fetcher=fetcher, plans=plans, now=NOW)

    assert report["fills"][0]["linkage"] == {
        "status": "ambiguous",
        "detection_id": None,
        "method": "symbol_direction_causal_time_window_v1",
        "candidate_count": 2,
        "lag_seconds": None,
    }
    assert report["fills"][1]["linkage"]["status"] == "unmatched"
    assert report["fills"][1]["linkage"]["candidate_count"] == 0


def test_partial_fill_is_enriched_internally_but_order_ids_are_omitted() -> None:
    def fetcher(*, method, endpoint, params, timeout):
        del method, params, timeout
        if endpoint == "/v2/orders":
            return [
                {
                    "id": "private-order-id",
                    "symbol": "NVDA",
                    "side": "buy",
                    "qty": "5",
                    "filled_qty": "2",
                    "status": "partially_filled",
                }
            ]
        return [
            {
                "id": "private-fill-id",
                "order_id": "private-order-id",
                "symbol": "NVDA",
                "side": "buy",
                "qty": "2",
                "price": "185.50",
                "transaction_time": "2026-08-24T15:45:00Z",
            }
        ]

    report = observe_fills(fetcher=fetcher, plans=[], now=NOW)
    fill = report["fills"][0]

    assert fill["fill_state"] == "partial_fill"
    assert fill["fees"] is None
    assert fill["fee_status"] == "unavailable"
    assert "private-order-id" not in json.dumps(report)
    assert "private-fill-id" not in json.dumps(report)


@pytest.mark.parametrize(
    "bounds",
    [
        ObservationBounds(lookback_days=0),
        ObservationBounds(lookback_days=31),
        ObservationBounds(max_pages=0),
        ObservationBounds(max_pages=11),
        ObservationBounds(page_size=0),
        ObservationBounds(page_size=101),
        ObservationBounds(timeout_seconds=0.9),
        ObservationBounds(timeout_seconds=30.1),
        ObservationBounds(linkage_window_minutes=0),
        ObservationBounds(linkage_window_minutes=1441),
    ],
)
def test_observation_bounds_fail_closed(bounds: ObservationBounds) -> None:
    with pytest.raises(ValueError):
        bounds.validate()


def test_run_once_writes_one_atomic_report_and_redacts_fetch_failures(tmp_path: Path) -> None:
    report_path = tmp_path / "reports" / "broker-fill-observer.json"

    def failing_fetcher(*, method, endpoint, params, timeout):
        del method, endpoint, params, timeout
        raise RuntimeError("APCA_API_SECRET_KEY=do-not-write account=private-account")

    report = run_once(
        fetcher=failing_fetcher,
        plans=[],
        now=NOW,
        report_path=report_path,
    )

    assert report["status"] == "unavailable"
    assert report["errors"] == [{"type": "RuntimeError", "reason": "broker_read_unavailable"}]
    assert report["execution_enabled"] is False
    assert report["can_submit_orders"] is False
    assert json.loads(report_path.read_text(encoding="utf-8")) == report
    assert not report_path.with_suffix(".json.tmp").exists()
    assert list(tmp_path.rglob("*.jsonl")) == []
    serialized = report_path.read_text(encoding="utf-8")
    assert "do-not-write" not in serialized
    assert "private-account" not in serialized

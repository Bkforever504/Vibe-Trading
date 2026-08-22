from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from scripts.broker_reconciliation_daemon import local_inventory, reconcile, run_once
from scripts import broker_reconciliation_daemon as daemon


NOW = datetime(2026, 8, 20, 15, 0, tzinfo=timezone.utc)


def test_local_inventory_ignores_closed_history() -> None:
    inventory = local_inventory(
        [
            {"trades": [
                {"symbol": "SPYOPT", "status": "open", "qty": 2, "client_order_id": "vibe-filled-entry"},
                {"symbol": "QQQOPT", "status": "submitted", "qty": 1, "client_order_id": "vibe-pending"},
                {"symbol": "OLDOPT", "status": "closed", "qty": 5, "client_order_id": "vibe-closed"},
            ]}
        ]
    )

    assert inventory == {"order_ids": ["vibe-pending"], "positions": {"SPYOPT": 2.0}}


def test_reconcile_detects_order_and_position_mismatches() -> None:
    diffs = reconcile(
        broker_orders=[{"client_order_id": "vibe-extra"}],
        broker_fills=[],
        broker_positions=[{"symbol": "SPYOPT", "qty": "1"}],
        local={"order_ids": ["vibe-missing"], "positions": {"SPYOPT": 2}},
    )

    assert {row["class"] for row in diffs} == {
        "missing_broker_order",
        "untracked_broker_order",
        "position_quantity_mismatch",
    }


def test_reconcile_does_not_treat_terminal_order_history_as_open_diff() -> None:
    diffs = reconcile(
        broker_orders=[
            {"client_order_id": "vibe-filled", "status": "filled"},
            {"client_order_id": "vibe-canceled", "status": "canceled"},
        ],
        broker_fills=[],
        broker_positions=[],
        local={"order_ids": [], "positions": {}},
    )
    assert diffs == []


def test_forced_scratch_reconciliation_publishes_diff_without_order_authority(tmp_path: Path) -> None:
    state = tmp_path / "state.json"
    state.write_text(json.dumps({"status": "open", "symbol": "SPYOPT", "qty": 1, "client_order_id": "vibe-local"}), encoding="utf-8")

    result = run_once(
        event_log=tmp_path / "events.jsonl",
        report_path=tmp_path / "report.json",
        state_files=[state],
        snapshot=([], [], []),
        now=NOW,
    )

    assert result["status"] == "diff"
    assert result["diff_count"] == 1
    assert result["diffs"][0]["class"] == "position_quantity_mismatch"
    assert result["execution_enabled"] is False
    assert result["can_submit_orders"] is False
    assert (tmp_path / "events.jsonl").exists()
    assert json.loads((tmp_path / "report.json").read_text(encoding="utf-8"))["status"] == "diff"


def test_alpaca_fill_request_obeys_current_page_limit_and_paginates(monkeypatch) -> None:
    from strategies import flip_bot

    monkeypatch.setattr(flip_bot, "KEY", "test-key")
    monkeypatch.setattr(flip_bot, "SECRET", "test-secret")
    monkeypatch.setattr(flip_bot, "BASE", "https://paper-api.alpaca.markets")
    calls = []

    class Response:
        def __init__(self, payload):
            self.payload = payload

        def raise_for_status(self):
            return None

        def json(self):
            return self.payload

    class Session:
        def get(self, url, *, headers, params, timeout):
            del headers, timeout
            calls.append((url, dict(params or {})))
            if url.endswith("/v2/orders"):
                return Response([])
            if url.endswith("/v2/positions"):
                return Response([])
            if "page_token" not in (params or {}):
                return Response([{"id": f"fill-{index}"} for index in range(100)])
            return Response([{"id": "fill-final"}])

    monkeypatch.setattr(daemon.requests, "Session", Session)

    _, fills, _ = daemon._alpaca_snapshot()

    activity_calls = [params for url, params in calls if url.endswith("/activities/FILL")]
    assert len(fills) == 101
    assert len(activity_calls) == 2
    assert all(params["page_size"] == 100 for params in activity_calls)
    assert activity_calls[0]["after"].endswith("Z")
    assert activity_calls[1]["page_token"] == "fill-99"

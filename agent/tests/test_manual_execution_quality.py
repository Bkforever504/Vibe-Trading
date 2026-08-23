from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from scripts.manual_execution_quality import (
    append_manual_observation,
    build_manual_observation,
    generate_execution_quality_report,
    read_observations,
)


PLAN_HASH = "plan-34d7359b8ec7f847a76e8d3b"


def _payload(**overrides: object) -> dict:
    payload = {
        "observation_id": "manual-SPY-cisd-20260824-01",
        "lifecycle_id": "pd-973cd0b14f09b3760c4d4da1",
        "detection_id": "pd-973cd0b14f09b3760c4d4da1",
        "plan_id": "plan-SPY-cisd-20260824",
        "plan_hash": PLAN_HASH,
        "source_label": "kenny_manual_trade_review",
        "source_as_of": "2026-08-24T14:42:00Z",
        "observed_at": "2026-08-24T15:12:00Z",
        "decision_at": "2026-08-24T14:35:00Z",
        "symbol": "SPY",
        "direction": "long",
        "intended_entry_price": 100.0,
        "intended_stop_price": 99.0,
        "intended_quantity": 10,
        "entry_status": "filled",
        "entry_spread_bps": 2.5,
        "entry_fills": [
            {"filled_at": "2026-08-24T14:36:00Z", "quantity": 6, "price": 100.05, "fee": 0.60},
            {"filled_at": "2026-08-24T14:37:00Z", "quantity": 4, "price": 100.10, "fee": 0.40},
        ],
        "exit_fills": [
            {
                "filled_at": "2026-08-24T15:00:00Z",
                "quantity": 10,
                "price": 101.10,
                "reference_price": 101.12,
                "spread_bps": 3.0,
                "fee": 1.0,
            }
        ],
    }
    payload.update(overrides)
    return payload


def test_builds_closed_manual_observation_with_net_execution_metrics() -> None:
    row = build_manual_observation(_payload(), expected_plan_hash=PLAN_HASH)

    assert row["actual_entry"]["filled_quantity"] == 10
    assert row["actual_entry"]["average_price"] == pytest.approx(100.07)
    assert row["entry_slippage_bps"] == pytest.approx(7.0)
    assert row["position_status"] == "closed"
    assert row["total_fees"] == pytest.approx(2.0)
    assert row["realized_gross_pnl"] == pytest.approx(10.3)
    assert row["realized_net_pnl"] == pytest.approx(8.3)
    assert row["realized_net_r"] == pytest.approx(0.83)
    assert row["exit_fills"][0]["slippage_bps"] == pytest.approx(1.977848)
    assert row["execution_enabled"] is False
    assert row["can_submit_orders"] is False


def test_partial_and_unfilled_observations_remain_explicit() -> None:
    partial = build_manual_observation(
        _payload(
            observation_id="manual-SPY-partial",
            entry_status="partial",
            entry_fills=[{"filled_at": "2026-08-24T14:36:00Z", "quantity": 4, "price": 100.05, "fee": 0.4}],
            exit_fills=[],
        ),
        expected_plan_hash=PLAN_HASH,
    )
    unfilled = build_manual_observation(
        _payload(
            observation_id="manual-SPY-unfilled",
            entry_status="unfilled",
            entry_fills=[],
            exit_fills=[],
        ),
        expected_plan_hash=PLAN_HASH,
    )

    assert partial["actual_entry"]["status"] == "partial"
    assert partial["position_status"] == "open"
    assert partial["realized_net_pnl"] is None
    assert unfilled["actual_entry"]["status"] == "unfilled"
    assert unfilled["actual_entry"]["average_price"] is None
    assert unfilled["position_status"] == "unfilled"


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"plan_hash": "plan-wrong"}, "plan_hash_mismatch"),
        ({"lifecycle_id": ""}, "missing_lifecycle_id"),
        ({"detection_id": ""}, "missing_detection_id"),
        ({"plan_id": ""}, "missing_plan_id"),
        ({"intended_quantity": -1}, "invalid_intended_quantity"),
        (
            {"entry_fills": [{"filled_at": "2026-08-24T14:36:00Z", "quantity": -1, "price": 100, "fee": 0}]},
            "invalid_entry_fill_quantity",
        ),
        (
            {"exit_fills": [{"filled_at": "2026-08-24T14:40:00Z", "quantity": -1, "price": 101, "fee": 0}]},
            "invalid_exit_fill_quantity",
        ),
        (
            {"exit_fills": [{"filled_at": "2026-08-24T14:35:30Z", "quantity": 1, "price": 101, "fee": 0}]},
            "exit_before_available_entry",
        ),
        ({"side": "buy"}, "forbidden_order_field"),
        ({"submit_order": True}, "forbidden_order_field"),
        ({"notes": {"action": "submit"}}, "forbidden_order_field"),
        ({"execution_enabled": True}, "execution_enabled_must_be_false"),
        ({"can_submit_orders": True}, "can_submit_orders_must_be_false"),
    ],
)
def test_fails_closed_on_invalid_or_execution_capable_input(overrides: dict, message: str) -> None:
    with pytest.raises(ValueError, match=message):
        build_manual_observation(_payload(**overrides), expected_plan_hash=PLAN_HASH)


def test_rejects_entry_status_or_chronology_that_disagrees_with_fills() -> None:
    with pytest.raises(ValueError, match="entry_status_mismatch"):
        build_manual_observation(
            _payload(entry_status="filled", entry_fills=[], exit_fills=[]), expected_plan_hash=PLAN_HASH
        )
    with pytest.raises(ValueError, match="fill_after_observation"):
        build_manual_observation(
            _payload(observed_at="2026-08-24T14:50:00Z"), expected_plan_hash=PLAN_HASH
        )


def test_short_partial_exit_uses_directional_slippage_and_allocated_fees() -> None:
    row = build_manual_observation(
        _payload(
            observation_id="manual-SPY-short",
            direction="short",
            intended_stop_price=101.0,
            entry_fills=[
                {"filled_at": "2026-08-24T14:36:00Z", "quantity": 10, "price": 99.9, "fee": 1.0}
            ],
            exit_fills=[
                {
                    "filled_at": "2026-08-24T15:00:00Z",
                    "quantity": 4,
                    "price": 99.0,
                    "reference_price": 98.98,
                    "spread_bps": 2.0,
                    "fee": 0.4,
                }
            ],
        ),
        expected_plan_hash=PLAN_HASH,
    )

    assert row["position_status"] == "partial_exit"
    assert row["entry_slippage_bps"] == pytest.approx(10.0)
    assert row["exit_fills"][0]["slippage_bps"] > 0
    assert row["realized_gross_pnl"] == pytest.approx(3.6)
    assert row["realized_net_pnl"] == pytest.approx(2.8)
    assert row["realized_net_r"] == pytest.approx(0.7)


def test_pnl_multiplier_supports_contract_observations_without_distorting_r() -> None:
    row = build_manual_observation(
        _payload(observation_id="manual-SPY-option", pnl_multiplier=100),
        expected_plan_hash=PLAN_HASH,
    )

    assert row["pnl_multiplier"] == 100
    assert row["realized_gross_pnl"] == pytest.approx(1030.0)
    assert row["realized_net_pnl"] == pytest.approx(1028.0)
    assert row["realized_net_r"] == pytest.approx(1.028)


def test_append_is_idempotent_and_observation_id_is_immutable(tmp_path: Path) -> None:
    ledger = tmp_path / "manual.jsonl"
    row = build_manual_observation(_payload(), expected_plan_hash=PLAN_HASH)

    first = append_manual_observation(row, path=ledger, expected_plan_hash=PLAN_HASH)
    duplicate = append_manual_observation(row, path=ledger, expected_plan_hash=PLAN_HASH)

    assert first == {"recorded": True, "duplicate": False, "observation_id": row["observation_id"]}
    assert duplicate == {"recorded": False, "duplicate": True, "observation_id": row["observation_id"]}
    assert len(read_observations(ledger)) == 1

    changed = {**row, "entry_spread_bps": 99.0}
    with pytest.raises(ValueError, match="immutable_observation_conflict"):
        append_manual_observation(changed, path=ledger, expected_plan_hash=PLAN_HASH)


def test_report_surfaces_followups_source_labels_and_freshness(tmp_path: Path) -> None:
    ledger = tmp_path / "manual.jsonl"
    closed = build_manual_observation(_payload(), expected_plan_hash=PLAN_HASH)
    partial = build_manual_observation(
        _payload(
            observation_id="manual-SPY-partial",
            entry_status="partial",
            source_label="manual_csv_import",
            source_as_of="2026-08-24T12:00:00Z",
            entry_fills=[{"filled_at": "2026-08-24T14:36:00Z", "quantity": 4, "price": 100.05, "fee": 0.4}],
            exit_fills=[],
        ),
        expected_plan_hash=PLAN_HASH,
    )
    unfilled = build_manual_observation(
        _payload(
            observation_id="manual-SPY-unfilled",
            entry_status="unfilled",
            source_as_of="2026-08-24T15:20:00Z",
            observed_at="2026-08-24T15:20:00Z",
            entry_fills=[],
            exit_fills=[],
        ),
        expected_plan_hash=PLAN_HASH,
    )
    for row in (closed, partial, unfilled):
        append_manual_observation(row, path=ledger, expected_plan_hash=PLAN_HASH)

    report = generate_execution_quality_report(
        read_observations(ledger),
        now=datetime(2026, 8, 24, 15, 17, tzinfo=timezone.utc),
        freshness_sla_minutes=60,
    )

    assert report["summary"] == {
        "observation_count": 3,
        "filled_count": 1,
        "partial_count": 1,
        "unfilled_count": 1,
        "closed_count": 1,
        "open_count": 1,
        "missing_followup_count": 1,
    }
    assert report["source_labels"] == ["kenny_manual_trade_review", "manual_csv_import"]
    assert report["status"] == "followup_required"
    freshness = {row["observation_id"]: row["freshness"] for row in report["observations"]}
    assert freshness["manual-SPY-cisd-20260824-01"] == "fresh"
    assert freshness["manual-SPY-partial"] == "stale"
    assert freshness["manual-SPY-unfilled"] == "clock_skew"
    assert report["execution_enabled"] is False
    assert report["can_submit_orders"] is False


def test_reader_fails_closed_on_corrupt_jsonl(tmp_path: Path) -> None:
    ledger = tmp_path / "manual.jsonl"
    ledger.write_text(json.dumps({"ok": True}) + "\nnot-json\n", encoding="utf-8")
    with pytest.raises(ValueError, match="invalid_jsonl"):
        read_observations(ledger)

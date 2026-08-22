from __future__ import annotations

from datetime import date

import pandas as pd

from scripts.bottom_reversal_forward_tracker import build_report, resolve_plan


def _plan() -> dict:
    return {
        "signal_id": "test-plan",
        "symbol": "TEST",
        "signal_date": "2026-08-10",
        "entry_trigger": 100.0,
        "invalidation": 95.0,
        "target_2r": 110.0,
        "planned_risk": 5.0,
        "status": "armed",
    }


def _bars(rows: list[tuple[str, float, float, float, float]]) -> pd.DataFrame:
    return pd.DataFrame(
        [{"open": o, "high": h, "low": l, "close": c} for _, o, h, l, c in rows],
        index=pd.to_datetime([day for day, *_ in rows]),
    )


def test_target_is_resolved_after_next_session_trigger_with_friction() -> None:
    frame = _bars(
        [
            ("2026-08-10", 98.0, 99.0, 97.0, 98.0),
            ("2026-08-11", 99.0, 103.0, 98.0, 102.0),
            ("2026-08-12", 103.0, 111.0, 102.0, 110.0),
        ]
    )
    row = resolve_plan(_plan(), frame, as_of=date(2026, 8, 13))
    assert row["status"] == "resolved"
    assert row["exit_reason"] == "target_2r"
    assert row["gross_r"] == 2.0
    assert row["net_r"] < row["gross_r"]


def test_same_bar_target_and_stop_is_conservatively_a_loss() -> None:
    frame = _bars(
        [
            ("2026-08-10", 98.0, 99.0, 97.0, 98.0),
            ("2026-08-11", 99.0, 111.0, 94.0, 102.0),
        ]
    )
    row = resolve_plan(_plan(), frame, as_of=date(2026, 8, 12))
    assert row["exit_reason"] == "stop_first"
    assert row["net_r"] < -1.0


def test_extended_gap_is_skipped_instead_of_chased() -> None:
    frame = _bars(
        [
            ("2026-08-10", 98.0, 99.0, 97.0, 98.0),
            ("2026-08-11", 103.0, 106.0, 102.0, 105.0),
        ]
    )
    row = resolve_plan(_plan(), frame, as_of=date(2026, 8, 12))
    assert row["status"] == "skipped_gap_extension"
    assert row["trade_counted"] is False


def test_tracker_registers_plan_but_cannot_enable_execution() -> None:
    investigator = {
        "generated_at": "2026-08-10T22:00:00Z",
        "armed_next_session": [
            {
                "symbol": "TEST",
                "as_of": "2026-08-10",
                "next_session_plan": {
                    "signal_id": "test-plan",
                    "entry_trigger": 100.0,
                    "invalidation": 95.0,
                    "target_2r": 110.0,
                },
            }
        ],
    }
    frame = _bars([("2026-08-10", 98.0, 99.0, 97.0, 98.0)])
    report, state = build_report(
        investigator,
        state={"schema_version": 1, "plans": {}},
        frames={"TEST": frame},
        as_of=date(2026, 8, 11),
    )
    assert "test-plan" in state["plans"]
    assert report["live_capital_gate"]["status"] == "blocked"
    assert report["execution_enabled"] is False
    assert report["can_submit_orders"] is False
    assert report["orders_submitted"] == 0

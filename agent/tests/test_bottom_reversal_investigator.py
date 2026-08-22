from __future__ import annotations

from datetime import date

import pandas as pd

from scripts.bottom_reversal_investigator import build_report, evaluate_symbol


def _frame(*, confirm: bool = True) -> pd.DataFrame:
    index = pd.bdate_range("2026-03-30", periods=103)
    closes = [100.0 + position * 0.03 for position in range(98)] + [92.0, 80.0, 82.0, 84.0, 88.0 if confirm else 83.0]
    rows = []
    for position, close in enumerate(closes):
        high = close + 1.0
        low = close - 1.0
        volume = 2_000_000.0
        if position == 99:
            low = 76.0
            high = 83.0
            volume = 4_000_000.0
        if position == 102 and confirm:
            high = 89.0
            low = 83.5
            volume = 2_600_000.0
        rows.append({"open": close - 0.5, "high": high, "low": low, "close": close, "volume": volume})
    return pd.DataFrame(rows, index=index)


def _spy(frame: pd.DataFrame) -> pd.DataFrame:
    values = [500.0 + position * 0.1 for position in range(len(frame))]
    return pd.DataFrame(
        {
            "open": values,
            "high": [value + 1.0 for value in values],
            "low": [value - 1.0 for value in values],
            "close": values,
            "volume": [10_000_000.0] * len(values),
        },
        index=frame.index,
    )


def test_capitulation_requires_later_demand_confirmation_before_arming() -> None:
    frame = _frame(confirm=True)
    row = evaluate_symbol("TEST", frame, _spy(frame))
    assert row["stage"] == "armed_next_session"
    assert row["capitulation_date"] is not None
    assert row["next_session_plan"]["entry_trigger"] > row["next_session_plan"]["invalidation"]
    assert row["paper_consumable"] is False
    assert row["execution_enabled"] is False
    assert row["can_submit_orders"] is False


def test_oversold_or_capitulation_alone_does_not_create_entry() -> None:
    frame = _frame(confirm=False)
    row = evaluate_symbol("TEST", frame, _spy(frame))
    assert row["stage"] == "capitulation_watch"
    assert row["next_session_plan"]["status"] == "not_armed"
    assert "demand_confirmation_not_complete" in row["blockers"]


def test_report_has_no_live_authority_or_invented_probability() -> None:
    frame = _frame(confirm=True)
    report = build_report(
        symbols=("SPY", "TEST"),
        as_of=date(2026, 8, 20),
        frames={"SPY": _spy(frame), "TEST": frame},
    )
    assert report["execution_enabled"] is False
    assert report["can_submit_orders"] is False
    assert report["orders_submitted"] == 0
    assert report["success_probability"] is None
    assert report["live_capital_gate"]["status"] == "blocked"


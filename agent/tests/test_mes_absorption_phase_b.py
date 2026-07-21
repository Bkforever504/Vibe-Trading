from __future__ import annotations

import pandas as pd

from research import mes_absorption_phase_b as lab


def test_long_and_short_pay_the_spread_and_commission() -> None:
    long_pnl = lab.trade_pnl(
        direction=1, entry_bid=100.00, entry_ask=100.25,
        exit_bid=101.00, exit_ask=101.25, stress=False,
    )
    short_pnl = lab.trade_pnl(
        direction=-1, entry_bid=101.00, entry_ask=101.25,
        exit_bid=100.00, exit_ask=100.25, stress=False,
    )
    assert long_pnl == short_pnl == 1.27


def test_stress_adds_two_ticks_and_double_commission() -> None:
    base = lab.trade_pnl(
        direction=1, entry_bid=100.00, entry_ask=100.25,
        exit_bid=101.00, exit_ask=101.25, stress=False,
    )
    stress = lab.trade_pnl(
        direction=1, entry_bid=100.00, entry_ask=100.25,
        exit_bid=101.00, exit_ask=101.25, stress=True,
    )
    assert round(base - stress, 2) == 4.98


def test_non_overlapping_selector_limits_each_session() -> None:
    times = pd.to_datetime([
        "2025-10-01 10:00", "2025-10-01 10:01", "2025-10-01 10:05",
        "2025-10-01 10:10", "2025-10-01 10:15",
    ])
    candidates = pd.DataFrame({"session_date": ["2025-10-01"] * 5, "signal_ts": times})
    selected = lab.select_non_overlapping(candidates)
    assert selected["signal_ts"].tolist() == [times[0], times[2], times[3]]


def test_pass_gate_is_conservative() -> None:
    base = {"trades": 30, "expectancy": 1.0, "profit_factor": 1.20}
    stress = {"expectancy": 0.01}
    assert lab.passes(base, stress, 30)
    assert not lab.passes({**base, "trades": 29}, stress, 30)
    assert not lab.passes(base, {"expectancy": 0.0}, 30)


def test_empty_fill_preserves_metric_columns() -> None:
    empty = pd.DataFrame(columns=["session_date", "signal_ts"])
    filled = lab.fill_signals(None, empty)
    assert list(filled["base_pnl"]) == []
    assert list(filled["stress_pnl"]) == []

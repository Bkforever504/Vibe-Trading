from __future__ import annotations

from datetime import date

import pandas as pd

from scripts import daily_stock_screener as screener


def test_fixed_liquid_universe_includes_semiconductor_gap_candidate() -> None:
    assert "SMCI" in screener.SCREENER_UNIVERSE
    assert screener.SECTOR_ETF["SMCI"] == "SMH"


def _frame(multiplier: float = 1.0, periods: int = 320) -> pd.DataFrame:
    index = pd.bdate_range("2024-01-02", periods=periods)
    values = [100.0 * multiplier]
    for i in range(1, periods):
        values.append(values[-1] * (0.995 if i % 3 == 0 else 1.004))
    close = pd.Series(values, index=index)
    return pd.DataFrame({
        "open": close * 0.999,
        "high": close * 1.01,
        "low": close * 0.99,
        "close": close,
        "volume": 5_000_000.0,
    })


def test_completed_bars_excludes_report_date() -> None:
    frame = _frame(periods=260)
    report_date = frame.index[-1].date()
    completed = screener.completed_bars(frame, report_date)
    assert completed.index[-1].date() < report_date
    assert len(completed) == len(frame) - 1


def test_screen_requires_liquidity_even_with_perfect_trend() -> None:
    frame = _frame()
    frame["volume"] = 1_000.0
    row = screener.screen_symbol("TEST", frame, frame["close"])
    assert row["long_eligible"] is False
    assert row["status"] == "blocked"
    assert "average_dollar_volume_below_minimum" in row["blockers"]


def test_build_report_is_read_only_and_directional() -> None:
    spy = _frame(multiplier=1.0)
    qqq = _frame(multiplier=1.2)
    # Give QQQ stronger completed-bar momentum than SPY.
    values = [120.0]
    for i in range(1, len(qqq)):
        values.append(values[-1] * (0.995 if i % 3 == 0 else 1.005))
    qqq["close"] = pd.Series(values, index=qqq.index)
    qqq["open"] = qqq["close"] * 0.999
    qqq["high"] = qqq["close"] * 1.01
    qqq["low"] = qqq["close"] * 0.99
    as_of = (spy.index[-1] + pd.Timedelta(days=1)).date()
    report = screener.build_report(
        symbols=("SPY", "QQQ"),
        as_of=as_of,
        frames={"SPY": spy, "QQQ": qqq},
        vix_term={"regime": "contango", "vix_over_vix3m": 0.9},
    )
    qqq_row = next(row for row in report["rankings"] if row["symbol"] == "QQQ")
    assert report["status"] == "ok"
    assert report["execution_enabled"] is False
    assert report["can_submit_orders"] is False
    assert report["can_promote_symbols"] is False
    assert qqq_row["long_eligible"] is True
    assert report["data_cutoff"] == "completed_daily_bars_strictly_before_report_date"

from __future__ import annotations

import pandas as pd

from research import daily_stock_screener_lab as lab


def _frame(growth: float, periods: int = 320) -> pd.DataFrame:
    index = pd.bdate_range("2024-01-02", periods=periods)
    values = [100.0]
    for i in range(1, periods):
        values.append(values[-1] * (0.995 if i % 3 == 0 else growth))
    close = pd.Series(values, index=index)
    return pd.DataFrame({
        "open": close * 0.998,
        "high": close * 1.01,
        "low": close * 0.99,
        "close": close,
        "volume": 5_000_000.0,
    })


def test_feature_return_executes_after_signal_day() -> None:
    frame = _frame(1.0015)
    table = lab.feature_table(frame, frame["close"])
    day = frame.index[-2]
    expected = frame.loc[frame.index[-1], "close"] / frame.loc[frame.index[-1], "open"] - 1.0
    assert table.loc[day, "next_intraday_return"] == expected


def test_medium_term_returns_enter_after_signal_and_use_fixed_exit() -> None:
    frame = _frame(1.0015)
    table = lab.feature_table(frame, frame["close"])
    day = frame.index[-21]
    expected_5d = frame.loc[frame.index[-16], "close"] / frame.loc[frame.index[-20], "open"] - 1.0
    expected_20d = frame.loc[frame.index[-1], "close"] / frame.loc[frame.index[-20], "open"] - 1.0
    assert table.loc[day, "next_5d_return"] == expected_5d
    assert table.loc[day, "next_20d_return"] == expected_20d


def test_trade_builder_charges_cost_and_never_trades_spy() -> None:
    spy = _frame(1.0010)
    qqq = _frame(1.0050)
    trades = lab.build_trades({"SPY": spy, "QQQ": qqq}, "full_screen", cost=0.002)
    assert not trades.empty
    assert set(trades["symbol"]) == {"QQQ"}
    assert (trades["net_return"] < trades["gross_return"]).all()
    assert "spy_relative_excess_return" in trades


def test_medium_term_trade_dates_are_non_overlapping() -> None:
    spy = _frame(1.0010, periods=420)
    qqq = _frame(1.0050, periods=420)
    trades = lab.build_trades(
        {"SPY": spy, "QQQ": qqq},
        "full_screen",
        cost=0.002,
        holding_days=5,
        long_only=True,
        non_overlapping=True,
    )
    dates = pd.DatetimeIndex(trades["signal_date"].drop_duplicates().sort_values())
    source_positions = [spy.index.get_loc(day) for day in dates]
    assert trades["direction"].eq("long").all()
    assert all(right - left == 5 for left, right in zip(source_positions, source_positions[1:]))


def test_metrics_reports_spy_relative_edge() -> None:
    trades = pd.DataFrame({
        "signal_date": pd.to_datetime(["2025-01-02", "2025-01-03"]),
        "net_return": [0.01, 0.02],
        "spy_relative_excess_return": [0.003, 0.005],
    })
    result = lab.metrics(trades)
    assert result["mean_spy_relative_excess_pct"] == 0.4

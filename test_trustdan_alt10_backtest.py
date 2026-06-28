import pandas as pd

from research.trustdan_alt10_backtest import Alt10Config, run_alt10_on_ohlcv


def _ohlcv(closes: list[float]) -> pd.DataFrame:
    idx = pd.date_range("2024-01-01", periods=len(closes), freq="D")
    return pd.DataFrame(
        {
            "open": closes,
            "high": [price + 0.4 for price in closes],
            "low": [price - 0.4 for price in closes],
            "close": closes,
            "volume": [1_000_000] * len(closes),
        },
        index=idx,
    )


def test_alt10_scales_out_long_units_at_profit_targets():
    prices = [10, 10, 10, 11, 12, 13, 14, 15, 16]
    result = run_alt10_on_ohlcv(
        _ohlcv(prices),
        Alt10Config(
            entry_len=3,
            n_len=2,
            stop_n=2.0,
            trail_len=3,
            trail_n=4.0,
            add_step_n=0.5,
            max_units=4,
            risk_pct=1.0,
            target1_n=0.75,
            target2_n=1.5,
            target3_n=2.25,
            allow_short=False,
        ),
    )

    target_trades = [trade for trade in result.closed_legs if trade.reason.startswith("target")]
    assert result.metrics.trade_count >= 3
    assert len(target_trades) >= 3
    assert all(trade.pnl_pct > 0 for trade in target_trades)
    assert result.equity_curve.iloc[-1] > 1.0


def test_alt10_can_short_breakdowns_and_records_profitable_short_targets():
    prices = [20, 20, 20, 19, 18, 17, 16, 15, 14]
    result = run_alt10_on_ohlcv(
        _ohlcv(prices),
        Alt10Config(
            entry_len=3,
            n_len=2,
            stop_n=2.0,
            trail_len=3,
            trail_n=4.0,
            add_step_n=0.5,
            max_units=4,
            risk_pct=1.0,
            target1_n=0.75,
            target2_n=1.5,
            target3_n=2.25,
            allow_long=False,
        ),
    )

    target_trades = [trade for trade in result.closed_legs if trade.reason.startswith("target")]
    assert len(target_trades) >= 3
    assert all(trade.side == -1 for trade in target_trades)
    assert all(trade.pnl_pct > 0 for trade in target_trades)

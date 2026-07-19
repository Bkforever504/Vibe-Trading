import numpy as np
import pandas as pd

from research import public_bot_replication_lab as lab


def test_ema_cross_uses_public_20_60_tolerance_rule() -> None:
    close = pd.Series([100.0] * 70 + [150.0] * 20)
    signal = lab.ema_cross_signal(close)
    assert signal.iloc[0] == 0
    assert signal.iloc[-1] == 1


def test_donchian_waits_for_prior_range_then_exits_on_prior_low() -> None:
    index = pd.date_range("2020-01-01", periods=8, freq="D")
    frame = pd.DataFrame({
        "high": [10, 11, 12, 13, 14, 16, 15, 14],
        "low": [9, 9, 10, 11, 12, 14, 13, 8],
        "close": [9.5, 10, 11, 12, 13, 15.5, 14, 8.5],
    }, index=index)
    signal = lab.donchian_signal(frame, entry=3, exit=2)
    assert signal.iloc[5] == 1
    assert signal.iloc[-1] == 0


def test_portfolio_returns_delays_signal_and_charges_turnover() -> None:
    index = pd.date_range("2020-01-01", periods=5, freq="D")
    close = pd.DataFrame({"SPY": [100, 101, 102, 103, 104]}, index=index)
    weights = pd.DataFrame({"SPY": [0, 1, 1, 1, 1]}, index=index)
    returns, execution = lab.portfolio_returns(close, weights, cost_bps=10)
    assert returns.iloc[1] == 0
    assert returns.iloc[2] == 0
    assert returns.iloc[3] > 0  # signal at day 1 first participates after the full-bar delay
    expected_day_3 = close.pct_change().iloc[3, 0] - 0.001
    assert abs(returns.iloc[3] - expected_day_3) < 1e-12
    assert execution["total_turnover"] == 1.0


def test_bootstrap_is_deterministic() -> None:
    values = pd.Series(np.tile([0.01, -0.005, 0.002], 50))
    first = lab.block_bootstrap_total_return(values, block=10, samples=100, seed=7)
    second = lab.block_bootstrap_total_return(values, block=10, samples=100, seed=7)
    assert first == second

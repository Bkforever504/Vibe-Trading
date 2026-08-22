import pandas as pd
import pytest

from research.pyquant_strategy_family_lab import (
    _scheduled_rank_weights,
    asset_class_trend_weights,
    smooth_momentum_proxy_weights,
    strategy_returns,
)


def _prices(rows: int = 260) -> pd.DataFrame:
    index = pd.bdate_range("2024-01-02", periods=rows)
    return pd.DataFrame({
        "UP": [100.0 + i for i in range(rows)],
        "DOWN": [400.0 - i for i in range(rows)],
    }, index=index)


def test_rank_weights_send_negative_momentum_assets_to_cash():
    closes = _prices()
    weights = _scheduled_rank_weights(closes, lookback=252, top_n=2, rebalance_days=5)

    assert weights.iloc[-1]["UP"] == 1.0
    assert weights.iloc[-1]["DOWN"] == 0.0


def test_returns_lag_new_weights_one_trading_day():
    index = pd.bdate_range("2026-01-02", periods=3)
    closes = pd.DataFrame({"A": [100.0, 110.0, 121.0]}, index=index)
    weights = pd.DataFrame({"A": [1.0, 1.0, 1.0]}, index=index)

    returns = strategy_returns(closes, weights, cost_per_notional=0.0)

    assert returns.iloc[0] == 0.0
    assert returns.iloc[1] == pytest.approx(0.1)


def test_turnover_cost_is_charged_on_execution_day():
    index = pd.bdate_range("2026-01-02", periods=3)
    closes = pd.DataFrame({"A": [100.0, 100.0, 100.0]}, index=index)
    weights = pd.DataFrame({"A": [0.0, 1.0, 1.0]}, index=index)

    returns = strategy_returns(closes, weights, cost_per_notional=0.001)

    assert returns.iloc[1] == 0.0
    assert returns.iloc[2] == -0.001


def test_trend_weights_only_hold_assets_above_200_day_average():
    closes = _prices(210)
    weights = asset_class_trend_weights(closes)

    assert weights.iloc[-1]["UP"] == 1.0
    assert weights.iloc[-1]["DOWN"] == 0.0


def test_smooth_momentum_prefers_persistent_winner_over_single_jump():
    index = pd.bdate_range("2024-01-02", periods=280)
    smooth = pd.Series([100.0 * (1.0012 ** i) for i in range(len(index))], index=index)
    jumpy = pd.Series(100.0, index=index)
    jumpy.iloc[80:] = 125.0
    closes = pd.DataFrame({"SMOOTH": smooth, "JUMPY": jumpy})

    weights = smooth_momentum_proxy_weights(
        closes,
        lookback=252,
        skip_recent=21,
        top_n=1,
        shortlist_multiple=2,
    )

    assert weights.iloc[-1]["SMOOTH"] == 1.0
    assert weights.iloc[-1]["JUMPY"] == 0.0


def test_smooth_momentum_validates_horizon_configuration():
    closes = _prices()

    with pytest.raises(ValueError, match="lookback"):
        smooth_momentum_proxy_weights(closes, lookback=21, skip_recent=21)

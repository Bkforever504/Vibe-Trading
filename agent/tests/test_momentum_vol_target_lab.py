from __future__ import annotations

import pandas as pd

from research.momentum_vol_target_lab import VolTargetConfig, lagged_vol_exposure


def test_exposure_is_capped_and_nonnegative() -> None:
    returns = pd.Series([0.01, -0.01] * 40, index=pd.date_range("2026-01-01", periods=80))
    exposure = lagged_vol_exposure(
        returns,
        VolTargetConfig(target_vol=0.50, vol_lookback=20, max_exposure=0.75),
    )

    assert exposure.min() >= 0.0
    assert exposure.max() <= 0.75


def test_current_return_cannot_change_current_exposure() -> None:
    index = pd.date_range("2026-01-01", periods=80)
    original = pd.Series([0.005, -0.004] * 40, index=index)
    shocked = original.copy()
    shocked.iloc[-1] = -0.50
    config = VolTargetConfig(target_vol=0.10, vol_lookback=20)

    original_exposure = lagged_vol_exposure(original, config)
    shocked_exposure = lagged_vol_exposure(shocked, config)

    assert original_exposure.iloc[-1] == shocked_exposure.iloc[-1]

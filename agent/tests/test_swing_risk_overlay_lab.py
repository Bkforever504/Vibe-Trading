from __future__ import annotations

import pandas as pd
import pytest

from research.swing_risk_overlay_lab import (
    OVERLAYS,
    capped_inverse_vol_weights,
    exposure_for_overlay,
    point_in_time_features,
)


def test_inverse_volatility_weights_are_capped_and_sum_to_one() -> None:
    weights = capped_inverse_vol_weights([0.10, 0.20, 0.30, 0.40, 0.50])
    assert sum(weights) == pytest.approx(1.0)
    assert max(weights) <= 0.35 + 1e-12
    assert weights[0] > weights[-1]


def test_features_use_only_history_through_decision_position() -> None:
    close = list(range(100, 301)) + [1_000]
    frame = pd.DataFrame({"close": close})
    features = point_in_time_features(frame, 200)
    changed_future = frame.copy()
    changed_future.loc[201, "close"] = -1_000
    assert point_in_time_features(changed_future, 200) == features


def test_combined_exposure_scales_breadth_and_virtual_drawdown() -> None:
    overlay = next(item for item in OVERLAYS if item.name == "combined_risk_overlay")
    context = {"breadth": 0.50, "spy_above_200": True}
    assert exposure_for_overlay(overlay, context, -0.05) == 0.5
    assert exposure_for_overlay(overlay, context, -0.10) == 0.25
    assert exposure_for_overlay(overlay, context, -0.16) == 0.0


def test_position_cap_leaves_residual_cash_when_too_few_assets_qualify() -> None:
    weights = capped_inverse_vol_weights([0.1, 0.2], cap=0.35)
    assert weights == [0.35, 0.35]
    assert sum(weights) == pytest.approx(0.70)

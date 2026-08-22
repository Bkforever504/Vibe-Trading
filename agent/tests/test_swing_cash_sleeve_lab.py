from __future__ import annotations

import pandas as pd
import pytest

from research.swing_cash_sleeve_lab import asset_period_return, blend_return


def test_blend_return_uses_residual_cash_without_leverage() -> None:
    value = blend_return(0.10, 0.02, 0.50, 10.0)
    assert value == pytest.approx(0.059)


def test_blend_return_rejects_leverage() -> None:
    with pytest.raises(ValueError):
        blend_return(0.10, 0.02, 1.01, 10.0)


def test_asset_period_return_enters_after_decision_date() -> None:
    index = pd.to_datetime(["2026-01-02", "2026-01-05", "2026-01-06"])
    frame = pd.DataFrame(
        {"open": [100.0, 110.0, 120.0], "close": [105.0, 115.0, 126.0]},
        index=index,
    )
    value = asset_period_return(frame, "2026-01-02", 2)
    assert value == pytest.approx(126.0 / 110.0 - 1.0)


def test_asset_period_return_rejects_incomplete_holding_window() -> None:
    index = pd.to_datetime(["2026-01-02", "2026-01-05"])
    frame = pd.DataFrame(
        {"open": [100.0, 110.0], "close": [105.0, 115.0]},
        index=index,
    )
    assert asset_period_return(frame, "2026-01-02", 2) == 0.0

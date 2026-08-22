from __future__ import annotations

import pandas as pd
import pytest

from research.mes_ofi_scalping_lab import add_point_in_time_zscore, executable_pnl


def test_executable_pnl_crosses_spread_and_charges_costs() -> None:
    base = executable_pnl(
        direction=1,
        entry_bid=100.00,
        entry_ask=100.25,
        exit_bid=100.50,
        exit_ask=100.75,
        stress=False,
    )
    stress = executable_pnl(
        direction=1,
        entry_bid=100.00,
        entry_ask=100.25,
        exit_bid=100.50,
        exit_ask=100.75,
        stress=True,
    )
    assert base == pytest.approx(0.25 * 5.0 - 2.48)
    assert stress == pytest.approx(0.25 * 5.0 - 4.96 - 2.50)


def test_zscore_uses_only_prior_buckets() -> None:
    frame = pd.DataFrame(
        {
            "session_date": ["2026-01-02"] * 62,
            "instrument_id": [1] * 62,
            "bucket_start": pd.date_range("2026-01-02 09:30", periods=62, freq="30s"),
            "ofi": list(range(60)) + [1000.0, 0.0],
        }
    )
    result = add_point_in_time_zscore(frame)
    expected = (1000.0 - pd.Series(range(60)).mean()) / pd.Series(range(60)).std(ddof=1)
    assert result.loc[60, "ofi_z"] == pytest.approx(expected)

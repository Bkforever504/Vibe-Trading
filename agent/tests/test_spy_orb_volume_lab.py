from __future__ import annotations

import pandas as pd

from research.spy_orb_volume_lab import adjusted_metrics, intraday_features


def test_time_bucket_relative_volume_uses_prior_days() -> None:
    rows, index = [], []
    for day in pd.date_range("2026-01-02", periods=25, freq="B"):
        for minute in ("09:30", "09:35", "09:40", "09:45", "09:50"):
            index.append(pd.Timestamp(f"{day.date()} {minute}", tz="America/New_York"))
            rows.append((100, 101, 99, 100.5, 1000 + day.day))
    frame = pd.DataFrame(rows, columns=["open", "high", "low", "close", "volume"], index=index)
    features = intraday_features(frame)
    assert features["bar_rvol20"].notna().sum() > 0
    assert features["cumulative_rvol20"].notna().sum() > 0


def test_double_cost_reduces_expectancy() -> None:
    trade = {"entry": 100.0, "stop": 99.0, "net_r": 1.0}
    base = adjusted_metrics([trade])
    stressed = adjusted_metrics([trade], 1.0)
    assert stressed["expectancy_r"] < base["expectancy_r"]

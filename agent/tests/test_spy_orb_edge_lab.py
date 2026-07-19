from __future__ import annotations

import pandas as pd

from research.spy_orb_edge_lab import LabConfig, _passes, bps_metrics, metrics, replay_closing_momentum


BASE = {
    "direction": "long", "weekday": 0, "vwap_aligned": True, "gap_aligned": True,
    "trend_aligned": True, "relative_open_volume": 1.2, "range_atr": 0.1,
}


def test_confluence_filters_require_only_declared_inputs() -> None:
    assert _passes(("vwap", "gap", "trend", "rvol", "range_atr"), BASE, LabConfig())
    assert not _passes(("vwap",), {**BASE, "vwap_aligned": False}, LabConfig())
    assert not _passes(("gap",), {**BASE, "gap_aligned": False}, LabConfig())


def test_social_mwf_filter_is_explicit_challenger() -> None:
    assert _passes(("mwf",), BASE, LabConfig())
    assert not _passes(("mwf",), {**BASE, "weekday": 1}, LabConfig())


def test_metrics_use_r_multiples_and_drawdown() -> None:
    result = metrics([{"net_r": 1.5}, {"net_r": -1.0}, {"net_r": -0.5}])
    assert result["trades"] == 3
    assert result["expectancy_r"] == 0.0
    assert result["profit_factor"] == 1.0
    assert result["max_drawdown_r"] == 1.5


def test_closing_momentum_uses_first_half_hour_direction() -> None:
    rows = []
    index = []
    for day, closes in (("2026-07-20", (100.0, 100.0)), ("2026-07-21", (101.0, 102.0))):
        for timestamp, close in (("09:30", closes[0]), ("09:59", closes[0]), ("15:30", closes[0]), ("16:00", closes[1])):
            index.append(pd.Timestamp(f"{day} {timestamp}", tz="America/New_York"))
            rows.append((close, close, close, close, 1000))
    frame = pd.DataFrame(rows, columns=["open", "high", "low", "close", "volume"], index=index)
    trades = replay_closing_momentum(frame, slippage_bps_per_side=0)

    assert len(trades) == 1
    assert trades[0]["direction"] == "long"
    assert bps_metrics(trades)["expectancy_bps"] > 0

from __future__ import annotations

import pandas as pd

from scripts.rsi2_shadow_logger import compute_signal_from_ohlcv


def test_volume_candidate_flags_are_telemetry_only() -> None:
    index = pd.date_range("2025-01-01", periods=260, freq="B")
    close = pd.Series([100 + i * 0.1 for i in range(260)], index=index)
    frame = pd.DataFrame(
        {
            "open": close - 0.1,
            "high": close + 0.5,
            "low": close - 0.5,
            "close": close,
            "volume": [1_000_000] * 259 + [2_000_000],
        },
        index=index,
    )

    result = compute_signal_from_ohlcv(frame)
    volume = result["features"]["volume_research"]

    assert volume["telemetry_only"] is True
    assert volume["changes_signal"] is False
    assert volume["rvol20"] > 1
    assert volume["candidate_flags"]["rvol_ge_1"] is True

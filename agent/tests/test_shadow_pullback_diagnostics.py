from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from strategies.shadow_pullback_signal import BEST_CONFIG, build_bar_diagnostics
from strategies.topstep_prop_bot import Candle


def _candle(i: int, open_: float, high: float, low: float, close: float) -> Candle:
    return Candle(
        timestamp=datetime(2026, 6, 26, 9 + i, 30),
        open=open_,
        high=high,
        low=low,
        close=close,
        volume=1000 + i,
    )


def test_build_bar_diagnostics_logs_each_post_opening_range_bar() -> None:
    candles = [
        _candle(0, 20000, 20010, 19990, 20000),
        _candle(1, 20000, 20040, 19995, 20035),
        _candle(2, 20035, 20038, 20005, 20012),
        _candle(3, 20012, 20015, 19950, 19960),
    ]

    diagnostics = build_bar_diagnostics(
        candles,
        BEST_CONFIG,
        prior_close=19980,
        gap_side="buy",
        vix_value=18.5,
    )

    assert len(diagnostics) == 3
    assert diagnostics[0]["bar_idx"] == 1
    assert diagnostics[0]["long_breakout"] is True
    assert diagnostics[0]["gap_aligned"] is True
    assert diagnostics[0]["score"] >= 5
    assert "close above opening range high" in diagnostics[0]["reasons"]
    assert diagnostics[-1]["short_breakout"] is True
    assert diagnostics[-1]["gap_aligned"] is False

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from research.fibonacci_confluence_lab import _conditions, _trade_outcome


def test_corrected_stop_uses_stop_first_on_ambiguous_bar() -> None:
    future = pd.DataFrame([{"high": 102.0, "low": 98.0, "close": 100.5}])
    result = _trade_outcome(
        future,
        direction=1,
        entry=100.0,
        stop=99.0,
        target=101.0,
        cost_bps=0.0,
    )
    assert result is not None
    assert result["exit_reason"] == "stop_first"
    assert result["net_r"] == -1.0


def test_confluence_stages_are_strictly_nested() -> None:
    bar = pd.Series(
        {
            "open": 100.0,
            "close": 101.0,
            "ema20": 100.5,
            "ema50": 100.0,
            "ema20_slope": 0.2,
            "vwap": 100.4,
            "relative_volume": 1.3,
        }
    )
    previous = pd.Series({"close": 100.2})
    flags = _conditions(bar, previous, direction=1, level=100.6, relative_volume_minimum=1.2)
    assert all(flags.values())

    bar["relative_volume"] = 1.0
    flags = _conditions(bar, previous, direction=1, level=100.6, relative_volume_minimum=1.2)
    assert flags["fib_rejection_trend_vwap"] is True
    assert flags["fib_rejection_trend_vwap_volume"] is False

from __future__ import annotations

import sys
import importlib.util
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

STRATEGY_PATH = ROOT / "research" / "pine_strategy_lab" / "examples" / "qqq_225_ma_filter_python.py"


def _load_strategy():
    spec = importlib.util.spec_from_file_location("qqq_225_ma_filter_python", STRATEGY_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.strategy


def test_qqq_225_ma_filter_enters_only_after_price_above_sma() -> None:
    dates = pd.date_range("2026-01-01", periods=8, freq="D")
    close = pd.Series([10, 10, 10, 11, 12, 9, 13, 14], index=dates)
    ohlcv = pd.DataFrame(
        {
            "open": close,
            "high": close,
            "low": close,
            "close": close,
            "volume": 1000,
        },
        index=dates,
    )

    signals = _load_strategy()(ohlcv, sma_window=3)

    assert signals.tolist() == [0, 0, 0, 1, 1, 0, 1, 1]

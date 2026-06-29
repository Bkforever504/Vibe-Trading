from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _load_strategy(name: str):
    path = ROOT / "research" / "pine_strategy_lab" / "examples" / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.strategy


def _ohlcv(close: list[float], start: str = "2026-01-01") -> pd.DataFrame:
    idx = pd.date_range(start, periods=len(close), freq="D")
    s = pd.Series(close, index=idx, dtype=float)
    return pd.DataFrame({"open": s, "high": s + 1, "low": s - 1, "close": s, "volume": 1000}, index=idx)


def test_month_end_seasonal_marks_first_and_last_trading_days() -> None:
    strategy = _load_strategy("month_end_seasonal_python")
    df = _ohlcv([10] * 10, start="2026-01-26")

    signals = strategy(df, last_days=2, first_days=2)

    assert signals.iloc[0] == 1  # first observed trading day in January sample
    assert signals.iloc[4] == 1  # Jan 30, last trading day in this slice/month
    assert signals.iloc[5] == 1  # Feb 1, first day in month


def test_williams_r_exits_after_time_stop() -> None:
    strategy = _load_strategy("williams_r_oversold_python")
    close = pd.Series([10, 9, 8, 9, 10, 11, 12], index=pd.date_range("2026-01-01", periods=7, freq="D"))
    df = pd.DataFrame(
        {"open": close, "high": close, "low": close, "close": close, "volume": 1000},
        index=close.index,
    )

    signals = strategy(df, wr_window=2, entry_threshold=-80, exit_threshold=-20, max_hold=2, trend_window=0)

    assert 1 in signals.tolist()
    assert signals.iloc[-1] == 0


def test_rotation_requires_defensive_close_and_prefers_primary_when_stronger() -> None:
    strategy = _load_strategy("tqqq_gld_rotation_python")
    df = _ohlcv([10, 11, 12, 13, 14])
    df["defensive_close"] = [10, 10.1, 10.2, 10.3, 10.4]

    signals = strategy(df, lookback_days=2)

    assert signals.iloc[-1] == 1


def test_seasonal_macd_returns_aligned_signal_series() -> None:
    strategy = _load_strategy("seasonal_macd_best_months_python")
    df = _ohlcv(list(range(100, 150)), start="2025-10-01")

    signals = strategy(df, entry_month=10, exit_month=5)

    assert list(signals.index) == list(df.index)
    assert set(signals.unique()).issubset({0, 1})

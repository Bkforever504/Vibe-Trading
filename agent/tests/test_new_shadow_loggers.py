from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts import shadow_alerts
from scripts.smc_shadow_logger import compute_smc_signals
from scripts.ttm_squeeze_shadow_logger import _squeeze_signal, compute_squeeze
from scripts.wavetrend_shadow_logger import _wt_signal, compute_wavetrend


def _sample_ohlcv(rows: int = 80) -> pd.DataFrame:
    idx = pd.date_range("2026-01-01", periods=rows, freq="D")
    trend = np.linspace(100, 120, rows)
    wave = np.sin(np.linspace(0, 8, rows)) * 2.0
    close = trend + wave
    open_ = close - 0.35
    high = close + 1.0
    low = close - 1.0
    volume = np.linspace(1_000_000, 1_500_000, rows)
    return pd.DataFrame(
        {
            "open": open_,
            "high": high,
            "low": low,
            "close": close,
            "volume": volume,
        },
        index=idx,
    )


def test_ttm_squeeze_computes_state_and_signal() -> None:
    df = _sample_ohlcv()

    sqz = compute_squeeze(df)
    signal = _squeeze_signal(sqz)

    assert {"sqz_on", "sqz_off", "momentum"}.issubset(sqz.columns)
    assert signal["action"] in {"enter_long", "enter_short", "hold_long", "hold_short", "flat"}
    assert signal["sqz_state"] in {"on", "off", "none", "unknown"}


def test_wavetrend_computes_cross_state_and_signal() -> None:
    df = _sample_ohlcv()

    wt = compute_wavetrend(df)
    signal = _wt_signal(df, wt)

    assert {"wt1", "wt2", "cross_above", "cross_below"}.issubset(wt.columns)
    assert signal["action"] in {"enter_long", "enter_short", "hold_long", "hold_short", "flat"}
    assert signal["zone"] in {"oversold", "overbought", "neutral"}


def test_shadow_alerts_detect_primary_comparison_entry_actions() -> None:
    entry = {
        "date": "2026-06-30",
        "execution_mode": "shadow_only",
        "data_source": "alpaca",
        "primary": {"symbol": "QQQ", "action": "enter_short"},
    }

    assert shadow_alerts.should_alert(entry, prev=None) is True
    message = shadow_alerts.format_alert("WaveTrend", entry)

    assert "WaveTrend" in message
    assert "enter_short" in message
    assert "QQQ" in message


def test_smc_fallback_runs_without_external_package(monkeypatch) -> None:
    import scripts.smc_shadow_logger as smc_logger

    monkeypatch.setattr(
        smc_logger,
        "_import_smc",
        lambda: (_ for _ in ()).throw(ImportError("package unavailable")),
    )

    result = compute_smc_signals(_sample_ohlcv())

    assert result["engine"] == "basic_fallback"
    assert result["current_close"] > 0
    assert result["action"] in {"watching", "bullish_bos", "bearish_bos"}

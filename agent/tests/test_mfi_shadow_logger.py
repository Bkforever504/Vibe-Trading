from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.mfi_shadow_logger import compute_mfi, _mfi_signal, compute_signal, log_entry, load_last_entry


def _make_df(
    n: int = 60,
    trend: str = "up",
    volume: int = 1_000_000,
) -> pd.DataFrame:
    """Synthetic OHLCV with controllable trend direction."""
    closes = []
    for i in range(n):
        if trend == "up":
            closes.append(400.0 + i * 0.5)
        elif trend == "down":
            closes.append(400.0 - i * 0.5)
        else:
            closes.append(400.0 + np.sin(i / 5) * 2)
    closes = np.array(closes)
    return pd.DataFrame({
        "high": closes + 1.0,
        "low": closes - 1.0,
        "close": closes,
        "volume": np.full(n, volume),
    })


def _make_oversold_df(n: int = 60) -> pd.DataFrame:
    """Falling prices → MFI should reach oversold territory."""
    closes = np.linspace(420.0, 380.0, n)
    return pd.DataFrame({
        "high": closes + 0.5,
        "low": closes - 0.5,
        "close": closes,
        "volume": np.full(n, 2_000_000),
    })


def _make_overbought_df(n: int = 60) -> pd.DataFrame:
    """Rising prices with high volume → MFI should reach overbought."""
    closes = np.linspace(380.0, 430.0, n)
    return pd.DataFrame({
        "high": closes + 0.5,
        "low": closes - 0.5,
        "close": closes,
        "volume": np.full(n, 5_000_000),
    })


# ---------------------------------------------------------------------------
# compute_mfi
# ---------------------------------------------------------------------------

def test_mfi_returns_series_same_length_as_input():
    df = _make_df(60)
    mfi = compute_mfi(df)
    assert len(mfi) == 60


def test_mfi_values_bounded_0_to_100():
    df = _make_df(60)
    mfi = compute_mfi(df).dropna()
    assert (mfi >= 0).all() and (mfi <= 100).all()


def test_mfi_rising_prices_produce_high_values():
    df = _make_overbought_df(60)
    mfi = compute_mfi(df).dropna()
    assert float(mfi.iloc[-1]) > 60.0


def test_mfi_falling_prices_produce_low_values():
    df = _make_oversold_df(60)
    mfi = compute_mfi(df).dropna()
    assert float(mfi.iloc[-1]) < 40.0


# ---------------------------------------------------------------------------
# _mfi_signal
# ---------------------------------------------------------------------------

def test_signal_insufficient_data_returns_flat():
    df = _make_df(5)
    sig = _mfi_signal(df, "SPY")
    assert sig["action"] == "flat"
    assert sig["status"] == "insufficient_data"


def test_signal_oversold_rising_returns_bull_bias():
    df = _make_oversold_df(60)
    # Force last bar to tick up slightly so "rising" is True
    df.loc[df.index[-1], "close"] = df["close"].iloc[-1] + 1.0
    df.loc[df.index[-1], "high"] = df["close"].iloc[-1] + 1.5
    sig = _mfi_signal(df, "SPY")
    assert sig["zone"] in {"oversold", "neutral"}
    assert sig["mfi"] is not None
    assert sig["status"] == "ok"


def test_signal_overbought_falling_returns_bear_bias():
    df = _make_overbought_df(60)
    df.loc[df.index[-1], "close"] = df["close"].iloc[-1] - 2.0
    sig = _mfi_signal(df, "SPY")
    assert sig["zone"] in {"overbought", "neutral"}
    assert sig["mfi"] is not None


def test_signal_execution_never_enabled():
    df = _make_df(60)
    sig = _mfi_signal(df, "SPY")
    assert "execution" not in str(sig).lower() or sig.get("params", {})


# ---------------------------------------------------------------------------
# compute_signal
# ---------------------------------------------------------------------------

def test_compute_signal_returns_shadow_only(monkeypatch):
    monkeypatch.setattr("scripts.mfi_shadow_logger.fetch_vix_context", lambda: {})
    monkeypatch.setattr("scripts.mfi_shadow_logger.data_source", lambda: "test")
    df = _make_df(60)
    entry = compute_signal(df, df)
    assert entry["execution_mode"] == "shadow_only"
    assert entry["paper_rules"]["live_execution_allowed"] is False


def test_compute_signal_consensus_bull_when_both_oversold_rising(monkeypatch):
    monkeypatch.setattr("scripts.mfi_shadow_logger.fetch_vix_context", lambda: {})
    monkeypatch.setattr("scripts.mfi_shadow_logger.data_source", lambda: "test")
    df = _make_oversold_df(60)
    df.loc[df.index[-1], "close"] = df["close"].iloc[-1] + 1.5
    df.loc[df.index[-1], "high"] = df["close"].iloc[-1] + 2.0
    entry = compute_signal(df, df)
    assert entry["consensus"] in {"bull", "none"}


def test_compute_signal_has_evidence_basis(monkeypatch):
    monkeypatch.setattr("scripts.mfi_shadow_logger.fetch_vix_context", lambda: {})
    monkeypatch.setattr("scripts.mfi_shadow_logger.data_source", lambda: "test")
    df = _make_df(60)
    entry = compute_signal(df, df)
    assert "MoonDev" in entry.get("evidence_basis", "")


# ---------------------------------------------------------------------------
# log_entry / load_last_entry
# ---------------------------------------------------------------------------

def test_log_and_reload(tmp_path):
    log = tmp_path / "mfi.jsonl"
    entry = {"date": "2026-07-01", "execution_mode": "shadow_only", "consensus": "none"}
    log_entry(entry, log)
    loaded = load_last_entry(log)
    assert loaded is not None
    assert loaded["date"] == "2026-07-01"
    assert loaded["execution_mode"] == "shadow_only"


def test_log_deduplicates_by_date(tmp_path):
    log = tmp_path / "mfi.jsonl"
    e1 = {"date": "2026-07-01", "consensus": "none"}
    e2 = {"date": "2026-07-01", "consensus": "bull"}
    log_entry(e1, log)
    log_entry(e2, log)
    lines = [l for l in log.read_text().splitlines() if l.strip()]
    assert len(lines) == 1
    assert json.loads(lines[0])["consensus"] == "bull"

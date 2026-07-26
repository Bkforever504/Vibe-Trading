from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from research import green_day_htf_ltf_lab as lab


def _synthetic_session(n: int = 90, seed: int = 7) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    index = pd.date_range("2026-07-20 09:30", periods=n, freq="1min", tz="America/New_York")
    drift = np.linspace(0, 0.6, n)
    noise = rng.normal(0, 0.05, n).cumsum()
    close = 700 + drift + noise
    open_ = np.concatenate(([700.0], close[:-1]))
    high = np.maximum(open_, close) + 0.05
    low = np.minimum(open_, close) - 0.05
    volume = rng.integers(5_000, 20_000, n).astype(float)
    return pd.DataFrame(
        {"open": open_, "high": high, "low": low, "close": close, "volume": volume},
        index=index,
    )


def test_metrics_reports_ci_status_and_skips_none_rows() -> None:
    small = [{"v": 1.0}, {"v": -2.0}, {"v": None}]
    result = lab.metrics(small, "v")

    assert result["count"] == 2
    assert result["ci_status"] == "insufficient_n"
    assert result["block_bootstrap_ci95"] == [None, None]

    large = [{"v": float(v)} for v in np.random.default_rng(1).normal(0, 1, 40)]
    assert lab.metrics(large, "v")["ci_status"] == "ok"


def test_checkpoint_window_end() -> None:
    assert lab._checkpoint_window_end("10:30") == "11:29"
    assert lab._checkpoint_window_end("12:00") == "12:59"


def test_complete_window_is_parameterized() -> None:
    frame = _synthetic_session(n=120)  # 09:30 through 11:29

    assert lab._complete_window(frame, "11:29") is True
    assert lab._complete_window(frame, "13:44") is False
    assert lab._complete_session(frame) is False


def test_per_checkpoint_mode_admits_partial_sessions_and_withholds_1345_metric() -> None:
    # Session complete only through 11:29: eligible for the 10:30 checkpoint
    # in per_checkpoint mode, ineligible in full_1345 mode.
    frame = _synthetic_session(n=120)
    htf = {
        "daily": pd.Series(["bullish"], index=[pd.Timestamp("2026-07-17")]),
        "weekly": pd.Series(["bullish"], index=[pd.Timestamp("2026-07-17")]),
        "monthly": pd.Series(["bullish"], index=[pd.Timestamp("2026-06-30")]),
    }

    rows_full, coverage_full = lab.replay_spy(frame, htf, completeness="full_1345")
    rows_pc, coverage_pc = lab.replay_spy(frame, htf, completeness="per_checkpoint")

    assert rows_full == []
    assert coverage_full["complete_through_1345_sessions"] == 0
    assert coverage_pc["completeness_mode"] == "per_checkpoint"
    assert coverage_pc["per_checkpoint_eligible_sessions"]["10:30"] == 1
    assert coverage_pc["per_checkpoint_eligible_sessions"]["12:00"] == 0
    for row in rows_pc:
        assert row["return_to_1345_bps"] is None
        assert row["return_60m_bps"] is not None


def test_lab_indicators_match_production_flip_bot_math() -> None:
    from strategies import flip_bot

    frame = _synthetic_session(n=80)
    lab_work = lab.compute_indicators(frame)

    hist = frame.rename(
        columns={"open": "Open", "high": "High", "low": "Low", "close": "Close", "volume": "Volume"}
    )
    production = flip_bot._vwap_50ema_bull_signal(hist, "TEST")

    assert production is not None
    assert production["close"] == float(lab_work["close"].iloc[-1])
    assert abs(production["vwap"] - float(lab_work["vwap"].iloc[-1])) < 1e-9
    assert abs(production["ema50"] - float(lab_work["ema50"].iloc[-1])) < 1e-9
    lab_distance = (
        float(lab_work["close"].iloc[-1]) - float(lab_work["vwap"].iloc[-1])
    ) / float(lab_work["vwap"].iloc[-1])
    assert abs(production["vwap_distance"] - lab_distance) < 1e-12
    assert production["fresh_pullback_confirmed"] == lab.fresh_pullback(lab_work, "bull")


def test_options_reconstruction_uses_canonical_structure_direction() -> None:
    from scripts import lifecycle_normalizer as canon

    spread = canon.normalize_options_trade({"strategy": "put_spread", "status": "open"})
    recovered = canon.normalize_options_trade({"strategy": "recovered_mleg", "status": "open"})

    assert spread["direction"] == "bullish"
    assert recovered["direction"] == canon.UNKNOWN
    assert recovered["quarantined"] is True

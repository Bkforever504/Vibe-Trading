from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts import hurst_regime_scanner as hurst


def test_hurst_exponent_detects_persistent_series() -> None:
    closes = [100 + i * 0.03 + i * i * 0.001 for i in range(140)]

    value = hurst.hurst_exponent(closes)

    assert value is not None
    assert value >= hurst.TREND_THRESHOLD


def test_hurst_exponent_detects_mean_reverting_series() -> None:
    closes = [100 + (1 if i % 2 == 0 else -1) for i in range(140)]

    value = hurst.hurst_exponent(closes)

    assert value is not None
    assert value <= hurst.MEAN_REVERSION_THRESHOLD


def test_classify_hurst_thresholds() -> None:
    assert hurst.classify_hurst(0.56) == ("persistent_trend", "momentum_trend_family", 1.0)
    assert hurst.classify_hurst(0.44) == ("anti_persistent", "mean_reversion_family", -1.0)
    assert hurst.classify_hurst(0.50) == ("random_walk_zone", "stand_aside_or_confirm", 0.0)
    assert hurst.classify_hurst(None) == ("unavailable", "no_context", 0.0)


def test_aggregate_requires_two_votes_for_symbol_bias() -> None:
    report = hurst.aggregate([
        {"symbol": "SPY", "status": "ok", "hurst": 0.60, "bias": "momentum_trend_family"},
        {"symbol": "QQQ", "status": "ok", "hurst": 0.58, "bias": "momentum_trend_family"},
        {"symbol": "IWM", "status": "ok", "hurst": 0.50, "bias": "stand_aside_or_confirm"},
    ])

    assert report["status"] == "ok"
    assert report["bias"] == "momentum_trend_family"
    assert report["ok_symbols"] == 3


def test_aggregate_ignores_missing_hurst_values() -> None:
    report = hurst.aggregate([
        {"symbol": "SPY", "status": "ok", "hurst": 0.42, "bias": "mean_reversion_family"},
        {"symbol": "QQQ", "status": "ok", "hurst": None, "bias": "no_context"},
        {"symbol": "IWM", "status": "error", "bias": "no_context"},
    ])

    assert report["status"] == "ok"
    assert report["avg_hurst"] == 0.42
    assert report["ok_symbols"] == 1
    assert report["votes"] == {"mean_reversion_family": 1}

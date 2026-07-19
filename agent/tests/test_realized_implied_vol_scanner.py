from __future__ import annotations

import json
import math
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts import realized_implied_vol_scanner as rviv


def test_realized_vol_from_closes_matches_log_return_vol() -> None:
    closes = [100, 101, 99, 102, 103, 100, 104, 105, 103, 106, 108]

    rv = rviv.realized_vol_from_closes(closes, 10)

    returns = [math.log(cur / prev) for prev, cur in zip(closes, closes[1:])]
    mean = sum(returns) / len(returns)
    expected = math.sqrt(sum((ret - mean) ** 2 for ret in returns) / (len(returns) - 1)) * math.sqrt(252)
    assert rv is not None
    assert round(rv, 10) == round(expected, 10)


def test_classify_ratio_thresholds() -> None:
    assert rviv.classify_ratio(1.21) == ("realized_over_implied", "momentum_breakout", 1.0)
    assert rviv.classify_ratio(0.79) == ("implied_over_realized", "premium_mean_reversion", -1.0)
    assert rviv.classify_ratio(1.0) == ("balanced", "stand_aside_or_confirm", 0.0)
    assert rviv.classify_ratio(None) == ("unavailable", "no_context", 0.0)


def test_latest_ivr_for_day_extracts_symbol_scans(tmp_path: Path) -> None:
    path = tmp_path / "ivr.jsonl"
    path.write_text(
        json.dumps({"date": "2026-06-29", "scans": [{"symbol": "SPY", "atm_iv": 0.2}]}) + "\n"
        + json.dumps({"date": "2026-06-30", "scans": [{"symbol": "SPY", "atm_iv": 0.25}, {"symbol": "QQQ", "atm_iv": 0.3}]}) + "\n",
        encoding="utf-8",
    )

    result = rviv.latest_ivr_for_day("2026-06-30", path)

    assert result["SPY"]["atm_iv"] == 0.25
    assert result["QQQ"]["atm_iv"] == 0.3


def test_aggregate_requires_two_votes_for_symbol_bias() -> None:
    report = rviv.aggregate([
        {"symbol": "SPY", "status": "ok", "rv_iv_ratio": 1.3, "bias": "momentum_breakout", "score": 1},
        {"symbol": "QQQ", "status": "ok", "rv_iv_ratio": 1.25, "bias": "momentum_breakout", "score": 1},
        {"symbol": "IWM", "status": "ok", "rv_iv_ratio": 0.9, "bias": "stand_aside_or_confirm", "score": 0},
    ])

    assert report["status"] == "ok"
    assert report["bias"] == "momentum_breakout"
    assert report["regime"] == "balanced"


def test_aggregate_counts_only_usable_ratios_as_coverage() -> None:
    report = rviv.aggregate([
        {"symbol": "SPY", "status": "ok", "rv_iv_ratio": 1.3, "bias": "momentum_breakout", "score": 1},
        {"symbol": "QQQ", "status": "ok", "rv_iv_ratio": None, "bias": "no_context", "score": 0},
        {"symbol": "IWM", "status": "unavailable", "bias": "no_context", "score": 0},
    ])

    assert report["status"] == "ok"
    assert report["avg_ratio"] == 1.3
    assert report["ok_symbols"] == 1
    assert report["status_ok_symbols"] == 2
    assert report["votes"] == {"momentum_breakout": 1}


def test_aggregate_is_unavailable_when_no_usable_ratios() -> None:
    report = rviv.aggregate([
        {"symbol": "SPY", "status": "ok", "rv_iv_ratio": None, "bias": "no_context", "score": 0},
        {"symbol": "QQQ", "status": "error", "bias": "no_context", "score": 0},
    ])

    assert report["status"] == "unavailable"
    assert report["avg_ratio"] is None
    assert report["ok_symbols"] == 0
    assert report["status_ok_symbols"] == 1

from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from unittest.mock import patch
import sys

import pytest

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.missed_banger_review import (
    BANGER_MOVE_PCT,
    _classify_miss,
    _deep_scan_universe,
    _flip_shadow_seen,
    _liquidity_qualified,
    build_report,
    load_last_report,
    log_report,
)

TODAY = date(2026, 7, 4)


# ---------------------------------------------------------------------------
# _classify_miss
# ---------------------------------------------------------------------------

def test_not_a_banger_when_small_move():
    verdict = _classify_miss("SPY", True, True, False, 2.0)
    assert verdict == "not_a_banger"

def test_bot_covered_when_saw_setup():
    verdict = _classify_miss("SPY", True, True, True, 8.0)
    assert verdict == "bot_covered"

def test_universe_gap_when_not_in_deep_scan():
    verdict = _classify_miss("XYZ", False, False, False, 10.0)
    assert verdict == "universe_gap"

def test_liquidity_blocked_when_in_universe_but_not_eligible():
    verdict = _classify_miss("RDDT", True, False, False, 12.0)
    assert verdict == "liquidity_gate_blocked"

def test_setup_not_triggered_when_qualified_but_no_setup():
    verdict = _classify_miss("IWM", True, True, False, 7.0)
    assert verdict == "setup_not_triggered"

def test_no_move_data_is_not_banger():
    verdict = _classify_miss("UNK", True, True, False, None)
    assert verdict == "not_a_banger"


# ---------------------------------------------------------------------------
# data loaders
# ---------------------------------------------------------------------------

def test_deep_scan_universe_extracts_symbols():
    rows = [
        {"scans": [{"symbol": "SPY", "status": "ok"}, {"symbol": "QQQ", "status": "ok"}]},
        {"candidates": ["IWM", "NVDA"]},
    ]
    universe = _deep_scan_universe(rows)
    assert "SPY" in universe
    assert "QQQ" in universe
    assert "IWM" in universe

def test_liquidity_qualified_extracts_eligible():
    rows = [{"results": [
        {"symbol": "IWM", "flip_shadow_eligible": True},
        {"symbol": "META", "flip_shadow_eligible": False},
    ]}]
    eligible = _liquidity_qualified(rows)
    assert "IWM" in eligible
    assert "META" not in eligible

def test_flip_shadow_seen_extracts_symbols():
    rows = [
        {"symbol": "NVDA"},
        {"candidates": [{"symbol": "QQQ"}, {"symbol": "TSLA"}]},
    ]
    seen = _flip_shadow_seen(rows)
    assert "NVDA" in seen
    assert "QQQ" in seen


# ---------------------------------------------------------------------------
# build_report
# ---------------------------------------------------------------------------

def test_build_report_read_only(tmp_path):
    obs = [{"ticker": "SPY", "date": "2026-07-01", "source": "test", "mode": "context_only"}]
    obs_path = tmp_path / "social-arb-observations.json"
    obs_path.write_text(json.dumps(obs))

    with patch("scripts.missed_banger_review.SOCIAL_OBS_PATH", obs_path), \
         patch("scripts.missed_banger_review.DEEP_SCAN_LOG", tmp_path / "nope.jsonl"), \
         patch("scripts.missed_banger_review.LIQUIDITY_LOG", tmp_path / "nope2.jsonl"), \
         patch("scripts.missed_banger_review.FLIP_SHADOW_LOG", tmp_path / "nope3.jsonl"), \
         patch("scripts.missed_banger_review._fetch_one_day_move", return_value=8.5):
        report = build_report(TODAY)

    assert report["execution_mode"] == "read_only"
    assert report["summary"]["observations_reviewed"] == 1
    assert report["summary"]["bangers_found"] == 1
    assert report["summary"]["missed_bangers"] == 1
    assert report["missed_bangers"][0]["symbol"] == "SPY"
    assert report["missed_bangers"][0]["verdict"] == "universe_gap"


def test_build_report_bot_covered(tmp_path):
    obs = [{"ticker": "QQQ", "date": "2026-07-01", "source": "test", "mode": "context_only"}]
    obs_path = tmp_path / "obs.json"
    obs_path.write_text(json.dumps(obs))

    deep_log = tmp_path / "deep.jsonl"
    deep_log.write_text(json.dumps({"scans": [{"symbol": "QQQ"}]}) + "\n")
    liq_log = tmp_path / "liq.jsonl"
    liq_log.write_text(json.dumps({"results": [{"symbol": "QQQ", "flip_shadow_eligible": True}]}) + "\n")
    shadow_log = tmp_path / "shadow.jsonl"
    shadow_log.write_text(json.dumps({"symbol": "QQQ"}) + "\n")

    with patch("scripts.missed_banger_review.SOCIAL_OBS_PATH", obs_path), \
         patch("scripts.missed_banger_review.DEEP_SCAN_LOG", deep_log), \
         patch("scripts.missed_banger_review.LIQUIDITY_LOG", liq_log), \
         patch("scripts.missed_banger_review.FLIP_SHADOW_LOG", shadow_log), \
         patch("scripts.missed_banger_review._fetch_one_day_move", return_value=9.0):
        report = build_report(TODAY)

    assert report["summary"]["bot_covered"] == 1
    assert report["summary"]["missed_bangers"] == 0


# ---------------------------------------------------------------------------
# log / load
# ---------------------------------------------------------------------------

def test_log_and_reload(tmp_path):
    log = tmp_path / "mbr.jsonl"
    report = {"date": "2026-07-04", "execution_mode": "read_only", "summary": {}}
    log_report(report, log_path=log)
    loaded = load_last_report(log_path=log)
    assert loaded["date"] == "2026-07-04"

def test_log_deduplicates(tmp_path):
    log = tmp_path / "mbr.jsonl"
    log_report({"date": "2026-07-04", "summary": {"missed_bangers": 1}}, log_path=log)
    log_report({"date": "2026-07-04", "summary": {"missed_bangers": 0}}, log_path=log)
    lines = [l for l in log.read_text().splitlines() if l.strip()]
    assert len(lines) == 1
    assert json.loads(lines[0])["summary"]["missed_bangers"] == 0

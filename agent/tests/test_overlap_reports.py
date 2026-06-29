"""Tests for williams_r_rsi2_overlap_report and qqq_gld_momentum_overlap_report."""
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.williams_r_rsi2_overlap_report import _load_log as wr_load, analyze as wr_analyze
from scripts.qqq_gld_momentum_overlap_report import (
    _load_log as gld_load,
    _nearest_momentum_date,
    analyze as gld_analyze,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _wr_entry(date: str, in_position: bool, action: str = "") -> dict:
    if not action:
        action = "hold_long" if in_position else "flat"
    return {
        "date": date,
        "primary_setup": {"in_position": in_position, "action": action},
    }


def _rsi2_entry(date: str, in_position: bool, action: str = "") -> dict:
    if not action:
        action = "hold_long" if in_position else "flat"
    return {
        "date": date,
        "primary_setup": {"in_position": in_position, "action": action},
    }


def _qqq_gld_entry(date: str, selected: str, action: str = "") -> dict:
    if not action:
        action = f"hold_{selected.lower()}"
    return {"date": date, "selected": selected, "action": action}


def _mom_entry(date: str, holdings: list[str]) -> dict:
    return {"date": date, "holdings": holdings}


def _write_jsonl(path: Path, entries: list[dict]) -> None:
    path.write_text("".join(json.dumps(e) + "\n" for e in entries), encoding="utf-8")


# ---------------------------------------------------------------------------
# _load_log tests
# ---------------------------------------------------------------------------

def test_load_log_returns_empty_for_missing_file() -> None:
    path = Path("/nonexistent/path/log.jsonl")
    assert wr_load(path) == {}


def test_load_log_indexes_by_date() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        p = Path(tmp) / "test.jsonl"
        _write_jsonl(p, [
            _wr_entry("2026-01-02", True),
            _wr_entry("2026-01-03", False),
        ])
        log = wr_load(p)
        assert set(log) == {"2026-01-02", "2026-01-03"}
        assert log["2026-01-02"]["primary_setup"]["in_position"] is True


def test_load_log_last_entry_wins_on_duplicate_date() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        p = Path(tmp) / "test.jsonl"
        p.write_text(
            json.dumps({"date": "2026-01-02", "primary_setup": {"in_position": True, "action": "hold_long"}}) + "\n"
            + json.dumps({"date": "2026-01-02", "primary_setup": {"in_position": False, "action": "flat"}}) + "\n",
            encoding="utf-8",
        )
        log = wr_load(p)
        assert log["2026-01-02"]["primary_setup"]["in_position"] is False


def test_load_log_skips_malformed_lines() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        p = Path(tmp) / "test.jsonl"
        p.write_text(
            "not json\n"
            + json.dumps({"date": "2026-01-02", "primary_setup": {"in_position": False, "action": "flat"}}) + "\n",
            encoding="utf-8",
        )
        log = wr_load(p)
        assert len(log) == 1


# ---------------------------------------------------------------------------
# WR vs RSI-2 analysis tests
# ---------------------------------------------------------------------------

def test_wr_rsi2_both_in_same_day() -> None:
    wr = {"2026-01-02": _wr_entry("2026-01-02", True)}
    rsi2 = {"2026-01-02": _rsi2_entry("2026-01-02", True)}
    result = wr_analyze(wr, rsi2)
    assert result["both_in"] == ["2026-01-02"]
    assert result["only_wr_in"] == []
    assert result["only_rsi2_in"] == []


def test_wr_rsi2_only_wr_in() -> None:
    wr = {"2026-01-02": _wr_entry("2026-01-02", True)}
    rsi2 = {"2026-01-02": _rsi2_entry("2026-01-02", False)}
    result = wr_analyze(wr, rsi2)
    assert result["only_wr_in"] == ["2026-01-02"]
    assert result["both_in"] == []


def test_wr_rsi2_only_rsi2_in() -> None:
    wr = {"2026-01-02": _wr_entry("2026-01-02", False)}
    rsi2 = {"2026-01-02": _rsi2_entry("2026-01-02", True)}
    result = wr_analyze(wr, rsi2)
    assert result["only_rsi2_in"] == ["2026-01-02"]
    assert result["both_in"] == []


def test_wr_rsi2_jaccard_both_in() -> None:
    wr = {"2026-01-02": _wr_entry("2026-01-02", True)}
    rsi2 = {"2026-01-02": _rsi2_entry("2026-01-02", True)}
    result = wr_analyze(wr, rsi2)
    assert result["jaccard"] == 1.0


def test_wr_rsi2_jaccard_no_overlap() -> None:
    wr = {
        "2026-01-02": _wr_entry("2026-01-02", True),
        "2026-01-03": _wr_entry("2026-01-03", False),
    }
    rsi2 = {
        "2026-01-02": _rsi2_entry("2026-01-02", False),
        "2026-01-03": _rsi2_entry("2026-01-03", True),
    }
    result = wr_analyze(wr, rsi2)
    assert result["jaccard"] == 0.0
    assert result["both_in"] == []


def test_wr_rsi2_entry_signal_detection() -> None:
    wr = {
        "2026-01-02": _wr_entry("2026-01-02", True, action="enter_long"),
        "2026-01-03": _wr_entry("2026-01-03", True, action="hold_long"),
    }
    rsi2 = {
        "2026-01-02": _rsi2_entry("2026-01-02", True),
        "2026-01-03": _rsi2_entry("2026-01-03", False),
    }
    result = wr_analyze(wr, rsi2)
    assert result["wr_entry_dates"] == ["2026-01-02"]
    assert result["wr_entries_with_rsi2_active"] == ["2026-01-02"]


def test_wr_rsi2_empty_logs() -> None:
    result = wr_analyze({}, {})
    assert result["jaccard"] == 0.0
    assert result["shared_dates"] == 0


# ---------------------------------------------------------------------------
# QQQ/GLD vs Momentum analysis tests
# ---------------------------------------------------------------------------

def test_nearest_momentum_date_exact_match() -> None:
    assert _nearest_momentum_date("2026-01-05", ["2026-01-05", "2026-01-04"]) == "2026-01-05"


def test_nearest_momentum_date_picks_most_recent_before() -> None:
    assert _nearest_momentum_date("2026-01-06", ["2026-01-05", "2026-01-03"]) == "2026-01-05"


def test_nearest_momentum_date_none_available() -> None:
    assert _nearest_momentum_date("2026-01-01", ["2026-01-05"]) is None


def test_qqq_gld_agree_both_qqq() -> None:
    qqq_gld = {"2026-01-05": _qqq_gld_entry("2026-01-05", "QQQ")}
    momentum = {"2026-01-05": _mom_entry("2026-01-05", ["QQQ", "XLK"])}
    result = gld_analyze(qqq_gld, momentum)
    assert len(result["both_qqq"]) == 1
    assert result["total_agree"] == 1
    assert result["total_diverge"] == 0
    assert result["pct_agree"] == 100.0


def test_qqq_gld_diverge_qqq_selected_but_not_in_momentum() -> None:
    qqq_gld = {"2026-01-05": _qqq_gld_entry("2026-01-05", "QQQ")}
    momentum = {"2026-01-05": _mom_entry("2026-01-05", ["XLK", "IWM"])}
    result = gld_analyze(qqq_gld, momentum)
    assert len(result["qqq_gld_qqq_only"]) == 1
    assert result["total_diverge"] == 1
    assert result["total_agree"] == 0


def test_qqq_gld_agree_both_gld() -> None:
    qqq_gld = {"2026-01-05": _qqq_gld_entry("2026-01-05", "GLD")}
    momentum = {"2026-01-05": _mom_entry("2026-01-05", ["GLD", "TLT"])}
    result = gld_analyze(qqq_gld, momentum)
    assert len(result["both_gld"]) == 1
    assert result["total_agree"] == 1


def test_qqq_gld_uses_nearest_momentum_date() -> None:
    qqq_gld = {"2026-01-06": _qqq_gld_entry("2026-01-06", "QQQ")}
    momentum = {"2026-01-05": _mom_entry("2026-01-05", ["QQQ", "SPY"])}
    result = gld_analyze(qqq_gld, momentum)
    assert result["rows"][0]["momentum_date"] == "2026-01-05"
    assert result["rows"][0]["agree"] is True


def test_qqq_gld_no_momentum_date_available() -> None:
    qqq_gld = {"2026-01-02": _qqq_gld_entry("2026-01-02", "QQQ")}
    momentum = {"2026-01-05": _mom_entry("2026-01-05", ["QQQ", "SPY"])}
    result = gld_analyze(qqq_gld, momentum)
    assert result["rows"][0]["momentum_date"] is None
    assert result["rows"][0]["agree"] is False
    assert result["total_shared"] == 0
    assert result["unmatched_rows"] == result["rows"]


def test_qqq_gld_empty_logs() -> None:
    result = gld_analyze({}, {})
    assert result["total_shared"] == 0
    assert result["pct_agree"] == 0.0


def test_qqq_gld_jaccard_full_agreement() -> None:
    qqq_gld = {"2026-01-05": _qqq_gld_entry("2026-01-05", "QQQ")}
    momentum = {"2026-01-05": _mom_entry("2026-01-05", ["QQQ", "SPY"])}
    result = gld_analyze(qqq_gld, momentum)
    assert result["jaccard_qqq"] == 1.0


def test_qqq_gld_jaccard_no_qqq_agreement() -> None:
    qqq_gld = {"2026-01-05": _qqq_gld_entry("2026-01-05", "GLD")}
    momentum = {"2026-01-05": _mom_entry("2026-01-05", ["QQQ", "SPY"])}
    result = gld_analyze(qqq_gld, momentum)
    assert result["jaccard_qqq"] == 0.0

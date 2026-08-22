"""Tests for research/options_exit_policy_lab.py."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from research import options_exit_policy_lab as lab


def _write_lifecycles(tmp_path: Path, rows: list[dict]) -> Path:
    p = tmp_path / "shadow.jsonl"
    p.write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")
    return p


def _life(lid: str, date: str, entry: float, marks: list[dict]) -> list[dict]:
    base = {
        "lifecycle_id": lid, "date": date, "symbol": "SPY", "right": "CALL",
        "strategy": "0dte", "day_type": "trend",
    }
    rows = [{**base, "event_type": "shadow_entry", "scanned_at": marks[0]["ts"],
             "entry_price_est": entry, "selection_bid": entry, "mark_price": entry,
             "return_pct_at_mark": 0.0, "best_return_pct_at_mark": 0.0,
             "mark_reason": ""}]
    for m in marks:
        rows.append({**base, "event_type": "shadow_mark", "scanned_at": m["ts"],
                     "selection_bid": m["bid"], "mark_price": m["bid"],
                     "return_pct_at_mark": (m["bid"] - entry) / entry * 100.0,
                     "best_return_pct_at_mark": max((mm["bid"] - entry) / entry * 100.0 for mm in marks[:marks.index(m)+1]),
                     "mark_reason": m.get("reason", "lifecycle_mark")})
    rows.append({**base, "event_type": "shadow_exit", "scanned_at": marks[-1]["ts"],
                 "selection_bid": marks[-1]["bid"], "mark_price": marks[-1]["bid"],
                 "return_pct_at_mark": (marks[-1]["bid"] - entry) / entry * 100.0,
                 "best_return_pct_at_mark": max((mm["bid"] - entry) / entry * 100.0 for mm in marks),
                 "mark_reason": marks[-1].get("reason", "hard_close")})
    return rows


def test_load_lifecycles_requires_entry_and_exit(tmp_path):
    rows = [{"lifecycle_id": "a", "event_type": "shadow_entry", "entry_price_est": 1.0,
             "selection_bid": 1.0, "mark_price": 1.0, "scanned_at": "2026-01-01T09:30:00"}]
    p = _write_lifecycles(tmp_path, rows)
    assert lab.load_lifecycles(p) == []


def test_target_hit_before_stop(tmp_path):
    rows = _life("a", "2026-01-01", 1.0, [
        {"ts": "2026-01-01T09:30:00", "bid": 1.0},
        {"ts": "2026-01-01T09:35:00", "bid": 1.60},  # +60% -> hits target 50
    ])
    p = _write_lifecycles(tmp_path, rows)
    lives = lab.load_lifecycles(p)
    assert len(lives) == 1
    ret, reason = lab._policy_fixed(lives[0], stop_pct=30.0, target_pct=50.0)
    assert ret == pytest.approx(60.0, abs=0.1)
    assert reason.startswith("target")


def test_stop_hit_before_target(tmp_path):
    rows = _life("a", "2026-01-01", 1.0, [
        {"ts": "2026-01-01T09:30:00", "bid": 1.0},
        {"ts": "2026-01-01T09:35:00", "bid": 0.60},  # -40% -> hits stop 30
    ])
    p = _write_lifecycles(tmp_path, rows)
    lives = lab.load_lifecycles(p)
    ret, reason = lab._policy_fixed(lives[0], stop_pct=30.0, target_pct=50.0)
    assert ret == pytest.approx(-40.0, abs=0.1)
    assert reason.startswith("stop")


def test_ratchet_locks_after_giveback(tmp_path):
    rows = _life("a", "2026-01-01", 1.0, [
        {"ts": "2026-01-01T09:30:00", "bid": 1.0},
        {"ts": "2026-01-01T09:35:00", "bid": 1.40},   # +40% arms
        {"ts": "2026-01-01T09:40:00", "bid": 1.25},   # +25% > +40-15 -> should NOT lock yet
        {"ts": "2026-01-01T09:45:00", "bid": 1.20},   # +20% -> below peak-15 -> locks
    ])
    p = _write_lifecycles(tmp_path, rows)
    lives = lab.load_lifecycles(p)
    ret, reason = lab._policy_ratchet(lives[0], arm_pct=25.0, giveback_pct=15.0, stop_pct=30.0)
    # locks at bid 1.25 -> +25%
    assert ret == pytest.approx(25.0, abs=0.1)
    assert reason.startswith("ratchet_lock")


def test_review_gate_fails_insufficient_samples():
    report = {"sample_size": 10, "unique_dates": 5,
              "post_fee": {"expectancy_pct": 5.0},
              "doubled_cost": {"expectancy_pct": 3.0},
              "top5_removed_post_fee": {"expectancy_pct": 1.0}}
    verdict = lab.review_gate_verdict(report)
    assert verdict["passed"] is False
    assert any("insufficient_samples" in c for c in verdict["failed_checks"])
    assert any("insufficient_dates" in c for c in verdict["failed_checks"])


def test_review_gate_fails_negative_expectancy():
    report = {"sample_size": 100, "unique_dates": 25,
              "post_fee": {"expectancy_pct": -1.0},
              "doubled_cost": {"expectancy_pct": -2.0},
              "top5_removed_post_fee": {"expectancy_pct": -5.0}}
    verdict = lab.review_gate_verdict(report)
    assert verdict["passed"] is False
    assert "post_fee_expectancy_not_positive" in verdict["failed_checks"]
    assert "doubled_cost_expectancy_not_positive" in verdict["failed_checks"]


def test_review_gate_passes_when_all_thresholds_met():
    report = {"sample_size": 200, "unique_dates": 40,
              "post_fee": {"expectancy_pct": 5.0},
              "doubled_cost": {"expectancy_pct": 3.0},
              "top5_removed_post_fee": {"expectancy_pct": 1.5}}
    verdict = lab.review_gate_verdict(report)
    assert verdict["passed"] is True
    assert verdict["failed_checks"] == []


def test_report_read_only_flags(tmp_path):
    rows = _life("a", "2026-01-01", 1.0, [
        {"ts": "2026-01-01T09:30:00", "bid": 1.0},
        {"ts": "2026-01-01T09:35:00", "bid": 1.2, "reason": "hard_close"},
    ])
    p = _write_lifecycles(tmp_path, rows)
    report = lab.build_report(candidates_path=p)
    assert report["execution_enabled"] is False
    assert report["can_submit_orders"] is False
    assert report["automatic_parameter_changes"] is False
    assert report["promotion_authority"] == "shadow_challenger_only"

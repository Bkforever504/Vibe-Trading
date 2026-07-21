from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts import build_active_trial_manifest as builder


def test_delayed_trial_uses_first_later_ask_not_signal_ask(monkeypatch, tmp_path: Path) -> None:
    shadow = tmp_path / "shadow.jsonl"
    base = {
        "schema_version": 3,
        "data_quality": "current_session_lifecycle",
        "execution_mode": "shadow_only",
        "lifecycle_id": "2026-07-21|SPY|CALL|0dte|09:30",
        "date": "2026-07-21",
        "symbol": "SPY",
        "right": "CALL",
        "strategy": "0dte",
        "episode_bucket_et": "09:30",
        "option_symbol": "SPY-CALL",
        "feature_snapshot": {
            "orb_entry_pattern": "breakout_retest",
            "orb_retest_status": "retest_confirmed_fresh",
            "orb_retest_age_bars": 4,
        },
    }
    entry = {**base, "action": "enter_shadow", "scanned_at": "2026-07-21T13:45:00Z", "selection_ask": 1.0, "selection_bid": 0.9}
    delayed = {**base, "action": "hold_shadow", "scanned_at": "2026-07-21T13:46:00Z", "selection_ask": 1.2, "selection_bid": 1.1}
    shadow.write_text("\n".join(json.dumps(row) for row in (entry, delayed)) + "\n", encoding="utf-8")
    monkeypatch.setattr(builder.accelerated, "_shadow_trades", lambda _path: [{
        "lifecycle_id": base["lifecycle_id"], "executable_exit_bid": 1.3,
    }])

    trials = builder._fresh_delayed_trials(shadow)

    assert len(trials) == 1
    assert trials[0]["return"] == pytest.approx(1.3 / 1.2 - 1)
    assert trials[0]["cost_2x_return"] == pytest.approx((1.3 / 1.2 - 1) - (1.2 - 1.1) / 1.2)
    assert trials[0]["entry_seen_at"] < trials[0]["delayed_entry_seen_at"]


def test_manifest_partitions_first_30_validation_then_forward(monkeypatch, tmp_path: Path) -> None:
    plan = tmp_path / "plan.json"
    plan.write_text(json.dumps({
        "plan_id": "test",
        "created_before_oos_start": True,
        "oos_start": "2026-01-01",
        "oos_end": "2026-12-31",
    }), encoding="utf-8")
    trials = [
        {
            "lifecycle_id": f"id-{pos}", "date": f"2026-02-{(pos % 28) + 1:02d}",
            "entry_seen_at": f"2026-02-01T10:{pos:02d}:00Z",
            "delayed_entry_seen_at": f"2026-02-01T10:{pos:02d}:30Z",
            "symbol": "SPY", "right": "CALL", "session": "opening", "retest_age_bars": 4,
            "return": 0.01, "cost_2x_return": 0.008, "cost_3x_return": 0.006,
        }
        for pos in range(60)
    ]
    monkeypatch.setattr(builder, "_fresh_delayed_trials", lambda _path: trials)

    manifest, report = builder.build_manifest(plan, tmp_path / "shadow.jsonl")

    assert len(manifest["returns"]["final"]) == 30
    assert len(manifest["returns"]["forward"]) == 30
    assert manifest["execution_delay_bars"] == 1
    assert manifest["timestamp_audit"]["passed"] is True
    assert manifest["backtest_forward_parity"]["passed"] is False
    assert report["ready_for_adversarial_pass"] is True


def test_current_manifest_excludes_consumed_pre_oos_context(monkeypatch, tmp_path: Path) -> None:
    plan = tmp_path / "plan.json"
    plan.write_text(json.dumps({
        "plan_id": "test", "created_before_oos_start": True,
        "oos_start": "2026-07-21", "oos_end": "2026-10-16",
    }), encoding="utf-8")
    monkeypatch.setattr(builder, "_fresh_delayed_trials", lambda _path: [{
        "lifecycle_id": "old", "date": "2026-07-17", "entry_seen_at": "a",
        "delayed_entry_seen_at": "b", "symbol": "SPY", "right": "CALL",
        "session": "opening", "retest_age_bars": 4, "return": 0.10,
        "cost_2x_return": 0.08, "cost_3x_return": 0.06,
    }])

    manifest, report = builder.build_manifest(plan, tmp_path / "shadow.jsonl")

    assert manifest["returns"]["final"] == []
    assert manifest["returns"]["forward"] == []
    assert report["consumed_context"]["completed_count"] == 1
    assert report["ready_for_adversarial_pass"] is False

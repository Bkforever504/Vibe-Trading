from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from scripts import accelerated_bot_learning_report as report


ROOT = Path(__file__).resolve().parents[2]


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    path.write_text("\n".join(json.dumps(row) for row in rows) + "\n", encoding="utf-8")


def test_joint_report_records_failures_for_both_learning_tracks(tmp_path: Path) -> None:
    shadow = tmp_path / "shadow.jsonl"
    base = {
        "schema_version": 3,
        "data_quality": "current_session_lifecycle",
        "execution_mode": "shadow_only",
        "date": "2026-07-14",
        "symbol": "SPY",
        "right": "CALL",
        "strategy": "0dte",
        "option_symbol": "SPY260714C00750000",
        "lifecycle_id": "episode-1",
        "episode_bucket_et": "10:00",
        "learner_tracks": ["flip_entry_exit", "options_directional_contract_selection"],
        "feature_snapshot": {"above_vwap": True},
        "entry_reasoning": {"spread_cents": 4, "catalyst": "test"},
    }
    _write_jsonl(shadow, [
        {**base, "scanned_at": "2026-07-14T15:00:00Z", "event_type": "shadow_entry", "entry_price_est": 1.0},
        {**base, "scanned_at": "2026-07-14T15:30:00Z", "event_type": "shadow_exit", "entry_price_est": 0.7, "mark_reason": "stop_30_hit"},
    ])
    flip = tmp_path / "flip.json"
    flip.write_text(json.dumps([{"status": "closed", "pnl": -30}]), encoding="utf-8")
    options = tmp_path / "options.json"
    options.write_text(json.dumps({"trades": [{
        "status": "closed", "net_credit": 0.59, "closing_filled_avg_price": 0.39, "qty": 2,
    }]}), encoding="utf-8")
    edge_trials = tmp_path / "edge-trials.json"
    edge_trials.write_text(json.dumps({"trial_count": 0}), encoding="utf-8")
    forward_plan = tmp_path / "forward-plan.json"
    forward_plan.write_text(json.dumps({
        "plan_id": "test-plan",
        "status": "preregistered_not_started",
        "oos_start": "2026-07-15",
        "oos_end": "2026-07-28",
        "primary_metric": "geometric_mean_return",
    }), encoding="utf-8")

    built = report.build_report(
        shadow_path=shadow,
        flip_path=flip,
        options_path=options,
        edge_trial_report_path=edge_trials,
        forward_plan_path=forward_plan,
        day="2026-07-14",
    )

    assert built["execution_enabled"] is False
    assert built["can_submit_orders"] is False
    assert built["throughput"]["today_completed_count"] == 1
    assert built["compounding_evidence"]["portfolio_compounding_proven"] is False
    assert "no_preregistered_edge_trials_recorded" in built["compounding_evidence"]["blockers"]
    assert built["flip_bot"]["actual_paper"]["net_return_points"] == -30
    assert built["options_bot"]["actual_defined_risk_paper"]["net_return_points"] == 40
    assert len(built["actual_trade_postmortems"]) == 2
    actual_failure = next(case for case in built["failure_memory"] if case["source"] == "actual_paper_trade")
    shadow_failure = next(case for case in built["failure_memory"] if case["source"] == "accelerated_directional_shadow")
    assert actual_failure["pnl_dollars"] == -30
    assert actual_failure["diagnosis"]
    assert shadow_failure["feature_snapshot"] == {"above_vwap": True}
    assert shadow_failure["next_action"] == "nominate_shadow_trial_only"


def test_report_is_directly_executable_from_repo_root() -> None:
    result = subprocess.run(
        [sys.executable, "scripts/accelerated_bot_learning_report.py", "--help"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert "accelerated Flip/options learning memory" in result.stdout

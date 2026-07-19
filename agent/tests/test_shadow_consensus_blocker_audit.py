from __future__ import annotations

import json
from pathlib import Path

from scripts import shadow_consensus_blocker_audit as audit


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(json.dumps(row) for row in rows) + "\n", encoding="utf-8")


def test_blocker_audit_flags_stale_symbol_sample_blocker(tmp_path: Path) -> None:
    decisions = tmp_path / "flip-decisions.jsonl"
    consensus = tmp_path / "shadow-consensus-gate.json"
    shadow = tmp_path / "flip-shadow-pnl-evaluator.json"
    _write_jsonl(decisions, [{
        "symbol": "SPY",
        "strategy": "0dte",
        "reason": "shadow_consensus_block",
        "details": {"blockers": ["not_enough_shadow_samples"], "recommendation": "needs_review"},
        "ts": "2026-07-14T15:00:00Z",
    }])
    _write_json(consensus, {"decisions": []})
    _write_json(shadow, {
        "completed_count": 20,
        "by_symbol": {
            "SPY": {"completed_count": 8, "win_rate": 0.75, "expectancy_return_pct": 12.5}
        },
    })

    built = audit.build_report(decision_log=decisions, consensus_path=consensus, shadow_path=shadow)

    assert built["execution_enabled"] is False
    assert built["can_submit_orders"] is False
    assert built["blockers"][0]["blocker"] == "not_enough_shadow_samples"
    assert built["review_notes"][0]["issue"] == "historical_sample_blocker_now_resolved_by_later_evidence"
    assert built["review_notes"][0]["current_contradiction"] is False


def test_blocker_audit_flags_current_sample_contradiction(tmp_path: Path) -> None:
    decisions = tmp_path / "flip-decisions.jsonl"
    consensus = tmp_path / "shadow-consensus-gate.json"
    shadow = tmp_path / "flip-shadow-pnl-evaluator.json"
    _write_jsonl(decisions, [])
    _write_json(consensus, {
        "decisions": [{
            "symbol": "SPY",
            "recommendation": "needs_review",
            "blockers": ["not_enough_shadow_samples"],
        }],
    })
    _write_json(shadow, {
        "completed_count": 20,
        "by_symbol": {
            "SPY": {"completed_count": 8, "win_rate": 0.75, "expectancy_return_pct": 12.5}
        },
    })

    built = audit.build_report(decision_log=decisions, consensus_path=consensus, shadow_path=shadow)

    assert built["review_notes"][0]["issue"] == "current_blocker_seen_despite_symbol_completed_count_meeting_gate_minimum"
    assert built["review_notes"][0]["current_contradiction"] is True

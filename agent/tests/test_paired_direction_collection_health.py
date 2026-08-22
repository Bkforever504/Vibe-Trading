from __future__ import annotations

import json
from pathlib import Path

from scripts import paired_direction_collection_health as health


def _write(path, rows) -> None:
    path.write_text("\n".join(json.dumps(row) for row in rows) + "\n", encoding="utf-8")


def test_health_report_counts_atomic_resolved_pair(tmp_path) -> None:
    attempts = tmp_path / "attempts.jsonl"
    candidates = tmp_path / "candidates.jsonl"
    _write(attempts, [{
        "date": "2026-01-01",
        "symbol": "SPY",
        "decision_pair_id": "pair-1",
        "status": "accepted",
        "reason": "synchronized_pair_created",
    }])
    rows = []
    for role, right, option in (
        ("source_direction", "CALL", "call-1"),
        ("opposite_direction", "PUT", "put-1"),
    ):
        rows.extend([
            {
                "date": "2026-01-01", "decision_pair_id": "pair-1",
                "decision_lattice_role": role, "right": right,
                "option_symbol": option, "event_type": "shadow_entry",
                "decision_context_sha256": "a" * 64,
                "paired_direction_policy_spec_sha256": "b" * 64,
            },
            {
                "date": "2026-01-01", "decision_pair_id": "pair-1",
                "decision_lattice_role": role, "right": right,
                "option_symbol": option, "event_type": "shadow_exit",
            },
        ])
    _write(candidates, rows)

    report = health.build_report(attempts, candidates)

    assert report["status"] == "collecting"
    assert report["attempt_summary"]["accepted_rate"] == 1.0
    assert report["lifecycle_health"]["dual_entry_pairs"] == 1
    assert report["lifecycle_health"]["resolved_dual_pairs"] == 1
    assert report["lifecycle_health"]["orphan_pair_count"] == 0
    assert report["lifecycle_health"]["sealed_context_pairs"] == 1
    assert report["lifecycle_health"]["sealed_policy_spec_pairs"] == 1
    assert report["lifecycle_health"]["seal_mismatch_count"] == 0
    assert report["execution_enabled"] is False
    assert report["can_submit_orders"] is False


def test_health_report_flags_low_acceptance_and_orphan(tmp_path) -> None:
    attempts = tmp_path / "attempts.jsonl"
    candidates = tmp_path / "candidates.jsonl"
    attempt_rows = [
        {
            "date": "2026-01-01", "symbol": "SPY", "decision_pair_id": f"pair-{index}",
            "status": "accepted" if index == 0 else "rejected",
            "reason": "synchronized_pair_created" if index == 0 else "quote_too_stale",
        }
        for index in range(10)
    ]
    _write(attempts, attempt_rows)
    _write(candidates, [{
        "date": "2026-01-01",
        "decision_pair_id": "pair-0",
        "decision_lattice_role": "source_direction",
        "option_symbol": "call-1",
        "event_type": "shadow_entry",
    }])

    report = health.build_report(attempts, candidates)

    assert report["status"] == "degraded"
    assert "synchronized_pair_acceptance_rate_below_20pct" in report["blockers"]
    assert "orphan_pair_lifecycles_detected" in report["blockers"]
    assert report["attempt_summary"]["reason_counts"]["quote_too_stale"] == 9


def test_health_report_distinguishes_no_diagnostics(tmp_path) -> None:
    report = health.build_report(tmp_path / "missing-attempts", tmp_path / "missing-candidates")

    assert report["status"] == "no_attempts_recorded"
    assert report["automatic_parameter_changes"] is False


def test_nightly_runner_refreshes_collection_health() -> None:
    root = Path(__file__).resolve().parents[2]
    runner = (root / "scripts" / "run_flip_execution_challenger_report.ps1").read_text(encoding="utf-8")

    assert "python scripts\\paired_direction_collection_health.py" in runner

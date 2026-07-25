from __future__ import annotations

import json
from pathlib import Path

from scripts.self_learning_edge_loop import build_report, write_outputs


def _write(path: Path, value: dict) -> Path:
    path.write_text(json.dumps(value), encoding="utf-8")
    return path


def test_loop_deduplicates_events_and_nominates_repeated_patterns(tmp_path) -> None:
    learning = _write(tmp_path / "learning.json", {"failure_memory": []})
    watchdog = _write(tmp_path / "watchdog.json", {
        "alerts": [{"code": "setup_agnostic_gate_mismatch", "severity": "high"}],
        "setup_mismatch_examples": [
        {"ts": "a", "symbol": "SPY", "strategy": "0dte", "issues": ["wrong_direction_gate"]},
        {"ts": "b", "symbol": "SPY", "strategy": "0dte", "issues": ["wrong_direction_gate"]},
    ]})
    audit = _write(tmp_path / "audit.json", {"subjects": []})
    ledger = tmp_path / "ledger.jsonl"
    report_path = tmp_path / "report.json"
    log_path = tmp_path / "log.jsonl"

    report, new_rows = build_report(learning, watchdog, audit, ledger)
    write_outputs(report, new_rows, ledger, report_path, log_path)
    rerun, rerun_rows = build_report(learning, watchdog, audit, ledger)

    assert len(new_rows) == 2
    assert rerun_rows == []
    assert rerun["summary"]["repeated_pattern_count"] == 1
    assert rerun["promotion_blockers"] == ["unresolved_repeated_high_severity_mistakes"]
    assert rerun["shadow_challenger_nominations"] == []
    assert rerun["summary"]["regression_repair_count"] == 1
    assert rerun["regression_repairs"][0]["production_config_mutation_allowed"] is False


def test_decaying_watchdog_mistake_remains_memory_without_blocking(tmp_path) -> None:
    learning = _write(tmp_path / "learning.json", {"failure_memory": []})
    watchdog = _write(tmp_path / "watchdog.json", {
        "alerts": [{"code": "setup_agnostic_gate_mismatch", "severity": "decaying"}],
        "setup_mismatch_examples": [
            {"ts": "a", "symbol": "SPY", "strategy": "0dte", "issues": ["old_bug"]},
            {"ts": "b", "symbol": "SPY", "strategy": "0dte", "issues": ["old_bug"]},
        ],
    })
    audit = _write(tmp_path / "audit.json", {"subjects": []})

    report, _ = build_report(learning, watchdog, audit, tmp_path / "ledger.jsonl")

    assert report["repeated_patterns"][0]["severity"] == "decaying"
    assert report["shadow_challenger_nominations"] == []
    assert report["summary"]["historical_resolved_pattern_count"] == 1
    assert report["promotion_blockers"] == []


def test_shadow_losses_are_clustered_by_actionable_entry_context(tmp_path) -> None:
    failures = []
    for pos in range(2):
        failures.append({
            "source": "accelerated_directional_shadow",
            "lifecycle_id": f"loss-{pos}",
            "date": "2026-07-20",
            "symbol": "SPY",
            "strategy": "0dte",
            "right": "CALL",
            "episode_bucket_et": "13:30",
            "diagnosis": "Thesis failed before follow-through; test stricter entry confirmation for this feature/regime cluster.",
            "feature_snapshot": {
                "orb_entry_pattern": "raw_breakout",
                "orb_retest_status": "retest_stale",
                "expected_move_consumed_fraction": 0.8,
                "spread_cents_at_signal": 5,
                "above_vwap": False,
                "above_ema50": False,
                "ema50_sloping_up": False,
            },
        })
    learning = _write(tmp_path / "learning.json", {"failure_memory": failures})
    watchdog = _write(tmp_path / "watchdog.json", {"alerts": [], "setup_mismatch_examples": []})
    audit = _write(tmp_path / "audit.json", {"subjects": []})

    report, _ = build_report(learning, watchdog, audit, tmp_path / "ledger.jsonl")

    nomination = report["shadow_challenger_nominations"][0]
    assert nomination["supporting_occurrences"] == 2
    assert nomination["top_clusters"][0]["context"]["session"] == "late"
    assert nomination["top_clusters"][0]["context"]["trend_alignment"] == "unconfirmed"
    assert nomination["proposed_shadow_change"] == "require_fresh_orb_retest"
    assert nomination["minimum_forward_outcomes"] == 30


def test_orb_retest_contrast_keeps_small_positive_cohort_in_shadow(tmp_path, monkeypatch) -> None:
    trades = []
    for pos in range(6):
        trades.append({
            "date": f"2026-07-{pos + 1:02d}",
            "evidence_exit_return_pct": 10.0,
            "feature_snapshot": {
                "orb_entry_pattern": "breakout_retest",
                "orb_retest_status": "retest_confirmed_fresh",
            },
        })
    for pos in range(10):
        trades.append({
            "date": f"2026-06-{pos + 1:02d}",
            "evidence_exit_return_pct": -5.0,
            "feature_snapshot": {"orb_entry_pattern": "raw_breakout", "orb_retest_status": "retest_stale"},
        })
    monkeypatch.setattr("scripts.self_learning_edge_loop.accelerated._shadow_trades", lambda _path: trades)

    result = __import__("scripts.self_learning_edge_loop", fromlist=["_orb_retest_contrast"])._orb_retest_contrast(
        tmp_path / "shadow.jsonl"
    )

    assert result["fresh_minus_raw_expectancy_pct"] == 15.0
    assert result["evidence_gate_passed"] is False
    assert result["interpretation"] == "fresh_retest_leading_but_sample_insufficient"


def test_non_orb_credit_loss_gets_strategy_specific_challenger() -> None:
    loop = __import__("scripts.self_learning_edge_loop", fromlist=["_proposed_shadow_change"])
    assert (
        loop._proposed_shadow_change("stop at or inside -100% credit", {})
        == "compare_credit_spread_stop_timing_75_100_125pct"
    )
    assert (
        loop._proposed_shadow_change(
            "Thesis failed before follow-through; test stricter entry confirmation for this feature/regime cluster.",
            {"entry_pattern": "unknown", "retest_status": "unknown", "trend_alignment": "unconfirmed"},
        )
        == "require_directional_vwap_ema_alignment"
    )


def test_active_trial_lifecycle_requires_validation_then_later_forward() -> None:
    loop = __import__("scripts.self_learning_edge_loop", fromlist=["_active_trial_lifecycle"])
    audit = {"by_subject": {"fresh-orb-retest-options": {
        "score_out_of_10": 5.0,
        "passed": False,
        "failed_checks": ["forward_sample_sufficient"],
        "diagnostics": {"final_trade_count": 30, "forward_trade_count": 12},
    }}}

    result = loop._active_trial_lifecycle(audit)

    assert result["stage"] == "collecting_forward"
    assert result["validation_progress"] == "30/30"
    assert result["forward_progress"] == "12/30"
    assert result["automatic_promotion_allowed"] is False


def test_alpaca_execution_evidence_summarizes_real_fill_delay_and_slippage(tmp_path) -> None:
    loop = __import__("scripts.self_learning_edge_loop", fromlist=["_alpaca_execution_evidence"])
    state = tmp_path / "flip-trades.json"
    state.write_text(json.dumps([
        {
            "entry_fill_confirmed": True,
            "entry_execution_evidence": {
                "entry_evidence_gate": "passed_fresh_orb_retest",
                "submit_to_fill_seconds": 2.5,
                "fill_vs_submit_ask_pct": 0.95,
                "fill_vs_signal_ask_pct": 6.0,
            },
        },
        {"entry_fill_confirmed": False},
    ]), encoding="utf-8")

    result = loop._alpaca_execution_evidence(state)

    assert result["trade_count"] == 2
    assert result["execution_evidence_count"] == 1
    assert result["missing_execution_evidence_count"] == 1
    assert result["fresh_orb_retest_fill_count"] == 1
    assert result["average_submit_to_fill_seconds"] == 2.5
    assert result["average_fill_vs_signal_ask_pct"] == 6.0
    assert result["automatic_parameter_changes_allowed"] is False

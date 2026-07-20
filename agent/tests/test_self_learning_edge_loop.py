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
    assert rerun["shadow_challenger_nominations"][0]["production_config_mutation_allowed"] is False


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
    assert report["promotion_blockers"] == []

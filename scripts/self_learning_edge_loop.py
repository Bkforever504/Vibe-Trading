#!/usr/bin/env python3
"""Deduplicated cross-bot mistake memory and shadow-only challenger loop."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parent.parent
VIBE_HOME = Path.home() / ".vibe-trading"
REPORT_DIR = VIBE_HOME / "reports"
LEARNING_PATH = REPORT_DIR / "accelerated-bot-learning.json"
WATCHDOG_PATH = REPORT_DIR / "bot-behavior-regression-watchdog.json"
AUDIT_PATH = REPORT_DIR / "adversarial-strategy-audit.json"
LEDGER_PATH = ROOT / "data" / "self_learning_mistake_ledger.jsonl"
REPORT_PATH = REPORT_DIR / "self-learning-edge-loop.json"
LOG_PATH = ROOT / "data" / "self_learning_edge_loop_log.jsonl"


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            value = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            rows.append(value)
    return rows


def _stable_id(payload: dict[str, Any]) -> str:
    raw = json.dumps(payload, separators=(",", ":"), sort_keys=True)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:20]


def _mistakes(learning: dict[str, Any], watchdog: dict[str, Any], audit: dict[str, Any]) -> list[dict[str, Any]]:
    rows = []
    for failure in learning.get("failure_memory") or []:
        if not isinstance(failure, dict):
            continue
        identity = {
            "source": failure.get("source"),
            "trade_id": failure.get("trade_id") or failure.get("lifecycle_id"),
            "date": failure.get("date"),
            "symbol": failure.get("symbol"),
        }
        lesson = str(failure.get("risk_lesson") or failure.get("diagnosis") or "unclassified_trade_failure")
        pattern = {
            "source": failure.get("source"),
            "bot": failure.get("bot"),
            "strategy": failure.get("strategy"),
            "lesson": lesson,
        }
        rows.append({**identity, "event_id": _stable_id(identity), "pattern_id": _stable_id(pattern),
                     "lesson": lesson, "next_action": failure.get("next_action"), "severity": "review"})
    mismatch_alert = next(
        (
            alert for alert in watchdog.get("alerts") or []
            if isinstance(alert, dict) and alert.get("code") == "setup_agnostic_gate_mismatch"
        ),
        {},
    )
    mismatch_severity = str(mismatch_alert.get("severity") or "high")
    for example in watchdog.get("setup_mismatch_examples") or []:
        if not isinstance(example, dict):
            continue
        for issue in example.get("issues") or []:
            identity = {"source": "behavior_watchdog", "ts": example.get("ts"), "symbol": example.get("symbol"), "issue": issue}
            pattern = {"source": "behavior_watchdog", "strategy": example.get("strategy"), "issue": issue}
            rows.append({**identity, "event_id": _stable_id(identity), "pattern_id": _stable_id(pattern),
                         "lesson": str(issue), "next_action": "nominate_regression_fix_and_replay",
                         "severity": mismatch_severity})
    for subject in audit.get("subjects") or []:
        if not isinstance(subject, dict) or subject.get("passed"):
            continue
        for check in subject.get("failed_checks") or []:
            identity = {"source": "adversarial_audit", "subject_id": subject.get("subject_id"),
                        "strategy_version": subject.get("strategy_version"), "check": check}
            pattern = dict(identity)
            rows.append({**identity, "event_id": _stable_id(identity), "pattern_id": _stable_id(pattern),
                         "lesson": f"adversarial_check_failed:{check}",
                         "next_action": "repair_evidence_or_strategy_in_shadow_then_reaudit", "severity": "high"})
    return rows


def build_report(
    learning_path: Path = LEARNING_PATH,
    watchdog_path: Path = WATCHDOG_PATH,
    audit_path: Path = AUDIT_PATH,
    ledger_path: Path = LEDGER_PATH,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    existing = _read_jsonl(ledger_path)
    known = {row.get("event_id") for row in existing}
    discovered = _mistakes(_read_json(learning_path), _read_json(watchdog_path), _read_json(audit_path))
    new_rows = [row for row in discovered if row["event_id"] not in known]
    # The immutable event remains unchanged, while current watchdog lifecycle
    # can downgrade a repaired issue from high to decaying in today's report.
    current_by_event = {row["event_id"]: row for row in discovered}
    effective_existing = [
        {**row, "severity": current_by_event.get(row.get("event_id"), {}).get("severity", row.get("severity"))}
        for row in existing
    ]
    all_rows = effective_existing + new_rows
    counts = Counter(row.get("pattern_id") for row in all_rows if row.get("pattern_id"))
    latest_by_pattern = {row["pattern_id"]: row for row in all_rows if row.get("pattern_id")}
    repeated = []
    for pattern_id, count in counts.most_common():
        if count < 2:
            continue
        row = latest_by_pattern[pattern_id]
        repeated.append({
            "pattern_id": pattern_id,
            "occurrences": count,
            "lesson": row.get("lesson"),
            "severity": row.get("severity"),
            "next_action": row.get("next_action"),
            "authority": "shadow_challenger_only",
            "production_config_mutation_allowed": False,
        })
    critical = [row for row in repeated if row.get("severity") in {"high", "critical"}]
    report = {
        "provider": "self_learning_edge_loop",
        "mode": "read_only_memory_and_shadow_nominations",
        "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "execution_enabled": False,
        "can_submit_orders": False,
        "automatic_parameter_changes": False,
        "summary": {
            "mistake_event_count": len(all_rows),
            "new_mistake_count": len(new_rows),
            "repeated_pattern_count": len(repeated),
            "critical_unresolved_pattern_count": len(critical),
        },
        "repeated_patterns": repeated,
        "shadow_challenger_nominations": repeated,
        "promotion_blockers": ["unresolved_repeated_high_severity_mistakes"] if critical else [],
        "learning_contract": {
            "observe": "Ingest completed actual/shadow outcomes, watchdog mismatches, and adversarial failures.",
            "remember": "Append stable event and pattern identifiers; never erase losing evidence.",
            "propose": "Repeated patterns may nominate one preregistered shadow challenger.",
            "verify": "Every challenger must pass independent adversarial and forward gates.",
            "promote": "Human review only; no self-approval or live configuration mutation.",
        },
    }
    return report, new_rows


def write_outputs(report: dict[str, Any], new_rows: list[dict[str, Any]], ledger_path: Path = LEDGER_PATH,
                  report_path: Path = REPORT_PATH, log_path: Path = LOG_PATH) -> None:
    ledger_path.parent.mkdir(parents=True, exist_ok=True)
    if new_rows:
        with ledger_path.open("a", encoding="utf-8") as handle:
            for row in new_rows:
                handle.write(json.dumps(row, separators=(",", ":"), sort_keys=True) + "\n")
    report_path.parent.mkdir(parents=True, exist_ok=True)
    temp = report_path.with_suffix(report_path.suffix + ".tmp")
    temp.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(temp, report_path)
    with log_path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(report, separators=(",", ":"), sort_keys=True) + "\n")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--print", action="store_true", dest="do_print")
    args = parser.parse_args()
    report, new_rows = build_report()
    write_outputs(report, new_rows)
    if args.do_print:
        print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

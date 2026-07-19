#!/usr/bin/env python3
"""Audit shadow-consensus blockers against available shadow evidence.

Read-only. This report identifies recurring blockers and flags candidates for
human review when a blocker appears despite symbol-level evidence meeting the
gate's own minimums. It does not modify gate logic.
"""
from __future__ import annotations

import argparse
import json
import os
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


VIBE_HOME = Path.home() / ".vibe-trading"
REPORT_DIR = VIBE_HOME / "reports"
DECISION_LOG = VIBE_HOME / "logs" / "flip-decisions.jsonl"
CONSENSUS_REPORT = REPORT_DIR / "shadow-consensus-gate.json"
SHADOW_REPORT = REPORT_DIR / "flip-shadow-pnl-evaluator.json"
REPORT_PATH = REPORT_DIR / "shadow-consensus-blocker-audit.json"
ROOT = Path(__file__).resolve().parent.parent
LOG_PATH = ROOT / "data" / "shadow_consensus_blocker_audit_log.jsonl"
MIN_SYMBOL_COMPLETED = 5


def _read_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    try:
        lines = path.read_text(encoding="utf-8-sig").splitlines()
    except OSError:
        return []
    rows = []
    for raw in lines:
        if not raw.strip():
            continue
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict):
            rows.append(payload)
    return rows


def _num(value: Any) -> float:
    try:
        return float(value or 0.0)
    except (TypeError, ValueError):
        return 0.0


def _symbol_stats(symbol: str, shadow_report: dict[str, Any]) -> dict[str, Any]:
    by_symbol = shadow_report.get("by_symbol") if isinstance(shadow_report.get("by_symbol"), dict) else {}
    return by_symbol.get(str(symbol).upper()) or by_symbol.get(str(symbol)) or {}


def _iter_block_events(decision_rows: list[dict[str, Any]], consensus: dict[str, Any]) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    for row in decision_rows:
        details = row.get("details") if isinstance(row.get("details"), dict) else {}
        blockers = details.get("blockers") if isinstance(details.get("blockers"), list) else []
        for blocker in blockers:
            events.append({
                "source": "flip_decision_log",
                "symbol": str(row.get("symbol") or "").upper(),
                "strategy": row.get("strategy"),
                "blocker": str(blocker),
                "recommendation": details.get("recommendation"),
                "ts": row.get("ts"),
            })
    for row in consensus.get("decisions") or []:
        if not isinstance(row, dict):
            continue
        blockers = row.get("blockers") if isinstance(row.get("blockers"), list) else []
        for blocker in blockers:
            events.append({
                "source": "shadow_consensus_report",
                "symbol": str(row.get("symbol") or "").upper(),
                "strategy": None,
                "blocker": str(blocker),
                "recommendation": row.get("recommendation"),
                "ts": consensus.get("generated_at") or consensus.get("date"),
            })
    return events


def build_report(
    *,
    decision_log: Path = DECISION_LOG,
    consensus_path: Path = CONSENSUS_REPORT,
    shadow_path: Path = SHADOW_REPORT,
) -> dict[str, Any]:
    decision_rows = _read_jsonl(decision_log)
    consensus = _read_json(consensus_path)
    shadow = _read_json(shadow_path)
    events = _iter_block_events(decision_rows, consensus)
    counts = Counter(event["blocker"] for event in events)
    by_blocker_symbols: dict[str, set[str]] = defaultdict(set)
    review_notes: list[dict[str, Any]] = []
    for event in events:
        blocker = str(event["blocker"])
        symbol = str(event["symbol"] or "")
        if symbol:
            by_blocker_symbols[blocker].add(symbol)
        stats = _symbol_stats(symbol, shadow)
        completed = int(_num(stats.get("completed_count")))
        expectancy = _num(stats.get("expectancy_return_pct"))
        win_rate = _num(stats.get("win_rate"))
        if blocker == "not_enough_shadow_samples" and completed >= MIN_SYMBOL_COMPLETED:
            is_current_snapshot = event["source"] == "shadow_consensus_report"
            review_notes.append({
                "blocker": blocker,
                "symbol": symbol,
                "issue": (
                    "current_blocker_seen_despite_symbol_completed_count_meeting_gate_minimum"
                    if is_current_snapshot
                    else "historical_sample_blocker_now_resolved_by_later_evidence"
                ),
                "current_contradiction": is_current_snapshot,
                "completed_count": completed,
                "win_rate": win_rate,
                "expectancy_return_pct": expectancy,
                "source": event["source"],
            })
        elif blocker in {"market_force_unclear", "kronos_low_confidence", "adaptive_stand_aside"} and completed >= MIN_SYMBOL_COMPLETED and expectancy > 0:
            review_notes.append({
                "blocker": blocker,
                "symbol": symbol,
                "issue": "recurring_blocker_on_positive_shadow_symbol_requires_attribution_review",
                "completed_count": completed,
                "win_rate": win_rate,
                "expectancy_return_pct": expectancy,
                "source": event["source"],
            })

    blocker_rows = []
    for blocker, count in counts.most_common():
        symbols = sorted(by_blocker_symbols.get(blocker, set()))
        symbol_details = []
        for symbol in symbols:
            stats = _symbol_stats(symbol, shadow)
            symbol_details.append({
                "symbol": symbol,
                "completed_count": int(_num(stats.get("completed_count"))),
                "win_rate": _num(stats.get("win_rate")),
                "expectancy_return_pct": _num(stats.get("expectancy_return_pct")),
            })
        blocker_rows.append({
            "blocker": blocker,
            "occurrence_count": count,
            "symbols": symbols,
            "symbol_details": symbol_details,
        })

    global_completed = int(_num(shadow.get("completed_count")))
    return {
        "provider": "shadow_consensus_blocker_audit",
        "mode": "read_only",
        "execution_enabled": False,
        "can_submit_orders": False,
        "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "decision_log": str(decision_log),
        "consensus_report": str(consensus_path),
        "shadow_report": str(shadow_path),
        "global_shadow_completed_count": global_completed,
        "min_symbol_completed_for_sample_gate": MIN_SYMBOL_COMPLETED,
        "blocker_count": len(blocker_rows),
        "blockers": blocker_rows,
        "review_notes": review_notes,
        "interpretation": [
            "not_enough_shadow_samples is symbol-specific, not global.",
            "A high global shadow row count does not prove every symbol has enough completed lifecycles.",
            "Historical blocker events are not contradictions when the sample minimum was reached later.",
            "Review notes are evidence prompts only; they do not loosen live gates.",
        ],
    }


def write_report(report: dict[str, Any], path: Path = REPORT_PATH) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(temp, path)


def append_log(report: dict[str, Any], path: Path = LOG_PATH) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(report, separators=(",", ":"), sort_keys=True) + "\n")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--decision-log", type=Path, default=DECISION_LOG)
    parser.add_argument("--consensus-path", type=Path, default=CONSENSUS_REPORT)
    parser.add_argument("--shadow-path", type=Path, default=SHADOW_REPORT)
    parser.add_argument("--report-path", type=Path, default=REPORT_PATH)
    parser.add_argument("--log-path", type=Path, default=LOG_PATH)
    parser.add_argument("--print", action="store_true", dest="do_print")
    args = parser.parse_args()
    report = build_report(decision_log=args.decision_log, consensus_path=args.consensus_path, shadow_path=args.shadow_path)
    write_report(report, args.report_path)
    append_log(report, args.log_path)
    if args.do_print:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        print(f"Shadow consensus blocker audit written to {args.report_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

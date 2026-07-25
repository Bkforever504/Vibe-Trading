#!/usr/bin/env python3
"""Read-only contamination audit for cross-family learning labels.

Compares legacy postmortem/learning classifications against the canonical
lifecycle normalizer and reports mismatched labels by bot family, with
examples. Never modifies any historical log and never touches execution.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts import closed_trade_postmortem as legacy_postmortem
from scripts import lifecycle_normalizer as canon

VIBE_HOME = Path.home() / ".vibe-trading"
FLIP_STATE_PATH = VIBE_HOME / "flip-trades.json"
OPTIONS_STATE_PATH = VIBE_HOME / "options-trades.json"
SHADOW_PATH = ROOT / "data" / "flip_shadow_candidates_log.jsonl"
MISTAKE_LEDGER_PATH = ROOT / "data" / "self_learning_mistake_ledger.jsonl"
REPORT_PATH = VIBE_HOME / "reports" / "lifecycle-contamination-audit.json"


def _read_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        return default


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


def _example(trade: dict[str, Any], **extra: Any) -> dict[str, Any]:
    return {
        "trade_id": trade.get("id"),
        "strategy": trade.get("strategy"),
        "status": trade.get("status"),
        **extra,
    }


def audit_flip(trades: list[dict[str, Any]]) -> dict[str, Any]:
    views = [canon.normalize_flip_trade(row) for row in trades]
    mismatches = []
    for row, view in zip(trades, views):
        legacy = legacy_postmortem._direction(row)
        if view["direction"] not in (canon.UNKNOWN,) and legacy != view["direction"]:
            mismatches.append(_example(row, legacy_direction=legacy, canonical_direction=view["direction"]))
    quarantined = [view for view in views if view["quarantined"]]
    return {
        "bot_family": canon.FLIP_FAMILY,
        "record_count": len(views),
        "direction_mismatch_count": len(mismatches),
        "direction_mismatch_examples": mismatches[:5],
        "quarantined_count": len(quarantined),
        "quarantine_reasons": dict(Counter(
            reason for view in quarantined for reason in view["unknown_reasons"]
        )),
    }


def audit_options(trades: list[dict[str, Any]]) -> dict[str, Any]:
    views = [canon.normalize_options_trade(row) for row in trades]
    direction_mismatches = []
    credit_rule_misapplied = []
    for row, view in zip(trades, views):
        legacy = legacy_postmortem._direction(row)
        if view["direction"] not in (canon.UNKNOWN,) and legacy != view["direction"]:
            direction_mismatches.append(
                _example(row, legacy_direction=legacy, canonical_direction=view["direction"])
            )
        # Legacy scoring applies credit-stop semantics to every record even
        # when there is no positive opening credit to measure against.
        credit = row.get("net_credit")
        try:
            has_credit = credit is not None and float(credit) > 0
        except (TypeError, ValueError):
            has_credit = False
        if not has_credit:
            credit_rule_misapplied.append(_example(row, reason="credit_rules_without_positive_credit"))
    quarantined = [view for view in views if view["quarantined"]]
    return {
        "bot_family": canon.OPTIONS_FAMILY,
        "record_count": len(views),
        "direction_mismatch_count": len(direction_mismatches),
        "direction_mismatch_examples": direction_mismatches[:5],
        "credit_rule_misapplication_count": len(credit_rule_misapplied),
        "credit_rule_misapplication_examples": credit_rule_misapplied[:5],
        "quarantined_count": len(quarantined),
        "quarantine_reasons": dict(Counter(
            reason for view in quarantined for reason in view["unknown_reasons"]
        )),
    }


def audit_shadow_trend_labels(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Find shadow rows whose trend alignment was graded without the
    direction-matching feature keys (e.g. puts graded on bullish-only keys)."""
    counts: Counter[str] = Counter()
    examples: list[dict[str, Any]] = []
    graded = 0
    for row in rows:
        features = row.get("feature_snapshot") if isinstance(row.get("feature_snapshot"), dict) else None
        if features is None:
            continue
        right = str(row.get("right") or features.get("right") or "").upper()
        direction = "bullish" if right == "CALL" else "bearish" if right == "PUT" else canon.UNKNOWN
        alignment, reason = canon.trend_alignment(direction, features)
        graded += 1
        if alignment == canon.UNKNOWN and reason:
            key = f"{right or 'NO_RIGHT'}:{reason.split(':', 1)[0]}"
            counts[key] += 1
            if len(examples) < 5:
                examples.append({
                    "lifecycle_id": row.get("lifecycle_id"),
                    "date": row.get("date"),
                    "right": right,
                    "schema_version": features.get("schema_version"),
                    "unknown_reason": reason,
                })
    return {
        "graded_row_count": graded,
        "trend_alignment_unknown_count": sum(counts.values()),
        "unknown_by_right_and_reason": dict(counts),
        "examples": examples,
    }


def audit_mistake_ledger(rows: list[dict[str, Any]]) -> dict[str, Any]:
    unknown_context = Counter()
    context_rows = 0
    for row in rows:
        context = row.get("context") if isinstance(row.get("context"), dict) else {}
        if not context:
            continue
        context_rows += 1
        for field in ("entry_pattern", "retest_status", "expected_move_bucket", "spread_bucket"):
            if context.get(field) == "unknown":
                unknown_context[field] += 1
        if context.get("trend_alignment") == "unconfirmed":
            unknown_context["trend_alignment_unconfirmed_possibly_missing_keys"] += 1
    return {
        "ledger_row_count": len(rows),
        "rows_with_context": context_rows,
        "unknown_context_field_counts": dict(unknown_context),
        "note": (
            "Ledger rows are immutable. Rows with unknown/ambiguous context "
            "must be excluded from challenger support counts until re-derived "
            "through the canonical normalizer."
        ),
    }


def build_report(
    flip_path: Path = FLIP_STATE_PATH,
    options_path: Path = OPTIONS_STATE_PATH,
    shadow_path: Path = SHADOW_PATH,
    ledger_path: Path = MISTAKE_LEDGER_PATH,
) -> dict[str, Any]:
    flip_rows = _read_json(flip_path, [])
    flip_rows = [row for row in flip_rows if isinstance(row, dict)] if isinstance(flip_rows, list) else []
    options_payload = _read_json(options_path, {})
    options_rows = options_payload.get("trades") if isinstance(options_payload, dict) else []
    options_rows = [row for row in options_rows or [] if isinstance(row, dict)]
    shadow_rows = _read_jsonl(shadow_path)
    ledger_rows = _read_jsonl(ledger_path)

    flip_audit = audit_flip(flip_rows)
    options_audit = audit_options(options_rows)
    shadow_audit = audit_shadow_trend_labels(shadow_rows)
    ledger_audit = audit_mistake_ledger(ledger_rows)

    contaminated_total = (
        flip_audit["direction_mismatch_count"]
        + options_audit["direction_mismatch_count"]
        + options_audit["credit_rule_misapplication_count"]
        + shadow_audit["trend_alignment_unknown_count"]
    )
    return {
        "provider": "lifecycle_contamination_audit",
        "mode": "read_only",
        "execution_enabled": False,
        "lifecycle_schema_version": canon.LIFECYCLE_SCHEMA_VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "summary": {
            "contaminated_label_count": contaminated_total,
            "flip_direction_mismatches": flip_audit["direction_mismatch_count"],
            "options_direction_mismatches": options_audit["direction_mismatch_count"],
            "options_credit_rule_misapplications": options_audit["credit_rule_misapplication_count"],
            "shadow_trend_alignment_unknowns": shadow_audit["trend_alignment_unknown_count"],
            "quarantined_flip": flip_audit["quarantined_count"],
            "quarantined_options": options_audit["quarantined_count"],
        },
        "by_family": {
            canon.FLIP_FAMILY: flip_audit,
            canon.OPTIONS_FAMILY: options_audit,
            canon.TOPSTEP_FAMILY: {
                "bot_family": canon.TOPSTEP_FAMILY,
                "record_count": 0,
                "note": "No closed MES trades exist yet; adapter is ready with point-value/fee semantics.",
            },
        },
        "shadow_trend_label_audit": shadow_audit,
        "mistake_ledger_audit": ledger_audit,
        "authority": "observational_report_only_no_production_mutation",
    }


def write_report(report: dict[str, Any], path: Path = REPORT_PATH) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(temp, path)
    return path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--print", action="store_true", dest="do_print")
    parser.add_argument("--no-write", action="store_true")
    args = parser.parse_args()
    report = build_report()
    if not args.no_write:
        write_report(report)
    if args.do_print:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        print(json.dumps(report["summary"], indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Fail-closed audit of named strategy concepts versus actual evidence."""
from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
TAXONOMY = ROOT / "research" / "pattern_taxonomy.json"
REGISTRY = ROOT / "research" / "concept_evidence_registry_2026-08-30.json"
DEFAULT_OUT = ROOT / "data" / "strategy_concept_coverage_audit.json"
DEFAULT_REPORT = Path.home() / ".vibe-trading" / "reports" / "strategy-concept-coverage-audit.json"
TESTED = {"isolated_tested", "cross_market_tested", "forward_validated"}


def _load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _priority(row: dict[str, Any]) -> int:
    status_score = {
        "untested": 50,
        "implementation_only": 45,
        "underspecified": 35,
        "partial_proxy_only": 30,
        "spy_only_tested": 25,
        "data_blocked": 5,
        "isolated_tested": 0,
    }.get(str(row.get("evidence_status")), 20)
    readiness_score = {"ready": 30, "partial": 15, "blocked": 0}.get(str(row.get("data_readiness")), 0)
    implementation_score = 10 if "live" in str(row.get("implementation_status", "")) else 0
    next_score = 10 if row.get("next_experiment") else 0
    return status_score + readiness_score + implementation_score + next_score


def build_audit(taxonomy_path: Path = TAXONOMY, registry_path: Path = REGISTRY) -> dict[str, Any]:
    taxonomy = _load(taxonomy_path)
    registry = _load(registry_path)
    registered = registry.get("patterns") if isinstance(registry.get("patterns"), dict) else {}
    taxonomy_rows = taxonomy.get("patterns") if isinstance(taxonomy.get("patterns"), list) else []
    taxonomy_ids = {str(row.get("id")) for row in taxonomy_rows}
    missing = sorted(taxonomy_ids - set(registered))
    orphaned = sorted(set(registered) - taxonomy_ids)
    rows: list[dict[str, Any]] = []
    for pattern in taxonomy_rows:
        pattern_id = str(pattern.get("id"))
        evidence = registered.get(pattern_id, {}) if isinstance(registered.get(pattern_id), dict) else {}
        status = str(evidence.get("evidence_status") or "untested")
        row = {
            "id": pattern_id,
            "family": pattern.get("family"),
            "timeframes": pattern.get("timeframes", []),
            "implementation_status": pattern.get("implementation_status"),
            "evidence_status": status,
            "data_readiness": evidence.get("data_readiness", "unknown"),
            "isolated_tested": status in TESTED,
            "evidence": evidence.get("evidence", []),
            "gap": evidence.get("gap"),
            "next_experiment": evidence.get("next_experiment"),
        }
        row["priority_score"] = _priority(row)
        rows.append(row)
    external: list[dict[str, Any]] = []
    for raw in registry.get("external_concept_queue", []):
        if not isinstance(raw, dict):
            continue
        row = {**raw, "family": "external_intake", "implementation_status": "external_concept"}
        row["priority_score"] = _priority(row)
        external.append(row)
    status_counts = Counter(str(row["evidence_status"]) for row in rows)
    tested_count = sum(row["isolated_tested"] for row in rows)
    queue = sorted(
        [row for row in rows + external if row.get("evidence_status") not in TESTED],
        key=lambda row: (row["priority_score"], row.get("id", "")),
        reverse=True,
    )
    return {
        "schema_version": 1,
        "mode": "research_governance_only",
        "execution_enabled": False,
        "rank_effect": "none",
        "taxonomy_pattern_count": len(rows),
        "isolated_tested_count": tested_count,
        "isolated_test_coverage_pct": round(100.0 * tested_count / len(rows), 1) if rows else 0.0,
        "status_counts": dict(status_counts),
        "registry_complete": not missing and not orphaned,
        "missing_registry_ids": missing,
        "orphaned_registry_ids": orphaned,
        "patterns": rows,
        "external_concept_queue": external,
        "priority_queue": queue,
        "data_ready_untested_count": sum(
            row.get("data_readiness") == "ready" and row.get("evidence_status") not in TESTED
            for row in rows + external
        ),
        "verdict": "coverage_gaps_require_tournaments" if tested_count < len(rows) else "all_named_concepts_isolated_tested",
        "warning": "Implementation, dashboard display, social evidence, and proxy tests do not count as isolated validation.",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    parser.add_argument("--print", action="store_true", dest="print_report")
    args = parser.parse_args()
    report = build_audit()
    for path in (args.output, args.report):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    if args.print_report:
        print(json.dumps({
            "verdict": report["verdict"],
            "coverage_pct": report["isolated_test_coverage_pct"],
            "status_counts": report["status_counts"],
            "data_ready_untested_count": report["data_ready_untested_count"],
            "top_priority": report["priority_queue"][:12],
        }, indent=2))
    # A taxonomy concept without an explicit evidence row is an operational
    # discovery failure, not an informational warning.
    return 0 if report["registry_complete"] else 2


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Audit external trading teachings before they enter any bot research lane.

The registry is intentionally static and reviewable. This module does not fetch
signals, connect to brokers, alter configuration, or grant promotion authority.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_REGISTRY = ROOT / "research" / "external_strategy_sources.json"
DEFAULT_JSON_OUTPUT = ROOT / "data" / "external_strategy_evidence_report.json"
DEFAULT_MARKDOWN_OUTPUT = ROOT / "research" / "EXTERNAL_STRATEGY_EVIDENCE_REPORT_2026-08-17.md"

WEIGHTS = {
    "rule_completeness": 2.0,
    "independent_verification": 2.0,
    "transaction_cost_realism": 1.5,
    "holdout_quality": 1.5,
    "point_in_time_data": 1.0,
    "license_clarity": 1.0,
    "complete_loss_history": 1.0,
}


def load_registry(path: Path = DEFAULT_REGISTRY) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("schema_version") != 1:
        raise ValueError("unsupported external strategy registry schema")
    if not isinstance(payload.get("sources"), list):
        raise ValueError("registry sources must be a list")
    return payload


def evidence_score(evidence: dict[str, Any]) -> float:
    score = 0.0
    for field, weight in WEIGHTS.items():
        value = float(evidence.get(field, 0.0))
        if not 0.0 <= value <= 1.0:
            raise ValueError(f"{field} must be between 0 and 1")
        score += value * weight
    return round(score, 2)


def _artifact_status(source: dict[str, Any], root: Path) -> tuple[list[str], list[str]]:
    declared = sorted({
        mapping["artifact"]
        for mapping in source.get("bot_mappings", [])
        if mapping.get("artifact")
    })
    missing = [path for path in declared if not (root / path).exists()]
    return declared, missing


def classify_source(source: dict[str, Any], score: float, missing_artifacts: list[str]) -> str:
    role = source.get("role")
    exact_rules = bool(source.get("evidence", {}).get("rules_exact"))
    replication_scope = source.get("replication_scope")

    if role == "social_claim":
        return "rejected_as_edge_evidence"
    if role == "verified_track_record_discovery":
        return "discovery_only"
    if role == "engineering_reference":
        return "engineering_reference" if score >= 5.0 else "education_only"
    if role == "process_control":
        return "process_control_adopted" if score >= 5.0 and not missing_artifacts else "education_only"
    if role == "benchmark":
        return "benchmark_accepted" if score >= 7.0 and exact_rules else "benchmark_unverified"
    if role == "falsification_evidence":
        return "required_caveat"
    if role == "research_hypothesis":
        if replication_scope == "exact" and exact_rules and score >= 7.0 and not missing_artifacts:
            return "shadow_replication_eligible"
        return "hypothesis_only"
    return "education_only"


def build_report(registry: dict[str, Any], *, root: Path = ROOT) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    for source in registry["sources"]:
        score = evidence_score(source.get("evidence", {}))
        artifacts, missing = _artifact_status(source, root)
        rows.append({
            "source_id": source["source_id"],
            "name": source["name"],
            "source_kind": source["source_kind"],
            "role": source["role"],
            "replication_scope": source.get("replication_scope", "none"),
            "evidence_score": score,
            "classification": classify_source(source, score, missing),
            "primary_urls": source.get("primary_urls", []),
            "track_record_status": source.get("track_record", {}).get("status", "not_claimed"),
            "track_record_caveat": source.get("track_record", {}).get("caveat"),
            "implementation_permission": source.get("licensing", {}).get("implementation_permission", "unknown"),
            "bot_mappings": source.get("bot_mappings", []),
            "declared_artifacts": artifacts,
            "missing_artifacts": missing,
            "teachings": source.get("teachings", []),
            "forbidden_uses": source.get("forbidden_uses", []),
        })

    counts: dict[str, int] = {}
    for row in rows:
        counts[row["classification"]] = counts.get(row["classification"], 0) + 1
    eligible = [row["source_id"] for row in rows if row["classification"] == "shadow_replication_eligible"]
    return {
        "schema_version": 1,
        "provider": "external_strategy_evidence",
        "as_of": registry.get("as_of"),
        "mode": "read_only_source_governance",
        "scoring_weights": WEIGHTS,
        "source_count": len(rows),
        "classification_counts": counts,
        "shadow_replication_eligible": eligible,
        "sources": rows,
        "automatic_promotion": False,
        "promotion_authority": "blocked",
        "execution_enabled": False,
        "can_submit_orders": False,
    }


def render_markdown(report: dict[str, Any]) -> str:
    lines = [
        "# External Strategy Evidence Report",
        "",
        f"As of: {report.get('as_of')}",
        "",
        "This report separates reproducible teachings from marketing claims. It has no execution or promotion authority.",
        "",
        "| Source | Role | Score / 10 | Classification | Bot use |",
        "|---|---:|---:|---|---|",
    ]
    for row in report["sources"]:
        bot_use = ", ".join(sorted({mapping.get("bot_id", "") for mapping in row["bot_mappings"]})) or "none"
        lines.append(
            f"| {row['name']} | {row['role']} | {row['evidence_score']:.2f} | "
            f"{row['classification']} | {bot_use} |"
        )
    lines.extend([
        "",
        "## Governance",
        "",
        "- Social screenshots, testimonials, and selective trade posts are rejected as edge evidence.",
        "- Opaque but broker-verified track records may identify candidates, never rules to copy.",
        "- Exact public rules may enter a cost-aware shadow replay only after the declared implementation artifact exists.",
        "- Books and videos are process education unless their rules and data are reproducible.",
        "- Every eligible hypothesis remains blocked from paper or live promotion by this report.",
        "",
        "## Current Actions",
        "",
    ])
    for row in report["sources"]:
        if row["classification"] in {"benchmark_accepted", "shadow_replication_eligible", "process_control_adopted", "engineering_reference"}:
            teachings = "; ".join(row["teachings"][:2]) or "No teaching recorded"
            lines.append(f"- **{row['name']}**: {teachings}")
    lines.extend([
        "",
        "## Safety",
        "",
        f"Execution enabled: `{str(report['execution_enabled']).lower()}`  ",
        f"Can submit orders: `{str(report['can_submit_orders']).lower()}`  ",
        f"Automatic promotion: `{str(report['automatic_promotion']).lower()}`",
        "",
    ])
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--registry", type=Path, default=DEFAULT_REGISTRY)
    parser.add_argument("--out", type=Path, default=DEFAULT_JSON_OUTPUT)
    parser.add_argument("--markdown", type=Path, default=DEFAULT_MARKDOWN_OUTPUT)
    parser.add_argument("--print", action="store_true", dest="print_report")
    args = parser.parse_args()
    report = build_report(load_registry(args.registry))
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.markdown.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    args.markdown.write_text(render_markdown(report), encoding="utf-8")
    if args.print_report:
        print(json.dumps(report, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()

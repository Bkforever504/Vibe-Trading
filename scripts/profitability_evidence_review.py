#!/usr/bin/env python3
"""Run the read-only profitability evidence upgrades as one review."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.clustered_portfolio_monte_carlo import build_report as build_clustered_risk
from scripts.clustered_portfolio_monte_carlo import read_jsonl as read_twin_rows
from scripts.execution_seasonality_report import build_report as build_execution_seasonality
from scripts.external_strategy_evidence import build_report as build_external_strategy_evidence
from scripts.external_strategy_evidence import load_registry as load_external_strategy_registry
from scripts.filter_counterfactual_attribution import build_report as build_filter_attribution
from scripts.filter_counterfactual_attribution import read_jsonl as read_setup_rows


DEFAULT_TWIN_PATH = ROOT / "data" / "options_shadow_twin_log.jsonl"
DEFAULT_SETUP_PATH = ROOT / "data" / "options_evidence_factory_log.jsonl"
DEFAULT_OUTPUT_PATH = ROOT / "data" / "profitability_evidence_review.json"


def build_review(
    twin_rows: list[dict[str, Any]],
    setup_rows: list[dict[str, Any]],
    *,
    account_equity: float = 10000.0,
) -> dict[str, Any]:
    filter_report = build_filter_attribution(twin_rows, setup_rows)
    seasonality_report = build_execution_seasonality(twin_rows)
    risk_report = build_clustered_risk(twin_rows, account_equity=account_equity)
    external_strategy_report = build_external_strategy_evidence(load_external_strategy_registry())
    blockers: list[str] = []
    if filter_report["resolved_candidate_count"] < 30:
        blockers.append("fewer_than_30_resolved_filter_counterfactuals")
    if seasonality_report["resolved_candidate_count"] < 30:
        blockers.append("fewer_than_30_resolved_execution_observations")
    if risk_report["evidence_status"] != "sufficient_for_risk_review":
        blockers.append("clustered_portfolio_history_insufficient")
    return {
        "schema_version": 1,
        "provider": "profitability_evidence_review",
        "mode": "read_only_diagnostic_bundle",
        "summary": {
            "resolved_filter_counterfactuals": filter_report["resolved_candidate_count"],
            "promising_veto_count": filter_report["promising_veto_count"],
            "resolved_execution_observations": seasonality_report["resolved_candidate_count"],
            "active_resolution_days": risk_report["active_resolution_day_count"],
            "external_sources_reviewed": external_strategy_report["source_count"],
            "shadow_replication_eligible_sources": len(
                external_strategy_report["shadow_replication_eligible"]
            ),
            "blockers": blockers,
        },
        "filter_counterfactual_attribution": filter_report,
        "execution_seasonality": seasonality_report,
        "clustered_portfolio_risk": risk_report,
        "external_strategy_evidence": external_strategy_report,
        "promotion_authority": "blocked",
        "execution_enabled": False,
        "can_submit_orders": False,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--twin", type=Path, default=DEFAULT_TWIN_PATH)
    parser.add_argument("--setups", type=Path, default=DEFAULT_SETUP_PATH)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUTPUT_PATH)
    parser.add_argument("--account-equity", type=float, default=10000.0)
    parser.add_argument("--print", action="store_true", dest="print_report")
    args = parser.parse_args()
    report = build_review(
        read_twin_rows(args.twin),
        read_setup_rows(args.setups),
        account_equity=args.account_equity,
    )
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    if args.print_report:
        print(json.dumps(report, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()

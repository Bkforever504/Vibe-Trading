#!/usr/bin/env python3
"""Build the daily unified capital decision from existing evidence artifacts."""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from strategies.profitability_control_plane import OpportunityCandidate, run_opportunity_exchange


DATA = ROOT / "data"
DEFAULT_OUTPUT = DATA / "profitability_control_plane.json"
DEFAULT_LEDGER = DATA / "profitability_control_plane_ledger.jsonl"


def _read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def _as_float(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _risk_cluster(lane: str) -> str:
    if lane in {"qqq_mean_reversion", "trend_participation", "momentum_edge_ensemble"}:
        return "long_equity_beta"
    if lane in {"volatility_premium", "weekly_minus_1atr_defined_risk_put_premium", "vrp_component_call_spread"}:
        return "short_equity_volatility"
    if lane.startswith("mes_"):
        return "equity_index_futures"
    return lane


def candidates_from_reports(opportunity: dict[str, Any], router: dict[str, Any]) -> list[OpportunityCandidate]:
    lifecycle = ((opportunity.get("strategy_lifecycle") or {}).get("lanes") or {})
    evidence = opportunity.get("evidence") or {}
    source_candidates = (opportunity.get("regime_allocator") or {}).get("candidates") or []
    candidates: list[OpportunityCandidate] = []

    for row in source_candidates:
        if not isinstance(row, dict) or row.get("lane") == "cash":
            continue
        lane = str(row.get("lane") or "unknown")
        lane_evidence = evidence.get(lane) if isinstance(evidence.get(lane), dict) else {}
        lane_lifecycle = lifecycle.get(lane) if isinstance(lifecycle.get(lane), dict) else {}
        ci = (lane_evidence.get("bootstrap") or {}).get("ci90") or [None, None]
        candidates.append(OpportunityCandidate(
            candidate_id=str(row.get("candidate_id") or lane),
            lane=lane,
            risk_cluster=_risk_cluster(lane),
            expected_pnl=_as_float(lane_evidence.get("mean_pnl")),
            lower_confidence_pnl=_as_float(ci[0] if ci else None),
            # Upstream histories are already net of their modeled strategy costs.
            estimated_round_trip_cost=0.0,
            max_loss=None,
            current_signal=bool(row.get("eligible")),
            lifecycle_state=str(lane_lifecycle.get("state") or "collecting"),
            paper_review_eligible=bool(lane_lifecycle.get("paper_review_eligible")),
            regime=str((row.get("regime_context") or {}).get("vix_regime") or "unknown"),
            regime_compatible=None,
            forward_observations=int(lane_lifecycle.get("observations") or 0),
            source="opportunity_intelligence_report",
        ))

    existing = {candidate.lane for candidate in candidates}
    for row in router.get("lanes") or []:
        if not isinstance(row, dict):
            continue
        lane = str(row.get("lane") or "unknown")
        if lane in existing:
            continue
        status = str(row.get("status") or "research_only")
        candidates.append(OpportunityCandidate(
            candidate_id=f"router:{lane}",
            lane=lane,
            risk_cluster=_risk_cluster(lane),
            expected_pnl=None,
            lower_confidence_pnl=None,
            estimated_round_trip_cost=None,
            max_loss=None,
            current_signal=status not in {"retired_as_income_candidate"},
            lifecycle_state="retired" if status == "retired_as_income_candidate" else "collecting",
            paper_review_eligible=False,
            forward_observations=0,
            source="edge_evidence_router_report",
        ))
    return candidates


def build_report(root: Path = ROOT) -> dict[str, Any]:
    opportunity = _read_json(root / "data" / "opportunity_intelligence_report.json")
    router = _read_json(root / "data" / "edge_evidence_router_report.json")
    report = run_opportunity_exchange(candidates_from_reports(opportunity, router))
    report["source_health"] = {
        "opportunity_intelligence_report": "available" if opportunity else "missing",
        "edge_evidence_router_report": "available" if router else "missing",
    }
    report["operating_objective"] = (
        "Produce either a validated after-cost paper candidate or an explicit cash decision; "
        "never force a trade to satisfy a daily income target."
    )
    return report


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--ledger", type=Path, default=DEFAULT_LEDGER)
    parser.add_argument("--print", action="store_true", dest="print_report")
    args = parser.parse_args()
    report = build_report()
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    args.ledger.parent.mkdir(parents=True, exist_ok=True)
    with args.ledger.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(report, sort_keys=True) + "\n")
    if args.print_report:
        print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


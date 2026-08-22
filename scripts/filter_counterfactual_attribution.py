#!/usr/bin/env python3
"""Measure whether research filters reject bad trades or merely reduce activity.

The report joins shadow candidates to their resolved counterfactual outcomes.
It is descriptive because filters overlap; no row has promotion authority.
"""
from __future__ import annotations

import argparse
import json
import math
from collections import defaultdict
from pathlib import Path
from statistics import mean, median
from typing import Any, Iterable


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_TWIN_PATH = ROOT / "data" / "options_shadow_twin_log.jsonl"
DEFAULT_SETUP_PATH = ROOT / "data" / "options_evidence_factory_log.jsonl"
DEFAULT_OUTPUT_PATH = ROOT / "data" / "filter_counterfactual_attribution.json"
MIN_COHORT = 10


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8-sig") as handle:
        for line in handle:
            try:
                value = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(value, dict):
                rows.append(value)
    return rows


def _number(value: Any) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if math.isfinite(parsed) else None


def _percentile(values: list[float], quantile: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    position = (len(ordered) - 1) * quantile
    low = int(math.floor(position))
    high = int(math.ceil(position))
    if low == high:
        return ordered[low]
    weight = position - low
    return ordered[low] * (1.0 - weight) + ordered[high] * weight


def _metrics(rows: list[dict[str, Any]]) -> dict[str, Any]:
    pnls = [float(row["pnl"]) for row in rows]
    wins = [value for value in pnls if value > 0]
    losses = [value for value in pnls if value < 0]
    return {
        "count": len(pnls),
        "wins": len(wins),
        "losses": len(losses),
        "win_rate": round(len(wins) / len(pnls), 4) if pnls else None,
        "aggregate_pnl_dollars": round(sum(pnls), 2),
        "average_pnl_dollars": round(mean(pnls), 2) if pnls else None,
        "median_pnl_dollars": round(median(pnls), 2) if pnls else None,
        "p10_pnl_dollars": round(float(_percentile(pnls, 0.10)), 2) if pnls else None,
        "worst_pnl_dollars": round(min(pnls), 2) if pnls else None,
        "best_pnl_dollars": round(max(pnls), 2) if pnls else None,
    }


def _shadow_blockers(candidate: dict[str, Any], decisions: list[dict[str, Any]]) -> tuple[bool, set[str]]:
    consensus = candidate.get("shadow_consensus")
    has_context = isinstance(consensus, dict) and bool(consensus)
    blockers: set[str] = set()
    if isinstance(consensus, dict):
        blockers.update(str(value) for value in consensus.get("blockers") or [] if value)
        nested = consensus.get("decision")
        if isinstance(nested, dict):
            blockers.update(str(value) for value in nested.get("blockers") or [] if value)
    for decision in decisions:
        details = decision.get("details")
        if isinstance(details, dict) and "blockers" in details:
            has_context = True
            blockers.update(str(value) for value in details.get("blockers") or [] if value)
    return has_context, blockers


def build_report(
    twin_rows: Iterable[dict[str, Any]],
    setup_rows: Iterable[dict[str, Any]] = (),
) -> dict[str, Any]:
    candidates: dict[str, dict[str, Any]] = {}
    outcomes: dict[str, dict[str, Any]] = {}
    decisions: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in twin_rows:
        candidate_id = str(row.get("candidate_id") or "")
        if not candidate_id:
            continue
        row_type = row.get("type")
        if row_type == "candidate":
            candidates[candidate_id] = row
        elif row_type == "outcome":
            outcomes[candidate_id] = row
        elif row_type == "decision":
            decisions[candidate_id].append(row)

    setup_gate_states: dict[str, dict[str, bool]] = defaultdict(dict)
    setup_warning_states: dict[str, set[str]] = defaultdict(set)
    setup_gate_universe: set[str] = set()
    setup_warning_universe: set[str] = set()
    for setup in setup_rows:
        if setup.get("type") != "matched_setup":
            continue
        gates = setup.get("gate_states") if isinstance(setup.get("gate_states"), dict) else {}
        warnings = {str(value) for value in setup.get("warning_states") or [] if value}
        setup_gate_universe.update(str(key) for key in gates)
        setup_warning_universe.update(warnings)
        for expression in setup.get("expressions") or []:
            if not isinstance(expression, dict) or not expression.get("candidate_id"):
                continue
            candidate_id = str(expression["candidate_id"])
            setup_gate_states[candidate_id].update({str(key): bool(value) for key, value in gates.items()})
            setup_warning_states[candidate_id].update(warnings)

    shadow_context: dict[str, bool] = {}
    active_shadow: dict[str, set[str]] = {}
    shadow_universe: set[str] = set()
    for candidate_id, candidate in candidates.items():
        has_context, blockers = _shadow_blockers(candidate, decisions.get(candidate_id, []))
        shadow_context[candidate_id] = has_context
        active_shadow[candidate_id] = blockers
        shadow_universe.update(blockers)

    resolved: list[dict[str, Any]] = []
    states_by_candidate: dict[str, dict[str, bool]] = {}
    for candidate_id, outcome in outcomes.items():
        candidate = candidates.get(candidate_id)
        pnl = _number(outcome.get("pnl_before_fees"))
        if candidate is None or pnl is None:
            continue
        states: dict[str, bool] = {}
        if shadow_context.get(candidate_id):
            states.update({f"shadow:{name}": name in active_shadow[candidate_id] for name in shadow_universe})
        if candidate_id in setup_gate_states:
            gates = setup_gate_states[candidate_id]
            states.update({f"setup_gate:{name}": not gates[name] for name in gates})
        if candidate_id in setup_warning_states:
            warnings = setup_warning_states[candidate_id]
            states.update({f"setup_warning:{name}": name in warnings for name in setup_warning_universe})
        states_by_candidate[candidate_id] = states
        resolved.append({
            "candidate_id": candidate_id,
            "strategy": candidate.get("strategy"),
            "underlying": candidate.get("underlying"),
            "pnl": pnl,
            "win": pnl > 0,
        })

    known_filters = sorted({name for states in states_by_candidate.values() for name in states})
    total_negative = abs(sum(min(0.0, float(row["pnl"])) for row in resolved))
    total_winners = sum(bool(row["win"]) for row in resolved)
    top_count = max(1, math.ceil(len(resolved) * 0.01)) if resolved else 0
    top_ids = {
        row["candidate_id"]
        for row in sorted(resolved, key=lambda value: float(value["pnl"]), reverse=True)[:top_count]
    }
    filters: list[dict[str, Any]] = []
    for filter_name in known_filters:
        observed = [row for row in resolved if filter_name in states_by_candidate[row["candidate_id"]]]
        blocked = [row for row in observed if states_by_candidate[row["candidate_id"]][filter_name]]
        allowed = [row for row in observed if not states_by_candidate[row["candidate_id"]][filter_name]]
        blocked_metrics = _metrics(blocked)
        allowed_metrics = _metrics(allowed)
        blocked_loss = abs(sum(min(0.0, float(row["pnl"])) for row in blocked))
        blocked_winners = sum(bool(row["win"]) for row in blocked)
        enough = len(blocked) >= MIN_COHORT and len(allowed) >= MIN_COHORT
        blocked_average = blocked_metrics["average_pnl_dollars"]
        allowed_average = allowed_metrics["average_pnl_dollars"]
        if not enough:
            verdict = "insufficient_cohort"
        elif blocked_average is not None and allowed_average is not None and blocked_average < 0 < allowed_average:
            verdict = "promising_veto"
        elif blocked_average is not None and allowed_average is not None and blocked_average > allowed_average:
            verdict = "harmful_or_inverted_veto"
        else:
            verdict = "inconclusive"
        filters.append({
            "filter": filter_name,
            "observed_count": len(observed),
            "blocked": blocked_metrics,
            "allowed": allowed_metrics,
            "allowed_minus_blocked_expectancy_dollars": round(float(allowed_average) - float(blocked_average), 2)
            if allowed_average is not None and blocked_average is not None else None,
            "counterfactual_loss_avoided_dollars": round(-sum(float(row["pnl"]) for row in blocked), 2),
            "loss_dollars_captured_rate": round(blocked_loss / total_negative, 4) if total_negative else None,
            "winner_removal_rate": round(blocked_winners / total_winners, 4) if total_winners else None,
            "top_one_pct_winners_removed": sum(row["candidate_id"] in top_ids for row in blocked),
            "verdict": verdict,
            "promotion_authority": "blocked",
        })

    filters.sort(key=lambda row: (
        row["verdict"] != "promising_veto",
        -(row["allowed_minus_blocked_expectancy_dollars"] or -math.inf),
        row["filter"],
    ))
    return {
        "schema_version": 1,
        "provider": "filter_counterfactual_attribution",
        "mode": "read_only_overlapping_filter_diagnostics",
        "resolved_candidate_count": len(resolved),
        "minimum_cohort_per_side": MIN_COHORT,
        "universe": _metrics(resolved),
        "filters": filters,
        "promising_veto_count": sum(row["verdict"] == "promising_veto" for row in filters),
        "limitations": [
            "Filters overlap, so individual attribution is descriptive rather than causal.",
            "Outcomes are shadow counterfactuals and may exclude fees unless the source outcome includes them.",
            "A promising veto still requires preregistered walk-forward validation.",
        ],
        "promotion_authority": "blocked",
        "execution_enabled": False,
        "can_submit_orders": False,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--twin", type=Path, default=DEFAULT_TWIN_PATH)
    parser.add_argument("--setups", type=Path, default=DEFAULT_SETUP_PATH)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUTPUT_PATH)
    parser.add_argument("--print", action="store_true", dest="print_report")
    args = parser.parse_args()
    report = build_report(read_jsonl(args.twin), read_jsonl(args.setups))
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    if args.print_report:
        print(json.dumps(report, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()

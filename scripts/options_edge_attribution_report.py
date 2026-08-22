#!/usr/bin/env python3
"""Attribute resolved matched options evidence without changing trading state."""
from __future__ import annotations

import argparse
import json
import math
import sys
from collections import Counter, defaultdict
from pathlib import Path
from statistics import mean
from typing import Any, Iterable

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.options_evidence_factory import DEFAULT_LOG_PATH as DEFAULT_EVIDENCE_PATH
from scripts.options_evidence_factory import read_records as read_evidence_records
from scripts.options_shadow_twin import DEFAULT_LOG_PATH as DEFAULT_TWIN_PATH
from scripts.options_shadow_twin import midpoint_close_debit, read_records as read_twin_records


SCHEMA_VERSION = 1
DEFAULT_NBBO_PATH = ROOT / "data" / "options_nbbo_curriculum_results.json"
DEFAULT_OUTPUT_PATH = ROOT / "data" / "options_edge_attribution_report.json"


def _number(value: Any) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if math.isfinite(parsed) else None


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _index_twin(rows: Iterable[dict[str, Any]]) -> tuple[
    dict[str, dict[str, Any]],
    dict[str, list[dict[str, Any]]],
    dict[str, dict[str, Any]],
]:
    candidates: dict[str, dict[str, Any]] = {}
    marks: dict[str, list[dict[str, Any]]] = defaultdict(list)
    outcomes: dict[str, dict[str, Any]] = {}
    for row in rows:
        candidate_id = str(row.get("candidate_id") or "")
        if not candidate_id:
            continue
        if row.get("type") == "candidate":
            candidates[candidate_id] = row
        elif row.get("type") == "mark":
            marks[candidate_id].append(row)
        elif row.get("type") == "outcome":
            outcomes[candidate_id] = row
    return candidates, dict(marks), outcomes


def _nbbo_outcomes(payload: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {
        str(row.get("candidate_id")): row
        for row in (payload.get("outcomes") or [])
        if isinstance(row, dict) and row.get("candidate_id") and row.get("status") == "resolved"
    }


def _outcome(candidate_id: str, twin: dict[str, dict[str, Any]], nbbo: dict[str, dict[str, Any]]) -> dict[str, Any]:
    if candidate_id in nbbo:
        row = nbbo[candidate_id]
        return {
            "status": "resolved",
            "source": "licensed_opra_curriculum",
            "net_pnl_dollars": _number(row.get("pnl_base")),
            "entry_credit": _number(row.get("entry_credit")),
            "closing_debit": _number(row.get("closing_debit")),
            "quantity": int(_number(row.get("quantity")) or 0),
            "reason": row.get("reason"),
        }
    if candidate_id in twin:
        row = twin[candidate_id]
        return {
            "status": "resolved",
            "source": "forward_shadow_quote_path",
            "net_pnl_dollars": _number(row.get("pnl_before_fees")),
            "entry_credit": _number(row.get("entry_credit")),
            "closing_debit": _number(row.get("closing_debit")),
            "quantity": int(_number(row.get("quantity")) or 0),
            "reason": row.get("reason"),
        }
    return {"status": "unresolved", "source": "none", "net_pnl_dollars": None}


def _entry_execution(candidate: dict[str, Any], quantity: int) -> dict[str, Any]:
    mid = _number(candidate.get("quoted_mid_credit"))
    executable = _number(candidate.get("executable_entry_credit"))
    if mid is None or executable is None or quantity <= 0:
        return {"status": "unavailable", "friction_dollars": None}
    friction = max(0.0, mid - executable) * 100.0 * quantity
    return {
        "status": "measured",
        "midpoint_credit": mid,
        "executable_credit": executable,
        "friction_dollars": round(friction, 2),
        "method": "arrival_mid_credit_minus_sell_bid_buy_ask_credit",
    }


def _exit_execution(mark_rows: list[dict[str, Any]], quantity: int) -> dict[str, Any]:
    for row in reversed(mark_rows):
        executable = _number(row.get("executable_close_debit"))
        midpoint = midpoint_close_debit(row.get("legs") or [])
        if executable is None or midpoint is None or quantity <= 0:
            continue
        friction = max(0.0, executable - midpoint) * 100.0 * quantity
        return {
            "status": "measured",
            "midpoint_close_debit": midpoint,
            "executable_close_debit": executable,
            "friction_dollars": round(friction, 2),
            "method": "buy_short_ask_sell_long_bid_debit_minus_midpoint_debit",
        }
    return {"status": "unavailable", "friction_dollars": None}


def _volatility_edge(candidate: dict[str, Any]) -> dict[str, Any]:
    source = candidate.get("volatility_edge") if isinstance(candidate.get("volatility_edge"), dict) else {}
    return {
        "status": source.get("status") or "unavailable",
        "atm_iv_annualized_pct": _number(source.get("atm_iv_annualized_pct")),
        "rv_forecast_annualized_pct": _number(source.get("rv_forecast_annualized_pct")),
        "net_vol_premium_after_event_pct": _number(source.get("net_vol_premium_after_event_pct")),
        "method": source.get("method_version"),
        "dollar_attribution_available": False,
    }


def _signal_edge(candidate: dict[str, Any]) -> dict[str, Any]:
    context = candidate.get("strategy_context") if isinstance(candidate.get("strategy_context"), dict) else {}
    return_bps = _number(context.get("underlying_return_bps"))
    return {
        "status": "measured" if return_bps is not None else "unavailable",
        "underlying_return_bps": return_bps,
        "dollar_attribution_available": False,
    }


def _liquidity_sweep_cohort(setup: dict[str, Any]) -> dict[str, Any]:
    regime = setup.get("regime_context") if isinstance(setup.get("regime_context"), dict) else {}
    context = regime.get("liquidity_sweep") if isinstance(regime.get("liquidity_sweep"), dict) else {}
    status = str(context.get("status") or "unavailable")
    events = [row for row in (context.get("events") or []) if isinstance(row, dict)]
    directions = sorted({str(row.get("direction")) for row in events if row.get("direction")})
    levels = sorted({str(row.get("level")) for row in events if row.get("level")})
    if status != "available":
        bucket = "unavailable"
    elif not directions:
        bucket = "no_confirmed_proxy_event"
    elif len(directions) == 1:
        bucket = f"{directions[0]}_proxy"
    else:
        bucket = "mixed_proxy_events"
    return {
        "bucket": bucket,
        "status": status,
        "event_count": len(events),
        "directions": directions,
        "levels": levels,
        "execution_authority": False,
    }


def build_report(
    evidence_rows: Iterable[dict[str, Any]],
    twin_rows: Iterable[dict[str, Any]],
    nbbo_payload: dict[str, Any],
) -> dict[str, Any]:
    setups = [row for row in evidence_rows if row.get("type") == "matched_setup"]
    candidates, marks, twin_outcomes = _index_twin(twin_rows)
    nbbo_outcomes = _nbbo_outcomes(nbbo_payload)
    setup_reports: list[dict[str, Any]] = []
    all_pnls: list[float] = []
    source_counts: Counter[str] = Counter()
    sweep_primary_pnls: dict[str, list[float]] = defaultdict(list)
    sweep_setup_counts: Counter[str] = Counter()

    for setup in setups:
        expressions: list[dict[str, Any]] = []
        for expression in setup.get("expressions") or []:
            candidate_id = str(expression.get("candidate_id") or "")
            if not candidate_id:
                expressions.append({
                    "expression_type": expression.get("expression_type"),
                    "strategy": expression.get("strategy"),
                    "status": expression.get("status"),
                    "candidate_id": None,
                    "net_pnl_dollars": 0.0 if expression.get("strategy") == "no_trade" else None,
                })
                continue
            candidate = candidates.get(candidate_id, {})
            outcome = _outcome(candidate_id, twin_outcomes, nbbo_outcomes)
            quantity = int(outcome.get("quantity") or _number(candidate.get("effective_qty")) or 0)
            pnl = _number(outcome.get("net_pnl_dollars"))
            if pnl is not None:
                all_pnls.append(pnl)
                source_counts[str(outcome.get("source") or "unknown")] += 1
            expressions.append({
                "expression_type": expression.get("expression_type"),
                "strategy": candidate.get("strategy") or expression.get("strategy"),
                "candidate_id": candidate_id,
                "status": outcome.get("status"),
                "outcome_source": outcome.get("source"),
                "net_pnl_dollars": pnl,
                "reason": outcome.get("reason"),
                "signal_edge": _signal_edge(candidate),
                "volatility_edge": _volatility_edge(candidate),
                "entry_execution_edge": _entry_execution(candidate, quantity),
                "exit_execution_edge": _exit_execution(marks.get(candidate_id, []), quantity),
                "management_edge": {
                    "status": "awaiting_preregistered_exit_policy_replay",
                    "dollar_attribution_available": False,
                },
                "interaction_residual_dollars": None,
            })
        primary = next((row for row in expressions if row.get("expression_type") == "primary"), None)
        resolved = [row for row in expressions if _number(row.get("net_pnl_dollars")) is not None]
        primary_pnl = _number((primary or {}).get("net_pnl_dollars"))
        alternatives = [
            row for row in resolved
            if row.get("expression_type") not in {"primary", "no_trade"}
        ]
        best_alternative = max(
            alternatives,
            key=lambda row: float(row.get("net_pnl_dollars") or 0.0),
            default=None,
        )
        structure_comparison = {
            "status": "measured" if primary_pnl is not None and best_alternative else "insufficient_matched_outcomes",
            "primary_pnl_dollars": primary_pnl,
            "best_alternative_expression": (best_alternative or {}).get("expression_type"),
            "best_alternative_pnl_dollars": _number((best_alternative or {}).get("net_pnl_dollars")),
            "best_alternative_minus_primary_dollars": round(
                float(best_alternative["net_pnl_dollars"]) - primary_pnl,
                2,
            ) if primary_pnl is not None and best_alternative else None,
        }
        sweep_cohort = _liquidity_sweep_cohort(setup)
        sweep_setup_counts[sweep_cohort["bucket"]] += 1
        if primary_pnl is not None:
            sweep_primary_pnls[sweep_cohort["bucket"]].append(primary_pnl)
        setup_reports.append({
            "setup_id": setup.get("setup_id"),
            "recorded_at": setup.get("recorded_at"),
            "source_strategy": setup.get("source_strategy"),
            "underlying": setup.get("underlying"),
            "expressions": expressions,
            "structure_edge": structure_comparison,
            "liquidity_sweep_cohort": sweep_cohort,
        })

    resolved_setup_count = sum(
        any(_number(row.get("net_pnl_dollars")) is not None for row in setup["expressions"])
        for setup in setup_reports
    )
    blockers = []
    if resolved_setup_count < 30:
        blockers.append("Fewer than 30 matched setups have any resolved expression.")
    if not nbbo_outcomes:
        blockers.append("No licensed OPRA curriculum outcomes are available for attribution.")
    sweep_attribution = {
        bucket: {
            "setup_count": count,
            "resolved_primary_count": len(sweep_primary_pnls.get(bucket, [])),
            "aggregate_primary_pnl_dollars": round(sum(sweep_primary_pnls.get(bucket, [])), 2),
            "average_primary_pnl_dollars": round(mean(sweep_primary_pnls[bucket]), 2)
            if sweep_primary_pnls.get(bucket) else None,
        }
        for bucket, count in sorted(sweep_setup_counts.items())
    }
    return {
        "schema_version": SCHEMA_VERSION,
        "provider": "options_edge_attribution_report",
        "mode": "read_only_matched_options_attribution",
        "setup_count": len(setup_reports),
        "resolved_setup_count": resolved_setup_count,
        "resolved_expression_count": len(all_pnls),
        "outcome_source_counts": dict(sorted(source_counts.items())),
        "aggregate_net_pnl_dollars": round(sum(all_pnls), 2),
        "average_net_pnl_dollars": round(mean(all_pnls), 2) if all_pnls else None,
        "liquidity_sweep_attribution": {
            "cohorts": sweep_attribution,
            "promotion_authority": "blocked",
            "note": "Cohorts are diagnostic until strategy-specific walk-forward validation passes.",
        },
        "setups": setup_reports,
        "blockers": blockers,
        "promotion_authority": "blocked",
        "execution_enabled": False,
        "can_submit_orders": False,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Build read-only matched options edge attribution")
    parser.add_argument("--evidence", type=Path, default=DEFAULT_EVIDENCE_PATH)
    parser.add_argument("--twin", type=Path, default=DEFAULT_TWIN_PATH)
    parser.add_argument("--nbbo", type=Path, default=DEFAULT_NBBO_PATH)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUTPUT_PATH)
    parser.add_argument("--print", action="store_true", dest="print_report")
    args = parser.parse_args()
    report = build_report(
        read_evidence_records(args.evidence),
        read_twin_records(args.twin),
        _read_json(args.nbbo),
    )
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    if args.print_report:
        print(json.dumps(report, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()

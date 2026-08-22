#!/usr/bin/env python3
"""Prior-date-only MES candidate router for forward shadow evidence.

The router may select which frozen candidate to observe next. It has no order
authority and cannot promote a candidate to Practice, Combine, or funded use.
"""
from __future__ import annotations

import argparse
import json
import math
from datetime import date, datetime, timezone
from pathlib import Path
from statistics import fmean, stdev
from typing import Any, Iterable


DEFAULT_LEDGER = Path(__file__).resolve().parents[1] / "data" / "topstep_forward_candidate_outcomes.jsonl"
DEFAULT_OUTPUT = Path(__file__).resolve().parents[1] / "data" / "topstep_prior_date_route.json"


def _max_drawdown(pnls: list[float]) -> float:
    equity = peak = worst = 0.0
    for pnl in pnls:
        equity += pnl
        peak = max(peak, equity)
        worst = max(worst, peak - equity)
    return round(worst, 2)


def summarize_candidate(rows: list[dict[str, Any]]) -> dict[str, Any]:
    pnls = [float(row["pnl_after_double_cost"]) for row in rows]
    wins = sum(value > 0 for value in pnls)
    gross_profit = sum(value for value in pnls if value > 0)
    gross_loss = -sum(value for value in pnls if value < 0)
    expectancy = fmean(pnls) if pnls else 0.0
    standard_error = stdev(pnls) / math.sqrt(len(pnls)) if len(pnls) >= 2 else None
    lcb = expectancy - 1.645 * standard_error if standard_error is not None else None
    return {
        "candidate_id": str(rows[0]["candidate_id"]),
        "resolved_outcomes": len(rows),
        "winning_outcomes": wins,
        "losing_outcomes": sum(value < 0 for value in pnls),
        "first_session_date": min(str(row["session_date"]) for row in rows),
        "last_session_date": max(str(row["session_date"]) for row in rows),
        "expectancy_after_double_cost": round(expectancy, 4),
        "expectancy_lcb_90": round(lcb, 4) if lcb is not None else None,
        "profit_factor_after_double_cost": round(gross_profit / gross_loss, 4) if gross_loss else None,
        "win_rate": round(wins / len(pnls), 4) if pnls else 0.0,
        "max_drawdown_dollars": _max_drawdown(pnls),
    }


def route_candidate(
    rows: Iterable[dict[str, Any]],
    *,
    route_date: date,
    trailing_outcomes: int = 60,
    minimum_outcomes: int = 30,
    minimum_profit_factor: float = 1.20,
    maximum_drawdown: float = 500.0,
) -> dict[str, Any]:
    if trailing_outcomes < minimum_outcomes or minimum_outcomes < 2:
        raise ValueError("Routing windows must retain at least two outcomes")
    prior: dict[str, list[dict[str, Any]]] = {}
    rejected_future_rows = 0
    malformed_rows = 0
    for row in rows:
        try:
            session = date.fromisoformat(str(row["session_date"]))
            candidate_id = str(row["candidate_id"]).strip()
            pnl = float(row["pnl_after_double_cost"])
        except (KeyError, TypeError, ValueError):
            malformed_rows += 1
            continue
        if not candidate_id or not math.isfinite(pnl) or str(row.get("status") or "resolved") != "resolved":
            malformed_rows += 1
            continue
        if session >= route_date:
            rejected_future_rows += 1
            continue
        clean = dict(row)
        clean["pnl_after_double_cost"] = pnl
        prior.setdefault(candidate_id, []).append(clean)

    summaries: list[dict[str, Any]] = []
    for candidate_id, candidate_rows in sorted(prior.items()):
        candidate_rows.sort(key=lambda row: str(row["session_date"]))
        summary = summarize_candidate(candidate_rows[-trailing_outcomes:])
        pf = summary["profit_factor_after_double_cost"]
        reasons: list[str] = []
        if summary["resolved_outcomes"] < minimum_outcomes:
            reasons.append("insufficient_resolved_outcomes")
        if summary["expectancy_after_double_cost"] <= 0:
            reasons.append("nonpositive_double_cost_expectancy")
        if summary["expectancy_lcb_90"] is None or summary["expectancy_lcb_90"] <= 0:
            reasons.append("nonpositive_expectancy_lcb_90")
        if (pf is None and summary["losing_outcomes"] > 0) or (pf is not None and pf < minimum_profit_factor):
            reasons.append("profit_factor_below_threshold")
        if summary["max_drawdown_dollars"] > maximum_drawdown:
            reasons.append("drawdown_above_threshold")
        summary["shadow_route_eligible"] = not reasons
        summary["reasons"] = reasons or ["forward_shadow_gate_passed"]
        summaries.append(summary)

    eligible = [row for row in summaries if row["shadow_route_eligible"]]
    eligible.sort(
        key=lambda row: (
            float(row["expectancy_lcb_90"]),
            float(row["profit_factor_after_double_cost"] or (1_000_000.0 if row["losing_outcomes"] == 0 else 0.0)),
        ),
        reverse=True,
    )
    selected = eligible[0]["candidate_id"] if eligible else None
    return {
        "schema_version": 1,
        "provider": "topstep_prior_date_candidate_router",
        "generated_at_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "route_date": route_date.isoformat(),
        "mode": "forward_shadow_only",
        "execution_enabled": False,
        "can_submit_orders": False,
        "selected_shadow_candidate": selected,
        "routing_status": "selected_for_shadow_observation" if selected else "no_candidate_passed_shadow_gate",
        "prior_date_enforced": True,
        "rejected_same_or_future_rows": rejected_future_rows,
        "malformed_rows": malformed_rows,
        "thresholds": {
            "trailing_outcomes": trailing_outcomes,
            "minimum_outcomes": minimum_outcomes,
            "minimum_profit_factor": minimum_profit_factor,
            "maximum_drawdown_dollars": maximum_drawdown,
            "expectancy_lcb_90": ">0",
        },
        "candidates": summaries,
        "warning": "A shadow route is not Practice, Combine, funded, or live-trading approval.",
    }


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8-sig").splitlines():
        if not line.strip():
            continue
        try:
            value = json.loads(line)
        except json.JSONDecodeError:
            rows.append({"status": "malformed"})
            continue
        rows.append(value if isinstance(value, dict) else {"status": "malformed"})
    return rows


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ledger", type=Path, default=DEFAULT_LEDGER)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--route-date", type=date.fromisoformat, default=date.today())
    args = parser.parse_args()
    report = route_candidate(load_jsonl(args.ledger), route_date=args.route_date)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

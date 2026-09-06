#!/usr/bin/env python3
"""Freeze a read-only lifecycle plan for completed-bar radar confirmations.

The 30-minute break-even rule is an explicit *experiment arm*, not a promoted
management rule.  Each plan retains the initial stop, one-R reference, 2R
target, and a time-stop timestamp so it can be evaluated later without
rewriting history or sending a broker instruction.
"""
from __future__ import annotations

import argparse
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Mapping

VIBE_HOME = Path.home() / ".vibe-trading"
RADAR_PATH = VIBE_HOME / "reports" / "intraday-opportunity-radar.json"
REPORT_PATH = VIBE_HOME / "reports" / "intraday-trade-lifecycle-shadow.json"
TIME_STOP_MINUTES = 30


def _number(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _timestamp(value: Any) -> datetime | None:
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None


def decision_contract(candidate: Mapping[str, Any]) -> dict[str, Any]:
    """Return a fail-closed manual-review decision; it never authorizes an order."""
    confirmation = candidate.get("price_action_confirmation") if isinstance(candidate.get("price_action_confirmation"), Mapping) else {}
    hard_gates = candidate.get("hard_gates") if isinstance(candidate.get("hard_gates"), Mapping) else {}
    evidence = candidate.get("a_plus_evidence") if isinstance(candidate.get("a_plus_evidence"), Mapping) else {}
    validation = evidence.get("validation") if isinstance(evidence.get("validation"), Mapping) else {}
    primary = candidate.get("primary_catalyst") if isinstance(candidate.get("primary_catalyst"), Mapping) else {}
    rvol = candidate.get("time_matched_rvol") if isinstance(candidate.get("time_matched_rvol"), Mapping) else {}
    blockers = [str(item) for item in candidate.get("blockers") or []]
    reasons: list[str] = []
    confirmed = str(confirmation.get("state") or "") in {"bullish_confirmed", "bearish_confirmed"}
    levels_complete = all(_number(candidate.get(key)) is not None for key in ("entry", "invalidation", "target"))
    gates_pass = bool(hard_gates) and all(value is True for value in hard_gates.values())
    if not confirmed:
        reasons.append("completed_5m_confirmation_missing")
    if not levels_complete:
        reasons.append("entry_stop_target_missing")
    if blockers or not gates_pass:
        reasons.append("tradeability_or_hard_gate_unresolved")
    if str(rvol.get("status") or "") != "available_iex_relative":
        reasons.append("same_time_rvol_unavailable")
    elif (_number(rvol.get("value")) or 0.0) < 1.0:
        reasons.append("same_time_rvol_below_1")
    if str(primary.get("status") or "") != "verified_primary_sec":
        reasons.append("primary_catalyst_not_verified")
    if str(validation.get("status") or "") != "validated_strategy_family":
        reasons.append("strategy_family_not_validated")
    grade = str(candidate.get("grade") or "")
    if reasons:
        outcome = "do_not_take"
    elif grade.startswith("A"):
        outcome = "a_plus_manual_review_eligible"
    elif grade.startswith("B"):
        outcome = "b_plus_manual_review_eligible"
    else:
        outcome = "do_not_take"
        reasons.append("grade_below_b_plus")
    return {
        "outcome": outcome,
        "grade": grade or "ungraded",
        "reasons": reasons,
        "required_human_checks": [
            "revalidate current quote and spread immediately before any manual action",
            "verify portfolio risk, correlation, and daily-loss constraints",
            "confirm the plan is still timely; do not chase a consumed move",
        ],
        "authority": "decision_support_only_no_order_or_execution_authority",
        "execution_enabled": False,
        "can_submit_orders": False,
    }


def lifecycle_plan(candidate: Mapping[str, Any]) -> dict[str, Any] | None:
    confirmation = candidate.get("price_action_confirmation") if isinstance(candidate.get("price_action_confirmation"), Mapping) else {}
    direction = str(candidate.get("direction") or "").lower()
    entry, stop, target = (_number(candidate.get(key)) for key in ("entry", "invalidation", "target"))
    observed = _timestamp(confirmation.get("bar_completed_at"))
    if direction not in {"bullish", "bearish"} or entry is None or stop is None or target is None or observed is None:
        return None
    if str(confirmation.get("state") or "") not in {"bullish_confirmed", "bearish_confirmed"}:
        return None
    risk = abs(entry - stop)
    if risk <= 0:
        return None
    sign = 1.0 if direction == "bullish" else -1.0
    one_r = entry + sign * risk
    return {
        "lifecycle_id": f"{str(candidate.get('symbol') or '').upper()}:{observed.astimezone(timezone.utc).isoformat()}",
        "symbol": str(candidate.get("symbol") or "").upper(),
        "lane_rank": candidate.get("lane_rank"),
        "grade": candidate.get("grade"),
        "setup": candidate.get("setup"),
        "direction": direction,
        "state": "confirmed_shadow_plan_pending_outcome",
        "confirmed_at": observed.astimezone(timezone.utc).isoformat().replace("+00:00", "Z"),
        "entry": round(entry, 4),
        "initial_stop": round(stop, 4),
        "one_r_reference": round(one_r, 4),
        "target_2r": round(target, 4),
        "time_stop_at": (observed + timedelta(minutes=TIME_STOP_MINUTES)).astimezone(timezone.utc).isoformat().replace("+00:00", "Z"),
        "exit_policy_arms": [
            {"id": "control_initial_stop_2r", "rule": "initial stop remains active until stop or 2R target"},
            {"id": "experiment_break_even_30m_after_1r", "rule": "at 30 minutes, move stop to entry only if price first reached +1R"},
        ],
        "promotion_status": "unvalidated_shadow_experiment_only",
        "decision_contract": decision_contract(candidate),
        "authority": "lifecycle_observation_only_no_alert_order_or_broker_action",
        "execution_enabled": False,
        "can_submit_orders": False,
    }


def build_report(radar: Mapping[str, Any]) -> dict[str, Any]:
    candidates = [row for row in radar.get("ranked_candidates") or [] if isinstance(row, Mapping)]
    plans = [plan for row in candidates if (plan := lifecycle_plan(row)) is not None]
    plans.sort(key=lambda row: (float(row.get("lane_rank") or 10_000), str(row.get("symbol") or "")))
    return {
        "schema_version": 1,
        "provider": "intraday_trade_lifecycle_shadow",
        "mode": "read_only_preregistered_exit_experiment",
        "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "radar_date": radar.get("date"),
        "radar_as_of_et": radar.get("as_of_et"),
        "time_stop_minutes": TIME_STOP_MINUTES,
        "plans": plans,
        "summary": {"confirmed_plans": len(plans), "promotion_status": "unvalidated_shadow_experiment_only"},
        "execution_enabled": False,
        "can_submit_orders": False,
    }


def _read(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--radar-path", type=Path, default=RADAR_PATH)
    parser.add_argument("--report-path", type=Path, default=REPORT_PATH)
    args = parser.parse_args()
    report = build_report(_read(args.radar_path))
    args.report_path.parent.mkdir(parents=True, exist_ok=True)
    args.report_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"Intraday lifecycle shadow: plans={report['summary']['confirmed_plans']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

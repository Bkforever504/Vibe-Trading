#!/usr/bin/env python3
"""Build a two-sided, read-only tactical plan from normalized cockpit candidates.

The plan never manufactures a missing direction and fails closed when one
source describes inconsistent levels.  It is presentation and review logic;
it has no broker imports or order authority.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Iterable, Mapping


def _mapping(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _number(value: Any) -> float | None:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if result == result else None


def _direction(value: Any) -> str:
    text = str(value or "").strip().lower()
    if text in {"bull", "bullish", "long", "call", "up"}:
        return "bullish"
    if text in {"bear", "bearish", "short", "put", "down"}:
        return "bearish"
    return "neutral"


def _target(candidate: Mapping[str, Any], index: int) -> float | None:
    plan = _mapping(candidate.get("trade_plan"))
    market_structure = _mapping(_mapping(candidate.get("evidence")).get("market_structure"))
    exit_plan = _mapping(market_structure.get("exit_plan"))
    targets = exit_plan.get("targets") if isinstance(exit_plan.get("targets"), list) else plan.get("targets")
    rows = targets if isinstance(targets, list) else []
    if index < len(rows):
        return _number(_mapping(rows[index]).get("price"))
    return _number(candidate.get("target")) if index == 0 else None


def _level_claims(candidate: Mapping[str, Any]) -> list[tuple[str, float]]:
    plan = _mapping(candidate.get("trade_plan"))
    timing = _mapping(plan.get("entry_timing"))
    evidence = _mapping(candidate.get("evidence"))
    trade_levels = _mapping(evidence.get("trade_levels"))
    next_session = _mapping(evidence.get("next_session_plan"))
    market_structure = _mapping(evidence.get("market_structure"))
    structure_entry = _mapping(market_structure.get("entry_plan"))
    raw = (
        ("candidate.entry", candidate.get("entry")),
        ("trade_plan.entry_trigger", plan.get("entry_trigger")),
        ("entry_timing.entry_trigger", timing.get("entry_trigger")),
        ("evidence.trade_levels.confirmation_trigger", trade_levels.get("confirmation_trigger")),
        ("evidence.next_session_plan.entry_trigger", next_session.get("entry_trigger")),
        ("evidence.market_structure.entry_plan.trigger", structure_entry.get("trigger")),
    )
    return [(name, parsed) for name, value in raw if (parsed := _number(value)) is not None]


def _claim_conflict(candidate: Mapping[str, Any], branch: str) -> dict[str, Any] | None:
    claims = _level_claims(candidate)
    if len(claims) < 2:
        return None
    values = [value for _, value in claims]
    reference = max(abs(value) for value in values) or 1.0
    tolerance = max(0.01, reference * 0.0005)
    if max(values) - min(values) <= tolerance:
        return None
    return {
        "field": f"{branch}.trigger",
        "reason": "same_source_trigger_claims_disagree",
        "tolerance": round(tolerance, 6),
        "claims": [{"path": name, "value": value} for name, value in claims],
    }


def _branch(candidate: Mapping[str, Any] | None, name: str) -> dict[str, Any]:
    if not candidate:
        return {
            "state": "UNAVAILABLE",
            "direction": "bullish" if name == "bull_case" else "bearish",
            "setup": None,
            "trigger": None,
            "entry_zone": {"status": "unavailable", "low": None, "high": None},
            "confirmation_required": "No source-qualified branch is available; do not manufacture one.",
            "retest_required": True,
            "stop": None,
            "t1": None,
            "t2": None,
            "time_stop": None,
            "entry_timing": None,
            "blockers": ["directional_branch_unavailable"],
            "source_labels": [],
            "execution_enabled": False,
            "can_submit_orders": False,
        }

    plan = _mapping(candidate.get("trade_plan"))
    timing = _mapping(plan.get("entry_timing"))
    evidence = _mapping(candidate.get("evidence"))
    market_structure = _mapping(evidence.get("market_structure"))
    structure_entry = _mapping(market_structure.get("entry_plan"))
    structure_exit = _mapping(market_structure.get("exit_plan"))
    trigger = _number(plan.get("entry_trigger")) or _number(candidate.get("entry"))
    stop = _number(plan.get("invalidation")) or _number(candidate.get("stop"))
    zone = _mapping(structure_entry.get("entry_zone")) or _mapping(timing.get("entry_zone"))
    actionability = str(candidate.get("actionability") or "research_only")
    state = {
        "shadow_ready": "READY_TO_REVIEW",
        "wait": "WAIT",
        "late_no_chase": "NO_CHASE",
        "invalid": "INVALID",
    }.get(actionability, "RESEARCH_ONLY")
    source_labels = candidate.get("source_labels")
    if not isinstance(source_labels, list):
        source_labels = evidence.get("source_labels") if isinstance(evidence.get("source_labels"), list) else []
    conflict = _claim_conflict(candidate, name)
    blockers = [str(value) for value in candidate.get("blockers") or []]
    if conflict:
        state = "INVALID"
        blockers.append("contradictory_source_levels")
    return {
        "state": state,
        "direction": _direction(candidate.get("direction")),
        "setup": candidate.get("setup"),
        "grade": candidate.get("grade"),
        "decision_score": _number(candidate.get("decision_score")),
        "trigger": trigger,
        "entry_zone": {
            "status": str(zone.get("status") or ("source_defined" if zone.get("low") is not None else "unavailable")),
            "low": _number(zone.get("low")) if zone else trigger,
            "high": _number(zone.get("high")) if zone else trigger,
        },
        "confirmation_required": timing.get("confirmation_required") or structure_entry.get("instruction") or "Wait for a completed 5-minute close, then a hold or retest.",
        "retest_required": True,
        "stop": stop,
        "t1": _target(candidate, 0),
        "t2": _target(candidate, 1),
        "time_stop": structure_exit.get("time_stop"),
        "entry_timing": timing or None,
        "blockers": list(dict.fromkeys(blockers)),
        "source": candidate.get("source"),
        "source_labels": [str(value) for value in source_labels],
        "conflict": conflict,
        "execution_enabled": False,
        "can_submit_orders": False,
    }


def _best(rows: Iterable[Mapping[str, Any]], direction: str) -> Mapping[str, Any] | None:
    matches = [row for row in rows if _direction(row.get("direction")) == direction]
    return max(matches, key=lambda row: float(_number(row.get("decision_score")) or 0.0), default=None)


def _geometry_conflicts(branch: Mapping[str, Any], name: str) -> list[dict[str, Any]]:
    direction = _direction(branch.get("direction"))
    trigger = _number(branch.get("trigger"))
    stop = _number(branch.get("stop"))
    targets = [value for value in (_number(branch.get("t1")), _number(branch.get("t2"))) if value is not None]
    if trigger is None or direction not in {"bullish", "bearish"}:
        return []
    conflicts: list[dict[str, Any]] = []
    if stop is not None and ((direction == "bullish" and stop >= trigger) or (direction == "bearish" and stop <= trigger)):
        conflicts.append({
            "field": f"{name}.stop",
            "reason": f"{direction}_stop_must_be_{'below' if direction == 'bullish' else 'above'}_trigger",
            "claims": [{"path": f"{name}.trigger", "value": trigger}, {"path": f"{name}.stop", "value": stop}],
        })
    for index, target in enumerate(targets, start=1):
        invalid = (direction == "bullish" and target <= trigger) or (direction == "bearish" and target >= trigger)
        if invalid:
            conflicts.append({
                "field": f"{name}.t{index}",
                "reason": f"{direction}_target_must_be_{'above' if direction == 'bullish' else 'below'}_trigger",
                "claims": [{"path": f"{name}.trigger", "value": trigger}, {"path": f"{name}.t{index}", "value": target}],
            })
    if len(targets) == 2 and ((direction == "bullish" and targets[1] < targets[0]) or (direction == "bearish" and targets[1] > targets[0])):
        conflicts.append({"field": f"{name}.targets", "reason": "targets_not_ordered_away_from_trigger"})
    return conflicts


def build_tactical_plan(
    candidates: Iterable[Mapping[str, Any]],
    *,
    primary_symbol: str | None = None,
    market_state: Mapping[str, Any] | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Return a two-sided review plan without inventing missing evidence."""
    now = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    rows = [dict(row) for row in candidates if isinstance(row, Mapping)]
    symbol = str(primary_symbol or "").upper()
    if not symbol and rows:
        symbol = str(rows[0].get("symbol") or "").upper()
    symbol_rows = [row for row in rows if str(row.get("symbol") or "").upper() == symbol]
    bull = _branch(_best(symbol_rows, "bullish"), "bull_case")
    bear = _branch(_best(symbol_rows, "bearish"), "bear_case")
    conflicts = [branch["conflict"] for branch in (bull, bear) if branch.get("conflict")]
    conflicts.extend(_geometry_conflicts(bull, "bull_case"))
    conflicts.extend(_geometry_conflicts(bear, "bear_case"))

    bull_trigger = _number(bull.get("trigger"))
    bear_trigger = _number(bear.get("trigger"))
    if bull_trigger is not None and bear_trigger is not None and bear_trigger >= bull_trigger:
        conflicts.append({
            "field": "no_trade_zone",
            "reason": "bearish_trigger_must_be_below_bullish_trigger",
            "claims": [{"path": "bear_case.trigger", "value": bear_trigger}, {"path": "bull_case.trigger", "value": bull_trigger}],
        })

    if conflicts:
        status = "INVALID_SOURCE_CONFLICT"
        bull["state"] = "INVALID" if bull.get("trigger") is not None else bull["state"]
        bear["state"] = "INVALID" if bear.get("trigger") is not None else bear["state"]
    elif any(branch["state"] == "READY_TO_REVIEW" for branch in (bull, bear)):
        status = "READY_TO_REVIEW"
    elif any(branch["state"] in {"WAIT", "NO_CHASE", "RESEARCH_ONLY"} for branch in (bull, bear)):
        status = "WAIT_FOR_CONFIRMATION"
    else:
        status = "STAND_ASIDE"

    zone = {
        "status": "available",
        "low": bear_trigger,
        "high": bull_trigger,
        "instruction": "Stand aside while price remains between the bearish and bullish triggers.",
    } if not conflicts and bear_trigger is not None and bull_trigger is not None else {
        "status": "unavailable",
        "low": None,
        "high": None,
        "instruction": "A two-sided no-trade zone requires consistent source-qualified bull and bear triggers.",
    }

    state = dict(market_state or {})
    state.setdefault("source_labels", [])
    return {
        "schema_version": 1,
        "generated_at": now.isoformat().replace("+00:00", "Z"),
        "status": status,
        "symbol": symbol or None,
        "market_state": state,
        "bull_case": bull,
        "bear_case": bear,
        "no_trade_zone": zone,
        "cross_checks": {
            "level_consistency": "fail" if conflicts else "pass",
            "conflicts": conflicts,
            "rule": "Any contradictory level or inverted two-sided geometry forces stand-aside.",
        },
        "decision": "STAND_ASIDE" if conflicts or status == "STAND_ASIDE" else status,
        "execution_enabled": False,
        "can_submit_orders": False,
    }


__all__ = ["build_tactical_plan"]

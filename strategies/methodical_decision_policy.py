"""Hierarchical, paper-only entry policy with explicit abstention.

The policy separates safety, thesis, trigger, independent confirmation, and
uncertainty. It cannot submit orders. A broker-facing caller may use its result
only for paper routing and contract reduction.
"""
from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from strategies.decision_intelligence import Evidence, assess_decision_intelligence


REPORT_DIR = Path.home() / ".vibe-trading" / "reports"
POLICY_VERSION = "methodical-paper-v1"


@dataclass(frozen=True)
class MethodicalDecisionConfig:
    min_external_confirmations: int = 1
    market_force_min_confidence: float = 8.0
    exploration_contract_cap: int = 1
    catalyst_max_age_seconds: int = 26 * 60 * 60
    htf_max_age_seconds: int = 26 * 60 * 60
    market_force_max_age_seconds: int = 20 * 60
    garch_max_age_seconds: int = 12 * 60 * 60
    surface_max_age_seconds: int = 20 * 60
    heatmap_max_age_seconds: int = 20 * 60
    control_plane_max_age_seconds: int = 26 * 60 * 60
    trade_signal_max_age_seconds: int = 10 * 60


def _read_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
        return payload if isinstance(payload, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def _parse_timestamp(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)
    except (TypeError, ValueError):
        return None


def _source_health(
    report: dict[str, Any],
    *,
    now: datetime,
    max_age_seconds: int,
) -> dict[str, Any]:
    generated = _parse_timestamp(report.get("generated_at") or report.get("timestamp"))
    if not report:
        return {"status": "missing", "generated_at": None, "age_seconds": None}
    if generated is None:
        return {"status": "unverifiable", "generated_at": None, "age_seconds": None}
    age = max(0.0, (now - generated).total_seconds())
    return {
        "status": "current" if age <= max_age_seconds else "stale",
        "generated_at": generated.isoformat().replace("+00:00", "Z"),
        "age_seconds": round(age, 1),
        "max_age_seconds": max_age_seconds,
    }


def _symbol_row(report: dict[str, Any], symbol: str, keys: tuple[str, ...]) -> dict[str, Any]:
    for key in keys:
        rows = report.get(key)
        if not isinstance(rows, list):
            continue
        for row in rows:
            if isinstance(row, dict) and str(row.get("symbol") or "").upper() == symbol:
                return row
    return {}


def load_methodical_context(
    symbol: str,
    *,
    report_dir: Path = REPORT_DIR,
    now: datetime | None = None,
    config: MethodicalDecisionConfig = MethodicalDecisionConfig(),
) -> dict[str, Any]:
    """Load only point-in-time reports; stale sources cannot cast a vote."""
    now = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    symbol = str(symbol or "").upper()
    reports = {
        "catalyst": _read_json(report_dir / "market-catalyst-calendar.json"),
        "htf": _read_json(report_dir / "higher-timeframe-market-map.json"),
        "market_force": _read_json(report_dir / "market-force-score.json"),
        "garch": _read_json(report_dir / "garch-volatility-risk.json"),
        "heatmap": _read_json(report_dir / "options-liquidation-heatmap.json"),
        "surface": _read_json(report_dir / "options-surface-intelligence.json"),
        "consensus": _read_json(report_dir / "shadow-consensus-gate.json"),
        "kronos": _read_json(report_dir / "kronos-market-forecast.json"),
        "timesfm": _read_json(report_dir / "timesfm-market-forecast.json"),
        "control_plane": _read_json(report_dir / "profitability-control-plane.json"),
        "trade_signals": _read_json(report_dir / "trade-signal-generator.json"),
    }
    source_health = {
        "catalyst": _source_health(
            reports["catalyst"], now=now, max_age_seconds=config.catalyst_max_age_seconds
        ),
        "higher_timeframe": _source_health(
            reports["htf"], now=now, max_age_seconds=config.htf_max_age_seconds
        ),
        "market_force": _source_health(
            reports["market_force"], now=now, max_age_seconds=config.market_force_max_age_seconds
        ),
        "garch": _source_health(
            reports["garch"], now=now, max_age_seconds=config.garch_max_age_seconds
        ),
        "heatmap": _source_health(
            reports["heatmap"], now=now, max_age_seconds=config.heatmap_max_age_seconds
        ),
        "surface": _source_health(
            reports["surface"], now=now, max_age_seconds=config.surface_max_age_seconds
        ),
        "profitability_control_plane": _source_health(
            reports["control_plane"], now=now, max_age_seconds=config.control_plane_max_age_seconds
        ),
        "trade_signal_generator": _source_health(
            reports["trade_signals"], now=now, max_age_seconds=config.trade_signal_max_age_seconds
        ),
    }
    return {
        "symbol": symbol,
        "loaded_at": now.isoformat().replace("+00:00", "Z"),
        "source_health": source_health,
        "portfolio_kill_switch_active": bool(
            (reports["consensus"].get("portfolio_kill_switch") or {}).get("active")
            or (reports["consensus"].get("kill_switch") or {}).get("active")
        ),
        "catalyst": reports["catalyst"].get("today") or {},
        "higher_timeframe": _symbol_row(reports["htf"], symbol, ("items", "results")),
        "market_force": reports["market_force"],
        "garch": _symbol_row(reports["garch"], symbol, ("symbols", "items", "results")),
        # These sources are retained for location/risk telemetry, not direction votes.
        "heatmap_advisory": _symbol_row(reports["heatmap"], symbol, ("results", "items")),
        "surface_advisory": _symbol_row(reports["surface"], symbol, ("results", "items")),
        "kronos_advisory": _symbol_row(reports["kronos"], symbol, ("items", "results")),
        "timesfm_advisory": _symbol_row(reports["timesfm"], symbol, ("items", "results")),
        "profitability_control_plane": reports["control_plane"],
        "trade_signal": _symbol_row(reports["trade_signals"], symbol, ("ready_signals", "signals")),
    }


def _direction(setup: dict[str, Any]) -> str:
    right = str(setup.get("right") or "").upper()
    if right == "CALL":
        return "bullish"
    if right == "PUT":
        return "bearish"
    return "unknown"


def _finite_float(value: Any, default: float = 0.0) -> float:
    try:
        parsed = float(value)
        return parsed if math.isfinite(parsed) else default
    except (TypeError, ValueError):
        return default


def _profitability_lane(setup: dict[str, Any]) -> str:
    explicit = str(setup.get("profitability_lane") or "").strip()
    if explicit:
        return explicit
    strategy = str(setup.get("strategy") or "").lower()
    if "0dte" in strategy or "flip" in strategy:
        return "aggressive_long_0dte_options"
    if "condor" in strategy or "theta" in strategy or "credit" in strategy:
        return "volatility_premium"
    if "trend" in strategy:
        return "trend_participation"
    return strategy or "unknown"


def _unit_confidence(value: Any, default: float = 0.5) -> float:
    parsed = _finite_float(value, default)
    if parsed > 1.0:
        parsed /= 10.0
    return min(1.0, max(0.0, parsed))


def _option_execution_economics(setup: dict[str, Any]) -> tuple[float | None, float | None]:
    max_gain = _finite_float(setup.get("max_gain"), 0.0)
    max_loss = _finite_float(setup.get("max_loss"), 0.0)
    reward_risk = max_gain / max_loss if max_gain > 0 and max_loss > 0 else None
    expected_reward_per_contract = max_gain / max(1, int(setup.get("contracts") or 1)) if max_gain > 0 else 0.0
    if reward_risk is None:
        entry = _finite_float(setup.get("entry_price_est"), 0.0)
        target_multiplier = _finite_float(setup.get("profit_target_multiplier"), 0.0)
        stop_multiplier = _finite_float(setup.get("stop_multiplier"), 0.0)
        reward = entry * max(0.0, target_multiplier - 1.0) * 100.0
        risk = entry * max(0.0, 1.0 - stop_multiplier) * 100.0
        if reward > 0 and risk > 0:
            reward_risk = reward / risk
            expected_reward_per_contract = reward
    spread_cents = _finite_float(setup.get("spread_cents"), 0.0)
    friction_dollars = spread_cents if spread_cents > 0 else 0.0
    friction_to_reward = (
        friction_dollars / expected_reward_per_contract
        if friction_dollars > 0 and expected_reward_per_contract > 0
        else None
    )
    return reward_risk, friction_to_reward


def _build_intelligence_assessment(
    setup: dict[str, Any],
    *,
    direction: str,
    trigger_confirmed: bool,
    votes: list[dict[str, str]],
    health: dict[str, Any],
    hard_blockers: list[str],
    pattern_memory: dict[str, Any] | None,
) -> dict[str, Any]:
    evidence: list[Evidence] = []
    if trigger_confirmed:
        evidence.append(Evidence(
            source="fresh_price_trigger",
            family="price_structure",
            direction=direction,
            confidence=_unit_confidence(setup.get("confidence", setup.get("score")), 0.65),
            reliability=0.75,
            detail=str(setup.get("entry_evidence_gate") or ""),
        ))
    family_by_source = {
        "higher_timeframe": "trend",
        "market_force": "regime",
        "market_internals": "breadth",
        "tick_extreme": "microstructure",
    }
    for vote in votes:
        evidence.append(Evidence(
            source=vote["source"],
            family=family_by_source.get(vote["source"], vote["source"]),
            direction=vote["direction"],
            confidence=0.70,
            reliability=0.70,
            detail=vote["verdict"],
        ))
    if isinstance(pattern_memory, dict) and pattern_memory.get("review_ready"):
        pattern_status = str(pattern_memory.get("status") or "")
        pattern_direction = (
            direction if pattern_status == "positive_edge"
            else "bearish" if direction == "bullish" and pattern_status == "negative_edge"
            else "bullish" if direction == "bearish" and pattern_status == "negative_edge"
            else "unknown"
        )
        evidence.append(Evidence(
            source="multitimeframe_pattern_memory",
            family="historical_analogs",
            direction=pattern_direction,
            confidence=0.65,
            reliability=0.55,
            validated=bool(pattern_memory.get("forward_validated")),
            detail=pattern_status,
        ))

    current_sources = sum(
        (health.get(name) or {}).get("status") == "current"
        for name in ("higher_timeframe", "market_force", "garch", "catalyst")
    )
    data_completeness = current_sources / 4.0
    recommended = str(setup.get("day_type_recommended_strategy") or "").lower()
    strategy = str(setup.get("strategy") or "").lower()
    regime_compatible = None if not recommended else strategy in recommended or recommended in strategy
    reward_risk, friction_to_reward = _option_execution_economics(setup)
    forward_validated = bool(
        isinstance(pattern_memory, dict)
        and pattern_memory.get("forward_validated")
        and pattern_memory.get("status") == "positive_edge"
    )
    return assess_decision_intelligence(
        candidate_id=str(setup.get("telemetry_trade_id") or setup.get("option_symbol") or "alpaca-candidate"),
        desired_direction=direction,
        evidence=evidence,
        hard_blockers=hard_blockers,
        data_completeness=data_completeness,
        regime=str(setup.get("day_type") or "unknown"),
        regime_compatible=regime_compatible,
        reward_risk=reward_risk,
        friction_to_reward=friction_to_reward,
        forward_validated_edge=forward_validated,
    )


def _cast_vote(
    votes: list[dict[str, str]],
    *,
    source: str,
    observed: str,
    desired: str,
) -> None:
    if observed not in {"bullish", "bearish"}:
        return
    votes.append(
        {
            "source": source,
            "direction": observed,
            "verdict": "confirm" if observed == desired else "conflict",
        }
    )


def evaluate_methodical_entry(
    setup: dict[str, Any],
    context: dict[str, Any],
    *,
    paper: bool,
    config: MethodicalDecisionConfig = MethodicalDecisionConfig(),
) -> dict[str, Any]:
    """Classify an executable candidate into primary, exploration, or blocked."""
    symbol = str(setup.get("symbol") or "").upper()
    strategy = str(setup.get("strategy") or "unknown")
    direction = _direction(setup)
    requested_contracts = max(0, int(setup.get("contracts") or 0))
    hard_blockers: list[str] = []
    cautions: list[str] = []
    votes: list[dict[str, str]] = []

    if not paper:
        hard_blockers.append("methodical_policy_has_no_live_authority")
    if context.get("portfolio_kill_switch_active"):
        hard_blockers.append("portfolio_kill_switch_active")
    if direction == "unknown":
        hard_blockers.append("directional_thesis_missing")
    if requested_contracts < 1:
        hard_blockers.append("invalid_contract_count")

    evidence_gate = str(setup.get("entry_evidence_gate") or "")
    trigger_confirmed = evidence_gate.startswith("passed_")
    if not trigger_confirmed:
        hard_blockers.append("fresh_price_trigger_not_confirmed")

    health = context.get("source_health") if isinstance(context.get("source_health"), dict) else {}
    htf = context.get("higher_timeframe") if isinstance(context.get("higher_timeframe"), dict) else {}
    if (health.get("higher_timeframe") or {}).get("status") == "current":
        bias = str(htf.get("primary_bias") or "unknown")
        alignment = str(htf.get("intraday_alignment") or "unknown")
        if alignment == "aligned":
            _cast_vote(votes, source="higher_timeframe", observed=bias, desired=direction)
        elif htf:
            cautions.append(f"higher_timeframe_{alignment}")

    market_force = context.get("market_force") if isinstance(context.get("market_force"), dict) else {}
    if (health.get("market_force") or {}).get("status") == "current":
        confidence = _finite_float(market_force.get("confidence"))
        classification = str(market_force.get("classification") or "")
        observed = (
            "bullish" if "bullish" in classification
            else "bearish" if "bearish" in classification
            else "unknown"
        )
        if confidence >= config.market_force_min_confidence:
            _cast_vote(votes, source="market_force", observed=observed, desired=direction)
        elif market_force:
            cautions.append("market_force_below_confirmation_threshold")

    internals = setup.get("market_internals_context")
    if isinstance(internals, dict) and internals.get("status") == "ok":
        observed = (
            "bullish" if internals.get("add_bullish")
            else "bearish" if internals.get("add_bearish")
            else "unknown"
        )
        _cast_vote(votes, source="market_internals", observed=observed, desired=direction)

    tick = setup.get("tick_context")
    if isinstance(tick, dict) and tick.get("status") == "ok":
        observed = (
            "bullish" if tick.get("exhaustion_bottom")
            else "bearish" if tick.get("exhaustion_top")
            else "unknown"
        )
        _cast_vote(votes, source="tick_extreme", observed=observed, desired=direction)

    trade_signal = context.get("trade_signal") if isinstance(context.get("trade_signal"), dict) else {}
    trade_signal_current = (health.get("trade_signal_generator") or {}).get("status") == "current"
    trade_signal_direction = str(trade_signal.get("direction") or "unknown")
    trade_signal_match = bool(
        trade_signal
        and trade_signal_current
        and trade_signal.get("paper_consumable")
        and trade_signal_direction == direction
    )
    if trade_signal_match:
        cautions.append("trade_signal_contract_match")
    elif trade_signal and trade_signal_current and trade_signal.get("paper_consumable"):
        cautions.append("trade_signal_contract_direction_conflict")
    elif setup.get("requires_trade_signal_contract"):
        hard_blockers.append("required_trade_signal_contract_missing_or_stale")

    catalyst = context.get("catalyst") if isinstance(context.get("catalyst"), dict) else {}
    if (health.get("catalyst") or {}).get("status") == "current":
        if str(catalyst.get("max_impact") or "none") == "high":
            cautions.append("high_impact_event_regime")
        cautions.extend(f"catalyst_{item}" for item in catalyst.get("vetoes") or [])

    confirmations = [vote for vote in votes if vote["verdict"] == "confirm"]
    conflicts = [vote for vote in votes if vote["verdict"] == "conflict"]
    control_plane = (
        context.get("profitability_control_plane")
        if isinstance(context.get("profitability_control_plane"), dict)
        else {}
    )
    control_health = health.get("profitability_control_plane") or {}
    control_lane = _profitability_lane(setup)
    capital_decision = control_plane.get("capital_decision") or {}
    selected_lanes = {
        str(row.get("lane") or "")
        for row in capital_decision.get("selected") or []
        if isinstance(row, dict)
    }
    control_plane_allows_primary = True
    if control_plane and control_health.get("status") == "current":
        control_plane_allows_primary = (
            capital_decision.get("action") == "paper_candidates_available"
            and control_lane in selected_lanes
        )
        if not control_plane_allows_primary:
            cautions.append("profitability_control_plane_demotes_to_exploration")
    elif control_plane:
        cautions.append("profitability_control_plane_not_current")
    fibonacci = setup.get("fibonacci_structure")
    if isinstance(fibonacci, dict):
        fibonacci_status = str(fibonacci.get("status") or "unknown")
        if fibonacci_status == "confirmed":
            cautions.append("fibonacci_structure_confirmed_advisory_only")
        elif fibonacci_status == "invalidated":
            cautions.append("fibonacci_structure_conflict_advisory_only")
        elif fibonacci_status in {"unavailable", "outside_zone", "awaiting_confirmation", "deep_retracement"}:
            cautions.append(f"fibonacci_structure_{fibonacci_status}")
    pattern_memory = setup.get("pattern_memory_advisory")
    if isinstance(pattern_memory, dict):
        pattern_status = str(pattern_memory.get("status") or "unknown")
        if pattern_status == "positive_edge":
            cautions.append("pattern_memory_positive_edge_research_only")
        elif pattern_status == "negative_edge":
            cautions.append("pattern_memory_negative_edge_research_only")
        elif pattern_status in {"ambiguous", "insufficient_history", "unavailable"}:
            cautions.append(f"pattern_memory_{pattern_status}")
    directional_sources_current = sum(
        (health.get(name) or {}).get("status") == "current"
        for name in ("higher_timeframe", "market_force")
    )
    if directional_sources_current == 0 and not any(
        isinstance(setup.get(name), dict) and setup[name].get("status") == "ok"
        for name in ("market_internals_context", "tick_context")
    ):
        cautions.append("independent_directional_context_unavailable")

    intelligence_assessment = _build_intelligence_assessment(
        setup,
        direction=direction,
        trigger_confirmed=trigger_confirmed,
        votes=votes,
        health=health,
        hard_blockers=hard_blockers,
        pattern_memory=pattern_memory if isinstance(pattern_memory, dict) else None,
    )

    primary_eligible = (
        not hard_blockers
        and len(confirmations) >= config.min_external_confirmations
        and not conflicts
        and "high_impact_event_regime" not in cautions
        and control_plane_allows_primary
    )

    garch = context.get("garch") if isinstance(context.get("garch"), dict) else {}
    garch_current = (health.get("garch") or {}).get("status") == "current"
    risk_multiplier = (
        min(1.0, max(0.25, _finite_float(garch.get("position_size_multiplier"), 1.0)))
        if garch_current and garch.get("status") == "ok"
        else 1.0
    )
    if not garch_current:
        cautions.append("garch_context_not_current")

    if hard_blockers:
        status = "blocked"
        action = "stand_aside"
        adjusted_contracts = 0
    elif primary_eligible:
        status = "primary_eligible"
        action = "paper_enter_primary"
        adjusted_contracts = max(1, int(math.floor(requested_contracts * risk_multiplier)))
    else:
        status = "exploration_only"
        action = "paper_enter_exploration"
        adjusted_contracts = min(requested_contracts, config.exploration_contract_cap)

    fingerprint = "|".join(
        [
            POLICY_VERSION,
            symbol,
            strategy,
            direction,
            str(setup.get("orb_breakout_at") or setup.get("catalyst") or ""),
            str(setup.get("option_symbol") or ""),
        ]
    )
    return {
        "policy_version": POLICY_VERSION,
        "decision_id": hashlib.sha256(fingerprint.encode("utf-8")).hexdigest()[:20],
        "symbol": symbol,
        "strategy": strategy,
        "direction": direction,
        "status": status,
        "action": action,
        "allowed": status != "blocked",
        "requested_contracts": requested_contracts,
        "adjusted_contracts": adjusted_contracts,
        "risk_multiplier": round(risk_multiplier, 4),
        "trigger": {
            "confirmed": trigger_confirmed,
            "entry_evidence_gate": evidence_gate or None,
            "confidence_basis": setup.get("confidence_basis"),
        },
        "confirmations": confirmations,
        "conflicts": conflicts,
        "cautions": sorted(set(cautions)),
        "hard_blockers": sorted(set(hard_blockers)),
        "source_health": health,
        "advisory_sources_without_directional_authority": [
            "options_liquidation_heatmap",
            "unsigned_options_surface",
            "inferred_gex",
            "kronos_unvalidated",
            "timesfm_unvalidated",
            "social_media_narrative",
            "fibonacci_0_618_pending_placebo_validation",
        ],
        "fibonacci_structure": fibonacci if isinstance(fibonacci, dict) else None,
        "pattern_memory_advisory": pattern_memory if isinstance(pattern_memory, dict) else None,
        "trade_signal_contract": {
            "required": bool(setup.get("requires_trade_signal_contract")),
            "matched": trade_signal_match,
            "source_status": (health.get("trade_signal_generator") or {}).get("status"),
            "signal_id": trade_signal.get("signal_id"),
            "entry": trade_signal.get("entry"),
            "stop": trade_signal.get("stop"),
            "targets": trade_signal.get("targets") or [],
            "authority": "confirmation_and_target_context_only",
        },
        "profitability_control": {
            "lane": control_lane,
            "source_status": control_health.get("status") if control_plane else "missing",
            "capital_action": capital_decision.get("action") if control_plane else None,
            "selected_lanes": sorted(selected_lanes),
            "allows_primary": control_plane_allows_primary,
            "authority": "demotion_only",
        },
        "intelligence_assessment": intelligence_assessment,
        "invalidation": {
            "underlying_structure_level": setup.get("underlying_structure_level"),
            "hard_close_date": setup.get("hard_close_date"),
            "hard_close_time": setup.get("hard_close_time"),
        },
        "execution_enabled": False,
        "can_submit_orders": False,
        "authority": "paper_routing_and_size_reduction_only",
    }

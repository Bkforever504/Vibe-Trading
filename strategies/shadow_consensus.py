from __future__ import annotations

import json
import math
import os
from pathlib import Path
from typing import Any


DEFAULT_REPORT_PATH = Path(os.path.expanduser(r"~\.vibe-trading\reports\shadow-consensus-gate.json"))


def consensus_enabled() -> bool:
    return os.getenv("ENABLE_SHADOW_CONSENSUS_GATE", "false").lower() == "true"


def _empty_report(reason: str) -> dict[str, Any]:
    return {
        "available": False,
        "provider": "shadow_consensus_gate",
        "portfolio_kill_switch": {"active": False},
        "decisions": [],
        "unavailable_reason": reason,
    }


def load_report(report_path: Path | str | None = None) -> dict[str, Any]:
    path = Path(report_path) if report_path is not None else DEFAULT_REPORT_PATH
    try:
        if not path.exists():
            return _empty_report("missing_report")
        payload = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            return _empty_report("invalid_report")
        payload["available"] = True
        return payload
    except Exception as exc:
        report = _empty_report("read_error")
        report["error"] = str(exc)
        return report


def symbol_decision(symbol: str, report_path: Path | str | None = None) -> dict[str, Any]:
    report = load_report(report_path)
    symbol_upper = str(symbol or "").upper()
    for row in report.get("decisions", []):
        if str(row.get("symbol", "")).upper() == symbol_upper:
            decision = dict(row)
            decision["_report_available"] = bool(report.get("available"))
            decision["_kill_switch_active"] = bool((report.get("portfolio_kill_switch") or {}).get("active"))
            return decision
    return {
        "symbol": symbol_upper,
        "recommendation": "needs_review",
        "options_playbook": "none",
        "blockers": ["no_symbol_consensus"],
        "reasons": ["No shadow consensus row exists for this symbol."],
        "_report_available": bool(report.get("available")),
        "_kill_switch_active": bool((report.get("portfolio_kill_switch") or {}).get("active")),
    }


def _playbook_applicable_blockers(
    blockers: list[str],
    requested_playbook: str | None,
) -> tuple[list[str], list[str]]:
    """Separate execution facts from warnings produced for another payoff shape."""
    playbook = str(requested_playbook or "").lower()
    if playbook not in {"long_call", "long_put", "directional_long_call", "directional_long_put"}:
        return list(blockers), []

    short_premium_markers = (
        "credit/risk_is_below_minimum",
        "credit_to_risk",
        "iv_not_overpriced",
        "new_short_premium_blocked",
    )
    applicable: list[str] = []
    ignored: list[str] = []
    for blocker in blockers:
        normalized = str(blocker).lower()
        if any(marker in normalized for marker in short_premium_markers):
            ignored.append(blocker)
        else:
            applicable.append(blocker)
    return applicable, ignored


def entry_advice(
    symbol: str,
    contracts: int,
    *,
    report_path: Path | str | None = None,
    enabled: bool | None = None,
    requested_playbook: str | None = None,
) -> dict[str, Any]:
    if enabled is None:
        enabled = consensus_enabled()
    requested = max(0, int(contracts or 0))
    if not enabled:
        return {
            "enabled": False,
            "allowed": True,
            "adjusted_contracts": requested,
            "recommendation": "disabled",
            "options_playbook": "none",
            "blockers": [],
            "reasons": ["Shadow consensus gate disabled for this process."],
        }

    report = load_report(report_path)
    if not report.get("available"):
        return {
            "enabled": True,
            "allowed": True,
            "adjusted_contracts": requested,
            "recommendation": "needs_review",
            "options_playbook": "none",
            "blockers": ["shadow_consensus_unavailable"],
            "reasons": [f"Consensus report unavailable: {report.get('unavailable_reason', 'unknown')}"],
        }

    decision = symbol_decision(symbol, report_path)
    recommendation = str(decision.get("recommendation") or "needs_review")
    raw_blockers = list(decision.get("blockers") or [])
    blockers, ignored_blockers = _playbook_applicable_blockers(raw_blockers, requested_playbook)
    reasons = list(decision.get("reasons") or [])
    kill_switch_active = bool(decision.get("_kill_switch_active"))
    # This report combines alpha opinions produced for different playbooks. It is
    # not setup-direction aware, so those opinions may size a trade down but must
    # not veto an otherwise valid Flip setup. Only portfolio/execution safety
    # facts retain hard-block authority here.
    # options_liquidity_blocked is advisory only: nightly scan can't assess 0DTE
    # liquidity (contracts don't exist pre-market); execution-time MAX_SPREAD_PCT
    # is the real guard.
    hard_blockers = {
        "portfolio_kill_switch_active",
    }
    active_hard_blockers = sorted(hard_blockers.intersection(blockers))
    blocked = kill_switch_active or bool(active_hard_blockers)

    adjusted = requested
    if blocked:
        adjusted = 0
    elif recommendation in {"stand_aside", "needs_review", "size_down"} and requested > 1:
        adjusted = max(1, math.floor(requested / 2))

    return {
        "enabled": True,
        "allowed": not blocked,
        "adjusted_contracts": adjusted,
        "recommendation": recommendation,
        "options_playbook": decision.get("options_playbook", "none"),
        "blockers": blockers,
        "raw_blockers": raw_blockers,
        "ignored_wrong_playbook_blockers": ignored_blockers,
        "requested_playbook": requested_playbook,
        "hard_blockers": active_hard_blockers,
        "alpha_advisory_only": bool(blockers) and not blocked,
        "reasons": reasons,
        "decision": decision,
    }


def exit_advice(
    symbol: str,
    right: str | None = None,
    *,
    report_path: Path | str | None = None,
    enabled: bool | None = None,
) -> dict[str, Any]:
    if enabled is None:
        enabled = consensus_enabled()
    if not enabled:
        return {"enabled": False, "action": "hold", "can_submit_orders": False, "blockers": []}

    report = load_report(report_path)
    if not report.get("available"):
        return {
            "enabled": True,
            "action": "hold",
            "can_submit_orders": False,
            "blockers": ["shadow_consensus_unavailable"],
            "reasons": [f"Consensus report unavailable: {report.get('unavailable_reason', 'unknown')}"],
        }

    decision = symbol_decision(symbol, report_path)
    blockers = list(decision.get("blockers") or [])
    recommendation = str(decision.get("recommendation") or "needs_review")
    playbook = str(decision.get("options_playbook") or "none")
    kill_switch_active = bool(decision.get("_kill_switch_active"))
    action = "hold"
    review_recommended = False
    reasons = list(decision.get("reasons") or [])

    if kill_switch_active or recommendation == "stand_aside":
        review_recommended = True
    elif right and playbook in {
        "long_call",
        "long_put",
        "directional_long_call",
        "directional_long_put",
    }:
        expected_right = "CALL" if "call" in playbook else "PUT"
        if str(right).upper() != expected_right:
            review_recommended = True
            blockers.append("shadow_direction_flip")
            reasons.append(f"Shadow playbook is {playbook}, opposite open {right}.")

    exit_control_eligible = bool(decision.get("shadow_exit_control_eligible"))
    if review_recommended and exit_control_eligible:
        action = "review_exit"
    elif review_recommended:
        blockers.append("shadow_exit_not_oos_ready")
        reasons.append("Shadow exit control remains advisory until chronological holdout expectancy is positive.")

    return {
        "enabled": True,
        "action": action,
        "review_recommended": review_recommended,
        "shadow_exit_control_eligible": exit_control_eligible,
        "can_submit_orders": False,
        "recommendation": recommendation,
        "options_playbook": playbook,
        "blockers": blockers,
        "reasons": reasons,
        "decision": decision,
    }

#!/usr/bin/env python3
"""Create an append-only, shadow-only decision record for confirmed signals.

This is deliberately not an agent-voting or brokerage module.  It joins the
existing completed-bar scanner, consensus report, and learning report into a
single evidence chain.  Every confirmed candidate receives an explicit
``shadow_accepted`` or ``shadow_rejected`` decision, while every record keeps
``execution_enabled`` and ``can_submit_orders`` false.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from agent.observability.trace_context import new_trace_id

VIBE_HOME = Path.home() / ".vibe-trading"
REPORT_DIR = VIBE_HOME / "reports"
ALERTS_PATH = REPORT_DIR / "simple-price-action-alerts.json"
CONSENSUS_PATH = REPORT_DIR / "shadow-consensus-gate.json"
LEARNING_PATH = REPORT_DIR / "flip-bot-learning-report.json"
DEBATE_PATH = REPORT_DIR / "agent-trade-debate.json"
CONFLUENCE_PATH = REPORT_DIR / "institutional-confluence-shadow.json"
PREMARKET_THESIS_PATH = REPORT_DIR / "premarket-thesis-shadow.json"
OLLAMA_CRITIC_PATH = REPORT_DIR / "ollama-shadow-critic.json"
LEDGER_PATH = ROOT / "data" / "governed_shadow_decision_ledger.jsonl"
REPORT_PATH = REPORT_DIR / "governed-shadow-decisions.json"
SCHEMA_VERSION = 2


def _read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            value = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            rows.append(value)
    return rows


def _canonical_hash(value: Any) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _as_number(value: Any) -> float | None:
    try:
        parsed = float(value)
        return parsed if parsed == parsed else None
    except (TypeError, ValueError):
        return None


def _candidate_key(candidate: dict[str, Any]) -> str:
    fields = (
        candidate.get("symbol"), candidate.get("direction"), candidate.get("setup"),
        candidate.get("bar_completed_at"), candidate.get("trigger"),
    )
    return "|".join("" if item is None else str(item) for item in fields)


def _consensus_for(symbol: str, report: dict[str, Any]) -> dict[str, Any]:
    portfolio_kill_switch = report.get("portfolio_kill_switch")
    for row in report.get("decisions") or []:
        if isinstance(row, dict) and str(row.get("symbol") or "").upper() == symbol.upper():
            result = dict(row)
            result["portfolio_kill_switch"] = portfolio_kill_switch
            result["generated_at"] = report.get("generated_at")
            return result
    return {
        "symbol": symbol,
        "recommendation": "needs_review",
        "blockers": ["no_symbol_consensus"],
        "portfolio_kill_switch": portfolio_kill_switch,
        "generated_at": report.get("generated_at"),
    }


def _latest_confirmed_candidates(events: list[Any], *, historical: bool) -> list[dict[str, Any]]:
    confirmed = [row for row in events if isinstance(row, dict) and row.get("state") == "CONFIRMED"]
    if historical:
        return confirmed
    latest: dict[tuple[str, str, str], dict[str, Any]] = {}
    for row in confirmed:
        identity = (
            str(row.get("symbol") or "").upper(),
            str(row.get("lane") or "STANDARD_SHADOW"),
            str(row.get("setup") or "unknown"),
        )
        latest[identity] = row
    return list(latest.values())


def _premarket_critic(candidate: dict[str, Any], report: dict[str, Any]) -> dict[str, Any]:
    symbol = str(candidate.get("symbol") or "").upper()
    thesis = next((row for row in report.get("theses") or [] if isinstance(row, dict) and row.get("symbol") == symbol), None)
    status = "missing"
    if report.get("status") == "ok" and thesis:
        try:
            at, generated, expiry = [datetime.fromisoformat(str(value).replace("Z", "+00:00")) for value in (
                candidate.get("bar_completed_at"), thesis.get("generated_at"), thesis.get("expires_at"))]
            if any(value.tzinfo is None for value in (at, generated, expiry)):
                status = "timestamp_invalid"
            elif generated > at:
                status = "future_evidence"
            elif at >= expiry:
                status = "expired"
            elif thesis.get("state") != "OBSERVE" or thesis.get("execution_enabled") is not False or thesis.get("can_submit_orders") is not False:
                status = "invalid_authority_or_state"
            else:
                return {"role": "premarket_thesis_critic", "as_of": thesis["generated_at"], "claim": thesis.get("direction") or "NEUTRAL", "facts": thesis}
        except (TypeError, ValueError):
            status = "timestamp_invalid"
    return {"role": "premarket_thesis_critic", "as_of": report.get("generated_at"), "claim": status, "facts": {"status": status, "symbol": symbol}}


def evidence_cards(candidate: dict[str, Any], consensus: dict[str, Any], learning: dict[str, Any], debate: dict[str, Any], confluence: dict[str, Any] | None = None, premarket: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    """Independent, hashable cards. No card may decide or submit a trade."""
    technical = {
        "role": "technical_evidence",
        "as_of": candidate.get("bar_completed_at"),
        "claim": "completed_bar_confirmation" if candidate.get("state") == "CONFIRMED" else "not_confirmed",
        "facts": {key: candidate.get(key) for key in ("symbol", "direction", "setup", "grade", "score", "trigger", "stop", "target", "lane")},
    }
    learning_card = {
        "role": "recent_evidence",
        "as_of": learning.get("generated_at"),
        "claim": "recent_regime_gate",
        "facts": learning.get("recent_regime") or {"status": "missing"},
    }
    consensus_card = {
        "role": "independent_critic",
        "as_of": consensus.get("generated_at") or consensus.get("as_of"),
        "claim": str(consensus.get("recommendation") or "needs_review"),
        "facts": {key: consensus.get(key) for key in ("recommendation", "blockers", "reasons", "market_direction", "consensus_score")},
    }
    debate_card = {
        "role": "market_regime_critic",
        "as_of": debate.get("timestamp"),
        "claim": str(debate.get("verdict") or "missing"),
        "facts": {"source_availability": debate.get("source_availability"), "agents": debate.get("agents")},
    }
    confluence = confluence if isinstance(confluence, dict) else {}
    symbol = str(candidate.get("symbol") or "").upper()
    institutional = next((row for row in confluence.get("cards") or [] if isinstance(row, dict) and str(row.get("symbol") or "").upper() == symbol), {})
    institutional_card = {
        "role": "institutional_confluence_critic",
        "as_of": confluence.get("generated_at"),
        "claim": str(institutional.get("recommendation") or "missing"),
        "facts": institutional or {"status": "missing", "alert_visibility_preserved": True},
    }
    premarket = premarket if isinstance(premarket, dict) else {}
    premarket_card = _premarket_critic(candidate, premarket)
    cards = [technical, learning_card, consensus_card, debate_card, institutional_card, premarket_card]
    for card in cards:
        card["evidence_hash"] = _canonical_hash(card)
    return cards


def policy_gate(
    candidate: dict[str, Any], consensus: dict[str, Any], learning: dict[str, Any], prior_keys: set[str],
    *, now: datetime | None = None, institutional: dict[str, Any] | None = None,
    ollama_critic: dict[str, Any] | None = None,
) -> tuple[str, list[str]]:
    """Deterministic shadow gate; agent agreement cannot override these rules."""
    blockers: list[str] = []
    key = _candidate_key(candidate)
    if candidate.get("state") != "CONFIRMED":
        blockers.append("not_completed_bar_confirmed")
    if now is not None:
        try:
            completed = datetime.fromisoformat(str(candidate.get("bar_completed_at") or "").replace("Z", "+00:00"))
            if completed.tzinfo is None:
                completed = completed.replace(tzinfo=timezone.utc)
            age = now.astimezone(timezone.utc) - completed.astimezone(timezone.utc)
            if not timedelta(0) <= age <= timedelta(minutes=15):
                blockers.append("candidate_stale_or_future_dated")
        except (TypeError, ValueError):
            blockers.append("candidate_timestamp_invalid")
    if not all(candidate.get(field) not in (None, "") for field in ("symbol", "direction", "trigger", "stop", "target", "bar_completed_at")):
        blockers.append("missing_required_trade_level")
    trigger, stop, target = (_as_number(candidate.get(field)) for field in ("trigger", "stop", "target"))
    direction = str(candidate.get("direction") or "").upper()
    if trigger is not None and stop is not None and target is not None:
        valid_levels = (direction == "LONG" and stop < trigger < target) or (direction == "SHORT" and target < trigger < stop)
        if not valid_levels:
            blockers.append("invalid_risk_reward_geometry")
    else:
        blockers.append("non_numeric_trade_level")
    # De-duplication belongs to the append-only ledger, not decision quality.
    # Re-running the dashboard must not turn a previously valid candidate into
    # a false "rejection" simply because it was already observed.
    del key, prior_keys
    recent = learning.get("recent_regime") if isinstance(learning.get("recent_regime"), dict) else {}
    if recent.get("new_shadow_entries_allowed") is not True:
        blockers.append("recent_evidence_missing_or_not_positive")
    recommendation = str(consensus.get("recommendation") or "needs_review").lower()
    if recommendation not in {"approve", "size_down"}:
        blockers.append(f"consensus_not_explicitly_approved:{recommendation}")
    portfolio_kill_switch = consensus.get("portfolio_kill_switch")
    kill_switch_active = portfolio_kill_switch.get("active") if isinstance(portfolio_kill_switch, dict) else None
    if not isinstance(kill_switch_active, bool):
        blockers.append("portfolio_kill_switch_state_missing_or_invalid")
    elif kill_switch_active is True:
        blockers.append("portfolio_kill_switch_active")
    # Critic is veto-only: it can add this blocker, never remove any
    # deterministic blocker or create approval.
    institutional = institutional if isinstance(institutional, dict) else {}
    nbbo = next((row for row in institutional.get("sources") or [] if isinstance(row, dict) and row.get("name") == "nbbo_options_flow"), {})
    if nbbo.get("available") is True and nbbo.get("fresh") is True and nbbo.get("contradicts_candidate") is True:
        blockers.append("nbbo_flow_contradicts_direction")
    # Local model is strictly veto-only. Support/neutral/unavailable output has
    # no authority and can never erase a deterministic blocker.
    ollama_critic = ollama_critic if isinstance(ollama_critic, dict) else {}
    critic_payload = {key: ollama_critic.get(key) for key in ("stance", "veto_reasons", "evidence_refs", "summary")}
    critic_hash_valid = bool(ollama_critic.get("response_hash")) and ollama_critic.get("response_hash") == _canonical_hash(critic_payload)
    if (
        ollama_critic.get("status") == "ok"
        and ollama_critic.get("authority") == "shadow_veto_only"
        and ollama_critic.get("execution_enabled") is False
        and ollama_critic.get("can_submit_orders") is False
        and ollama_critic.get("stance") == "veto"
        and ollama_critic.get("veto_reasons")
        and ollama_critic.get("model_digest")
        and critic_hash_valid
    ):
        blockers.append("ollama_local_critic_veto")
    return ("shadow_rejected" if blockers else "shadow_accepted"), blockers


def build_report(*, historical: bool = False) -> dict[str, Any]:
    alerts, consensus_report, learning, debate, confluence, premarket, ollama_report = (
        _read_json(ALERTS_PATH), _read_json(CONSENSUS_PATH), _read_json(LEARNING_PATH), _read_json(DEBATE_PATH), _read_json(CONFLUENCE_PATH), _read_json(PREMARKET_THESIS_PATH),
        _read_json(OLLAMA_CRITIC_PATH),
    )
    events = alerts.get("recent_events") if isinstance(alerts.get("recent_events"), list) else []
    confirmed = _latest_confirmed_candidates(events, historical=historical)
    prior = _read_jsonl(LEDGER_PATH)
    prior_keys = {str(row.get("candidate_key")) for row in prior}
    decisions: list[dict[str, Any]] = []
    for candidate in confirmed:
        symbol = str(candidate.get("symbol") or "").upper()
        consensus = _consensus_for(symbol, consensus_report)
        candidate_key = _candidate_key(candidate)
        ollama_card = next((row for row in ollama_report.get("cards") or [] if isinstance(row, dict) and row.get("candidate_key") == candidate_key), {})
        decision, blockers = policy_gate(
            candidate, consensus, learning, prior_keys,
            now=None if historical else datetime.now(timezone.utc),
            institutional=next((row for row in confluence.get("cards") or [] if isinstance(row, dict) and str(row.get("symbol") or "").upper() == symbol), {}),
            ollama_critic=ollama_card,
        )
        cards = evidence_cards(candidate, consensus, learning, debate, confluence, premarket)
        event_id = _canonical_hash({"candidate": _candidate_key(candidate)})
        record = {
            "schema_version": SCHEMA_VERSION,
            "event_type": "shadow_decision",
            # Candidate identity is stable across refreshes. Evidence may be
            # regenerated at a different clock time, but must never create a
            # second simulated decision for the same completed bar.
            "event_id": event_id,
            "trace_id": new_trace_id(event_id),
            "bar_close_ts": candidate.get("bar_completed_at"),
            # Preserve a real upstream emit time when supplied. Never substitute
            # the decision clock for a missing scanner timestamp.
            "scanner_emit_ts": candidate.get("scanner_emit_ts") or candidate.get("confirmed_at"),
            "recorded_at": _utc_now(),
            "candidate_key": _candidate_key(candidate),
            "candidate": candidate,
            "evidence_cards": cards,
            "decision": decision,
            "blockers": blockers,
            "simulated_position_created": decision == "shadow_accepted",
            "execution_enabled": False,
            "can_submit_orders": False,
            "authority": "shadow_only_deterministic_policy",
        }
        decisions.append(record)
    sources = {name: {"path": str(path), "hash": _canonical_hash(_read_json(path))} for name, path in {
        "alerts": ALERTS_PATH, "consensus": CONSENSUS_PATH, "learning": LEARNING_PATH, "debate": DEBATE_PATH,
        "institutional_confluence": CONFLUENCE_PATH,
        "premarket_thesis": PREMARKET_THESIS_PATH, "ollama_shadow_critic": OLLAMA_CRITIC_PATH,
    }.items()}
    return {
        "provider": "governed_shadow_decision",
        "generated_at": _utc_now(),
        "mode": "shadow_only",
        "execution_enabled": False,
        "can_submit_orders": False,
        "historical_replay": historical,
        "sources": sources,
        "decisions": decisions,
        "summary": {
            "confirmed_candidates": len(confirmed),
            "shadow_accepted": sum(1 for row in decisions if row["decision"] == "shadow_accepted"),
            "shadow_rejected": sum(1 for row in decisions if row["decision"] == "shadow_rejected"),
            "rejected_by_reason": {reason: sum(reason in row["blockers"] for row in decisions) for reason in sorted({item for row in decisions for item in row["blockers"]})},
        },
        "warnings": [
            "Every confirmed setup is recorded even when rejected; rejection is not a hidden alert suppression.",
            "No broker client, order route, or live-execution authority is present.",
        ],
    }


def append_new(report: dict[str, Any], path: Path = LEDGER_PATH) -> int:
    existing_rows = _read_jsonl(path)
    existing_ids = {str(row.get("event_id")) for row in existing_rows}
    existing_keys = {str(row.get("candidate_key")) for row in existing_rows}
    new = [
        row for row in report["decisions"]
        if str(row.get("event_id")) not in existing_ids
        and str(row.get("candidate_key")) not in existing_keys
    ]
    if new:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            for row in new:
                handle.write(json.dumps(row, sort_keys=True, default=str) + "\n")
    return len(new)


def write_report(report: dict[str, Any], path: Path = REPORT_PATH) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--historical", action="store_true", help="Record each historical confirmed event once for counterfactual review.")
    parser.add_argument("--print", action="store_true", dest="print_output")
    args = parser.parse_args()
    report = build_report(historical=args.historical)
    appended = append_new(report)
    report["summary"]["new_ledger_events"] = appended
    write_report(report)
    if args.print_output:
        print(json.dumps(report["summary"], indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

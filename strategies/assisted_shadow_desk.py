#!/usr/bin/env python3
"""Tamper-evident human decision journal for shadow trade candidates.

The desk measures whether a human approve/skip decision adds forward value.
It cannot submit orders. Every candidate is frozen before its outcome is known,
decisions expire quickly, and both approved and skipped candidates can be
resolved as counterfactual observations.
"""
from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Literal


DEFAULT_JOURNAL = Path.home() / ".vibe-trading" / "assisted-shadow-decisions.jsonl"
Decision = Literal["approve", "skip"]


class AssistedShadowError(RuntimeError):
    """The assisted-shadow journal or state transition is invalid."""


@dataclass(frozen=True)
class PacketState:
    packet: dict[str, Any]
    decision: dict[str, Any] | None = None
    resolution: dict[str, Any] | None = None


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(value: datetime) -> str:
    if value.tzinfo is None:
        raise ValueError("Timestamp must be timezone-aware")
    return value.astimezone(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _parse_time(value: Any) -> datetime:
    if not isinstance(value, str) or not value.strip():
        raise AssistedShadowError(f"Invalid timestamp: {value!r}")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise AssistedShadowError(f"Invalid timestamp: {value!r}") from exc
    if parsed.tzinfo is None:
        raise AssistedShadowError(f"Timestamp is not timezone-aware: {value!r}")
    return parsed.astimezone(timezone.utc)


def _canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False)


def _digest(value: Any) -> str:
    return hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


def _finite(value: Any, field: str) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError) as exc:
        raise AssistedShadowError(f"{field} must be numeric") from exc
    if not math.isfinite(parsed):
        raise AssistedShadowError(f"{field} must be finite")
    return parsed


def normalize_candidate(candidate: dict[str, Any]) -> dict[str, Any]:
    """Return the exact, JSON-safe candidate that a decision will bind."""
    if not isinstance(candidate, dict):
        raise AssistedShadowError("Candidate must be an object")
    symbol = str(candidate.get("symbol") or "").strip().upper()
    strategy = str(candidate.get("strategy") or "").strip()
    side = str(candidate.get("side") or "").strip().lower()
    if not symbol or not strategy:
        raise AssistedShadowError("Candidate requires symbol and strategy")
    if side not in {"buy", "sell"}:
        raise AssistedShadowError("Candidate side must be buy or sell")
    entry = _finite(candidate.get("entry"), "entry")
    stop = _finite(candidate.get("stop"), "stop")
    target = _finite(candidate.get("target"), "target")
    if side == "buy" and not stop < entry < target:
        raise AssistedShadowError("Buy candidate must satisfy stop < entry < target")
    if side == "sell" and not target < entry < stop:
        raise AssistedShadowError("Sell candidate must satisfy target < entry < stop")
    quantity = int(candidate.get("quantity", 1))
    if quantity != 1:
        raise AssistedShadowError("Assisted-shadow candidates are fixed at quantity=1")
    point_value = _finite(candidate.get("point_value", 1.0), "point_value")
    estimated_cost = _finite(
        candidate.get("estimated_round_trip_cost", 0.0),
        "estimated_round_trip_cost",
    )
    if point_value <= 0 or estimated_cost < 0:
        raise AssistedShadowError("point_value must be positive and estimated cost non-negative")
    return {
        "symbol": symbol,
        "strategy": strategy,
        "side": side,
        "entry": entry,
        "stop": stop,
        "target": target,
        "quantity": 1,
        "point_value": point_value,
        "estimated_round_trip_cost": estimated_cost,
        "observed_at": candidate.get("observed_at"),
        "context": dict(candidate.get("context") or {}),
    }


def _read_events(journal: Path) -> list[dict[str, Any]]:
    if not journal.exists():
        return []
    events: list[dict[str, Any]] = []
    previous_hash: str | None = None
    for line_number, raw in enumerate(journal.read_text(encoding="utf-8").splitlines(), 1):
        if not raw.strip():
            continue
        try:
            event = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise AssistedShadowError(f"Invalid JSON at journal line {line_number}") from exc
        if event.get("previous_event_hash") != previous_hash:
            raise AssistedShadowError(f"Broken event chain at journal line {line_number}")
        claimed = event.get("event_hash")
        unsigned = {key: value for key, value in event.items() if key != "event_hash"}
        if claimed != _digest(unsigned):
            raise AssistedShadowError(f"Event hash mismatch at journal line {line_number}")
        previous_hash = claimed
        events.append(event)
    return events


def _append_event(journal: Path, event: dict[str, Any]) -> dict[str, Any]:
    events = _read_events(journal)
    signed = dict(event)
    signed["previous_event_hash"] = events[-1]["event_hash"] if events else None
    signed["event_hash"] = _digest(signed)
    journal.parent.mkdir(parents=True, exist_ok=True)
    with journal.open("a", encoding="utf-8") as handle:
        handle.write(_canonical(signed) + "\n")
    return signed


def load_states(journal: Path = DEFAULT_JOURNAL) -> dict[str, PacketState]:
    states: dict[str, PacketState] = {}
    for event in _read_events(journal):
        packet_id = str(event.get("packet_id") or "")
        event_type = event.get("event_type")
        if event_type == "candidate_created":
            if packet_id in states:
                raise AssistedShadowError(f"Duplicate packet: {packet_id}")
            packet = dict(event["packet"])
            candidate = packet.get("candidate")
            if packet.get("candidate_digest") != _digest(candidate):
                raise AssistedShadowError(f"Candidate digest mismatch: {packet_id}")
            states[packet_id] = PacketState(packet=packet)
        elif packet_id not in states:
            raise AssistedShadowError(f"Event references unknown packet: {packet_id}")
        elif event_type == "decision_recorded":
            state = states[packet_id]
            if state.decision is not None:
                raise AssistedShadowError(f"Duplicate decision: {packet_id}")
            states[packet_id] = PacketState(state.packet, dict(event), state.resolution)
        elif event_type == "outcome_resolved":
            state = states[packet_id]
            if state.resolution is not None:
                raise AssistedShadowError(f"Duplicate resolution: {packet_id}")
            states[packet_id] = PacketState(state.packet, state.decision, dict(event))
        else:
            raise AssistedShadowError(f"Unknown event type: {event_type!r}")
    return states


def create_packet(
    candidate: dict[str, Any],
    *,
    journal: Path = DEFAULT_JOURNAL,
    decision_window_seconds: int = 90,
    now: datetime | None = None,
) -> dict[str, Any]:
    if not 15 <= decision_window_seconds <= 300:
        raise AssistedShadowError("Decision window must be between 15 and 300 seconds")
    created = (now or _utc_now()).astimezone(timezone.utc)
    frozen = normalize_candidate(candidate)
    packet_core = {
        "schema_version": 1,
        "created_at": _iso(created),
        "expires_at": _iso(created + timedelta(seconds=decision_window_seconds)),
        "mode": "assisted_shadow_only",
        "execution_enabled": False,
        "can_submit_orders": False,
        "candidate": frozen,
        "candidate_digest": _digest(frozen),
    }
    packet_id = _digest(packet_core)[:20]
    packet = {"packet_id": packet_id, **packet_core}
    existing = load_states(journal)
    if packet_id in existing:
        return existing[packet_id].packet
    _append_event(
        journal,
        {
            "event_type": "candidate_created",
            "recorded_at": _iso(created),
            "packet_id": packet_id,
            "packet": packet,
        },
    )
    return packet


def record_decision(
    packet_id: str,
    decision: Decision,
    *,
    journal: Path = DEFAULT_JOURNAL,
    expected_candidate_digest: str | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    if decision not in {"approve", "skip"}:
        raise AssistedShadowError("Decision must be approve or skip")
    states = load_states(journal)
    if packet_id not in states:
        raise AssistedShadowError(f"Unknown packet: {packet_id}")
    state = states[packet_id]
    if state.decision is not None:
        raise AssistedShadowError(f"Decision already recorded: {packet_id}")
    decided = (now or _utc_now()).astimezone(timezone.utc)
    if decided > _parse_time(state.packet["expires_at"]):
        raise AssistedShadowError(f"Decision window expired: {packet_id}")
    actual_digest = state.packet["candidate_digest"]
    if expected_candidate_digest is not None and expected_candidate_digest != actual_digest:
        raise AssistedShadowError("Candidate digest changed before decision")
    return _append_event(
        journal,
        {
            "event_type": "decision_recorded",
            "recorded_at": _iso(decided),
            "packet_id": packet_id,
            "candidate_digest": actual_digest,
            "decision": decision,
            "execution_authority": "none_shadow_observation_only",
        },
    )


def resolve_outcome(
    packet_id: str,
    *,
    exit_price: float,
    journal: Path = DEFAULT_JOURNAL,
    resolved_at: datetime | None = None,
) -> dict[str, Any]:
    states = load_states(journal)
    if packet_id not in states:
        raise AssistedShadowError(f"Unknown packet: {packet_id}")
    state = states[packet_id]
    if state.decision is None:
        raise AssistedShadowError("Outcome cannot be resolved before approve/skip decision")
    if state.resolution is not None:
        raise AssistedShadowError(f"Outcome already resolved: {packet_id}")
    candidate = state.packet["candidate"]
    exit_value = _finite(exit_price, "exit_price")
    direction = 1.0 if candidate["side"] == "buy" else -1.0
    gross = (exit_value - candidate["entry"]) * direction * candidate["point_value"]
    net = gross - candidate["estimated_round_trip_cost"]
    resolved = (resolved_at or _utc_now()).astimezone(timezone.utc)
    return _append_event(
        journal,
        {
            "event_type": "outcome_resolved",
            "recorded_at": _iso(resolved),
            "packet_id": packet_id,
            "candidate_digest": state.packet["candidate_digest"],
            "decision": state.decision["decision"],
            "exit_price": exit_value,
            "gross_pnl": round(gross, 8),
            "net_pnl": round(net, 8),
            "outcome_authority": "counterfactual_shadow_not_broker_fill",
        },
    )


def packet_summary(state: PacketState, *, now: datetime | None = None) -> dict[str, Any]:
    observed = (now or _utc_now()).astimezone(timezone.utc)
    return {
        "packet_id": state.packet["packet_id"],
        "created_at": state.packet["created_at"],
        "expires_at": state.packet["expires_at"],
        "expired": observed > _parse_time(state.packet["expires_at"]),
        "decision": state.decision["decision"] if state.decision else "pending",
        "resolved": state.resolution is not None,
        "candidate": state.packet["candidate"],
        "candidate_digest": state.packet["candidate_digest"],
        "execution_enabled": False,
        "can_submit_orders": False,
    }

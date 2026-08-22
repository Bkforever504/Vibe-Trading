"""Fail-closed, idempotent order-intent envelope.

This module wraps a broker submit callable without replacing any strategy or
risk gate. Runtime order authority is intentionally disabled. The pure
``evaluate_order_intent`` function exists so the refusal rules can be tested
without creating a broker credential or network surface.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping

from strategies.risk_kill_switch import DEFAULT_BLOCK_FILE, manual_reset_required


ROOT = Path(__file__).resolve().parents[1]
RECONCILIATION_LOG = ROOT / "data" / "reconciliation_events.jsonl"
ENVELOPE_LOG = ROOT / "data" / "order_envelope_events.jsonl"
EXECUTION_ENABLED = False
CAN_SUBMIT_ORDERS = False


@dataclass(frozen=True)
class OrderIntent:
    strategy_id: str
    symbol: str
    intent_ts: str
    bar_ts: str
    freshness: str = "fresh"


def client_order_id_for(intent: OrderIntent) -> str:
    """Return Alpaca's 48-character-safe prefix of the frozen SHA-256 ID."""
    raw = f"{intent.strategy_id}{intent.symbol}{intent.intent_ts}{intent.bar_ts}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:48]


def _append_jsonl(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(dict(payload), sort_keys=True, separators=(",", ":")) + "\n")


def _reconciliation_collision(client_order_id: str, path: Path) -> bool:
    try:
        lines = path.read_text(encoding="utf-8-sig").splitlines()
    except OSError:
        return False
    for line in lines:
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        identifiers = {
            str(row.get(key) or "")
            for key in ("client_order_id", "order_id", "local_order_id", "broker_order_id")
        }
        identifiers.update(str(value) for value in row.get("identifiers", []) if value)
        if client_order_id in identifiers:
            return True
    return False


def evaluate_order_intent(
    intent: OrderIntent,
    *,
    execution_enabled: bool = EXECUTION_ENABLED,
    can_submit_orders: bool = CAN_SUBMIT_ORDERS,
    reconciliation_log: Path = RECONCILIATION_LOG,
    kill_switch_file: Path = DEFAULT_BLOCK_FILE,
) -> dict[str, Any]:
    """Evaluate all envelope gates and return a non-executing decision."""
    order_id = client_order_id_for(intent)
    blockers: list[str] = []
    if not execution_enabled:
        blockers.append("execution_disabled")
    if not can_submit_orders:
        blockers.append("order_authority_disabled")
    if intent.freshness.lower() not in {"fresh", "live"}:
        blockers.append("stale_freshness")
    if manual_reset_required(kill_switch_file):
        blockers.append("kill_switch_red")
    if _reconciliation_collision(order_id, reconciliation_log):
        blockers.append("reconciliation_log_collision")
    return {
        "schema_version": 1,
        "evaluated_at": datetime.now(timezone.utc).isoformat(),
        "intent": asdict(intent),
        "client_order_id": order_id,
        "allowed": False,
        "submitted": False,
        "blockers": blockers or ["static_order_authority_invariant"],
        "execution_enabled": False,
        "can_submit_orders": False,
    }


def submit_order(
    intent: OrderIntent,
    order_payload: Mapping[str, Any],
    submitter: Callable[[Mapping[str, Any]], Any],
    *,
    event_log: Path = ENVELOPE_LOG,
    reconciliation_log: Path = RECONCILIATION_LOG,
    kill_switch_file: Path = DEFAULT_BLOCK_FILE,
) -> dict[str, Any]:
    """Wrap a submit callable; current authority guarantees it is never called."""
    del order_payload, submitter
    decision = evaluate_order_intent(
        intent,
        execution_enabled=False,
        can_submit_orders=False,
        reconciliation_log=reconciliation_log,
        kill_switch_file=kill_switch_file,
    )
    _append_jsonl(event_log, decision)
    return decision


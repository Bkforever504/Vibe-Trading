"""Shared read-only normalization for options lifecycle reports."""
from __future__ import annotations

from typing import Any


_LIFECYCLE_FIELDS = (
    "opened_at",
    "closed_at",
    "closing_reason",
    "pnl",
    "net_credit",
    "order_id",
    "closing_order_id",
    "leg_details",
    "candidate_confidence",
    "quote_mark",
)


def _completeness(trade: dict[str, Any], index: int) -> tuple[int, int, int]:
    populated = sum(trade.get(field) not in (None, "", [], {}) for field in _LIFECYCLE_FIELDS)
    original_bonus = 0 if str(trade.get("id") or "").startswith("recovered-") else 1
    return populated, original_bonus, -index


def dedupe_options_trade_records(trades: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Collapse duplicate closed lifecycles by opening order id for reporting.

    State is never modified. Open records and records without an order id are
    always preserved. For duplicate closed records, the most complete lifecycle
    wins; deterministic ties prefer the original non-recovered record.
    """
    selected: dict[str, tuple[int, dict[str, Any]]] = {}
    passthrough: list[tuple[int, dict[str, Any]]] = []
    for index, trade in enumerate(trades):
        if not isinstance(trade, dict):
            continue
        order_id = str(trade.get("order_id") or "").strip()
        if trade.get("status") != "closed" or not order_id:
            passthrough.append((index, trade))
            continue
        current = selected.get(order_id)
        if current is None or _completeness(trade, index) > _completeness(current[1], current[0]):
            selected[order_id] = (index, trade)
    rows = passthrough + list(selected.values())
    rows.sort(key=lambda item: item[0])
    return [trade for _, trade in rows]

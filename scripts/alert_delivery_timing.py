"""Canonical delivery-time boundary for alert outcome evaluation."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Mapping


def _timestamp(value: Any) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(str(value or "").replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def delivered_at(alert: Mapping[str, Any]) -> datetime | None:
    """Return a real transport timestamp; never fall back to the signal bar."""
    for key in ("delivered_at", "attempted_at", "discord_delivered_at"):
        stamp = _timestamp(alert.get(key))
        if stamp is not None:
            return stamp
    return None


def first_complete_bar_after_delivery(alert: Mapping[str, Any]) -> datetime | None:
    stamp = delivered_at(alert)
    return stamp.replace(second=0, microsecond=0) + timedelta(minutes=1) if stamp else None

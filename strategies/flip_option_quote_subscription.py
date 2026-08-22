"""Short-lived option quote subscription intents shared by Flip processes."""
from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any


DEFAULT_PATH = Path.home() / ".vibe-trading" / "state" / "flip-option-stream-subscriptions.json"


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _timestamp(value: Any) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _read(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _write(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(temp, path)


def request_option_quote(
    symbol: str,
    *,
    path: Path = DEFAULT_PATH,
    ttl_seconds: float = 30.0,
    now: datetime | None = None,
) -> None:
    """Publish an expiring request for the event monitor to stream one contract."""
    normalized = str(symbol or "").strip().upper()
    if not normalized:
        return
    observed_at = (now or _utc_now()).astimezone(timezone.utc)
    expires_at = observed_at + timedelta(seconds=max(1.0, float(ttl_seconds)))
    payload = _read(path)
    rows = payload.get("subscriptions") if isinstance(payload.get("subscriptions"), dict) else {}
    active = {
        key: value
        for key, value in rows.items()
        if isinstance(value, dict)
        and (_timestamp(value.get("expires_at")) or datetime.min.replace(tzinfo=timezone.utc)) > observed_at
    }
    active[normalized] = {
        "requested_at": observed_at.isoformat().replace("+00:00", "Z"),
        "expires_at": expires_at.isoformat().replace("+00:00", "Z"),
    }
    _write(
        path,
        {
            "provider": "flip_option_quote_subscription",
            "generated_at": observed_at.isoformat().replace("+00:00", "Z"),
            "subscriptions": active,
        },
    )


def requested_option_symbols(
    *,
    path: Path = DEFAULT_PATH,
    now: datetime | None = None,
) -> set[str]:
    """Return only unexpired candidate symbols; malformed rows fail closed."""
    observed_at = (now or _utc_now()).astimezone(timezone.utc)
    payload = _read(path)
    rows = payload.get("subscriptions") if isinstance(payload.get("subscriptions"), dict) else {}
    return {
        str(symbol).strip().upper()
        for symbol, value in rows.items()
        if str(symbol).strip()
        and isinstance(value, dict)
        and (_timestamp(value.get("expires_at")) or datetime.min.replace(tzinfo=timezone.utc)) > observed_at
    }

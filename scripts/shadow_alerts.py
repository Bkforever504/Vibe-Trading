"""Low-noise Discord alerts for shadow strategy loggers."""
from __future__ import annotations

import json
import os
import urllib.request
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
ENV_PATH = ROOT / "agent" / ".env"


def _env_value(name: str) -> str | None:
    value = os.environ.get(name)
    if value:
        return value.strip()
    if not ENV_PATH.exists():
        return None
    for line in ENV_PATH.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line.startswith("#") or "=" not in line:
            continue
        key, _, raw = line.partition("=")
        if key.strip() == name:
            return raw.strip()
    return None


def webhook_url() -> str | None:
    return _env_value("SHADOW_ALERT_WEBHOOK_URL") or _env_value("DISCORD_WEBHOOK_URL")


def should_alert(entry: dict, prev: dict | None) -> bool:
    """Alert only on fresh entries/rotations, never routine holds."""
    if prev is not None and prev.get("date") == entry.get("date"):
        return False
    if _entry_actions(entry):
        return True
    action = str(entry.get("action", ""))
    return action.startswith("rotate_to_") or action == "rebalance"


def _entry_actions(entry: dict) -> list[tuple[str, dict]]:
    found: list[tuple[str, dict]] = []
    for key in ("primary_setup", "comparison_setup", "primary", "comparison"):
        setup = entry.get(key)
        if isinstance(setup, dict) and str(setup.get("action", "")).startswith("enter_"):
            found.append((key, setup))
    return found


def format_alert(strategy_name: str, entry: dict) -> str:
    lines = [
        f"**Shadow signal: {strategy_name}**",
        f"Date: `{entry.get('date', 'unknown')}`",
        f"Mode: `{entry.get('execution_mode', 'shadow_only')}`",
        f"Data: `{entry.get('data_source', 'unknown')}`",
    ]
    vix = entry.get("vix_context")
    if isinstance(vix, dict) and vix.get("close") is not None:
        lines.append(f"VIX: `{vix.get('close')}` `{vix.get('regime')}`")

    for key, setup in _entry_actions(entry):
        symbol = setup.get("symbol") or entry.get("symbol") or entry.get("primary_symbol") or ""
        name = setup.get("name") or setup.get("strategy") or key
        lines.append(
            f"{key}: `{name}` `{symbol}` action=`{setup.get('action')}` "
            f"conf=`{setup.get('confidence')}`"
        )

    action = str(entry.get("action", ""))
    if action.startswith("rotate_to_"):
        lines.append(
            f"Rotation: action=`{action}` selected=`{entry.get('selected')}` "
            f"prev=`{entry.get('previous_selected')}` conf=`{entry.get('confidence')}`"
        )
    elif action == "rebalance":
        lines.append(
            f"Rebalance: holdings=`{','.join(entry.get('holdings', []))}` "
            f"previous=`{','.join(entry.get('previous_holdings', []))}`"
        )

    lines.append("No orders placed. Shadow-only.")
    return "\n".join(lines)


def maybe_send_shadow_alert(strategy_name: str, entry: dict, prev: dict | None) -> bool:
    if not should_alert(entry, prev):
        return False
    url = webhook_url()
    if not url:
        return False
    payload = json.dumps({"content": format_alert(strategy_name, entry)}).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=10):
            return True
    except Exception:
        return False

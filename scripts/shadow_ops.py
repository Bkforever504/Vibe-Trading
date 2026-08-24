#!/usr/bin/env python3
"""Shared kill-switch and consecutive-failure state for shadow scanners."""
from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
KILL_SWITCH = ROOT / "KILL_SWITCH"
HEALTH_DIR = Path.home() / ".vibe-trading" / "health" / "shadow-scanners"
FAILURE_THRESHOLD = 3


def utc_now_z() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _safe_name(name: str) -> str:
    value = re.sub(r"[^a-z0-9_.-]+", "-", name.lower()).strip("-.")
    if not value:
        raise ValueError("scanner_name_invalid")
    return value


def state_path(name: str) -> Path:
    return HEALTH_DIR / f"{_safe_name(name)}.json"


def halt_path(name: str) -> Path:
    return HEALTH_DIR / f"{_safe_name(name)}.halt"


def read_state(name: str) -> dict[str, Any]:
    path = state_path(name)
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        value = {}
    return value if isinstance(value, dict) else {}


def _write_atomic(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".partial")
    temporary.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(path)


def record_success(name: str) -> dict[str, Any]:
    prior = read_state(name)
    row = {
        "scanner": _safe_name(name),
        "consecutive_failures": 0,
        "last_success_at": utc_now_z(),
        "last_failure_at": prior.get("last_failure_at"),
        "last_error_type": None,
        "halted": halt_path(name).exists(),
        "execution_enabled": False,
        "can_submit_orders": False,
    }
    _write_atomic(state_path(name), row)
    return row


def record_failure(name: str, *, error_type: str, reason: str) -> dict[str, Any]:
    prior = read_state(name)
    count = int(prior.get("consecutive_failures") or 0) + 1
    halted = count >= FAILURE_THRESHOLD
    row = {
        "scanner": _safe_name(name),
        "consecutive_failures": count,
        "last_success_at": prior.get("last_success_at"),
        "last_failure_at": utc_now_z(),
        "last_error_type": error_type[:80],
        "last_reason": reason[:300],
        "halted": halted,
        "execution_enabled": False,
        "can_submit_orders": False,
    }
    _write_atomic(state_path(name), row)
    if halted:
        _write_atomic(halt_path(name), row)
    return row


def is_halted(name: str) -> bool:
    return halt_path(name).exists()


def clear_halt(name: str) -> dict[str, Any]:
    halt_path(name).unlink(missing_ok=True)
    return record_success(name)


def kill_switch_active() -> bool:
    return KILL_SWITCH.exists()

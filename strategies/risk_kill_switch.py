#!/usr/bin/env python3
"""Manual-reset risk kill switch for strategy scripts.

The block file is intentionally simple and human-readable. If it exists, bot
order helpers should refuse to submit new orders until Kenny manually removes
the file after review.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

DEFAULT_BLOCK_FILE = Path(os.path.expanduser(r"~\.vibe-trading\MANUAL_RESET_REQUIRED.json"))


@dataclass(frozen=True)
class KillSwitchConfig:
    max_daily_loss_pct: float = 0.03
    max_drawdown_pct: float = 0.10


@dataclass(frozen=True)
class KillSwitchDecision:
    allowed: bool
    reason: str
    details: dict[str, Any]


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _pct_loss(reference: float, equity: float) -> float:
    if reference <= 0:
        return 0.0
    return max(0.0, (reference - equity) / reference)


def block_payload(reason: str, *, source: str, details: dict[str, Any] | None = None) -> dict[str, Any]:
    return {
        "status": "blocked",
        "reason": reason,
        "source": source,
        "created_at": _utc_now(),
        "manual_reset_required": True,
        "details": details or {},
    }


def write_block_file(
    block_file: Path = DEFAULT_BLOCK_FILE,
    *,
    reason: str,
    source: str = "risk_kill_switch",
    details: dict[str, Any] | None = None,
) -> dict[str, Any]:
    payload = block_payload(reason, source=source, details=details)
    block_file.parent.mkdir(parents=True, exist_ok=True)
    block_file.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    return payload


def evaluate_kill_switch(
    *,
    equity: float,
    start_equity: float,
    peak_equity: float,
    block_file: Path = DEFAULT_BLOCK_FILE,
    config: KillSwitchConfig = KillSwitchConfig(),
    source: str = "risk_kill_switch",
) -> KillSwitchDecision:
    if block_file.exists():
        return KillSwitchDecision(False, "manual_reset_required", {"block_file": str(block_file)})

    daily_loss_pct = _pct_loss(start_equity, equity)
    drawdown_pct = _pct_loss(peak_equity, equity)
    details = {
        "equity": equity,
        "start_equity": start_equity,
        "peak_equity": peak_equity,
        "daily_loss_pct": daily_loss_pct,
        "drawdown_pct": drawdown_pct,
        "max_daily_loss_pct": config.max_daily_loss_pct,
        "max_drawdown_pct": config.max_drawdown_pct,
    }

    if daily_loss_pct >= config.max_daily_loss_pct:
        write_block_file(block_file, reason="daily_loss_limit", source=source, details=details)
        return KillSwitchDecision(False, "daily_loss_limit", details)

    if drawdown_pct >= config.max_drawdown_pct:
        write_block_file(block_file, reason="max_drawdown_limit", source=source, details=details)
        return KillSwitchDecision(False, "max_drawdown_limit", details)

    return KillSwitchDecision(True, "allowed", details)


def manual_reset_required(block_file: Path = DEFAULT_BLOCK_FILE) -> bool:
    return block_file.exists()


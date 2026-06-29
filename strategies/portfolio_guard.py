#!/usr/bin/env python3
"""Portfolio-level kill switch - halts ALL bots when aggregate daily loss exceeds limit.

Separate from per-bot block files (MANUAL_RESET_REQUIRED.json, KALSHI_MANUAL_RESET_REQUIRED.json).
A single catastrophic day triggers a full portfolio halt across every strategy.

Kill file: ~/.vibe-trading/PORTFOLIO_KILL_SWITCH.json
Reset: delete the file manually after reviewing losses. All bots resume on next run.

Kill thresholds (all read dynamically from env at call time - never at import time):
  PORTFOLIO_SOFT_WARNING_DOLLARS     (default 500)  - log warning only
  PORTFOLIO_MAX_DAILY_LOSS_DOLLARS   (default 750)  - hard kill after N consecutive polls
  PORTFOLIO_SOFT_BREACH_POLLS_REQUIRED (default 2)  - polls below hard threshold before kill
  PORTFOLIO_EMERGENCY_KILL_DOLLARS   (default 1500) - immediate kill regardless of poll count
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path

PORTFOLIO_KILL_FILE = Path(os.path.expanduser(r"~\.vibe-trading\PORTFOLIO_KILL_SWITCH.json"))


# ---------------------------------------------------------------------------
# Dynamic config - read env at call time, not import time
# ---------------------------------------------------------------------------

def portfolio_max_daily_loss_dollars() -> float:
    return float(os.getenv("PORTFOLIO_MAX_DAILY_LOSS_DOLLARS", "750.0"))


def portfolio_soft_warning_dollars() -> float:
    return float(os.getenv("PORTFOLIO_SOFT_WARNING_DOLLARS", "500.0"))


def portfolio_emergency_kill_dollars() -> float:
    return float(os.getenv("PORTFOLIO_EMERGENCY_KILL_DOLLARS", "1500.0"))


def portfolio_soft_breach_polls_required() -> int:
    return int(os.getenv("PORTFOLIO_SOFT_BREACH_POLLS_REQUIRED", "2"))


# ---------------------------------------------------------------------------
# Core kill switch logic
# ---------------------------------------------------------------------------

def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def portfolio_kill_active(kill_file: Path = PORTFOLIO_KILL_FILE) -> bool:
    return kill_file.exists()


def trigger_portfolio_kill(
    *,
    daily_pnl_dollars: float,
    source: str = "portfolio_guard",
    reason: str = "max_daily_loss",
    kill_file: Path = PORTFOLIO_KILL_FILE,
    details: dict | None = None,
) -> None:
    payload = {
        "status": "killed",
        "reason": reason,
        "daily_pnl_dollars": round(daily_pnl_dollars, 2),
        "max_daily_loss_dollars": portfolio_max_daily_loss_dollars(),
        "soft_warning_dollars": portfolio_soft_warning_dollars(),
        "emergency_kill_dollars": portfolio_emergency_kill_dollars(),
        "breach_polls_required": portfolio_soft_breach_polls_required(),
        "triggered_at": _utc_now(),
        "source": source,
        "manual_reset_required": True,
        "reset_instructions": (
            "Review losses. Delete this file when ready to resume. "
            "All bots check this file before placing orders."
        ),
    }
    if details:
        payload["details"] = details
    kill_file.parent.mkdir(parents=True, exist_ok=True)
    kill_file.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")


def check_and_maybe_kill(
    daily_pnl_dollars: float,
    *,
    max_daily_loss_dollars: float | None = None,
    source: str = "portfolio_guard",
    kill_file: Path = PORTFOLIO_KILL_FILE,
) -> bool:
    """Return True if a kill file exists or this single check breaches the hard limit.

    This compatibility helper kills immediately on one hard-limit breach. The scheduled
    portfolio monitor adds softer behavior on top: warning tier, consecutive hard
    breach polls, and emergency halt.
    max_daily_loss_dollars: if None, reads from env at call time.
    """
    if portfolio_kill_active(kill_file):
        return True
    limit = max_daily_loss_dollars if max_daily_loss_dollars is not None else portfolio_max_daily_loss_dollars()
    if daily_pnl_dollars <= -abs(limit):
        trigger_portfolio_kill(
            daily_pnl_dollars=daily_pnl_dollars,
            source=source,
            reason="max_daily_loss",
            kill_file=kill_file,
        )
        return True
    return False

#!/usr/bin/env python3
"""Portfolio monitor - polls Alpaca equity and triggers portfolio kill switch if daily loss is too large.

Run via Windows Task Scheduler every 15 minutes during market hours (9:30-16:15 ET Mon-Fri).
Task: python strategies/portfolio_monitor.py

Kill thresholds (set in agent/.env):
  PORTFOLIO_SOFT_WARNING_DOLLARS       default 500   - log warning, no kill
  PORTFOLIO_MAX_DAILY_LOSS_DOLLARS     default 750   - hard kill after N consecutive polls
  PORTFOLIO_SOFT_BREACH_POLLS_REQUIRED default 2     - consecutive polls required before hard kill
  PORTFOLIO_EMERGENCY_KILL_DOLLARS     default 1500  - immediate kill regardless of poll count

State file (tracks consecutive breach count):
  ~/.vibe-trading/portfolio_monitor_state.json

Env vars:
  ALPACA_API_KEY, ALPACA_SECRET_KEY, ALPACA_PAPER (default true)
  DISCORD_WEBHOOK_URL (optional)
"""
from __future__ import annotations

import json
import logging
import os
import sys
from datetime import date
from pathlib import Path

# IMPORTANT: load .env BEFORE importing portfolio_guard so dynamic env reads see the values.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
ENV_FILE = ROOT / "agent" / ".env"
load_dotenv(dotenv_path=ENV_FILE, override=True)

import requests

from strategies.portfolio_guard import (
    PORTFOLIO_KILL_FILE,
    portfolio_emergency_kill_dollars,
    portfolio_kill_active,
    portfolio_max_daily_loss_dollars,
    portfolio_soft_breach_polls_required,
    portfolio_soft_warning_dollars,
    trigger_portfolio_kill,
)

STATE_FILE = Path(os.path.expanduser(r"~\.vibe-trading\portfolio_monitor_state.json"))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("portfolio_monitor")

PAPER = os.getenv("ALPACA_PAPER", "true").lower() == "true"
BASE = "https://paper-api.alpaca.markets" if PAPER else "https://api.alpaca.markets"
DISCORD_WEBHOOK = os.getenv("DISCORD_WEBHOOK_URL", "")


def _headers() -> dict:
    return {
        "APCA-API-KEY-ID": os.getenv("ALPACA_API_KEY", ""),
        "APCA-API-SECRET-KEY": os.getenv("ALPACA_SECRET_KEY", ""),
    }


def _fetch_daily_pnl() -> float:
    resp = requests.get(
        f"{BASE}/v2/account/portfolio/history",
        headers=_headers(),
        params={"period": "1D", "timeframe": "1Min", "extended_hours": "false"},
        timeout=10,
    )
    resp.raise_for_status()
    data = resp.json()
    equity = [e for e in (data.get("equity") or []) if e is not None]
    if len(equity) < 2:
        raise ValueError(f"Insufficient equity data points: {len(equity)}")
    return round(float(equity[-1]) - float(equity[0]), 2)


def _fetch_account_equity() -> float:
    resp = requests.get(f"{BASE}/v2/account", headers=_headers(), timeout=10)
    resp.raise_for_status()
    return float(resp.json().get("equity", 0))


def _fetch_positions_summary() -> list[dict]:
    resp = requests.get(f"{BASE}/v2/positions", headers=_headers(), timeout=10)
    resp.raise_for_status()
    positions = resp.json()
    if not isinstance(positions, list):
        return []
    summary = []
    for pos in positions:
        if not isinstance(pos, dict):
            continue
        summary.append({
            "symbol": str(pos.get("symbol", "")),
            "qty": str(pos.get("qty", "")),
            "market_value": round(float(pos.get("market_value") or 0), 2),
            "unrealized_pl": round(float(pos.get("unrealized_pl") or 0), 2),
        })
    return summary


def _positions_text(positions: list[dict], limit: int = 8) -> str:
    if not positions:
        return "Open positions: none or unavailable"
    lines = []
    for pos in positions[:limit]:
        symbol = pos.get("symbol", "")
        qty = pos.get("qty", "")
        upl = float(pos.get("unrealized_pl") or 0)
        lines.append(f"{symbol} qty={qty} uPL=${upl:+.2f}")
    extra = len(positions) - len(lines)
    if extra > 0:
        lines.append(f"... {extra} more")
    return "Open positions:\n" + "\n".join(lines)


def _discord_alert(message: str) -> None:
    if not DISCORD_WEBHOOK:
        return
    try:
        requests.post(DISCORD_WEBHOOK, json={"content": message}, timeout=5)
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Consecutive-breach state (prevents single bad option mark from killing bots)
# ---------------------------------------------------------------------------

def _load_state() -> dict:
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {"soft_breach_count": 0, "soft_warning_sent": False, "trade_date": ""}


def _save_state(state: dict) -> None:
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps(state, indent=2), encoding="utf-8")


def _increment_breach_count() -> int:
    state = _load_state()
    today = date.today().isoformat()
    if state.get("trade_date") != today:
        state = {"soft_breach_count": 0, "soft_warning_sent": False, "trade_date": today}
    state["soft_breach_count"] = int(state.get("soft_breach_count", 0)) + 1
    state["soft_warning_sent"] = True
    state["trade_date"] = today
    _save_state(state)
    return state["soft_breach_count"]


def _reset_breach_count() -> None:
    state = _load_state()
    state["soft_breach_count"] = 0
    state["soft_warning_sent"] = False
    state["trade_date"] = date.today().isoformat()
    _save_state(state)


def _mark_soft_warning_sent() -> bool:
    """Return True only for the first soft alert in the current breach window."""
    state = _load_state()
    today = date.today().isoformat()
    if state.get("trade_date") != today:
        state = {"soft_breach_count": 0, "soft_warning_sent": False, "trade_date": today}
    already_sent = bool(state.get("soft_warning_sent"))
    state["soft_warning_sent"] = True
    state["trade_date"] = today
    _save_state(state)
    return not already_sent


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> int:
    soft_limit = portfolio_soft_warning_dollars()
    hard_limit = portfolio_max_daily_loss_dollars()
    emergency_limit = portfolio_emergency_kill_dollars()
    polls_required = portfolio_soft_breach_polls_required()

    if portfolio_kill_active(PORTFOLIO_KILL_FILE):
        log.warning(f"PORTFOLIO KILL SWITCH ALREADY ACTIVE: {PORTFOLIO_KILL_FILE}")
        log.warning("Delete the file manually after reviewing losses to resume trading.")
        return 0

    try:
        daily_pnl = _fetch_daily_pnl()
    except Exception as exc:
        log.error(f"Failed to fetch portfolio history: {exc}")
        return 1

    try:
        equity = _fetch_account_equity()
    except Exception:
        equity = 0.0

    log.info(
        f"Portfolio P&L today: ${daily_pnl:+.2f}  |  equity=${equity:,.2f}  |  "
        f"soft=-${soft_limit:.0f}  hard=-${hard_limit:.0f}  emergency=-${emergency_limit:.0f}"
    )

    # Emergency: immediate kill regardless of poll count
    if daily_pnl <= -abs(emergency_limit):
        log.critical(f"EMERGENCY KILL: P&L ${daily_pnl:+.2f} exceeds emergency limit -${emergency_limit:.0f}")
        try:
            positions = _fetch_positions_summary()
        except Exception:
            positions = []
        log.critical(_positions_text(positions))
        trigger_portfolio_kill(
            daily_pnl_dollars=daily_pnl,
            source="portfolio_monitor",
            reason="emergency_kill",
            kill_file=PORTFOLIO_KILL_FILE,
            details={
                "equity": round(equity, 2),
                "positions": positions,
                "emergency_kill_dollars": emergency_limit,
            },
        )
        _discord_alert(
            f"EMERGENCY PORTFOLIO KILL @everyone\n"
            f"Daily P&L: ${daily_pnl:+.2f} (limit -${emergency_limit:.0f})\n"
            f"IMMEDIATE halt. Delete `PORTFOLIO_KILL_SWITCH.json` to resume.\n"
            f"{_positions_text(positions)}\n"
            f"File: `{PORTFOLIO_KILL_FILE}`"
        )
        return 2

    # Hard kill: require N consecutive polls below threshold
    if daily_pnl <= -abs(hard_limit):
        breach_count = _increment_breach_count()
        log.warning(
            f"Hard threshold breach #{breach_count}/{polls_required}: "
            f"P&L ${daily_pnl:+.2f} <= -${hard_limit:.0f}"
        )
        if breach_count >= polls_required:
            log.critical(f"KILL SWITCH TRIGGERED after {breach_count} consecutive breach polls")
            try:
                positions = _fetch_positions_summary()
            except Exception:
                positions = []
            log.critical(_positions_text(positions))
            trigger_portfolio_kill(
                daily_pnl_dollars=daily_pnl,
                source="portfolio_monitor",
                reason="max_daily_loss",
                kill_file=PORTFOLIO_KILL_FILE,
                details={
                    "equity": round(equity, 2),
                    "positions": positions,
                    "hard_limit_dollars": hard_limit,
                    "breach_count": breach_count,
                    "polls_required": polls_required,
                },
            )
            _discord_alert(
                f"PORTFOLIO KILL SWITCH TRIGGERED @everyone\n"
                f"Daily P&L: ${daily_pnl:+.2f} (limit -${hard_limit:.0f}, {breach_count} polls)\n"
                f"All bots halted. Delete `PORTFOLIO_KILL_SWITCH.json` to resume.\n"
                f"{_positions_text(positions)}\n"
                f"File: `{PORTFOLIO_KILL_FILE}`"
            )
            return 2
        else:
            remaining = polls_required - breach_count
            log.warning(f"Will trigger kill in {remaining} more poll(s) if loss persists. Watching...")
            _discord_alert(
                f"Portfolio soft breach (poll {breach_count}/{polls_required})\n"
                f"P&L: ${daily_pnl:+.2f} - kill triggers in {remaining} more poll(s) if it persists."
            )
        return 0

    # Soft warning only - don't kill
    if daily_pnl <= -abs(soft_limit):
        log.warning(f"SOFT WARNING: P&L ${daily_pnl:+.2f} below -${soft_limit:.0f}. Watching.")
        state = _load_state()
        state["soft_breach_count"] = 0
        state["trade_date"] = date.today().isoformat()
        _save_state(state)
        if _mark_soft_warning_sent():
            _discord_alert(
                f"Portfolio soft warning\n"
                f"P&L: ${daily_pnl:+.2f} below soft warning -${soft_limit:.0f}.\n"
                f"No kill. Hard kill starts at -${hard_limit:.0f} for {polls_required} consecutive poll(s)."
            )
        return 0

    # All clear - reset breach counter
    _reset_breach_count()
    headroom = abs(hard_limit) + daily_pnl
    log.info(f"Portfolio OK - ${headroom:.2f} remaining before kill switch")
    return 0


if __name__ == "__main__":
    sys.exit(main())


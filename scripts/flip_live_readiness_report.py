#!/usr/bin/env python3
"""Read-only Flip live-transition readiness and affordability report."""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from strategies.flip_live_readiness import affordable_contracts, evaluate_live_readiness

ENV_PATH = ROOT / "agent" / ".env"
REPORT_PATH = Path.home() / ".vibe-trading" / "reports" / "flip-live-readiness.json"
MAX_NOTIONAL_PCT = 0.02
MAX_CONTRACTS = 5


def _load_env() -> None:
    if not ENV_PATH.exists():
        return
    for line in ENV_PATH.read_text(encoding="utf-8").splitlines():
        if not line.strip() or line.lstrip().startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip())


def _account() -> tuple[dict[str, Any], str | None]:
    key = os.getenv("ALPACA_API_KEY", "")
    secret = os.getenv("ALPACA_SECRET_KEY", "")
    paper = os.getenv("ALPACA_PAPER", "true").lower() == "true"
    base = "https://paper-api.alpaca.markets" if paper else "https://api.alpaca.markets"
    if not key or not secret:
        return {}, "credentials_missing"
    try:
        response = requests.get(
            f"{base}/v2/account",
            headers={"APCA-API-KEY-ID": key, "APCA-API-SECRET-KEY": secret},
            timeout=10,
        )
        response.raise_for_status()
        payload = response.json()
        return payload if isinstance(payload, dict) else {}, None
    except Exception as exc:
        return {}, str(exc)[:200]


def build_report(*, hypothetical_equity: float = 300.0) -> dict[str, Any]:
    _load_env()
    paper = os.getenv("ALPACA_PAPER", "true").lower() == "true"
    live_enabled = os.getenv("FLIP_LIVE_EXECUTION_ENABLED", "false").lower() == "true"
    account, account_error = _account()
    readiness = evaluate_live_readiness(
        account if not paper else {},
        live_enabled=live_enabled,
        approval_ack=os.getenv("FLIP_LIVE_APPROVAL_ACK", ""),
    )
    prices = (0.05, 0.25, 0.50, 1.00, 1.50, 2.00)
    affordability = [
        affordable_contracts(
            account_equity=hypothetical_equity,
            option_price=price,
            max_notional_pct=MAX_NOTIONAL_PCT,
            max_contracts=MAX_CONTRACTS,
        )
        for price in prices
    ]
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "mode": "paper" if paper else "live",
        "live_execution_enabled": live_enabled,
        "ready_for_live_entries": bool(not paper and readiness.ready),
        "live_blockers": ["configured_for_paper_endpoint"] if paper else list(readiness.blockers),
        "broker_account_read_error": account_error,
        "broker_account": {
            "status": account.get("status"),
            "equity": account.get("equity"),
            "buying_power": account.get("options_buying_power") or account.get("buying_power"),
            "options_trading_level": account.get("options_trading_level") or account.get("options_approved_level"),
            "trading_blocked": account.get("trading_blocked"),
        },
        "hypothetical_equity": hypothetical_equity,
        "configured_limits": {"max_notional_pct": MAX_NOTIONAL_PCT, "max_contracts": MAX_CONTRACTS},
        "affordability": affordability,
        "conclusion": (
            "Current 2% premium-notional cap cannot buy a typical option contract at this equity."
            if not any(row["affordable"] for row in affordability if row["option_price"] >= 0.25)
            else "At least one modeled option premium is affordable under current limits."
        ),
        "execution_enabled": False,
        "can_submit_orders": False,
        "changes_made": "none; read-only report",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--equity", type=float, default=300.0)
    parser.add_argument("--no-write", action="store_true")
    args = parser.parse_args()
    report = build_report(hypothetical_equity=args.equity)
    if not args.no_write:
        REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
        REPORT_PATH.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Read-only Polymarket top-wallet discovery.

Pulls the public profit leaderboard across time windows, keeps wallets that
are persistent (present in both the monthly and all-time windows), and runs
them through the existing wallet tracker scoring pipeline. On-chain history
cannot be faked, which makes this the only replication path with verifiable
data.

No API keys. No private keys. No order placement.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from strategies.polymarket_wallet_tracker import (
    PolymarketPublicClient,
    build_wallet_report,
    write_wallet_report,
    upsert_wallet_profile,
)

LEADERBOARD_BASE = "https://data-api.polymarket.com"
REPORT_FILE = Path.home() / ".vibe-trading" / "reports" / "polymarket-wallet-discovery.json"
DEFAULT_TIMEOUT_SECONDS = 20


def fetch_leaderboard(window: str, *, limit: int = 50, session: Any | None = None) -> list[dict[str, Any]]:
    active = session or requests.Session()
    response = active.get(
        f"{LEADERBOARD_BASE}/v1/leaderboard",
        params={"window": window, "limit": limit},
        timeout=DEFAULT_TIMEOUT_SECONDS,
    )
    response.raise_for_status()
    payload = response.json()
    rows = payload if isinstance(payload, list) else payload.get("leaderboard", [])
    return [row for row in rows if isinstance(row, dict)]


def _wallet(row: dict[str, Any]) -> str:
    return str(row.get("proxyWallet") or row.get("wallet") or row.get("address") or "").lower()


def discover_persistent_wallets(*, limit: int = 50, session: Any | None = None) -> dict[str, dict[str, Any]]:
    """Wallets present on both the monthly and all-time profit leaderboards."""
    month = {_wallet(row): row for row in fetch_leaderboard("month", limit=limit, session=session)}
    alltime = {_wallet(row): row for row in fetch_leaderboard("all", limit=limit, session=session)}
    persistent = {}
    for wallet, row in month.items():
        if wallet and wallet in alltime:
            persistent[wallet] = {
                "name": row.get("userName") or row.get("name") or row.get("pseudonym") or wallet,
                "month_profit": row.get("pnl", row.get("amount")),
                "alltime_profit": alltime[wallet].get("pnl", alltime[wallet].get("amount")),
            }
    return persistent


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Discover and score persistent top Polymarket wallets (read only).")
    parser.add_argument("--limit", type=int, default=50, help="Leaderboard depth per window.")
    parser.add_argument("--history-limit", type=int, default=500, help="Max history rows per wallet.")
    parser.add_argument("--max-wallets", type=int, default=10, help="Max persistent wallets to fully score.")
    parser.add_argument("--out", type=Path, default=REPORT_FILE)
    parser.add_argument("--append-profiles", action="store_true", help="Upsert scored wallets into copy-trader-profiles.json.")
    parser.add_argument("--print", action="store_true")
    args = parser.parse_args(argv)

    persistent = discover_persistent_wallets(limit=args.limit)
    ranked = sorted(
        persistent.items(),
        key=lambda item: float(item[1].get("month_profit") or 0),
        reverse=True,
    )[: args.max_wallets]

    client = PolymarketPublicClient()
    report = build_wallet_report([wallet for wallet, _ in ranked], client=client, limit=args.history_limit)
    for profile in report["wallets"]:
        meta = persistent.get(str(profile.get("wallet", "")).lower(), {})
        profile["leaderboard_name"] = meta.get("name")
        profile["leaderboard_month_profit"] = meta.get("month_profit")
        profile["leaderboard_alltime_profit"] = meta.get("alltime_profit")
    report["provider"] = "polymarket_wallet_discovery"
    report["persistence_filter"] = "wallet present on both month and all-time profit leaderboards"
    report["leaderboard_depth"] = args.limit
    report["persistent_wallet_count"] = len(persistent)

    write_wallet_report(report, args.out)
    if args.append_profiles:
        for profile in report["wallets"]:
            upsert_wallet_profile(profile)

    if args.print:
        summary = [
            {
                "name": p.get("leaderboard_name"),
                "wallet": p.get("wallet", "")[:10] + "...",
                "month_profit": p.get("leaderboard_month_profit"),
                "alltime_profit": p.get("leaderboard_alltime_profit"),
                "trades": p.get("trades"),
                "win_rate": p.get("win_rate"),
                "profit_factor": p.get("profit_factor"),
                "status": p.get("status"),
                "confidence": p.get("confidence"),
            }
            for p in report["wallets"]
        ]
        print(json.dumps({"generated_at": datetime.now(timezone.utc).isoformat(),
                          "persistent_wallets": len(persistent),
                          "scored": summary}, indent=2))
    else:
        print(f"Discovery report written to: {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

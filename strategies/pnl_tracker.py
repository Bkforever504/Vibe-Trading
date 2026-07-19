#!/usr/bin/env python3
"""
P&L Tracker — reads Alpaca closed orders and prints daily performance report.

Usage:
    python strategies/pnl_tracker.py              # today
    python strategies/pnl_tracker.py --days 7     # last 7 days
    python strategies/pnl_tracker.py --days 30    # last 30 days (full paper period)
"""
from __future__ import annotations

import os
import sys
from collections import defaultdict
from datetime import datetime, timedelta, timezone

from dotenv import load_dotenv

load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), "..", "agent", ".env"))

import requests

KEY    = os.getenv("ALPACA_API_KEY", "")
SECRET = os.getenv("ALPACA_SECRET_KEY", "")
PAPER  = os.getenv("ALPACA_PAPER", "true").lower() == "true"
BASE   = "https://paper-api.alpaca.markets" if PAPER else "https://api.alpaca.markets"
HDR    = {"APCA-API-KEY-ID": KEY, "APCA-API-SECRET-KEY": SECRET}


def _get(path: str, params: dict = {}) -> list | dict:
    r = requests.get(f"{BASE}{path}", headers=HDR, params=params, timeout=10)
    r.raise_for_status()
    return r.json()


def fetch_orders(days: int) -> list[dict]:
    since  = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    orders = _get("/v2/orders", {"status": "closed", "after": since, "limit": 500, "direction": "asc"})
    return [o for o in orders if o.get("filled_at")]


def fetch_account() -> dict:
    return _get("/v2/account")


def _leg_cashflow(order: dict) -> float:
    """Return estimated cashflow for one filled option leg.

    Sell fills are positive credits. Buy fills are negative debits.
    """
    filled_qty = float(order.get("filled_qty") or order.get("qty") or 0)
    filled_price = float(order.get("filled_avg_price") or order.get("limit_price") or 0)
    side = order.get("side", "")
    multiplier = 100 if str(order.get("asset_class", "us_option")) == "us_option" else 1
    cashflow = filled_price * filled_qty * multiplier
    return cashflow if side == "sell" else -cashflow


def _net_order(order: dict) -> dict:
    """Net a parent multi-leg order into one trade event.

    Alpaca multi-leg orders may include a `legs` array. When present, net those
    legs together so an opening spread is one credit/debit, not one fake win and
    one fake loss.
    """
    legs = order.get("legs") or []
    filled_at = order.get("filled_at", "")
    submitted_at = order.get("submitted_at", "")
    day = filled_at[:10] if filled_at else "unknown"
    order_id = order.get("id") or order.get("client_order_id") or ""

    if legs:
        cashflow = sum(_leg_cashflow(leg) for leg in legs)
        symbols = [leg.get("symbol", "") for leg in legs]
        return {
            "id": order_id,
            "day": day,
            "submitted_at": submitted_at,
            "filled_at": filled_at,
            "symbol": " / ".join(s for s in symbols if s),
            "side": "mleg",
            "legs": [
                {
                    "symbol": leg.get("symbol", ""),
                    "side": leg.get("side", ""),
                    "price": float(leg.get("filled_avg_price") or leg.get("limit_price") or 0),
                    "qty": float(leg.get("filled_qty") or leg.get("qty") or 0),
                    "cashflow": _leg_cashflow(leg),
                }
                for leg in legs
            ],
            "cashflow": cashflow,
        }

    return {
        "id": order_id,
        "day": day,
        "submitted_at": submitted_at,
        "filled_at": filled_at,
        "symbol": order.get("symbol", ""),
        "side": order.get("side", ""),
        "legs": [],
        "cashflow": _leg_cashflow(order),
    }


def build_report(orders: list[dict], days: int) -> None:
    acct         = fetch_account()
    equity       = float(acct.get("equity", 0))
    cash         = float(acct.get("cash", 0))
    buying_power = float(acct.get("buying_power", 0))

    print("\n" + "=" * 60)
    print(f"  OPTIONS BOT — P&L REPORT  (last {days} day(s))  [{'PAPER' if PAPER else 'LIVE'}]")
    print("=" * 60)
    print(f"  Account equity:    ${equity:>12,.2f}")
    print(f"  Cash available:    ${cash:>12,.2f}")
    print(f"  Buying power:      ${buying_power:>12,.2f}")
    print("-" * 60)

    if not orders:
        print(f"  No closed trades in the last {days} day(s).\n")
        return

    daily: dict[str, list] = defaultdict(list)
    credits = debits = 0
    total_cashflow  = 0.0
    hold_times: list[float] = []

    for o in orders:
        event = _net_order(o)
        total_cashflow += event["cashflow"]
        daily[event["day"]].append(event)

        submitted_at = event.get("submitted_at", "")
        filled_at = event.get("filled_at", "")
        if submitted_at and filled_at:
            try:
                t0 = datetime.fromisoformat(submitted_at.replace("Z", "+00:00"))
                t1 = datetime.fromisoformat(filled_at.replace("Z", "+00:00"))
                hold_times.append((t1 - t0).total_seconds() / 3600)
            except Exception:
                pass

        if event["cashflow"] > 0:
            credits += 1
        elif event["cashflow"] < 0:
            debits += 1

    total_events = credits + debits
    avg_hold     = (sum(hold_times) / len(hold_times)) if hold_times else 0

    print(f"  Closed order events:{total_events:>11}")
    print(f"  Credits / Debits:  {credits} / {debits}")
    print(f"  Net cashflow (est):${total_cashflow:>+,.2f}")
    print(f"  Avg fill time:     {avg_hold:.1f} hrs")
    print("=" * 60)

    print("\n  DAILY BREAKDOWN:")
    for day in sorted(daily.keys()):
        events   = daily[day]
        day_pnl = sum(f["cashflow"] for f in events)
        print(f"\n  {day}  ({len(events)} order event(s))  net cashflow~${day_pnl:+,.2f}")
        for f in events:
            print(f"    {f['side']:4s}  {f['symbol'][:35]:<35}  ~${f['cashflow']:+.2f}")
            for leg in f["legs"]:
                print(
                    f"      {leg['side']:4s} {leg['symbol']:<32} "
                    f"price={leg['price']:.2f} qty={leg['qty']:.0f} ~${leg['cashflow']:+.2f}"
                )

    print("\n  NOTE: This nets multi-leg order cashflows, but it is not realized strategy P&L")
    print("  unless matching open and close order groups are both present in the date range.")
    print("  Exact closed P&L: Alpaca dashboard -> Account -> History.\n")


def main() -> None:
    import argparse
    ap = argparse.ArgumentParser(description="Options Bot P&L Tracker")
    ap.add_argument("--days", type=int, default=1, help="Days to look back (default: 1)")
    args = ap.parse_args()

    if not KEY or not SECRET:
        print("ERROR: ALPACA_API_KEY / ALPACA_SECRET_KEY missing in agent/.env")
        sys.exit(1)

    print(f"Fetching last {args.days} day(s) of orders...")
    orders = fetch_orders(args.days)
    build_report(orders, args.days)


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""Read-only Tradovate live-data smoke test.

No orders. This validates credentials, resolves the active MNQ/NQ contract,
fetches recent chart bars, and writes a CSV snapshot for inspection.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from strategies.tradovate_market_data import (
    TradovateSettings,
    fetch_chart_candles,
    likely_contract_symbol,
    load_dotenv,
    redacted_settings,
    write_candles_csv,
)


def main() -> None:
    parser = argparse.ArgumentParser(description="Check read-only Tradovate market data access.")
    parser.add_argument("--symbol", default=os.getenv("TRADOVATE_SYMBOL", "MNQ"), help="Root or contract, e.g. MNQ or MNQU6.")
    parser.add_argument("--bars", type=int, default=30, help="Recent bars to request.")
    parser.add_argument("--interval-minutes", type=int, default=1, help="Minute-bar interval.")
    parser.add_argument("--json", action="store_true", help="Print machine-readable status.")
    args = parser.parse_args()

    load_dotenv(ROOT / "agent" / ".env")
    settings = TradovateSettings.from_env()
    missing = settings.missing_fields()
    contract = likely_contract_symbol(args.symbol)

    status = {
        "ok": False,
        "settings": redacted_settings(settings),
        "symbol": args.symbol,
        "contract": contract,
        "bars_requested": args.bars,
        "interval_minutes": args.interval_minutes,
        "missing_fields": missing,
        "csv": None,
        "error": None,
    }

    if missing:
        status["error"] = "missing_credentials"
        if args.json:
            print(json.dumps(status, indent=2))
        else:
            print("Tradovate credentials are not configured yet.")
            print("Add these to agent/.env:")
            for field in missing:
                print(f"  {field}=...")
            print("\nRequired by Tradovate API auth: username/password plus appId/cid/sec from API Access.")
        sys.exit(2)

    try:
        candles = fetch_chart_candles(
            contract,
            bars=args.bars,
            interval_minutes=args.interval_minutes,
            settings=settings,
        )
        output = Path(os.path.expanduser(r"~\.vibe-trading\tradovate")) / f"{contract}_{args.interval_minutes}m_latest.csv"
        write_candles_csv(candles, output)
        status.update({
            "ok": bool(candles),
            "bars_received": len(candles),
            "first_timestamp": candles[0].timestamp.isoformat() if candles else None,
            "last_timestamp": candles[-1].timestamp.isoformat() if candles else None,
            "last_close": candles[-1].close if candles else None,
            "csv": str(output),
        })
    except Exception as exc:
        status["error"] = str(exc)
        if args.json:
            print(json.dumps(status, indent=2))
        else:
            print(f"Tradovate market-data check failed: {exc}")
        sys.exit(1)

    if args.json:
        print(json.dumps(status, indent=2))
    else:
        print(f"Tradovate market data OK: {status['bars_received']} bar(s) for {contract}")
        print(f"Latest close: {status['last_close']} at {status['last_timestamp']} UTC")
        print(f"CSV written to: {status['csv']}")


if __name__ == "__main__":
    main()

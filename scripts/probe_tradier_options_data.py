#!/usr/bin/env python3
"""Credential-safe read-only probe for Tradier production market data."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.tradier_options_data import fetch_quotes_with_meta, quote_is_fresh


def _summary(symbol: str, parsed: dict[str, Any]) -> dict[str, Any]:
    quote = parsed.get("quote") if isinstance(parsed, dict) else {}
    provenance = parsed.get("provenance") if isinstance(parsed, dict) else {}
    return {
        "symbol": symbol,
        "bid": (quote or {}).get("bid"),
        "ask": (quote or {}).get("ask"),
        "quote_timestamp": (quote or {}).get("quote_timestamp"),
        "quote_age_seconds": (quote or {}).get("quote_age_seconds"),
        "fresh": quote_is_fresh(parsed),
        "provider": (provenance or {}).get("provider"),
        "quote_scope": (provenance or {}).get("quote_scope"),
        "status": (provenance or {}).get("status"),
        "missing_fields": (provenance or {}).get("missing_fields"),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "symbols",
        nargs="*",
        default=["IWM"],
        help="equity or OCC symbols; pass an OCC symbol to verify option entitlement",
    )
    args = parser.parse_args()
    try:
        quotes, meta = fetch_quotes_with_meta(args.symbols)
    except Exception as exc:
        print(
            json.dumps(
                {
                    "status": "blocked",
                    "error": f"{type(exc).__name__}: {exc}",
                    "execution_enabled": False,
                    "can_submit_orders": False,
                },
                indent=2,
                sort_keys=True,
            )
        )
        return 1
    report = {
        "status": "ok" if quotes else "blocked_no_quotes",
        "meta": meta,
        "quotes": [_summary(symbol, quotes.get(symbol.upper()) or {}) for symbol in args.symbols],
        "execution_enabled": False,
        "can_submit_orders": False,
    }
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if quotes else 1


if __name__ == "__main__":
    raise SystemExit(main())

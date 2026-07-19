#!/usr/bin/env python3
"""Check Ironbeam API readiness without submitting orders."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from strategies.ironbeam_market_data import (
    IronbeamSettings,
    likely_contract_symbol,
    load_dotenv,
    readiness_report,
    redacted_settings,
    request_access_token,
)


def main() -> int:
    parser = argparse.ArgumentParser(description="Read-only Ironbeam API readiness check")
    parser.add_argument("--symbol", default="MNQ", help="Root or contract, e.g. MNQ or MNQU6")
    parser.add_argument("--auth", action="store_true", help="Attempt bearer-token auth if readiness passes")
    args = parser.parse_args()

    load_dotenv(ROOT / "agent" / ".env")
    settings = IronbeamSettings.from_env()
    report = readiness_report(settings)
    output = {
        "settings": redacted_settings(settings),
        "contract": likely_contract_symbol(args.symbol),
        "readiness": report,
    }

    if args.auth and report["ready"]:
        token = request_access_token(settings)
        output["auth"] = {"ok": True, "token_preview": token[:4] + "***" + token[-4:]}
    elif args.auth:
        output["auth"] = {"ok": False, "reason": "readiness blockers must be cleared first"}

    print(json.dumps(output, indent=2))
    return 0 if report["ready"] else 2


if __name__ == "__main__":
    raise SystemExit(main())

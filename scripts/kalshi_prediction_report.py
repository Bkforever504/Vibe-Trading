#!/usr/bin/env python3
"""Generate the paper-only Kalshi prediction-market report."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv

from strategies.kalshi_prediction_bot import REPORT_FILE, load_fair_values, run_scan


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate paper-only Kalshi prediction-market report.")
    parser.add_argument("--limit", type=int, default=25, help="Number of active markets to scan.")
    parser.add_argument("--fair-values", type=Path, help="JSON mapping of Kalshi ticker to fair YES probability.")
    parser.add_argument("--out", type=Path, default=REPORT_FILE, help="Output report path.")
    parser.add_argument("--print", action="store_true", help="Print report JSON after writing it.")
    args = parser.parse_args()

    load_dotenv(ROOT / "agent" / ".env")
    report = run_scan(fair_values=load_fair_values(args.fair_values), out=args.out, limit=args.limit)
    if args.print:
        print(json.dumps(report, indent=2))
    else:
        print(f"Kalshi prediction report written to: {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

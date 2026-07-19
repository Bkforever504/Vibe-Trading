#!/usr/bin/env python3
"""Generate the paper-only copy-trader watchlist report."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from strategies.copy_trader_watchlist import DEFAULT_PROFILES_FILE, DEFAULT_SIGNALS_FILE, REPORT_FILE, run_report


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate paper-only copy-trader watchlist report.")
    parser.add_argument("--profiles", type=Path, default=DEFAULT_PROFILES_FILE, help="JSON list of trader profiles.")
    parser.add_argument("--signals", type=Path, default=DEFAULT_SIGNALS_FILE, help="JSON list of observed copy signals.")
    parser.add_argument("--out", type=Path, default=REPORT_FILE, help="Output report path.")
    parser.add_argument("--print", action="store_true", help="Print report JSON after writing it.")
    args = parser.parse_args()

    report = run_report(profiles_path=args.profiles, signals_path=args.signals, out=args.out)
    if args.print:
        print(json.dumps(report, indent=2))
    else:
        print(f"Copy trader watchlist written to: {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

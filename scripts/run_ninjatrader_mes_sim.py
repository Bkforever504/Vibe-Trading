#!/usr/bin/env python3
"""Run the MES candidate and optionally dispatch a Sim101-only OIF entry."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from strategies.mes_sim_candidate import run_mes_candidate


def main() -> None:
    parser = argparse.ArgumentParser(description="MES NinjaTrader Sim101 forward-test runner")
    parser.add_argument(
        "--execute-sim",
        action="store_true",
        help="Allow the fail-closed adapter to dispatch one Sim101 MES entry when a signal exists",
    )
    args = parser.parse_args()
    print(json.dumps(run_mes_candidate(execute_sim=args.execute_sim), indent=2, default=str))


if __name__ == "__main__":
    main()

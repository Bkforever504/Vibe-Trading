"""Read-only Polygon options-chain smoke test and weekly cost report."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
load_dotenv(ROOT / "agent" / ".env")

from agent.data_providers.polygon_options_client import PolygonOptionsClient  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("symbols", nargs="*", default=["SPY", "QQQ", "IWM"])
    parser.add_argument("--minimum-strikes", type=int, default=20)
    args = parser.parse_args()

    client = PolygonOptionsClient()
    results = [client.fetch_chain(symbol) for symbol in args.symbols]
    report_path = client.write_weekly_cost_report()
    summaries = [{key: value for key, value in result.items() if key != "contracts"} for result in results]
    payload = {
        "status": "ok" if all(r["status"] == "ok" and r["contract_count"] >= args.minimum_strikes for r in results) else "missing",
        "results": summaries,
        "minimum_strikes": args.minimum_strikes,
        "cost_report": str(report_path),
        "execution_enabled": False,
    }
    print(json.dumps(payload, indent=2))
    return 0 if payload["status"] == "ok" else 2


if __name__ == "__main__":
    raise SystemExit(main())

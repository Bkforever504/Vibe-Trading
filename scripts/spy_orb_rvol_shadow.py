#!/usr/bin/env python3
"""Log the exact SPY 15-minute ORB + RVOL candidate without order authority."""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import replace
from datetime import date, time, timedelta, timezone, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from research.spy_orb_edge_lab import LabConfig, fetch_alpaca, replay

REPORT = Path.home() / ".vibe-trading" / "reports" / "spy-orb-rvol-shadow.json"
LOG = ROOT / "data" / "spy_orb_rvol_shadow.jsonl"


def build_report() -> dict:
    today = date.today()
    bars = fetch_alpaca((today - timedelta(days=55)).isoformat(), None)
    config = replace(LabConfig(), opening_minutes=15, last_entry_et=time(10, 30), reward_risk=1.5)
    trades = replay(bars, config)["relative_open_volume"]
    today_trade = next((trade for trade in reversed(trades) if trade["date"] == today.isoformat()), None)
    signal = None
    if today_trade:
        signal = {key: value for key, value in today_trade.items() if key not in {"outcome", "net_r"}}
        signal.update({"status": "shadow_signal", "outcome": "pending_external_evaluation"})
    return {
        "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "date": today.isoformat(), "strategy": "spy_15m_orb_rvol", "mode": "shadow_only",
        "execution_enabled": False, "can_submit_orders": False,
        "status": "signal" if signal else "no_signal", "signal": signal,
        "promotion_gate": "30+ untouched forward signals, positive expectancy, PF >= 1.15, option quote replay",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", type=Path, default=REPORT)
    parser.add_argument("--log", type=Path, default=LOG)
    parser.add_argument("--no-append", action="store_true")
    parser.add_argument("--print", action="store_true", dest="do_print")
    args = parser.parse_args()
    report = build_report()
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    if not args.no_append:
        args.log.parent.mkdir(parents=True, exist_ok=True)
        with args.log.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(report, separators=(",", ":"), sort_keys=True) + "\n")
    if args.do_print:
        print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

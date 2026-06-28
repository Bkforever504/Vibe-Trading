"""
Read-only RSI-2 shadow report.

Usage:
    python scripts/rsi2_shadow_report.py
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path


LOG_PATH = Path(__file__).resolve().parent.parent / "data" / "rsi2_shadow_log.jsonl"
FORWARD_DAYS_NEEDED = 30
SIGNALS_NEEDED = 10


def load_entries(log_path: Path = LOG_PATH) -> list[dict]:
    if not log_path.exists():
        return []
    entries: list[dict] = []
    for line in log_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(row, dict):
            entries.append(row)
    return sorted(entries, key=lambda row: row.get("date", ""))


def _count_entries(entries: list[dict], setup_key: str, action: str) -> int:
    return sum(1 for row in entries if row.get(setup_key, {}).get("action") == action)


def print_report(entries: list[dict]) -> None:
    print("\n" + "=" * 62)
    print("RSI-2 QQQ Shadow Dashboard")
    print(f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print("=" * 62 + "\n")

    if not entries:
        print("No RSI-2 shadow logs found. Run scripts/rsi2_shadow_logger.py first.")
        return

    latest = entries[-1]
    features = latest.get("features", {})
    print("CURRENT SIGNAL")
    print(f"  Date:   {latest.get('date')}")
    print(f"  Symbol: {latest.get('symbol', 'QQQ')}")
    print(f"  Close:  {features.get('close')}")
    print(f"  RSI2:   {features.get('rsi2')}")
    print(f"  EMA200: {features.get('ema200')}")
    print()

    for key, label in [("primary_setup", "Primary"), ("comparison_setup", "Comparison")]:
        setup = latest.get(key, {})
        print(f"{label}: {setup.get('name')}")
        print(f"  Confidence: {setup.get('confidence')}")
        print(f"  Action:     {setup.get('action')}")
        print(f"  In trade:   {setup.get('in_position')}")
    print()

    primary_entries = _count_entries(entries, "primary_setup", "enter_long")
    comparison_entries = _count_entries(entries, "comparison_setup", "enter_long")
    days = len(entries)
    ready = days >= FORWARD_DAYS_NEEDED and primary_entries >= SIGNALS_NEEDED
    print("FORWARD TEST STATUS")
    print(f"  Log rows:          {days}/{FORWARD_DAYS_NEEDED}")
    print(f"  Primary entries:   {primary_entries}/{SIGNALS_NEEDED}")
    print(f"  Comparison entries:{comparison_entries}/{SIGNALS_NEEDED}")
    print(f"  Status:            {'READY FOR REVIEW' if ready else 'NOT READY - DO NOT EXECUTE'}")


def main() -> int:
    print_report(load_entries(LOG_PATH))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

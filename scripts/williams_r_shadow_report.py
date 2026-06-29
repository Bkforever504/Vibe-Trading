"""
Read-only Williams %R shadow report.

Usage:
    python scripts/williams_r_shadow_report.py
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path


LOG_PATH = Path(__file__).resolve().parent.parent / "data" / "williams_r_shadow_log.jsonl"
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
    print("Williams %R Shadow Dashboard")
    print(f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print("=" * 62 + "\n")

    if not entries:
        print("No Williams %R shadow logs found. Run scripts/williams_r_shadow_logger.py first.")
        return

    latest = entries[-1]
    print("CURRENT SIGNAL")
    print(f"  Date: {latest.get('date')}")

    for key, label in [("primary_setup", "Primary"), ("comparison_setup", "Comparison")]:
        setup = latest.get(key, {})
        print(f"\n{label}: {setup.get('name')} ({setup.get('symbol')})")
        print(f"  Confidence: {setup.get('confidence')}")
        print(f"  WR now:     {setup.get('wr_now')}")
        print(f"  Action:     {setup.get('action')}")
        print(f"  In trade:   {setup.get('in_position')}")
        if setup.get("trend_filter_active"):
            print(f"  Above SMA:  {setup.get('above_trend_sma')}")

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
    print()
    print("OVERLAP NOTE")
    print("  Must compare signal overlap vs RSI-2 QQQ before any execution.")
    print("  Both are oversold mean-reversion on the same symbol.")


def main() -> int:
    print_report(load_entries(LOG_PATH))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

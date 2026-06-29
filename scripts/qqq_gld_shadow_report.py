"""
Read-only QQQ/GLD rotation shadow report.

Usage:
    python scripts/qqq_gld_shadow_report.py
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path


LOG_PATH = Path(__file__).resolve().parent.parent / "data" / "qqq_gld_shadow_log.jsonl"
FORWARD_ROWS_NEEDED = 8


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


def print_report(entries: list[dict]) -> None:
    print("\n" + "=" * 62)
    print("QQQ/GLD Rotation Shadow Dashboard")
    print(f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print("=" * 62 + "\n")

    if not entries:
        print("No QQQ/GLD shadow logs found. Run scripts/qqq_gld_shadow_logger.py first.")
        return

    latest = entries[-1]
    switches = sum(1 for row in entries if str(row.get("action", "")).startswith("rotate_to_"))
    qqq_rows = sum(1 for row in entries if row.get("selected") == "QQQ")
    gld_rows = sum(1 for row in entries if row.get("selected") == "GLD")

    print("CURRENT SIGNAL")
    print(f"  Date:          {latest.get('date')}")
    print(f"  Selected:      {latest.get('selected')}")
    print(f"  Action:        {latest.get('action')}")
    print(f"  Confidence:    {latest.get('confidence')}")
    print(f"  Return spread: {float(latest.get('return_spread', 0)) * 100:+.2f}%")
    print()
    print("FORWARD TEST STATUS")
    print(f"  Log rows:      {len(entries)}/{FORWARD_ROWS_NEEDED}")
    print(f"  Switches:      {switches}")
    print(f"  QQQ rows:      {qqq_rows}")
    print(f"  GLD rows:      {gld_rows}")
    print(f"  Status:        {'READY FOR REVIEW' if len(entries) >= FORWARD_ROWS_NEEDED else 'NOT READY - DO NOT EXECUTE'}")
    print()
    print("RISK NOTE")
    print("  This is QQQ/GLD only. TQQQ rows were rejected for high drawdown.")
    print("  Must compare overlap vs existing multi-asset momentum rotation before execution.")


def main() -> int:
    print_report(load_entries(LOG_PATH))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

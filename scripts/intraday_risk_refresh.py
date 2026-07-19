#!/usr/bin/env python3
"""Refresh protective news/catalyst/consensus context in dependency order."""
from __future__ import annotations

import argparse
import subprocess
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def refresh(day: str | None = None) -> list[dict[str, object]]:
    day = day or date.today().isoformat()
    steps = [
        ("geopolitical_risk", ["scripts/geopolitical_risk_context.py", "--date", day]),
        ("catalyst_calendar", ["scripts/market_catalyst_calendar.py", "--date", day]),
        ("market_force", ["scripts/market_force_score.py", "--date", day]),
        ("adaptive_options", ["scripts/adaptive_options_shadow_playbook.py"]),
        ("shadow_consensus", ["scripts/shadow_consensus_gate.py", "--date", day]),
        ("daily_edge", ["scripts/daily_edge_orchestrator.py", "--date", day]),
    ]
    results = []
    for name, args in steps:
        completed = subprocess.run(
            [sys.executable, *args],
            cwd=ROOT,
            text=True,
            capture_output=True,
            timeout=90,
            check=False,
        )
        results.append({
            "name": name,
            "returncode": completed.returncode,
            "stdout": completed.stdout.strip()[-500:],
            "stderr": completed.stderr.strip()[-500:],
        })
        if completed.returncode != 0:
            break
    return results


def main() -> int:
    parser = argparse.ArgumentParser(description="Refresh intraday protective risk context.")
    parser.add_argument("--date")
    args = parser.parse_args()
    results = refresh(args.date)
    for row in results:
        print(f"{row['name']}: exit={row['returncode']} {row['stdout']}")
        if row["stderr"]:
            print(f"  stderr={row['stderr']}")
    return 0 if results and all(row["returncode"] == 0 for row in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())

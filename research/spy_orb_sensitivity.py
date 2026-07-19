#!/usr/bin/env python3
"""Small preregistered structural sensitivity grid for the SPY ORB lab."""
from __future__ import annotations

import json
import sys
from dataclasses import replace
from datetime import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from research.spy_orb_edge_lab import LabConfig, load_bars, metrics, replay

OUTPUT = Path.home() / ".vibe-trading" / "reports" / "spy-orb-sensitivity.json"


def main() -> int:
    bars = load_bars("2022-01-01", None, False)
    rows = []
    for opening_minutes in (5, 15):
        for reward_risk in (1.0, 1.5, 2.0):
            for cutoff in (time(10, 30), time(11, 30)):
                config = replace(
                    LabConfig(), opening_minutes=opening_minutes,
                    reward_risk=reward_risk, last_entry_et=cutoff,
                )
                trades = replay(bars, config)
                row = {
                    "opening_minutes": opening_minutes,
                    "reward_risk": reward_risk,
                    "last_entry_et": cutoff.isoformat(timespec="minutes"),
                }
                for variant in ("baseline", "relative_open_volume"):
                    values = trades[variant]
                    split = int(len(values) * 0.70)
                    row[variant] = {"train": metrics(values[:split]), "holdout": metrics(values[split:])}
                rows.append(row)
                print(
                    f"OR={opening_minutes:>2} RR={reward_risk:.1f} cutoff={cutoff:%H:%M} "
                    f"base_oos={row['baseline']['holdout']['expectancy_r']} "
                    f"rvol_oos={row['relative_open_volume']['holdout']['expectancy_r']}"
                )
    report = {
        "mode": "research_only", "execution_enabled": False, "rows": rows,
        "warning": "This finite grid is a robustness diagnostic, not permission to select the best holdout result.",
    }
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(report, indent=2, default=str) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

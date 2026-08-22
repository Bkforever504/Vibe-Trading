#!/usr/bin/env python3
"""Read-only evidence report for the QQQ mean-reversion shadow lane."""
from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path
from typing import Any

import numpy as np


ROOT = Path(__file__).resolve().parents[1]
LOG_PATH = ROOT / "data" / "qqq_mean_reversion_shadow_log.jsonl"
MINIMUM_DAYS = 30
MINIMUM_OUTCOMES = 10


def load_rows(path: Path = LOG_PATH) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(row, dict):
            rows.append(row)
    return rows


def summarize(rows: list[dict[str, Any]]) -> dict[str, Any]:
    signals = [row for row in rows if row.get("record_type") == "signal"]
    outcomes = [row for row in rows if row.get("record_type") == "outcome" and row.get("status") == "resolved"]
    observation_dates = sorted({str(row.get("date")) for row in signals if row.get("date")})
    grouped: dict[str, list[float]] = defaultdict(list)
    for row in outcomes:
        grouped[str(row.get("variant"))].append(float(row.get("net_pnl_per_10000", 0.0)))
    evidence: dict[str, Any] = {}
    for variant, values in sorted(grouped.items()):
        array = np.asarray(values, dtype=float)
        wins = array[array > 0]
        losses = array[array <= 0]
        evidence[variant] = {
            "resolved_outcomes": len(array),
            "expectancy_per_10000": round(float(array.mean()), 2),
            "win_rate": round(float((array > 0).mean()), 4),
            "profit_factor": round(float(wins.sum() / abs(losses.sum())), 4) if len(losses) else None,
            "review_sample_ready": len(observation_dates) >= MINIMUM_DAYS and len(array) >= MINIMUM_OUTCOMES,
        }
    latest = signals[-1] if signals else {}
    return {
        "mode": "shadow_only",
        "execution_enabled": False,
        "can_submit_orders": False,
        "logged_trading_days": len(observation_dates),
        "minimum_logged_trading_days": MINIMUM_DAYS,
        "minimum_resolved_outcomes_per_variant": MINIMUM_OUTCOMES,
        "latest_date": latest.get("date"),
        "latest_actions": {
            name: setup.get("action")
            for name, setup in latest.get("setups", {}).items()
        },
        "variant_evidence": evidence,
        "promotion_ready": False,
        "warning": "Sample readiness only triggers human review; it never grants execution authority.",
    }


def main() -> int:
    print(json.dumps(summarize(load_rows()), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

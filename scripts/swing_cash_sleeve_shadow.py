#!/usr/bin/env python3
"""Monthly shadow decision for the breadth-scaled swing portfolio."""
from __future__ import annotations

import argparse
import json
import sys
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from research.higher_timeframe_volume_screen_lab import load_symbol, period_candidates
from research.swing_risk_overlay_lab import (
    BASELINE,
    OVERLAYS,
    SYMBOLS,
    build_context,
    eligible_candidates,
    exposure_for_overlay,
)


DEFAULT_OUTPUT = ROOT / "data" / "swing_cash_sleeve_shadow_decision.json"
BREADTH_OVERLAY = next(row for row in OVERLAYS if row.name == "breadth_scaled")


def completed_month_cutoff(as_of: date) -> pd.Timestamp:
    return pd.Timestamp(as_of).replace(day=1) - pd.Timedelta(days=1)


def build_shadow_decision(
    decision_date: str,
    candidates: list[dict[str, Any]],
    context: dict[str, Any],
) -> dict[str, Any]:
    selected = eligible_candidates(candidates, BREADTH_OVERLAY, context)
    exposure = exposure_for_overlay(BREADTH_OVERLAY, context, 0.0)
    raw_weight = 1.0 / len(selected) if selected else 0.0
    position_weight = exposure * raw_weight
    allocations = [
        {"symbol": row["symbol"], "weight": round(position_weight, 6)}
        for row in selected
    ]
    concentration_ok = position_weight <= 0.35 + 1e-12
    return {
        "schema_version": 1,
        "strategy": "monthly_momentum_breadth_bil_cash",
        "mode": "shadow_only",
        "decision_date": decision_date,
        "breadth": round(float(context["breadth"]), 6),
        "equity_exposure": round(exposure, 6),
        "treasury_symbol": "BIL",
        "treasury_exposure": round(1.0 - exposure, 6),
        "equity_allocations": allocations,
        "maximum_position_weight": round(position_weight, 6),
        "concentration_cap": 0.35,
        "concentration_ok": concentration_ok,
        "promotion_eligible": False,
        "execution_enabled": False,
        "can_submit_orders": False,
        "blockers": [
            reason
            for reason, active in (
                ("insufficient_forward_observations", True),
                ("historical_promotion_gates_not_passed", True),
                ("position_concentration_above_35pct", not concentration_ok),
            )
            if active
        ],
    }


def current_decision(*, as_of: date, refresh: bool) -> dict[str, Any]:
    cutoff = completed_month_cutoff(as_of)
    as_of_stamp = pd.Timestamp(as_of)
    frames = {
        symbol: load_symbol(symbol, "2015-01-01", None, refresh).loc[:as_of_stamp]
        for symbol in SYMBOLS
    }
    source_last_date = min(frame.index[-1] for frame in frames.values())
    candidates = [
        row
        for symbol, frame in frames.items()
        for row in period_candidates(symbol, frame, "monthly")
        if pd.Timestamp(row["decision_date"]) <= cutoff
    ]
    if not candidates:
        raise RuntimeError("no completed monthly candidates available")
    decision_date = max(row["decision_date"] for row in candidates)
    date_candidates = [row for row in candidates if row["decision_date"] == decision_date]
    context = build_context(frames, decision_date)
    payload = build_shadow_decision(decision_date, date_candidates, context)
    payload["generated_at"] = datetime.now(timezone.utc).isoformat()
    payload["requested_data_cutoff"] = str(cutoff.date())
    payload["source_last_date"] = str(source_last_date.date())
    payload["source_staleness_calendar_days"] = int((as_of_stamp - source_last_date).days)
    if payload["source_staleness_calendar_days"] > 5:
        payload["blockers"].append("source_data_stale")
    return payload


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--as-of", type=date.fromisoformat, default=date.today())
    parser.add_argument("--refresh", action="store_true")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    payload = current_decision(as_of=args.as_of, refresh=args.refresh)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

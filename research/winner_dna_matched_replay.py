#!/usr/bin/env python3
"""Match realized winner archetypes to every historical losing twin."""
from __future__ import annotations

import argparse
import json
import math
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from research.green_day_htf_ltf_lab import (  # noqa: E402
    MINUTE_PATH,
    build_htf_table,
    load_daily,
    metrics,
    replay_spy,
)
from scripts import lifecycle_normalizer as canon  # noqa: E402
from scripts.closed_trade_postmortem import dedupe_options_trade_records  # noqa: E402

VIBE_HOME = Path.home() / ".vibe-trading"
FLIP_PATH = VIBE_HOME / "flip-trades.json"
OPTIONS_PATH = VIBE_HOME / "options-trades.json"
OUTPUT_PATH = ROOT / "data" / "winner_dna_matched_replay_results.json"
CHECKPOINT = "10:30"
CORE_FEATURES = {
    "bull": (
        "above_vwap",
        "above_ema50",
        "ema50_sloping_up",
        "green_session",
        "not_extended_from_vwap",
        "pullback_held_trend",
    ),
    "bear": (
        "below_vwap",
        "below_ema50",
        "ema50_sloping_down",
        "red_session",
        "not_extended_from_vwap",
        "pullback_failed_near_trend",
    ),
}


def _read_json(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        return default


def _entry_time_et(row: dict[str, Any]) -> str | None:
    quality = row.get("entry_quality")
    if isinstance(quality, dict) and quality.get("entry_minute_et"):
        return str(quality["entry_minute_et"])
    raw = row.get("entry_at")
    if not raw:
        return None
    stamp = pd.Timestamp(raw)
    if stamp.tzinfo is None:
        return None
    return stamp.tz_convert("America/New_York").strftime("%H:%M")


def _legacy_core_snapshot(row: dict[str, Any], direction: str) -> dict[str, bool]:
    quality = row.get("entry_quality")
    snapshot = quality.get("feature_snapshot") if isinstance(quality, dict) else None
    if isinstance(snapshot, dict):
        return {name: snapshot.get(name) is True for name in CORE_FEATURES[direction]}
    catalyst = str(row.get("catalyst") or "").lower()
    phrases = {
        "above_vwap": "above vwap",
        "above_ema50": "above 50ema",
        "ema50_sloping_up": "50ema sloping up",
        "green_session": "green session",
        "pullback_held_trend": "pullback held trend",
        "below_vwap": "below vwap",
        "below_ema50": "below 50ema",
        "ema50_sloping_down": "50ema sloping down",
        "red_session": "red session",
        "pullback_failed_near_trend": "pullback failed near trend",
        "not_extended_from_vwap": "not extended from vwap",
    }
    return {name: phrases[name] in catalyst for name in CORE_FEATURES[direction]}


def actual_flip_seeds(path: Path = FLIP_PATH) -> dict[str, Any]:
    rows = _read_json(path, [])
    closed = [row for row in rows if isinstance(row, dict) and row.get("status") == "closed"]
    evidence: list[dict[str, Any]] = []
    for row in closed:
        view = canon.normalize_flip_trade(row)
        contracts = int(row.get("contracts") or 0)
        if view["quarantined"] or not 1 <= contracts <= 5:
            continue
        direction = "bull" if view["direction"] == "bullish" else "bear"
        snapshot = _legacy_core_snapshot(row, direction)
        evidence.append({
            "trade_id": row.get("id"),
            "date": str(row.get("entry_date") or "")[:10],
            "entry_time_et": _entry_time_et(row),
            "direction": direction,
            "right": row.get("right"),
            "pnl_dollars": view.get("pnl_dollars"),
            "winner": float(view.get("pnl_dollars") or 0.0) > 0,
            "core_snapshot": snapshot,
            "core_complete": all(snapshot.values()),
        })
    winners = [row for row in evidence if row["winner"]]
    modal_checkpoint = Counter(
        row["entry_time_et"] for row in winners if row["entry_time_et"]
    ).most_common(1)
    archetypes: dict[str, Any] = {}
    for direction in ("bull", "bear"):
        seeds = [
            row for row in winners
            if row["direction"] == direction
            and row["entry_time_et"] == CHECKPOINT
            and row["core_complete"]
        ]
        twins = [
            row for row in evidence
            if row["direction"] == direction
            and row["entry_time_et"] == CHECKPOINT
            and row["core_complete"]
        ]
        archetypes[direction] = {
            "winner_seed_count": len(seeds),
            "actual_twin_count": len(twins),
            "actual_twin_wins": sum(row["winner"] for row in twins),
            "actual_twin_losses": sum(not row["winner"] for row in twins),
            "actual_twin_net_pnl_dollars": round(
                sum(float(row["pnl_dollars"] or 0.0) for row in twins), 2
            ),
            "seed_trade_ids": [row["trade_id"] for row in seeds],
        }
    return {
        "source_closed_count": len(closed),
        "eligible_current_size_count": len(evidence),
        "winner_count": len(winners),
        "modal_winner_checkpoint_et": modal_checkpoint[0][0] if modal_checkpoint else None,
        "modal_winner_checkpoint_count": modal_checkpoint[0][1] if modal_checkpoint else 0,
        "archetypes": archetypes,
        "trades": evidence,
    }


def actual_options_seed_status(path: Path = OPTIONS_PATH) -> dict[str, Any]:
    payload = _read_json(path, {})
    source = payload.get("trades", []) if isinstance(payload, dict) else []
    rows = [
        row for row in dedupe_options_trade_records(source)
        if isinstance(row, dict) and row.get("status") == "closed"
    ]
    views = [canon.normalize_options_trade(row) for row in rows]
    eligible = [
        view for view in views
        if not view["quarantined"] and view.get("pnl_dollars") is not None
    ]
    winners = [view for view in eligible if float(view["pnl_dollars"]) > 0]
    return {
        "deduplicated_closed_count": len(rows),
        "fill_derived_eligible_count": len(eligible),
        "fill_derived_winner_count": len(winners),
        "minimum_winners_for_archetype": 5,
        "archetype_status": "eligible" if len(winners) >= 5 else "insufficient_fill_derived_winners",
        "excluded_count": len(rows) - len(eligible),
    }


def _window(day: str) -> str:
    year = int(day[:4])
    if year <= 2023:
        return "development_2022_2023"
    if year == 2024:
        return "selection_2024"
    return "diagnostic_consumed_2025_plus"


def _gate(archetype: dict[str, Any]) -> tuple[str, list[str]]:
    blockers: list[str] = []
    overall = archetype["overall"]
    if overall["count"] < 30:
        blockers.append("fewer_than_30_historical_matches")
    if archetype["independent_dates"] < 20:
        blockers.append("fewer_than_20_independent_dates")
    for name, partition in archetype["partitions"].items():
        if partition["expectancy"] is None or partition["expectancy"] <= 0:
            blockers.append(f"{name}_expectancy_not_positive")
        pf = partition["profit_factor"]
        if not isinstance(pf, (int, float)) or pf <= 1.10:
            blockers.append(f"{name}_profit_factor_not_above_1_10")
    if (
        overall.get("top_one_pct_removed_expectancy") is None
        or overall["top_one_pct_removed_expectancy"] <= 0
    ):
        blockers.append("top_one_pct_removed_expectancy_not_positive")
    ci = overall.get("block_bootstrap_ci95") or [None, None]
    if ci[0] is None or ci[0] <= 0:
        blockers.append("overall_ci_lower_bound_not_above_zero")
    return ("forward_shadow_nominee" if not blockers else "not_nominated", blockers)


def build_report(
    flip_path: Path = FLIP_PATH,
    options_path: Path = OPTIONS_PATH,
    minute_path: Path = MINUTE_PATH,
) -> dict[str, Any]:
    flip = actual_flip_seeds(flip_path)
    minute = pd.read_parquet(minute_path)
    daily = load_daily("SPY")
    if daily is None:
        raise FileNotFoundError("SPY daily cache missing")
    replay_rows, coverage = replay_spy(
        minute, build_htf_table(daily), completeness="per_checkpoint"
    )
    combined = [
        row for row in replay_rows
        if row["checkpoint_et"] == CHECKPOINT and row["variant"] == "ltf_only"
    ]
    combined_summary = {
        "eligible_sessions": (
            coverage.get("per_checkpoint_eligible_sessions", {}).get(CHECKPOINT)
        ),
        "signal_count": len(combined),
        "partitions": {
            name: metrics(
                [row for row in combined if _window(row["date"]) == name],
                "return_60m_bps",
            )
            for name in (
                "development_2022_2023",
                "selection_2024",
                "diagnostic_consumed_2025_plus",
            )
        },
        "overall": metrics(combined, "return_60m_bps"),
    }
    archetypes: dict[str, Any] = {}
    for direction in ("bull", "bear"):
        selected = [
            row for row in replay_rows
            if row["checkpoint_et"] == CHECKPOINT
            and row["variant"] == "ltf_only"
            and row["direction"] == direction
        ]
        partitions = {
            name: metrics(
                [row for row in selected if _window(row["date"]) == name],
                "return_60m_bps",
            )
            for name in (
                "development_2022_2023",
                "selection_2024",
                "diagnostic_consumed_2025_plus",
            )
        }
        result = {
            **flip["archetypes"][direction],
            "frozen_features": list(CORE_FEATURES[direction]),
            "checkpoint_et": CHECKPOINT,
            "historical_match_count": len(selected),
            "independent_dates": len({row["date"] for row in selected}),
            "partitions": partitions,
            "overall": metrics(selected, "return_60m_bps"),
        }
        result["promotion_status"], result["promotion_blockers"] = _gate(result)
        result["research_lead"] = (
            result["overall"]["expectancy"] is not None
            and result["overall"]["expectancy"] > 0
            and result["overall"]["profit_factor"] not in (None, "inf")
            and float(result["overall"]["profit_factor"]) > 1.10
        )
        archetypes[direction] = result
    return {
        "schema_version": 1,
        "generated_at": datetime.now().astimezone().isoformat(),
        "mode": "read_only_winner_dna_matched_replay",
        "execution_enabled": False,
        "can_submit_orders": False,
        "checkpoint_et": CHECKPOINT,
        "outcome": "60m_directional_underlying_bps_minus_2bps",
        "actual_flip": flip,
        "actual_options": actual_options_seed_status(options_path),
        "historical_coverage": coverage,
        "combined_10_30_reconciliation": combined_summary,
        "archetypes": archetypes,
        "conclusion": {
            "promotion_count": sum(
                row["promotion_status"] == "forward_shadow_nominee"
                for row in archetypes.values()
            ),
            "research_leads": [
                name for name, row in archetypes.items() if row["research_lead"]
            ],
            "production_change_allowed": False,
        },
        "warnings": [
            "Winner seeds select hypotheses; they do not prove them.",
            "All historical losing twins are retained.",
            "SPY IEX underlying returns do not reproduce 0DTE option fills or convexity.",
            "The 2025+ period is consumed diagnostic evidence, not pristine OOS.",
            "Only a new forward-only sample can promote a research lead.",
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--flip-path", type=Path, default=FLIP_PATH)
    parser.add_argument("--options-path", type=Path, default=OPTIONS_PATH)
    parser.add_argument("--minute-path", type=Path, default=MINUTE_PATH)
    parser.add_argument("--output", type=Path, default=OUTPUT_PATH)
    args = parser.parse_args()
    report = build_report(args.flip_path, args.options_path, args.minute_path)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(json.dumps({
        "output": str(args.output),
        "flip_winners": report["actual_flip"]["winner_count"],
        "options_fill_winners": report["actual_options"]["fill_derived_winner_count"],
        "archetypes": {
            name: {
                "matches": row["historical_match_count"],
                "expectancy_bps": row["overall"]["expectancy"],
                "profit_factor": row["overall"]["profit_factor"],
                "status": row["promotion_status"],
            }
            for name, row in report["archetypes"].items()
        },
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

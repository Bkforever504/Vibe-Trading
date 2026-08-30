#!/usr/bin/env python3
"""Resolve mapped-SPY-level shadow observations into frozen research slices.

The report measures an underlying 60-minute proxy only after the observation
was available from a completed five-minute bar.  It cannot estimate option
premium, fills, fees, or submit an order.  Gap, breadth, and intermarket fields
are carried solely to test whether they add explanatory value.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from statistics import median
from typing import Any, Iterable, Mapping
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.spy_level_reaction_shadow import (
    ET, REACTION_LEDGER_PATH, SYMBOL, _completed_rows, _credentials, _finite, _parse_timestamp,
)

import requests


VIBE_HOME = Path.home() / ".vibe-trading"
REPORT_PATH = VIBE_HOME / "reports" / "spy-level-reaction-outcomes.json"
OUTCOME_LEDGER_PATH = ROOT / "data" / "spy_level_reaction_outcomes.jsonl"
HORIZON_MINUTES = 60
MINIMUM_BUCKET_SAMPLE = 30


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            item = json.loads(line)
            if isinstance(item, dict):
                rows.append(item)
    except (OSError, ValueError, TypeError):
        return rows
    return rows


def _candidate_time(candidate: Mapping[str, Any]) -> datetime | None:
    reaction = candidate.get("reaction") if isinstance(candidate.get("reaction"), Mapping) else {}
    return _parse_timestamp(reaction.get("decision_available_at") or reaction.get("observed_at"))


def pending_candidates(candidates: Iterable[Mapping[str, Any]], existing_ids: set[str], *, now_et: datetime) -> list[dict[str, Any]]:
    pending: list[dict[str, Any]] = []
    for candidate in candidates:
        if candidate.get("eligible_for_outcome_comparison") is not True:
            continue
        candidate_id = str(candidate.get("candidate_id") or "")
        available_at = _candidate_time(candidate)
        if not candidate_id or candidate_id in existing_ids or available_at is None:
            continue
        if available_at + timedelta(minutes=HORIZON_MINUTES) <= now_et:
            pending.append(dict(candidate))
    return pending


def fetch_spy_bars(start_et: datetime, end_et: datetime) -> list[dict[str, Any]]:
    response = requests.get(
        "https://data.alpaca.markets/v2/stocks/bars",
        headers=_credentials(),
        params={
            "symbols": SYMBOL, "timeframe": "5Min",
            "start": start_et.astimezone(timezone.utc).isoformat().replace("+00:00", "Z"),
            "end": end_et.astimezone(timezone.utc).isoformat().replace("+00:00", "Z"),
            "adjustment": "raw", "feed": "iex", "limit": 10000, "sort": "asc",
        },
        timeout=25,
    )
    response.raise_for_status()
    payload = response.json()
    return [row for row in (payload.get("bars") or {}).get(SYMBOL, []) if isinstance(row, dict)]


def resolve_candidate(candidate: Mapping[str, Any], rows: Iterable[Mapping[str, Any]], *, now_et: datetime) -> dict[str, Any] | None:
    """Resolve a candidate using only bars that began after it was available."""
    reaction = candidate.get("reaction") if isinstance(candidate.get("reaction"), Mapping) else {}
    available_at = _candidate_time(candidate)
    direction = str(reaction.get("direction") or "")
    entry = _finite(reaction.get("level"))
    if available_at is None or entry is None or direction not in {"bullish", "bearish"}:
        return None
    horizon_end = available_at + timedelta(minutes=HORIZON_MINUTES)
    if now_et < horizon_end:
        return None
    bars = [
        row for row in _completed_rows(rows)
        if available_at <= row["timestamp"] < horizon_end
    ]
    if len(bars) < HORIZON_MINUTES // 5:
        return None
    if direction == "bullish":
        mfe = max(row["h"] - entry for row in bars)
        mae = min(row["l"] - entry for row in bars)
        terminal = bars[-1]["c"] - entry
    else:
        mfe = max(entry - row["l"] for row in bars)
        mae = min(entry - row["h"] for row in bars)
        terminal = entry - bars[-1]["c"]
    gap = candidate.get("gap_context") if isinstance(candidate.get("gap_context"), Mapping) else {}
    breadth = candidate.get("breadth_context") if isinstance(candidate.get("breadth_context"), Mapping) else {}
    intermarket = candidate.get("intermarket_context") if isinstance(candidate.get("intermarket_context"), Mapping) else {}
    return {
        "schema_version": 1,
        "candidate_id": candidate.get("candidate_id"),
        "provider": "spy_level_reaction_outcome_resolver",
        "symbol": SYMBOL,
        "observed_at": reaction.get("observed_at"),
        "decision_available_at": available_at.isoformat(),
        "resolved_at": horizon_end.isoformat(),
        "direction": direction,
        "level_name": reaction.get("level_name"),
        "entry_level": round(entry, 4),
        "horizon_minutes": HORIZON_MINUTES,
        "mfe_points": round(mfe, 4),
        "mae_points": round(mae, 4),
        "terminal_outcome_points": round(terminal, 4),
        "won": terminal > 0,
        "gap_fill_bucket": str(gap.get("fill_bucket") or "unavailable"),
        "breadth_regime": str(breadth.get("regime") or "unavailable"),
        "intermarket_regime": str(intermarket.get("qqq_spy_regime") or "unavailable"),
        "sector_leader": ((intermarket.get("sector_leaders") or [{}])[0].get("etf") if isinstance((intermarket.get("sector_leaders") or [{}])[0], Mapping) else None),
        "cost_adjusted": False,
        "cost_model": "unavailable_underlying_proxy_only",
        "execution_enabled": False,
        "can_submit_orders": False,
        "limitations": "Underlying 60-minute proxy only; not an option fill, premium, fee, slippage, or live-trading result.",
    }


def _slice(rows: Iterable[Mapping[str, Any]], field: str) -> list[dict[str, Any]]:
    groups: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for row in rows:
        groups[str(row.get(field) or "unavailable")].append(row)
    result: list[dict[str, Any]] = []
    for key, items in sorted(groups.items()):
        outcomes = [float(item.get("terminal_outcome_points") or 0.0) for item in items]
        mfes = [float(item.get("mfe_points") or 0.0) for item in items]
        maes = [float(item.get("mae_points") or 0.0) for item in items]
        result.append({
            "bucket": key,
            "sample_count": len(items),
            "win_rate": round(sum(bool(item.get("won")) for item in items) / len(items), 4),
            "mean_terminal_outcome_points": round(sum(outcomes) / len(outcomes), 4),
            "median_terminal_outcome_points": round(float(median(outcomes)), 4),
            "mean_mfe_points": round(sum(mfes) / len(mfes), 4),
            "mean_mae_points": round(sum(maes) / len(maes), 4),
            "meets_minimum_sample": len(items) >= MINIMUM_BUCKET_SAMPLE,
        })
    return result


def build_report(outcomes: Iterable[Mapping[str, Any]], *, generated_at: datetime | None = None) -> dict[str, Any]:
    rows = [dict(row) for row in outcomes if isinstance(row, Mapping)]
    now = (generated_at or datetime.now(timezone.utc)).astimezone(timezone.utc)
    gap_slices = _slice(rows, "gap_fill_bucket")
    return {
        "schema_version": 1,
        "provider": "spy_level_reaction_outcome_resolver",
        "generated_at": now.isoformat().replace("+00:00", "Z"),
        "mode": "shadow_research_only",
        "horizon_minutes": HORIZON_MINUTES,
        "minimum_bucket_sample": MINIMUM_BUCKET_SAMPLE,
        "outcomes": rows,
        "summary": {
            "resolved_count": len(rows),
            "gap_time_to_fill_slices": gap_slices,
            "breadth_regime_slices": _slice(rows, "breadth_regime"),
            "intermarket_regime_slices": _slice(rows, "intermarket_regime"),
            "promotion_eligible": False,
            "promotion_blockers": [
                "frozen_forward_sample_below_minimum" if len(rows) < MINIMUM_BUCKET_SAMPLE else "cost_adjusted_execution_model_required",
                "cost_adjusted_option_outcomes_not_available",
                "manual_review_and_separate_authorization_required",
            ],
        },
        "warnings": [
            "Gap-fill buckets describe realized paths only; they do not predict a fill.",
            "Breadth and QQQ/SPY-sector context are challengers, not gates or sizing inputs.",
            "No option premium, fee, spread, slippage, or executable-fill result is inferred from the underlying proxy.",
        ],
        "execution_enabled": False,
        "can_submit_orders": False,
    }


def append_new_outcomes(rows: Iterable[Mapping[str, Any]], *, ledger_path: Path = OUTCOME_LEDGER_PATH) -> int:
    existing = {str(row.get("candidate_id")) for row in _read_jsonl(ledger_path) if row.get("candidate_id")}
    fresh = [dict(row) for row in rows if row.get("candidate_id") and str(row["candidate_id"]) not in existing]
    if not fresh:
        return 0
    ledger_path.parent.mkdir(parents=True, exist_ok=True)
    with ledger_path.open("a", encoding="utf-8") as handle:
        for row in fresh:
            handle.write(json.dumps(row, separators=(",", ":"), sort_keys=True) + "\n")
        handle.flush()
        os.fsync(handle.fileno())
    return len(fresh)


def write_report(report: Mapping[str, Any], *, report_path: Path = REPORT_PATH) -> None:
    report_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = report_path.with_suffix(report_path.suffix + ".partial")
    temporary.write_text(json.dumps(dict(report), indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(report_path)


def run(now_et: datetime | None = None, *, candidate_path: Path = REACTION_LEDGER_PATH, outcome_path: Path = OUTCOME_LEDGER_PATH) -> dict[str, Any]:
    now_et = (now_et or datetime.now(ET)).astimezone(ET)
    existing = _read_jsonl(outcome_path)
    pending = pending_candidates(_read_jsonl(candidate_path), {str(row.get("candidate_id")) for row in existing}, now_et=now_et)
    resolved: list[dict[str, Any]] = []
    if pending:
        earliest = min((_candidate_time(item) for item in pending if _candidate_time(item) is not None), default=None)
        if earliest is not None:
            bars = fetch_spy_bars(earliest, now_et)
            resolved = [outcome for item in pending if (outcome := resolve_candidate(item, bars, now_et=now_et)) is not None]
            append_new_outcomes(resolved, ledger_path=outcome_path)
            existing.extend(resolved)
    report = build_report(existing, generated_at=now_et)
    report["newly_resolved_count"] = len(resolved)
    report["pending_candidate_count"] = len(pending) - len(resolved)
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidate-path", type=Path, default=REACTION_LEDGER_PATH)
    parser.add_argument("--outcome-path", type=Path, default=OUTCOME_LEDGER_PATH)
    parser.add_argument("--report-path", type=Path, default=REPORT_PATH)
    parser.add_argument("--print", action="store_true", dest="print_report")
    args = parser.parse_args()
    try:
        report = run(candidate_path=args.candidate_path, outcome_path=args.outcome_path)
        report["operational_health"] = "ok"
    except Exception as exc:
        report = build_report([])
        report.update({"operational_health": "degraded", "error": f"{type(exc).__name__}: {str(exc)[:200]}"})
    write_report(report, report_path=args.report_path)
    if args.print_report:
        print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report.get("operational_health") == "ok" else 1


if __name__ == "__main__":
    raise SystemExit(main())

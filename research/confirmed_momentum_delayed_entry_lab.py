#!/usr/bin/env python3
"""Executable delayed-entry replay for the frozen first-mark hypothesis."""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import random
import statistics
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_INPUT = ROOT / "data" / "flip_shadow_candidates_log.jsonl"
DEFAULT_OUTPUT = ROOT / "data" / "confirmed_momentum_delayed_entry_results.json"
SPEC_PATH = ROOT / "research" / "CONFIRMED_MOMENTUM_DELAYED_ENTRY_SPEC_2026-08-17.md"
FORWARD_START = "2026-08-18"
BASELINE_COST_PCT = 1.5
STRESS_COST_PCT = 3.0
BOOTSTRAP_SEED = 20260817
BOOTSTRAP_SAMPLES = 5000


@dataclass(frozen=True)
class Mark:
    timestamp: str
    event_type: str
    bid: float
    ask: float | None
    signal_return_pct: float
    reason: str
    elapsed_minutes: float | None


@dataclass(frozen=True)
class Lifecycle:
    lifecycle_id: str
    date: str
    symbol: str
    marks: tuple[Mark, ...]


@dataclass(frozen=True)
class Outcome:
    lifecycle_id: str
    date: str
    symbol: str
    entry_time: str
    exit_time: str
    entry_ask: float
    exit_bid: float
    raw_return_pct: float
    exit_reason: str


def _num(value: Any) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if math.isfinite(parsed) else None


def _elapsed(start: str, end: str) -> float | None:
    try:
        start_dt = datetime.fromisoformat(start.replace("Z", "+00:00"))
        end_dt = datetime.fromisoformat(end.replace("Z", "+00:00"))
    except (AttributeError, TypeError, ValueError):
        return None
    return (end_dt - start_dt).total_seconds() / 60.0


def load_lifecycles(path: Path) -> list[Lifecycle]:
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    if not path.exists():
        return []
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        lifecycle_id = row.get("lifecycle_id")
        if isinstance(lifecycle_id, str) and lifecycle_id:
            groups[lifecycle_id].append(row)

    lifecycles: list[Lifecycle] = []
    for lifecycle_id, rows in groups.items():
        rows.sort(key=lambda row: str(row.get("scanned_at") or ""))
        entry = next((row for row in rows if row.get("event_type") == "shadow_entry"), None)
        if entry is None or not any(row.get("event_type") == "shadow_exit" for row in rows):
            continue
        entry_time = str(entry.get("scanned_at") or "")
        signal_price = _num(entry.get("entry_price_est"))
        if signal_price is None or signal_price <= 0:
            continue
        marks: list[Mark] = []
        for row in rows:
            if row.get("event_type") not in {"shadow_mark", "shadow_exit"}:
                continue
            bid = _num(row.get("selection_bid"))
            ask = _num(row.get("selection_ask"))
            midpoint = _num(row.get("mark_price"))
            signal_return = _num(row.get("return_pct_at_mark"))
            if signal_return is None and midpoint is not None:
                signal_return = (midpoint - signal_price) / signal_price * 100.0
            if bid is None or bid <= 0 or signal_return is None:
                continue
            timestamp = str(row.get("scanned_at") or "")
            marks.append(Mark(
                timestamp=timestamp,
                event_type=str(row.get("event_type")),
                bid=bid,
                ask=ask if ask is not None and ask > 0 else None,
                signal_return_pct=signal_return,
                reason=str(row.get("mark_reason") or ""),
                elapsed_minutes=_elapsed(entry_time, timestamp),
            ))
        if marks and any(mark.event_type == "shadow_exit" for mark in marks):
            lifecycles.append(Lifecycle(
                lifecycle_id=lifecycle_id,
                date=str(entry.get("date") or "")[:10],
                symbol=str(entry.get("symbol") or ""),
                marks=tuple(marks),
            ))
    return lifecycles


def _lock_floor(best_return: float) -> float:
    floor = max(15.0, best_return - 10.0)
    if best_return >= 40.0:
        return max(floor, 30.0)
    if best_return >= 30.0:
        return max(floor, 20.0)
    return floor


def replay(lifecycle: Lifecycle) -> tuple[Outcome | None, str]:
    first = next((mark for mark in lifecycle.marks if mark.event_type == "shadow_mark"), None)
    if first is None:
        return None, "missing_first_mark"
    if first.elapsed_minutes is None or not 0.0 <= first.elapsed_minutes < 10.0:
        return None, "first_mark_outside_window"
    if first.signal_return_pct <= 0.0:
        return None, "momentum_not_confirmed"
    if first.ask is None:
        return None, "missing_confirmation_ask"

    start = lifecycle.marks.index(first)
    later = lifecycle.marks[start + 1 :]
    if not later:
        return None, "missing_post_entry_bid"
    best = -math.inf
    selected: Mark | None = None
    reason = ""
    for mark in later:
        current = (mark.bid - first.ask) / first.ask * 100.0
        best = max(best, current)
        if current <= -30.0:
            selected, reason = mark, "stop_30"
            break
        if current >= 75.0:
            selected, reason = mark, "target_75"
            break
        if best >= 25.0 and 0.0 < current <= _lock_floor(best):
            selected, reason = mark, "profit_protect"
            break
        if mark.event_type == "shadow_exit":
            selected, reason = mark, mark.reason or "logged_exit"
            break
    if selected is None:
        return None, "missing_resolved_exit"
    raw_return = (selected.bid - first.ask) / first.ask * 100.0
    return Outcome(
        lifecycle_id=lifecycle.lifecycle_id,
        date=lifecycle.date,
        symbol=lifecycle.symbol,
        entry_time=first.timestamp,
        exit_time=selected.timestamp,
        entry_ask=first.ask,
        exit_bid=selected.bid,
        raw_return_pct=round(raw_return, 6),
        exit_reason=reason,
    ), "eligible"


def _bootstrap_date_lower(outcomes: list[Outcome], cost_pct: float) -> float | None:
    grouped: dict[str, list[float]] = defaultdict(list)
    for outcome in outcomes:
        grouped[outcome.date].append(outcome.raw_return_pct - cost_pct)
    days = [statistics.fmean(values) for _, values in sorted(grouped.items())]
    if len(days) < 2:
        return None
    rng = random.Random(BOOTSTRAP_SEED)
    means = [statistics.fmean(rng.choices(days, k=len(days))) for _ in range(BOOTSTRAP_SAMPLES)]
    means.sort()
    return round(means[int(0.025 * (len(means) - 1))], 4)


def metrics(outcomes: list[Outcome], cost_pct: float) -> dict[str, Any]:
    values = [outcome.raw_return_pct - cost_pct for outcome in outcomes]
    wins = [value for value in values if value > 0]
    losses = [value for value in values if value <= 0]
    gross_loss = abs(sum(losses))
    remove_count = math.ceil(len(values) * 0.05) if values else 0
    trimmed = sorted(values, reverse=True)[remove_count:]
    equity = peak = drawdown = 0.0
    for value in values:
        equity += value
        peak = max(peak, equity)
        drawdown = min(drawdown, equity - peak)
    dates = sorted({outcome.date for outcome in outcomes})
    holdout_dates = set(dates[-max(1, math.ceil(len(dates) * 0.20)):]) if dates else set()
    holdout = [outcome.raw_return_pct - cost_pct for outcome in outcomes if outcome.date in holdout_dates]
    return {
        "trades": len(values),
        "independent_dates": len(dates),
        "expectancy_pct": round(statistics.fmean(values), 4) if values else 0.0,
        "win_rate": round(len(wins) / len(values), 4) if values else 0.0,
        "profit_factor": round(sum(wins) / gross_loss, 4) if gross_loss else (999.0 if wins else 0.0),
        "max_additive_drawdown_pct": round(drawdown, 4),
        "top5_removed_expectancy_pct": round(statistics.fmean(trimmed), 4) if trimmed else 0.0,
        "last20pct_dates_expectancy_pct": round(statistics.fmean(holdout), 4) if holdout else 0.0,
        "date_cluster_bootstrap_95_lower_mean_pct": _bootstrap_date_lower(outcomes, cost_pct),
    }


def _partition_report(outcomes: list[Outcome]) -> dict[str, Any]:
    baseline = metrics(outcomes, BASELINE_COST_PCT)
    stress = metrics(outcomes, STRESS_COST_PCT)
    checks = {
        "minimum_100_trades": baseline["trades"] >= 100,
        "minimum_30_dates": baseline["independent_dates"] >= 30,
        "profit_factor_at_least_1_20": baseline["profit_factor"] >= 1.20,
        "baseline_expectancy_positive": baseline["expectancy_pct"] > 0,
        "stress_expectancy_positive": stress["expectancy_pct"] > 0,
        "top5_removed_expectancy_positive": baseline["top5_removed_expectancy_pct"] > 0,
        "last20pct_dates_expectancy_positive": baseline["last20pct_dates_expectancy_pct"] > 0,
        "date_cluster_bootstrap_lower_positive": (
            baseline["date_cluster_bootstrap_95_lower_mean_pct"] is not None
            and baseline["date_cluster_bootstrap_95_lower_mean_pct"] > 0
        ),
    }
    return {"baseline": baseline, "stress": stress, "checks": checks, "passed": all(checks.values())}


def build_report(path: Path = DEFAULT_INPUT) -> dict[str, Any]:
    lifecycles = load_lifecycles(path)
    outcomes: list[Outcome] = []
    diagnostics = Counter()
    for lifecycle in lifecycles:
        outcome, status = replay(lifecycle)
        diagnostics[status] += 1
        if outcome is not None:
            outcomes.append(outcome)
    consumed = [outcome for outcome in outcomes if outcome.date < FORWARD_START]
    forward = [outcome for outcome in outcomes if outcome.date >= FORWARD_START]
    spec_hash = hashlib.sha256(SPEC_PATH.read_bytes()).hexdigest()
    consumed_report = _partition_report(consumed)
    forward_report = _partition_report(forward)
    return {
        "schema_version": 1,
        "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "provider": "confirmed_momentum_delayed_entry_lab",
        "specification": str(SPEC_PATH),
        "specification_sha256": spec_hash,
        "input": str(path),
        "input_sha256": hashlib.sha256(path.read_bytes()).hexdigest() if path.exists() else None,
        "forward_start": FORWARD_START,
        "diagnostics": dict(sorted(diagnostics.items())),
        "exit_reasons": dict(Counter(outcome.exit_reason for outcome in outcomes)),
        "consumed_history": consumed_report,
        "forward_evidence": forward_report,
        "verdict": (
            "human_paper_review_due" if forward_report["passed"]
            else "forward_collection_active" if consumed_report["passed"]
            else "historical_candidate_rejected"
        ),
        "outcomes": [asdict(outcome) for outcome in outcomes],
        "automatic_parameter_selection": False,
        "paper_execution_enabled": False,
        "execution_enabled": False,
        "can_submit_orders": False,
        "promotion_authority": "none_human_review_request_only",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    report = build_report(args.input)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({key: report[key] for key in (
        "diagnostics", "exit_reasons", "consumed_history", "forward_evidence", "verdict",
        "execution_enabled", "can_submit_orders",
    )}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

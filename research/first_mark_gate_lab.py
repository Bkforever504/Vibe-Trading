#!/usr/bin/env python3
"""Replay the frozen first-mark momentum exit policies on shadow lifecycles.

The policy family was selected after `flip_filter_lab` exposed a first-mark
split, so this corpus is consumed-history evidence. The lab is read-only and
has no paper or live promotion authority.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from research import flip_filter_lab

DEFAULT_CANDIDATES_PATH = ROOT / "data" / "flip_shadow_candidates_log.jsonl"
DEFAULT_OUTPUT_PATH = ROOT / "data" / "first_mark_gate_lab_results.json"
DEFAULT_FEE_PCT = 1.5
HOLDOUT_FRACTION = 0.20
MIN_SAMPLES_REVIEW = 30
MIN_DATES_REVIEW = 20


@dataclass(frozen=True)
class Observation:
    timestamp: str
    event_type: str
    signal_return_pct: float
    executable_bid: float
    reason: str
    elapsed_minutes: float | None
    bid_basis: str


@dataclass(frozen=True)
class Lifecycle:
    lifecycle_id: str
    date: str
    symbol: str
    entry_ask: float
    entry_basis: str
    observations: tuple[Observation, ...]


@dataclass(frozen=True)
class Outcome:
    lifecycle_id: str
    date: str
    return_pct: float
    reason: str
    gate_fired: bool


def _num(value: Any) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if math.isfinite(parsed) else None


def _elapsed_minutes(start: str, end: str) -> float | None:
    try:
        start_dt = datetime.fromisoformat(start.replace("Z", "+00:00"))
        end_dt = datetime.fromisoformat(end.replace("Z", "+00:00"))
    except (AttributeError, TypeError, ValueError):
        return None
    return (end_dt - start_dt).total_seconds() / 60.0


def load_lifecycles(path: Path) -> list[Lifecycle]:
    if not path.exists():
        return []
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
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
        entries = [row for row in rows if row.get("event_type") == "shadow_entry"]
        exits = [row for row in rows if row.get("event_type") == "shadow_exit"]
        if not entries or not exits:
            continue
        entry = entries[0]
        entry_signal = _num(entry.get("entry_price_est"))
        entry_ask = _num(entry.get("selection_ask"))
        entry_basis = "recorded_ask"
        if entry_ask is None or entry_ask <= 0:
            entry_ask = entry_signal
            entry_basis = "entry_price_est_fallback"
        if entry_ask is None or entry_ask <= 0 or entry_signal is None or entry_signal <= 0:
            continue

        entry_time = str(entry.get("scanned_at") or "")
        observations: list[Observation] = []
        for row in rows:
            if row.get("event_type") not in {"shadow_mark", "shadow_exit"}:
                continue
            mark = _num(row.get("mark_price"))
            signal_return = _num(row.get("return_pct_at_mark"))
            if signal_return is None and mark is not None:
                signal_return = (mark - entry_signal) / entry_signal * 100.0
            bid = _num(row.get("selection_bid"))
            bid_basis = "recorded_bid"
            if bid is None or bid <= 0:
                bid = mark
                bid_basis = "mark_price_fallback"
            if signal_return is None or bid is None or bid <= 0:
                continue
            timestamp = str(row.get("scanned_at") or "")
            observations.append(Observation(
                timestamp=timestamp,
                event_type=str(row.get("event_type") or ""),
                signal_return_pct=round(signal_return, 6),
                executable_bid=bid,
                reason=str(row.get("mark_reason") or ""),
                elapsed_minutes=_elapsed_minutes(entry_time, timestamp),
                bid_basis=bid_basis,
            ))
        if not observations or not any(obs.event_type == "shadow_exit" for obs in observations):
            continue
        lifecycles.append(Lifecycle(
            lifecycle_id=lifecycle_id,
            date=str(entry.get("date") or "")[:10],
            symbol=str(entry.get("symbol") or ""),
            entry_ask=entry_ask,
            entry_basis=entry_basis,
            observations=tuple(observations),
        ))
    return lifecycles


GatePredicate = Callable[[float], bool]


POLICIES: dict[str, GatePredicate | None] = {
    "baseline_no_gate": None,
    "gate_mark1_any_negative": lambda value: value <= 0.0,
    "gate_mark1_below_minus5": lambda value: value < -5.0,
    "gate_mark1_below_minus10": lambda value: value < -10.0,
}


def _replay(lifecycle: Lifecycle, policy: str, predicate: GatePredicate | None) -> Outcome:
    first = lifecycle.observations[0]
    logged_exit = next(
        obs for obs in reversed(lifecycle.observations)
        if obs.event_type == "shadow_exit"
    )
    eligible = first.elapsed_minutes is not None and 0.0 <= first.elapsed_minutes < 10.0
    gate_fired = predicate(first.signal_return_pct) if predicate is not None and eligible else False
    selected = first if gate_fired else logged_exit
    return Outcome(
        lifecycle_id=lifecycle.lifecycle_id,
        date=lifecycle.date,
        return_pct=round((selected.executable_bid - lifecycle.entry_ask) / lifecycle.entry_ask * 100.0, 6),
        reason=(f"{policy}_first_mark_exit" if gate_fired else selected.reason or "logged_exit"),
        gate_fired=gate_fired,
    )


def _top_winners_removed(values: list[float], fraction: float = 0.05) -> list[float]:
    if not values:
        return []
    remove_count = max(1, int(len(values) * fraction))
    return sorted(values)[:-remove_count] if remove_count < len(values) else []


def _metrics(outcomes: list[Outcome], fee_pct: float) -> dict[str, Any]:
    adjusted = [outcome.return_pct - fee_pct for outcome in outcomes]
    if not adjusted:
        return {"n": 0}
    wins = [value for value in adjusted if value > 0]
    losses = [value for value in adjusted if value <= 0]
    gross_profit = sum(wins)
    gross_loss = -sum(losses)
    equity = peak = 0.0
    max_drawdown = 0.0
    for value in adjusted:
        equity += value
        peak = max(peak, equity)
        max_drawdown = min(max_drawdown, equity - peak)
    return {
        "n": len(adjusted),
        "unique_dates": len({outcome.date for outcome in outcomes if outcome.date}),
        "expectancy_pct": round(sum(adjusted) / len(adjusted), 3),
        "win_rate": round(len(wins) / len(adjusted), 3),
        "profit_factor": round(gross_profit / gross_loss, 3) if gross_loss > 0 else None,
        "average_win_pct": round(sum(wins) / len(wins), 3) if wins else None,
        "average_loss_pct": round(sum(losses) / len(losses), 3) if losses else None,
        "max_additive_drawdown_pct": round(max_drawdown, 3),
        "gate_fired_count": sum(outcome.gate_fired for outcome in outcomes),
        "exit_reasons": dict(Counter(outcome.reason for outcome in outcomes)),
    }


def _evaluate(policy: str, predicate: GatePredicate | None, lives: list[Lifecycle], fee_pct: float) -> dict[str, Any]:
    outcomes = [_replay(lifecycle, policy, predicate) for lifecycle in lives]
    raw_returns = [outcome.return_pct for outcome in outcomes]
    top5_outcomes = [
        Outcome(str(index), "", value, "top5_removed", False)
        for index, value in enumerate(_top_winners_removed(raw_returns))
    ]
    return {
        "policy": policy,
        "post_fee": _metrics(outcomes, fee_pct),
        "doubled_cost": _metrics(outcomes, fee_pct * 2.0),
        "top5_winners_removed_post_fee": _metrics(top5_outcomes, fee_pct),
    }


def _review_gate(policy_row: dict[str, Any]) -> dict[str, Any]:
    post_fee = policy_row["post_fee"]
    doubled = policy_row["doubled_cost"]
    top5 = policy_row["top5_winners_removed_post_fee"]
    failed: list[str] = []
    if int(post_fee.get("n") or 0) < MIN_SAMPLES_REVIEW:
        failed.append(f"insufficient_samples_{post_fee.get('n', 0)}/{MIN_SAMPLES_REVIEW}")
    if int(post_fee.get("unique_dates") or 0) < MIN_DATES_REVIEW:
        failed.append(f"insufficient_dates_{post_fee.get('unique_dates', 0)}/{MIN_DATES_REVIEW}")
    if float(post_fee.get("expectancy_pct") or 0.0) <= 0.0:
        failed.append("executable_post_fee_expectancy_not_positive")
    if float(doubled.get("expectancy_pct") or 0.0) <= 0.0:
        failed.append("executable_doubled_cost_expectancy_not_positive")
    if float(top5.get("expectancy_pct") or 0.0) <= 0.0:
        failed.append("executable_top5_removed_expectancy_not_positive")
    return {
        "passed": not failed,
        "failed_checks": failed,
        "minimum_samples": MIN_SAMPLES_REVIEW,
        "minimum_dates": MIN_DATES_REVIEW,
    }


def _chronological_split(lives: list[Lifecycle]) -> tuple[list[Lifecycle], list[Lifecycle]]:
    dates = sorted({life.date for life in lives if life.date})
    if len(dates) < 5:
        return lives, []
    holdout_count = max(1, math.ceil(len(dates) * HOLDOUT_FRACTION))
    holdout_dates = set(dates[-holdout_count:])
    return (
        [life for life in lives if life.date not in holdout_dates],
        [life for life in lives if life.date in holdout_dates],
    )


def _timing_summary(lives: list[Lifecycle]) -> dict[str, Any]:
    values = sorted(
        life.observations[0].elapsed_minutes
        for life in lives
        if life.observations and life.observations[0].elapsed_minutes is not None
    )
    if not values:
        return {"n": 0}
    return {
        "n": len(values),
        "minimum_minutes": round(values[0], 3),
        "median_minutes": round(values[len(values) // 2], 3),
        "mean_minutes": round(sum(values) / len(values), 3),
        "maximum_minutes": round(values[-1], 3),
        "under_2_minutes": sum(value < 2.0 for value in values),
        "between_4_and_6_minutes": sum(4.0 <= value <= 6.0 for value in values),
        "over_10_minutes": sum(value > 10.0 for value in values),
    }


def _green_filter_review(
    candidates_path: Path,
    fee_pct: float,
    executable_gate_review: dict[str, Any],
) -> dict[str, Any]:
    filter_report = flip_filter_lab.build_report(candidates_path=candidates_path, fee_pct=fee_pct)
    row = next(
        (item for item in filter_report["filters_ranked"] if item["filter"] == "first_mark_green"),
        None,
    )
    if row is None:
        return {
            "status": "unavailable",
            "request_paper_approval": False,
            "paper_execution_enabled": False,
        }
    midpoint_filter_passed = bool(row["review_gate"]["passed"])
    executable_gate_passed = bool(executable_gate_review["passed"])
    request_review = midpoint_filter_passed and executable_gate_passed
    if request_review:
        status = "human_review_due"
    elif row["unique_dates"] < flip_filter_lab.MIN_DATES_REVIEW:
        status = "collect_more_shadow_dates"
    elif not executable_gate_passed:
        status = "blocked_executable_replay_not_profitable"
    else:
        status = "blocked_midpoint_filter_review_gate"
    return {
        "status": status,
        "request_paper_approval": request_review,
        "paper_execution_enabled": False,
        "sample_size": row["n"],
        "unique_dates": row["unique_dates"],
        "minimum_dates": flip_filter_lab.MIN_DATES_REVIEW,
        "stats": row["stats"],
        "review_gate": row["review_gate"],
        "executable_gate_review": executable_gate_review,
        "approval_rule": "midpoint_filter_and_executable_gate_must_both_pass",
    }


def build_report(
    candidates_path: Path = DEFAULT_CANDIDATES_PATH,
    fee_pct: float = DEFAULT_FEE_PCT,
) -> dict[str, Any]:
    lives = load_lifecycles(candidates_path)
    train, holdout = _chronological_split(lives)
    full_rows = [_evaluate(name, predicate, lives, fee_pct) for name, predicate in POLICIES.items()]
    for row in full_rows:
        row["review_gate"] = _review_gate(row)
    train_rows = [_evaluate(name, predicate, train, fee_pct) for name, predicate in POLICIES.items()]
    holdout_rows = [_evaluate(name, predicate, holdout, fee_pct) for name, predicate in POLICIES.items()]
    return {
        "provider": "first_mark_gate_lab",
        "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "mode": "read_only_consumed_history_replay",
        "evidence_label": "exploratory_post_discovery_consumed_corpus",
        "execution_enabled": False,
        "can_submit_orders": False,
        "paper_execution_enabled": False,
        "automatic_parameter_selection": False,
        "promotion_authority": "none_human_review_request_only",
        "replay_spec": str(ROOT / "research" / "FIRST_MARK_GATE_REPLAY_SPEC_2026-08-12.md"),
        "candidates_path": str(candidates_path),
        "fee_pct": fee_pct,
        "total_lifecycles": len(lives),
        "unique_dates": len({life.date for life in lives if life.date}),
        "train_lifecycles": len(train),
        "holdout_lifecycles": len(holdout),
        "first_observation_timing": _timing_summary(lives),
        "price_coverage": {
            "recorded_entry_ask": sum(life.entry_basis == "recorded_ask" for life in lives),
            "entry_price_fallback": sum(life.entry_basis != "recorded_ask" for life in lives),
            "first_recorded_bid": sum(life.observations[0].bid_basis == "recorded_bid" for life in lives),
            "first_mark_price_fallback": sum(life.observations[0].bid_basis != "recorded_bid" for life in lives),
        },
        "policies_full_corpus": full_rows,
        "policies_chronological_train": train_rows,
        "policies_chronological_last_20pct_dates": holdout_rows,
        "first_mark_green_review": _green_filter_review(
            candidates_path,
            fee_pct,
            next(
                row["review_gate"]
                for row in full_rows
                if row["policy"] == "gate_mark1_any_negative"
            ),
        ),
        "notes": (
            "The discovery and replay use the same consumed corpus. Passing a review gate "
            "requests human paper review only and does not establish out-of-sample edge."
        ),
    }


def write_report(report: dict[str, Any], output_path: Path = DEFAULT_OUTPUT_PATH) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = output_path.with_suffix(output_path.suffix + ".tmp")
    temporary.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(temporary, output_path)


def _summary(report: dict[str, Any]) -> str:
    lines = [
        f"lifecycles={report['total_lifecycles']} dates={report['unique_dates']} evidence=consumed",
        "",
        f"{'policy':<30} {'n':>5} {'exp%':>8} {'2x%':>8} {'top5-%':>9} {'wr':>7} {'pf':>7} {'fired':>7}",
        "-" * 90,
    ]
    for row in report["policies_full_corpus"]:
        post = row["post_fee"]
        doubled = row["doubled_cost"]
        top5 = row["top5_winners_removed_post_fee"]
        lines.append(
            f"{row['policy']:<30} {post.get('n', 0):>5} "
            f"{post.get('expectancy_pct', 0):>8.2f} {doubled.get('expectancy_pct', 0):>8.2f} "
            f"{top5.get('expectancy_pct', 0):>9.2f} {post.get('win_rate', 0):>7.1%} "
            f"{(post.get('profit_factor') or 0):>7.2f} {post.get('gate_fired_count', 0):>7}"
        )
    review = report["first_mark_green_review"]
    lines.extend([
        "",
        f"first_mark_green_review={review['status']} dates={review.get('unique_dates', 0)}/{review.get('minimum_dates', 20)}",
        "No execution or automatic promotion authority.",
    ])
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidates", type=Path, default=DEFAULT_CANDIDATES_PATH)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUTPUT_PATH)
    parser.add_argument("--fee-pct", type=float, default=DEFAULT_FEE_PCT)
    parser.add_argument("--print", action="store_true", dest="do_print")
    args = parser.parse_args()
    report = build_report(candidates_path=args.candidates, fee_pct=args.fee_pct)
    write_report(report, args.out)
    if args.do_print:
        print(_summary(report))
        print(f"\nreport: {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

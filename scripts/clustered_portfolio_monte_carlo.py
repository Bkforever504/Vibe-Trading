#!/usr/bin/env python3
"""Cluster-aware Monte Carlo for resolved shadow options outcomes."""
from __future__ import annotations

import argparse
import json
import math
import random
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from statistics import mean
from typing import Any, Iterable


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_TWIN_PATH = ROOT / "data" / "options_shadow_twin_log.jsonl"
DEFAULT_OUTPUT_PATH = ROOT / "data" / "clustered_portfolio_monte_carlo.json"


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8-sig") as handle:
        for line in handle:
            try:
                value = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(value, dict):
                rows.append(value)
    return rows


def _number(value: Any) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if math.isfinite(parsed) else None


def _date(value: Any) -> str | None:
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).date().isoformat()
    except (TypeError, ValueError):
        return None


def _max_drawdown(values: list[float]) -> float:
    equity = 0.0
    peak = 0.0
    maximum = 0.0
    for value in values:
        equity += value
        peak = max(peak, equity)
        maximum = max(maximum, peak - equity)
    return maximum


def _max_underwater_duration(values: list[float]) -> int:
    equity = 0.0
    peak = 0.0
    current = 0
    maximum = 0
    for value in values:
        equity += value
        if equity >= peak:
            peak = equity
            current = 0
        else:
            current += 1
            maximum = max(maximum, current)
    return maximum


def _percentile(values: list[float], quantile: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, int(math.ceil(quantile * len(ordered)) - 1)))
    return ordered[index]


def _sample_block_path(values: list[float], horizon: int, block: int, rng: random.Random) -> list[float]:
    path: list[float] = []
    while len(path) < horizon:
        start = rng.randrange(len(values))
        path.extend(values[(start + offset) % len(values)] for offset in range(block))
    return path[:horizon]


def _simulate(
    values: list[float],
    *,
    paths: int,
    horizon: int,
    block: int,
    seed: int,
    ruin_drawdown: float,
    historical_drawdown: float,
) -> dict[str, Any]:
    if not values:
        return {"paths": 0, "status": "no_observations"}
    rng = random.Random(seed)
    final_pnls: list[float] = []
    drawdowns: list[float] = []
    durations: list[int] = []
    ruin_count = 0
    exceed_15 = 0
    exceed_20 = 0
    for _ in range(paths):
        path = _sample_block_path(values, horizon, block, rng)
        final_pnls.append(sum(path))
        drawdown = _max_drawdown(path)
        drawdowns.append(drawdown)
        durations.append(_max_underwater_duration(path))
        ruin_count += drawdown >= ruin_drawdown
        exceed_15 += historical_drawdown > 0 and drawdown >= historical_drawdown * 1.5
        exceed_20 += historical_drawdown > 0 and drawdown >= historical_drawdown * 2.0
    return {
        "paths": paths,
        "horizon_days": horizon,
        "block_length_days": block,
        "average_final_pnl_dollars": round(mean(final_pnls), 2),
        "p05_final_pnl_dollars": round(float(_percentile(final_pnls, 0.05)), 2),
        "loss_probability": round(sum(value < 0 for value in final_pnls) / paths, 4),
        "p95_max_drawdown_dollars": round(float(_percentile(drawdowns, 0.95)), 2),
        "p99_max_drawdown_dollars": round(float(_percentile(drawdowns, 0.99)), 2),
        "p95_underwater_duration_days": int(_percentile([float(value) for value in durations], 0.95) or 0),
        "ruin_drawdown_dollars": round(ruin_drawdown, 2),
        "ruin_probability": round(ruin_count / paths, 4),
        "probability_drawdown_ge_1_5x_historical": round(exceed_15 / paths, 4),
        "probability_drawdown_ge_2x_historical": round(exceed_20 / paths, 4),
    }


def _correlation(left: list[float], right: list[float]) -> float | None:
    if len(left) < 5 or len(left) != len(right):
        return None
    left_mean = mean(left)
    right_mean = mean(right)
    numerator = sum((a - left_mean) * (b - right_mean) for a, b in zip(left, right))
    left_ss = sum((a - left_mean) ** 2 for a in left)
    right_ss = sum((b - right_mean) ** 2 for b in right)
    denominator = math.sqrt(left_ss * right_ss)
    return numerator / denominator if denominator else None


def build_report(
    rows: Iterable[dict[str, Any]],
    *,
    paths: int = 5000,
    horizon: int = 50,
    account_equity: float = 10000.0,
    ruin_fraction: float = 0.10,
    seed: int = 20260814,
) -> dict[str, Any]:
    candidates: dict[str, dict[str, Any]] = {}
    outcomes: dict[str, dict[str, Any]] = {}
    for row in rows:
        candidate_id = str(row.get("candidate_id") or "")
        if not candidate_id:
            continue
        if row.get("type") == "candidate":
            candidates[candidate_id] = row
        elif row.get("type") == "outcome":
            outcomes[candidate_id] = row

    by_day: dict[str, float] = defaultdict(float)
    by_strategy_day: dict[str, dict[str, float]] = defaultdict(lambda: defaultdict(float))
    resolved_count = 0
    for candidate_id, outcome in outcomes.items():
        pnl = _number(outcome.get("pnl_before_fees"))
        resolved_date = _date(outcome.get("resolved_at"))
        candidate = candidates.get(candidate_id, {})
        if pnl is None or resolved_date is None:
            continue
        strategy = str(candidate.get("strategy") or "unknown")
        by_day[resolved_date] += pnl
        by_strategy_day[strategy][resolved_date] += pnl
        resolved_count += 1

    ordered_dates = sorted(by_day)
    daily_pnls = [by_day[value] for value in ordered_dates]
    historical_drawdown = _max_drawdown(daily_pnls)
    block = max(2, int(math.sqrt(len(daily_pnls)))) if daily_pnls else 1
    ruin_drawdown = account_equity * ruin_fraction
    clustered = _simulate(
        daily_pnls,
        paths=paths,
        horizon=horizon,
        block=block,
        seed=seed,
        ruin_drawdown=ruin_drawdown,
        historical_drawdown=historical_drawdown,
    )
    iid = _simulate(
        daily_pnls,
        paths=paths,
        horizon=horizon,
        block=1,
        seed=seed + 1,
        ruin_drawdown=ruin_drawdown,
        historical_drawdown=historical_drawdown,
    )
    correlations: list[dict[str, Any]] = []
    strategies = sorted(by_strategy_day)
    for index, left_name in enumerate(strategies):
        for right_name in strategies[index + 1:]:
            overlap = sorted(set(by_strategy_day[left_name]) & set(by_strategy_day[right_name]))
            value = _correlation(
                [by_strategy_day[left_name][day] for day in overlap],
                [by_strategy_day[right_name][day] for day in overlap],
            )
            correlations.append({
                "left": left_name,
                "right": right_name,
                "overlap_days": len(overlap),
                "correlation": round(value, 4) if value is not None else None,
                "status": "measured" if value is not None else "insufficient_overlap",
            })
    sufficient = len(daily_pnls) >= 20 and resolved_count >= 30
    return {
        "schema_version": 1,
        "provider": "clustered_portfolio_monte_carlo",
        "mode": "read_only_resolution_day_cluster_bootstrap",
        "resolved_outcome_count": resolved_count,
        "active_resolution_day_count": len(daily_pnls),
        "historical": {
            "aggregate_pnl_dollars": round(sum(daily_pnls), 2),
            "average_active_day_pnl_dollars": round(mean(daily_pnls), 2) if daily_pnls else None,
            "max_drawdown_dollars": round(historical_drawdown, 2),
            "max_underwater_duration_active_days": _max_underwater_duration(daily_pnls),
        },
        "clustered_day_bootstrap": clustered,
        "iid_day_comparator": iid,
        "strategy_correlations": correlations,
        "evidence_status": "sufficient_for_risk_review" if sufficient else "insufficient_history",
        "limitations": [
            "Outcomes are grouped by resolution day; unrealized mark-to-market correlation is not represented.",
            "Bootstrap cannot simulate regimes absent from observed history.",
            "Risk estimates remain advisory and cannot promote sizing or execution.",
        ],
        "promotion_authority": "blocked",
        "execution_enabled": False,
        "can_submit_orders": False,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--twin", type=Path, default=DEFAULT_TWIN_PATH)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUTPUT_PATH)
    parser.add_argument("--paths", type=int, default=5000)
    parser.add_argument("--horizon", type=int, default=50)
    parser.add_argument("--account-equity", type=float, default=10000.0)
    parser.add_argument("--ruin-fraction", type=float, default=0.10)
    parser.add_argument("--seed", type=int, default=20260814)
    parser.add_argument("--print", action="store_true", dest="print_report")
    args = parser.parse_args()
    report = build_report(
        read_jsonl(args.twin),
        paths=args.paths,
        horizon=args.horizon,
        account_equity=args.account_equity,
        ruin_fraction=args.ruin_fraction,
        seed=args.seed,
    )
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    if args.print_report:
        print(json.dumps(report, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()

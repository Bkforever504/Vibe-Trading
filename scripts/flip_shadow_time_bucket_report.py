#!/usr/bin/env python3
"""Mine Flip shadow lifecycles for time-of-day edge.

Read-only: consumes `flip_shadow_candidates_log.jsonl` and reports which entry
time buckets show usable cost-adjusted expectancy. It never places orders or
changes thresholds.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts import flip_shadow_pnl_evaluator as evaluator


VIBE_HOME = Path.home() / ".vibe-trading"
SOURCE_PATH = ROOT / "data" / "flip_shadow_candidates_log.jsonl"
REPORT_PATH = VIBE_HOME / "reports" / "flip-shadow-time-buckets.json"
LOG_PATH = ROOT / "data" / "flip_shadow_time_bucket_log.jsonl"
MIN_BUCKET_RANKING_COMPLETED = 10
MIN_BUCKET_GATE_REVIEW_COMPLETED = 30
SELECTOR_HAIRCUT_PER_TRIAL_PCT = 0.35
MIN_STRUCTURE_COHORT_COMPLETED = 20
MIN_STRUCTURE_REVIEW_COMPLETED = 100
MIN_STRUCTURE_REVIEW_DATES = 20
MIN_STRUCTURE_HOLDOUT_COMPLETED = 30


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        if not raw.strip():
            continue
        try:
            row = json.loads(raw)
        except json.JSONDecodeError:
            continue
        if isinstance(row, dict):
            rows.append(row)
    return rows


def _group_shadow_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    groups: dict[tuple[str, ...], list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        if int(row.get("schema_version") or 0) < 2:
            continue
        if row.get("data_quality") != "current_session_lifecycle":
            continue
        if row.get("execution_mode") not in (None, "shadow_only"):
            continue
        if not row.get("symbol") or not row.get("option_symbol"):
            continue
        groups[evaluator._row_key(row)].append(row)
    trades = [evaluator.evaluate_group(group_rows) for group_rows in groups.values()]
    return [trade for trade in trades if trade.get("status") in {"winner", "loser"}]


def _num(value: Any) -> float:
    try:
        return float(value or 0.0)
    except (TypeError, ValueError):
        return 0.0


def _sharpe_sortino(returns: list[float]) -> tuple[Optional[float], Optional[float]]:
    n = len(returns)
    if n < 2:
        return None, None
    mu = sum(returns) / n
    variance = sum((r - mu) ** 2 for r in returns) / (n - 1)
    sigma = math.sqrt(variance) if variance > 0 else 0.0
    sharpe = round(mu / sigma, 3) if sigma > 0 else None
    downside_sq = [r ** 2 for r in returns if r < 0]
    sigma_d = math.sqrt(sum(downside_sq) / len(downside_sq)) if downside_sq else 0.0
    sortino = round(mu / sigma_d, 3) if sigma_d > 0 else None
    return sharpe, sortino


def _summarize(items: list[dict[str, Any]]) -> dict[str, Any]:
    wins = [item for item in items if _num(item.get("evidence_exit_return_pct")) > 0]
    losses = [item for item in items if _num(item.get("evidence_exit_return_pct")) <= 0]
    returns = [_num(item.get("evidence_exit_return_pct")) for item in items]
    win_returns = [value for value in returns if value > 0]
    loss_returns = [abs(value) for value in returns if value <= 0]
    avg_win = sum(win_returns) / len(win_returns) if win_returns else 0.0
    avg_loss = sum(loss_returns) / len(loss_returns) if loss_returns else 0.0
    win_rate = len(wins) / len(items) if items else 0.0
    expectancy = (win_rate * avg_win) - ((1.0 - win_rate) * avg_loss) if items else 0.0
    avg_capture = (
        sum(_num(item.get("evidence_capture_efficiency")) for item in items) / len(items)
        if items else 0.0
    )
    sharpe, sortino = _sharpe_sortino(returns)
    return {
        "completed_count": len(items),
        "winner_count": len(wins),
        "loser_count": len(losses),
        "win_rate": round(win_rate, 3),
        "expectancy_return_pct": round(expectancy, 2),
        "avg_win_return_pct": round(avg_win, 2),
        "avg_loss_return_pct": round(avg_loss, 2),
        "avg_capture_efficiency": round(avg_capture, 3),
        "sharpe_ratio": sharpe,
        "sortino_ratio": sortino,
        "total_cost_adjusted_pnl": round(sum(_num(item.get("cost_adjusted_exit_pnl")) for item in items), 2),
        "symbols": sorted({str(item.get("symbol")) for item in items if item.get("symbol")}),
        "sample_status": (
            "gate_review_sample_floor_met"
            if len(items) >= MIN_BUCKET_GATE_REVIEW_COMPLETED
            else "shadow_rank_only"
            if len(items) >= MIN_BUCKET_RANKING_COMPLETED
            else "too_few_samples"
        ),
        "live_gate_eligible": False,
    }


def _apply_selector_haircut(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Deflate bucket expectancy for the number of rankable choices inspected."""
    rankable_trials = sum(
        1 for row in rows
        if int(row.get("completed_count") or 0) >= MIN_BUCKET_RANKING_COMPLETED
    )
    penalty = round(rankable_trials * SELECTOR_HAIRCUT_PER_TRIAL_PCT, 2)
    adjusted: list[dict[str, Any]] = []
    for row in rows:
        expectancy = _num(row.get("expectancy_return_pct"))
        deflated = round(expectancy - penalty, 2)
        blockers = [
            "forward_confirmation_required",
            "human_review_required",
        ]
        if int(row.get("completed_count") or 0) < MIN_BUCKET_GATE_REVIEW_COMPLETED:
            blockers.append("gate_review_sample_floor_not_met")
        if deflated <= 0:
            blockers.append("selection_bias_adjusted_expectancy_not_positive")
        adjusted.append(
            {
                **row,
                "selector_trial_count": rankable_trials,
                "selection_bias_haircut_return_pct": penalty,
                "selection_bias_adjusted_expectancy_return_pct": deflated,
                "promotion_blockers": blockers,
            }
        )
    return adjusted


def _profit_factor(returns: list[float]) -> float | None:
    gains = sum(value for value in returns if value > 0)
    losses = abs(sum(value for value in returns if value < 0))
    if losses <= 0:
        return None if gains <= 0 else float("inf")
    return gains / losses


def _max_drawdown(returns: list[float]) -> float:
    equity = 0.0
    peak = 0.0
    worst = 0.0
    for value in returns:
        equity += value
        peak = max(peak, equity)
        worst = max(worst, peak - equity)
    return worst


def _return_metrics(items: list[dict[str, Any]]) -> dict[str, Any]:
    ordered = sorted(items, key=lambda row: (str(row.get("date") or ""), str(row.get("entry_seen_at") or "")))
    returns = [_num(row.get("evidence_exit_return_pct")) for row in ordered]
    wins = [value for value in returns if value > 0]
    quote_complete = [row for row in ordered if row.get("executable_quote_coverage")]
    stressed_returns: list[float] = []
    for row, value in zip(ordered, returns):
        ask = _num(row.get("executable_entry_ask"))
        spread_dollars = _num(row.get("best_spread_cents")) / 100.0
        if row.get("executable_quote_coverage") and ask > 0 and spread_dollars >= 0:
            # Baseline already crosses entry ask/exit bid. Subtract one more
            # observed spread to model approximately doubled execution costs.
            stressed_returns.append(value - spread_dollars / ask * 100.0)
    remove_count = max(1, math.ceil(len(returns) * 0.05)) if returns else 0
    without_top = sorted(returns, reverse=True)[remove_count:] if remove_count else []
    factor = _profit_factor(returns)
    return {
        "count": len(ordered),
        "win_rate": round(len(wins) / len(ordered), 4) if ordered else None,
        "expectancy_return_pct": round(sum(returns) / len(returns), 4) if returns else None,
        "profit_factor": round(factor, 4) if factor is not None and math.isfinite(factor) else factor,
        "max_drawdown_return_points": round(_max_drawdown(returns), 4),
        "executable_quote_coverage": round(len(quote_complete) / len(ordered), 4) if ordered else 0.0,
        "doubled_cost_expectancy_return_pct": (
            round(sum(stressed_returns) / len(stressed_returns), 4)
            if len(stressed_returns) == len(ordered) and stressed_returns else None
        ),
        "top_5pct_removed_expectancy_return_pct": (
            round(sum(without_top) / len(without_top), 4) if without_top else None
        ),
    }


def _walk_forward_cohort(
    cohort_type: str,
    cohort: str,
    items: list[dict[str, Any]],
) -> dict[str, Any]:
    dates = sorted({str(row.get("date") or "")[:10] for row in items if row.get("date")})
    split_index = min(len(dates) - 1, max(1, math.ceil(len(dates) * 0.70))) if len(dates) >= 2 else len(dates)
    training_dates = set(dates[:split_index])
    holdout_dates = set(dates[split_index:])
    training = [row for row in items if str(row.get("date") or "")[:10] in training_dates]
    holdout = [row for row in items if str(row.get("date") or "")[:10] in holdout_dates]
    full_metrics = _return_metrics(items)
    training_metrics = _return_metrics(training)
    holdout_metrics = _return_metrics(holdout)

    daily_returns: dict[str, float] = defaultdict(float)
    for row in items:
        daily_returns[str(row.get("date") or "")[:10]] += _num(row.get("evidence_exit_return_pct"))
    positive_daily_total = sum(value for value in daily_returns.values() if value > 0)
    max_day_fraction = (
        max((value for value in daily_returns.values() if value > 0), default=0.0) / positive_daily_total
        if positive_daily_total > 0 else None
    )
    blockers: list[str] = ["human_review_required"]
    if cohort_type != "setup_symbol":
        blockers.append("context_cohort_research_only")
    if len(items) < MIN_STRUCTURE_REVIEW_COMPLETED:
        blockers.append("fewer_than_100_completed")
    if len(dates) < MIN_STRUCTURE_REVIEW_DATES:
        blockers.append("fewer_than_20_distinct_dates")
    if len(holdout) < MIN_STRUCTURE_HOLDOUT_COMPLETED:
        blockers.append("fewer_than_30_chronological_holdout")
    if float(full_metrics.get("executable_quote_coverage") or 0.0) < 0.95:
        blockers.append("executable_quote_coverage_below_95pct")
    if float(full_metrics.get("expectancy_return_pct") or 0.0) <= 0:
        blockers.append("full_expectancy_not_positive")
    if float(holdout_metrics.get("expectancy_return_pct") or 0.0) <= 0:
        blockers.append("holdout_expectancy_not_positive")
    if float(full_metrics.get("doubled_cost_expectancy_return_pct") or 0.0) <= 0:
        blockers.append("doubled_cost_expectancy_not_positive")
    if float(full_metrics.get("top_5pct_removed_expectancy_return_pct") or 0.0) <= 0:
        blockers.append("top_5pct_removed_expectancy_not_positive")
    if max_day_fraction is None or max_day_fraction > 0.20:
        blockers.append("single_day_profit_concentration_above_20pct")
    statistical_blockers = [reason for reason in blockers if reason != "human_review_required"]
    return {
        "cohort_type": cohort_type,
        "cohort": cohort,
        "distinct_dates": len(dates),
        "training_date_count": len(training_dates),
        "holdout_date_count": len(holdout_dates),
        "full": full_metrics,
        "training": training_metrics,
        "chronological_holdout": holdout_metrics,
        "max_profitable_day_contribution": round(max_day_fraction, 4) if max_day_fraction is not None else None,
        "statistical_gate_ready": not statistical_blockers,
        "promotion_eligible": False,
        "promotion_blockers": blockers,
    }


def _market_structure_cohorts(trades: list[dict[str, Any]]) -> dict[str, Any]:
    grouped: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for trade in trades:
        symbol = str(trade.get("symbol") or "unknown")
        strategy = str(trade.get("strategy") or "unknown")
        bucket = str(trade.get("episode_bucket_et") or "unknown")
        features = trade.get("feature_snapshot") if isinstance(trade.get("feature_snapshot"), dict) else {}
        grouped[("setup_symbol", f"{symbol}|{strategy}")].append(trade)
        grouped[("setup_symbol_time", f"{symbol}|{strategy}|{bucket}")].append(trade)
        day_type = str(features.get("day_type") or "")
        if day_type:
            grouped[("setup_symbol_day_type", f"{symbol}|{strategy}|{day_type}")].append(trade)
        if features.get("market_context_snapshot_status") == "current":
            candle = str(features.get("candlestick_primary_signal") or "none")
            htf = str(features.get("htf_primary_bias") or "unknown")
            alignment = str(features.get("htf_intraday_alignment") or "unknown")
            grouped[("setup_symbol_candle", f"{symbol}|{strategy}|{candle}")].append(trade)
            grouped[("setup_symbol_htf", f"{symbol}|{strategy}|{htf}|{alignment}")].append(trade)
    rows = [
        _walk_forward_cohort(cohort_type, cohort, items)
        for (cohort_type, cohort), items in sorted(grouped.items())
        if len(items) >= MIN_STRUCTURE_COHORT_COMPLETED
    ]
    rows.sort(
        key=lambda row: (
            float(row["chronological_holdout"].get("expectancy_return_pct") or -1e9),
            int(row["full"].get("count") or 0),
        ),
        reverse=True,
    )
    return {
        "authority": "read_only_setup_attribution_no_execution",
        "minimum_report_count": MIN_STRUCTURE_COHORT_COMPLETED,
        "review_requirements": {
            "completed": MIN_STRUCTURE_REVIEW_COMPLETED,
            "distinct_dates": MIN_STRUCTURE_REVIEW_DATES,
            "chronological_holdout": MIN_STRUCTURE_HOLDOUT_COMPLETED,
            "executable_quote_coverage": 0.95,
            "positive_full_holdout_doubled_cost_and_top5_removed": True,
            "max_profitable_day_contribution": 0.20,
        },
        "cohort_count": len(rows),
        "statistical_gate_ready_count": sum(row["statistical_gate_ready"] for row in rows),
        "cohorts": rows,
    }


def build_report(source_path: Path = SOURCE_PATH) -> dict[str, Any]:
    all_trades = _group_shadow_rows(_read_jsonl(source_path))
    research_trades = [
        trade for trade in all_trades
        if str(trade.get("strategy") or "") in evaluator.RESEARCH_ONLY_STRATEGIES
    ]
    trades = [
        trade for trade in all_trades
        if str(trade.get("strategy") or "") not in evaluator.RESEARCH_ONLY_STRATEGIES
    ]
    by_bucket: dict[str, list[dict[str, Any]]] = defaultdict(list)
    by_bucket_strategy: dict[str, list[dict[str, Any]]] = defaultdict(list)
    by_bucket_symbol: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for trade in trades:
        bucket = str(trade.get("episode_bucket_et") or "unknown")
        strategy = str(trade.get("strategy") or "unknown")
        symbol = str(trade.get("symbol") or "unknown")
        by_bucket[bucket].append(trade)
        by_bucket_strategy[f"{bucket}|{strategy}"].append(trade)
        by_bucket_symbol[f"{bucket}|{symbol}"].append(trade)

    bucket_rows = _apply_selector_haircut([
        {"bucket_et": bucket, **_summarize(items)}
        for bucket, items in sorted(by_bucket.items())
    ])
    strategy_rows = _apply_selector_haircut([
        {"bucket_et": key.split("|", 1)[0], "strategy": key.split("|", 1)[1], **_summarize(items)}
        for key, items in sorted(by_bucket_strategy.items())
    ])
    symbol_rows = _apply_selector_haircut([
        {"bucket_et": key.split("|", 1)[0], "symbol": key.split("|", 1)[1], **_summarize(items)}
        for key, items in sorted(by_bucket_symbol.items())
    ])
    rankable = [row for row in bucket_rows if row["completed_count"] >= MIN_BUCKET_RANKING_COMPLETED]
    ranked = sorted(
        rankable,
        key=lambda row: (row["expectancy_return_pct"], row["completed_count"]),
        reverse=True,
    )
    selector_rankings = [
        {
            **row,
            "shadow_selector_rank": index,
            "ranking_authority": "shadow_research_only",
        }
        for index, row in enumerate(ranked, start=1)
    ]
    best = selector_rankings
    worst = sorted(
        selector_rankings,
        key=lambda row: (row["expectancy_return_pct"], -row["completed_count"]),
    )
    research_by_strategy: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for trade in research_trades:
        research_by_strategy[str(trade.get("strategy") or "unknown")].append(trade)
    research_strategy_rows = [
        {"strategy": strategy, **_summarize(items), "ranking_authority": "isolated_shadow_research_only"}
        for strategy, items in sorted(research_by_strategy.items())
    ]
    return {
        "provider": "flip_shadow_time_bucket_report",
        "mode": "read_only",
        "execution_enabled": False,
        "can_submit_orders": False,
        "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "source_path": str(source_path),
        "completed_lifecycle_count": len(trades),
        "research_completed_lifecycle_count": len(research_trades),
        "min_bucket_ranking_completed": MIN_BUCKET_RANKING_COMPLETED,
        "min_bucket_gate_review_completed": MIN_BUCKET_GATE_REVIEW_COMPLETED,
        "selector_haircut_per_trial_pct": SELECTOR_HAIRCUT_PER_TRIAL_PCT,
        "buckets": bucket_rows,
        "by_bucket_strategy": strategy_rows,
        "by_bucket_symbol": symbol_rows,
        "best_buckets": best[:5],
        "weak_buckets": worst[:5],
        "shadow_selector_rankings": selector_rankings,
        "research_strategy_results": research_strategy_rows,
        "market_structure_walk_forward": _market_structure_cohorts(all_trades),
        "time_gate_authority": "none",
        "warnings": [
            "Read-only shadow analysis. Do not trade from one bucket without forward confirmation.",
            "Cost-adjusted evidence uses entry ask / exit bid when available; incomplete quote coverage remains shadow-only.",
            "Buckets with 10-29 completions may be ranked for shadow research but cannot become live gates.",
            "Thirty completions only permits gate review; it never auto-promotes a time filter.",
            "Research-only 15-minute ORB and level-sweep lifecycles are excluded from primary time-bucket selector rankings.",
            "Selector rankings include a simple multiple-testing haircut; it is a governance brake, not a statistical proof.",
            "Market-structure cohorts use chronological date holdout and cannot change execution settings.",
            "Context-conditioned cohorts are diagnostic only; only preregistered setup-symbol cohorts may reach statistical review.",
        ],
    }


def write_report(report: dict[str, Any], path: Path = REPORT_PATH) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(temp, path)


def append_log(report: dict[str, Any], path: Path = LOG_PATH) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(report, separators=(",", ":"), sort_keys=True) + "\n")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-path", type=Path, default=SOURCE_PATH)
    parser.add_argument("--report-path", type=Path, default=REPORT_PATH)
    parser.add_argument("--log-path", type=Path, default=LOG_PATH)
    parser.add_argument("--print", action="store_true", dest="do_print")
    args = parser.parse_args()
    report = build_report(args.source_path)
    write_report(report, args.report_path)
    append_log(report, args.log_path)
    if args.do_print:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        print(f"Flip shadow time-bucket report written to {args.report_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

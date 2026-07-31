#!/usr/bin/env python3
"""Mine Flip shadow lifecycles for time-of-day edge.

Read-only: consumes `flip_shadow_candidates_log.jsonl` and reports which entry
time buckets show usable cost-adjusted expectancy. It never places orders or
changes thresholds.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

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
    return {
        "completed_count": len(items),
        "winner_count": len(wins),
        "loser_count": len(losses),
        "win_rate": round(win_rate, 3),
        "expectancy_return_pct": round(expectancy, 2),
        "avg_win_return_pct": round(avg_win, 2),
        "avg_loss_return_pct": round(avg_loss, 2),
        "avg_capture_efficiency": round(avg_capture, 3),
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
        "time_gate_authority": "none",
        "warnings": [
            "Read-only shadow analysis. Do not trade from one bucket without forward confirmation.",
            "Cost-adjusted evidence uses entry ask / exit bid when available; incomplete quote coverage remains shadow-only.",
            "Buckets with 10-29 completions may be ranked for shadow research but cannot become live gates.",
            "Thirty completions only permits gate review; it never auto-promotes a time filter.",
            "Research-only 15-minute ORB and level-sweep lifecycles are excluded from primary time-bucket selector rankings.",
            "Selector rankings include a simple multiple-testing haircut; it is a governance brake, not a statistical proof.",
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

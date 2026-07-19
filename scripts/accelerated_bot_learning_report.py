#!/usr/bin/env python3
"""Build joint Flip/options learning memory from actual and shadow lifecycles.

Read-only: this report never places orders or edits strategy parameters. It
turns every completed schema-v3 episode and actual closed trade into explicit
performance evidence, with failure diagnoses that can nominate later trials.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import sys
from collections import defaultdict
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts import flip_shadow_pnl_evaluator as evaluator
from scripts import closed_trade_postmortem as postmortem


VIBE_HOME = Path.home() / ".vibe-trading"
SHADOW_LOG_PATH = ROOT / "data" / "flip_shadow_candidates_log.jsonl"
FLIP_TRADES_PATH = VIBE_HOME / "flip-trades.json"
OPTIONS_TRADES_PATH = VIBE_HOME / "options-trades.json"
REPORT_PATH = VIBE_HOME / "reports" / "accelerated-bot-learning.json"
LOG_PATH = ROOT / "data" / "accelerated_bot_learning_log.jsonl"
EDGE_TRIAL_REPORT_PATH = VIBE_HOME / "reports" / "edge-trial-ledger.json"
FORWARD_PLAN_PATH = ROOT / "research" / "edge_trials" / "accelerated_directional_v3_forward_plan_2026-07-15.json"


def _read_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        return default


def _safe_float(value: Any) -> float | None:
    try:
        return float(value) if value not in (None, "") else None
    except (TypeError, ValueError):
        return None


def _shadow_trades(path: Path) -> list[dict[str, Any]]:
    rows = [
        row for row in evaluator._read_jsonl(path)
        if int(row.get("schema_version") or 0) >= 3
        and row.get("data_quality") == "current_session_lifecycle"
        and row.get("execution_mode") == "shadow_only"
        and str(row.get("strategy") or "") not in evaluator.RESEARCH_ONLY_STRATEGIES
    ]
    groups: dict[tuple[str, ...], list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        if row.get("symbol") and row.get("option_symbol"):
            groups[evaluator._row_key(row)].append(row)
    return [evaluator.evaluate_group(group) for group in groups.values()]


def _return_summary(values: list[float]) -> dict[str, Any]:
    winners = [value for value in values if value > 0]
    losers = [abs(value) for value in values if value <= 0]
    win_rate = len(winners) / len(values) if values else 0.0
    avg_win = sum(winners) / len(winners) if winners else 0.0
    avg_loss = sum(losers) / len(losers) if losers else 0.0
    expectancy = win_rate * avg_win - (1 - win_rate) * avg_loss if values else 0.0
    return {
        "completed_count": len(values),
        "winner_count": len(winners),
        "loser_count": len(losers),
        "win_rate": round(win_rate, 3),
        "avg_win": round(avg_win, 2),
        "avg_loss": round(avg_loss, 2),
        "payoff_ratio": round(avg_win / avg_loss, 3) if avg_loss else None,
        "expectancy": round(expectancy, 2),
        "net_return_points": round(sum(values), 2),
    }


def _actual_flip(path: Path) -> dict[str, Any]:
    rows = _read_json(path, [])
    closed = [row for row in rows if isinstance(row, dict) and row.get("status") == "closed"]
    pnls = [_safe_float(row.get("pnl")) for row in closed]
    values = [value for value in pnls if value is not None]
    return {**_return_summary(values), "metric": "realized_pnl_dollars", "source_count": len(closed)}


def _actual_options(path: Path) -> dict[str, Any]:
    payload = _read_json(path, {})
    rows = payload.get("trades") if isinstance(payload, dict) else []
    deduped = postmortem.dedupe_options_trade_records(rows or [])
    closed = [row for row in deduped if isinstance(row, dict) and row.get("status") == "closed"]
    pnls: list[float] = []
    unresolved = 0
    for row in closed:
        explicit = _safe_float(row.get("pnl"))
        if explicit is not None:
            pnls.append(explicit)
            continue
        credit = _safe_float(row.get("net_credit"))
        debit = _safe_float(row.get("closing_filled_avg_price"))
        qty = _safe_float(row.get("qty")) or 1.0
        if credit is not None and debit is not None:
            pnls.append((credit - debit) * qty * 100)
        else:
            unresolved += 1
    return {
        **_return_summary(pnls),
        "metric": "realized_or_fill_derived_pnl_dollars",
        "source_count": len(closed),
        "unresolved_pnl_count": unresolved,
    }


def _actual_trade_postmortems(flip_path: Path, options_path: Path) -> list[dict[str, Any]]:
    cases: list[dict[str, Any]] = []
    flip_rows = _read_json(flip_path, [])
    for row in flip_rows if isinstance(flip_rows, list) else []:
        if isinstance(row, dict) and row.get("status") == "closed":
            cases.append(postmortem.score_flip_trade(row))

    options_payload = _read_json(options_path, {})
    options_rows = options_payload.get("trades") if isinstance(options_payload, dict) else []
    for row in postmortem.dedupe_options_trade_records(options_rows or []):
        if not isinstance(row, dict) or row.get("status") != "closed":
            continue
        normalized = dict(row)
        if _safe_float(normalized.get("pnl")) is None:
            credit = _safe_float(normalized.get("net_credit"))
            debit = _safe_float(normalized.get("closing_filled_avg_price"))
            qty = _safe_float(normalized.get("qty")) or 1.0
            if credit is not None and debit is not None:
                normalized["pnl"] = (credit - debit) * qty * 100
        cases.append(postmortem.score_iwm_trade(normalized))
    return cases


def _diagnosis(trade: dict[str, Any]) -> str:
    result = float(trade.get("evidence_exit_return_pct") or 0.0)
    reason = str(trade.get("cost_adjusted_exit_reason") or trade.get("simulated_exit_reason") or trade.get("logged_exit_reason") or "")
    best = float(trade.get("cost_adjusted_best_return_pct") or trade.get("return_pct") or 0.0)
    spread = (trade.get("entry_reasoning") or {}).get("spread_cents")
    if reason.startswith("stop_"):
        return "Thesis failed before follow-through; test stricter entry confirmation for this feature/regime cluster."
    if result <= 0 and best > 0:
        return "Trade showed edge then surrendered it; compare earlier ratchet and direction-flip exits in a preregistered trial."
    if result <= 0 and spread not in (None, "") and float(spread) >= 10:
        return "Wide entry market likely impaired expectancy; test a tighter spread veto without changing production yet."
    if result <= 0:
        return "No profitable follow-through inside the fixed horizon; test whether this setup belongs in a different regime or time bucket."
    return "Winner retained for contrastive learning."


def _shadow_failure_memory(trades: list[dict[str, Any]]) -> list[dict[str, Any]]:
    failures = [trade for trade in trades if trade.get("status") == "loser"]
    failures.sort(key=lambda row: (str(row.get("date") or ""), str(row.get("entry_seen_at") or "")), reverse=True)
    return [
        {
            "source": "accelerated_directional_shadow",
            "lifecycle_id": trade.get("lifecycle_id"),
            "date": trade.get("date"),
            "symbol": trade.get("symbol"),
            "right": trade.get("right"),
            "strategy": trade.get("strategy"),
            "options_playbook": trade.get("options_playbook"),
            "episode_bucket_et": trade.get("episode_bucket_et"),
            "return_pct": trade.get("evidence_exit_return_pct"),
            "best_return_pct": trade.get("cost_adjusted_best_return_pct") if trade.get("executable_quote_coverage") else trade.get("return_pct"),
            "giveback_pct": trade.get("giveback_pct"),
            "exit_reason": trade.get("cost_adjusted_exit_reason") if trade.get("executable_quote_coverage") else trade.get("simulated_exit_reason"),
            "price_basis": trade.get("evidence_price_basis"),
            "executable_quote_coverage": trade.get("executable_quote_coverage"),
            "feature_snapshot": trade.get("feature_snapshot") or {},
            "entry_reasoning": trade.get("entry_reasoning") or {},
            "diagnosis": _diagnosis(trade),
            "next_action": "nominate_shadow_trial_only",
        }
        for trade in failures[:100]
    ]


def _geometric_compounding_evidence(trades: list[dict[str, Any]]) -> dict[str, Any]:
    ordered = sorted(trades, key=lambda row: (str(row.get("date") or ""), str(row.get("entry_seen_at") or "")))
    returns = [float(row.get("evidence_exit_return_pct") or 0.0) / 100.0 for row in ordered]
    valid = [value for value in returns if value > -1.0]
    mean_log_return = sum(math.log1p(value) for value in valid) / len(valid) if valid else 0.0
    geometric_mean = math.expm1(mean_log_return) if valid else 0.0
    equity = 1.0
    peak = 1.0
    max_drawdown = 0.0
    for value in valid:
        equity *= 1.0 + value
        peak = max(peak, equity)
        max_drawdown = max(max_drawdown, (peak - equity) / peak if peak > 0 else 0.0)

    by_day: dict[str, list[float]] = defaultdict(list)
    for row, value in zip(ordered, returns):
        by_day[str(row.get("date") or "")].append(value)
    clustered_daily_returns = [sum(values) / len(values) for _, values in sorted(by_day.items()) if values]
    valid_daily = [value for value in clustered_daily_returns if value > -1.0]
    daily_geometric_mean = (
        math.expm1(sum(math.log1p(value) for value in valid_daily) / len(valid_daily))
        if valid_daily else 0.0
    )
    holdout = valid[-30:] if len(valid) >= 100 else []
    holdout_geometric_mean = (
        math.expm1(sum(math.log1p(value) for value in holdout) / len(holdout)) if holdout else None
    )
    quote_coverage_count = sum(1 for row in ordered if row.get("executable_quote_coverage") is True)
    return {
        "basis": "option_contract_return_sequence_not_account_equity",
        "completed_episode_count": len(ordered),
        "executable_quote_coverage_count": quote_coverage_count,
        "executable_quote_coverage_rate": round(quote_coverage_count / len(ordered), 3) if ordered else 0.0,
        "arithmetic_expectancy_pct": round(sum(valid) / len(valid) * 100, 3) if valid else 0.0,
        "geometric_mean_return_pct": round(geometric_mean * 100, 3),
        "clustered_daily_geometric_mean_pct": round(daily_geometric_mean * 100, 3),
        "sequence_max_drawdown_pct": round(max_drawdown * 100, 3),
        "chronological_holdout_count": len(holdout),
        "chronological_holdout_geometric_mean_pct": round(holdout_geometric_mean * 100, 3) if holdout_geometric_mean is not None else None,
        "portfolio_compounding_proven": False,
    }


def _actual_failure_memory(cases: list[dict[str, Any]]) -> list[dict[str, Any]]:
    failures = [case for case in cases if _safe_float(case.get("pnl")) is not None and float(case["pnl"]) < 0]
    failures.sort(key=lambda row: (str(row.get("date") or ""), str(row.get("trade_id") or "")), reverse=True)
    return [
        {
            "source": "actual_paper_trade",
            "bot": case.get("bot"),
            "trade_id": case.get("trade_id"),
            "date": case.get("date"),
            "symbol": case.get("symbol"),
            "strategy": case.get("strategy"),
            "direction": case.get("direction"),
            "pnl_dollars": case.get("pnl"),
            "process_score": case.get("score"),
            "process_grade": case.get("grade"),
            "entry_and_exit_evidence": (case.get("pnl_explanation") or {}).get("evidence") or [],
            "diagnosis": (case.get("pnl_explanation") or {}).get("primary_driver"),
            "risk_lesson": (case.get("pnl_explanation") or {}).get("risk_lesson"),
            "next_action": (case.get("pnl_explanation") or {}).get("next_action"),
        }
        for case in failures
    ]


def build_report(
    *,
    shadow_path: Path = SHADOW_LOG_PATH,
    flip_path: Path = FLIP_TRADES_PATH,
    options_path: Path = OPTIONS_TRADES_PATH,
    edge_trial_report_path: Path = EDGE_TRIAL_REPORT_PATH,
    forward_plan_path: Path = FORWARD_PLAN_PATH,
    day: str | None = None,
) -> dict[str, Any]:
    day = day or date.today().isoformat()
    trades = _shadow_trades(shadow_path)
    completed = [trade for trade in trades if trade.get("status") in {"winner", "loser"}]
    returns = [float(trade.get("evidence_exit_return_pct") or 0.0) for trade in completed]
    today_trades = [trade for trade in trades if str(trade.get("date") or "") == day]
    today_completed = [trade for trade in completed if str(trade.get("date") or "") == day]
    trading_days = {str(trade.get("date") or "") for trade in completed if trade.get("date")}
    shadow_summary = _return_summary(returns)
    actual_postmortems = _actual_trade_postmortems(flip_path, options_path)
    failure_memory = _actual_failure_memory(actual_postmortems) + _shadow_failure_memory(completed)
    compounding = _geometric_compounding_evidence(completed)
    edge_trial_report = _read_json(edge_trial_report_path, {})
    forward_plan = _read_json(forward_plan_path, {})
    compounding_blockers = []
    if len(completed) < 100:
        compounding_blockers.append("fewer_than_100_completed_accelerated_episodes")
    if len(trading_days) < 10:
        compounding_blockers.append("fewer_than_10_distinct_trading_days")
    if compounding["chronological_holdout_count"] < 30:
        compounding_blockers.append("30_episode_chronological_holdout_unavailable")
    if compounding["executable_quote_coverage_rate"] < 1.0:
        compounding_blockers.append("incomplete_entry_ask_exit_bid_quote_coverage")
    if int(edge_trial_report.get("trial_count") or 0) == 0:
        compounding_blockers.append("no_preregistered_edge_trials_recorded")
    if forward_plan.get("status") != "preregistered_not_started":
        compounding_blockers.append("forward_compounding_trial_not_preregistered")
    compounding_blockers.append("account_equity_allocation_and_cross_episode_correlation_not_yet_proven")
    compounding["blockers"] = compounding_blockers
    compounding["edge_trial_count"] = int(edge_trial_report.get("trial_count") or 0)
    compounding["forward_plan"] = {
        "plan_id": forward_plan.get("plan_id"),
        "status": forward_plan.get("status"),
        "oos_start": forward_plan.get("oos_start"),
        "oos_end": forward_plan.get("oos_end"),
        "primary_metric": forward_plan.get("primary_metric"),
    }
    return {
        "provider": "accelerated_bot_learning_report",
        "mode": "read_only_learning_memory",
        "execution_enabled": False,
        "can_submit_orders": False,
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
        "date": day,
        "learning_contract": {
            "episode_interval_minutes": 30,
            "episode_horizon_minutes": 60,
            "target_return_pct": 75,
            "stop_return_pct": -30,
            "promotion_review_min_completed": 100,
            "promotion_review_min_trading_days": 10,
            "promotion_review_min_chronological_holdout": 30,
            "automatic_live_promotion": False,
        },
        "throughput": {
            "today_episode_count": len(today_trades),
            "today_completed_count": len(today_completed),
            "all_episode_count": len(trades),
            "all_completed_count": len(completed),
            "distinct_trading_days": len(trading_days),
        },
        "flip_bot": {
            "actual_paper": _actual_flip(flip_path),
            "accelerated_directional_shadow": shadow_summary,
        },
        "options_bot": {
            "actual_defined_risk_paper": _actual_options(options_path),
            "accelerated_directional_contract_shadow": shadow_summary,
            "scope_note": "Directional contract episodes train symbol, contract, entry, and exit intelligence; actual condor/spread fills remain the evidence source for premium-selling strategies.",
        },
        "actual_trade_postmortems": actual_postmortems,
        "failure_memory": failure_memory,
        "compounding_evidence": compounding,
        "memory_sources": {
            "shadow_lifecycle_source_of_truth": str(shadow_path),
            "actual_flip_source_of_truth": str(flip_path),
            "actual_options_source_of_truth": str(options_path),
            "resolved_shadow_evaluation": str(evaluator.REPORT_PATH),
            "actual_postmortem_log": str(postmortem.LOG_PATH),
        },
        "readiness": {
            "completed_remaining": max(0, 100 - len(completed)),
            "trading_days_remaining": max(0, 10 - len(trading_days)),
            "human_review_only": True,
        },
        "warnings": [
            "Many same-day episodes accelerate learning but do not create extra trading-day diversity.",
            "Shadow prices are estimates and cannot prove achievable fills without spread/slippage checks.",
            "Failure memory may nominate experiments; it cannot rewrite production thresholds or enable live execution.",
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
    parser = argparse.ArgumentParser(description="Build joint accelerated Flip/options learning memory.")
    parser.add_argument("--print", action="store_true", dest="print_report")
    parser.add_argument("--report-path", type=Path, default=REPORT_PATH)
    args = parser.parse_args()
    report = build_report()
    write_report(report, args.report_path)
    append_log(report)
    if args.print_report:
        print(json.dumps({"throughput": report["throughput"], "readiness": report["readiness"]}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

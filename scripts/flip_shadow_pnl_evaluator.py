"""Evaluate hypothetical P&L for Flip Bot 0DTE shadow candidates.

Read-only. This consumes the shadow candidate log and estimates what each
candidate could have done after its first logged scan. It never calls a broker.
"""
from __future__ import annotations

import argparse
import json
import math
from collections import defaultdict
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
VIBE_HOME = Path.home() / ".vibe-trading"
LOG_PATH = ROOT / "data" / "flip_shadow_candidates_log.jsonl"
REPORT_PATH = VIBE_HOME / "reports" / "flip-shadow-pnl-evaluator.json"
EVAL_LOG_PATH = ROOT / "data" / "flip_shadow_pnl_evaluation_log.jsonl"
TARGET_RETURN_PCT = 75.0
STOP_RETURN_PCT = -30.0
RATCHET_ARM_PCT = 40.0
RATCHET_FLOOR_PCT = 25.0
RATCHET_GIVEBACK_PCT = 15.0
OOS_FRACTION = 0.20
MIN_OOS_SAMPLES = 5
ACCELERATED_MIN_COMPLETED = 100
ACCELERATED_MIN_TRADING_DAYS = 10
ACCELERATED_MIN_OOS_SAMPLES = 30
DIRECTIONAL_CONFLICT_MIN_OBSERVATIONS = 10
RESEARCH_ONLY_STRATEGIES = frozenset(
    {"orb_15m_retest", "level_sweep_reversal", "orb_extension_reversal"}
)
RESEARCH_STRATEGY_MIN_COMPLETED = 50
RESEARCH_STRATEGY_MIN_TRADING_DAYS = 10
RESEARCH_STRATEGY_MIN_OOS_SAMPLES = 15


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        raw = raw.strip()
        if not raw:
            continue
        try:
            row = json.loads(raw)
        except json.JSONDecodeError:
            continue
        if isinstance(row, dict):
            rows.append(row)
    return rows


def _safe_float(value: Any) -> float | None:
    try:
        if value in (None, ""):
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _safe_int(value: Any, default: int = 1) -> int:
    try:
        return max(1, int(value))
    except (TypeError, ValueError):
        return default


def _row_key(row: dict[str, Any]) -> tuple[str, ...]:
    lifecycle_id = str(row.get("lifecycle_id") or "")
    if lifecycle_id:
        return ("episode", lifecycle_id)
    return (
        "legacy",
        str(row.get("date") or "")[:10],
        str(row.get("symbol") or ""),
        str(row.get("right") or ""),
        str(row.get("option_symbol") or ""),
        str(row.get("strategy") or "0dte"),
    )


def _directional_conflict(right: Any, classification: Any) -> bool:
    normalized_right = str(right or "").upper()
    normalized_force = str(classification or "").lower()
    return (
        normalized_right == "CALL" and normalized_force == "bearish_confirmation"
    ) or (
        normalized_right == "PUT" and normalized_force == "bullish_confirmation"
    )


def _first_directional_conflict(
    rows: list[dict[str, Any]],
    *,
    right: Any,
    midpoint_entry: float,
    executable_entry: float,
) -> dict[str, Any] | None:
    """Return the first forward-observed conflict after entry, never the entry row."""
    for row in rows[1:]:
        if row.get("market_force_snapshot_status") != "current":
            continue
        classification = row.get("market_force_classification")
        if not _directional_conflict(right, classification):
            continue
        midpoint_exit = _safe_float(row.get("entry_price_est"))
        executable_exit = _safe_float(row.get("selection_bid"))
        if executable_entry > 0 and executable_exit is not None and executable_exit > 0:
            exit_price = executable_exit
            entry_price = executable_entry
            price_basis = "entry_ask_exit_bid"
        elif midpoint_entry > 0 and midpoint_exit is not None and midpoint_exit > 0:
            exit_price = midpoint_exit
            entry_price = midpoint_entry
            price_basis = "midpoint_fallback_not_promotion_grade"
        else:
            return None
        return {
            "classification": classification,
            "seen_at": row.get("scanned_at"),
            "market_force_timestamp": row.get("market_force_timestamp"),
            "exit_price": exit_price,
            "exit_return_pct": ((exit_price - entry_price) / entry_price) * 100,
            "price_basis": price_basis,
        }
    return None


def evaluate_group(rows: list[dict[str, Any]]) -> dict[str, Any]:
    rows = sorted(rows, key=lambda row: str(row.get("scanned_at") or ""))
    first = rows[0]
    logged_exit_reason = next(
        (row.get("mark_reason") for row in reversed(rows) if row.get("event_type") == "shadow_exit"),
        None,
    )
    entry = _safe_float(first.get("entry_price_est")) or 0.0
    entry_ask = _safe_float(first.get("selection_ask"))
    contracts = _safe_int(first.get("contracts"), 1)
    priced_rows = [row for row in rows if _safe_float(row.get("entry_price_est")) is not None]
    prices = [_safe_float(row.get("entry_price_est")) or 0.0 for row in priced_rows]
    executable_quote_coverage = bool(
        entry_ask is not None
        and entry_ask > 0
        and priced_rows
        and all((_safe_float(row.get("selection_bid")) or 0.0) > 0 for row in priced_rows)
    )

    lifecycle_closed = any(row.get("event_type") == "shadow_exit" for row in rows)
    if len(prices) < 2 or entry <= 0:
        best_price = entry
        return_pct = 0.0
        hypothetical_pnl = 0.0
        status = "insufficient_followup"
        best_seen_at = first.get("scanned_at")
        simulated_exit_price = entry
        simulated_exit_return_pct = 0.0
        simulated_exit_seen_at = first.get("scanned_at")
        simulated_exit_reason = "insufficient_followup"
    else:
        best_price = max(prices)
        best_index = prices.index(best_price)
        best_seen_at = priced_rows[best_index].get("scanned_at")
        return_pct = ((best_price - entry) / entry) * 100
        hypothetical_pnl = (best_price - entry) * contracts * 100
        simulated = _simulate_ratcheted_exit(priced_rows, entry)
        simulated_exit_price = simulated["exit_price"]
        simulated_exit_return_pct = simulated["exit_return_pct"]
        simulated_exit_seen_at = simulated["exit_seen_at"]
        simulated_exit_reason = simulated["exit_reason"]
        if lifecycle_closed and simulated_exit_reason == "last_observation" and logged_exit_reason:
            simulated_exit_reason = str(logged_exit_reason)
        if lifecycle_closed:
            status = "winner" if simulated_exit_return_pct > 0 else "loser"
        else:
            status = "open_lifecycle"

    executable_entry = float(entry_ask) if entry_ask is not None and entry_ask > 0 else entry
    executable_rows = [
        {
            **row,
            "entry_price_est": _safe_float(row.get("selection_bid")) or _safe_float(row.get("entry_price_est")),
        }
        for row in priced_rows
    ]
    executable = _simulate_ratcheted_exit(executable_rows, executable_entry) if executable_rows and executable_entry > 0 else {
        "exit_price": executable_entry,
        "exit_return_pct": 0.0,
        "exit_seen_at": first.get("scanned_at"),
        "exit_reason": "insufficient_executable_quotes",
    }
    cost_adjusted_exit_reason = executable["exit_reason"]
    if lifecycle_closed and cost_adjusted_exit_reason == "last_observation" and logged_exit_reason:
        cost_adjusted_exit_reason = str(logged_exit_reason)
    executable_prices = [
        _safe_float(row.get("entry_price_est")) or executable_entry for row in executable_rows
    ]
    cost_adjusted_best_return_pct = (
        ((max(executable_prices) - executable_entry) / executable_entry) * 100
        if executable_prices and executable_entry > 0
        else 0.0
    )
    cost_adjusted_capture_efficiency = (
        float(executable["exit_return_pct"]) / cost_adjusted_best_return_pct
        if cost_adjusted_best_return_pct > 0 and float(executable["exit_return_pct"]) > 0
        else 0.0
    )
    evidence_exit_return_pct = (
        float(executable["exit_return_pct"])
        if executable_quote_coverage
        else float(simulated_exit_return_pct or 0.0)
    )
    if lifecycle_closed:
        status = "winner" if evidence_exit_return_pct > 0 else "loser"

    directional_conflict = _first_directional_conflict(
        rows,
        right=first.get("right"),
        midpoint_entry=entry,
        executable_entry=executable_entry,
    )
    conflict_return = (
        float(directional_conflict["exit_return_pct"])
        if directional_conflict is not None
        else None
    )
    conflict_pnl = (
        (float(directional_conflict["exit_price"]) - (
            executable_entry
            if directional_conflict["price_basis"] == "entry_ask_exit_bid"
            else entry
        )) * contracts * 100
        if directional_conflict is not None
        else None
    )

    giveback_pct = max(0.0, return_pct - simulated_exit_return_pct)
    capture_efficiency = (
        round(simulated_exit_return_pct / return_pct, 3)
        if return_pct > 0 and simulated_exit_return_pct > 0
        else 0.0
    )

    return {
        "schema_version": int(first.get("schema_version") or 0),
        "lifecycle_id": first.get("lifecycle_id"),
        "learning_mode": first.get("learning_mode"),
        "learner_tracks": first.get("learner_tracks") or [],
        "episode_bucket_et": first.get("episode_bucket_et"),
        "episode_horizon_minutes": first.get("episode_horizon_minutes"),
        "date": str(first.get("date") or "")[:10],
        "symbol": first.get("symbol"),
        "right": first.get("right"),
        "strategy": first.get("strategy") or "0dte",
        "option_symbol": first.get("option_symbol"),
        "contracts": contracts,
        "entry_seen_at": first.get("scanned_at"),
        "best_seen_at": best_seen_at,
        "observation_count": len(rows),
        "lifecycle_closed": lifecycle_closed,
        "entry_price": round(entry, 4),
        "best_price": round(best_price, 4),
        "return_pct": round(return_pct, 2),
        "hypothetical_pnl": round(hypothetical_pnl, 2),
        "simulated_exit_model": "target_or_40_15_ratchet",
        "simulated_exit_price": round(float(simulated_exit_price or 0.0), 4),
        "simulated_exit_seen_at": simulated_exit_seen_at,
        "simulated_exit_return_pct": round(float(simulated_exit_return_pct or 0.0), 2),
        "simulated_exit_pnl": round(float(simulated_exit_price - entry) * contracts * 100, 2),
        "simulated_exit_reason": simulated_exit_reason,
        "executable_quote_coverage": executable_quote_coverage,
        "executable_entry_ask": round(executable_entry, 4),
        "executable_exit_bid": round(float(executable["exit_price"] or 0.0), 4),
        "cost_adjusted_exit_return_pct": round(float(executable["exit_return_pct"] or 0.0), 2),
        "cost_adjusted_exit_pnl": round(float(executable["exit_price"] - executable_entry) * contracts * 100, 2),
        "cost_adjusted_exit_reason": cost_adjusted_exit_reason,
        "cost_adjusted_best_return_pct": round(cost_adjusted_best_return_pct, 2),
        "cost_adjusted_capture_efficiency": round(cost_adjusted_capture_efficiency, 3),
        "evidence_exit_return_pct": round(evidence_exit_return_pct, 2),
        "evidence_capture_efficiency": (
            round(cost_adjusted_capture_efficiency, 3) if executable_quote_coverage else capture_efficiency
        ),
        "evidence_target_hit": (
            str(cost_adjusted_exit_reason).startswith("target_") if executable_quote_coverage else return_pct >= TARGET_RETURN_PCT
        ),
        "evidence_price_basis": "entry_ask_exit_bid" if executable_quote_coverage else "midpoint_fallback_not_promotion_grade",
        "directional_conflict_exit_model": "first_post_entry_market_force_conflict",
        "directional_conflict_observed": directional_conflict is not None,
        "directional_conflict_classification": directional_conflict.get("classification") if directional_conflict else None,
        "directional_conflict_seen_at": directional_conflict.get("seen_at") if directional_conflict else None,
        "directional_conflict_market_force_timestamp": directional_conflict.get("market_force_timestamp") if directional_conflict else None,
        "directional_conflict_exit_price": round(float(directional_conflict["exit_price"]), 4) if directional_conflict else None,
        "directional_conflict_exit_return_pct": round(conflict_return, 2) if conflict_return is not None else None,
        "directional_conflict_exit_pnl": round(conflict_pnl, 2) if conflict_pnl is not None else None,
        "directional_conflict_price_basis": directional_conflict.get("price_basis") if directional_conflict else None,
        "directional_conflict_vs_baseline_return_delta_pct": (
            round(conflict_return - evidence_exit_return_pct, 2)
            if conflict_return is not None and lifecycle_closed
            else None
        ),
        "directional_conflict_min_observations_for_review": DIRECTIONAL_CONFLICT_MIN_OBSERVATIONS,
        "logged_exit_reason": logged_exit_reason,
        "feature_snapshot": first.get("feature_snapshot") or {},
        "entry_reasoning": first.get("entry_reasoning") or {},
        "options_playbook": first.get("options_playbook"),
        "giveback_pct": round(giveback_pct, 2),
        "capture_efficiency": capture_efficiency,
        "target_missed_by_pct": round(max(0.0, TARGET_RETURN_PCT - return_pct), 2),
        "best_spread_cents": min(
            [
                int(spread)
                for spread in (_safe_float(row.get("spread_cents")) for row in rows)
                if spread is not None
            ],
            default=None,
        ),
        "status": status,
        "target_75_hit": return_pct >= TARGET_RETURN_PCT,
        "execution_mode": "shadow_only",
    }


def _simulate_ratcheted_exit(rows: list[dict[str, Any]], entry: float) -> dict[str, Any]:
    best_return = float("-inf")
    last_row = rows[-1]
    last_price = _safe_float(last_row.get("entry_price_est")) or entry
    for row in rows:
        price = _safe_float(row.get("entry_price_est")) or entry
        current_return = ((price - entry) / entry) * 100
        best_return = max(best_return, current_return)
        if current_return <= STOP_RETURN_PCT:
            return {
                "exit_price": price,
                "exit_return_pct": current_return,
                "exit_seen_at": row.get("scanned_at"),
                "exit_reason": f"stop_{abs(STOP_RETURN_PCT):.0f}_hit",
            }
        if current_return >= TARGET_RETURN_PCT:
            return {
                "exit_price": price,
                "exit_return_pct": current_return,
                "exit_seen_at": row.get("scanned_at"),
                "exit_reason": f"target_{TARGET_RETURN_PCT:.0f}_hit",
            }
        lock_floor = max(RATCHET_FLOOR_PCT, best_return - RATCHET_GIVEBACK_PCT)
        if best_return >= RATCHET_ARM_PCT and 0 < current_return <= lock_floor:
            return {
                "exit_price": price,
                "exit_return_pct": current_return,
                "exit_seen_at": row.get("scanned_at"),
                "exit_reason": f"ratchet_lock_{lock_floor:.1f}",
            }
    last_return = ((last_price - entry) / entry) * 100 if entry > 0 else 0.0
    return {
        "exit_price": last_price,
        "exit_return_pct": last_return,
        "exit_seen_at": last_row.get("scanned_at"),
        "exit_reason": "last_observation",
    }


def _symbol_summary(trades: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for trade in trades:
        if trade.get("symbol"):
            grouped[str(trade["symbol"])].append(trade)
    summary: dict[str, dict[str, Any]] = {}
    for symbol, items in sorted(grouped.items()):
        completed = [item for item in items if item.get("status") in {"winner", "loser"}]
        completed.sort(key=lambda item: (str(item.get("date") or ""), str(item.get("entry_seen_at") or "")))
        winners = [item for item in completed if float(item.get("evidence_exit_return_pct") or 0) > 0]
        losers = [item for item in completed if float(item.get("evidence_exit_return_pct") or 0) <= 0]
        trading_days = {str(item.get("date") or "") for item in completed if item.get("date")}
        target_hits = [item for item in completed if item.get("evidence_target_hit")]
        exit_returns = [float(item.get("evidence_exit_return_pct") or 0.0) for item in completed]
        win_returns = [value for value in exit_returns if value > 0]
        loss_returns = [abs(value) for value in exit_returns if value <= 0]
        avg_win = sum(win_returns) / len(win_returns) if win_returns else 0.0
        avg_loss = sum(loss_returns) / len(loss_returns) if loss_returns else 0.0
        avg_capture = (
            sum(float(item.get("evidence_capture_efficiency") or 0.0) for item in completed) / len(completed)
            if completed
            else 0.0
        )
        win_rate = len(winners) / len(completed) if completed else 0.0
        loss_rate = len(losers) / len(completed) if completed else 0.0
        expectancy = (win_rate * avg_win) - (loss_rate * avg_loss) if completed else 0.0
        accelerated = any(int(item.get("schema_version") or 0) >= 3 for item in completed)
        accelerated_completed = [item for item in completed if int(item.get("schema_version") or 0) >= 3]
        executable_covered = [item for item in accelerated_completed if item.get("executable_quote_coverage") is True]
        executable_quote_coverage_rate = (
            len(executable_covered) / len(accelerated_completed) if accelerated_completed else 1.0
        )
        required_completed = ACCELERATED_MIN_COMPLETED if accelerated else 10
        required_trading_days = ACCELERATED_MIN_TRADING_DAYS if accelerated else 30
        required_oos = ACCELERATED_MIN_OOS_SAMPLES if accelerated else MIN_OOS_SAMPLES
        oos_count = max(required_oos, math.ceil(len(completed) * OOS_FRACTION)) if completed else 0
        oos_items = completed[-min(oos_count, len(completed)):]
        oos_returns = [float(item.get("evidence_exit_return_pct") or 0.0) for item in oos_items]
        oos_winners = [value for value in oos_returns if value > 0]
        oos_losers = [abs(value) for value in oos_returns if value <= 0]
        oos_win_rate = len(oos_winners) / len(oos_returns) if oos_returns else 0.0
        oos_avg_win = sum(oos_winners) / len(oos_winners) if oos_winners else 0.0
        oos_avg_loss = sum(oos_losers) / len(oos_losers) if oos_losers else 0.0
        oos_expectancy = (
            oos_win_rate * oos_avg_win - (1.0 - oos_win_rate) * oos_avg_loss
            if oos_returns
            else 0.0
        )
        target_hit_rate = len(target_hits) / len(completed) if completed else 0.0
        selection_score = round(
            100 * (
                0.35 * win_rate
                + 0.20 * target_hit_rate
                + 0.20 * avg_capture
                + 0.25 * min(max(expectancy, 0.0) / TARGET_RETURN_PCT, 1.0)
            ),
            1,
        )
        promotion_eligible = (
            len(completed) >= required_completed
            and len(trading_days) >= required_trading_days
            and expectancy > 0
            and len(oos_items) >= required_oos
            and oos_expectancy > 0
            and avg_loss <= max(avg_win * 1.25, abs(STOP_RETURN_PCT))
            and executable_quote_coverage_rate >= 1.0
        )
        summary[symbol] = {
            "evidence_path": "accelerated_clustered_forward" if accelerated else "legacy_daily_forward",
            "required_completed_count": required_completed,
            "required_trading_day_count": required_trading_days,
            "required_out_of_sample_count": required_oos,
            "executable_quote_coverage_rate": round(executable_quote_coverage_rate, 3),
            "promotion_price_basis": "entry_ask_exit_bid_required" if accelerated else "legacy_midpoint_evidence",
            "sample_count": len(items),
            "completed_count": len(completed),
            "trading_day_count": len(trading_days),
            "winner_count": len(winners),
            "loser_count": len(losers),
            "win_rate": round(win_rate, 3),
            "loss_rate": round(1.0 - win_rate, 3) if completed else 0.0,
            "target_hit_rate": round(target_hit_rate, 3),
            "avg_return_pct": round(
                sum(float(item.get("return_pct") or 0.0) for item in completed) / len(completed),
                2,
            )
            if completed
            else 0.0,
            "best_return_pct": round(max((float(item.get("return_pct") or 0.0) for item in items), default=0.0), 2),
            "total_hypothetical_pnl": round(sum(float(item.get("hypothetical_pnl") or 0.0) for item in completed), 2),
            "avg_simulated_exit_return_pct": round(
                sum(float(item.get("evidence_exit_return_pct") or 0.0) for item in completed) / len(completed),
                2,
            ) if completed else 0.0,
            "avg_win_return_pct": round(avg_win, 2) if win_returns else 0.0,
            "avg_loss_return_pct": round(avg_loss, 2) if loss_returns else 0.0,
            "payoff_ratio": round(avg_win / avg_loss, 3) if avg_loss > 0 else None,
            "expectancy_return_pct": round(expectancy, 2),
            "out_of_sample_count": len(oos_items),
            "out_of_sample_win_rate": round(oos_win_rate, 3),
            "out_of_sample_expectancy_return_pct": round(oos_expectancy, 2),
            "out_of_sample_positive": len(oos_items) >= MIN_OOS_SAMPLES and oos_expectancy > 0,
            "avg_capture_efficiency": round(avg_capture, 3),
            "avg_giveback_pct": round(
                sum(float(item.get("giveback_pct") or 0.0) for item in completed) / len(completed),
                2,
            )
            if completed
            else 0.0,
            "selection_score": selection_score,
            "promotion_eligible": promotion_eligible,
            "recommended_use": "promotion_review" if promotion_eligible else "shadow_only",
        }
    return summary


def _research_strategy_summary(trades: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for trade in trades:
        grouped[str(trade.get("strategy") or "unknown")].append(trade)

    summaries: list[dict[str, Any]] = []
    for strategy, items in sorted(grouped.items()):
        completed = [item for item in items if item.get("status") in {"winner", "loser"}]
        completed.sort(key=lambda item: (str(item.get("date") or ""), str(item.get("entry_seen_at") or "")))
        returns = [float(item.get("evidence_exit_return_pct") or 0.0) for item in completed]
        winners = [value for value in returns if value > 0]
        losers = [abs(value) for value in returns if value <= 0]
        win_rate = len(winners) / len(returns) if returns else 0.0
        avg_win = sum(winners) / len(winners) if winners else 0.0
        avg_loss = sum(losers) / len(losers) if losers else 0.0
        expectancy = win_rate * avg_win - (1.0 - win_rate) * avg_loss if returns else 0.0
        oos_items = completed[-min(RESEARCH_STRATEGY_MIN_OOS_SAMPLES, len(completed)):]
        oos_returns = [float(item.get("evidence_exit_return_pct") or 0.0) for item in oos_items]
        oos_expectancy = sum(oos_returns) / len(oos_returns) if oos_returns else 0.0
        trading_days = {str(item.get("date") or "") for item in completed if item.get("date")}
        quote_coverage_count = sum(1 for item in completed if item.get("executable_quote_coverage") is True)
        quote_coverage_rate = quote_coverage_count / len(completed) if completed else 0.0
        promotion_review_ready = (
            len(completed) >= RESEARCH_STRATEGY_MIN_COMPLETED
            and len(trading_days) >= RESEARCH_STRATEGY_MIN_TRADING_DAYS
            and len(oos_items) >= RESEARCH_STRATEGY_MIN_OOS_SAMPLES
            and expectancy > 0
            and oos_expectancy > 0
            and quote_coverage_rate >= 1.0
        )
        summaries.append({
            "strategy": strategy,
            "authority": "shadow_challenger_only",
            "automatic_live_promotion": False,
            "sample_count": len(items),
            "completed_count": len(completed),
            "trading_day_count": len(trading_days),
            "winner_count": len(winners),
            "loser_count": len(losers),
            "win_rate": round(win_rate, 3),
            "expectancy_return_pct": round(expectancy, 2),
            "out_of_sample_count": len(oos_items),
            "out_of_sample_expectancy_return_pct": round(oos_expectancy, 2),
            "executable_quote_coverage_rate": round(quote_coverage_rate, 3),
            "required_completed_count": RESEARCH_STRATEGY_MIN_COMPLETED,
            "required_trading_day_count": RESEARCH_STRATEGY_MIN_TRADING_DAYS,
            "required_out_of_sample_count": RESEARCH_STRATEGY_MIN_OOS_SAMPLES,
            "promotion_review_ready": promotion_review_ready,
            "recommended_use": "human_promotion_review" if promotion_review_ready else "shadow_only",
        })
    return summaries


def build_report(log_path: Path = LOG_PATH, day: str | None = None) -> dict[str, Any]:
    all_rows = _read_jsonl(log_path)
    rows = [
        row for row in all_rows
        if int(row.get("schema_version") or 0) >= 2
        and row.get("data_quality") == "current_session_lifecycle"
    ]
    if day:
        rows = [row for row in rows if str(row.get("date") or "")[:10] == day]
    groups: dict[tuple[str, ...], list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        if row.get("execution_mode") not in (None, "shadow_only"):
            continue
        if not row.get("symbol") or not row.get("option_symbol"):
            continue
        groups[_row_key(row)].append(row)

    all_trades = [evaluate_group(group_rows) for group_rows in groups.values()]
    research_trades = [
        trade for trade in all_trades if str(trade.get("strategy") or "") in RESEARCH_ONLY_STRATEGIES
    ]
    trades = [
        trade for trade in all_trades if str(trade.get("strategy") or "") not in RESEARCH_ONLY_STRATEGIES
    ]
    trades.sort(key=lambda trade: float(trade.get("return_pct") or 0.0), reverse=True)
    research_trades.sort(key=lambda trade: float(trade.get("return_pct") or 0.0), reverse=True)
    completed = [trade for trade in trades if trade.get("status") in {"winner", "loser"}]
    winners = [trade for trade in completed if float(trade.get("evidence_exit_return_pct") or 0.0) > 0]
    losers = [trade for trade in completed if float(trade.get("evidence_exit_return_pct") or 0.0) <= 0]
    exit_returns = [float(trade.get("evidence_exit_return_pct") or 0.0) for trade in completed]
    avg_win = sum(value for value in exit_returns if value > 0) / len(winners) if winners else 0.0
    avg_loss = abs(sum(value for value in exit_returns if value <= 0)) / len(losers) if losers else 0.0
    win_rate = len(winners) / len(completed) if completed else 0.0
    loss_rate = len(losers) / len(completed) if completed else 0.0
    expectancy = (win_rate * avg_win) - (loss_rate * avg_loss) if completed else 0.0
    conflict_observations = [
        trade for trade in completed if trade.get("directional_conflict_observed") is True
    ]
    conflict_deltas = [
        float(trade["directional_conflict_vs_baseline_return_delta_pct"])
        for trade in conflict_observations
        if trade.get("directional_conflict_vs_baseline_return_delta_pct") is not None
    ]
    by_symbol = _symbol_summary(trades)
    research_strategy_challengers = _research_strategy_summary(research_trades)
    challenger_leaderboard = sorted(
        [dict(symbol=symbol, **summary) for symbol, summary in by_symbol.items()],
        key=lambda row: (bool(row["promotion_eligible"]), float(row["selection_score"]), int(row["completed_count"])),
        reverse=True,
    )
    today_entries = [
        {
            "symbol": row.get("symbol"),
            "right": row.get("right"),
            "option_symbol": row.get("option_symbol"),
            "entry_price_est": row.get("entry_price_est"),
            "spread_cents": row.get("spread_cents"),
            "catalyst": row.get("catalyst"),
        }
        for row in rows
        if row.get("event_type") == "shadow_entry"
    ]
    return {
        "provider": "flip_shadow_pnl_evaluator",
        "mode": "read_only",
        "execution_enabled": False,
        "date": day or date.today().isoformat(),
        "evaluation_scope": day or "all_trusted_history",
        "timestamp": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "source_path": str(log_path),
        "trusted_schema_version": 2,
        "accelerated_schema_version": 3,
        "legacy_rows_excluded": len(all_rows) - len([
            row for row in all_rows
            if int(row.get("schema_version") or 0) >= 2
            and row.get("data_quality") == "current_session_lifecycle"
        ]),
        "sample_count": len(trades),
        "completed_count": len(completed),
        "research_sample_count": len(research_trades),
        "research_completed_count": sum(
            1 for trade in research_trades if trade.get("status") in {"winner", "loser"}
        ),
        "accelerated_episode_count": sum(1 for trade in trades if int(trade.get("schema_version") or 0) >= 3),
        "accelerated_completed_count": sum(1 for trade in completed if int(trade.get("schema_version") or 0) >= 3),
        "accelerated_executable_quote_coverage_count": sum(
            1 for trade in completed
            if int(trade.get("schema_version") or 0) >= 3 and trade.get("executable_quote_coverage") is True
        ),
        "winner_count": len(winners),
        "loser_count": len(losers),
        "win_rate": round(win_rate, 3) if completed else 0.0,
        "avg_win_return_pct": round(avg_win, 2) if winners else 0.0,
        "avg_loss_return_pct": round(avg_loss, 2) if losers else 0.0,
        "payoff_ratio": round(avg_win / avg_loss, 3) if avg_loss > 0 else None,
        "expectancy_return_pct": round(expectancy, 2),
        "directional_conflict_exit_research": {
            "authority": "shadow_only",
            "observation_count": len(conflict_observations),
            "minimum_observations_for_review": DIRECTIONAL_CONFLICT_MIN_OBSERVATIONS,
            "promotion_review_ready": len(conflict_observations) >= DIRECTIONAL_CONFLICT_MIN_OBSERVATIONS,
            "avg_return_delta_vs_baseline_pct": round(sum(conflict_deltas) / len(conflict_deltas), 2) if conflict_deltas else None,
            "improved_outcome_count": sum(1 for delta in conflict_deltas if delta > 0),
            "worsened_outcome_count": sum(1 for delta in conflict_deltas if delta < 0),
            "unchanged_outcome_count": sum(1 for delta in conflict_deltas if delta == 0),
        },
        "total_hypothetical_pnl": round(sum(float(trade.get("hypothetical_pnl") or 0.0) for trade in completed), 2),
        "total_simulated_exit_pnl": round(sum(float(trade.get("simulated_exit_pnl") or 0.0) for trade in completed), 2),
        "total_cost_adjusted_exit_pnl": round(
            sum(float(trade.get("cost_adjusted_exit_pnl") or 0.0) for trade in completed if trade.get("executable_quote_coverage") is True),
            2,
        ),
        "avg_capture_efficiency": round(
            sum(float(trade.get("evidence_capture_efficiency") or 0.0) for trade in completed) / len(completed),
            3,
        )
        if completed
        else 0.0,
        "avg_giveback_pct": round(
            sum(float(trade.get("giveback_pct") or 0.0) for trade in completed) / len(completed),
            2,
        )
        if completed
        else 0.0,
        "by_symbol": by_symbol,
        "challenger_leaderboard": challenger_leaderboard,
        "research_strategy_challengers": research_strategy_challengers,
        "today_shadow_entries": today_entries,
        "execution_focus": {
            "symbol": "SPY",
            "reason": "Accelerated episodes shorten calendar time, but promotion still requires 100 completed episodes, 10 trading days, 30 chronological holdout episodes, and human review.",
            "eligible_challengers": [row["symbol"] for row in challenger_leaderboard if row["promotion_eligible"]],
        },
        "top_trades": trades[:25],
        "research_top_trades": research_trades[:25],
        "promotion_note": "Schema-v3 uses entry-ask/exit-bid returns and requires 100 completed episodes, 10 trading days, at least 30 chronological holdout episodes, positive full/holdout expectancy, controlled losses, complete executable-quote coverage, and human approval. Same-day episodes are not treated as extra trading days.",
        "warnings": [
            "Read-only evaluator. No broker calls are made.",
            "Promotion evidence uses entry ask and exit bid when complete quotes exist; incomplete quote paths remain shadow-only.",
            "Bid/ask reconstruction still does not guarantee fills or model market impact.",
            "Do not promote TSLA/QQQ/IWM/NVDA from one viral screenshot or one large day.",
            "Directional-conflict exits are counterfactual shadow observations only and require at least 10 completed observations before review.",
            "The 15-minute ORB and level-sweep challengers are isolated from symbol promotion, selector ranking, and primary accelerated counts.",
        ],
    }


def write_report(report: dict[str, Any], report_path: Path = REPORT_PATH) -> Path:
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return report_path


def append_log(report: dict[str, Any], log_path: Path = EVAL_LOG_PATH) -> None:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(report, separators=(",", ":"), sort_keys=True) + "\n")


def print_report(report: dict[str, Any]) -> None:
    print("\nFlip Shadow P&L Evaluator | read-only")
    print("=" * 72)
    print(
        f"date={report.get('date') or 'all'} samples={report['sample_count']} "
        f"completed={report['completed_count']} win_rate={report['win_rate']} "
        f"hyp_pnl=${report['total_hypothetical_pnl']}"
    )
    for trade in report["top_trades"][:8]:
        print(
            f"{trade['symbol']:5} {trade['right']:4} {trade['option_symbol']:24} "
            f"entry={trade['entry_price']:.2f} best={trade['best_price']:.2f} "
            f"ret={trade['return_pct']:.1f}% pnl=${trade['hypothetical_pnl']:.2f} "
            f"{trade['status']}"
        )
    print("No orders placed. No settings changed.\n")


def main() -> int:
    parser = argparse.ArgumentParser(description="Evaluate Flip Bot shadow candidate hypothetical P&L.")
    parser.add_argument("--date", default=None, help="Optional YYYY-MM-DD; omit for all trusted history.")
    parser.add_argument("--log-path", type=Path, default=LOG_PATH)
    parser.add_argument("--report-path", type=Path, default=REPORT_PATH)
    parser.add_argument("--eval-log-path", type=Path, default=EVAL_LOG_PATH)
    parser.add_argument("--print", action="store_true", dest="do_print")
    args = parser.parse_args()
    report = build_report(log_path=args.log_path, day=args.date)
    write_report(report, args.report_path)
    append_log(report, args.eval_log_path)
    if args.do_print:
        print_report(report)
    else:
        print(f"Flip shadow P&L evaluation written to {args.report_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

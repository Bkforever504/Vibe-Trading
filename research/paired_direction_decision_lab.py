#!/usr/bin/env python3
"""Replay CALL, PUT, or abstain at the same shadow decision point.

The lab pairs resolved call and put lifecycles by date, symbol, and episode
bucket. Static pre-entry decision rules are compared with a hindsight oracle,
with spread-aware returns, doubled costs, winner removal, and date-clustering
checks. Read-only; no result can enable execution.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
import math
from pathlib import Path
from typing import Any, Callable

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from research import options_exit_policy_lab as exit_lab

DEFAULT_CANDIDATES_PATH = exit_lab.DEFAULT_CANDIDATES_PATH
DEFAULT_OUTPUT_PATH = ROOT / "data" / "paired_direction_decision_lab_results.json"
DEFAULT_FEE_PCT = exit_lab.DEFAULT_FEE_PER_CONTRACT_PCT
MIN_TRIGGERED_TRADES = 100
MIN_TRIGGERED_DATES = 20
MAX_POSITIVE_GROSS_DATE_SHARE = 0.30
MAX_CAUSAL_ENTRY_SKEW_SECONDS = 5.0
MAX_CAUSAL_QUOTE_SKEW_SECONDS = 2.0
MAX_CAUSAL_QUOTE_AGE_SECONDS = 15.0
SELECTOR_MIN_TRAIN_DATES = 10
SELECTOR_MIN_NEIGHBOR_DATES = 5
SELECTOR_MIN_NEIGHBORS = 30
SELECTOR_MIN_SIMILARITY = 0.60
SELECTOR_MAX_NEIGHBORS = 100
SELECTOR_LCB_Z = 1.28
SELECTOR_MIN_ACTION_MARGIN_PCT = 2.0


def _pick(rows: list[exit_lab.Lifecycle]) -> exit_lab.Lifecycle:
    return next((life for life in rows if life.strategy == "0dte"), rows[0])


def _parse_timestamp(value: str) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(str(value or "").replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed.replace(tzinfo=timezone.utc) if parsed.tzinfo is None else parsed.astimezone(timezone.utc)


def _timestamp_skew_seconds(left: str, right: str) -> float | None:
    left_at = _parse_timestamp(left)
    right_at = _parse_timestamp(right)
    return abs((left_at - right_at).total_seconds()) if left_at and right_at else None


def _pair_record(
    day: str,
    symbol: str,
    bucket: str,
    group: list[exit_lab.Lifecycle],
    *,
    pair_id: str,
    explicit: bool,
) -> dict[str, Any] | None:
    calls = [life for life in group if life.right == "CALL"]
    puts = [life for life in group if life.right == "PUT"]
    if not calls or not puts:
        return None
    call = _pick(calls)
    put = _pick(puts)
    context_life = next(
        (life for life in (call, put) if life.decision_lattice_role == "source_direction"),
        max((call, put), key=lambda life: len(life.features)),
    )
    entry_skew = _timestamp_skew_seconds(call.entry_at, put.entry_at)
    quote_skew = _timestamp_skew_seconds(call.entry_quote_timestamp, put.entry_quote_timestamp)
    quote_ages = [
        age for age in (call.entry_quote_age_seconds, put.entry_quote_age_seconds)
        if age is not None and math.isfinite(age)
    ]
    synchronized = (
        explicit
        and call.pair_sync_status == "synchronized_forward"
        and put.pair_sync_status == "synchronized_forward"
        and call.pair_construction_method == "symmetric_log_moneyness_single_snapshot"
        and put.pair_construction_method == "symmetric_log_moneyness_single_snapshot"
        and entry_skew is not None
        and entry_skew <= MAX_CAUSAL_ENTRY_SKEW_SECONDS
        and quote_skew is not None
        and quote_skew <= MAX_CAUSAL_QUOTE_SKEW_SECONDS
        and len(quote_ages) == 2
        and max(quote_ages) <= MAX_CAUSAL_QUOTE_AGE_SECONDS
    )
    if synchronized:
        quality = "synchronized_forward"
    elif explicit:
        quality = "explicit_pair_failed_sync_quality"
    elif entry_skew is not None and entry_skew <= MAX_CAUSAL_ENTRY_SKEW_SECONDS:
        quality = "legacy_same_timestamp_unmatched_contracts"
    else:
        quality = "legacy_bucket_approximate"
    return {
        "pair_id": pair_id,
        "date": day,
        "symbol": symbol,
        "episode_bucket_et": bucket,
        "call": call,
        "put": put,
        "features": context_life.features,
        "day_type": context_life.day_type,
        "pair_quality": quality,
        "eligible_for_causal_review": synchronized,
        "entry_time_skew_seconds": round(entry_skew, 3) if entry_skew is not None else None,
        "quote_time_skew_seconds": round(quote_skew, 3) if quote_skew is not None else None,
        "maximum_quote_age_seconds": round(max(quote_ages), 3) if len(quote_ages) == 2 else None,
    }


def build_pairs(lives: list[exit_lab.Lifecycle]) -> list[dict[str, Any]]:
    explicit_groups: dict[str, list[exit_lab.Lifecycle]] = defaultdict(list)
    legacy_groups: dict[tuple[str, str, str], list[exit_lab.Lifecycle]] = defaultdict(list)
    for life in lives:
        if life.decision_pair_id:
            explicit_groups[life.decision_pair_id].append(life)
        elif life.episode_bucket_et:
            legacy_groups[(life.date, life.symbol, life.episode_bucket_et)].append(life)
    pairs: list[dict[str, Any]] = []
    for pair_id, group in sorted(explicit_groups.items()):
        first = group[0]
        row = _pair_record(
            first.date,
            first.symbol,
            first.episode_bucket_et,
            group,
            pair_id=pair_id,
            explicit=True,
        )
        if row:
            pairs.append(row)
    for (day, symbol, bucket), group in sorted(legacy_groups.items()):
        calls = [life for life in group if life.right == "CALL"]
        puts = [life for life in group if life.right == "PUT"]
        if not calls or not puts:
            continue
        row = _pair_record(
            day,
            symbol,
            bucket,
            group,
            pair_id=f"legacy|{day}|{symbol}|{bucket}",
            explicit=False,
        )
        if row:
            pairs.append(row)
    return pairs


def _vote_score(features: dict[str, Any]) -> int:
    score = 0
    market_force = features.get("market_force_classification")
    if market_force == "bullish_lean":
        score += 2
    elif market_force == "bearish_lean":
        score -= 2
    htf = features.get("htf_primary_bias")
    if htf == "bullish":
        score += 2
    elif htf == "bearish":
        score -= 2
    for key in ("above_vwap", "above_ema50", "ema50_sloping_up", "green_session", "ttm_momentum_rising"):
        score += int(features.get(key) is True)
    for key in ("below_vwap", "below_ema50", "ema50_sloping_down", "red_session"):
        score -= int(features.get(key) is True)
    return score


DecisionRule = Callable[[dict[str, Any]], str]

RULES: dict[str, DecisionRule] = {
    "always_call": lambda _features: "CALL",
    "always_put": lambda _features: "PUT",
    "market_force": lambda f: (
        "CALL" if f.get("market_force_classification") == "bullish_lean"
        else "PUT" if f.get("market_force_classification") == "bearish_lean"
        else "NONE"
    ),
    "htf_bias": lambda f: (
        "CALL" if f.get("htf_primary_bias") == "bullish"
        else "PUT" if f.get("htf_primary_bias") == "bearish"
        else "NONE"
    ),
    "structure_vote": lambda f: "CALL" if _vote_score(f) >= 2 else "PUT" if _vote_score(f) <= -2 else "NONE",
    "strict_complete_structure": lambda f: (
        ("CALL" if _vote_score(f) >= 3 else "PUT" if _vote_score(f) <= -3 else "NONE")
        if f.get("market_context_snapshot_status") == "complete"
        and f.get("candlestick_context_status") == "current"
        else "NONE"
    ),
}

SELECTOR_FEATURES = (
    "market_force_classification",
    "htf_primary_bias",
    "htf_intraday_alignment",
    "above_vwap",
    "below_vwap",
    "above_ema50",
    "below_ema50",
    "ema50_sloping_up",
    "ema50_sloping_down",
    "green_session",
    "red_session",
    "ttm_state",
    "ttm_momentum_rising",
    "orb_direction",
    "orb_retest_status",
    "retest_grade",
    "candlestick_bias",
    "candlestick_context_status",
    "market_context_snapshot_status",
)


def _context_signature(pair: dict[str, Any]) -> dict[str, str]:
    features = pair.get("features") or {}
    signature: dict[str, str] = {}
    for key in SELECTOR_FEATURES:
        value = features.get(key)
        if isinstance(value, bool):
            signature[key] = "true" if value else "false"
        elif isinstance(value, str) and value.strip():
            signature[key] = value.strip().lower()
    day_type = pair.get("day_type")
    if isinstance(day_type, str) and day_type:
        signature["day_type"] = day_type.lower()
    bucket = str(pair.get("episode_bucket_et") or "")
    if bucket:
        signature["episode_half_hour"] = bucket[:4]
    return signature


def _context_similarity(left: dict[str, str], right: dict[str, str]) -> float:
    shared = set(left).intersection(right)
    if len(shared) < 3:
        return 0.0
    return sum(left[key] == right[key] for key in shared) / len(shared)


def _neighbor_action_estimate(
    training: list[dict[str, Any]],
    target: dict[str, Any],
    action: str,
    fee_pct: float,
) -> dict[str, Any] | None:
    signature = _context_signature(target)
    neighbors = []
    for pair in training:
        similarity = _context_similarity(signature, _context_signature(pair))
        if similarity >= SELECTOR_MIN_SIMILARITY:
            neighbors.append((similarity, pair))
    neighbors.sort(key=lambda row: row[0], reverse=True)
    neighbors = neighbors[:SELECTOR_MAX_NEIGHBORS]
    if len(neighbors) < SELECTOR_MIN_NEIGHBORS:
        return None
    by_date: dict[str, list[tuple[float, float]]] = defaultdict(list)
    for similarity, pair in neighbors:
        life = pair["call"] if action == "CALL" else pair["put"]
        by_date[pair["date"]].append((_life_return(life, fee_pct), similarity))
    if len(by_date) < SELECTOR_MIN_NEIGHBOR_DATES:
        return None
    date_means = [
        sum(value * weight for value, weight in values) / sum(weight for _value, weight in values)
        for values in by_date.values()
    ]
    mean = sum(date_means) / len(date_means)
    if len(date_means) > 1:
        variance = sum((value - mean) ** 2 for value in date_means) / (len(date_means) - 1)
        standard_error = math.sqrt(variance / len(date_means))
    else:
        standard_error = math.inf
    return {
        "expected_return_pct": round(mean, 4),
        "lower_confidence_bound_pct": round(mean - SELECTOR_LCB_Z * standard_error, 4),
        "neighbor_count": len(neighbors),
        "neighbor_dates": len(by_date),
        "average_similarity": round(sum(row[0] for row in neighbors) / len(neighbors), 4),
    }


def evaluate_walk_forward_context_selector(
    pairs: list[dict[str, Any]],
    *,
    fee_pct: float = DEFAULT_FEE_PCT,
) -> dict[str, Any]:
    """Choose CALL/PUT/NONE using nearest prior-date contexts and a return LCB."""
    rows: list[dict[str, Any]] = []
    dates = sorted({pair["date"] for pair in pairs})
    for day in dates:
        training = [pair for pair in pairs if pair["date"] < day]
        train_dates = len({pair["date"] for pair in training})
        for pair in (row for row in pairs if row["date"] == day):
            call_return = _life_return(pair["call"], fee_pct)
            put_return = _life_return(pair["put"], fee_pct)
            estimates: dict[str, Any] = {}
            action = "NONE"
            reason = f"insufficient_prior_dates_{train_dates}/{SELECTOR_MIN_TRAIN_DATES}"
            if train_dates >= SELECTOR_MIN_TRAIN_DATES:
                for candidate in ("CALL", "PUT"):
                    estimate = _neighbor_action_estimate(training, pair, candidate, fee_pct)
                    if estimate:
                        estimates[candidate] = estimate
                if len(estimates) == 2:
                    best = max(estimates, key=lambda candidate: estimates[candidate]["expected_return_pct"])
                    other = "PUT" if best == "CALL" else "CALL"
                    margin = (
                        estimates[best]["expected_return_pct"]
                        - estimates[other]["expected_return_pct"]
                    )
                    if (
                        estimates[best]["lower_confidence_bound_pct"] > 0
                        and margin >= SELECTOR_MIN_ACTION_MARGIN_PCT
                    ):
                        action = best
                        reason = "positive_lcb_and_action_margin"
                    else:
                        reason = "uncertainty_or_action_margin_not_cleared"
                else:
                    reason = "insufficient_context_neighbors"
            selected = call_return if action == "CALL" else put_return if action == "PUT" else 0.0
            rows.append({
                "pair_id": pair["pair_id"],
                "date": day,
                "symbol": pair["symbol"],
                "action": action,
                "selection_reason": reason,
                "return_pct": selected,
                "call_return_pct": call_return,
                "put_return_pct": put_return,
                "prior_training_dates": train_dates,
                "estimates": estimates,
            })
    triggered = [row for row in rows if row["action"] != "NONE"]
    metrics = exit_lab._cohort_metrics([row["return_pct"] for row in triggered])
    doubled = exit_lab._cohort_metrics([row["return_pct"] - fee_pct for row in triggered])
    top_removed = exit_lab._cohort_metrics(_drop_top_triggered(triggered))
    concentration = _positive_date_concentration(triggered)
    triggered_dates = len({row["date"] for row in triggered})
    failed = []
    if len(triggered) < MIN_TRIGGERED_TRADES:
        failed.append(f"insufficient_triggered_trades_{len(triggered)}/{MIN_TRIGGERED_TRADES}")
    if triggered_dates < MIN_TRIGGERED_DATES:
        failed.append(f"insufficient_triggered_dates_{triggered_dates}/{MIN_TRIGGERED_DATES}")
    if metrics.get("expectancy_pct", 0) <= 0:
        failed.append("triggered_expectancy_not_positive")
    if doubled.get("expectancy_pct", 0) <= 0:
        failed.append("doubled_cost_expectancy_not_positive")
    if top_removed.get("expectancy_pct", 0) <= 0:
        failed.append("top_winner_removed_expectancy_not_positive")
    date_share = concentration.get("best_date_share_of_positive_gross")
    if date_share is None or date_share > MAX_POSITIVE_GROSS_DATE_SHARE:
        failed.append("positive_returns_too_concentrated_by_date")
    return {
        "selector": "prior_date_context_neighbors_positive_lcb",
        "selection_is_strictly_walk_forward": True,
        "paired_signals": len(rows),
        "triggered_trades": len(triggered),
        "triggered_dates": triggered_dates,
        "participation_rate": round(len(triggered) / len(rows), 4) if rows else 0.0,
        "action_counts": dict(Counter(row["action"] for row in rows)),
        "triggered_metrics": metrics,
        "doubled_cost_triggered_metrics": doubled,
        "top5pct_winners_removed_metrics": top_removed,
        "date_concentration": concentration,
        "review_gate": {"passed": not failed, "failed_checks": failed},
        "preregistered_parameters": {
            "minimum_train_dates": SELECTOR_MIN_TRAIN_DATES,
            "minimum_neighbors": SELECTOR_MIN_NEIGHBORS,
            "minimum_neighbor_dates": SELECTOR_MIN_NEIGHBOR_DATES,
            "minimum_similarity": SELECTOR_MIN_SIMILARITY,
            "maximum_neighbors": SELECTOR_MAX_NEIGHBORS,
            "lower_confidence_z": SELECTOR_LCB_Z,
            "minimum_action_margin_pct": SELECTOR_MIN_ACTION_MARGIN_PCT,
        },
        "outcomes": rows,
    }


def _life_return(life: exit_lab.Lifecycle, fee_pct: float) -> float:
    return round(exit_lab.POLICIES["baseline_current"](life)[0] - fee_pct, 4)


def _positive_date_concentration(rows: list[dict[str, Any]]) -> dict[str, Any]:
    by_date: dict[str, float] = defaultdict(float)
    for row in rows:
        by_date[row["date"]] += max(0.0, row["return_pct"])
    gross = sum(by_date.values())
    best_date, best_value = max(by_date.items(), key=lambda item: item[1], default=(None, 0.0))
    return {
        "positive_gross_pct": round(gross, 4),
        "best_positive_date": best_date,
        "best_positive_date_gross_pct": round(best_value, 4),
        "best_date_share_of_positive_gross": round(best_value / gross, 4) if gross > 0 else None,
    }


def _drop_top_triggered(rows: list[dict[str, Any]], pct: float = 5.0) -> list[float]:
    values = sorted(row["return_pct"] for row in rows if row["action"] != "NONE")
    if not values:
        return []
    count = max(1, int(len(values) * pct / 100.0))
    return values[:-count] if count < len(values) else []


def evaluate_rule(
    name: str,
    rule: DecisionRule,
    pairs: list[dict[str, Any]],
    *,
    fee_pct: float = DEFAULT_FEE_PCT,
) -> dict[str, Any]:
    rows = []
    for pair in pairs:
        call_return = _life_return(pair["call"], fee_pct)
        put_return = _life_return(pair["put"], fee_pct)
        action = rule(pair["features"])
        selected = call_return if action == "CALL" else put_return if action == "PUT" else 0.0
        rows.append({
            "pair_id": pair["pair_id"],
            "date": pair["date"],
            "symbol": pair["symbol"],
            "episode_bucket_et": pair["episode_bucket_et"],
            "action": action,
            "return_pct": selected,
            "call_return_pct": call_return,
            "put_return_pct": put_return,
            "oracle_action": "CALL" if call_return >= max(0.0, put_return) else "PUT" if put_return > 0 else "NONE",
            "oracle_return_pct": max(0.0, call_return, put_return),
            "direction_correct": action != "NONE" and selected == max(call_return, put_return) and selected > 0,
        })
    triggered = [row for row in rows if row["action"] != "NONE"]
    signal_returns = [row["return_pct"] for row in rows]
    triggered_returns = [row["return_pct"] for row in triggered]
    doubled = [row["return_pct"] - fee_pct for row in triggered]
    concentration = _positive_date_concentration(triggered)
    metrics = exit_lab._cohort_metrics(triggered_returns)
    doubled_metrics = exit_lab._cohort_metrics(doubled)
    top_removed = exit_lab._cohort_metrics(_drop_top_triggered(triggered))
    triggered_dates = len({row["date"] for row in triggered})
    failed = []
    if len(triggered) < MIN_TRIGGERED_TRADES:
        failed.append(f"insufficient_triggered_trades_{len(triggered)}/{MIN_TRIGGERED_TRADES}")
    if triggered_dates < MIN_TRIGGERED_DATES:
        failed.append(f"insufficient_triggered_dates_{triggered_dates}/{MIN_TRIGGERED_DATES}")
    if metrics.get("expectancy_pct", 0) <= 0:
        failed.append("triggered_expectancy_not_positive")
    if doubled_metrics.get("expectancy_pct", 0) <= 0:
        failed.append("doubled_cost_expectancy_not_positive")
    if top_removed.get("expectancy_pct", 0) <= 0:
        failed.append("top_winner_removed_expectancy_not_positive")
    date_share = concentration.get("best_date_share_of_positive_gross")
    if date_share is None or date_share > MAX_POSITIVE_GROSS_DATE_SHARE:
        failed.append("positive_returns_too_concentrated_by_date")
    return {
        "rule": name,
        "paired_signals": len(rows),
        "triggered_trades": len(triggered),
        "triggered_dates": triggered_dates,
        "participation_rate": round(len(triggered) / len(rows), 4) if rows else 0.0,
        "action_counts": dict(Counter(row["action"] for row in rows)),
        "per_signal_metrics": exit_lab._cohort_metrics(signal_returns),
        "triggered_metrics": metrics,
        "doubled_cost_triggered_metrics": doubled_metrics,
        "top5pct_winners_removed_metrics": top_removed,
        "date_concentration": concentration,
        "direction_accuracy_when_triggered": round(
            sum(row["direction_correct"] for row in triggered) / len(triggered), 4
        ) if triggered else None,
        "review_gate": {"passed": not failed, "failed_checks": failed},
        "outcomes": rows,
    }


def _skew_summary(pairs: list[dict[str, Any]], key: str) -> dict[str, Any]:
    values = sorted(
        float(pair[key]) for pair in pairs
        if pair.get(key) is not None and math.isfinite(float(pair[key]))
    )
    if not values:
        return {"count": 0, "median_seconds": None, "p95_seconds": None, "maximum_seconds": None}
    p95_index = min(len(values) - 1, math.ceil(len(values) * 0.95) - 1)
    return {
        "count": len(values),
        "median_seconds": round(values[len(values) // 2], 3),
        "p95_seconds": round(values[p95_index], 3),
        "maximum_seconds": round(values[-1], 3),
    }


def opportunity_surface(
    pairs: list[dict[str, Any]],
    *,
    fee_pct: float = DEFAULT_FEE_PCT,
) -> dict[str, Any]:
    categories = Counter()
    oracle: list[float] = []
    calls: list[float] = []
    puts: list[float] = []
    direction_spreads: list[float] = []
    for pair in pairs:
        call_return = _life_return(pair["call"], fee_pct)
        put_return = _life_return(pair["put"], fee_pct)
        calls.append(call_return)
        puts.append(put_return)
        oracle.append(max(0.0, call_return, put_return))
        direction_spreads.append(abs(call_return - put_return))
        if call_return > 0 and put_return > 0:
            categories["both_profitable"] += 1
        elif call_return > 0:
            categories["call_only_profitable"] += 1
        elif put_return > 0:
            categories["put_only_profitable"] += 1
        else:
            categories["neither_profitable"] += 1
    total = len(pairs)
    best_static = max(
        exit_lab._cohort_metrics(calls).get("expectancy_pct", 0.0),
        exit_lab._cohort_metrics(puts).get("expectancy_pct", 0.0),
        0.0,
    )
    oracle_expectancy = exit_lab._cohort_metrics(oracle).get("expectancy_pct", 0.0)
    return {
        "paired_signals": total,
        "category_counts": dict(categories),
        "category_rates": {
            key: round(categories.get(key, 0) / total, 4) if total else 0.0
            for key in (
                "call_only_profitable", "put_only_profitable",
                "both_profitable", "neither_profitable",
            )
        },
        "tradable_move_available_rate": round(
            sum(value > 0 for value in oracle) / total, 4
        ) if total else 0.0,
        "oracle_hindsight_metrics": exit_lab._cohort_metrics(oracle),
        "best_static_direction_expectancy_pct": round(best_static, 4),
        "hindsight_direction_selection_value_pct": round(oracle_expectancy - best_static, 4),
        "average_absolute_call_put_return_gap_pct": round(
            sum(direction_spreads) / total, 4
        ) if total else None,
        "execution_authority": "none_hindsight_decomposition_only",
    }


def build_report(
    candidates_path: Path = DEFAULT_CANDIDATES_PATH,
    *,
    fee_pct: float = DEFAULT_FEE_PCT,
) -> dict[str, Any]:
    lives = exit_lab.load_lifecycles(candidates_path)
    all_pairs = build_pairs(lives)
    pairs = [pair for pair in all_pairs if pair["eligible_for_causal_review"]]
    legacy_pairs = [pair for pair in all_pairs if not pair["eligible_for_causal_review"]]
    rule_reports = [evaluate_rule(name, rule, pairs, fee_pct=fee_pct) for name, rule in RULES.items()]
    legacy_rule_reports = [
        evaluate_rule(name, rule, legacy_pairs, fee_pct=fee_pct)
        for name, rule in RULES.items()
    ]
    oracle = [
        max(0.0, _life_return(pair["call"], fee_pct), _life_return(pair["put"], fee_pct))
        for pair in pairs
    ]
    legacy_oracle = [
        max(0.0, _life_return(pair["call"], fee_pct), _life_return(pair["put"], fee_pct))
        for pair in legacy_pairs
    ]
    rule_reports.sort(
        key=lambda row: row["per_signal_metrics"].get("expectancy_pct", float("-inf")), reverse=True
    )
    legacy_rule_reports.sort(
        key=lambda row: row["per_signal_metrics"].get("expectancy_pct", float("-inf")), reverse=True
    )
    return {
        "provider": "paired_direction_decision_lab",
        "mode": "read_only_call_put_abstain_replay",
        "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "execution_enabled": False,
        "can_submit_orders": False,
        "automatic_parameter_changes": False,
        "candidates_path": str(candidates_path),
        "resolved_lifecycles": len(lives),
        "all_candidate_pairs": len(all_pairs),
        "paired_decision_points": len(pairs),
        "paired_dates": len({pair["date"] for pair in pairs}),
        "pair_quality_audit": {
            "counts": dict(Counter(pair["pair_quality"] for pair in all_pairs)),
            "entry_time_skew": _skew_summary(all_pairs, "entry_time_skew_seconds"),
            "quote_time_skew": _skew_summary(all_pairs, "quote_time_skew_seconds"),
            "causal_review_requires": {
                "explicit_pair_id": True,
                "construction_method": "symmetric_log_moneyness_single_snapshot",
                "maximum_entry_skew_seconds": MAX_CAUSAL_ENTRY_SKEW_SECONDS,
                "maximum_quote_skew_seconds": MAX_CAUSAL_QUOTE_SKEW_SECONDS,
                "maximum_quote_age_seconds": MAX_CAUSAL_QUOTE_AGE_SECONDS,
            },
        },
        "oracle_hindsight_ceiling": {
            "metrics": exit_lab._cohort_metrics(oracle),
            "execution_authority": "none_hindsight_only",
        },
        "opportunity_surface": opportunity_surface(pairs, fee_pct=fee_pct),
        "rules_ranked": rule_reports,
        "walk_forward_context_selector": evaluate_walk_forward_context_selector(
            pairs,
            fee_pct=fee_pct,
        ),
        "legacy_approximate_pair_diagnostic": {
            "pair_count": len(legacy_pairs),
            "dates": len({pair["date"] for pair in legacy_pairs}),
            "oracle_hindsight_ceiling": exit_lab._cohort_metrics(legacy_oracle),
            "opportunity_surface": opportunity_surface(legacy_pairs, fee_pct=fee_pct),
            "rules_ranked": legacy_rule_reports,
            "execution_authority": "none_not_synchronized_or_moneyness_matched",
        },
        "promotion_authority": "none_requires_new_forward_paired_dates",
        "notes": [
            "Abstention returns zero and pays no transaction cost.",
            "Causal review uses only explicit, synchronized, symmetric-log-moneyness pairs.",
            "Legacy time-bucket pairs are retained as diagnostics but cannot support promotion.",
            "Call and put returns use each contract's recorded lifecycle and executable bid exits.",
            "The oracle sees future outcomes and is diagnostic only.",
            "Date concentration prevents one exceptional session from being called an edge.",
            "The context selector trains on prior dates only and abstains unless its lower confidence bound is positive.",
        ],
    }


def write_report(report: dict[str, Any], path: Path = DEFAULT_OUTPUT_PATH) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(temp, path)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidates", type=Path, default=DEFAULT_CANDIDATES_PATH)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUTPUT_PATH)
    parser.add_argument("--fee-pct", type=float, default=DEFAULT_FEE_PCT)
    args = parser.parse_args()
    report = build_report(args.candidates, fee_pct=args.fee_pct)
    write_report(report, args.out)
    print(json.dumps({
        "paired_decision_points": report["paired_decision_points"],
        "paired_dates": report["paired_dates"],
        "pair_quality_audit": report["pair_quality_audit"],
        "oracle_hindsight_ceiling": report["oracle_hindsight_ceiling"],
        "walk_forward_context_selector": {
            key: report["walk_forward_context_selector"][key]
            for key in (
                "triggered_trades", "triggered_dates", "participation_rate",
                "triggered_metrics", "review_gate",
            )
        },
        "rules": [
            {key: row[key] for key in (
                "rule", "triggered_trades", "triggered_dates", "participation_rate",
                "per_signal_metrics", "triggered_metrics", "doubled_cost_triggered_metrics",
                "top5pct_winners_removed_metrics", "date_concentration", "review_gate",
            )}
            for row in report["rules_ranked"]
        ],
        "report": str(args.out),
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

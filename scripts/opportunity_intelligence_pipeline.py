#!/usr/bin/env python3
"""Read-only opportunity allocation, evidence, and operations report.

This module intentionally has no broker client and no order path. It turns the
existing strategy/shadow artifacts into a synchronized daily research ledger.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import random
import sys
from collections import defaultdict
from datetime import datetime, timezone
from itertools import combinations
from pathlib import Path
from statistics import mean
from typing import Any, Iterable

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.filter_counterfactual_attribution import build_report as build_gate_report
from scripts.probability_calibration import probability_metrics


DATA = ROOT / "data"
VIBE_HOME = Path.home() / ".vibe-trading"
DEFAULT_LEDGER = DATA / "opportunity_intelligence_ledger.jsonl"
DEFAULT_OUTPUT = DATA / "opportunity_intelligence_report.json"
PROTOCOL = "research/OPPORTUNITY_INTELLIGENCE_PROTOCOL_2026-08-19.md"
SCHEMA_VERSION = 3
MIN_DECAY_OBSERVATIONS = 30
RECENT_DECAY_WINDOW = 20
MAX_LANE_WEIGHT = 0.35
PLACEBO_PATHS = 5000
RNG_SEED = 20260819
MIN_DEPENDENCE_OVERLAP = 20
MIN_EXECUTION_REALITY_SAMPLES = 10
RECOVERY_REVIEWS_REQUIRED = 2
DEPENDENCE_CORRELATION_LIMIT = 0.65
LOSS_EVENT_CORRELATION_LIMIT = 0.35
JOINT_LOSS_LIFT_LIMIT = 1.50
FINGERPRINT_PATHS = (
    "research/OPPORTUNITY_INTELLIGENCE_PROTOCOL_2026-08-19.md",
    "research/ALGO_OPERATIONS_OVERHAUL_2026-08-19.md",
    "scripts/opportunity_intelligence_pipeline.py",
    "scripts/options_shadow_twin.py",
    "strategies/flip_bot.py",
)
LANE_REVIEW_BLOCKS = {
    "qqq_mean_reversion": "development_only_failed_experiment_wide_multiple_testing",
    "mes_reopen_drift": "retrospective_only_independent_bootstrap_crosses_zero",
}


def _read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return rows
    for line in lines:
        try:
            value = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            rows.append(value)
    return rows


def _latest_jsonl(path: Path) -> dict[str, Any]:
    rows = _read_jsonl(path)
    return rows[-1] if rows else {}


def _finite(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _percentile(values: list[float], quantile: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    position = (len(ordered) - 1) * quantile
    lower = int(math.floor(position))
    upper = int(math.ceil(position))
    if lower == upper:
        return ordered[lower]
    weight = position - lower
    return ordered[lower] * (1.0 - weight) + ordered[upper] * weight


def _max_drawdown(values: Iterable[float]) -> float:
    equity = 0.0
    peak = 0.0
    maximum = 0.0
    for value in values:
        equity += float(value)
        peak = max(peak, equity)
        maximum = max(maximum, peak - equity)
    return maximum


def _profit_factor(values: list[float]) -> float | None:
    gains = sum(value for value in values if value > 0)
    losses = abs(sum(value for value in values if value <= 0))
    return gains / losses if losses else None


def _bootstrap_mean(values: list[float], *, paths: int = 4000, block: int = 5) -> dict[str, Any]:
    if len(values) < 10:
        return {"status": "insufficient_n", "samples": len(values), "ci90": [None, None]}
    rng = random.Random(RNG_SEED)
    means: list[float] = []
    for _ in range(paths):
        drawn: list[float] = []
        while len(drawn) < len(values):
            start = rng.randrange(len(values))
            drawn.extend(values[(start + offset) % len(values)] for offset in range(block))
        means.append(mean(drawn[: len(values)]))
    return {
        "status": "ok",
        "samples": len(values),
        "paths": paths,
        "block": block,
        "ci90": [round(float(_percentile(means, 0.05)), 4), round(float(_percentile(means, 0.95)), 4)],
    }


def placebo_test(values: list[float], *, paths: int = PLACEBO_PATHS) -> dict[str, Any]:
    """Test the observed mean against a seeded random sign-flip null."""
    if len(values) < 20:
        return {"status": "insufficient_n", "observations": len(values), "p_value": None}
    observed = mean(values)
    rng = random.Random(RNG_SEED + 17)
    null_means = [mean([value if rng.random() >= 0.5 else -value for value in values]) for _ in range(paths)]
    p_value = (1 + sum(value >= observed for value in null_means)) / (paths + 1)
    return {
        "status": "pass" if observed > 0 and p_value <= 0.05 else "fail",
        "method": "seeded_random_sign_flip_zero_location_null",
        "observations": len(values),
        "paths": paths,
        "observed_mean": round(observed, 4),
        "reverse_direction_mean": round(-observed, 4),
        "null_mean_p95": round(float(_percentile(null_means, 0.95)), 4),
        "one_sided_p_value": round(p_value, 6),
        "limitation": "Sign-flip inference assumes exchangeable trade signs and does not prove causal market structure.",
    }


def edge_decay(values: list[float]) -> dict[str, Any]:
    if len(values) < MIN_DECAY_OBSERVATIONS:
        return {"status": "insufficient_n", "observations": len(values), "research_allocation_allowed": False}
    recent = values[-RECENT_DECAY_WINDOW:]
    prior = values[:-RECENT_DECAY_WINDOW]
    recent_mean = mean(recent)
    prior_mean = mean(prior)
    non_positive = recent_mean <= 0
    collapsed = prior_mean > 0 and recent_mean < 0.5 * prior_mean
    status = "suspend" if non_positive and collapsed else "watch" if non_positive or collapsed else "stable"
    return {
        "status": status,
        "observations": len(values),
        "recent_window": RECENT_DECAY_WINDOW,
        "prior_mean": round(prior_mean, 4),
        "recent_mean": round(recent_mean, 4),
        "recent_to_prior_ratio": round(recent_mean / prior_mean, 4) if prior_mean else None,
        "recent_profit_factor": round(_profit_factor(recent), 4) if _profit_factor(recent) is not None else None,
        "research_allocation_allowed": status != "suspend",
    }


def expanding_probability_calibration(series: list[dict[str, Any]]) -> dict[str, Any]:
    samples: list[dict[str, Any]] = []
    wins = 1
    total = 2
    for row in sorted(series, key=lambda value: str(value.get("date") or "")):
        pnl = _finite(row.get("pnl"))
        if pnl is None:
            continue
        samples.append({
            "timestamp": f"{row['date']}T21:00:00+00:00",
            "probability": wins / total,
            "outcome": int(pnl > 0),
        })
        wins += int(pnl > 0)
        total += 1
    result = probability_metrics(samples)
    result["method"] = "expanding_laplace_smoothed_base_rate_frozen_before_each_outcome"
    result["authority"] = "read_only_retrospective_diagnostic"
    return result


def _qqq_history(root: Path) -> list[dict[str, Any]]:
    from research.qqq_mean_reversion_challenger_lab import (
        BASE_COST,
        DATA_PATH,
        DEVELOPMENT_END,
        VARIANTS,
        prepare_frame,
        simulate,
    )
    import pandas as pd

    path = root / DATA_PATH.relative_to(ROOT)
    full = pd.read_parquet(path).sort_index()
    full.index = pd.to_datetime(full.index)
    frame = prepare_frame(full.loc[:DEVELOPMENT_END])
    variant = next(value for value in VARIANTS if value.name == "rsi2_exit_prior_high")
    return [
        {
            "date": trade["exit_date"],
            "pnl": float(trade["gross_pnl"]) - BASE_COST * float(trade["exposure"]),
            "source": "development_only_qqq_rsi2_exit_prior_high",
        }
        for trade in simulate(frame, variant)
    ]


def _mes_history(root: Path) -> list[dict[str, Any]]:
    from research.mes_overnight_holdout import fetch_vix, load_mes
    from research.mes_reopen_vix_holdout import build_trades

    original_root = ROOT
    if root != original_root:
        return []
    trades = build_trades(load_mes(), fetch_vix())
    return [
        {"date": index.date().isoformat(), "pnl": float(row["net_dollar"]), "source": "retrospective_mes_reopen_vix"}
        for index, row in trades.iterrows()
    ]


def _options_history(root: Path) -> list[dict[str, Any]]:
    rows = _read_jsonl(root / "data" / "options_shadow_twin_log.jsonl")
    candidates = {str(row.get("candidate_id")): row for row in rows if row.get("type") == "candidate"}
    output: list[dict[str, Any]] = []
    for row in rows:
        if row.get("type") != "outcome":
            continue
        pnl = _finite(row.get("pnl_before_fees"))
        if pnl is None:
            continue
        candidate = candidates.get(str(row.get("candidate_id")), {})
        output.append({
            "date": str(row.get("resolved_at") or "")[:10],
            "pnl": pnl,
            "source": "options_shadow_twin_before_fees",
            "strategy": candidate.get("strategy"),
        })
    return output


def load_historical_series(root: Path = ROOT) -> tuple[dict[str, list[dict[str, Any]]], dict[str, str]]:
    series: dict[str, list[dict[str, Any]]] = {}
    errors: dict[str, str] = {}
    for lane, loader in (
        ("qqq_mean_reversion", _qqq_history),
        ("mes_reopen_drift", _mes_history),
        ("volatility_premium", _options_history),
    ):
        try:
            series[lane] = loader(root)
        except Exception as exc:  # source failure must be visible, not fatal to other lanes
            series[lane] = []
            errors[lane] = f"{type(exc).__name__}: {exc}"
    series["trend_participation"] = []
    return series, errors


def evidence_report(series: dict[str, list[dict[str, Any]]]) -> dict[str, Any]:
    output: dict[str, Any] = {}
    for lane, rows in series.items():
        values = [float(row["pnl"]) for row in rows if _finite(row.get("pnl")) is not None]
        bootstrap = _bootstrap_mean(values)
        output[lane] = {
            "observations": len(values),
            "mean_pnl": round(mean(values), 4) if values else None,
            "win_rate": round(sum(value > 0 for value in values) / len(values), 4) if values else None,
            "profit_factor": round(_profit_factor(values), 4) if _profit_factor(values) is not None else None,
            "max_drawdown": round(_max_drawdown(values), 2) if values else None,
            "bootstrap": bootstrap,
            "placebo": placebo_test(values),
            "decay": edge_decay(values),
            "probability_calibration": expanding_probability_calibration(rows),
        }
    return output


def _block_simulation(values: list[float], *, paths: int = 5000, horizon: int = 100) -> dict[str, Any]:
    if len(values) < 20:
        return {"status": "insufficient_n", "observations": len(values)}
    rng = random.Random(RNG_SEED + 31)
    block = max(2, int(math.sqrt(len(values))))
    totals: list[float] = []
    drawdowns: list[float] = []
    for _ in range(paths):
        path: list[float] = []
        while len(path) < horizon:
            start = rng.randrange(len(values))
            path.extend(values[(start + offset) % len(values)] for offset in range(block))
        path = path[:horizon]
        totals.append(sum(path))
        drawdowns.append(_max_drawdown(path))
    return {
        "status": "ok",
        "paths": paths,
        "horizon_sessions": horizon,
        "block_length": block,
        "mean_final_pnl": round(mean(totals), 2),
        "p05_final_pnl": round(float(_percentile(totals, 0.05)), 2),
        "loss_probability": round(sum(value < 0 for value in totals) / paths, 4),
        "p95_max_drawdown": round(float(_percentile(drawdowns, 0.95)), 2),
        "p99_max_drawdown": round(float(_percentile(drawdowns, 0.99)), 2),
    }


def uncertainty_weights(
    candidates: list[dict[str, Any]],
    evidence: dict[str, Any],
) -> dict[str, float]:
    scores: dict[str, float] = {}
    for candidate in candidates:
        lane = str(candidate["lane"])
        if lane == "cash" or not candidate.get("eligible"):
            continue
        lane_evidence = evidence.get(lane, {})
        lower = ((lane_evidence.get("bootstrap") or {}).get("ci90") or [None])[0]
        decay = (lane_evidence.get("decay") or {}).get("status")
        observations = int(lane_evidence.get("observations") or 0)
        if lower is None or lower <= 0 or observations < 30 or decay == "suspend":
            continue
        drawdown = float(lane_evidence.get("max_drawdown") or 1.0)
        scores[lane] = max(0.0, float(lower)) / max(1.0, drawdown)
    weights = {str(candidate["lane"]): 0.0 for candidate in candidates if candidate["lane"] != "cash"}
    total = sum(scores.values())
    if total > 0:
        for lane, score in scores.items():
            weights[lane] = min(MAX_LANE_WEIGHT, score / total)
    weights["cash"] = max(0.0, 1.0 - sum(weights.values()))
    return {lane: round(value, 4) for lane, value in weights.items()}


def portfolio_report(
    series: dict[str, list[dict[str, Any]]],
    weights: dict[str, float],
) -> dict[str, Any]:
    by_date: dict[str, float] = defaultdict(float)
    included: list[str] = []
    for lane, rows in series.items():
        weight = float(weights.get(lane, 0.0))
        if weight <= 0:
            continue
        included.append(lane)
        for row in rows:
            if row.get("date"):
                by_date[str(row["date"])] += weight * float(row["pnl"])
    values = [by_date[day] for day in sorted(by_date)]
    return {
        "included_lanes": included,
        "cash_weight": weights.get("cash", 1.0),
        "synchronized_dates": len(values),
        "historical_weighted_max_drawdown": round(_max_drawdown(values), 2) if values else None,
        "moving_block_bootstrap": _block_simulation(values),
        "warning": "Mixed dollar PnL series are normalized only by research weights; this is a capacity diagnostic, not an account forecast.",
    }


def _pearson(left: list[float], right: list[float]) -> float | None:
    if len(left) != len(right) or len(left) < 2:
        return None
    left_mean = mean(left)
    right_mean = mean(right)
    numerator = sum((a - left_mean) * (b - right_mean) for a, b in zip(left, right))
    left_scale = math.sqrt(sum((value - left_mean) ** 2 for value in left))
    right_scale = math.sqrt(sum((value - right_mean) ** 2 for value in right))
    if left_scale == 0 or right_scale == 0:
        return None
    return numerator / (left_scale * right_scale)


def portfolio_dependence(
    series: dict[str, list[dict[str, Any]]],
    weights: dict[str, float],
    *,
    min_overlap: int = MIN_DEPENDENCE_OVERLAP,
) -> dict[str, Any]:
    """Measure whether nominally different lanes lose together.

    Pairwise correlation alone misses strategies that are quiet together but
    fail on the same stress dates, so this also reports binary loss-event
    correlation and joint-loss lift over independent loss probabilities.
    """
    daily: dict[str, dict[str, float]] = {}
    for lane, rows in series.items():
        by_date: dict[str, float] = defaultdict(float)
        for row in rows:
            if row.get("date") and _finite(row.get("pnl")) is not None:
                by_date[str(row["date"])] += float(row["pnl"])
        daily[lane] = dict(by_date)

    pairs: list[dict[str, Any]] = []
    correlated_groups: list[list[str]] = []
    for left_lane, right_lane in combinations(sorted(daily), 2):
        overlap = sorted(set(daily[left_lane]) & set(daily[right_lane]))
        if len(overlap) < min_overlap:
            pairs.append({
                "left": left_lane,
                "right": right_lane,
                "overlap": len(overlap),
                "status": "insufficient_overlap",
            })
            continue
        left = [daily[left_lane][day] for day in overlap]
        right = [daily[right_lane][day] for day in overlap]
        left_loss = [1.0 if value < 0 else 0.0 for value in left]
        right_loss = [1.0 if value < 0 else 0.0 for value in right]
        joint_losses = sum(a == 1.0 and b == 1.0 for a, b in zip(left_loss, right_loss))
        left_loss_rate = mean(left_loss)
        right_loss_rate = mean(right_loss)
        expected_joint = left_loss_rate * right_loss_rate
        actual_joint = joint_losses / len(overlap)
        joint_lift = actual_joint / expected_joint if expected_joint > 0 else None
        correlation = _pearson(left, right)
        loss_correlation = _pearson(left_loss, right_loss)
        high = bool(
            (correlation is not None and correlation >= DEPENDENCE_CORRELATION_LIMIT)
            or (loss_correlation is not None and loss_correlation >= LOSS_EVENT_CORRELATION_LIMIT)
            or (joint_lift is not None and joint_losses >= 5 and joint_lift >= JOINT_LOSS_LIFT_LIMIT)
        )
        if high:
            correlated_groups.append([left_lane, right_lane])
        pairs.append({
            "left": left_lane,
            "right": right_lane,
            "overlap": len(overlap),
            "return_correlation": round(correlation, 4) if correlation is not None else None,
            "loss_event_correlation": round(loss_correlation, 4) if loss_correlation is not None else None,
            "left_loss_rate": round(left_loss_rate, 4),
            "right_loss_rate": round(right_loss_rate, 4),
            "joint_loss_count": joint_losses,
            "joint_loss_rate": round(actual_joint, 4),
            "joint_loss_lift_vs_independence": round(joint_lift, 4) if joint_lift is not None else None,
            "status": "correlated_risk_cluster" if high else "no_high_dependence_detected",
        })

    active_lanes = sorted(lane for lane, weight in weights.items() if lane != "cash" and float(weight) > 0)
    active_high_pairs = [
        pair for pair in pairs
        if pair.get("status") == "correlated_risk_cluster"
        and pair.get("left") in active_lanes
        and pair.get("right") in active_lanes
    ]
    active_pairs = [
        pair for pair in pairs
        if pair.get("left") in active_lanes and pair.get("right") in active_lanes
    ]
    if active_high_pairs:
        status = "concentrated"
    elif not active_lanes:
        status = "cash_only"
    elif len(active_lanes) == 1:
        status = "single_active_lane"
    elif active_pairs and all(pair.get("status") == "insufficient_overlap" for pair in active_pairs):
        status = "insufficient_overlap"
    else:
        status = "no_high_dependence_detected"
    return {
        "status": status,
        "minimum_overlap": min_overlap,
        "active_lanes": active_lanes,
        "pairs": pairs,
        "active_correlated_pairs": active_high_pairs,
        "recommended_constraint": (
            "Treat each active correlated pair as one risk sleeve and cap its combined research weight at 35%."
            if active_high_pairs else "No additional dependence cap indicated; this does not prove diversification."
        ),
        "allocation_authority": "blocked_diagnostic_only",
    }


def _read_trade_rows(path: Path) -> list[dict[str, Any]]:
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        return []
    return [row for row in value if isinstance(row, dict)] if isinstance(value, list) else []


def execution_reality_gap(
    trade_rows: list[dict[str, Any]],
    modeled_gap_pct: float | None,
    *,
    min_samples: int = MIN_EXECUTION_REALITY_SAMPLES,
) -> dict[str, Any]:
    evidence = [
        row.get("entry_execution_evidence")
        for row in trade_rows
        if isinstance(row.get("entry_execution_evidence"), dict)
    ]
    signal_slippage = [
        max(0.0, float(row["fill_vs_signal_ask_pct"]))
        for row in evidence
        if _finite(row.get("fill_vs_signal_ask_pct")) is not None
    ]
    submit_slippage = [
        max(0.0, float(row["fill_vs_submit_ask_pct"]))
        for row in evidence
        if _finite(row.get("fill_vs_submit_ask_pct")) is not None
    ]
    delays = [
        float(row["submit_to_fill_seconds"])
        for row in evidence
        if _finite(row.get("submit_to_fill_seconds")) is not None
    ]
    sample_count = len(signal_slippage)
    average_signal = mean(signal_slippage) if signal_slippage else None
    p95_signal = _percentile(signal_slippage, 0.95)
    multiple = (
        average_signal / modeled_gap_pct
        if average_signal is not None and modeled_gap_pct is not None and modeled_gap_pct > 0
        else None
    )
    if sample_count < min_samples:
        status = "insufficient_forward_fills"
    elif (average_signal or 0.0) > max(3.0, 2.0 * (modeled_gap_pct or 0.0)) or (p95_signal or 0.0) > 5.0:
        status = "high_execution_drift"
    elif (average_signal or 0.0) > max(1.5, 1.25 * (modeled_gap_pct or 0.0)) or (p95_signal or 0.0) > 3.0:
        status = "watch_execution_drift"
    else:
        status = "within_frozen_tolerance"
    return {
        "status": status,
        "minimum_forward_fills": min_samples,
        "trade_rows": len(trade_rows),
        "execution_evidence_rows": len(evidence),
        "signal_slippage_samples": sample_count,
        "modeled_mid_to_executable_gap_pct": round(modeled_gap_pct, 4) if modeled_gap_pct is not None else None,
        "average_adverse_fill_vs_signal_ask_pct": round(average_signal, 4) if average_signal is not None else None,
        "p95_adverse_fill_vs_signal_ask_pct": round(float(p95_signal), 4) if p95_signal is not None else None,
        "average_adverse_fill_vs_submit_ask_pct": round(mean(submit_slippage), 4) if submit_slippage else None,
        "average_submit_to_fill_seconds": round(mean(delays), 3) if delays else None,
        "observed_to_modeled_gap_multiple": round(multiple, 4) if multiple is not None else None,
        "intervention": "suspend_new_promotion_reviews" if status == "high_execution_drift" else "none",
        "execution_authority": "blocked_diagnostic_only",
    }


def strategy_lifecycle(
    evidence: dict[str, Any],
    previous: dict[str, Any] | None = None,
    *,
    review_key: str | None = None,
) -> dict[str, Any]:
    review_key = review_key or datetime.now(timezone.utc).date().isoformat()
    previous_lifecycle = (previous or {}).get("strategy_lifecycle") or {}
    previous_lanes = previous_lifecycle.get("lanes") or {}
    previous_schema = int(previous_lifecycle.get("schema_version") or 0)
    lanes: dict[str, Any] = {}
    for lane, row in sorted(evidence.items()):
        observations = int(row.get("observations") or 0)
        lower = ((row.get("bootstrap") or {}).get("ci90") or [None])[0]
        placebo = str((row.get("placebo") or {}).get("status") or "insufficient_n")
        decay = str((row.get("decay") or {}).get("status") or "insufficient_n")
        prior = previous_lanes.get(lane) if isinstance(previous_lanes, dict) else {}
        prior_streak = int((prior or {}).get("stable_review_streak") or 0)
        prior_review_key = str(
            (prior or {}).get("last_review_key")
            or (previous or {}).get("generated_at")
            or ""
        )[:10]
        same_review = prior_review_key == review_key
        if previous_schema < 2 and same_review:
            prior_streak = min(prior_streak, 1)
        pass_now = observations >= 30 and lower is not None and lower > 0 and placebo == "pass" and decay == "stable"
        stable_streak = (prior_streak if same_review else prior_streak + 1) if pass_now else 0
        reasons: list[str] = []
        if observations < 30:
            reasons.append("fewer_than_30_resolved_observations")
        if lower is None or lower <= 0:
            reasons.append("bootstrap_lower_bound_not_positive")
        if placebo != "pass":
            reasons.append(f"placebo_{placebo}")
        if decay != "stable":
            reasons.append(f"decay_{decay}")
        permanent_block = LANE_REVIEW_BLOCKS.get(lane)
        if permanent_block:
            reasons.append(permanent_block)

        if observations < 30:
            state = "collecting"
        elif decay == "suspend" or placebo == "fail" or lower is None or lower <= 0:
            state = "suspended"
        elif decay == "watch":
            state = "watch"
        elif permanent_block:
            state = "research_only"
        elif stable_streak < RECOVERY_REVIEWS_REQUIRED:
            state = "recovery_observation"
        else:
            state = "review_ready"
        lanes[lane] = {
            "state": state,
            "observations": observations,
            "stable_review_streak": stable_streak,
            "stable_reviews_required": RECOVERY_REVIEWS_REQUIRED,
            "last_review_key": review_key,
            "reasons": reasons,
            "paper_review_eligible": state == "review_ready",
            "permanent_review_block": permanent_block,
            "automatic_promotion_allowed": False,
            "automatic_reactivation_allowed": False,
        }
    return {
        "schema_version": 2,
        "lanes": lanes,
        "rule": "Two consecutive passing reviews are required after sufficient evidence; promotion and reactivation still require human approval.",
        "promotion_authority": "blocked",
    }


def configuration_fingerprint(root: Path = ROOT) -> dict[str, Any]:
    files: dict[str, str | None] = {}
    for relative in FINGERPRINT_PATHS:
        path = root / relative
        try:
            files[relative] = hashlib.sha256(path.read_bytes()).hexdigest()
        except OSError:
            files[relative] = None
    material = json.dumps(files, sort_keys=True, separators=(",", ":"))
    return {
        "algorithm": "sha256",
        "combined": hashlib.sha256(material.encode("utf-8")).hexdigest(),
        "files": files,
        "purpose": "Detect unreviewed changes between evidence packets; this is not code signing.",
    }


def execution_ab(root: Path = ROOT) -> dict[str, Any]:
    rows = _read_jsonl(root / "data" / "options_shadow_twin_log.jsonl")
    samples: list[dict[str, float]] = []
    for row in rows:
        if row.get("type") != "candidate":
            continue
        midpoint = _finite(row.get("quoted_mid_credit"))
        if midpoint is None:
            midpoint = _finite(row.get("midpoint_credit"))
        executable = _finite(row.get("executable_entry_credit"))
        if executable is None:
            executable = _finite(row.get("entry_credit"))
        if midpoint is None or executable is None or midpoint < executable:
            continue
        gap = midpoint - executable
        samples.append({
            "midpoint": midpoint,
            "immediate_executable": executable,
            "patient_limit_proxy": executable + 0.50 * gap,
            "escalating_limit_proxy": executable + 0.25 * gap,
        })
    if not samples:
        return {"status": "awaiting_point_in_time_quotes", "samples": 0, "selection_authority": "blocked"}
    means = {key: round(mean(row[key] for row in samples), 4) for key in samples[0]}
    return {
        "status": "descriptive_quote_counterfactual",
        "samples": len(samples),
        "average_entry_credit": means,
        "average_midpoint_minus_executable": round(means["midpoint"] - means["immediate_executable"], 4),
        "fill_assumption": "Patient and escalating policies are quote interpolation proxies; fill probability is unknown.",
        "selection_authority": "blocked_until_policy_specific_forward_fills",
    }


def _candidate_id(as_of: str, lane: str, source_key: str) -> str:
    return hashlib.sha256(f"schema={SCHEMA_VERSION}|{as_of}|{lane}|{source_key}".encode()).hexdigest()[:20]


def current_candidates(root: Path = ROOT) -> list[dict[str, Any]]:
    qqq = _latest_jsonl(root / "data" / "qqq_mean_reversion_shadow_log.jsonl")
    mes = _latest_jsonl(root / "data" / "mes_reopen_vix_shadow_log.jsonl")
    trend = _latest_jsonl(root / "data" / "trend_participation_shadow_log.jsonl")
    condor = _read_json(root / "data" / "spy_iron_condor_decision.json")
    theta = _read_json(root / "data" / "theta_harvester_latest_decision.json")
    dates = [
        str(qqq.get("date") or ""),
        str(mes.get("timestamp") or "")[:10],
        str(trend.get("session") or ""),
        str(condor.get("generated_at") or "")[:10],
    ]
    as_of = max((value for value in dates if value), default=datetime.now(timezone.utc).date().isoformat())

    setups = qqq.get("setups") if isinstance(qqq.get("setups"), dict) else {}
    preferred = setups.get("rsi2_exit_prior_high") if isinstance(setups.get("rsi2_exit_prior_high"), dict) else {}
    qqq_action = str(preferred.get("action") or "unavailable")
    qqq_eligible = any(token in qqq_action for token in ("arm_entry", "virtual_long"))
    condor_details = condor.get("details") if isinstance(condor.get("details"), dict) else {}
    blockers = [str(value) for value in condor_details.get("blockers") or []]
    if not blockers and condor.get("status") != "eligible":
        blockers = [str(condor.get("reason") or theta.get("reason") or "no_volatility_premium_setup")]

    regime_context = {
        "qqq_mean_reversion": {
            "vix_regime": (qqq.get("vix_context") or {}).get("regime"),
            "vix_close": (qqq.get("vix_context") or {}).get("close"),
            "above_sma200": (qqq.get("features") or {}).get("close", 0) > (qqq.get("features") or {}).get("sma200", math.inf),
            "rsi2": (qqq.get("features") or {}).get("rsi2"),
        },
        "mes_reopen_drift": {
            "data_source": mes.get("data_source"),
            "signal_reason": mes.get("reason"),
        },
        "trend_participation": {
            "candidate_count": trend.get("candidate_count"),
            "rejection_counts": trend.get("rejection_counts"),
        },
        "volatility_premium": {
            "gate_states": condor_details.get("gates"),
            "decision_status": condor.get("status"),
        },
        "cash": {"always_available": True},
    }
    definitions = [
        ("qqq_mean_reversion", qqq_eligible, [] if qqq_eligible else [qqq_action], "qqq:rsi2_exit_prior_high", "upstream_qqq_shadow_position_exit"),
        ("mes_reopen_drift", bool(mes.get("should_enter")), [] if mes.get("should_enter") else [str(mes.get("reason") or "not_eligible")], str(mes.get("trade_key") or "mes"), "upstream_next_0930_et_shadow_exit"),
        ("trend_participation", int(trend.get("candidate_count") or 0) > 0, [] if int(trend.get("candidate_count") or 0) > 0 else ["no_trend_candidate"], str(trend.get("session") or "trend"), "upstream_trend_shadow_outcome"),
        ("volatility_premium", condor.get("status") == "eligible", blockers, str(condor.get("generated_at") or "vol"), "upstream_options_shadow_twin_outcome"),
        ("cash", True, [], "cash", "zero_pnl_benchmark"),
    ]
    return [
        {
            "schema_version": SCHEMA_VERSION,
            "candidate_id": _candidate_id(as_of, lane, key),
            "as_of": as_of,
            "lane": lane,
            "eligible": eligible,
            "decision": "consider" if eligible and lane != "cash" else "cash" if lane == "cash" else "reject",
            "rejection_reasons": reasons,
            "source_key": key,
            "regime_context": regime_context[lane],
            "resolution_contract": resolution_contract,
            "resolution_status": "benchmark" if lane == "cash" else "pending_upstream",
            "execution_enabled": False,
            "can_submit_orders": False,
        }
        for lane, eligible, reasons, key, resolution_contract in definitions
    ]


def append_candidates(path: Path, candidates: list[dict[str, Any]]) -> int:
    existing = {str(row.get("candidate_id")) for row in _read_jsonl(path)}
    new_rows = [row for row in candidates if row["candidate_id"] not in existing]
    if not new_rows:
        return 0
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        for row in new_rows:
            handle.write(json.dumps({"record_type": "candidate", **row}, sort_keys=True) + "\n")
    return len(new_rows)


def source_slo(root: Path = ROOT) -> dict[str, Any]:
    paths = {
        "qqq_shadow": root / "data" / "qqq_mean_reversion_shadow_log.jsonl",
        "mes_shadow": root / "data" / "mes_reopen_vix_shadow_log.jsonl",
        "trend_shadow": root / "data" / "trend_participation_shadow_log.jsonl",
        "options_twin": root / "data" / "options_shadow_twin_log.jsonl",
        "iron_condor": root / "data" / "spy_iron_condor_decision.json",
    }
    now = datetime.now(timezone.utc).timestamp()
    rows: dict[str, Any] = {}
    for name, path in paths.items():
        exists = path.exists()
        age = (now - path.stat().st_mtime) / 3600 if exists else None
        parseable = bool(_read_json(path)) if path.suffix == ".json" else bool(_read_jsonl(path))
        rows[name] = {
            "path": str(path.relative_to(root)),
            "exists": exists,
            "parseable": parseable,
            "age_hours": round(age, 2) if age is not None else None,
            "fresh_within_48h": bool(age is not None and age <= 48),
        }
    healthy = all(row["exists"] and row["parseable"] and row["fresh_within_48h"] for row in rows.values())
    return {
        "status": "ok" if healthy else "degraded",
        "sources": rows,
        "invariants": {
            "execution_enabled": False,
            "can_submit_orders": False,
            "candidate_rows_include_rejections": True,
            "cash_is_explicit": True,
        },
    }


def build_report(root: Path = ROOT, *, write_ledger: bool = True, ledger_path: Path | None = None) -> dict[str, Any]:
    output_path = root / DEFAULT_OUTPUT.relative_to(ROOT)
    previous_report = _read_json(output_path)
    candidates = current_candidates(root)
    series, history_errors = load_historical_series(root)
    evidence = evidence_report(series)
    weights = uncertainty_weights(candidates, evidence)
    for candidate in candidates:
        candidate["research_weight"] = weights.get(str(candidate["lane"]), 0.0)
        candidate["allocation_reason"] = (
            "explicit_cash_residual" if candidate["lane"] == "cash"
            else "eligible_positive_lower_bound" if candidate["research_weight"] > 0
            else "zero_weight_due_to_signal_evidence_or_decay"
        )
    ledger = ledger_path or (root / DEFAULT_LEDGER.relative_to(ROOT))
    appended = append_candidates(ledger, candidates) if write_ledger else 0

    twin_rows = _read_jsonl(root / "data" / "options_shadow_twin_log.jsonl")
    setup_rows = _read_jsonl(root / "data" / "options_evidence_factory_log.jsonl")
    gate_attribution = build_gate_report(twin_rows, setup_rows)
    execution = execution_ab(root)
    entry_credit = (execution.get("average_entry_credit") or {}) if isinstance(execution, dict) else {}
    midpoint = _finite(entry_credit.get("midpoint"))
    gap = _finite(execution.get("average_midpoint_minus_executable")) if isinstance(execution, dict) else None
    modeled_gap_pct = gap / midpoint * 100.0 if gap is not None and midpoint not in (None, 0.0) else None
    trade_path = VIBE_HOME / "flip-trades.json" if root == ROOT else root / "data" / "flip-trades.json"
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "provider": "opportunity_intelligence_pipeline",
        "protocol": PROTOCOL,
        "mode": "read_only_shadow_research",
        "execution_enabled": False,
        "can_submit_orders": False,
        "orders_submitted": 0,
        "as_of": candidates[0]["as_of"],
        "regime_allocator": {
            "weights": weights,
            "candidates": candidates,
            "rule": "positive_90pct_block_bootstrap_lower_bound_plus_non_suspended_decay_capped_35pct",
        },
        "evidence": evidence,
        "gate_attribution": gate_attribution,
        "rejected_trade_ledger": {
            "path": str(ledger.relative_to(root)) if ledger.is_relative_to(root) else str(ledger),
            "new_records": appended,
            "total_records": len(_read_jsonl(ledger)),
            "all_current_rejections_recorded": all(
                any(row.get("candidate_id") == candidate["candidate_id"] for row in _read_jsonl(ledger))
                for candidate in candidates if candidate["decision"] == "reject"
            ) if write_ledger else None,
        },
        "execution_ab": execution,
        "execution_reality_gap": execution_reality_gap(_read_trade_rows(trade_path), modeled_gap_pct),
        "portfolio_simulation": portfolio_report(series, weights),
        "portfolio_dependence": portfolio_dependence(series, weights),
        "strategy_lifecycle": strategy_lifecycle(evidence, previous_report, review_key=candidates[0]["as_of"]),
        "configuration_fingerprint": configuration_fingerprint(root),
        "risk_method_invariants": {
            "martingale_allowed": False,
            "grid_averaging_allowed": False,
            "averaging_down_allowed": False,
            "automatic_risk_increase_after_loss_allowed": False,
            "automatic_strategy_promotion_allowed": False,
            "automatic_strategy_reactivation_allowed": False,
            "fixed_or_reduced_risk_only": True,
        },
        "operational_slo": source_slo(root),
        "history_load_errors": history_errors,
        "promotion_authority": "blocked",
        "warnings": [
            "Research weights are not position sizes and cannot reach a broker.",
            "QQQ history is development-only and failed experiment-wide multiple-test correction.",
            "MES evidence is retrospective and its independent bootstrap interval crosses zero.",
            "Missing evidence maps to zero research weight, never a favorable assumption.",
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--ledger", type=Path, default=DEFAULT_LEDGER)
    parser.add_argument("--no-ledger", action="store_true")
    parser.add_argument("--print", action="store_true", dest="print_report")
    args = parser.parse_args()
    report = build_report(ROOT, write_ledger=not args.no_ledger, ledger_path=args.ledger)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    if args.print_report:
        print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

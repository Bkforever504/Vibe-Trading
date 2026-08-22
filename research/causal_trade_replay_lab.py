#!/usr/bin/env python3
"""Causal trade autopsy and walk-forward exit-policy replay.

Every resolved Flip shadow lifecycle is measured twice:

1. An oracle autopsy asks which frozen policy would have worked after seeing the
   complete path. This is a diagnostic upper bound and has no execution value.
2. A walk-forward replay chooses a policy using earlier dates only, then applies
   it to the next unseen date. This is the only replay result that can support a
   future paper-trial proposal.

The report is read-only. It cannot change parameters or submit orders.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from research import options_exit_policy_lab as exit_lab

DEFAULT_CANDIDATES_PATH = exit_lab.DEFAULT_CANDIDATES_PATH
DEFAULT_OUTPUT_PATH = ROOT / "data" / "causal_trade_replay_lab_results.json"
DEFAULT_FEE_PCT = exit_lab.DEFAULT_FEE_PER_CONTRACT_PCT
MIN_TRAIN_DATES = 5
MIN_CONTEXT_SAMPLES = 30
MIN_CONTEXT_DATES = 3
MIN_OOS_DATES_FOR_REVIEW = 20
MIN_OOS_TRADES_FOR_REVIEW = 100

Policy = Callable[[exit_lab.Lifecycle], exit_lab.PolicyResult]
EntryVariant = Callable[[exit_lab.Lifecycle], tuple[exit_lab.Lifecycle | None, str]]


def _finite(value: float | None, fallback: float = -math.inf) -> float:
    return float(value) if value is not None and math.isfinite(float(value)) else fallback


def _post_fee(result: exit_lab.PolicyResult, fee_pct: float) -> float:
    return round(float(result[0]) - fee_pct, 4)


def _mark_returns(life: exit_lab.Lifecycle, fee_pct: float) -> list[float]:
    return [
        round(exit_lab._bid_return_pct(mark.bid, life.entry_premium) - fee_pct, 4)
        for mark in life.marks
        if mark.bid > 0
    ]


def _actionable_entry_marks(life: exit_lab.Lifecycle) -> list[exit_lab.Mark]:
    """Return later, two-sided executable marks with duplicate timestamps removed."""
    rows: list[exit_lab.Mark] = []
    seen: set[str] = set()
    for mark in life.marks:
        if mark.ts == life.entry_at or mark.ts in seen:
            continue
        seen.add(mark.ts)
        if mark.ask is None or mark.ask <= 0 or mark.bid <= 0:
            continue
        rows.append(mark)
    return rows


def _rebase_lifecycle(life: exit_lab.Lifecycle, entry_mark: exit_lab.Mark) -> exit_lab.Lifecycle:
    marks = tuple(mark for mark in life.marks if mark.ts >= entry_mark.ts)
    return exit_lab.Lifecycle(
        lifecycle_id=life.lifecycle_id,
        date=life.date,
        symbol=life.symbol,
        right=life.right,
        strategy=life.strategy,
        day_type=life.day_type,
        entry_premium=float(entry_mark.ask),
        marks=marks,
        entry_at=entry_mark.ts,
        features=life.features,
        episode_bucket_et=life.episode_bucket_et,
        decision_pair_id=life.decision_pair_id,
        decision_lattice_role=life.decision_lattice_role,
        entry_quote_timestamp=life.entry_quote_timestamp,
        entry_quote_age_seconds=life.entry_quote_age_seconds,
        pair_construction_method=life.pair_construction_method,
        pair_sync_status=life.pair_sync_status,
    )


def _delay_entry(life: exit_lab.Lifecycle, marks: int) -> tuple[exit_lab.Lifecycle | None, str]:
    candidates = _actionable_entry_marks(life)
    if len(candidates) < marks:
        return None, f"insufficient_marks_for_delay_{marks}"
    return _rebase_lifecycle(life, candidates[marks - 1]), f"delay_{marks}_marks"


def _first_green_confirmation(life: exit_lab.Lifecycle) -> tuple[exit_lab.Lifecycle | None, str]:
    for mark in _actionable_entry_marks(life):
        if mark.bid > life.entry_premium:
            return _rebase_lifecycle(life, mark), "first_bid_above_original_entry"
    return None, "never_confirmed_above_original_entry"


def _two_mark_rising_confirmation(life: exit_lab.Lifecycle) -> tuple[exit_lab.Lifecycle | None, str]:
    candidates = _actionable_entry_marks(life)
    for prior, current in zip(candidates, candidates[1:]):
        if current.bid > prior.bid and current.bid > life.entry_premium:
            return _rebase_lifecycle(life, current), "two_mark_rising_above_original_entry"
    return None, "never_confirmed_two_mark_rise"


def _dip_recovery_entry(life: exit_lab.Lifecycle) -> tuple[exit_lab.Lifecycle | None, str]:
    candidates = _actionable_entry_marks(life)
    for prior, current in zip(candidates, candidates[1:]):
        drawdown = (prior.bid - life.entry_premium) / life.entry_premium * 100.0
        if drawdown <= -15.0 and current.bid > prior.bid:
            return _rebase_lifecycle(life, current), "recovering_after_15pct_dip"
    return None, "no_dip_recovery_trigger"


ENTRY_VARIANTS: dict[str, EntryVariant] = {
    "delay_one_mark": lambda life: _delay_entry(life, 1),
    "delay_two_marks": lambda life: _delay_entry(life, 2),
    "first_green_confirmation": _first_green_confirmation,
    "two_mark_rising_confirmation": _two_mark_rising_confirmation,
    "dip_15pct_then_recovery": _dip_recovery_entry,
}

ENTRY_FEATURE_ALLOWLIST = (
    "day_type",
    "market_force_classification",
    "above_vwap",
    "below_vwap",
    "above_ema50",
    "below_ema50",
    "ema50_sloping_up",
    "ema50_sloping_down",
    "green_session",
    "red_session",
    "htf_primary_bias",
    "htf_intraday_alignment",
    "candlestick_bias",
    "candlestick_context_status",
    "ttm_state",
    "ttm_momentum_rising",
    "opening_range_bucket",
    "orb_direction",
    "orb_retest_status",
    "retest_grade",
    "pullback_held_trend",
    "pullback_failed_near_trend",
    "not_extended_from_vwap",
    "catalyst_max_impact",
    "market_context_snapshot_status",
)


def _feature_value(value: Any) -> str | None:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, str) and value.strip():
        return value.strip().lower()
    return None


def entry_feature_attribution(
    lives: list[exit_lab.Lifecycle],
    *,
    fee_pct: float = DEFAULT_FEE_PCT,
    min_samples: int = 30,
    min_dates: int = 3,
) -> dict[str, Any]:
    """Rank pre-entry context buckets by baseline outcome, descriptively only."""
    baseline = {
        life.lifecycle_id: _post_fee(exit_lab.POLICIES["baseline_current"](life), fee_pct)
        for life in lives
    }
    rows: list[dict[str, Any]] = []
    for feature in ENTRY_FEATURE_ALLOWLIST:
        groups: dict[str, list[exit_lab.Lifecycle]] = defaultdict(list)
        for life in lives:
            value = _feature_value(life.features.get(feature))
            if value is not None:
                groups[value].append(life)
        for value, cohort in groups.items():
            cohort_ids = {life.lifecycle_id for life in cohort}
            complement = [life for life in lives if life.lifecycle_id not in cohort_ids]
            dates = {life.date for life in cohort if life.date}
            if len(cohort) < min_samples or len(dates) < min_dates or not complement:
                continue
            cohort_metrics = exit_lab._cohort_metrics([baseline[life.lifecycle_id] for life in cohort])
            complement_metrics = exit_lab._cohort_metrics([baseline[life.lifecycle_id] for life in complement])
            delta = round(
                cohort_metrics.get("expectancy_pct", 0) - complement_metrics.get("expectancy_pct", 0),
                4,
            )
            rows.append({
                "feature": feature,
                "value": value,
                "sample_size": len(cohort),
                "unique_dates": len(dates),
                "cohort_metrics": cohort_metrics,
                "complement_metrics": complement_metrics,
                "expectancy_delta_vs_complement_pct": delta,
                "risk_flag": delta < 0 and cohort_metrics.get("expectancy_pct", 0) < 0,
            })
    rows.sort(key=lambda row: row["expectancy_delta_vs_complement_pct"])
    return {
        "mode": "posthoc_pre_entry_feature_attribution",
        "minimum_samples": min_samples,
        "minimum_dates": min_dates,
        "ranked_risk_to_opportunity": rows,
        "execution_authority": "none_requires_preregistered_forward_veto_trial",
    }


def evaluate_entry_timing_variants(
    lives: list[exit_lab.Lifecycle],
    *,
    fee_pct: float = DEFAULT_FEE_PCT,
    exit_policy: Policy | None = None,
) -> dict[str, Any]:
    """Replay post-hoc entry challengers using recorded ask-to-bid execution."""
    exit_fn = exit_policy or exit_lab.POLICIES["baseline_current"]
    baseline = [_post_fee(exit_lab.POLICIES["baseline_current"](life), fee_pct) for life in lives]
    variants: dict[str, Any] = {}
    for name, builder in ENTRY_VARIANTS.items():
        signal_returns: list[float] = []
        trade_returns: list[float] = []
        triggers = Counter()
        salvaged = 0
        winners_missed_or_spoiled = 0
        for life, baseline_return in zip(lives, baseline):
            rebased, reason = builder(life)
            triggers[reason] += 1
            if rebased is None:
                signal_returns.append(0.0)
                if baseline_return > 0:
                    winners_missed_or_spoiled += 1
                continue
            value = _post_fee(exit_fn(rebased), fee_pct)
            signal_returns.append(value)
            trade_returns.append(value)
            salvaged += baseline_return <= 0 < value
            winners_missed_or_spoiled += baseline_return > 0 >= value
        variants[name] = {
            "signals": len(lives),
            "trades_triggered": len(trade_returns),
            "participation_rate": round(len(trade_returns) / len(lives), 4) if lives else 0.0,
            "per_signal_metrics": exit_lab._cohort_metrics(signal_returns),
            "per_triggered_trade_metrics": exit_lab._cohort_metrics(trade_returns),
            "baseline_losses_salvaged_hindsight": salvaged,
            "baseline_winners_missed_or_spoiled_hindsight": winners_missed_or_spoiled,
            "trigger_reason_counts": dict(triggers),
            "evidence_status": "posthoc_consumed_corpus_requires_new_forward_dates",
        }
    return {
        "execution_basis": "recorded_delayed_ask_to_later_executable_bid",
        "exit_policy": "baseline_current_rebased_to_delayed_entry",
        "variants": variants,
        "execution_authority": "none_posthoc_discovery_only",
    }


def autopsy_lifecycle(
    life: exit_lab.Lifecycle,
    *,
    policies: dict[str, Policy] | None = None,
    fee_pct: float = DEFAULT_FEE_PCT,
) -> dict[str, Any]:
    """Explain one completed trade without granting hindsight execution authority."""
    policy_set = policies or exit_lab.POLICIES
    outcomes: dict[str, dict[str, Any]] = {}
    for name, fn in policy_set.items():
        result = fn(life)
        outcomes[name] = {
            "return_pct": _post_fee(result, fee_pct),
            "exit_reason": result[1],
        }
    baseline = outcomes["baseline_current"]["return_pct"]
    ranked = sorted(outcomes.items(), key=lambda item: item[1]["return_pct"], reverse=True)
    oracle_name, oracle = ranked[0]
    tape = _mark_returns(life, fee_pct)
    mfe = max(tape) if tape else None
    mae = min(tape) if tape else None
    profitable = [name for name, row in outcomes.items() if row["return_pct"] > 0]

    if baseline > 0:
        diagnosis = "baseline_winner"
    elif not tape:
        diagnosis = "insufficient_executable_marks"
    elif max(tape) <= 0:
        diagnosis = "entry_never_profitable_after_cost"
    elif oracle["return_pct"] <= 0:
        diagnosis = "profitable_excursion_not_captured_by_frozen_policies"
    else:
        diagnosis = "exit_policy_salvageable_hindsight_only"

    return {
        "lifecycle_id": life.lifecycle_id,
        "date": life.date,
        "symbol": life.symbol,
        "right": life.right,
        "strategy": life.strategy,
        "day_type": life.day_type,
        "entry_premium": life.entry_premium,
        "entry_at": life.entry_at,
        "entry_features": life.features,
        "entry_feature_count": len(life.features),
        "mark_count": len(tape),
        "mfe_post_fee_pct": mfe,
        "mae_post_fee_pct": mae,
        "baseline_return_pct": baseline,
        "baseline_exit_reason": outcomes["baseline_current"]["exit_reason"],
        "diagnosis": diagnosis,
        "profitable_frozen_policies": profitable,
        "oracle_best_policy": oracle_name,
        "oracle_best_return_pct": oracle["return_pct"],
        "oracle_improvement_pct": round(oracle["return_pct"] - baseline, 4),
        "oracle_hindsight_only": True,
        "policy_outcomes": outcomes,
    }


def _robust_score(report: dict[str, Any]) -> float:
    """Worst of normal, doubled-cost, and winner-trimmed expectancy."""
    values = (
        report["post_fee"].get("expectancy_pct"),
        report["doubled_cost"].get("expectancy_pct"),
        report["top5_removed_post_fee"].get("expectancy_pct"),
    )
    return round(min(_finite(value) for value in values), 4)


def _context_cohorts(life: exit_lab.Lifecycle) -> list[tuple[str, tuple[str, ...]]]:
    market_force = str(life.features.get("market_force_classification") or "unknown")
    htf_bias = str(life.features.get("htf_primary_bias") or "unknown")
    return [
        (
            "strategy_right_day_type_market_force",
            (life.strategy, life.right, life.day_type, market_force),
        ),
        ("strategy_right_market_force", (life.strategy, life.right, market_force)),
        ("strategy_right_htf_bias", (life.strategy, life.right, htf_bias)),
        ("strategy_right_day_type", (life.strategy, life.right, life.day_type)),
        ("strategy_right", (life.strategy, life.right)),
        ("strategy", (life.strategy,)),
        ("global", ()),
    ]


def _matches(life: exit_lab.Lifecycle, scope: str, key: tuple[str, ...]) -> bool:
    market_force = str(life.features.get("market_force_classification") or "unknown")
    htf_bias = str(life.features.get("htf_primary_bias") or "unknown")
    if scope == "strategy_right_day_type_market_force":
        return (life.strategy, life.right, life.day_type, market_force) == key
    if scope == "strategy_right_market_force":
        return (life.strategy, life.right, market_force) == key
    if scope == "strategy_right_htf_bias":
        return (life.strategy, life.right, htf_bias) == key
    if scope == "strategy_right_day_type":
        return (life.strategy, life.right, life.day_type) == key
    if scope == "strategy_right":
        return (life.strategy, life.right) == key
    if scope == "strategy":
        return (life.strategy,) == key
    return True


def select_policy_from_history(
    history: list[exit_lab.Lifecycle],
    target: exit_lab.Lifecycle,
    *,
    policies: dict[str, Policy] | None = None,
    fee_pct: float = DEFAULT_FEE_PCT,
    min_context_samples: int = MIN_CONTEXT_SAMPLES,
    min_context_dates: int = MIN_CONTEXT_DATES,
) -> dict[str, Any]:
    """Select an exit policy from prior lifecycles only."""
    policy_set = policies or exit_lab.POLICIES
    cohort: list[exit_lab.Lifecycle] = []
    selected_scope = "global"
    selected_key: tuple[str, ...] = ()
    for scope, key in _context_cohorts(target):
        candidate = [life for life in history if _matches(life, scope, key)]
        dates = {life.date for life in candidate if life.date}
        if len(candidate) >= min_context_samples and len(dates) >= min_context_dates:
            cohort = candidate
            selected_scope = scope
            selected_key = key
            break
    if not cohort:
        cohort = list(history)

    scored = []
    for name, fn in policy_set.items():
        report = exit_lab.evaluate_policy(name, fn, cohort, fee_pct)
        scored.append((name, _robust_score(report), report))
    scored.sort(key=lambda row: (row[1], row[0] == "baseline_current"), reverse=True)
    name, score, report = scored[0]
    selection_reason = "positive_robust_prior_edge"
    if score <= 0 and "baseline_current" in policy_set:
        baseline = next(row for row in scored if row[0] == "baseline_current")
        name, score, report = baseline
        selection_reason = "fallback_baseline_no_positive_robust_prior_edge"
    return {
        "policy": name,
        "robust_score_pct": score,
        "positive_robust_edge": score > 0,
        "selection_reason": selection_reason,
        "scope": selected_scope,
        "context": list(selected_key),
        "training_trades": len(cohort),
        "training_dates": len({life.date for life in cohort if life.date}),
        "training_metrics": report,
    }


def _top_removed(values: list[float], pct: float = 5.0) -> list[float]:
    if not values:
        return []
    count = max(1, int(len(values) * pct / 100.0))
    return sorted(values)[:-count] if count < len(values) else []


def walk_forward_replay(
    lives: list[exit_lab.Lifecycle],
    *,
    policies: dict[str, Policy] | None = None,
    fee_pct: float = DEFAULT_FEE_PCT,
    min_train_dates: int = MIN_TRAIN_DATES,
    min_context_samples: int = MIN_CONTEXT_SAMPLES,
    min_context_dates: int = MIN_CONTEXT_DATES,
) -> dict[str, Any]:
    """Choose on prior dates and execute the choice on each next unseen date."""
    policy_set = policies or exit_lab.POLICIES
    dates = sorted({life.date for life in lives if life.date})
    rows: list[dict[str, Any]] = []
    folds: list[dict[str, Any]] = []
    for test_date in dates[min_train_dates:]:
        history = [life for life in lives if life.date < test_date]
        tests = [life for life in lives if life.date == test_date]
        date_rows = []
        for life in tests:
            selection = select_policy_from_history(
                history,
                life,
                policies=policy_set,
                fee_pct=fee_pct,
                min_context_samples=min_context_samples,
                min_context_dates=min_context_dates,
            )
            selected = _post_fee(policy_set[selection["policy"]](life), fee_pct)
            baseline = _post_fee(policy_set["baseline_current"](life), fee_pct)
            row = {
                "lifecycle_id": life.lifecycle_id,
                "date": life.date,
                "strategy": life.strategy,
                "right": life.right,
                "day_type": life.day_type,
                "selected_policy": selection["policy"],
                "selection_scope": selection["scope"],
                "training_trades": selection["training_trades"],
                "training_dates": selection["training_dates"],
                "training_robust_score_pct": selection["robust_score_pct"],
                "training_positive_robust_edge": selection["positive_robust_edge"],
                "selection_reason": selection["selection_reason"],
                "selected_return_pct": selected,
                "baseline_return_pct": baseline,
                "delta_pct": round(selected - baseline, 4),
                "baseline_loss_salvaged": baseline <= 0 < selected,
                "baseline_winner_spoiled": baseline > 0 >= selected,
            }
            rows.append(row)
            date_rows.append(row)
        folds.append({
            "test_date": test_date,
            "training_dates": len({life.date for life in history}),
            "test_trades": len(date_rows),
            "selected_expectancy_pct": round(sum(r["selected_return_pct"] for r in date_rows) / len(date_rows), 4) if date_rows else None,
            "baseline_expectancy_pct": round(sum(r["baseline_return_pct"] for r in date_rows) / len(date_rows), 4) if date_rows else None,
            "selected_policy_counts": dict(Counter(r["selected_policy"] for r in date_rows)),
        })

    selected_returns = [row["selected_return_pct"] for row in rows]
    baseline_returns = [row["baseline_return_pct"] for row in rows]
    selected_metrics = exit_lab._cohort_metrics(selected_returns)
    baseline_metrics = exit_lab._cohort_metrics(baseline_returns)
    doubled_cost_metrics = exit_lab._cohort_metrics([value - fee_pct for value in selected_returns])
    top5_removed = exit_lab._cohort_metrics(_top_removed(selected_returns))
    oos_dates = len({row["date"] for row in rows})
    failed = []
    if len(rows) < MIN_OOS_TRADES_FOR_REVIEW:
        failed.append(f"insufficient_oos_trades_{len(rows)}/{MIN_OOS_TRADES_FOR_REVIEW}")
    if oos_dates < MIN_OOS_DATES_FOR_REVIEW:
        failed.append(f"insufficient_oos_dates_{oos_dates}/{MIN_OOS_DATES_FOR_REVIEW}")
    if selected_metrics.get("expectancy_pct", 0) <= 0:
        failed.append("oos_expectancy_not_positive")
    if doubled_cost_metrics.get("expectancy_pct", 0) <= 0:
        failed.append("oos_doubled_cost_expectancy_not_positive")
    if top5_removed.get("expectancy_pct", 0) <= 0:
        failed.append("oos_top5_removed_expectancy_not_positive")

    return {
        "initial_training_dates": min_train_dates,
        "oos_trades": len(rows),
        "oos_dates": oos_dates,
        "selected_policy_metrics": selected_metrics,
        "baseline_metrics_same_oos": baseline_metrics,
        "selected_doubled_cost_metrics": doubled_cost_metrics,
        "selected_top5_removed_metrics": top5_removed,
        "expectancy_delta_pct": round(
            selected_metrics.get("expectancy_pct", 0) - baseline_metrics.get("expectancy_pct", 0), 4
        ),
        "drawdown_delta_pct": round(
            selected_metrics.get("max_dd_pct", 0) - baseline_metrics.get("max_dd_pct", 0), 4
        ),
        "baseline_losses_salvaged": sum(row["baseline_loss_salvaged"] for row in rows),
        "baseline_winners_spoiled": sum(row["baseline_winner_spoiled"] for row in rows),
        "selected_policy_counts": dict(Counter(row["selected_policy"] for row in rows)),
        "selection_scope_counts": dict(Counter(row["selection_scope"] for row in rows)),
        "review_gate": {"passed": not failed, "failed_checks": failed},
        "folds": folds,
        "outcomes": rows,
    }


def build_report(
    candidates_path: Path = DEFAULT_CANDIDATES_PATH,
    *,
    fee_pct: float = DEFAULT_FEE_PCT,
    min_train_dates: int = MIN_TRAIN_DATES,
) -> dict[str, Any]:
    lives = exit_lab.load_lifecycles(candidates_path)
    autopsies = [autopsy_lifecycle(life, fee_pct=fee_pct) for life in lives]
    diagnosis_counts = Counter(row["diagnosis"] for row in autopsies)
    baseline = [row["baseline_return_pct"] for row in autopsies]
    oracle = [row["oracle_best_return_pct"] for row in autopsies]
    policy_attribution: dict[str, dict[str, Any]] = {}
    for name in exit_lab.POLICIES:
        values = [row["policy_outcomes"][name]["return_pct"] for row in autopsies]
        policy_attribution[name] = {
            "metrics": exit_lab._cohort_metrics(values),
            "baseline_losses_salvaged_hindsight": sum(
                row["baseline_return_pct"] <= 0 < row["policy_outcomes"][name]["return_pct"]
                for row in autopsies
            ),
            "baseline_winners_spoiled_hindsight": sum(
                row["baseline_return_pct"] > 0 >= row["policy_outcomes"][name]["return_pct"]
                for row in autopsies
            ),
        }
    return {
        "provider": "causal_trade_replay_lab",
        "mode": "read_only_trade_autopsy_and_walk_forward_replay",
        "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "execution_enabled": False,
        "can_submit_orders": False,
        "automatic_parameter_changes": False,
        "candidates_path": str(candidates_path),
        "fee_pct_per_trade": fee_pct,
        "resolved_lifecycles": len(lives),
        "diagnosis_counts": dict(diagnosis_counts),
        "baseline_metrics": exit_lab._cohort_metrics(baseline),
        "oracle_hindsight_ceiling": {
            "metrics": exit_lab._cohort_metrics(oracle),
            "execution_authority": "none_hindsight_diagnostic_only",
        },
        "policy_attribution": policy_attribution,
        "entry_feature_attribution": entry_feature_attribution(lives, fee_pct=fee_pct),
        "entry_timing_counterfactuals": evaluate_entry_timing_variants(lives, fee_pct=fee_pct),
        "walk_forward": walk_forward_replay(lives, fee_pct=fee_pct, min_train_dates=min_train_dates),
        "trade_autopsies": autopsies,
        "promotion_authority": "none_report_may_only_propose_separate_forward_paper_trial",
        "notes": [
            "Oracle-best results use future marks and must never drive execution.",
            "Walk-forward selections use only dates strictly earlier than each test date.",
            "A losing trade that never had positive executable MFE is an entry problem, not an exit problem.",
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
    parser.add_argument("--min-train-dates", type=int, default=MIN_TRAIN_DATES)
    args = parser.parse_args()
    report = build_report(args.candidates, fee_pct=args.fee_pct, min_train_dates=args.min_train_dates)
    write_report(report, args.out)
    walk = report["walk_forward"]
    print(json.dumps({
        "resolved_lifecycles": report["resolved_lifecycles"],
        "diagnosis_counts": report["diagnosis_counts"],
        "baseline_metrics": report["baseline_metrics"],
        "oracle_hindsight_ceiling": report["oracle_hindsight_ceiling"],
        "entry_timing_counterfactuals": report["entry_timing_counterfactuals"],
        "worst_entry_feature_buckets": report["entry_feature_attribution"]["ranked_risk_to_opportunity"][:10],
        "walk_forward": {key: value for key, value in walk.items() if key not in {"folds", "outcomes"}},
        "report": str(args.out),
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

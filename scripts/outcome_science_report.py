"""Build a read-only attribution ledger for every completed bot outcome.

Attributions are observational hypotheses, not causal proof. The report never
changes strategy settings and never calls an execution interface.
"""
from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

try:
    from flip_shadow_pnl_evaluator import LOG_PATH as SHADOW_LOG_PATH
    from flip_shadow_pnl_evaluator import _read_jsonl, _row_key, evaluate_group
except ModuleNotFoundError:
    from scripts.flip_shadow_pnl_evaluator import LOG_PATH as SHADOW_LOG_PATH
    from scripts.flip_shadow_pnl_evaluator import _read_jsonl, _row_key, evaluate_group

ROOT = Path(__file__).resolve().parent.parent
VIBE_HOME = Path.home() / ".vibe-trading"
WEATHER_STATE_PATH = VIBE_HOME / "polymarket-weather-paper-state.json"
LIVE_POSTMORTEM_LOG_PATH = ROOT / "data" / "closed_trade_postmortem_log.jsonl"
REPORT_PATH = VIBE_HOME / "reports" / "outcome-science-report.json"
LOG_PATH = ROOT / "data" / "outcome_science_report_log.jsonl"
MIN_PATTERN_SAMPLES = 10


def _safe_float(value: Any) -> float | None:
    try:
        if value in (None, ""):
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _read_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        return payload if isinstance(payload, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def _time_window(bucket: Any) -> str:
    raw = str(bucket or "")
    try:
        hour, minute = (int(part) for part in raw.split(":", 1))
        value = hour * 60 + minute
    except (TypeError, ValueError):
        return "unknown"
    if value < 10 * 60:
        return "open_to_1000_et"
    if value < 12 * 60:
        return "1000_to_noon_et"
    if value < 13 * 60 + 30:
        return "lunch_1200_to_1330_et"
    return "after_1330_et"


def _spread_pct(trade: dict[str, Any]) -> float | None:
    feature = trade.get("feature_snapshot") if isinstance(trade.get("feature_snapshot"), dict) else {}
    cents = _safe_float(feature.get("spread_cents_at_signal"))
    if cents is None:
        cents = _safe_float(trade.get("best_spread_cents"))
    entry = _safe_float(trade.get("executable_entry_ask")) or _safe_float(trade.get("entry_price"))
    if cents is None or not entry or entry <= 0:
        return None
    return round((cents / 100.0) / entry, 4)


def _orb_alignment(trade: dict[str, Any]) -> str:
    feature = trade.get("feature_snapshot") if isinstance(trade.get("feature_snapshot"), dict) else {}
    orb = str(feature.get("orb_direction") or "").lower()
    right = str(trade.get("right") or "").upper()
    if not orb:
        return "unavailable"
    aligned = (right == "CALL" and orb == "bull") or (right == "PUT" and orb == "bear")
    return "aligned" if aligned else "conflicted"


def attribute_flip_shadow(trade: dict[str, Any]) -> dict[str, Any]:
    exit_return = float(trade.get("evidence_exit_return_pct") or 0.0)
    best_return = (
        float(trade.get("cost_adjusted_best_return_pct") or 0.0)
        if trade.get("executable_quote_coverage") is True
        else float(trade.get("return_pct") or 0.0)
    )
    spread_pct = _spread_pct(trade)
    wide_spread = spread_pct is not None and spread_pct > 0.10
    quote_complete = trade.get("executable_quote_coverage") is True
    alignment = _orb_alignment(trade)
    exit_reason = str(trade.get("cost_adjusted_exit_reason") or trade.get("logged_exit_reason") or "unknown")
    outcome = "win" if exit_return > 0 else "loss" if exit_return < 0 else "flat"

    if outcome == "win" and exit_reason.startswith("target_"):
        primary = "target_reached"
    elif outcome == "win" and "ratchet" in exit_reason:
        primary = "runner_captured_by_ratchet"
    elif outcome == "win":
        primary = "directional_followthrough_before_exit"
    elif best_return >= 25:
        primary = "profitable_path_reversed_before_exit"
    elif best_return <= 5:
        primary = "signal_failed_without_favorable_excursion"
    else:
        primary = "insufficient_followthrough_then_adverse_move"

    concerns: list[str] = []
    if not quote_complete:
        concerns.append("incomplete_executable_quote_path")
    if wide_spread:
        concerns.append("entry_spread_over_10pct")
    if alignment == "conflicted":
        concerns.append("orb_direction_conflicted_with_contract")
    if alignment == "unavailable":
        concerns.append("orb_direction_unavailable")

    clean_process = quote_complete and not wide_spread and alignment == "aligned"
    if clean_process and outcome == "win":
        process = "process_supported_positive_outcome"
    elif clean_process and outcome != "win":
        process = "valid_process_negative_outcome"
    elif outcome == "win":
        process = "positive_outcome_process_unproven"
    else:
        process = "process_concern_negative_outcome"

    feature = trade.get("feature_snapshot") if isinstance(trade.get("feature_snapshot"), dict) else {}
    observed_feature_count = sum(
        feature.get(key) not in (None, "", "unavailable")
        for key in (
            "orb_direction",
            "orb_breakout_candle_atr_ratio",
            "expected_move_consumed_fraction",
            "opening_range_fraction",
            "quote_age_seconds",
        )
    )
    confidence = "high" if quote_complete and observed_feature_count >= 4 else "medium" if quote_complete else "low"
    return {
        "outcome_id": trade.get("lifecycle_id") or trade.get("option_symbol"),
        "source": "flip_shadow",
        "date": trade.get("date"),
        "symbol": trade.get("symbol"),
        "right": trade.get("right"),
        "strategy": trade.get("strategy"),
        "time_window": _time_window(trade.get("episode_bucket_et")),
        "outcome": outcome,
        "pnl_basis": "shadow_entry_ask_exit_bid" if quote_complete else "shadow_midpoint_fallback",
        "return_pct": round(exit_return, 2),
        "best_return_pct": round(best_return, 2),
        "giveback_pct": round(max(0.0, best_return - exit_return), 2),
        "exit_reason": exit_reason,
        "primary_attribution_hypothesis": primary,
        "process_classification": process,
        "attribution_confidence": confidence,
        "observed_evidence": {
            "orb_alignment": alignment,
            "spread_pct": spread_pct,
            "executable_quote_coverage": quote_complete,
            "quote_age_seconds": feature.get("quote_age_seconds"),
            "orb_breakout_candle_atr_ratio": feature.get("orb_breakout_candle_atr_ratio"),
            "expected_move_consumed_fraction": feature.get("expected_move_consumed_fraction"),
            "opening_range_fraction": feature.get("opening_range_fraction"),
            "opening_range_bucket": feature.get("opening_range_bucket"),
            "catalyst": (trade.get("entry_reasoning") or {}).get("catalyst") if isinstance(trade.get("entry_reasoning"), dict) else None,
        },
        "process_concerns": concerns,
        "learner_action": "aggregate_for_review_only",
    }


def load_flip_shadow_attributions(path: Path = SHADOW_LOG_PATH) -> list[dict[str, Any]]:
    groups: dict[tuple[str, ...], list[dict[str, Any]]] = defaultdict(list)
    for row in _read_jsonl(path):
        if (
            int(row.get("schema_version") or 0) >= 2
            and row.get("data_quality") == "current_session_lifecycle"
            and row.get("execution_mode") in (None, "shadow_only")
            and row.get("symbol")
            and row.get("option_symbol")
        ):
            groups[_row_key(row)].append(row)
    evaluated = [evaluate_group(rows) for rows in groups.values()]
    return [attribute_flip_shadow(row) for row in evaluated if row.get("status") in {"winner", "loser"}]


def load_live_attributions(path: Path = LIVE_POSTMORTEM_LOG_PATH) -> list[dict[str, Any]]:
    latest_by_id: dict[str, dict[str, Any]] = {}
    for snapshot in _read_jsonl(path):
        rows = snapshot.get("postmortems") if isinstance(snapshot.get("postmortems"), list) else []
        for row in rows:
            if not isinstance(row, dict):
                continue
            outcome_id = str(row.get("trade_id") or "")
            if not outcome_id:
                continue
            explanation = row.get("pnl_explanation") if isinstance(row.get("pnl_explanation"), dict) else {}
            outcome_raw = str(explanation.get("outcome") or "unknown")
            outcome = "win" if outcome_raw == "profit" else "loss" if outcome_raw == "loss" else outcome_raw
            pnl = _safe_float(row.get("pnl"))
            if outcome not in {"win", "loss", "flat"} and pnl is not None:
                outcome = "win" if pnl > 0 else "loss" if pnl < 0 else "flat"
            score = int(row.get("score") or 0)
            process = (
                "process_supported_positive_outcome" if outcome == "win" and score >= 7
                else "valid_process_negative_outcome" if outcome == "loss" and score >= 7
                else "positive_outcome_process_unproven" if outcome == "win"
                else "process_concern_negative_outcome" if outcome == "loss"
                else "process_unclassified"
            )
            latest_by_id[outcome_id] = {
                "outcome_id": outcome_id,
                "source": "live_options",
                "date": row.get("date"),
                "symbol": row.get("symbol"),
                "strategy": row.get("strategy"),
                "outcome": outcome,
                "pnl_dollars": pnl,
                "pnl_basis": explanation.get("pnl_source"),
                "primary_attribution_hypothesis": explanation.get("primary_driver") or "closed_outcome_driver_unclassified",
                "process_classification": process,
                "attribution_confidence": "medium",
                "observed_evidence": explanation.get("evidence") or [],
                "process_concerns": row.get("reasons") or [],
                "learner_action": explanation.get("next_action") or "human_review",
            }
    return list(latest_by_id.values())


def attribute_weather(position: dict[str, Any]) -> dict[str, Any]:
    pnl = float(position.get("pnl_dollars") or 0.0)
    outcome = "win" if pnl > 0 else "loss" if pnl < 0 else "flat"
    exit_reason = str(position.get("exit_reason") or "unknown")
    agreement = position.get("entry_model_agreement") is True
    promotion_grade = position.get("promotion_grade") is True
    model_spread = _safe_float(position.get("model_probability_spread"))
    if exit_reason == "resolved_settlement" and outcome == "win":
        primary = "forecast_edge_realized_at_settlement"
    elif exit_reason == "resolved_settlement":
        primary = "forecast_probability_missed_at_settlement"
    elif exit_reason == "take_profit":
        primary = "market_repriced_toward_forecast"
    elif exit_reason == "stop_loss":
        primary = "market_repriced_against_forecast"
    elif exit_reason == "edge_closed":
        primary = "modeled_edge_converged"
    else:
        primary = f"weather_exit_{exit_reason}"
    clean_process = agreement and promotion_grade
    process = (
        "process_supported_positive_outcome" if clean_process and outcome == "win"
        else "valid_process_negative_outcome" if clean_process and outcome != "win"
        else "positive_outcome_process_unproven" if outcome == "win"
        else "process_concern_negative_outcome"
    )
    concerns = []
    if not agreement:
        concerns.append("three_model_agreement_not_proven")
    if not promotion_grade:
        concerns.append("not_promotion_grade")
    if model_spread is not None and model_spread > 0.20:
        concerns.append("model_probability_spread_over_20_points")
    return {
        "outcome_id": position.get("paper_position_id") or position.get("market_id"),
        "source": "polymarket_weather_paper",
        "date": str(position.get("exit_at") or position.get("target_date") or "")[:10],
        "symbol": position.get("station"),
        "strategy": "temperature_probability_edge",
        "outcome": outcome,
        "pnl_dollars": round(pnl, 2),
        "pnl_basis": "paper_entry_ask_exit_bid",
        "exit_reason": exit_reason,
        "primary_attribution_hypothesis": primary,
        "process_classification": process,
        "attribution_confidence": "high" if exit_reason == "resolved_settlement" and clean_process else "medium",
        "observed_evidence": {
            "entry_edge": position.get("entry_edge"),
            "entry_fair_yes": position.get("entry_fair_yes"),
            "entry_price": position.get("entry_price"),
            "entry_lead_hours": position.get("entry_lead_hours"),
            "model_probabilities": position.get("model_probabilities") or {},
            "model_probability_spread": model_spread,
            "bucket": position.get("bucket"),
            "city_slug": position.get("slug"),
        },
        "process_concerns": concerns,
        "learner_action": "aggregate_for_review_only",
    }


def load_weather_attributions(path: Path = WEATHER_STATE_PATH) -> list[dict[str, Any]]:
    state = _read_json(path)
    rows = state.get("closed_positions") if isinstance(state.get("closed_positions"), list) else []
    return [attribute_weather(row) for row in rows if isinstance(row, dict) and row.get("exit_reason")]


def _breakdown(rows: list[dict[str, Any]], key: str) -> dict[str, dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[str(row.get(key) or "unknown")].append(row)
    result: dict[str, dict[str, Any]] = {}
    for value, items in sorted(grouped.items()):
        wins = sum(item.get("outcome") == "win" for item in items)
        losses = sum(item.get("outcome") == "loss" for item in items)
        classified = wins + losses
        result[value] = {
            "count": len(items),
            "classified_count": classified,
            "wins": wins,
            "losses": losses,
            "win_rate": round(wins / classified, 3) if classified else None,
        }
    return result


def build_report(
    shadow_path: Path = SHADOW_LOG_PATH,
    live_path: Path = LIVE_POSTMORTEM_LOG_PATH,
    weather_path: Path = WEATHER_STATE_PATH,
) -> dict[str, Any]:
    outcomes = [
        *load_flip_shadow_attributions(shadow_path),
        *load_live_attributions(live_path),
        *load_weather_attributions(weather_path),
    ]
    outcomes.sort(key=lambda row: (str(row.get("date") or ""), str(row.get("outcome_id") or "")))
    reasons = Counter(str(row.get("primary_attribution_hypothesis") or "unknown") for row in outcomes)
    trial_family = {
        "signal_failed_without_favorable_excursion": "entry_filter_or_timing_trial",
        "insufficient_followthrough_then_adverse_move": "entry_timing_or_horizon_trial",
        "profitable_path_reversed_before_exit": "exit_ratchet_or_monitoring_cadence_trial",
    }
    review_candidates = [
        {
            "hypothesis": reason,
            "sample_count": count,
            "status": "eligible_for_preregistered_trial_review" if reason in trial_family else "repeated_baseline_pattern",
            "recommended_trial_family": trial_family.get(reason, "preserve_as_control_baseline"),
            "automatic_live_change_allowed": False,
        }
        for reason, count in reasons.most_common()
        if count >= MIN_PATTERN_SAMPLES
    ]
    return {
        "provider": "outcome_science_report",
        "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "mode": "read_only_learning",
        "execution_enabled": False,
        "can_submit_orders": False,
        "automatic_strategy_changes_enabled": False,
        "outcome_count": len(outcomes),
        "win_count": sum(row.get("outcome") == "win" for row in outcomes),
        "loss_count": sum(row.get("outcome") == "loss" for row in outcomes),
        "flat_or_unclassified_count": sum(row.get("outcome") not in {"win", "loss"} for row in outcomes),
        "by_source": _breakdown(outcomes, "source"),
        "by_primary_attribution": _breakdown(outcomes, "primary_attribution_hypothesis"),
        "by_process_classification": _breakdown(outcomes, "process_classification"),
        "review_candidates": review_candidates,
        "outcomes": outcomes,
        "governance": {
            "minimum_pattern_samples": MIN_PATTERN_SAMPLES,
            "causal_claims_allowed": False,
            "human_review_required": True,
            "promotion_path": "repeated_pattern -> preregistered trial -> chronological holdout -> human approval",
        },
        "warnings": [
            "Attributions are observational hypotheses and can be confounded by market regime, selection, and fill assumptions.",
            "A win is not automatically good process and a loss is not automatically bad process.",
            "This report cannot alter live gates, thresholds, sizing, symbols, or execution settings.",
        ],
    }


def write_report(report: dict[str, Any], report_path: Path = REPORT_PATH, log_path: Path = LOG_PATH) -> None:
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(report, separators=(",", ":"), sort_keys=True) + "\n")


def print_report(report: dict[str, Any]) -> None:
    print("\nOutcome Science Report | read-only")
    print("=" * 72)
    print(f"outcomes={report['outcome_count']} wins={report['win_count']} losses={report['loss_count']}")
    for reason, stats in list(report["by_primary_attribution"].items())[:10]:
        print(f"{reason:48} n={stats['count']:<4} win_rate={stats['win_rate']}")
    print(f"review_candidates={len(report['review_candidates'])}; no strategy settings changed\n")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--shadow-path", type=Path, default=SHADOW_LOG_PATH)
    parser.add_argument("--live-path", type=Path, default=LIVE_POSTMORTEM_LOG_PATH)
    parser.add_argument("--weather-path", type=Path, default=WEATHER_STATE_PATH)
    parser.add_argument("--report-path", type=Path, default=REPORT_PATH)
    parser.add_argument("--log-path", type=Path, default=LOG_PATH)
    parser.add_argument("--print", action="store_true", dest="print_report")
    args = parser.parse_args()
    report = build_report(args.shadow_path, args.live_path, args.weather_path)
    write_report(report, args.report_path, args.log_path)
    if args.print_report:
        print_report(report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

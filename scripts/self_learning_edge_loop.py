#!/usr/bin/env python3
"""Deduplicated cross-bot mistake memory and shadow-only challenger loop."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts import accelerated_bot_learning_report as accelerated


VIBE_HOME = Path.home() / ".vibe-trading"
REPORT_DIR = VIBE_HOME / "reports"
LEARNING_PATH = REPORT_DIR / "accelerated-bot-learning.json"
WATCHDOG_PATH = REPORT_DIR / "bot-behavior-regression-watchdog.json"
AUDIT_PATH = REPORT_DIR / "adversarial-strategy-audit.json"
LEDGER_PATH = ROOT / "data" / "self_learning_mistake_ledger.jsonl"
REPORT_PATH = REPORT_DIR / "self-learning-edge-loop.json"
LOG_PATH = ROOT / "data" / "self_learning_edge_loop_log.jsonl"
SHADOW_PATH = ROOT / "data" / "flip_shadow_candidates_log.jsonl"
FLIP_STATE_PATH = VIBE_HOME / "flip-trades.json"
FRESH_RETEST_PLAN = ROOT / "research" / "edge_trials" / "fresh_orb_retest_forward_plan_2026-07-20.json"


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            value = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            rows.append(value)
    return rows


def _alpaca_execution_evidence(path: Path) -> dict[str, Any]:
    if not path.exists():
        trades: list[dict[str, Any]] = []
    else:
        try:
            payload = json.loads(path.read_text(encoding="utf-8-sig"))
        except (OSError, json.JSONDecodeError):
            payload = []
        trades = [row for row in payload if isinstance(row, dict)] if isinstance(payload, list) else []

    evidence = [
        row["entry_execution_evidence"]
        for row in trades
        if isinstance(row.get("entry_execution_evidence"), dict)
    ]
    delays = [
        float(row["submit_to_fill_seconds"])
        for row in evidence
        if row.get("submit_to_fill_seconds") is not None
    ]
    submit_slippage = [
        float(row["fill_vs_submit_ask_pct"])
        for row in evidence
        if row.get("fill_vs_submit_ask_pct") is not None
    ]
    signal_slippage = [
        float(row["fill_vs_signal_ask_pct"])
        for row in evidence
        if row.get("fill_vs_signal_ask_pct") is not None
    ]
    fresh_retests = [row for row in evidence if row.get("entry_evidence_gate") == "passed_fresh_orb_retest"]
    return {
        "source": str(path),
        "trade_count": len(trades),
        "execution_evidence_count": len(evidence),
        "missing_execution_evidence_count": len(trades) - len(evidence),
        "fresh_orb_retest_fill_count": len(fresh_retests),
        "broker_confirmed_fill_count": sum(bool(row.get("entry_fill_confirmed")) for row in trades),
        "average_submit_to_fill_seconds": round(sum(delays) / len(delays), 3) if delays else None,
        "average_fill_vs_submit_ask_pct": round(sum(submit_slippage) / len(submit_slippage), 3) if submit_slippage else None,
        "average_fill_vs_signal_ask_pct": round(sum(signal_slippage) / len(signal_slippage), 3) if signal_slippage else None,
        "fills_above_3pct_submit_slippage": sum(value > 3.0 for value in submit_slippage),
        "authority": "observed_alpaca_execution_diagnostics_only",
        "automatic_parameter_changes_allowed": False,
    }


def _stable_id(payload: dict[str, Any]) -> str:
    raw = json.dumps(payload, separators=(",", ":"), sort_keys=True)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:20]


def _shadow_failure_context(failure: dict[str, Any]) -> dict[str, Any]:
    features = failure.get("feature_snapshot") if isinstance(failure.get("feature_snapshot"), dict) else {}
    if not features:
        reasoning = failure.get("entry_reasoning") if isinstance(failure.get("entry_reasoning"), dict) else {}
        features = reasoning.get("feature_snapshot") if isinstance(reasoning.get("feature_snapshot"), dict) else {}
    right = str(failure.get("right") or features.get("right") or "unknown").upper()
    bucket = str(failure.get("episode_bucket_et") or "unknown")
    try:
        hour, minute = (int(value) for value in bucket.split(":", 1))
        total_minutes = hour * 60 + minute
        session = "opening" if total_minutes < 10 * 60 + 30 else "midday" if total_minutes < 12 * 60 + 30 else "late"
    except (TypeError, ValueError):
        session = "unknown"
    if right == "CALL":
        aligned = all(features.get(name) is True for name in ("above_vwap", "above_ema50", "ema50_sloping_up"))
    elif right == "PUT":
        aligned = all(features.get(name) is True for name in ("below_vwap", "below_ema50", "ema50_sloping_down"))
    else:
        aligned = False
    try:
        consumed = float(features.get("expected_move_consumed_fraction"))
        expected_move_bucket = "ge_0_70" if consumed >= 0.70 else "0_50_to_0_70" if consumed >= 0.50 else "lt_0_50"
    except (TypeError, ValueError):
        expected_move_bucket = "unknown"
    try:
        spread = float(features.get("spread_cents_at_signal") or (failure.get("entry_reasoning") or {}).get("spread_cents"))
        spread_bucket = "wide_ge_10" if spread >= 10 else "medium_6_to_9" if spread >= 6 else "tight_le_5"
    except (TypeError, ValueError):
        spread_bucket = "unknown"
    return {
        "right": right,
        "session": session,
        "entry_pattern": str(features.get("orb_entry_pattern") or "unknown"),
        "retest_status": str(features.get("orb_retest_status") or "unknown"),
        "trend_alignment": "confirmed" if aligned else "unconfirmed",
        "expected_move_bucket": expected_move_bucket,
        "spread_bucket": spread_bucket,
    }


def _proposed_shadow_change(lesson: str, context: dict[str, Any]) -> str:
    if "surrendered" in lesson:
        return "compare_earlier_profit_ratchet_vs_frozen_exit"
    if not context:
        if "credit" in lesson:
            return "compare_credit_spread_stop_timing_75_100_125pct"
        if "sizing within current cap" in lesson:
            return "require_stronger_entry_regime_confirmation"
        return "manual_strategy_specific_review"
    if (
        context.get("entry_pattern") == "raw_breakout"
        and context.get("retest_status") in {"retest_stale", "retest_missing", "unknown"}
    ):
        return "require_fresh_orb_retest"
    if context.get("trend_alignment") == "unconfirmed":
        return "require_directional_vwap_ema_alignment"
    if context.get("expected_move_bucket") == "ge_0_70":
        return "veto_expected_move_consumed_ge_0_70"
    if context.get("session") == "late":
        return "restrict_new_entries_before_12_30_et"
    if context.get("spread_bucket") == "wide_ge_10":
        return "require_entry_spread_below_10_cents"
    return "require_breakout_follow_through_confirmation"


def _cohort_metrics(rows: list[dict[str, Any]]) -> dict[str, Any]:
    values = [float(row.get("evidence_exit_return_pct") or 0.0) for row in rows]
    by_date: dict[str, list[float]] = {}
    for row, value in zip(rows, values):
        by_date.setdefault(str(row.get("date") or "unknown"), []).append(value)
    daily = [sum(day) / len(day) for day in by_date.values() if day]
    return {
        "completed_count": len(values),
        "trading_day_count": len(daily),
        "win_rate": round(sum(value > 0 for value in values) / len(values), 3) if values else None,
        "expectancy_return_pct": round(sum(values) / len(values), 3) if values else None,
        "date_clustered_expectancy_return_pct": round(sum(daily) / len(daily), 3) if daily else None,
    }


def _orb_retest_contrast(shadow_path: Path) -> dict[str, Any]:
    trades = accelerated._shadow_trades(shadow_path)
    fresh, raw = [], []
    for trade in trades:
        features = trade.get("feature_snapshot") if isinstance(trade.get("feature_snapshot"), dict) else {}
        pattern = str(features.get("orb_entry_pattern") or "")
        status = str(features.get("orb_retest_status") or "")
        if pattern == "breakout_retest" and status == "retest_confirmed_fresh":
            fresh.append(trade)
        elif pattern == "raw_breakout":
            raw.append(trade)
    fresh_metrics = _cohort_metrics(fresh)
    raw_metrics = _cohort_metrics(raw)
    fresh_expectancy = fresh_metrics.get("expectancy_return_pct")
    raw_expectancy = raw_metrics.get("expectancy_return_pct")
    gate_passed = fresh_metrics["completed_count"] >= 30 and fresh_metrics["trading_day_count"] >= 20
    return {
        "metric_basis": "cost_adjusted_option_contract_return_not_account_pnl",
        "fresh_confirmed_retest": fresh_metrics,
        "raw_unconfirmed_breakout": raw_metrics,
        "fresh_minus_raw_expectancy_pct": (
            round(float(fresh_expectancy) - float(raw_expectancy), 3)
            if fresh_expectancy is not None and raw_expectancy is not None else None
        ),
        "minimum_completed_required": 30,
        "minimum_trading_days_required": 20,
        "evidence_gate_passed": gate_passed,
        "interpretation": (
            "fresh_retest_forward_gate_satisfied_human_review_only"
            if gate_passed and (fresh_expectancy or 0) > 0
            else "fresh_retest_leading_but_sample_insufficient"
            if (fresh_expectancy or 0) > (raw_expectancy or 0)
            else "fresh_retest_not_leading"
        ),
        "production_config_mutation_allowed": False,
    }


def _aggregate_nominations(patterns: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for row in patterns:
        grouped.setdefault(str(row["proposed_shadow_change"]), []).append(row)
    nominations = []
    for proposed_change, rows in grouped.items():
        rows = sorted(rows, key=lambda row: int(row.get("occurrences") or 0), reverse=True)
        nominations.append({
            "proposed_shadow_change": proposed_change,
            "supporting_occurrences": sum(int(row.get("occurrences") or 0) for row in rows),
            "supporting_cluster_count": len(rows),
            "top_clusters": [
                {"occurrences": row.get("occurrences"), "context": row.get("context") or {}, "lesson": row.get("lesson")}
                for row in rows[:5]
            ],
            "minimum_forward_outcomes": 30,
            "minimum_forward_trading_days": 20,
            "preregistration_required": True,
            "authority": "shadow_challenger_only",
            "production_config_mutation_allowed": False,
        })
    return sorted(nominations, key=lambda row: row["supporting_occurrences"], reverse=True)


def _active_trial_lifecycle(audit: dict[str, Any]) -> dict[str, Any]:
    subject = (audit.get("by_subject") or {}).get("fresh-orb-retest-options") or {}
    diagnostics = subject.get("diagnostics") if isinstance(subject.get("diagnostics"), dict) else {}
    validation = int(diagnostics.get("final_trade_count") or 0)
    forward = int(diagnostics.get("forward_trade_count") or 0)
    if not subject:
        stage = "manifest_missing"
        next_action = "build_fail_closed_runtime_manifest"
    elif validation < 30:
        stage = "collecting_validation"
        next_action = "accumulate_first_30_oos_delayed_entry_outcomes"
    elif forward < 30:
        stage = "collecting_forward"
        next_action = "freeze_validation_then_accumulate_30_later_forward_outcomes"
    elif not subject.get("passed"):
        stage = "adversarial_repairs_required"
        next_action = "repair_failed_evidence_checks_without_retuning_consumed_returns"
    else:
        stage = "human_review_eligible"
        next_action = "independent_human_review_no_automatic_promotion"
    return {
        "subject_id": "fresh-orb-retest-options",
        "stage": stage,
        "validation_progress": f"{validation}/30",
        "forward_progress": f"{forward}/30",
        "adversarial_score_out_of_10": subject.get("score_out_of_10"),
        "adversarial_passed": subject.get("passed") is True,
        "failed_checks": subject.get("failed_checks") or [],
        "next_action": next_action,
        "automatic_promotion_allowed": False,
    }


def _mistakes(learning: dict[str, Any], watchdog: dict[str, Any], audit: dict[str, Any]) -> list[dict[str, Any]]:
    rows = []
    for failure in learning.get("failure_memory") or []:
        if not isinstance(failure, dict):
            continue
        identity = {
            "source": failure.get("source"),
            "trade_id": failure.get("trade_id") or failure.get("lifecycle_id"),
            "date": failure.get("date"),
            "symbol": failure.get("symbol"),
        }
        lesson = str(failure.get("risk_lesson") or failure.get("diagnosis") or "unclassified_trade_failure")
        context = (
            _shadow_failure_context(failure)
            if failure.get("source") == "accelerated_directional_shadow"
            else {}
        )
        pattern = {
            "source": failure.get("source"),
            "bot": failure.get("bot"),
            "strategy": failure.get("strategy"),
            "lesson": lesson,
            "context": context,
        }
        rows.append({**identity, "event_id": _stable_id(identity), "pattern_id": _stable_id(pattern),
                     "lesson": lesson, "next_action": failure.get("next_action"), "severity": "review",
                     "context": context})
    mismatch_alert = next(
        (
            alert for alert in watchdog.get("alerts") or []
            if isinstance(alert, dict) and alert.get("code") == "setup_agnostic_gate_mismatch"
        ),
        {},
    )
    mismatch_severity = str(mismatch_alert.get("severity") or "high")
    for example in watchdog.get("setup_mismatch_examples") or []:
        if not isinstance(example, dict):
            continue
        for issue in example.get("issues") or []:
            identity = {"source": "behavior_watchdog", "ts": example.get("ts"), "symbol": example.get("symbol"), "issue": issue}
            pattern = {"source": "behavior_watchdog", "strategy": example.get("strategy"), "issue": issue}
            rows.append({**identity, "event_id": _stable_id(identity), "pattern_id": _stable_id(pattern),
                         "lesson": str(issue), "next_action": "nominate_regression_fix_and_replay",
                         "severity": mismatch_severity})
    for subject in audit.get("subjects") or []:
        if not isinstance(subject, dict) or subject.get("passed"):
            continue
        for check in subject.get("failed_checks") or []:
            identity = {"source": "adversarial_audit", "subject_id": subject.get("subject_id"),
                        "strategy_version": subject.get("strategy_version"), "check": check}
            pattern = dict(identity)
            rows.append({**identity, "event_id": _stable_id(identity), "pattern_id": _stable_id(pattern),
                         "lesson": f"adversarial_check_failed:{check}",
                         "next_action": "repair_evidence_or_strategy_in_shadow_then_reaudit", "severity": "high"})
    return rows


def build_report(
    learning_path: Path = LEARNING_PATH,
    watchdog_path: Path = WATCHDOG_PATH,
    audit_path: Path = AUDIT_PATH,
    ledger_path: Path = LEDGER_PATH,
    shadow_path: Path = SHADOW_PATH,
    flip_state_path: Path = FLIP_STATE_PATH,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    existing = _read_jsonl(ledger_path)
    known = {row.get("event_id") for row in existing}
    learning = _read_json(learning_path)
    watchdog = _read_json(watchdog_path)
    audit = _read_json(audit_path)
    discovered = _mistakes(learning, watchdog, audit)
    new_rows = [row for row in discovered if row["event_id"] not in known]
    # The immutable event remains unchanged, while current watchdog lifecycle
    # can downgrade a repaired issue from high to decaying in today's report.
    current_by_event = {row["event_id"]: row for row in discovered}
    effective_existing = []
    for row in existing:
        current = current_by_event.get(row.get("event_id"), {})
        # The ledger stays immutable. Reporting may apply a newer classifier to
        # the same event so repaired bugs decay and broad loss labels become
        # useful feature/regime clusters.
        effective_existing.append({
            **row,
            "severity": current.get("severity", row.get("severity")),
            "pattern_id": current.get("pattern_id", row.get("pattern_id")),
            "context": current.get("context", row.get("context") or {}),
        })
    all_rows = effective_existing + new_rows
    counts = Counter(row.get("pattern_id") for row in all_rows if row.get("pattern_id"))
    latest_by_pattern = {row["pattern_id"]: row for row in all_rows if row.get("pattern_id")}
    repeated = []
    for pattern_id, count in counts.most_common():
        if count < 2:
            continue
        row = latest_by_pattern[pattern_id]
        repeated.append({
            "pattern_id": pattern_id,
            "occurrences": count,
            "lesson": row.get("lesson"),
            "severity": row.get("severity"),
            "next_action": row.get("next_action"),
            "context": row.get("context") or {},
            "proposed_shadow_change": _proposed_shadow_change(str(row.get("lesson") or ""), row.get("context") or {}),
            "minimum_forward_outcomes": 30,
            "preregistration_required": True,
            "authority": "shadow_challenger_only",
            "production_config_mutation_allowed": False,
        })
    critical = [row for row in repeated if row.get("severity") in {"high", "critical"}]
    actionable = [row for row in repeated if row.get("severity") not in {"decaying", "resolved"}]
    historical = [row for row in repeated if row.get("severity") in {"decaying", "resolved"}]
    nominations = _aggregate_nominations(actionable)
    retest_contrast = _orb_retest_contrast(shadow_path)
    execution_evidence = _alpaca_execution_evidence(flip_state_path)
    trial_lifecycle = _active_trial_lifecycle(audit)
    report = {
        "provider": "self_learning_edge_loop",
        "mode": "read_only_memory_and_shadow_nominations",
        "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "execution_enabled": False,
        "can_submit_orders": False,
        "automatic_parameter_changes": False,
        "summary": {
            "mistake_event_count": len(all_rows),
            "new_mistake_count": len(new_rows),
            "repeated_pattern_count": len(repeated),
            "actionable_pattern_count": len(actionable),
            "actionable_challenger_count": len(nominations),
            "historical_resolved_pattern_count": len(historical),
            "critical_unresolved_pattern_count": len(critical),
        },
        "repeated_patterns": repeated,
        "shadow_challenger_nominations": nominations,
        "historical_resolved_patterns": historical,
        "contrastive_evidence": {"orb_fresh_retest_vs_raw_breakout": retest_contrast},
        "alpaca_execution_evidence": execution_evidence,
        "active_preregistered_trial": {
            "plan_id": "fresh-orb-retest-forward-2026-07-20",
            "path": str(FRESH_RETEST_PLAN),
            "exists": FRESH_RETEST_PLAN.exists(),
        },
        "trial_lifecycle": trial_lifecycle,
        "highest_value_next_step": trial_lifecycle["next_action"],
        "promotion_blockers": ["unresolved_repeated_high_severity_mistakes"] if critical else [],
        "learning_contract": {
            "observe": "Ingest completed actual/shadow outcomes, watchdog mismatches, and adversarial failures.",
            "remember": "Append stable event and pattern identifiers; never erase losing evidence.",
            "propose": "Repeated patterns may nominate one preregistered shadow challenger.",
            "verify": "Every challenger must pass independent adversarial and forward gates.",
            "promote": "Human review only; no self-approval or live configuration mutation.",
        },
    }
    return report, new_rows


def write_outputs(report: dict[str, Any], new_rows: list[dict[str, Any]], ledger_path: Path = LEDGER_PATH,
                  report_path: Path = REPORT_PATH, log_path: Path = LOG_PATH) -> None:
    ledger_path.parent.mkdir(parents=True, exist_ok=True)
    if new_rows:
        with ledger_path.open("a", encoding="utf-8") as handle:
            for row in new_rows:
                handle.write(json.dumps(row, separators=(",", ":"), sort_keys=True) + "\n")
    report_path.parent.mkdir(parents=True, exist_ok=True)
    temp = report_path.with_suffix(report_path.suffix + ".tmp")
    temp.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(temp, report_path)
    with log_path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(report, separators=(",", ":"), sort_keys=True) + "\n")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--print", action="store_true", dest="do_print")
    args = parser.parse_args()
    report, new_rows = build_report()
    write_outputs(report, new_rows)
    if args.do_print:
        print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

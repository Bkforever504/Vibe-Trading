"""Read-only calibration and recovery report for the Flip options bot.

The report deliberately separates realized option P&L from underlying-only
counterfactuals. It never changes strategy settings or submits orders.
"""
from __future__ import annotations

import argparse
import json
import math
import re
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable


ROOT = Path(__file__).resolve().parent.parent
VIBE_HOME = Path.home() / ".vibe-trading"
DEFAULT_TRADES = VIBE_HOME / "flip-trades.json"
DEFAULT_MISSED_REVIEW = VIBE_HOME / "reports" / "flip-decision-missed-banger-review.json"
DEFAULT_REPORT = VIBE_HOME / "reports" / "edge-recovery-report.json"
DEFAULT_LOG = ROOT / "data" / "edge_recovery_report_log.jsonl"
POST_HARDENING_START = "2026-06-29"
CONFIDENCE_PATTERN = re.compile(r"(?<!\d)(\d+(?:\.\d+)?)\s*/\s*10(?!\d)")


def _finite(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _load_json(path: Path, fallback: Any) -> Any:
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        return fallback
    return value


def extract_confidence(trade: dict[str, Any]) -> tuple[float | None, str]:
    entry_quality = trade.get("entry_quality") if isinstance(trade.get("entry_quality"), dict) else {}
    snapshot = entry_quality.get("feature_snapshot") if isinstance(entry_quality.get("feature_snapshot"), dict) else {}
    structured = _finite(snapshot.get("confidence"))
    if structured is not None:
        return min(10.0, max(0.0, structured)), "structured_entry_snapshot"
    catalyst = str(trade.get("catalyst") or "")
    match = CONFIDENCE_PATTERN.search(catalyst)
    if match:
        return min(10.0, max(0.0, float(match.group(1)))), "inferred_from_catalyst"
    return None, "missing"


def calibration_summary(predictions: Iterable[float], outcomes: Iterable[int]) -> dict[str, Any]:
    pairs = [(min(1.0, max(0.0, float(p))), int(y)) for p, y in zip(predictions, outcomes)]
    if not pairs:
        return {"sample_count": 0, "status": "insufficient_data"}
    probabilities = [p for p, _ in pairs]
    labels = [y for _, y in pairs]
    observed = sum(labels) / len(labels)
    predicted = sum(probabilities) / len(probabilities)
    brier = sum((p - y) ** 2 for p, y in pairs) / len(pairs)
    base_brier = sum((observed - y) ** 2 for y in labels) / len(labels)
    skill = None if base_brier == 0 else 1.0 - brier / base_brier
    unique = sorted({round(p, 6) for p in probabilities})
    return {
        "sample_count": len(pairs),
        "mean_predicted_win_probability": round(predicted, 4),
        "observed_win_rate": round(observed, 4),
        "calibration_gap": round(predicted - observed, 4),
        "brier_score": round(brier, 4),
        "base_rate_brier_score": round(base_brier, 4),
        "brier_skill_vs_constant_base_rate": round(skill, 4) if skill is not None else None,
        "unique_prediction_count": len(unique),
        "discrimination_status": "unmeasurable_saturated_score" if len(unique) < 2 else "measurable",
        "status": "not_calibrated" if abs(predicted - observed) > 0.10 or (skill is not None and skill <= 0) else "provisionally_calibrated",
    }


def _trade_stats(trades: list[dict[str, Any]]) -> dict[str, Any]:
    pnls = [float(t["pnl"]) for t in trades]
    wins = sum(p > 0 for p in pnls)
    gross_profit = sum(p for p in pnls if p > 0)
    gross_loss = -sum(p for p in pnls if p < 0)
    return {
        "trade_count": len(pnls),
        "wins": wins,
        "losses": sum(p < 0 for p in pnls),
        "win_rate": round(wins / len(pnls), 4) if pnls else None,
        "net_pnl": round(sum(pnls), 2),
        "expectancy": round(sum(pnls) / len(pnls), 2) if pnls else None,
        "profit_factor": round(gross_profit / gross_loss, 4) if gross_loss else None,
    }


def split_at_profit_peak(trades: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
    if not trades:
        return [], [], {"status": "no_trades"}
    cumulative = 0.0
    peak = float("-inf")
    peak_index = 0
    for index, trade in enumerate(trades):
        cumulative += float(trade["pnl"])
        if cumulative > peak:
            peak = cumulative
            peak_index = index
    return (
        trades[: peak_index + 1],
        trades[peak_index + 1 :],
        {
            "method": "first_maximum_cumulative_realized_pnl",
            "peak_trade_index": peak_index + 1,
            "peak_date": trades[peak_index]["entry_date"],
            "peak_cumulative_pnl": round(peak, 2),
        },
    )


def consensus_counterfactual(trades: list[dict[str, Any]]) -> dict[str, Any]:
    observed: list[dict[str, Any]] = []
    for trade in trades:
        consensus = trade.get("shadow_consensus") if isinstance(trade.get("shadow_consensus"), dict) else {}
        if str(consensus.get("recommendation") or "").lower() != "stand_aside":
            continue
        pnl = _finite(trade.get("pnl"))
        if pnl is None:
            continue
        blockers = {str(item) for item in consensus.get("blockers") or []}
        observed.append({
            "trade_id": trade.get("id"),
            "date": trade.get("entry_date"),
            "pnl": round(pnl, 2),
            "blocker_count": len(blockers),
        })
    avoided = -sum(float(row["pnl"]) for row in observed)
    return {
        "observed_trade_count": len(observed),
        "observed_net_pnl": round(sum(float(row["pnl"]) for row in observed), 2),
        "strict_veto_counterfactual_pnl_delta": round(avoided, 2),
        "would_have_avoided_losses": sum(float(row["pnl"]) < 0 for row in observed),
        "would_have_skipped_winners": sum(float(row["pnl"]) > 0 for row in observed),
        "trades": observed,
        "evidence_status": "insufficient_for_authority" if len(observed) < 30 else "review_for_preregistration",
        "warning": "Counterfactual uses realized trades only and is selection-biased; it cannot establish that every stand_aside should veto.",
    }


def blocker_proxy_summary(evaluations: list[dict[str, Any]]) -> dict[str, Any]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in evaluations:
        if row.get("outcome_status") != "observed" or row.get("direction") not in {"bull", "bear"}:
            continue
        if _finite(row.get("directional_end_move_pct")) is None:
            continue
        grouped[str(row.get("reason") or "unknown")].append(row)
    summaries = []
    for reason, rows in grouped.items():
        end_moves = [float(row["directional_end_move_pct"]) for row in rows]
        favorable = [float(row.get("max_favorable_underlying_pct") or 0.0) for row in rows]
        adverse = [float(row.get("max_adverse_underlying_pct") or 0.0) for row in rows]
        summaries.append({
            "reason": reason,
            "observed_count": len(rows),
            "blocked_direction_finished_favorable": sum(value > 0 for value in end_moves),
            "blocked_direction_finished_adverse": sum(value < 0 for value in end_moves),
            "directional_end_hit_rate": round(sum(value > 0 for value in end_moves) / len(rows), 4),
            "avg_directional_end_move_pct": round(sum(end_moves) / len(rows), 4),
            "avg_max_favorable_underlying_pct": round(sum(favorable) / len(rows), 4),
            "avg_max_adverse_underlying_pct": round(sum(adverse) / len(rows), 4),
        })
    summaries.sort(key=lambda row: (-int(row["observed_count"]), str(row["reason"])))
    return {
        "evidence_kind": "underlying_5m_proxy_not_option_fill",
        "reason_summaries": summaries,
        "warning": "A favorable underlying move is not executable option P&L and does not include spread, IV, decay, or fills.",
    }


def build_report(trades_payload: Any, missed_review: dict[str, Any]) -> dict[str, Any]:
    raw_trades = trades_payload if isinstance(trades_payload, list) else []
    closed: list[dict[str, Any]] = []
    for raw in raw_trades:
        if not isinstance(raw, dict) or raw.get("status") != "closed":
            continue
        pnl = _finite(raw.get("pnl"))
        date = str(raw.get("entry_date") or "")[:10]
        if pnl is None or not date:
            continue
        closed.append({**raw, "pnl": pnl, "entry_date": date})
    closed.sort(key=lambda row: (row["entry_date"], str(row.get("entry_at") or ""), str(row.get("id") or "")))
    post = [row for row in closed if row["entry_date"] >= POST_HARDENING_START]
    predictions: list[float] = []
    outcomes: list[int] = []
    provenance = defaultdict(int)
    for trade in post:
        confidence, source = extract_confidence(trade)
        provenance[source] += 1
        if confidence is not None:
            predictions.append(confidence / 10.0)
            outcomes.append(int(float(trade["pnl"]) > 0))

    early, recent, split = split_at_profit_peak(post)
    structured = [row for row in post if extract_confidence(row)[1] == "structured_entry_snapshot"]
    missed_evaluations = missed_review.get("evaluations") if isinstance(missed_review.get("evaluations"), list) else []
    dimensions = {
        "risk_controls": 10.0,
        "realized_sample_depth": round(min(10.0, len(post) / 100.0 * 10.0), 1),
        "confidence_calibration": 0.0 if len(set(predictions)) < 2 else 3.0,
        "point_in_time_entry_telemetry": round(min(10.0, len(structured) / 30.0 * 10.0), 1),
        "independent_oos_or_forward_trials": 0.0,
    }
    overall = round(sum(dimensions.values()) / len(dimensions), 1)
    return {
        "provider": "edge_recovery_report",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "mode": "read_only_research",
        "execution_enabled": False,
        "can_submit_orders": False,
        "post_hardening_start": POST_HARDENING_START,
        "all_closed_trade_stats": _trade_stats(closed),
        "post_hardening_trade_stats": _trade_stats(post),
        "green_stretch_vs_recent": {
            "split": split,
            "through_profit_peak": _trade_stats(early),
            "after_profit_peak": _trade_stats(recent),
            "interpretation": "The sample is too small to distinguish regime decay from ordinary outcome variance.",
        },
        "confidence_calibration": {
            **calibration_summary(predictions, outcomes),
            "provenance_counts": dict(sorted(provenance.items())),
            "structured_snapshot_subset": _trade_stats(structured),
            "execution_ready": False,
            "interpretation": "A score used as confidence must vary and predict outcomes; a repeated 9/10 setup grade does neither yet.",
        },
        "consensus_veto_counterfactual": consensus_counterfactual(post),
        "blocked_trade_proxy": blocker_proxy_summary(missed_evaluations),
        "profitability_evidence_grade": {
            "score_out_of_10": overall,
            "dimensions": dimensions,
            "status": "evidence_building",
            "minimum_next_gate": "30 point-in-time trades with varying preregistered probabilities, then 100 post-hardening trades and chronological holdout evidence.",
        },
        "actions": [
            "Rename the current 0-10 value to setup_score until calibration is earned.",
            "Log a preregistered probability from a frozen model separately from setup_score.",
            "Keep the multi-warning primary consensus caution veto in paper mode and evaluate 30 blocked-versus-taken outcomes.",
            "Do not loosen gates to recreate the early winning streak; test regime and exit hypotheses independently.",
        ],
        "warnings": [
            "No result here guarantees future profit.",
            "Counterfactual block outcomes use underlying bars, not executable option fills.",
            "The post-hardening realized sample is far below a promotion-quality evidence threshold.",
        ],
    }


def write_report(report: dict[str, Any], report_path: Path, log_path: Path) -> None:
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(report, sort_keys=True) + "\n")


def main() -> int:
    parser = argparse.ArgumentParser(description="Build the read-only Flip edge recovery and confidence report.")
    parser.add_argument("--trades", type=Path, default=DEFAULT_TRADES)
    parser.add_argument("--missed-review", type=Path, default=DEFAULT_MISSED_REVIEW)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    parser.add_argument("--log", type=Path, default=DEFAULT_LOG)
    parser.add_argument("--no-log", action="store_true")
    args = parser.parse_args()
    report = build_report(_load_json(args.trades, []), _load_json(args.missed_review, {}))
    if args.no_log:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    else:
        write_report(report, args.report, args.log)
    post = report["post_hardening_trade_stats"]
    cal = report["confidence_calibration"]
    recent = report["green_stretch_vs_recent"]["after_profit_peak"]
    print(f"Post-hardening: {post['trade_count']} trades | net ${post['net_pnl']:.2f} | WR {post['win_rate']:.1%}")
    print(f"After peak: {recent['trade_count']} trades | net ${recent['net_pnl']:.2f} | WR {recent['win_rate']:.1%}")
    print(f"Confidence: {cal['status']} | Brier {cal.get('brier_score')} | unique predictions {cal.get('unique_prediction_count')}")
    print(f"Evidence grade: {report['profitability_evidence_grade']['score_out_of_10']}/10")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

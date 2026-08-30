"""Compare Flip exit policies on executable, completed shadow quote paths.

Read-only research. It never submits orders or changes live settings.
"""
from __future__ import annotations

import argparse
import math
import json
import statistics
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from strategies.flip_shadow_setup_challengers import simulate_structural_exit_tournament

try:
    from flip_shadow_pnl_evaluator import LOG_PATH as SHADOW_LOG_PATH
    from flip_shadow_pnl_evaluator import RESEARCH_ONLY_STRATEGIES, _read_jsonl, _row_key, _safe_float
except ModuleNotFoundError:
    from scripts.flip_shadow_pnl_evaluator import LOG_PATH as SHADOW_LOG_PATH
    from scripts.flip_shadow_pnl_evaluator import RESEARCH_ONLY_STRATEGIES, _read_jsonl, _row_key, _safe_float

VIBE_HOME = Path.home() / ".vibe-trading"
REPORT_PATH = VIBE_HOME / "reports" / "flip-exit-policy-comparison.json"
LOG_PATH = ROOT / "data" / "flip_exit_policy_comparison_log.jsonl"

TARGET_PCT = 75.0
STOP_PCT = -30.0
RATCHET_ARM_PCT = 40.0
RATCHET_GIVEBACK_PCT = 15.0
RUNNER_FRACTION = 0.40
MIN_PROMOTION_PATHS = 100
MIN_INDEPENDENT_DATES = 10
MIN_HOLDOUT_DATES = 3
MIN_HOLDOUT_PATHS = 20
HOLDOUT_DATE_FRACTION = 0.30


def _lock_floor(best: float) -> float:
    floor = max(25.0, best - RATCHET_GIVEBACK_PCT)
    if best >= 60.0:
        floor = max(floor, 45.0)
    elif best >= 50.0:
        floor = max(floor, 35.0)
    return floor


def simulate_path(returns: list[float], policy: str) -> dict[str, Any]:
    if not returns:
        return {"return_pct": 0.0, "reason": "no_path", "best_return_pct": 0.0}
    best = 0.0
    partial_return = 0.0
    partial_taken = False
    remaining = 1.0
    for index, current in enumerate(returns):
        best = max(best, current)
        if current <= STOP_PCT:
            total = partial_return + remaining * current
            return {"return_pct": total, "reason": "stop", "best_return_pct": best}
        if policy == "current_all_out_75" and current >= TARGET_PCT:
            return {"return_pct": current, "reason": "target_all_out", "best_return_pct": best}
        if policy == "partial_60_runner_40" and not partial_taken and current >= TARGET_PCT:
            partial_return = (1.0 - RUNNER_FRACTION) * current
            remaining = RUNNER_FRACTION
            partial_taken = True
            if index == len(returns) - 1:
                return {
                    "return_pct": partial_return + remaining * current,
                    "reason": "runner_hard_close",
                    "best_return_pct": best,
                }
            continue
        if best >= RATCHET_ARM_PCT and current <= _lock_floor(best):
            total = partial_return + remaining * current
            reason = "runner_ratchet" if partial_taken else "ratchet"
            return {"return_pct": total, "reason": reason, "best_return_pct": best}
        if index == len(returns) - 1:
            total = partial_return + remaining * current
            reason = "runner_hard_close" if partial_taken else "hard_close"
            return {"return_pct": total, "reason": reason, "best_return_pct": best}
    raise AssertionError("unreachable")


def load_executable_paths(path: Path = SHADOW_LOG_PATH) -> list[dict[str, Any]]:
    groups: dict[tuple[str, ...], list[dict[str, Any]]] = defaultdict(list)
    for row in _read_jsonl(path):
        if (
            int(row.get("schema_version") or 0) >= 3
            and row.get("data_quality") == "current_session_lifecycle"
            and row.get("execution_mode") in (None, "shadow_only")
            and row.get("symbol")
            and row.get("option_symbol")
            and str(row.get("strategy") or "") not in RESEARCH_ONLY_STRATEGIES
        ):
            groups[_row_key(row)].append(row)

    paths: list[dict[str, Any]] = []
    for rows in groups.values():
        rows.sort(key=lambda row: str(row.get("scanned_at") or ""))
        first = rows[0]
        if not any(row.get("event_type") == "shadow_exit" for row in rows):
            continue
        entry = _safe_float(first.get("selection_ask"))
        bids = [_safe_float(row.get("selection_bid")) for row in rows]
        if not entry or entry <= 0 or not bids or any(bid is None or bid <= 0 for bid in bids):
            continue
        returns = [((float(bid) - entry) / entry) * 100.0 for bid in bids]
        observations = []
        for row, bid in zip(rows, bids):
            observations.append({
                **row,
                "return_pct_at_mark": ((float(bid) - entry) / entry) * 100.0,
            })
        paths.append({
            "lifecycle_id": first.get("lifecycle_id"),
            "date": str(first.get("date") or "")[:10],
            "symbol": first.get("symbol"),
            "right": first.get("right"),
            "entry_ask": entry,
            "observation_count": len(returns),
            "returns": returns,
            "observations": observations,
        })
    return paths


def _summary(results: list[dict[str, Any]]) -> dict[str, Any]:
    values = [float(row["return_pct"]) for row in results]
    wins = [value for value in values if value > 0]
    losses = [value for value in values if value <= 0]
    gross_wins = sum(wins)
    gross_losses = abs(sum(losses))
    return {
        "sample_count": len(values),
        "win_rate": round(len(wins) / len(values), 3) if values else None,
        "avg_return_pct": round(statistics.fmean(values), 2) if values else None,
        "median_return_pct": round(statistics.median(values), 2) if values else None,
        "avg_win_return_pct": round(statistics.fmean(wins), 2) if wins else None,
        "avg_loss_return_pct": round(statistics.fmean(losses), 2) if losses else None,
        "profit_factor": round(gross_wins / gross_losses, 3) if gross_losses else None,
        "worst_return_pct": round(min(values), 2) if values else None,
        "reason_counts": dict(sorted(__import__("collections").Counter(row["reason"] for row in results).items())),
    }


def _positive_absolute_expectancy(summary: dict[str, Any]) -> bool:
    avg_return = summary.get("avg_return_pct")
    profit_factor = summary.get("profit_factor")
    return bool(
        avg_return is not None
        and float(avg_return) > 0
        and profit_factor is not None
        and float(profit_factor) > 1
    )


def _valid_path_date(value: Any) -> str | None:
    candidate = str(value or "")[:10]
    try:
        return datetime.strptime(candidate, "%Y-%m-%d").date().isoformat()
    except ValueError:
        return None


def _chronological_holdout(
    results: dict[str, list[dict[str, Any]]],
    policies: tuple[str, ...],
) -> dict[str, Any]:
    dated_rows = {
        policy: [row for row in rows if _valid_path_date(row.get("date"))]
        for policy, rows in results.items()
    }
    independent_dates = sorted({
        _valid_path_date(row.get("date"))
        for rows in dated_rows.values()
        for row in rows
        if _valid_path_date(row.get("date"))
    })
    blockers: list[str] = []
    if len(independent_dates) < MIN_INDEPENDENT_DATES:
        blockers.append("insufficient_independent_dates")

    holdout_date_count = max(
        MIN_HOLDOUT_DATES,
        math.ceil(len(independent_dates) * HOLDOUT_DATE_FRACTION),
    ) if independent_dates else 0
    if holdout_date_count >= len(independent_dates):
        training_dates: list[str] = []
        holdout_dates = independent_dates
    else:
        training_dates = independent_dates[:-holdout_date_count]
        holdout_dates = independent_dates[-holdout_date_count:]
    training_date_set = set(training_dates)
    holdout_date_set = set(holdout_dates)
    training_summaries = {
        policy: _summary([
            row for row in dated_rows[policy]
            if _valid_path_date(row.get("date")) in training_date_set
        ])
        for policy in policies
    }
    holdout_summaries = {
        policy: _summary([
            row for row in dated_rows[policy]
            if _valid_path_date(row.get("date")) in holdout_date_set
        ])
        for policy in policies
    }
    challengers = tuple(policy for policy in policies if policy != "current_all_out_75")
    candidate = max(
        challengers,
        key=lambda policy: float(training_summaries[policy]["avg_return_pct"] or -9999),
        default=None,
    ) if training_dates else None
    training_delta = None
    holdout_delta = None
    if candidate:
        training_avg = training_summaries[candidate].get("avg_return_pct")
        training_baseline_avg = training_summaries["current_all_out_75"].get("avg_return_pct")
        if training_avg is not None and training_baseline_avg is not None:
            training_delta = round(float(training_avg) - float(training_baseline_avg), 2)
        holdout_avg = holdout_summaries[candidate].get("avg_return_pct")
        holdout_baseline_avg = holdout_summaries["current_all_out_75"].get("avg_return_pct")
        if holdout_avg is not None and holdout_baseline_avg is not None:
            holdout_delta = round(float(holdout_avg) - float(holdout_baseline_avg), 2)

    holdout_path_count = (
        int(holdout_summaries[candidate].get("sample_count") or 0) if candidate else 0
    )
    if holdout_path_count < MIN_HOLDOUT_PATHS:
        blockers.append("insufficient_holdout_paths")
    if candidate is None:
        blockers.append("no_training_selected_challenger")
    else:
        if training_delta is None or training_delta <= 0:
            blockers.append("training_delta_not_positive")
        if not _positive_absolute_expectancy(training_summaries[candidate]):
            blockers.append("training_absolute_expectancy_not_positive")
        if holdout_delta is None or holdout_delta <= 0:
            blockers.append("holdout_delta_not_positive")
        if not _positive_absolute_expectancy(holdout_summaries[candidate]):
            blockers.append("holdout_absolute_expectancy_not_positive")

    return {
        "qualified": not blockers,
        "reason": "chronological_holdout_qualified" if not blockers else "chronological_holdout_blocked",
        "blockers": blockers,
        "split_method": "latest_30pct_of_unique_trading_dates",
        "candidate_selected_on": "training_dates_only",
        "minimum_independent_dates": MIN_INDEPENDENT_DATES,
        "minimum_holdout_dates": MIN_HOLDOUT_DATES,
        "minimum_holdout_paths": MIN_HOLDOUT_PATHS,
        "independent_date_count": len(independent_dates),
        "training_dates": training_dates,
        "holdout_dates": holdout_dates,
        "training_path_count": (
            int(training_summaries[candidate].get("sample_count") or 0) if candidate else 0
        ),
        "holdout_path_count": holdout_path_count,
        "candidate_policy": candidate,
        "training_candidate_summary": training_summaries.get(candidate) if candidate else None,
        "training_avg_return_delta_vs_current": training_delta,
        "holdout_candidate_summary": holdout_summaries.get(candidate) if candidate else None,
        "holdout_baseline_summary": holdout_summaries.get("current_all_out_75"),
        "holdout_avg_return_delta_vs_current": holdout_delta,
    }


def build_report(path: Path = SHADOW_LOG_PATH) -> dict[str, Any]:
    paths = load_executable_paths(path)
    policies = ("current_all_out_75", "ratchet_runner_no_target", "partial_60_runner_40")
    results: dict[str, list[dict[str, Any]]] = {policy: [] for policy in policies}
    for path_row in paths:
        for policy in policies:
            result = simulate_path(path_row["returns"], policy)
            results[policy].append({
                **result,
                "lifecycle_id": path_row["lifecycle_id"],
                "date": path_row["date"],
                "symbol": path_row["symbol"],
            })
    summaries = {policy: _summary(rows) for policy, rows in results.items()}
    baseline = summaries["current_all_out_75"]
    for policy, summary in summaries.items():
        summary["avg_return_delta_vs_current"] = (
            round(float(summary["avg_return_pct"]) - float(baseline["avg_return_pct"]), 2)
            if summary["avg_return_pct"] is not None and baseline["avg_return_pct"] is not None
            else None
        )
    challenger = max(
        (policy for policy in policies if policy != "current_all_out_75"),
        key=lambda policy: float(summaries[policy]["avg_return_pct"] or -9999),
        default=None,
    )
    delta = summaries.get(challenger, {}).get("avg_return_delta_vs_current") if challenger else None
    holdout = _chronological_holdout(results, policies)
    promotion_blockers: list[str] = []
    if len(paths) < MIN_PROMOTION_PATHS:
        promotion_blockers.append("insufficient_executable_completed_paths")
    if challenger is None:
        promotion_blockers.append("no_challenger")
    else:
        challenger_summary = summaries[challenger]
        if delta is None or float(delta) <= 0:
            promotion_blockers.append("challenger_avg_return_delta_not_positive")
        if challenger_summary.get("avg_return_pct") is None or float(challenger_summary["avg_return_pct"]) <= 0:
            promotion_blockers.append("challenger_avg_return_not_positive")
        profit_factor = challenger_summary.get("profit_factor")
        if profit_factor is None or float(profit_factor) <= 1:
            promotion_blockers.append("challenger_profit_factor_not_above_one")
        if holdout.get("candidate_policy") != challenger:
            promotion_blockers.append("full_sample_winner_differs_from_training_selected_challenger")
    if not holdout["qualified"]:
        promotion_blockers.append("chronological_holdout_not_qualified")
    structural_rows: dict[str, list[dict[str, Any]]] = defaultdict(list)
    complete_structural_paths = 0
    for path_row in paths:
        tournament = simulate_structural_exit_tournament(path_row["observations"])
        if not tournament or not any(
            row.get("underlying_mark_status") == "observed_forward"
            for row in path_row["observations"]
        ):
            continue
        if all(name in tournament for name in (
            "current_ratchet", "structural_vwap_trail", "structural_5m_close_trail"
        )):
            complete_structural_paths += 1
        for policy, outcome in tournament.items():
            structural_rows[policy].append({
                "return_pct": outcome["hypothetical_exit_pct"],
                "reason": outcome["exit_trigger"],
                "lifecycle_id": path_row["lifecycle_id"],
                "symbol": path_row["symbol"],
            })
    structural_summary = {
        policy: _summary(rows) for policy, rows in sorted(structural_rows.items())
    }
    structural_winner = max(
        structural_summary,
        key=lambda policy: float(structural_summary[policy].get("avg_return_pct") or -9999),
        default=None,
    )
    structural_baseline = structural_summary.get("current_ratchet", {}).get("avg_return_pct")
    structural_delta = None
    if structural_winner and structural_baseline is not None:
        winner_avg = structural_summary[structural_winner].get("avg_return_pct")
        if winner_avg is not None:
            structural_delta = round(float(winner_avg) - float(structural_baseline), 2)
    structural_blockers: list[str] = []
    if complete_structural_paths < 20:
        structural_blockers.append("insufficient_complete_forward_paths")
    if structural_winner in (None, "current_ratchet"):
        structural_blockers.append("no_structural_challenger_winner")
    else:
        structural_winner_summary = structural_summary[structural_winner]
        if structural_delta is None or structural_delta <= 0:
            structural_blockers.append("structural_avg_return_delta_not_positive")
        if (
            structural_winner_summary.get("avg_return_pct") is None
            or float(structural_winner_summary["avg_return_pct"]) <= 0
        ):
            structural_blockers.append("structural_avg_return_not_positive")
        structural_profit_factor = structural_winner_summary.get("profit_factor")
        if structural_profit_factor is None or float(structural_profit_factor) <= 1:
            structural_blockers.append("structural_profit_factor_not_above_one")
    return {
        "provider": "flip_exit_policy_comparison",
        "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "mode": "read_only_research",
        "execution_enabled": False,
        "can_submit_orders": False,
        "source_path": str(path),
        "executable_completed_path_count": len(paths),
        "policies": summaries,
        "best_challenger": challenger,
        "best_challenger_avg_return_delta": delta,
        "promotion_ready": not promotion_blockers,
        "promotion_reason": (
            "evidence_qualified_for_human_review_only"
            if not promotion_blockers
            else "promotion_evidence_blocked"
        ),
        "promotion_blockers": promotion_blockers,
        "promotion_authorized": False,
        "chronological_holdout": holdout,
        "promotion_requirements": {
            "minimum_executable_completed_paths": MIN_PROMOTION_PATHS,
            "positive_challenger_avg_return_delta": True,
            "positive_challenger_avg_return": True,
            "challenger_profit_factor_above_one": True,
            "chronological_holdout_required": True,
            "human_approval_required": True,
        },
        "structural_tournament": {
            "complete_forward_path_count": complete_structural_paths,
            "policies": structural_summary,
            "best_path": structural_winner,
            "best_path_avg_return_delta_vs_current_ratchet": structural_delta,
            "review_ready": not structural_blockers,
            "review_reason": (
                "evidence_qualified_for_human_review_only"
                if not structural_blockers
                else "structural_review_evidence_blocked"
            ),
            "review_blockers": structural_blockers,
            "human_approval_required": True,
            "execution_behavior_changed": False,
        },
        "warnings": [
            "Quote-path simulation cannot guarantee fills or reproduce between-sample peaks.",
            "The partial-runner policy assumes proportional fills and ignores order latency.",
            "No live threshold or exit behavior is changed by this report.",
            "Structural paths count only forward rows with contemporaneous underlying marks.",
        ],
    }


def write_report(report: dict[str, Any], report_path: Path = REPORT_PATH, log_path: Path = LOG_PATH) -> None:
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(report, separators=(",", ":"), sort_keys=True) + "\n")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--path", type=Path, default=SHADOW_LOG_PATH)
    parser.add_argument("--report-path", type=Path, default=REPORT_PATH)
    parser.add_argument("--log-path", type=Path, default=LOG_PATH)
    parser.add_argument("--print", action="store_true", dest="print_report")
    args = parser.parse_args()
    report = build_report(args.path)
    write_report(report, args.report_path, args.log_path)
    if args.print_report:
        print(json.dumps({
            "executable_completed_path_count": report["executable_completed_path_count"],
            "policies": report["policies"],
            "best_challenger": report["best_challenger"],
            "promotion_ready": report["promotion_ready"],
            "structural_tournament": report["structural_tournament"],
        }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

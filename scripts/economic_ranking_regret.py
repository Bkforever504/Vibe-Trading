#!/usr/bin/env python3
"""Audit point-in-time ranking utility and economic regret in shadow mode.

This report deliberately requires an explicit, cost-adjusted R outcome backed
by observed fill evidence.  It never derives option premium, assumes a fill,
or treats an underlying move as an executable return.
"""
from __future__ import annotations

import argparse
import json
import math
from datetime import datetime, timezone
from pathlib import Path
from statistics import mean, median
from typing import Any, Iterable


ROOT = Path(__file__).resolve().parents[1]
VIBE_HOME = Path.home() / ".vibe-trading"
DEFAULT_RADAR_LOG = ROOT / "data" / "intraday_opportunity_radar_log.jsonl"
DEFAULT_OUTCOMES = ROOT / "data" / "economic_ranking_outcomes.jsonl"
DEFAULT_OUTPUT = VIBE_HOME / "reports" / "economic-ranking-regret.json"
MAX_PRIOR_SNAPSHOT_AGE_MINUTES = 15.0
ALLOWED_EVIDENCE = {
    "actual_fill",
    "broker_fill",
    "explicit_shadow_fill",
    "observed_quote_shadow_fill",
    "quote_observed_shadow_fill",
}


def _read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def _read_rows(path: Path) -> list[dict[str, Any]]:
    """Read either a JSON list/object-with-rows or JSONL without guessing."""
    try:
        text = path.read_text(encoding="utf-8-sig")
    except OSError:
        return []
    try:
        value = json.loads(text)
    except json.JSONDecodeError:
        value = None
    if isinstance(value, list):
        return [row for row in value if isinstance(row, dict)]
    if isinstance(value, dict):
        rows = value.get("rows") or value.get("outcomes") or value.get("snapshots")
        if isinstance(rows, list):
            return [row for row in rows if isinstance(row, dict)]
        # A one-line JSONL fixture/file is also valid JSON.  Preserve that
        # record rather than silently converting it to an empty collection.
        return [value]
    rows: list[dict[str, Any]] = []
    for raw in text.splitlines():
        try:
            row = json.loads(raw)
        except json.JSONDecodeError:
            continue
        if isinstance(row, dict):
            rows.append(row)
    return rows


def _number(value: Any) -> float | None:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def _dt(value: Any) -> datetime | None:
    if value in (None, ""):
        return None
    try:
        result = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    if result.tzinfo is None:
        result = result.replace(tzinfo=timezone.utc)
    return result.astimezone(timezone.utc)


def _stamp(row: dict[str, Any]) -> str | None:
    value = row.get("as_of_et") or row.get("generated_at") or row.get("decision_at")
    return str(value) if value else None


def _symbol(row: dict[str, Any]) -> str:
    return str(row.get("symbol") or row.get("instrument") or "").strip().upper()


def _direction(value: Any) -> str:
    result = str(value or "").strip().lower()
    if result in {"long", "bull", "bullish", "up", "1", "+1"}:
        return "bullish"
    if result in {"short", "bear", "bearish", "down", "-1"}:
        return "bearish"
    return result


def _move_magnitude(move: dict[str, Any]) -> float:
    direct = _number(move.get("move_pct"))
    if direct is None:
        direct = _number(move.get("magnitude_pct"))
    if direct is None:
        suffix = "long" if _direction(move.get("direction") or move.get("label")) == "bullish" else "short"
        direct = _number(move.get(f"magnitude_{suffix}"))
    return abs(direct or 0.0)


def _candidate_confirmed(candidate: dict[str, Any] | None) -> bool:
    if not candidate:
        return False
    stage = str(candidate.get("confirmation_stage") or "").lower()
    if stage == "completed_5m_confirmed" or stage.endswith("_confirmed"):
        return True
    if candidate.get("setup_confirmed") is True or candidate.get("confirmed") is True:
        return True
    confirmation = candidate.get("price_action_confirmation")
    if isinstance(confirmation, dict):
        return str(confirmation.get("state") or "").lower().endswith("_confirmed")
    return False


def _candidate_lists(snapshot: dict[str, Any], key: str) -> list[dict[str, Any]]:
    """Merge benchmark and broad lanes once, preserving their recorded order."""
    benchmark = snapshot.get("benchmark_lane")
    benchmark = benchmark if isinstance(benchmark, dict) else {}
    rows = [row for row in benchmark.get(key) or [] if isinstance(row, dict)]
    rows.extend(row for row in snapshot.get(key) or [] if isinstance(row, dict))
    deduped: list[dict[str, Any]] = []
    seen: set[str] = set()
    for row in rows:
        symbol = _symbol(row)
        if symbol and symbol not in seen:
            seen.add(symbol)
            deduped.append(row)
    return deduped


def _has_key(snapshot: dict[str, Any], key: str) -> bool:
    benchmark = snapshot.get("benchmark_lane")
    return key in snapshot or (isinstance(benchmark, dict) and key in benchmark)


def _all_candidates(snapshot: dict[str, Any]) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for key in ("ranked_candidates", "filtered_candidates", "actionable_ranked_candidates"):
        for row in _candidate_lists(snapshot, key):
            result.setdefault(_symbol(row), row)
    return result


def _qualified_outcome(row: dict[str, Any]) -> tuple[str, datetime, float] | None:
    """Accept only explicit net-R records with observed fill evidence."""
    symbol = _symbol(row)
    decision = _dt(row.get("decision_at") or row.get("radar_snapshot_at") or row.get("as_of_et"))
    net_r = _number(row.get("net_r_after_costs"))
    evidence = row.get("execution_evidence")
    if isinstance(evidence, dict):
        evidence_status = str(evidence.get("status") or evidence.get("source") or "").lower()
        fill_assumed = bool(evidence.get("fill_assumed"))
    else:
        evidence_status = str(row.get("execution_evidence_status") or evidence or "").lower()
        fill_assumed = bool(row.get("fill_assumed"))
    premium_source = str(row.get("premium_source") or "").lower()
    forbidden_premium = bool(row.get("premium_inferred_from_underlying")) or any(
        token in premium_source for token in ("infer", "model", "theoretical", "underlying_proxy")
    )
    resolved = str(row.get("status") or row.get("outcome_status") or "resolved").lower() == "resolved"
    if (
        not symbol
        or decision is None
        or net_r is None
        or evidence_status not in ALLOWED_EVIDENCE
        or fill_assumed
        or forbidden_premium
        or not resolved
    ):
        return None
    return symbol, decision, net_r


def _decision_key(value: datetime) -> str:
    return value.isoformat().replace("+00:00", "Z")


def _dcg(relevances: list[float], k: int) -> float:
    return sum(max(0.0, value) / math.log2(index + 2.0) for index, value in enumerate(relevances[:k]))


def _ndcg(relevances: list[float], oracle: list[float], k: int) -> float | None:
    ideal = _dcg(sorted((max(0.0, value) for value in oracle), reverse=True), k)
    if ideal <= 0.0:
        return None
    return _dcg(relevances, k) / ideal


def _nearest_prior(move: dict[str, Any], snapshots: list[dict[str, Any]]) -> dict[str, Any] | None:
    start = _dt(move.get("move_start_at") or move.get("trigger_bar_ts") or move.get("bar_close_ts"))
    if start is None:
        return None
    prior = [row for row in snapshots if _dt(_stamp(row)) and _dt(_stamp(row)) <= start]
    if not prior:
        return None
    selected = prior[-1]
    selected_at = _dt(_stamp(selected))
    if selected_at is None or (start - selected_at).total_seconds() / 60.0 > MAX_PRIOR_SNAPSHOT_AGE_MINUTES:
        return None
    return selected


def _stage_for_move(move: dict[str, Any], snapshot: dict[str, Any] | None, k: int) -> tuple[str, int | None]:
    if snapshot is None:
        return "discovery", None
    symbol = _symbol(move)
    ranked = _candidate_lists(snapshot, "ranked_candidates")
    actionable = _candidate_lists(snapshot, "actionable_ranked_candidates")
    all_candidates = _all_candidates(snapshot)
    discovered_symbols = {str(value).upper() for value in snapshot.get("all_discovered_symbols") or []}
    discovered = symbol in discovered_symbols or symbol in all_candidates
    if not discovered:
        return "discovery", None
    candidate = all_candidates.get(symbol)
    if not _candidate_confirmed(candidate):
        return "confirmation", None
    if not _has_key(snapshot, "actionable_ranked_candidates"):
        return "execution", None
    actionable_symbols = [_symbol(row) for row in actionable]
    if symbol not in actionable_symbols:
        return "execution", None
    rank = actionable_symbols.index(symbol) + 1
    if rank > k:
        return "rank", rank
    ranked_direction = _direction((candidate or {}).get("direction"))
    truth_direction = _direction(move.get("direction") or move.get("label"))
    if ranked_direction and truth_direction and ranked_direction != truth_direction:
        return "rank", rank
    return "captured", rank


def build_report(
    ground_truth: dict[str, Any],
    radar_history: Iterable[dict[str, Any]],
    outcome_rows: Iterable[dict[str, Any]],
    *,
    ks: tuple[int, ...] = (5, 10),
) -> dict[str, Any]:
    date_key = str(ground_truth.get("date") or "")[:10]
    snapshots = sorted(
        [
            row for row in radar_history
            if isinstance(row, dict) and str(row.get("date") or _stamp(row) or "")[:10] == date_key and _dt(_stamp(row))
        ],
        key=lambda row: _dt(_stamp(row)) or datetime.min.replace(tzinfo=timezone.utc),
    )
    moves = [
        row for row in ground_truth.get("moves") or []
        if isinstance(row, dict) and row.get("excluded") is not True and _symbol(row)
    ]
    qualified_outcomes: dict[str, dict[str, float]] = {}
    complete_decisions: set[str] = set()
    rejected_outcomes = 0
    for row in outcome_rows:
        if not isinstance(row, dict):
            rejected_outcomes += 1
            continue
        parsed = _qualified_outcome(row)
        if parsed is None:
            rejected_outcomes += 1
            continue
        symbol, decision, net_r = parsed
        key = _decision_key(decision)
        qualified_outcomes.setdefault(key, {})[symbol] = net_r
        if row.get("universe_snapshot_complete") is True:
            complete_decisions.add(key)

    issues: list[str] = []
    if not date_key:
        issues.append("ground_truth_date_missing")
    if ground_truth.get("metrics_qualified") is not True:
        issues.append("ground_truth_not_metrics_qualified")
    if not moves:
        issues.append("ground_truth_moves_missing")
    if not snapshots:
        issues.append("radar_history_missing_for_date")
    if not qualified_outcomes:
        issues.append("explicit_net_r_outcomes_missing")
    if not complete_decisions:
        issues.append("complete_outcome_universe_missing")

    decision_evaluations: list[dict[str, Any]] = []
    for snapshot in snapshots:
        decision_at = _dt(_stamp(snapshot))
        if decision_at is None:
            continue
        key = _decision_key(decision_at)
        outcomes = qualified_outcomes.get(key) or {}
        ranking = _candidate_lists(snapshot, "actionable_ranked_candidates")
        symbols = [_symbol(row) for row in ranking]
        if key not in complete_decisions or not ranking or any(symbol not in outcomes for symbol in symbols):
            continue
        selected_r = outcomes[symbols[0]]
        oracle_r = max(outcomes.values())
        relevances = [outcomes[symbol] for symbol in symbols]
        metrics = {f"ndcg_at_{k}": _ndcg(relevances, list(outcomes.values()), k) for k in ks}
        decision_evaluations.append({
            "decision_at": key,
            "ranked_symbols": symbols,
            "outcome_universe_size": len(outcomes),
            "selected_symbol": symbols[0],
            "selected_net_r_after_costs": round(selected_r, 6),
            "oracle_symbol": max(outcomes, key=outcomes.get),
            "oracle_net_r_after_costs": round(oracle_r, 6),
            "oracle_vs_selected_net_r_regret": round(oracle_r - selected_r, 6),
            **{name: round(value, 6) if value is not None else None for name, value in metrics.items()},
            "fill_assumed": False,
            "premium_inferred": False,
            "execution_enabled": False,
            "can_submit_orders": False,
        })
    if not decision_evaluations:
        issues.append("no_point_in_time_decision_has_complete_explicit_outcomes")

    largest_k = max(ks)
    move_evaluations: list[dict[str, Any]] = []
    stage_counts = {stage: 0 for stage in ("discovery", "confirmation", "execution", "rank", "captured")}
    stage_magnitude = {stage: 0.0 for stage in stage_counts}
    stage_positive_net_r = {stage: 0.0 for stage in stage_counts}
    stage_missing_net_r = {stage: 0 for stage in stage_counts}
    for move in moves:
        magnitude = _move_magnitude(move)
        snapshot = _nearest_prior(move, snapshots)
        stage, rank = _stage_for_move(move, snapshot, largest_k)
        snapshot_at = _dt(_stamp(snapshot or {}))
        explicit_net_r = (
            (qualified_outcomes.get(_decision_key(snapshot_at)) or {}).get(_symbol(move))
            if snapshot_at is not None else None
        )
        stage_counts[stage] += 1
        stage_magnitude[stage] += magnitude
        if explicit_net_r is None:
            stage_missing_net_r[stage] += 1
        else:
            stage_positive_net_r[stage] += max(0.0, explicit_net_r)
        move_evaluations.append({
            "move_id": move.get("move_id"),
            "symbol": _symbol(move),
            "move_start_at": move.get("move_start_at") or move.get("trigger_bar_ts") or move.get("bar_close_ts"),
            "move_magnitude_pct": round(magnitude, 6),
            "terminal_stage": stage,
            "actionable_rank": rank,
            "linked_snapshot_at": _stamp(snapshot or {}),
            "explicit_net_r_after_costs": round(explicit_net_r, 6) if explicit_net_r is not None else None,
            "fill_assumed": False,
            "premium_inferred": False,
        })

    metric_inputs_qualified = not issues
    total_magnitude = sum(row["move_magnitude_pct"] for row in move_evaluations)
    magnitude_recall: dict[int, float | None] = {}
    for k in ks:
        captured = sum(
            row["move_magnitude_pct"] for row in move_evaluations
            if row["terminal_stage"] == "captured" and row["actionable_rank"] is not None and row["actionable_rank"] <= k
        )
        magnitude_recall[k] = captured / total_magnitude if total_magnitude > 0 else None
    ndcg_values = {
        k: [row[f"ndcg_at_{k}"] for row in decision_evaluations if row.get(f"ndcg_at_{k}") is not None]
        for k in ks
    }
    regrets = [row["oracle_vs_selected_net_r_regret"] for row in decision_evaluations]
    if not metric_inputs_qualified:
        metrics: dict[str, Any] = {
            **{f"ndcg_at_{k}": None for k in ks},
            **{f"magnitude_weighted_recall_at_{k}": None for k in ks},
            "oracle_vs_selected_net_r_regret": None,
        }
    else:
        metrics = {
            **{
                f"ndcg_at_{k}": round(mean(ndcg_values[k]), 6) if ndcg_values[k] else None
                for k in ks
            },
            **{
                f"magnitude_weighted_recall_at_{k}": round(magnitude_recall[k], 6) if magnitude_recall[k] is not None else None
                for k in ks
            },
            "oracle_vs_selected_net_r_regret": {
                "mean": round(mean(regrets), 6),
                "median": round(median(regrets), 6),
                "total": round(sum(regrets), 6),
                "decision_count": len(regrets),
            },
        }

    return {
        "schema_version": 1,
        "provider": "economic_ranking_regret",
        "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "date": date_key or None,
        "mode": "shadow_audit_only",
        "metrics_qualified": metric_inputs_qualified,
        "qualification_issues": issues,
        "metrics": metrics,
        "stage_decomposition": {
            "basis": f"first_terminal_failure_stage_at_nearest_prior_snapshot; rank_cutoff={largest_k}",
            "counts": stage_counts,
            "move_magnitude_pct": {key: round(value, 6) for key, value in stage_magnitude.items()},
            "explicit_positive_net_r_opportunity": {
                key: round(value, 6) for key, value in stage_positive_net_r.items()
            },
            "missing_explicit_net_r_count": stage_missing_net_r,
            "diagnostic_only_when_metrics_unqualified": not metric_inputs_qualified,
        },
        "input_summary": {
            "ground_truth_moves": len(moves),
            "radar_snapshots": len(snapshots),
            "qualified_explicit_outcomes": sum(len(value) for value in qualified_outcomes.values()),
            "rejected_or_unusable_outcomes": rejected_outcomes,
            "complete_outcome_decisions": len(complete_decisions),
            "evaluated_decisions": len(decision_evaluations),
        },
        "decision_evaluations": decision_evaluations,
        "move_evaluations": move_evaluations,
        "outcome_contract": {
            "required_return_field": "net_r_after_costs",
            "required_evidence_status": sorted(ALLOWED_EVIDENCE),
            "requires_universe_snapshot_complete": True,
            "underlying_derived_option_premium_allowed": False,
            "fill_assumptions_allowed": False,
        },
        "warnings": [
            "Economic metrics are unavailable unless the frozen ground truth, point-in-time radar, complete outcome universe, and explicit cost-adjusted fill evidence are all present.",
            "nDCG uses max(net R after costs, 0) as graded relevance; raw negative R remains in regret.",
            "This report measures shadow evidence only and cannot place, route, or authorize an order.",
        ],
        "execution_enabled": False,
        "can_submit_orders": False,
    }


def _atomic_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(path)


def _latest_ground_truth(data_dir: Path) -> Path | None:
    paths = sorted(data_dir.glob("move_ground_truth_????????.json"))
    return paths[-1] if paths else None


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ground-truth", type=Path, help="Frozen move-ground-truth JSON; defaults to latest in --data-dir")
    parser.add_argument("--radar-log", type=Path, default=DEFAULT_RADAR_LOG)
    parser.add_argument("--outcomes", type=Path, default=DEFAULT_OUTCOMES)
    parser.add_argument("--data-dir", type=Path, default=ROOT / "data")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--print", action="store_true", dest="print_report")
    args = parser.parse_args()
    ground_path = args.ground_truth or _latest_ground_truth(args.data_dir)
    ground_truth = _read_json(ground_path) if ground_path else {}
    report = build_report(ground_truth, _read_rows(args.radar_log), _read_rows(args.outcomes))
    _atomic_json(args.output, report)
    if args.print_report:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        print(
            f"economic_ranking_regret date={report['date']} qualified={report['metrics_qualified']} "
            f"decisions={report['input_summary']['evaluated_decisions']} issues={','.join(report['qualification_issues']) or 'none'}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Resolve terminal shadow plans with executable-side marks.

The resolver is deliberately conservative: a plan is appended only after a
terminal event exists. Missing quote fields stay null; they are never replaced
with midpoint or synthetic prices.
"""
from __future__ import annotations

import argparse
import json
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping


ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "data"
OUTPUT_PATH = DATA_DIR / "shadow_outcomes.jsonl"
LEDGER_NAMES = (
    "options_shadow_twin_log.jsonl",
    "adaptive_options_shadow_playbook_log.jsonl",
    "mes_reopen_vix_shadow_log.jsonl",
    "mes_orb_0932_vix_v2_shadow_log.jsonl",
    "mes_reopen_drift_v2_shadow_log.jsonl",
    "event_gap_continuation_shadow_log.jsonl",
    "momentum_edge_ensemble_shadow_log.jsonl",
    "gex_level_reaction_shadow_log.jsonl",
    "trend_participation_shadow_log.jsonl",
    "simple_price_action_shadow_log.jsonl",
)


def _number(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _time(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).astimezone(timezone.utc)
    except ValueError:
        return None


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    try:
        lines = path.read_text(encoding="utf-8-sig").splitlines()
    except OSError:
        return []
    rows: list[dict[str, Any]] = []
    for line in lines:
        try:
            value = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            rows.append(value)
    return rows


def _plan_id(row: Mapping[str, Any]) -> str | None:
    for key in ("plan_id", "candidate_id", "trade_key"):
        if row.get(key):
            return str(row[key])
    return None


def _nested_rows(row: Mapping[str, Any]) -> Iterable[dict[str, Any]]:
    yield dict(row)
    for key in ("rows", "candidates", "observations", "signals", "plans"):
        value = row.get(key)
        if isinstance(value, list):
            for child in value:
                if isinstance(child, dict):
                    inherited = dict(child)
                    inherited.setdefault("captured_at", row.get("generated_at") or row.get("timestamp"))
                    yield inherited


def _entry_price(candidate: Mapping[str, Any]) -> tuple[float | None, str]:
    for key in ("entry_fill_executable", "entry_ask", "executable_entry_debit", "executable_entry_credit", "entry_price"):
        value = _number(candidate.get(key))
        if value is not None:
            return value, "credit" if "credit" in key else "debit"
    return None, "debit"


def _mark_price(mark: Mapping[str, Any], style: str) -> float | None:
    keys = (
        ("executable_close_debit", "close_debit", "ask", "executable_ask")
        if style == "credit"
        else ("exit_fill_executable", "executable_bid", "bid", "mark_price")
    )
    for key in keys:
        value = _number(mark.get(key))
        if value is not None:
            return value
    return None


def resolve_plan(
    candidate: Mapping[str, Any],
    marks: Iterable[Mapping[str, Any]],
    terminal: Mapping[str, Any],
    *,
    source_ledger: str,
    resolved_at: datetime,
) -> dict[str, Any]:
    plan_id = _plan_id(candidate)
    if not plan_id:
        raise ValueError("candidate has no plan identifier")
    entry, style = _entry_price(candidate)
    ordered_marks = sorted(
        marks,
        key=lambda row: str(row.get("marked_at") or row.get("timestamp") or row.get("captured_at") or ""),
    )
    executable_marks = [value for value in (_mark_price(row, style) for row in ordered_marks) if value is not None]
    if style == "credit":
        exit_fill = _number(terminal.get("closing_debit"))
        if exit_fill is None and executable_marks:
            exit_fill = executable_marks[-1]
        path_pnl = [entry - value for value in executable_marks] if entry is not None else []
    else:
        exit_fill = next(
            (
                value
                for value in (
                    _number(terminal.get("exit_fill_executable")),
                    _number(terminal.get("exit_bid")),
                    _number(terminal.get("exit_price")),
                )
                if value is not None
            ),
            executable_marks[-1] if executable_marks else None,
        )
        path_pnl = [value - entry for value in executable_marks] if entry is not None else []

    quantity = _number(terminal.get("quantity")) or _number(candidate.get("effective_qty")) or 1.0
    pnl_before_fees = _number(terminal.get("pnl_before_fees"))
    net_pnl = _number(terminal.get("net_dollar"))
    pnl = net_pnl if net_pnl is not None else pnl_before_fees
    if pnl is None and entry is not None and exit_fill is not None:
        pnl = (entry - exit_fill if style == "credit" else exit_fill - entry) * 100.0 * quantity
        pnl_before_fees = pnl
    max_risk = _number(candidate.get("max_risk_per_contract")) or _number(candidate.get("risk_per_contract"))
    terminal_outcome_r = _number(terminal.get("outcome_r"))
    outcome_r = terminal_outcome_r if terminal_outcome_r is not None else pnl / (max_risk * quantity) if pnl is not None and max_risk and quantity else None

    entry_time = _time(candidate.get("created_at") or candidate.get("captured_at") or candidate.get("timestamp"))
    exit_time = _time(terminal.get("resolved_at") or terminal.get("closed_at") or terminal.get("timestamp"))
    duration = (exit_time - entry_time).total_seconds() / 60.0 if entry_time and exit_time and exit_time >= entry_time else None
    promotion_eligible = candidate.get("promotion_eligible") is not False and terminal.get("promotion_eligible") is not False
    terminal_resolved_at = _time(terminal.get("resolved_at") or terminal.get("closed_at") or terminal.get("timestamp"))
    return {
        "schema_version": 1,
        "plan_id": plan_id,
        "candidate_id": candidate.get("candidate_id") or candidate.get("strategy_id") or plan_id,
        "strategy_id": candidate.get("strategy_id"),
        "family_id": candidate.get("family_id"),
        "spec_hash": candidate.get("spec_hash"),
        "source_ledger": source_ledger,
        "data_source": candidate.get("data_source"),
        "evidence_tier": candidate.get("evidence_tier"),
        "promotion_eligible": promotion_eligible,
        "evidence_blockers": candidate.get("evidence_blockers") or [],
        "entry_fill_executable": entry,
        "exit_fill_executable": exit_fill,
        "mfe": max(path_pnl) if path_pnl else None,
        "mae": min(path_pnl) if path_pnl else None,
        "outcome_r": outcome_r,
        "pnl_before_fees": pnl_before_fees,
        "net_dollar": net_pnl,
        "time_in_trade_minutes": round(duration, 3) if duration is not None else None,
        "counterfactual_next_ranked": candidate.get("counterfactual_next_ranked"),
        "counterfactual_cash": {"pnl": 0.0, "outcome_r": 0.0},
        "resolved_at": (terminal_resolved_at or resolved_at).isoformat(),
        "terminal_reason": terminal.get("reason"),
        "quote_method": "entry_executable_ask_or_strategy_credit_exit_executable_bid_or_close_debit" if promotion_eligible else "proxy_ohlcv_non_executable",
        "execution_enabled": False,
        "can_submit_orders": False,
    }


def build_resolutions(
    ledger_rows: Mapping[str, Iterable[Mapping[str, Any]]],
    *,
    existing_plan_ids: set[str] | None = None,
    resolved_at: datetime | None = None,
) -> list[dict[str, Any]]:
    existing_plan_ids = existing_plan_ids or set()
    resolved_at = (resolved_at or datetime.now(timezone.utc)).astimezone(timezone.utc)
    output: list[dict[str, Any]] = []
    for source in sorted(ledger_rows):
        expanded = [child for parent in ledger_rows[source] for child in _nested_rows(parent)]
        candidates: dict[str, dict[str, Any]] = {}
        marks: dict[str, list[dict[str, Any]]] = defaultdict(list)
        terminals: dict[str, dict[str, Any]] = {}
        for row in expanded:
            plan_id = _plan_id(row)
            if not plan_id:
                continue
            kind = str(row.get("type") or row.get("event_type") or "").lower()
            if kind in {"outcome", "resolved", "exit", "closed"} or row.get("resolved_at"):
                terminals[plan_id] = row
            elif kind in {"mark", "quote", "snapshot"} or any(key in row for key in ("executable_close_debit", "executable_bid")):
                marks[plan_id].append(row)
            else:
                candidates.setdefault(plan_id, row)
        for plan_id in sorted(set(candidates) & set(terminals)):
            if plan_id in existing_plan_ids:
                continue
            output.append(
                resolve_plan(
                    candidates[plan_id],
                    marks.get(plan_id, []),
                    terminals[plan_id],
                    source_ledger=source,
                    resolved_at=resolved_at,
                )
            )
    return output


def run_once(*, data_dir: Path = DATA_DIR, output_path: Path = OUTPUT_PATH, now: datetime | None = None) -> dict[str, Any]:
    existing_rows = _read_jsonl(output_path)
    existing = {str(row.get("plan_id")) for row in existing_rows if row.get("plan_id")}
    ledgers = {name: _read_jsonl(data_dir / name) for name in LEDGER_NAMES}
    rows = build_resolutions(ledgers, existing_plan_ids=existing, resolved_at=now)
    if rows:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with output_path.open("a", encoding="utf-8", newline="\n") as handle:
            for row in rows:
                handle.write(json.dumps(row, sort_keys=True, separators=(",", ":")) + "\n")
    return {
        "schema_version": 1,
        "resolved_count": len(rows),
        "existing_count": len(existing),
        "missing_ledgers": sorted(name for name in LEDGER_NAMES if not (data_dir / name).exists()),
        "execution_enabled": False,
        "can_submit_orders": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-dir", type=Path, default=DATA_DIR)
    parser.add_argument("--output", type=Path, default=OUTPUT_PATH)
    args = parser.parse_args()
    print(json.dumps(run_once(data_dir=args.data_dir, output_path=args.output), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

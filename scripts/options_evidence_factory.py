#!/usr/bin/env python3
"""Read-only matched counterfactual factory for formed options setups.

The factory records concrete, point-in-time option expressions for later OPRA
replay. It has no broker execution imports and cannot submit orders.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
import sys
from collections import Counter
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterable

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.options_shadow_twin import (
    DEFAULT_LOG_PATH as DEFAULT_TWIN_LOG_PATH,
    executable_entry_credit,
    read_records as read_twin_records,
    record_candidate,
    record_decision,
)


SCHEMA_VERSION = 1
DEFAULT_LOG_PATH = ROOT / "data" / "options_evidence_factory_log.jsonl"
DEFAULT_REPORT_PATH = ROOT / "data" / "options_evidence_factory_report.json"
SUPPORTED_STRATEGIES = {"put_spread", "call_spread", "iron_condor", "iron_fly"}
OCC_PATTERN = re.compile(r"^[A-Z]{1,6}\d{6}[CP]\d{8}$")

CandidateRecorder = Callable[..., str | None]
DecisionRecorder = Callable[..., None]


def _number(value: Any) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if math.isfinite(parsed) else None


def _parse_ts(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _hash(payload: Any, length: int = 24) -> str:
    serialized = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()[:length]


def _append_jsonl(path: Path, row: dict[str, Any]) -> None:
    if os.getenv("PYTEST_CURRENT_TEST") and path == DEFAULT_LOG_PATH:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(row, sort_keys=True, separators=(",", ":"), allow_nan=False) + "\n")


def read_records(path: Path = DEFAULT_LOG_PATH) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(row, dict):
            rows.append(row)
    return rows


def stable_setup_id(base_setup: dict[str, Any], decision_at: datetime) -> str:
    explicit = str(base_setup.get("setup_id") or "").strip()
    if explicit:
        return explicit
    identity = {
        "source_strategy": str(base_setup.get("source_strategy") or base_setup.get("strategy") or ""),
        "underlying": str(base_setup.get("underlying") or "").upper(),
        "decision_at": _iso(decision_at),
        "decision_hash": str(base_setup.get("decision_hash") or ""),
        "source_candidate_id": str(base_setup.get("source_candidate_id") or ""),
    }
    return f"setup-{_hash(identity)}"


def _snapshot_map(trade_meta: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {
        str(row.get("symbol") or "").upper(): row
        for row in (trade_meta.get("leg_market_snapshots") or [])
        if isinstance(row, dict) and row.get("symbol")
    }


def _quote_time(snapshot: dict[str, Any]) -> datetime | None:
    return _parse_ts(snapshot.get("quote_timestamp") or snapshot.get("captured_at"))


def validate_expression(
    trade_meta: dict[str, Any],
    legs_payload: Iterable[dict[str, Any]],
    *,
    decision_at: datetime,
) -> tuple[bool, str]:
    strategy = str(trade_meta.get("strategy") or "")
    underlying = str(trade_meta.get("underlying") or "")
    if strategy not in SUPPORTED_STRATEGIES:
        return False, "unsupported_strategy"
    if not underlying:
        return False, "missing_underlying"
    selected_at = _parse_ts(trade_meta.get("contract_selected_at")) or decision_at
    if selected_at > decision_at:
        return False, "future_contract_selection"
    legs = list(legs_payload)
    if len(legs) not in {2, 4}:
        return False, "unsupported_leg_count"
    snapshots = _snapshot_map(trade_meta)
    for leg in legs:
        symbol = str(leg.get("symbol") or "").replace(" ", "").upper()
        if not OCC_PATTERN.fullmatch(symbol):
            return False, "invalid_occ_contract"
        if str(leg.get("side") or "").lower() not in {"buy", "sell"}:
            return False, "invalid_leg_side"
        quote = snapshots.get(symbol)
        if quote is None:
            return False, "missing_leg_quote"
        bid = _number(quote.get("bid"))
        ask = _number(quote.get("ask"))
        if bid is None or ask is None or bid <= 0 or ask < bid:
            return False, "invalid_leg_market"
        observed_at = _quote_time(quote)
        if observed_at is None:
            return False, "missing_quote_timestamp"
        if observed_at > decision_at:
            return False, "future_quote_timestamp"
    return True, "ok"


def _right(snapshot: dict[str, Any]) -> str:
    value = str(snapshot.get("right") or "").upper()
    return "P" if value in {"P", "PUT"} else "C" if value in {"C", "CALL"} else ""


def _component_expression(
    primary_meta: dict[str, Any],
    primary_legs: list[dict[str, Any]],
    *,
    right: str,
) -> dict[str, Any] | None:
    snapshots = _snapshot_map(primary_meta)
    selected = [
        deepcopy(leg)
        for leg in primary_legs
        if _right(snapshots.get(str(leg.get("symbol") or "").upper(), {})) == right
    ]
    if len(selected) != 2:
        return None
    sides = {str(leg.get("side") or "").lower() for leg in selected}
    if sides != {"buy", "sell"}:
        return None
    component_meta = deepcopy(primary_meta)
    component_meta["strategy"] = "put_spread" if right == "P" else "call_spread"
    component_meta["expression_type"] = "component_put_spread" if right == "P" else "component_call_spread"
    selected_symbols = {str(leg.get("symbol") or "").upper() for leg in selected}
    component_meta["leg_market_snapshots"] = [
        deepcopy(row)
        for symbol, row in snapshots.items()
        if symbol in selected_symbols
    ]
    quote_legs = []
    strikes = []
    for leg in selected:
        snapshot = snapshots[str(leg.get("symbol") or "").upper()]
        quote_legs.append({**leg, "bid": snapshot.get("bid"), "ask": snapshot.get("ask")})
        strike = _number(snapshot.get("strike"))
        if strike is not None:
            strikes.append(strike)
    entry_credit = executable_entry_credit(quote_legs)
    if entry_credit is None or len(strikes) != 2:
        return None
    width = abs(strikes[0] - strikes[1])
    if width <= entry_credit:
        return None
    component_meta["net_credit"] = entry_credit
    component_meta["max_risk_per_contract"] = round((width - entry_credit) * 100.0, 2)
    cohort = str(primary_meta.get("calibration_cohort") or primary_meta.get("strategy_version") or "matched")
    component_meta["calibration_cohort"] = f"{cohort}:{component_meta['strategy']}"
    return {"trade_meta": component_meta, "legs_payload": selected}


def matched_expressions(
    primary_trade_meta: dict[str, Any],
    legs_payload: Iterable[dict[str, Any]],
) -> list[dict[str, Any]]:
    primary_meta = deepcopy(primary_trade_meta)
    primary_meta.setdefault("expression_type", "primary")
    primary_legs = [deepcopy(leg) for leg in legs_payload]
    expressions = [{"trade_meta": primary_meta, "legs_payload": primary_legs}]
    if str(primary_meta.get("strategy") or "") in {"iron_condor", "iron_fly"}:
        for right in ("P", "C"):
            component = _component_expression(primary_meta, primary_legs, right=right)
            if component is not None:
                expressions.append(component)
    return expressions


def record_matched_setup(
    base_setup: dict[str, Any],
    primary_trade_meta: dict[str, Any],
    legs_payload: Iterable[dict[str, Any]],
    *,
    consensus: dict[str, Any] | None = None,
    effective_qty: int | None = None,
    twin_path: Path = DEFAULT_TWIN_LOG_PATH,
    evidence_path: Path = DEFAULT_LOG_PATH,
    now: datetime | None = None,
    candidate_recorder: CandidateRecorder = record_candidate,
    decision_recorder: DecisionRecorder = record_decision,
) -> dict[str, Any]:
    """Record a primary candidate, available components, and no-trade benchmark."""
    decision_at = now or _parse_ts(base_setup.get("decision_at")) or datetime.now(timezone.utc)
    setup_id = stable_setup_id(base_setup, decision_at)
    source_strategy = str(
        base_setup.get("source_strategy") or primary_trade_meta.get("strategy") or "unknown"
    )
    gate_states = base_setup.get("gate_states") if isinstance(base_setup.get("gate_states"), dict) else {}
    warning_states = [str(item) for item in (base_setup.get("warning_states") or []) if str(item)]
    decision_hash = str(base_setup.get("decision_hash") or _hash({
        "source_strategy": source_strategy,
        "gate_states": gate_states,
        "warning_states": warning_states,
    }))
    results: list[dict[str, Any]] = []
    primary_candidate_id: str | None = None

    for index, expression in enumerate(matched_expressions(primary_trade_meta, legs_payload)):
        meta = deepcopy(expression["trade_meta"])
        expression_legs = expression["legs_payload"]
        expression_type = str(meta.get("expression_type") or ("primary" if index == 0 else "matched"))
        meta.update({
            "setup_id": setup_id,
            "parent_setup_id": setup_id,
            "source_strategy": source_strategy,
            "expression_type": expression_type,
            "decision_hash": decision_hash,
            "contract_selected_at": meta.get("contract_selected_at") or _iso(decision_at),
            "gate_states": gate_states,
            "warning_states": warning_states,
            "spot_at_entry": base_setup.get("spot_at_entry"),
            "event_context": base_setup.get("event_context")
            if isinstance(base_setup.get("event_context"), dict)
            else meta.get("event_context", {}),
            "regime_context": base_setup.get("regime_context")
            if isinstance(base_setup.get("regime_context"), dict)
            else meta.get("regime_context", {}),
            "evidence_authority": "read_only_counterfactual_no_execution",
        })
        for snapshot in meta.get("leg_market_snapshots") or []:
            if isinstance(snapshot, dict) and not (
                snapshot.get("quote_timestamp") or snapshot.get("captured_at")
            ):
                snapshot["captured_at"] = _iso(decision_at)
                snapshot["timestamp_method"] = "factory_local_capture_time"
        valid, reason = validate_expression(meta, expression_legs, decision_at=decision_at)
        candidate_id: str | None = None
        if valid:
            candidate_id = candidate_recorder(
                meta,
                expression_legs,
                consensus=consensus if index == 0 else {},
                effective_qty=effective_qty,
                path=twin_path,
                now=decision_at,
            )
            if candidate_id is None:
                valid, reason = False, "candidate_recorder_rejected"
        if index == 0:
            primary_candidate_id = candidate_id
        elif candidate_id:
            decision_recorder(
                candidate_id,
                "counterfactual_only_no_order_path",
                details={"setup_id": setup_id, "expression_type": expression_type},
                path=twin_path,
                now=decision_at,
            )
        result = {
            "expression_type": expression_type,
            "strategy": meta.get("strategy"),
            "status": "recorded" if candidate_id else "unavailable",
            "candidate_id": candidate_id,
            "reason": "ok" if candidate_id else reason,
        }
        results.append(result)

    results.append({
        "expression_type": "no_trade",
        "strategy": "no_trade",
        "status": "benchmark",
        "candidate_id": None,
        "reason": "matched_opportunity_cost_control",
    })
    row = {
        "schema_version": SCHEMA_VERSION,
        "type": "matched_setup",
        "setup_id": setup_id,
        "recorded_at": _iso(decision_at),
        "source_strategy": source_strategy,
        "underlying": str(primary_trade_meta.get("underlying") or base_setup.get("underlying") or ""),
        "decision_hash": decision_hash,
        "gate_states": gate_states,
        "warning_states": warning_states,
        "expressions": results,
        "execution_enabled": False,
        "can_submit_orders": False,
    }
    _append_jsonl(evidence_path, row)
    return {
        "status": "recorded" if primary_candidate_id else "primary_unavailable",
        "setup_id": setup_id,
        "primary_candidate_id": primary_candidate_id,
        "expressions": results,
        "execution_enabled": False,
        "can_submit_orders": False,
    }


def build_report(
    evidence_rows: Iterable[dict[str, Any]],
    twin_rows: Iterable[dict[str, Any]],
) -> dict[str, Any]:
    setups = [row for row in evidence_rows if row.get("type") == "matched_setup"]
    candidates = {
        str(row.get("candidate_id")): row
        for row in twin_rows
        if row.get("type") == "candidate" and row.get("candidate_id")
    }
    outcomes = {
        str(row.get("candidate_id")): row
        for row in twin_rows
        if row.get("type") == "outcome" and row.get("candidate_id")
    }
    expression_rows = [expression for setup in setups for expression in (setup.get("expressions") or [])]
    candidate_ids = [
        str(row.get("candidate_id"))
        for row in expression_rows
        if row.get("candidate_id")
    ]
    dates = {
        str(row.get("recorded_at") or "")[:10]
        for row in setups
        if row.get("recorded_at")
    }
    unavailable = Counter(
        str(row.get("reason") or "unknown")
        for row in expression_rows
        if row.get("status") == "unavailable"
    )
    by_strategy = Counter(
        str(candidates[candidate_id].get("strategy") or "unknown")
        for candidate_id in candidate_ids
        if candidate_id in candidates
    )
    complete_quotes = sum(
        bool(candidates[candidate_id].get("entry_quote_complete"))
        for candidate_id in candidate_ids
        if candidate_id in candidates
    )
    return {
        "schema_version": SCHEMA_VERSION,
        "provider": "options_evidence_factory",
        "mode": "read_only_counterfactual_coverage",
        "setup_count": len(setups),
        "distinct_date_count": len(dates),
        "expression_count": len(expression_rows),
        "recorded_candidate_count": len(candidate_ids),
        "resolved_candidate_count": sum(candidate_id in outcomes for candidate_id in candidate_ids),
        "entry_quote_complete_count": complete_quotes,
        "entry_quote_coverage": round(complete_quotes / len(candidate_ids), 4) if candidate_ids else 0.0,
        "by_strategy": dict(sorted(by_strategy.items())),
        "unavailable_reason_counts": dict(sorted(unavailable.items())),
        "minimum_diagnostic_review": {
            "resolved_per_strategy": 30,
            "distinct_dates": 20,
            "authority": "human_review_only",
        },
        "execution_enabled": False,
        "can_submit_orders": False,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Report matched options evidence coverage")
    parser.add_argument("--evidence", type=Path, default=DEFAULT_LOG_PATH)
    parser.add_argument("--twin", type=Path, default=DEFAULT_TWIN_LOG_PATH)
    parser.add_argument("--out", type=Path, default=DEFAULT_REPORT_PATH)
    parser.add_argument("--print", action="store_true", dest="print_report")
    args = parser.parse_args()
    report = build_report(read_records(args.evidence), read_twin_records(args.twin))
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    if args.print_report:
        print(json.dumps(report, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()

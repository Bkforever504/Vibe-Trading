"""Forward-only journal and resolver for non-authoritative Fibonacci plans."""
from __future__ import annotations

import hashlib
import json
import math
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_PATH = ROOT / "data" / "fibonacci_shadow_plans.json"
DEFAULT_REPORT = Path.home() / ".vibe-trading" / "reports" / "fibonacci-shadow-outcomes.json"
HISTORICAL_REPORT = ROOT / "data" / "fibonacci_execution_lab.json"


def _read(path: Path) -> list[dict[str, Any]]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        return []
    return [row for row in payload if isinstance(row, dict)] if isinstance(payload, list) else []


def _write(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(payload, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")
    os.replace(temp, path)


def _plan_id(setup: dict[str, Any], analysis: dict[str, Any], plan: dict[str, Any]) -> str:
    identity = {
        "symbol": str(setup.get("symbol") or "").upper(),
        "strategy": setup.get("strategy"),
        "direction": analysis.get("direction"),
        "anchor_start": (analysis.get("anchor_start") or {}).get("timestamp"),
        "anchor_end": (analysis.get("anchor_end") or {}).get("timestamp"),
        "entry": plan.get("entry_reference"),
        "stop": plan.get("stop_reference"),
        "target": plan.get("target_reference"),
    }
    raw = json.dumps(identity, sort_keys=True, separators=(",", ":"))
    return "fib-" + hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def record_plan(
    setup: dict[str, Any],
    analysis: dict[str, Any],
    *,
    path: Path = DEFAULT_PATH,
    now: datetime | None = None,
) -> str | None:
    """Record one eligible underlying benchmark once per confirmed impulse."""
    plan = analysis.get("execution_plan") if isinstance(analysis.get("execution_plan"), dict) else {}
    if plan.get("status") != "eligible_shadow":
        return None
    plan_id = _plan_id(setup, analysis, plan)
    rows = _read(path)
    if any(row.get("plan_id") == plan_id for row in rows):
        return plan_id
    created = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    rows.append(
        {
            "schema_version": 1,
            "plan_id": plan_id,
            "created_at": created.isoformat().replace("+00:00", "Z"),
            "as_of": analysis.get("as_of"),
            "symbol": str(setup.get("symbol") or "").upper(),
            "strategy": setup.get("strategy"),
            "direction": analysis.get("direction"),
            "entry_reference": plan.get("entry_reference"),
            "stop_reference": plan.get("stop_reference"),
            "target_reference": plan.get("target_reference"),
            "ttl_completed_bars": plan.get("order_ttl_completed_bars"),
            "status": "pending_unfilled",
            "price_domain": "underlying_not_option_premium",
            "execution_enabled": False,
            "can_submit_orders": False,
        }
    )
    _write(path, rows)
    return plan_id


def _utc_index(frame: pd.DataFrame) -> pd.DataFrame:
    result = frame.copy()
    index = pd.to_datetime(result.index)
    if index.tz is None:
        index = index.tz_localize("America/New_York")
    result.index = index.tz_convert("UTC")
    result.columns = [str(column).lower() for column in result.columns]
    return result.sort_index()


def _resolve_one(plan: dict[str, Any], frame: pd.DataFrame) -> dict[str, Any]:
    if not str(plan.get("status") or "").startswith("pending"):
        return plan
    try:
        as_of = pd.Timestamp(plan["as_of"])
        as_of = as_of.tz_localize("America/New_York") if as_of.tzinfo is None else as_of
        as_of = as_of.tz_convert("UTC")
        entry = float(plan["entry_reference"])
        stop = float(plan["stop_reference"])
        target = float(plan["target_reference"])
        ttl = max(1, int(plan["ttl_completed_bars"]))
    except (KeyError, TypeError, ValueError):
        return {**plan, "status": "invalid_plan", "resolved_at": datetime.now(timezone.utc).isoformat()}
    future = frame[frame.index > as_of]
    if future.empty:
        return plan
    bullish = plan.get("direction") == "bullish"
    fill_at = None
    fill_bar = None
    for timestamp, bar in future.iloc[:ttl].iterrows():
        touched = float(bar["low"]) <= entry <= float(bar["high"])
        if touched:
            fill_at, fill_bar = timestamp, bar
            break
        invalidated = float(bar["close"]) <= stop if bullish else float(bar["close"]) >= stop
        if invalidated:
            return {**plan, "status": "canceled_before_fill", "resolved_at": timestamp.isoformat()}
    if fill_at is None:
        if len(future) >= ttl:
            return {**plan, "status": "expired_unfilled", "resolved_at": future.index[ttl - 1].isoformat()}
        return plan

    risk = abs(entry - stop)
    for timestamp, bar in future[future.index >= fill_at].iterrows():
        stop_hit = float(bar["low"]) <= stop if bullish else float(bar["high"]) >= stop
        target_hit = float(bar["high"]) >= target if bullish else float(bar["low"]) <= target
        if stop_hit and target_hit:
            return {
                **plan,
                "status": "ambiguous_same_bar",
                "fill_at": fill_at.isoformat(),
                "resolved_at": timestamp.isoformat(),
                "r_multiple": None,
            }
        if stop_hit or target_hit:
            return {
                **plan,
                "status": "resolved_target" if target_hit else "resolved_stop",
                "fill_at": fill_at.isoformat(),
                "resolved_at": timestamp.isoformat(),
                "exit_reference": target if target_hit else stop,
                "r_multiple": round(abs(target - entry) / risk, 6) if target_hit else -1.0,
            }
    return {**plan, "status": "pending_filled", "fill_at": fill_at.isoformat()}


def resolve_plans(
    frames: dict[str, pd.DataFrame],
    *,
    path: Path = DEFAULT_PATH,
    report_path: Path = DEFAULT_REPORT,
) -> dict[str, Any]:
    rows = _read(path)
    normalized = {symbol.upper(): _utc_index(frame) for symbol, frame in frames.items() if frame is not None and not frame.empty}
    resolved = [_resolve_one(row, normalized[str(row.get("symbol") or "").upper()]) if str(row.get("symbol") or "").upper() in normalized else row for row in rows]
    _write(path, resolved)
    scored = [row for row in resolved if row.get("r_multiple") is not None]
    values = [float(row["r_multiple"]) for row in scored]
    wins = [value for value in values if value > 0]
    losses = [value for value in values if value < 0]
    distinct_days = len({str(row.get("fill_at") or "")[:10] for row in scored})
    historical_gate = False
    try:
        historical = json.loads(HISTORICAL_REPORT.read_text(encoding="utf-8-sig"))
        historical_gate = bool((historical.get("promotion_gate") or {}).get("passed"))
    except (OSError, json.JSONDecodeError):
        pass
    expectancy = sum(values) / len(values) if values else None
    profit_factor = sum(wins) / abs(sum(losses)) if losses else (math.inf if wins else None)
    checks = {
        "historical_preregistered_gate_passed": historical_gate,
        "minimum_30_forward_resolved_fills": len(scored) >= 30,
        "minimum_20_forward_dates": distinct_days >= 20,
        "positive_forward_expectancy_r": expectancy is not None and expectancy > 0,
        "forward_profit_factor_gte_1_20": profit_factor is not None and profit_factor >= 1.20,
    }
    report = {
        "provider": "fibonacci_shadow_outcomes",
        "mode": "read_only_forward_underlying_benchmark",
        "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "plan_count": len(resolved),
        "resolved_fill_count": len(scored),
        "distinct_forward_dates": distinct_days,
        "expectancy_r": round(expectancy, 6) if expectancy is not None else None,
        "profit_factor": (
            round(profit_factor, 6)
            if profit_factor is not None and math.isfinite(profit_factor)
            else "infinite_no_losses"
            if profit_factor is not None
            else None
        ),
        "status_counts": {status: sum(row.get("status") == status for row in resolved) for status in sorted({str(row.get("status")) for row in resolved})},
        "promotion_gate": {"passed": all(checks.values()), "checks": checks, "authority": "human_review_only"},
        "execution_enabled": False,
        "can_submit_orders": False,
        "can_change_strategy_gates": False,
        "warnings": [
            "Underlying benchmark outcomes are not option PnL or broker fills.",
            "Same-bar stop/target ambiguity is excluded from scored outcomes.",
            "No promotion, sizing, or execution change is automatic.",
        ],
    }
    _write(report_path, report)
    return report

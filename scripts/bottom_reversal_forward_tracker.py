#!/usr/bin/env python3
"""Forward-only outcome tracker for armed bottom-reversal plans.

The tracker never creates a setup. It records plans emitted by
``bottom_reversal_investigator`` and resolves them using completed daily bars.
Entry-bar stop/target collisions are losses, extended gaps are skipped, and
modeled friction is deducted from every completed trade.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import random
import sys
from collections import defaultdict
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd


ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.bottom_reversal_investigator import REPORT_PATH as INVESTIGATOR_PATH
from scripts.daily_stock_screener import completed_bars
from scripts.market_data import fetch_ohlcv


VIBE_HOME = Path.home() / ".vibe-trading"
STATE_PATH = VIBE_HOME / "state" / "bottom-reversal-forward-state.json"
REPORT_PATH = VIBE_HOME / "reports" / "bottom-reversal-forward-evidence.json"
LOG_PATH = ROOT / "data" / "bottom_reversal_forward_evidence_log.jsonl"
MAX_HOLD_SESSIONS = 10
MAX_ENTRY_GAP_R = 0.25
ROUND_TRIP_FRICTION_BPS = 10.0


def _read_json(path: Path, default: Any) -> Any:
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        return default
    return value


def _atomic_write(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def _signal_id(symbol: str, as_of: str, entry: float, stop: float) -> str:
    identity = f"bottom_reversal_v1|{symbol}|{as_of}|{entry:.6f}|{stop:.6f}"
    return hashlib.sha256(identity.encode("utf-8")).hexdigest()[:24]


def _normalize(frame: pd.DataFrame) -> pd.DataFrame:
    if frame is None or frame.empty:
        return pd.DataFrame()
    bars = frame.copy().sort_index()
    bars.columns = [str(column).lower() for column in bars.columns]
    required = ["open", "high", "low", "close"]
    if not set(required).issubset(bars.columns):
        return pd.DataFrame()
    bars = bars[required].apply(pd.to_numeric, errors="coerce").dropna()
    bars.index = pd.to_datetime(bars.index)
    return bars


def register_plans(state: dict[str, Any], investigator: dict[str, Any]) -> int:
    plans = state.setdefault("plans", {})
    added = 0
    for row in investigator.get("armed_next_session") or []:
        if not isinstance(row, dict):
            continue
        plan = row.get("next_session_plan") if isinstance(row.get("next_session_plan"), dict) else {}
        try:
            symbol = str(row["symbol"]).upper()
            as_of = str(row["as_of"])
            entry = float(plan["entry_trigger"])
            stop = float(plan["invalidation"])
            target = float(plan["target_2r"])
        except (KeyError, TypeError, ValueError):
            continue
        if not stop < entry < target:
            continue
        signal_id = str(plan.get("signal_id") or _signal_id(symbol, as_of, entry, stop))
        if signal_id in plans:
            continue
        plans[signal_id] = {
            "signal_id": signal_id,
            "symbol": symbol,
            "signal_date": as_of,
            "entry_trigger": entry,
            "invalidation": stop,
            "target_2r": target,
            "planned_risk": entry - stop,
            "status": "armed",
            "registered_at": investigator.get("generated_at"),
            "entry_probability": None,
            "probability_status": "not_issued_until_causal_calibration_exists",
        }
        added += 1
    return added


def resolve_plan(plan: dict[str, Any], frame: pd.DataFrame, *, as_of: date) -> dict[str, Any]:
    if plan.get("status") not in {"armed", "open"}:
        return plan
    bars = completed_bars(_normalize(frame), as_of)
    signal_date = date.fromisoformat(str(plan["signal_date"]))
    future = bars[bars.index.date > signal_date]
    if future.empty:
        return plan

    entry_trigger = float(plan["entry_trigger"])
    stop = float(plan["invalidation"])
    target = float(plan["target_2r"])
    planned_risk = float(plan["planned_risk"])
    entry_price = float(plan["entry_price"]) if plan.get("entry_price") is not None else None
    entry_date = date.fromisoformat(str(plan["entry_date"])) if plan.get("entry_date") else None
    held = 0

    for timestamp, bar in future.iterrows():
        bar_date = timestamp.date()
        if entry_date is not None and bar_date < entry_date:
            continue
        if entry_price is None:
            if float(bar["high"]) < entry_trigger:
                continue
            maximum_entry = entry_trigger + MAX_ENTRY_GAP_R * planned_risk
            if float(bar["open"]) > maximum_entry:
                return {
                    **plan,
                    "status": "skipped_gap_extension",
                    "resolved_date": bar_date.isoformat(),
                    "gap_open": round(float(bar["open"]), 4),
                    "maximum_allowed_entry": round(maximum_entry, 4),
                    "trade_counted": False,
                }
            entry_price = max(entry_trigger, float(bar["open"]))
            entry_date = bar_date
            plan = {
                **plan,
                "status": "open",
                "entry_date": entry_date.isoformat(),
                "entry_price": round(entry_price, 4),
            }

        held += 1
        stop_hit = float(bar["low"]) <= stop
        target_hit = float(bar["high"]) >= target
        if stop_hit:
            realized_r = (stop - entry_price) / planned_risk
            reason = "stop_first" if target_hit else "stop"
            exit_price = stop
        elif target_hit:
            realized_r = (target - entry_price) / planned_risk
            reason = "target_2r"
            exit_price = target
        elif held >= MAX_HOLD_SESSIONS:
            exit_price = float(bar["close"])
            realized_r = (exit_price - entry_price) / planned_risk
            reason = "time_exit_10_sessions"
        else:
            continue

        friction_r = (entry_price * ROUND_TRIP_FRICTION_BPS / 10_000.0) / planned_risk
        return {
            **plan,
            "status": "resolved",
            "resolved_date": bar_date.isoformat(),
            "exit_price": round(exit_price, 4),
            "exit_reason": reason,
            "gross_r": round(realized_r, 6),
            "modeled_friction_r": round(friction_r, 6),
            "net_r": round(realized_r - friction_r, 6),
            "trade_counted": True,
            "same_bar_ambiguity": "stop_first",
        }
    return plan


def _bootstrap_lower(values_by_date: dict[str, float], *, samples: int = 4000, seed: int = 20260819) -> float | None:
    values = list(values_by_date.values())
    if len(values) < 10:
        return None
    rng = random.Random(seed)
    means = []
    for _ in range(samples):
        draw = [values[rng.randrange(len(values))] for _ in values]
        means.append(sum(draw) / len(draw))
    means.sort()
    return round(means[int(0.05 * (len(means) - 1))], 6)


def evidence_summary(plans: list[dict[str, Any]]) -> dict[str, Any]:
    resolved = [row for row in plans if row.get("status") == "resolved" and row.get("trade_counted")]
    net = [float(row["net_r"]) for row in resolved if math.isfinite(float(row.get("net_r", math.nan)))]
    by_date: dict[str, float] = defaultdict(float)
    for row in resolved:
        by_date[str(row.get("entry_date"))] += float(row["net_r"])
    equity = peak = 0.0
    max_drawdown = 0.0
    for row in sorted(resolved, key=lambda item: (str(item.get("resolved_date")), str(item.get("signal_id")))):
        equity += float(row["net_r"])
        peak = max(peak, equity)
        max_drawdown = min(max_drawdown, equity - peak)
    lower = _bootstrap_lower(by_date)
    return {
        "resolved_trades": len(resolved),
        "distinct_entry_dates": len(by_date),
        "wins": sum(value > 0 for value in net),
        "win_rate": round(sum(value > 0 for value in net) / len(net), 6) if net else None,
        "average_net_r": round(sum(net) / len(net), 6) if net else None,
        "total_net_r": round(sum(net), 6) if net else None,
        "max_drawdown_r": round(max_drawdown, 6) if net else None,
        "day_clustered_bootstrap_90pct_lower_mean_r": lower,
        "probability_calibration_status": "unavailable_no_causal_probabilities_issued",
    }


def build_report(
    investigator: dict[str, Any],
    *,
    state: dict[str, Any] | None = None,
    frames: dict[str, pd.DataFrame] | None = None,
    as_of: date | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    as_of = as_of or date.today()
    state = dict(state or {"schema_version": 1, "plans": {}})
    state["plans"] = dict(state.get("plans") or {})
    added = register_plans(state, investigator)
    symbols = sorted({str(row.get("symbol")) for row in state["plans"].values() if row.get("symbol")})
    source_frames = dict(frames or {})
    failures: dict[str, str] = {}
    if frames is None:
        for symbol in symbols:
            try:
                source_frames[symbol] = fetch_ohlcv(symbol, lookback_days=120)
            except Exception as exc:
                failures[symbol] = f"{type(exc).__name__}: {exc}"[:180]
    for signal_id, plan in list(state["plans"].items()):
        frame = source_frames.get(str(plan.get("symbol")), pd.DataFrame())
        if not frame.empty:
            state["plans"][signal_id] = resolve_plan(plan, frame, as_of=as_of)
    plans = sorted(state["plans"].values(), key=lambda row: (str(row.get("signal_date")), str(row.get("signal_id"))))
    summary = evidence_summary(plans)
    live_checks = {
        "minimum_50_resolved_trades": summary["resolved_trades"] >= 50,
        "minimum_30_distinct_dates": summary["distinct_entry_dates"] >= 30,
        "positive_net_expectancy": bool(summary["average_net_r"] is not None and summary["average_net_r"] > 0),
        "positive_bootstrap_lower_bound": bool(
            summary["day_clustered_bootstrap_90pct_lower_mean_r"] is not None
            and summary["day_clustered_bootstrap_90pct_lower_mean_r"] > 0
        ),
        "causal_probability_calibration_available": False,
        "explicit_human_approval": False,
    }
    report = {
        "schema_version": 1,
        "provider": "bottom_reversal_forward_tracker",
        "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "date": as_of.isoformat(),
        "mode": "forward_only_read_only_evidence",
        "new_plans_registered": added,
        "summary": summary,
        "plans": plans,
        "fetch_failures": failures,
        "resolution_policy": {
            "entry": "next_completed_session_high_crosses_trigger",
            "maximum_entry_gap_r": MAX_ENTRY_GAP_R,
            "same_bar_ambiguity": "stop_first",
            "maximum_hold_sessions": MAX_HOLD_SESSIONS,
            "round_trip_friction_bps": ROUND_TRIP_FRICTION_BPS,
        },
        "live_capital_gate": {
            "status": "blocked" if not all(live_checks.values()) else "eligible_for_human_review",
            "checks": live_checks,
            "first_live_stage": "one_share_or_defined_risk_max_0_10pct_equity_risk_after_explicit_approval",
        },
        "execution_enabled": False,
        "can_submit_orders": False,
        "orders_submitted": 0,
    }
    state["updated_at"] = report["generated_at"]
    return report, state


def write_outputs(report: dict[str, Any], state: dict[str, Any], *, report_path: Path, state_path: Path, log_path: Path) -> None:
    _atomic_write(report_path, report)
    _atomic_write(state_path, state)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(report, separators=(",", ":"), sort_keys=True) + "\n")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--investigator-path", type=Path, default=INVESTIGATOR_PATH)
    parser.add_argument("--state-path", type=Path, default=STATE_PATH)
    parser.add_argument("--report-path", type=Path, default=REPORT_PATH)
    parser.add_argument("--log-path", type=Path, default=LOG_PATH)
    parser.add_argument("--print", action="store_true", dest="print_report")
    args = parser.parse_args()
    investigator = _read_json(args.investigator_path, {})
    state = _read_json(args.state_path, {"schema_version": 1, "plans": {}})
    report, state = build_report(investigator, state=state)
    write_outputs(report, state, report_path=args.report_path, state_path=args.state_path, log_path=args.log_path)
    if args.print_report:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        summary = report["summary"]
        print(
            "Bottom reversal evidence: "
            f"plans={len(report['plans'])} resolved={summary['resolved_trades']} "
            f"live_gate={report['live_capital_gate']['status']}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

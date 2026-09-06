#!/usr/bin/env python3
"""Completed-daily priority swing observation and revalidation (shadow only)."""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import sys
from datetime import date, datetime, time, timezone
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping
from zoneinfo import ZoneInfo

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts import governed_shadow_alert
from scripts.market_data import fetch_ohlcv
from scripts.priority_focus_universe import PRIORITY_FOCUS_UNIVERSE


ET = ZoneInfo("America/New_York")
VIBE_HOME = Path.home() / ".vibe-trading"
REPORT_PATH = VIBE_HOME / "reports" / "priority-swing-observation.json"
STATE_PATH = VIBE_HOME / "state" / "priority-swing-observation-state.json"
EVENT_PATH = ROOT / "data" / "priority_swing_observation_events.jsonl"
UNIVERSE_SOURCE = "priority_swing_observation_v1_config"
VALID_STATES = {"WATCH", "ARMED", "CONFIRMED", "INVALIDATED"}


def _atomic_json(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(dict(value), indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def _read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def _finite(value: Any) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if math.isfinite(parsed) else None


def completed_adjusted_daily(frame: pd.DataFrame, *, as_of_et: datetime) -> pd.DataFrame:
    """Return daily bars completed by the observation time in New York."""
    if frame is None or frame.empty:
        return pd.DataFrame()
    clock = as_of_et.astimezone(ET)
    result = frame.copy()
    result.columns = [str(column).lower() for column in result.columns]
    required = ["open", "high", "low", "close", "volume"]
    if any(column not in result for column in required):
        return pd.DataFrame()
    result = result[required].apply(pd.to_numeric, errors="coerce").dropna().sort_index()
    allowed_today = clock.time() >= time(16)
    mask = []
    for index in result.index:
        session_date = pd.Timestamp(index).date()
        mask.append(session_date < clock.date() or (allowed_today and session_date == clock.date()))
    completed = result[mask]
    completed.attrs.update(frame.attrs)
    return completed


def _atr(frame: pd.DataFrame, periods: int = 14) -> float | None:
    if len(frame) < periods + 1:
        return None
    previous = frame["close"].shift(1)
    true_range = pd.concat([
        frame["high"] - frame["low"],
        (frame["high"] - previous).abs(),
        (frame["low"] - previous).abs(),
    ], axis=1).max(axis=1)
    value = _finite(true_range.tail(periods).mean())
    return value


def evaluate_symbol(
    symbol: str, daily: pd.DataFrame, *, as_of_et: datetime,
    previous: Mapping[str, Any] | None,
) -> dict[str, Any]:
    frame = completed_adjusted_daily(daily, as_of_et=as_of_et)
    prior_state = str((previous or {}).get("state") or "NONE")
    base = {
        "symbol": symbol.upper(), "previous_state": prior_state,
        "validation_status": "unvalidated_observation", "strict_execution_eligible": False,
        "setup_family": "completed_daily_trend_structure_breakout_observation",
        "source_labels": [
            "completed_adjusted_daily_ohlcv", "daily_sma20_sma50_trend",
            "prior_20_completed_day_structure", "priority_focus_universe_config",
        ],
        "authority": "shadow_observation_only_no_rank_sizing_or_order_authority",
        "execution_enabled": False, "can_submit_orders": False,
    }
    if len(frame) < 51:
        signal_date = str(pd.Timestamp(frame.index[-1]).date()) if not frame.empty else None
        return {
            **base, "state": "INVALIDATED", "signal_date": signal_date, "continuing_setup": False,
            "completed_daily_evidence": {"status": "insufficient", "completed_bar_count": len(frame)},
            "trigger": None, "invalidation": None, "blockers": ["requires_51_completed_adjusted_daily_bars"],
        }
    close, high, low, volume = frame["close"], frame["high"], frame["low"], frame["volume"]
    latest_date = str(pd.Timestamp(frame.index[-1]).date())
    sma20 = float(close.tail(20).mean())
    sma50 = float(close.tail(50).mean())
    prior_high = float(high.iloc[-21:-1].max())
    prior_low = float(low.iloc[-21:-1].min())
    average_volume = float(volume.iloc[-21:-1].mean())
    volume_ratio = float(volume.iloc[-1] / average_volume) if average_volume > 0 else 0.0
    atr = _atr(frame) or max(float(close.iloc[-1]) * 0.01, 0.01)
    trigger = prior_high
    invalidation = min(sma20, float(low.iloc[-1]), prior_low + 0.5 * atr) - 0.10 * atr
    trend_aligned = bool(float(close.iloc[-1]) > sma20 > sma50)
    breakout = bool(float(close.iloc[-1]) > trigger and volume_ratio >= 1.20)
    near_trigger = bool(float(high.iloc[-1]) >= trigger or trigger - float(close.iloc[-1]) <= 0.25 * atr)
    blockers: list[str] = []
    if not trend_aligned:
        blockers.append("completed_daily_trend_not_close_above_sma20_above_sma50")
    if not breakout:
        blockers.append("completed_daily_breakout_with_1_2x_volume_not_confirmed")
    prior_invalidation = _finite((previous or {}).get("invalidation"))
    invalidated_prior = bool(
        prior_state in {"WATCH", "ARMED", "CONFIRMED"}
        and (not trend_aligned or (prior_invalidation is not None and float(close.iloc[-1]) < prior_invalidation))
    )
    if invalidated_prior or not trend_aligned:
        state = "INVALIDATED"
    elif breakout:
        state = "CONFIRMED"
    elif near_trigger:
        state = "ARMED"
    else:
        state = "WATCH"
    continuing = prior_state in {"WATCH", "ARMED", "CONFIRMED"} and state != "INVALIDATED"
    signal_date = str((previous or {}).get("signal_date") or latest_date) if continuing or state == "INVALIDATED" and prior_state != "NONE" else latest_date
    return {
        **base, "state": state, "signal_date": signal_date, "continuing_setup": continuing,
        "completed_daily_evidence": {
            "status": "available", "latest_completed_date": latest_date, "completed_bar_count": len(frame),
            "data_source": str(frame.attrs.get("data_source") or "adjusted_daily_source_unknown"),
            "trend": {
                "close": round(float(close.iloc[-1]), 4), "sma20": round(sma20, 4), "sma50": round(sma50, 4),
                "aligned": trend_aligned,
            },
            "structure": {
                "prior_20_day_high": round(prior_high, 4), "prior_20_day_low": round(prior_low, 4),
                "breakout_confirmed": breakout, "volume_ratio_vs_prior_20": round(volume_ratio, 4),
                "atr14": round(atr, 4),
            },
        },
        "trigger": round(trigger, 4), "invalidation": round(invalidation, 4),
        "blockers": list(dict.fromkeys(blockers)),
    }


def _transition_id(symbol: str, previous_state: str, state: str, signal_date: Any) -> str:
    raw = f"{symbol}|{previous_state}|{state}|{signal_date}|priority-swing-observation-v1"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def build_report(
    *, mode: str, frames: Mapping[str, pd.DataFrame] | None = None,
    as_of_et: datetime | None = None, previous_state: Mapping[str, Any] | None = None,
    symbols: Iterable[str] = PRIORITY_FOCUS_UNIVERSE,
) -> dict[str, Any]:
    if mode not in {"scan", "revalidate"}:
        raise ValueError("mode_must_be_scan_or_revalidate")
    clock = (as_of_et or datetime.now(ET)).astimezone(ET)
    configured = [str(symbol).upper() for symbol in symbols if str(symbol).upper() in PRIORITY_FOCUS_UNIVERSE]
    state = dict(previous_state or {})
    prior_rows = state.get("observations") if isinstance(state.get("observations"), Mapping) else {}
    observations: list[dict[str, Any]] = []
    errors: list[str] = []
    for symbol in configured:
        try:
            frame = frames[symbol] if frames is not None and symbol in frames else fetch_ohlcv(symbol, lookback_days=280)
            observations.append(evaluate_symbol(symbol, frame, as_of_et=clock, previous=prior_rows.get(symbol)))
        except Exception as exc:
            errors.append(f"{symbol}:{type(exc).__name__}:{str(exc)[:120]}")
            observations.append(evaluate_symbol(symbol, pd.DataFrame(), as_of_et=clock, previous=prior_rows.get(symbol)))
    transitions = []
    for row in observations:
        previous = str(row.get("previous_state") or "NONE")
        current = str(row.get("state") or "INVALIDATED")
        if current != previous:
            alertable = (
                previous in {"NONE", "WATCH"} and current in {"ARMED", "CONFIRMED"}
            ) or (
                previous in {"WATCH", "ARMED", "CONFIRMED"} and current == "INVALIDATED"
            )
            transitions.append({
                "schema_version": 1,
                "transition_id": _transition_id(row["symbol"], previous, current, row.get("signal_date")),
                "symbol": row["symbol"], "previous_state": previous, "state": current, "alertable": alertable,
                "signal_date": row.get("signal_date"), "observed_at": clock.isoformat(),
                "setup_family": row.get("setup_family"), "validation_status": "unvalidated_observation",
                "execution_enabled": False, "can_submit_orders": False,
            })
    counts = {value: sum(row["state"] == value for row in observations) for value in sorted(VALID_STATES)}
    return {
        "schema_version": "priority-swing-observation-v1", "provider": "priority_swing_observation",
        "mode": mode, "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "as_of_et": clock.isoformat(), "universe_source": UNIVERSE_SOURCE,
        "priority_symbols": configured,
        "summary": {"symbols_requested": len(configured), "symbols_observed": len(observations) - len(errors), "errors": len(errors), "state_counts": counts},
        "observations": observations, "transition_events": transitions, "errors": errors,
        "notification_attempts": 0, "alerts_sent": 0, "notification_failures": 0,
        "pending_delivery": len([row for row in transitions if row.get("alertable")]),
        "notification_error_classes": {},
        "execution_enabled": False, "can_submit_orders": False,
    }


def _format_alert(event: Mapping[str, Any], row: Mapping[str, Any]) -> str:
    return (
        f"**Priority swing {event.get('state')} | {event.get('symbol')}**\n"
        f"Previous `{event.get('previous_state')}` | signal date `{event.get('signal_date')}`\n"
        f"Trigger `{row.get('trigger')}` | invalidation `{row.get('invalidation')}`\n"
        f"Blockers `{','.join(str(value) for value in row.get('blockers') or []) or 'none'}`\n"
        "Unvalidated completed-daily shadow observation. No order placed."
    )


def _append_unique(path: Path, events: Iterable[Mapping[str, Any]]) -> int:
    seen: set[str] = set()
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            try:
                seen.add(str(json.loads(line).get("transition_id") or ""))
            except json.JSONDecodeError:
                continue
    fresh = [dict(event) for event in events if str(event.get("transition_id") or "") not in seen]
    if fresh:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            for event in fresh:
                handle.write(json.dumps(event, separators=(",", ":"), sort_keys=True) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
    return len(fresh)


def persist_run(
    report: dict[str, Any], *, report_path: Path = REPORT_PATH, state_path: Path = STATE_PATH,
    event_path: Path = EVENT_PATH, alert: bool = False,
    sender: Callable[[str], Mapping[str, Any]] | None = None,
) -> None:
    prior = _read_json(state_path)
    pending = [dict(row) for row in prior.get("pending_alerts") or [] if isinstance(row, dict)]
    alerted = {str(value) for value in prior.get("alerted_transition_ids") or []}
    transitions = [dict(row) for row in report.get("transition_events") or [] if isinstance(row, dict)]
    _append_unique(event_path, transitions)
    if alert:
        by_id = {
            str(row.get("transition_id")): row for row in [*pending, *transitions]
            if row.get("transition_id") and row.get("alertable") is True
        }
        by_symbol = {str(row.get("symbol")): row for row in report.get("observations") or [] if isinstance(row, dict)}
        retry: list[dict[str, Any]] = []
        attempts = failures = sent = 0
        error_classes: dict[str, int] = {}
        transport = sender or governed_shadow_alert.deliver
        for transition_id, event in by_id.items():
            if transition_id in alerted:
                continue
            result = dict(transport(_format_alert(event, by_symbol.get(str(event.get("symbol")), {}))))
            attempts += max(0, int(result.get("attempts") or 0))
            if result.get("delivered") is True:
                alerted.add(transition_id)
                sent += 1
            else:
                failures += 1
                retry.append(event)
                error_class = str(result.get("error_class") or "unknown_delivery_error")
                error_classes[error_class] = error_classes.get(error_class, 0) + 1
        report["notification_attempts"] = attempts
        report["alerts_sent"] = sent
        report["notification_failures"] = failures
        report["pending_delivery"] = len(retry)
        report["notification_error_classes"] = dict(sorted(error_classes.items()))
        report["notification_error_policy"] = "structured_governed_transport_no_webhook_urls_persisted"
        pending = retry
    state_observations = {row["symbol"]: row for row in report.get("observations") or [] if isinstance(row, dict) and row.get("symbol")}
    _atomic_json(state_path, {
        "schema_version": 1, "updated_at": report.get("generated_at"), "observations": state_observations,
        "alerted_transition_ids": sorted(alerted)[-5000:], "pending_alerts": pending,
        "execution_enabled": False, "can_submit_orders": False,
    })
    _atomic_json(report_path, report)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=("scan", "revalidate"), default="scan")
    parser.add_argument("--alert", action="store_true")
    parser.add_argument("--report-path", type=Path, default=REPORT_PATH)
    parser.add_argument("--state-path", type=Path, default=STATE_PATH)
    parser.add_argument("--event-path", type=Path, default=EVENT_PATH)
    parser.add_argument("--print", action="store_true", dest="print_report")
    args = parser.parse_args()
    previous = _read_json(args.state_path)
    report = build_report(mode=args.mode, previous_state=previous)
    persist_run(report, report_path=args.report_path, state_path=args.state_path, event_path=args.event_path, alert=args.alert)
    if args.print_report:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        print(json.dumps(report["summary"], sort_keys=True))
    return 0 if not report["errors"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

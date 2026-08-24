#!/usr/bin/env python3
"""Frozen MES 09:32 ET ORB v2 shadow logger.

Observes the exact `mes-orb-0932-vix-v2` candidate specified in
`research/preregistrations/mes_orb_0932_vix_v2.md` and
`research/FROZEN_STRATEGY_1_2026-08-22.md`. No order authority.

Modes:
  --mode entry    Fired at 09:47 ET (after 09:30-09:45 trigger window closes).
                  Records the first eligible 5m trigger + entry/stop/target plan.
  --mode resolve  Fired at 12:05 ET (after frozen 12:00 ET time exit).
                  Replays completed 2m bars to score the entry with adverse-first
                  tie-breaks and emits a terminal outcome record.

The output ledger `data/mes_orb_0932_vix_v2_shadow_log.jsonl` is consumed by
`scripts/shadow_outcome_resolver.py`; the plan_id ties the entry candidate to
the terminal outcome exactly once per session.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import sys
import warnings
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

STRATEGY_ID = "mes-orb-0932-vix-v2"
FAMILY_ID = "mes-opening-breakout"
SPEC_HASH = "sha256:1b5b00351729d29d41f9b58cf3bbe7ad66d5edda594d29d405af72279dd4fd5b"
SPEC_PATH = "research/preregistrations/mes_orb_0932_vix_v2.md"
LOG_PATH = ROOT / "data" / "mes_orb_0932_vix_v2_shadow_log.jsonl"
HMM_REPORT = Path.home() / ".vibe-trading" / "reports" / "hmm-regime.json"

ET = ZoneInfo("America/New_York")
POINT_VALUE = 5.0                    # MES $5 per index point
TICK_SIZE = 0.25                     # MES tick
COMMISSION_ROUND_TRIP = 0.70         # $0.35/side per contract
SLIPPAGE_TICKS_ROUND_TRIP = 2        # 1 tick entry + 1 tick exit
FRICTION_ROUND_TRIP = COMMISSION_ROUND_TRIP + SLIPPAGE_TICKS_ROUND_TRIP * TICK_SIZE * POINT_VALUE

VIX_MIN = 15.0
VIX_MAX = 25.0
BREAKOUT_BUFFER = 0.001              # 0.10% beyond opening range
RVOL_MIN = 1.5
RVOL_LOOKBACK_SESSIONS = 5
ELIGIBLE_WEEKDAYS = {0, 2, 4}        # Mon, Wed, Fri
TRIGGER_START = time(9, 30)
TRIGGER_END = time(9, 45)
ENTRY_CAPTURE_START = time(9, 45)
ENTRY_CAPTURE_END = time(10, 0)
TIME_EXIT = time(12, 0)
BREAK_EVEN_R = 0.5
BREAK_EVEN_MIN_AFTER = timedelta(minutes=15)
QUANTITY = 1


# ---------------------------------------------------------------------------
# Data loaders (yfinance MES=F proxy; Databento upgrade tracked separately).
# ---------------------------------------------------------------------------

def _yfinance_download(symbol: str, *, period: str, interval: str, prepost: bool) -> Any:
    import yfinance as yf

    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        return yf.download(
            symbol,
            period=period,
            interval=interval,
            auto_adjust=False,
            prepost=prepost,
            progress=False,
        )


def download_mes_2m(period: str = "5d") -> Any:
    return _yfinance_download("MES=F", period=period, interval="2m", prepost=False)


def download_mes_5m(period: str = "10d") -> Any:
    return _yfinance_download("MES=F", period=period, interval="5m", prepost=False)


def download_vix_daily(period: str = "15d") -> Any:
    del period
    import pandas as pd

    from scripts.market_data import fetch_vix_context

    row = fetch_vix_context()
    if row.get("available") is False or row.get("date") is None or row.get("close") is None:
        raise ValueError("official CBOE VIX prior close unavailable")
    return pd.DataFrame(
        {"Close": [float(row["close"])]},
        index=pd.DatetimeIndex([pd.to_datetime(row["date"])]),
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def utc_now_z(instant: datetime | None = None) -> str:
    return (instant or datetime.now(timezone.utc)).astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _flatten(frame: Any) -> Any:
    import pandas as pd

    if isinstance(frame.columns, pd.MultiIndex):
        frame = frame.copy()
        frame.columns = frame.columns.get_level_values(0)
    return frame


def _to_et(frame: Any) -> Any:
    import pandas as pd

    frame = _flatten(frame).sort_index()
    if not isinstance(frame.index, pd.DatetimeIndex):
        raise TypeError("market data must use a DatetimeIndex")
    if frame.index.tz is None:
        frame.index = frame.index.tz_localize("America/New_York")
    else:
        frame.index = frame.index.tz_convert("America/New_York")
    return frame


def _records(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8-sig").splitlines():
        if line.strip():
            rows.append(json.loads(line))
    return rows


def _append_record(record: dict[str, Any], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(record, separators=(",", ":"), sort_keys=True) + "\n")


def _replace_records(rows: list[dict[str, Any]], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        "".join(json.dumps(row, separators=(",", ":"), sort_keys=True) + "\n" for row in rows),
        encoding="utf-8",
    )
    os.replace(temporary, path)


def _base_record(event_type: str, as_of: datetime) -> dict[str, Any]:
    return {
        "event_type": event_type,
        "type": event_type,
        "captured_at": utc_now_z(as_of),
        "timestamp": utc_now_z(as_of),
        "preregistration": SPEC_PATH,
        "spec_hash": SPEC_HASH,
        "strategy_id": STRATEGY_ID,
        "candidate_id": STRATEGY_ID,
        "family_id": FAMILY_ID,
        "setup_family": FAMILY_ID,
        "data_source": "yfinance_proxy_MES=F_2m_5m_and_cboe_official_VIX",
        "evidence_tier": "proxy_ohlcv_non_executable",
        "promotion_eligible": False,
        "evidence_blockers": ["databento_mbo_and_executable_quotes_required"],
        "execution_mode": "shadow_only",
        "execution_enabled": False,
        "can_submit_orders": False,
    }


# ---------------------------------------------------------------------------
# Regime + macro gates
# ---------------------------------------------------------------------------

def _hmm_state(session_date: date, report_path: Path = HMM_REPORT) -> str | None:
    try:
        payload = json.loads(report_path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        return None
    aggregate = payload.get("aggregate") or {}
    report_date_raw = payload.get("date") or str(payload.get("timestamp") or "")[:10]
    try:
        report_date = date.fromisoformat(str(report_date_raw))
    except ValueError:
        return None
    age_days = (session_date - report_date).days
    if age_days < 0 or age_days > 3:
        return None
    state = aggregate.get("state")
    if isinstance(state, str):
        return state
    return None


def _macro_block(day: date) -> tuple[bool, list[str]]:
    """Return (blocked, event_names) for CPI/PCE/PPI/NFP/FOMC/GDP in RTH window."""
    try:
        from scripts.market_catalyst_calendar import events_for_date
    except Exception:
        return True, ["macro_calendar_unavailable"]
    events = events_for_date(day) or []
    macro_tags = ("CPI", "PCE", "PPI", "Nonfarm", "Payroll", "NFP", "FOMC", "GDP")
    blocked_names: list[str] = []
    for event in events:
        name = str(event.get("name", ""))
        if not any(tag.lower() in name.lower() for tag in macro_tags):
            continue
        impact = str(event.get("impact", "")).lower()
        if impact not in {"medium", "high"}:
            continue
        event_time = str(event.get("time_et", ""))
        try:
            hour, minute = event_time.split(":")
            release = time(int(hour), int(minute))
        except (ValueError, AttributeError):
            release = None
        if release is None or (time(9, 30) <= release <= time(15, 30)):
            blocked_names.append(name)
    return bool(blocked_names), blocked_names


# ---------------------------------------------------------------------------
# Session slicing + opening range
# ---------------------------------------------------------------------------

def _session_frame(frame: Any, session_date: date, start: str, end: str) -> Any:
    frame = _to_et(frame)
    day_rows = frame[frame.index.date == session_date]
    return day_rows.between_time(start, end)


def opening_range(bars_2m: Any, session_date: date) -> tuple[float, float]:
    rows = _session_frame(bars_2m, session_date, "09:30", "09:31")
    if rows.empty:
        raise ValueError("opening range 09:30-09:31 unavailable")
    return float(rows["High"].max()), float(rows["Low"].min())


def rvol_baseline(bars_5m: Any, session_date: date, bar_start: time) -> float | None:
    frame = _to_et(bars_5m)
    reference_end = time((bar_start.hour * 60 + bar_start.minute + 5) // 60, (bar_start.minute + 5) % 60)
    start_str = bar_start.strftime("%H:%M")
    end_str = reference_end.strftime("%H:%M")
    prior_dates = sorted({d for d in frame.index.date if d < session_date})
    prior_dates = prior_dates[-RVOL_LOOKBACK_SESSIONS:]
    if len(prior_dates) < RVOL_LOOKBACK_SESSIONS:
        return None
    volumes: list[float] = []
    for prior in prior_dates:
        window = frame[frame.index.date == prior].between_time(start_str, end_str)
        if window.empty:
            continue
        volumes.append(float(window["Volume"].iloc[0]))
    if len(volumes) != RVOL_LOOKBACK_SESSIONS:
        return None
    return sum(volumes) / len(volumes)


# ---------------------------------------------------------------------------
# Entry decision
# ---------------------------------------------------------------------------

def build_entry_plan(
    bars_2m: Any,
    bars_5m: Any,
    vix_daily: Any,
    session_date: date,
    *,
    hmm_state: str | None,
    macro_blocked: bool,
    macro_names: list[str],
) -> dict[str, Any]:
    reasons: list[str] = []
    filters: dict[str, Any] = {}

    filters["day_of_week"] = session_date.strftime("%A")
    if session_date.weekday() not in ELIGIBLE_WEEKDAYS:
        reasons.append("day_of_week_not_mon_wed_fri")

    or_high, or_low = opening_range(bars_2m, session_date)
    filters["opening_range"] = {"high": or_high, "low": or_low, "width": or_high - or_low}

    vix_frame = _flatten(vix_daily).copy()
    vix_frame = vix_frame[vix_frame.index.date < session_date]
    if vix_frame.empty or "Close" not in vix_frame:
        raise ValueError("prior VIX close unavailable")
    vix_close = float(vix_frame["Close"].dropna().iloc[-1])
    filters["vix_prior_close"] = vix_close
    filters["vix_source"] = "cboe_vix_history"
    filters["vix_observed_session"] = vix_frame["Close"].dropna().index[-1].date().isoformat()
    if not (VIX_MIN <= vix_close <= VIX_MAX):
        reasons.append(f"vix_out_of_band_{vix_close:.2f}")

    filters["hmm_state"] = hmm_state
    if hmm_state != "trend":
        reasons.append(f"hmm_state_{hmm_state or 'unavailable'}")

    filters["macro_blocked"] = macro_blocked
    filters["macro_events"] = macro_names
    if macro_blocked:
        reasons.append("macro_event_in_rth_window")

    triggers_frame = _session_frame(bars_5m, session_date, "09:30", "09:44")
    trigger: dict[str, Any] | None = None
    for timestamp, row in triggers_frame.iterrows():
        bar_time = timestamp.time()
        if bar_time < TRIGGER_START or bar_time >= TRIGGER_END:
            continue
        close = float(row["Close"])
        volume = float(row["Volume"])
        long_level = or_high * (1 + BREAKOUT_BUFFER)
        short_level = or_low * (1 - BREAKOUT_BUFFER)
        direction: str | None = None
        if close >= long_level:
            direction = "long"
        elif close <= short_level:
            direction = "short"
        if direction is None:
            continue
        baseline = rvol_baseline(bars_5m, session_date, bar_time)
        rvol = (volume / baseline) if baseline and baseline > 0 else None
        rvol_pass = bool(rvol is not None and rvol >= RVOL_MIN)
        trigger = {
            "bar_open_et": bar_time.strftime("%H:%M"),
            "close": close,
            "volume": volume,
            "direction": direction,
            "rvol": rvol,
            "rvol_baseline": baseline,
            "rvol_pass": rvol_pass,
            "trigger_timestamp": timestamp.isoformat(),
            "actionable_at": (timestamp + timedelta(minutes=5)).isoformat(),
        }
        if not rvol_pass:
            reasons.append("rvol_below_1_5")
        break

    filters["trigger"] = trigger
    if trigger is None:
        reasons.append("no_qualifying_trigger_in_first_15m")
        return {"should_enter": False, "filters": filters, "reason": ";".join(reasons) or "no_trigger"}

    or_width = or_high - or_low
    if direction := trigger["direction"]:
        entry_price = float(trigger["close"])
        if direction == "long":
            stop_price = or_low - TICK_SIZE
            t1_price = entry_price + or_width
            t2_price = entry_price + 2.0 * or_width
        else:
            stop_price = or_high + TICK_SIZE
            t1_price = entry_price - or_width
            t2_price = entry_price - 2.0 * or_width
    stop_distance = abs(entry_price - stop_price)
    max_risk = stop_distance * POINT_VALUE

    plan = {
        "direction": direction,
        "entry_price": entry_price,
        "stop_price": stop_price,
        "t1_price": t1_price,
        "t2_price": t2_price,
        "stop_distance_pts": stop_distance,
        "max_risk_per_contract": max_risk,
        "opening_range": filters["opening_range"],
        "trigger": trigger,
    }

    if reasons:
        return {"should_enter": False, "filters": filters, "plan": plan, "reason": ";".join(reasons)}
    return {"should_enter": True, "filters": filters, "plan": plan, "reason": "eligible"}


# ---------------------------------------------------------------------------
# Terminal resolution
# ---------------------------------------------------------------------------

def _bar_hit(low: float, high: float, target: float, direction_up: bool) -> bool:
    return (direction_up and high >= target) or ((not direction_up) and low <= target)


def resolve_plan(bars_2m: Any, session_date: date, plan: Mapping[str, Any]) -> dict[str, Any]:
    frame = _session_frame(bars_2m, session_date, "09:30", "12:00")
    trigger_ts = datetime.fromisoformat(str(plan["trigger"]["trigger_timestamp"]))
    actionable_at = datetime.fromisoformat(str(plan["trigger"].get("actionable_at") or trigger_ts + timedelta(minutes=5)))
    forward = frame[frame.index >= actionable_at]
    if forward.empty:
        raise ValueError("post-trigger bars unavailable")

    direction = plan["direction"]
    is_long = direction == "long"
    entry_price = float(plan["entry_price"])
    stop_price = float(plan["stop_price"])
    t1_price = float(plan["t1_price"])
    t2_price = float(plan["t2_price"])
    stop_distance = float(plan["stop_distance_pts"])
    trigger_dt = actionable_at

    banked_half_pts = 0.0
    remaining_open = True
    remaining_exit_pts = 0.0
    t1_hit = False
    stop_price_dynamic = stop_price
    exit_reason = "time_stop_12_00_et"
    exit_timestamp: datetime | None = None
    exit_price_observed_proxy: float | None = None
    break_even_moved = False

    for timestamp, row in forward.iterrows():
        if not remaining_open:
            break
        low = float(row["Low"])
        high = float(row["High"])

        # Adverse-first tie break: check stop before target inside same bar.
        hit_stop = _bar_hit(low, high, stop_price_dynamic, direction_up=not is_long)
        hit_t1 = (not t1_hit) and _bar_hit(low, high, t1_price, direction_up=is_long)
        hit_t2 = t1_hit and _bar_hit(low, high, t2_price, direction_up=is_long)

        if hit_stop:
            if not t1_hit:
                banked_half_pts = 0.0
                remaining_exit_pts = (stop_price_dynamic - entry_price) if is_long else (entry_price - stop_price_dynamic)
                remaining_open = False
                exit_reason = "stop_before_t1"
                exit_price_observed_proxy = stop_price_dynamic
                exit_timestamp = timestamp
                break
            remaining_exit_pts = (stop_price_dynamic - entry_price) if is_long else (entry_price - stop_price_dynamic)
            remaining_open = False
            exit_reason = "trail_stop_after_t1"
            exit_price_observed_proxy = stop_price_dynamic
            exit_timestamp = timestamp
            break

        if hit_t1:
            banked_half_pts = 0.5 * ((t1_price - entry_price) if is_long else (entry_price - t1_price))
            t1_hit = True
            stop_price_dynamic = (entry_price + TICK_SIZE) if is_long else (entry_price - TICK_SIZE)
            break_even_moved = True
            if hit_t2 and (t2_price >= t1_price if is_long else t2_price <= t1_price):
                remaining_exit_pts = (t2_price - entry_price) if is_long else (entry_price - t2_price)
                remaining_exit_pts *= 0.5
                remaining_open = False
                exit_reason = "t2_after_t1"
                exit_timestamp = timestamp
                exit_price_observed_proxy = t2_price
                break
            continue

        if hit_t2:
            remaining_exit_pts = 0.5 * ((t2_price - entry_price) if is_long else (entry_price - t2_price))
            remaining_open = False
            exit_reason = "t2_after_t1"
            exit_timestamp = timestamp
            exit_price_observed_proxy = t2_price
            break

        # Break-even nudge after 15 minutes and >=0.5R w/o T1.
        minutes_since = (timestamp - trigger_dt).total_seconds() / 60.0
        if not break_even_moved and not t1_hit and minutes_since >= BREAK_EVEN_MIN_AFTER.total_seconds() / 60.0:
            unrealized_pts = (high - entry_price) if is_long else (entry_price - low)
            if unrealized_pts >= BREAK_EVEN_R * stop_distance:
                stop_price_dynamic = entry_price
                break_even_moved = True

    if remaining_open:
        final_row = forward.iloc[-1]
        exit_price = float(final_row["Close"])
        remaining_exit_pts = (exit_price - entry_price) if is_long else (entry_price - exit_price)
        if t1_hit:
            remaining_exit_pts *= 0.5
        exit_reason = "time_stop_12_00_et"
        exit_timestamp = forward.index[-1]
        exit_price_observed_proxy = exit_price

    total_pts = banked_half_pts + remaining_exit_pts
    gross = total_pts * POINT_VALUE * QUANTITY
    net = gross - FRICTION_ROUND_TRIP * QUANTITY
    outcome = "win" if net > 0 else ("loss" if net < 0 else "flat")

    return {
        "exit_reason": exit_reason,
        "exit_timestamp": exit_timestamp.isoformat() if exit_timestamp is not None else None,
        "exit_price_observed_proxy": exit_price_observed_proxy,
        "t1_hit": t1_hit,
        "banked_half_pts": round(banked_half_pts, 4),
        "remaining_exit_pts": round(remaining_exit_pts, 4),
        "total_pts": round(total_pts, 4),
        "gross_dollar": round(gross, 2),
        "friction_round_trip_dollar": FRICTION_ROUND_TRIP,
        "net_dollar": round(net, 2),
        "outcome": outcome,
    }


# ---------------------------------------------------------------------------
# Entrypoints
# ---------------------------------------------------------------------------

def _unsettled_entry(path: Path, key: str) -> dict[str, Any] | None:
    for row in _records(path):
        if row.get("event_type") == "entry" and row.get("plan_id") == key and not row.get("settled"):
            return row
    return None


def run_entry(*, as_of: datetime | None = None, log_path: Path = LOG_PATH) -> int:
    as_of = as_of or datetime.now(ET)
    session_date = as_of.astimezone(ET).date()
    plan_id = f"{STRATEGY_ID}:{session_date.isoformat()}"

    existing = _records(log_path)
    if any(row.get("event_type") == "entry" and row.get("plan_id") == plan_id for row in existing):
        message = {"status": "duplicate_ignored", "plan_id": plan_id}
        print(json.dumps(message))
        return 0

    local_time = as_of.astimezone(ET).time().replace(tzinfo=None)
    if not (ENTRY_CAPTURE_START <= local_time <= ENTRY_CAPTURE_END):
        record = _base_record("entry", as_of) | {
            "candidate_id": STRATEGY_ID,
            "plan_id": plan_id,
            "trade_key": plan_id,
            "session_date": session_date.isoformat(),
            "should_enter": False,
            "reason": "outside_entry_capture_window",
            "settled": True,
        }
        _append_record(record, log_path)
        print(json.dumps(record, separators=(",", ":"), sort_keys=True))
        return 0

    hmm = _hmm_state(session_date)
    macro_blocked, macro_names = _macro_block(session_date)

    try:
        bars_2m = download_mes_2m()
        bars_5m = download_mes_5m()
        vix = download_vix_daily()
        decision = build_entry_plan(
            bars_2m,
            bars_5m,
            vix,
            session_date,
            hmm_state=hmm,
            macro_blocked=macro_blocked,
            macro_names=macro_names,
        )
        filters = decision["filters"]
        context_observed_at = utc_now_z(as_of)
        filters["macro_source"] = "market_catalyst_calendar"
        filters["macro_observed_at"] = context_observed_at
        filters["hmm_source"] = "hmm_regime_report"
        filters["hmm_observed_at"] = (
            datetime.fromtimestamp(HMM_REPORT.stat().st_mtime, tz=timezone.utc)
            .isoformat()
            .replace("+00:00", "Z")
            if HMM_REPORT.exists()
            else None
        )
        vix_session = date.fromisoformat(str(filters["vix_observed_session"]))
        filters["vix_observed_at"] = (
            datetime.combine(vix_session, time(16, 15), ET)
            .astimezone(timezone.utc)
            .isoformat()
            .replace("+00:00", "Z")
        )
        plan = decision.get("plan")
        record = _base_record("entry", as_of) | {
            "candidate_id": STRATEGY_ID,
            "plan_id": plan_id,
            "trade_key": plan_id,
            "session_date": session_date.isoformat(),
            "should_enter": decision["should_enter"],
            "reason": decision["reason"],
            "filters": decision["filters"],
            "settled": not decision["should_enter"],
        }
        if plan:
            record["plan"] = plan
            record["direction"] = plan["direction"]
            record["entry_price"] = plan["entry_price"]
            record["created_at"] = plan["trigger"]["actionable_at"]
            record["entry_price_observed_proxy"] = plan["entry_price"]
            record["stop_price"] = plan["stop_price"]
            record["t1_price"] = plan["t1_price"]
            record["t2_price"] = plan["t2_price"]
            record["max_risk_per_contract"] = plan["max_risk_per_contract"]
            record["quantity"] = QUANTITY
            record["effective_qty"] = QUANTITY
            record["stop_distance_pts"] = plan["stop_distance_pts"]
    except Exception as exc:  # data provider brittleness handled explicitly
        record = _base_record("entry", as_of) | {
            "candidate_id": STRATEGY_ID,
            "plan_id": plan_id,
            "trade_key": plan_id,
            "session_date": session_date.isoformat(),
            "should_enter": False,
            "reason": "market_data_incomplete",
            "error": str(exc)[:240],
            "settled": True,
        }

    _append_record(record, log_path)
    print(json.dumps(record, separators=(",", ":"), sort_keys=True))
    return 0


def run_resolve(*, as_of: datetime | None = None, log_path: Path = LOG_PATH) -> int:
    as_of = as_of or datetime.now(ET)
    session_date = as_of.astimezone(ET).date()
    plan_id = f"{STRATEGY_ID}:{session_date.isoformat()}"

    entry = _unsettled_entry(log_path, plan_id)
    if entry is None:
        record = _base_record("resolve_noop", as_of) | {
            "candidate_id": STRATEGY_ID,
            "plan_id": plan_id,
            "reason": "no_unsettled_entry_for_session",
        }
        _append_record(record, log_path)
        print(json.dumps(record, separators=(",", ":"), sort_keys=True))
        return 0

    plan = entry.get("plan") or {}
    if not plan or not entry.get("should_enter"):
        record = _base_record("exit", as_of) | {
            "candidate_id": STRATEGY_ID,
            "plan_id": plan_id,
            "trade_key": plan_id,
            "resolved_at": utc_now_z(as_of),
            "reason": "no_actionable_plan",
            "settled": True,
        }
        _finalize(entry, record, log_path)
        print(json.dumps(record, separators=(",", ":"), sort_keys=True))
        return 0

    try:
        bars_2m = download_mes_2m()
        summary = resolve_plan(bars_2m, session_date, plan)
        pnl = summary["net_dollar"]
        exit_reason = summary["exit_reason"]
        max_risk = float(entry.get("max_risk_per_contract") or 0.0)
        outcome_r = (pnl / max_risk) if max_risk else None
        record = _base_record("exit", as_of) | {
            "candidate_id": STRATEGY_ID,
            "plan_id": plan_id,
            "trade_key": plan_id,
            "resolved_at": utc_now_z(as_of),
            "session_date": session_date.isoformat(),
            "entry_price": entry.get("entry_price"),
            "entry_price_observed_proxy": entry.get("entry_price_observed_proxy"),
            "stop_price": entry.get("stop_price"),
            "t1_price": entry.get("t1_price"),
            "t2_price": entry.get("t2_price"),
            "exit_reason": exit_reason,
            "reason": exit_reason,
            "exit_timestamp": summary["exit_timestamp"],
            "exit_price_observed_proxy": summary["exit_price_observed_proxy"],
            "exit_fill_executable": None,
            "exit_bid": None,
            "exit_price": None,
            "outcome": summary["outcome"],
            "outcome_r": outcome_r,
            "gross_dollar": summary["gross_dollar"],
            "friction_round_trip_dollar": FRICTION_ROUND_TRIP,
            "net_dollar": summary["net_dollar"],
            "pnl_before_fees": summary["gross_dollar"],
            "promotion_eligible": False,
            "quantity": QUANTITY,
            "detail": summary,
            "settled": True,
        }
    except Exception as exc:
        record = _base_record("exit", as_of) | {
            "candidate_id": STRATEGY_ID,
            "plan_id": plan_id,
            "trade_key": plan_id,
            "resolved_at": utc_now_z(as_of),
            "reason": "market_data_incomplete",
            "error": str(exc)[:240],
            "settled": True,
        }

    _finalize(entry, record, log_path)
    print(json.dumps(record, separators=(",", ":"), sort_keys=True))
    return 0


def _finalize(entry_row: dict[str, Any], terminal_row: dict[str, Any], log_path: Path) -> None:
    rows = _records(log_path)
    for row in rows:
        if row is entry_row:
            row["settled"] = True
        if row.get("event_type") == "entry" and row.get("plan_id") == entry_row.get("plan_id"):
            row["settled"] = True
    rows.append(terminal_row)
    _replace_records(rows, log_path)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=("entry", "resolve"), required=True)
    parser.add_argument("--log-path", type=Path, default=LOG_PATH)
    args = parser.parse_args()
    if args.mode == "entry":
        return run_entry(log_path=args.log_path)
    return run_resolve(log_path=args.log_path)


if __name__ == "__main__":
    raise SystemExit(main())

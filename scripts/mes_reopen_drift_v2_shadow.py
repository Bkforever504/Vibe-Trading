#!/usr/bin/env python3
"""Frozen MES reopen drift v2 shadow logger.

Observes the exact `mes-reopen-drift-v2` candidate specified in
`research/preregistrations/mes_reopen_drift_v2.md` and
`research/FROZEN_STRATEGY_3_2026-08-22.md`. No order authority.

Modes:
  --mode entry    Fired at 18:35 ET (after the 17:00-17:30 CT / 18:00-18:30 ET
                  reopen 30-minute bar closes). Records the direction, entry,
                  stop, targets, Hurst, and macro-blocker context.
  --mode resolve  Fired at 08:35 ET the next trading day (after the frozen
                  08:30 ET flat-time). Replays completed 30-minute ETH bars to
                  score the entry with adverse-first tie-breaks.

The output ledger `data/mes_reopen_drift_v2_shadow_log.jsonl` is consumed by
`scripts/shadow_outcome_resolver.py`; the plan_id ties the entry candidate to
the terminal outcome exactly once per ETH session.
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

from scripts.hurst_regime_scanner import hurst_exponent

STRATEGY_ID = "mes-reopen-drift-v2"
FAMILY_ID = "mes-overnight-drift"
SPEC_HASH = "sha256:3a345679af8d94402cd8a0d06406635f093aa843fa24dd1324d66429144f42ad"
SPEC_PATH = "research/preregistrations/mes_reopen_drift_v2.md"
LOG_PATH = ROOT / "data" / "mes_reopen_drift_v2_shadow_log.jsonl"

ET = ZoneInfo("America/New_York")
CT = ZoneInfo("America/Chicago")
POINT_VALUE = 5.0
TICK_SIZE = 0.25
COMMISSION_ROUND_TRIP = 0.70
SLIPPAGE_TICKS_ROUND_TRIP = 4        # 2 ticks per side per spec §9
FRICTION_ROUND_TRIP = COMMISSION_ROUND_TRIP + SLIPPAGE_TICKS_ROUND_TRIP * TICK_SIZE * POINT_VALUE

VIX_MIN = 12.0
VIX_MAX = 28.0
HURST_MIN = 0.52
HURST_WINDOW_BARS = 100
VOLUME_MULTIPLE = 0.6
VOLUME_LOOKBACK_SESSIONS = 5
RTH_TOP_BOTTOM_FRACTION = 0.4
ATR_PERIOD = 14
ATR_STOP_MULT = 1.5
T2_MULT = 2.5
BREAK_EVEN_R = 1.0
BREAK_EVEN_MIN_AFTER = timedelta(hours=2)
EARLY_EXIT_R = -0.5
EARLY_EXIT_AFTER = timedelta(hours=4)
QUANTITY = 1
ELIGIBLE_WEEKDAYS = {0, 1, 2, 3}  # Monday-Thursday RTH close into next session
ENTRY_CAPTURE_START = time(18, 30)
ENTRY_CAPTURE_END = time(19, 0)


# ---------------------------------------------------------------------------
# Data loaders
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


def download_mes_30m(period: str = "20d") -> Any:
    return _yfinance_download("MES=F", period=period, interval="30m", prepost=True)


def download_mes_1h(period: str = "60d") -> Any:
    return _yfinance_download("MES=F", period=period, interval="60m", prepost=True)


def download_mes_5m(period: str = "10d") -> Any:
    return _yfinance_download("MES=F", period=period, interval="5m", prepost=True)


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


def _to_tz(frame: Any, tz: ZoneInfo) -> Any:
    import pandas as pd

    frame = _flatten(frame).sort_index()
    if not isinstance(frame.index, pd.DatetimeIndex):
        raise TypeError("market data must use a DatetimeIndex")
    if frame.index.tz is None:
        frame.index = frame.index.tz_localize("America/New_York")
    return frame.tz_convert(tz)


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
        "data_source": "yfinance_proxy_MES=F_30m_1h_5m_and_cboe_official_VIX",
        "evidence_tier": "proxy_ohlcv_non_executable",
        "promotion_eligible": False,
        "evidence_blockers": ["databento_mbo_and_executable_quotes_required"],
        "execution_mode": "shadow_only",
        "execution_enabled": False,
        "can_submit_orders": False,
    }


# ---------------------------------------------------------------------------
# Filters
# ---------------------------------------------------------------------------

def _macro_block_next_day(next_day: date) -> tuple[bool, list[str]]:
    try:
        from scripts.market_catalyst_calendar import events_for_date
    except Exception:
        return True, ["macro_calendar_unavailable"]
    events = events_for_date(next_day) or []
    macro_tags = ("FOMC", "CPI", "Nonfarm", "Payroll", "NFP", "ECB", "BOJ")
    hits: list[str] = []
    for event in events:
        name = str(event.get("name", ""))
        impact = str(event.get("impact", "")).lower()
        if impact not in {"medium", "high"}:
            continue
        if any(tag.lower() in name.lower() for tag in macro_tags):
            hits.append(name)
    return bool(hits), hits


def rth_close_bias(bars_5m: Any, session_date: date) -> dict[str, Any]:
    frame = _to_tz(bars_5m, ET)
    day = frame[frame.index.date == session_date].between_time("09:30", "15:59")
    if day.empty:
        raise ValueError("RTH session data unavailable")
    high = float(day["High"].max())
    low = float(day["Low"].min())
    close = float(day["Close"].iloc[-1])
    typical = (day["High"] + day["Low"] + day["Close"]) / 3.0
    volume = day["Volume"].astype(float)
    vwap_series = (typical * volume).cumsum() / volume.cumsum().replace(0, math.nan)
    vwap = float(vwap_series.iloc[-1]) if not vwap_series.dropna().empty else float("nan")
    session_range = high - low if high > low else 0.0
    frac = ((close - low) / session_range) if session_range > 0 else 0.5
    direction: str | None = None
    if frac >= (1 - RTH_TOP_BOTTOM_FRACTION) and close > vwap:
        direction = "long"
    elif frac <= RTH_TOP_BOTTOM_FRACTION and close < vwap:
        direction = "short"
    return {
        "rth_high": high,
        "rth_low": low,
        "rth_close": close,
        "rth_vwap": vwap,
        "close_fraction": round(frac, 4),
        "direction": direction,
    }


def eth_volume_baseline(bars_30m: Any, entry_ts_ct: datetime) -> tuple[float, float | None]:
    frame = _to_tz(bars_30m, CT)
    same_time_hour = entry_ts_ct.time().strftime("%H:%M")
    dates = sorted({d for d in frame.index.date if d < entry_ts_ct.date()})
    dates = dates[-VOLUME_LOOKBACK_SESSIONS:]
    volumes: list[float] = []
    for prior in dates:
        rows = frame[frame.index.date == prior].between_time(same_time_hour, same_time_hour)
        if rows.empty:
            continue
        volumes.append(float(rows["Volume"].iloc[0]))
    trigger_rows = frame[
        (frame.index.date == entry_ts_ct.date())
    ].between_time(same_time_hour, same_time_hour)
    if trigger_rows.empty:
        raise ValueError("trigger 30m bar unavailable")
    trigger_volume = float(trigger_rows["Volume"].iloc[0])
    baseline = (sum(volumes) / len(volumes)) if len(volumes) == VOLUME_LOOKBACK_SESSIONS else None
    return trigger_volume, baseline


def trigger_bar(bars_30m: Any, session_date: date) -> dict[str, Any]:
    """Return 17:00-17:30 CT (= 18:00-18:30 ET) bar rows for the given RTH session date.

    The ETH session opens on the RTH date and continues past midnight; the trigger
    bar timestamp on the CT axis is `session_date 17:00 CT`.
    """
    frame = _to_tz(bars_30m, CT)
    target_date = session_date
    rows = frame[frame.index.date == target_date].between_time("17:00", "17:00")
    if rows.empty:
        raise ValueError("17:00 CT reopen bar unavailable")
    row = rows.iloc[0]
    ts = rows.index[0]
    return {
        "timestamp_ct": ts.isoformat(),
        "timestamp_et": ts.astimezone(ET).isoformat(),
        "open": float(row["Open"]),
        "high": float(row["High"]),
        "low": float(row["Low"]),
        "close": float(row["Close"]),
        "volume": float(row["Volume"]),
    }


def atr_30m(bars_30m: Any, up_to: datetime) -> float | None:
    frame = _to_tz(bars_30m, CT)
    trimmed = frame[frame.index <= up_to]
    if len(trimmed) < ATR_PERIOD + 1:
        return None
    highs = trimmed["High"].astype(float)
    lows = trimmed["Low"].astype(float)
    closes = trimmed["Close"].astype(float)
    prev_close = closes.shift(1)
    true_range = (highs - lows).combine((highs - prev_close).abs(), max).combine(
        (lows - prev_close).abs(), max
    )
    atr = true_range.rolling(ATR_PERIOD).mean().iloc[-1]
    return float(atr) if atr == atr else None


def eth_hurst(bars_1h: Any, up_to: datetime) -> float | None:
    frame = _to_tz(bars_1h, ET)
    filtered = frame[frame.index <= up_to]
    # ETH-only: exclude RTH bars 09:30-16:00 ET
    filtered = filtered.between_time("16:00", "09:30")
    closes = filtered["Close"].astype(float).dropna().tolist()
    if len(closes) < HURST_WINDOW_BARS:
        return None
    return hurst_exponent(closes[-HURST_WINDOW_BARS:])


def build_entry_plan(
    *,
    bars_30m: Any,
    bars_1h: Any,
    bars_5m: Any,
    vix_daily: Any,
    session_date: date,
    macro_context: tuple[bool, list[str]] | None = None,
) -> dict[str, Any]:
    reasons: list[str] = []
    filters: dict[str, Any] = {}

    filters["day_of_week"] = session_date.strftime("%A")
    if session_date.weekday() not in ELIGIBLE_WEEKDAYS:
        reasons.append("day_of_week_not_mon_thu")

    bias = rth_close_bias(bars_5m, session_date)
    filters["rth_bias"] = bias
    if bias["direction"] is None:
        reasons.append("rth_close_bias_mixed")

    trigger = trigger_bar(bars_30m, session_date)
    filters["trigger_bar"] = trigger

    trigger_dt_ct = datetime.fromisoformat(trigger["timestamp_ct"])
    trigger_volume, baseline = eth_volume_baseline(bars_30m, trigger_dt_ct)
    volume_pass = bool(baseline is not None and trigger_volume >= VOLUME_MULTIPLE * baseline)
    filters["eth_volume"] = {
        "trigger_volume": trigger_volume,
        "baseline": baseline,
        "multiple_required": VOLUME_MULTIPLE,
        "pass": volume_pass,
    }
    if not volume_pass:
        reasons.append("eth_volume_below_baseline")

    vix_frame = _flatten(vix_daily).copy()
    vix_frame = vix_frame[vix_frame.index.date <= session_date]
    if vix_frame.empty or "Close" not in vix_frame:
        raise ValueError("VIX close unavailable")
    vix_close = float(vix_frame["Close"].dropna().iloc[-1])
    filters["vix_prior_close"] = vix_close
    filters["vix_source"] = "cboe_vix_history"
    filters["vix_observed_session"] = vix_frame["Close"].dropna().index[-1].date().isoformat()
    if not (VIX_MIN <= vix_close <= VIX_MAX):
        reasons.append(f"vix_out_of_band_{vix_close:.2f}")

    hurst = eth_hurst(bars_1h, trigger_dt_ct.astimezone(ET))
    filters["hurst_1h_eth_100bar"] = hurst
    if hurst is None or hurst < HURST_MIN:
        reasons.append(f"hurst_below_min_{hurst}")

    next_day = session_date + timedelta(days=1)
    macro_blocked, macro_names = macro_context if macro_context is not None else _macro_block_next_day(next_day)
    filters["macro_next_day_blocked"] = macro_blocked
    filters["macro_events_next_day"] = macro_names
    if macro_blocked:
        reasons.append("macro_event_next_day")

    atr = atr_30m(bars_30m, trigger_dt_ct)
    filters["atr_30m_14"] = atr
    if atr is None or atr <= 0:
        reasons.append("atr_unavailable")

    direction = bias["direction"] or "long"
    entry_price = trigger["close"]
    stop_distance = (atr or 0.0) * ATR_STOP_MULT
    if direction == "long":
        stop_price = entry_price - stop_distance
        t1_price = entry_price + stop_distance
        t2_price = entry_price + T2_MULT * stop_distance
    else:
        stop_price = entry_price + stop_distance
        t1_price = entry_price - stop_distance
        t2_price = entry_price - T2_MULT * stop_distance
    max_risk = stop_distance * POINT_VALUE if stop_distance else 0.0

    plan = {
        "direction": direction,
        "entry_price": entry_price,
        "stop_price": stop_price,
        "t1_price": t1_price,
        "t2_price": t2_price,
        "stop_distance_pts": stop_distance,
        "max_risk_per_contract": max_risk,
        "trigger": trigger,
        "actionable_at": (trigger_dt_ct + timedelta(minutes=30)).isoformat(),
        "atr_30m": atr,
    }

    if reasons:
        return {"should_enter": False, "filters": filters, "plan": plan, "reason": ";".join(reasons)}
    return {"should_enter": True, "filters": filters, "plan": plan, "reason": "eligible"}


# ---------------------------------------------------------------------------
# Resolver
# ---------------------------------------------------------------------------

def _bar_hit(low: float, high: float, target: float, direction_up: bool) -> bool:
    return (direction_up and high >= target) or ((not direction_up) and low <= target)


def resolve_plan(bars_30m: Any, plan: Mapping[str, Any]) -> dict[str, Any]:
    frame = _to_tz(bars_30m, ET)
    trigger_ts_ct = datetime.fromisoformat(plan["trigger"]["timestamp_ct"])
    trigger_ts_et = trigger_ts_ct.astimezone(ET)
    session_start = datetime.fromisoformat(str(plan.get("actionable_at") or trigger_ts_ct + timedelta(minutes=30))).astimezone(ET)
    session_end = trigger_ts_et.replace(hour=8, minute=30, second=0, microsecond=0)
    if session_end <= session_start:
        session_end = session_end + timedelta(days=1)

    forward = frame[(frame.index > session_start) & (frame.index <= session_end)]
    if forward.empty:
        raise ValueError("post-trigger ETH bars unavailable")

    direction = plan["direction"]
    is_long = direction == "long"
    entry_price = float(plan["entry_price"])
    stop_price = float(plan["stop_price"])
    t1_price = float(plan["t1_price"])
    t2_price = float(plan["t2_price"])
    stop_distance = float(plan["stop_distance_pts"])
    atr = float(plan.get("atr_30m") or 0.0)

    banked_half_pts = 0.0
    remaining_open = True
    remaining_exit_pts = 0.0
    t1_hit = False
    stop_price_dynamic = stop_price
    exit_reason = "time_stop_08_30_et"
    exit_timestamp = None
    exit_price_observed_proxy: float | None = None
    break_even_moved = False
    early_exit_ready = False

    for timestamp, row in forward.iterrows():
        if not remaining_open:
            break
        low = float(row["Low"])
        high = float(row["High"])

        hit_stop = _bar_hit(low, high, stop_price_dynamic, direction_up=not is_long)
        hit_t1 = (not t1_hit) and _bar_hit(low, high, t1_price, direction_up=is_long)
        hit_t2 = t1_hit and _bar_hit(low, high, t2_price, direction_up=is_long)

        if hit_stop:
            if not t1_hit:
                banked_half_pts = 0.0
                remaining_exit_pts = (stop_price_dynamic - entry_price) if is_long else (entry_price - stop_price_dynamic)
                exit_reason = "stop_before_t1"
                exit_price_observed_proxy = stop_price_dynamic
            else:
                remaining_exit_pts = (stop_price_dynamic - entry_price) if is_long else (entry_price - stop_price_dynamic)
                exit_reason = "trail_stop_after_t1"
                exit_price_observed_proxy = stop_price_dynamic
            remaining_open = False
            exit_timestamp = timestamp
            break

        if hit_t1:
            banked_half_pts = 0.5 * ((t1_price - entry_price) if is_long else (entry_price - t1_price))
            t1_hit = True
            trail = 0.25 * atr
            stop_price_dynamic = (entry_price + trail) if is_long else (entry_price - trail)
            break_even_moved = True
            if hit_t2 and (t2_price >= t1_price if is_long else t2_price <= t1_price):
                remaining_exit_pts = 0.5 * ((t2_price - entry_price) if is_long else (entry_price - t2_price))
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

        elapsed = timestamp - trigger_ts_et
        if not t1_hit and elapsed >= EARLY_EXIT_AFTER:
            unrealized_pts = (float(row["Close"]) - entry_price) if is_long else (entry_price - float(row["Close"]))
            if unrealized_pts <= EARLY_EXIT_R * stop_distance:
                remaining_exit_pts = unrealized_pts
                remaining_open = False
                exit_reason = "four_hour_negative_half_r"
                exit_timestamp = timestamp
                exit_price_observed_proxy = float(row["Close"])
                break

        if not break_even_moved and not t1_hit and elapsed >= BREAK_EVEN_MIN_AFTER:
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
        exit_reason = "time_stop_08_30_et"
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
    session_date = as_of.astimezone(CT).date()
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

    try:
        bars_30m = download_mes_30m()
        bars_1h = download_mes_1h()
        bars_5m = download_mes_5m()
        vix = download_vix_daily()
        decision = build_entry_plan(
            bars_30m=bars_30m,
            bars_1h=bars_1h,
            bars_5m=bars_5m,
            vix_daily=vix,
            session_date=session_date,
        )
        filters = decision["filters"]
        context_observed_at = utc_now_z(as_of)
        filters["macro_source"] = "market_catalyst_calendar"
        filters["macro_observed_at"] = context_observed_at
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
            record["created_at"] = plan["actionable_at"]
            record["entry_price_observed_proxy"] = plan["entry_price"]
            record["stop_price"] = plan["stop_price"]
            record["t1_price"] = plan["t1_price"]
            record["t2_price"] = plan["t2_price"]
            record["max_risk_per_contract"] = plan["max_risk_per_contract"]
            record["quantity"] = QUANTITY
            record["effective_qty"] = QUANTITY
            record["stop_distance_pts"] = plan["stop_distance_pts"]
    except Exception as exc:
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
    session_date = (as_of.astimezone(CT) - timedelta(days=1)).date()
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
        bars_30m = download_mes_30m()
        summary = resolve_plan(bars_30m, plan)
        pnl = summary["net_dollar"]
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
            "exit_reason": summary["exit_reason"],
            "reason": summary["exit_reason"],
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

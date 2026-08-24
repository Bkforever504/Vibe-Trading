#!/usr/bin/env python3
"""Frozen Equity ORB Scout v1 shadow scanner.

Observes the exact `equity-orb-scout-v1` candidate specified in
`research/preregistrations/equity_orb_scout_v1.md`. Scans the frozen
`data/universes/equity_scout_v1_membership_2026-08-23.json` universe once per
RTH session and records the first eligible 15-minute ORB breakout per symbol.

Modes:
  --mode entry    Fired at 10:32 ET (after 09:45-10:30 trigger window closes).
  --mode resolve  Fired at 16:05 ET (after 15:55 ET flat time).

Output ledger: `data/equity_orb_scout_v1_shadow_log.jsonl`. Consumed by
`scripts/shadow_outcome_resolver.py`; plan_id = `<candidate>:<symbol>:<date>`.
Evidence tier is `proxy_ohlcv_non_executable` with `promotion_eligible=false`
until Kenny sign-off swaps to executable NBBO quotes.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import warnings
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from typing import Any, Mapping
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

STRATEGY_ID = "equity-orb-scout-v1"
FAMILY_ID = "equity-orb-scout"
SPEC_HASH = "sha256:61d15241050297f84a3d1bcf0fdc2fa152885268d88cbed2891b61406c99fc27"
SPEC_PATH = "research/preregistrations/equity_orb_scout_v1.md"
UNIVERSE_PATH = ROOT / "data" / "universes" / "equity_scout_v1_membership_2026-08-23.json"
LOG_PATH = ROOT / "data" / "equity_orb_scout_v1_shadow_log.jsonl"

ET = ZoneInfo("America/New_York")

BREAKOUT_BUFFER = 0.001
RVOL_MIN = 1.5
RVOL_LOOKBACK_SESSIONS = 5
OR_START = time(9, 30)
OR_END = time(9, 45)
TRIGGER_START = time(9, 45)
TRIGGER_END = time(10, 30)
TIME_EXIT = time(15, 55)
BREAK_EVEN_R = 0.5
BREAK_EVEN_MIN_AFTER = timedelta(minutes=15)
COMMISSION_PER_SHARE = 0.005
SLIPPAGE_PER_SIDE = 0.01
QUANTITY = 1

TOP_N_DASHBOARD = 20  # highest-grade signals surfaced to dashboard per day


# ---------------------------------------------------------------------------
# Universe
# ---------------------------------------------------------------------------

def load_universe(path: Path = UNIVERSE_PATH) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8-sig"))
    required = ("universe_id", "universe_version", "sha256_membership_hash", "membership_as_of", "symbols")
    for key in required:
        if key not in payload:
            raise ValueError(f"universe_membership_missing_{key}")
    symbols = payload["symbols"]
    if not isinstance(symbols, list) or not symbols:
        raise ValueError("universe_membership_symbols_invalid")
    canonical = "\n".join(sorted(set(str(symbol).upper() for symbol in symbols))) + "\n"
    computed = "sha256:" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    if len(symbols) != len(set(symbols)) or payload.get("symbol_count") != len(symbols):
        raise ValueError("universe_membership_count_or_uniqueness_mismatch")
    if payload["sha256_membership_hash"] != computed:
        raise ValueError("universe_membership_hash_mismatch")
    return payload


# ---------------------------------------------------------------------------
# Data loaders
# ---------------------------------------------------------------------------

def _yfinance_download(symbols: list[str], *, period: str, interval: str) -> Any:
    import yfinance as yf

    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        return yf.download(
            symbols,
            period=period,
            interval=interval,
            auto_adjust=False,
            prepost=False,
            progress=False,
            group_by="ticker",
            threads=True,
        )


def download_bars_5m(symbols: list[str], period: str = "10d") -> Any:
    return _yfinance_download(symbols, period=period, interval="5m")


def download_bars_1m(symbols: list[str], period: str = "5d") -> Any:
    return _yfinance_download(symbols, period=period, interval="1m")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def utc_now_z(instant: datetime | None = None) -> str:
    return (instant or datetime.now(timezone.utc)).astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _to_et(frame: Any) -> Any:
    import pandas as pd

    frame = frame.sort_index()
    if not isinstance(frame.index, pd.DatetimeIndex):
        raise TypeError("market data must use a DatetimeIndex")
    if frame.index.tz is None:
        frame.index = frame.index.tz_localize("America/New_York")
    else:
        frame.index = frame.index.tz_convert("America/New_York")
    return frame


def _symbol_frame(bundle: Any, symbol: str) -> Any:
    if hasattr(bundle, "columns") and hasattr(bundle.columns, "levels"):
        try:
            return bundle[symbol].dropna(how="all")
        except KeyError:
            return None
    return bundle


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


def _base_record(event_type: str, as_of: datetime, universe: Mapping[str, Any]) -> dict[str, Any]:
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
        "universe_id": universe["universe_id"],
        "universe_version": universe["universe_version"],
        "universe_hash": universe["sha256_membership_hash"],
        "membership_as_of": universe["membership_as_of"],
        "data_source": "yfinance_proxy_multi_symbol_1m_5m",
        "evidence_tier": "proxy_ohlcv_non_executable",
        "promotion_eligible": False,
        "evidence_blockers": [
            "executable_nbbo_quotes_required",
            "kenny_signoff_required",
        ],
        "execution_mode": "shadow_only",
        "execution_enabled": False,
        "can_submit_orders": False,
    }


# ---------------------------------------------------------------------------
# Macro veto
# ---------------------------------------------------------------------------

def _macro_veto(day: date) -> tuple[bool, list[str]]:
    try:
        from scripts.market_catalyst_calendar import events_for_date
    except Exception:
        return True, ["macro_calendar_unavailable"]
    events = events_for_date(day) or []
    hits: list[str] = []
    for event in events:
        impact = str(event.get("impact", "")).lower()
        if impact != "high":
            continue
        event_time = str(event.get("time_et", ""))
        try:
            hour, minute = event_time.split(":")
            release = time(int(hour), int(minute))
        except (ValueError, AttributeError):
            release = time(12, 0)
        if time(9, 30) <= release <= time(15, 30):
            hits.append(str(event.get("name", "")))
    return bool(hits), hits


# ---------------------------------------------------------------------------
# Per-symbol setup detection
# ---------------------------------------------------------------------------

def _session_slice(frame: Any, session_date: date, start: str, end: str) -> Any:
    frame = _to_et(frame)
    day_rows = frame[frame.index.date == session_date]
    return day_rows.between_time(start, end)


def _opening_range(bars_1m: Any, session_date: date) -> tuple[float, float] | None:
    rows = _session_slice(bars_1m, session_date, "09:30", "09:44")
    expected = {time(9, 30 + minute) for minute in range(15)}
    observed = {stamp.time().replace(tzinfo=None) for stamp in rows.index}
    if rows.empty or "High" not in rows or "Low" not in rows or observed != expected:
        return None
    return float(rows["High"].max()), float(rows["Low"].min())


def _rvol_baseline(bars_5m: Any, session_date: date, bar_start: time) -> float | None:
    frame = _to_et(bars_5m)
    prior_dates = sorted({d for d in frame.index.date if d < session_date})
    prior_dates = prior_dates[-RVOL_LOOKBACK_SESSIONS:]
    if len(prior_dates) != RVOL_LOOKBACK_SESSIONS:
        return None
    start_str = bar_start.strftime("%H:%M")
    end_str = bar_start.strftime("%H:%M")
    volumes: list[float] = []
    for prior in prior_dates:
        window = frame[frame.index.date == prior].between_time(start_str, end_str)
        if window.empty:
            continue
        volumes.append(float(window["Volume"].iloc[0]))
    if len(volumes) != RVOL_LOOKBACK_SESSIONS:
        return None
    return sum(volumes) / len(volumes)


def _session_vwap_at(bars_1m: Any, session_date: date, up_to: datetime) -> float | None:
    rth = _session_slice(bars_1m, session_date, "09:30", "16:00")
    rth = rth[rth.index <= up_to]
    if rth.empty:
        return None
    typical = (rth["High"] + rth["Low"] + rth["Close"]) / 3.0
    vol = rth["Volume"].astype(float)
    denom = vol.sum()
    if denom <= 0:
        return None
    return float((typical * vol).sum() / denom)


def build_symbol_plan(
    symbol: str,
    bars_1m_bundle: Any,
    bars_5m_bundle: Any,
    session_date: date,
) -> dict[str, Any]:
    reasons: list[str] = []
    bars_1m = _symbol_frame(bars_1m_bundle, symbol)
    bars_5m = _symbol_frame(bars_5m_bundle, symbol)
    if bars_1m is None or bars_5m is None or bars_1m.empty or bars_5m.empty:
        return {"symbol": symbol, "should_enter": False, "reason": "no_data"}

    opening = _opening_range(bars_1m, session_date)
    if opening is None:
        return {"symbol": symbol, "should_enter": False, "reason": "opening_range_unavailable"}
    or_high, or_low = opening
    or_width = or_high - or_low
    if or_width <= 0:
        return {"symbol": symbol, "should_enter": False, "reason": "opening_range_zero_width"}

    triggers = _session_slice(bars_5m, session_date, "09:45", "10:29")
    trigger: dict[str, Any] | None = None
    for timestamp, row in triggers.iterrows():
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
        # The 5-minute trigger is only actionable after its 09:xx–09:xx+4
        # constituent minutes have completed; include all of them in VWAP.
        vwap = _session_vwap_at(bars_1m, session_date, timestamp + timedelta(minutes=4))
        vwap_pass = bool(
            vwap is not None
            and ((direction == "long" and close > vwap) or (direction == "short" and close < vwap))
        )
        baseline = _rvol_baseline(bars_5m, session_date, bar_time)
        rvol = (volume / baseline) if baseline and baseline > 0 else None
        rvol_pass = bool(rvol is not None and rvol >= RVOL_MIN)
        trigger = {
            "bar_open_et": bar_time.strftime("%H:%M"),
            "trigger_timestamp": timestamp.isoformat(),
            "close": close,
            "volume": volume,
            "direction": direction,
            "rvol": rvol,
            "rvol_baseline": baseline,
            "rvol_pass": rvol_pass,
            "vwap": vwap,
            "vwap_pass": vwap_pass,
        }
        if not rvol_pass:
            reasons.append("rvol_below_1_5")
        if not vwap_pass:
            reasons.append("vwap_misaligned")
        break

    if trigger is None:
        return {"symbol": symbol, "should_enter": False, "reason": "no_qualifying_trigger", "opening_range": {"high": or_high, "low": or_low, "width": or_width}}

    direction = trigger["direction"]
    entry_price = float(trigger["close"])
    if direction == "long":
        stop_price = or_low - 0.01
        t1_price = entry_price + or_width
        t2_price = entry_price + 2.0 * or_width
    else:
        stop_price = or_high + 0.01
        t1_price = entry_price - or_width
        t2_price = entry_price - 2.0 * or_width
    stop_distance = abs(entry_price - stop_price)
    max_risk = stop_distance  # dollars per share

    grade_components = {
        "rvol": trigger["rvol"] or 0.0,
        "displacement_pct": abs(entry_price - (or_high if direction == "long" else or_low)) / entry_price if entry_price else 0.0,
        "vwap_pass": 1.0 if trigger["vwap_pass"] else 0.0,
    }
    grade = round(
        (min(grade_components["rvol"], 5.0) / 5.0) * 0.4
        + min(grade_components["displacement_pct"] * 200.0, 1.0) * 0.4
        + grade_components["vwap_pass"] * 0.2,
        4,
    )

    plan = {
        "direction": direction,
        "entry_price": entry_price,
        "stop_price": stop_price,
        "t1_price": t1_price,
        "t2_price": t2_price,
        "stop_distance_pts": stop_distance,
        "max_risk_per_contract": max_risk,
        "opening_range": {"high": or_high, "low": or_low, "width": or_width},
        "trigger": trigger,
        "grade": grade,
        "grade_components": grade_components,
    }

    return {
        "symbol": symbol,
        "should_enter": not reasons,
        "reason": ";".join(reasons) or "eligible",
        "plan": plan,
    }


# ---------------------------------------------------------------------------
# Resolver
# ---------------------------------------------------------------------------

def _bar_hit(low: float, high: float, target: float, direction_up: bool) -> bool:
    return (direction_up and high >= target) or ((not direction_up) and low <= target)


def resolve_symbol(bars_1m_bundle: Any, symbol: str, session_date: date, plan: Mapping[str, Any]) -> dict[str, Any]:
    bars_1m = _symbol_frame(bars_1m_bundle, symbol)
    if bars_1m is None or bars_1m.empty:
        raise ValueError("no_intraday_data_for_resolution")
    frame = _session_slice(bars_1m, session_date, "09:30", "15:55")
    trigger_ts = plan["trigger"]["trigger_timestamp"]
    forward = frame[frame.index > trigger_ts]
    if forward.empty:
        raise ValueError("no_post_trigger_bars")

    direction = plan["direction"]
    is_long = direction == "long"
    entry_price = float(plan["entry_price"])
    stop_price = float(plan["stop_price"])
    t1_price = float(plan["t1_price"])
    t2_price = float(plan["t2_price"])
    stop_distance = float(plan["stop_distance_pts"])
    trigger_dt = datetime.fromisoformat(trigger_ts)

    banked_half_pts = 0.0
    remaining_open = True
    remaining_exit_pts = 0.0
    t1_hit = False
    stop_price_dynamic = stop_price
    exit_reason = "time_stop_15_55_et"
    exit_timestamp = None
    break_even_moved = False

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
            else:
                remaining_exit_pts = (stop_price_dynamic - entry_price) if is_long else (entry_price - stop_price_dynamic)
                exit_reason = "trail_stop_after_t1"
            remaining_open = False
            exit_timestamp = timestamp
            break

        if hit_t1:
            banked_half_pts = 0.5 * ((t1_price - entry_price) if is_long else (entry_price - t1_price))
            t1_hit = True
            stop_price_dynamic = (entry_price + 0.01) if is_long else (entry_price - 0.01)
            break_even_moved = True
            if hit_t2:
                remaining_exit_pts = 0.5 * ((t2_price - entry_price) if is_long else (entry_price - t2_price))
                remaining_open = False
                exit_reason = "t2_after_t1"
                exit_timestamp = timestamp
                break
            continue

        if hit_t2:
            remaining_exit_pts = 0.5 * ((t2_price - entry_price) if is_long else (entry_price - t2_price))
            remaining_open = False
            exit_reason = "t2_after_t1"
            exit_timestamp = timestamp
            break

        minutes_since = (timestamp - trigger_dt).total_seconds() / 60.0
        if not break_even_moved and not t1_hit and minutes_since >= BREAK_EVEN_MIN_AFTER.total_seconds() / 60.0:
            unrealized = (high - entry_price) if is_long else (entry_price - low)
            if unrealized >= BREAK_EVEN_R * stop_distance:
                stop_price_dynamic = entry_price
                break_even_moved = True

    if remaining_open:
        final_row = forward.iloc[-1]
        exit_price = float(final_row["Close"])
        remaining_exit_pts = (exit_price - entry_price) if is_long else (entry_price - exit_price)
        if t1_hit:
            remaining_exit_pts *= 0.5
        exit_reason = "time_stop_15_55_et"
        exit_timestamp = forward.index[-1]

    total_pts = banked_half_pts + remaining_exit_pts
    friction = 2 * SLIPPAGE_PER_SIDE + 2 * COMMISSION_PER_SHARE
    gross = total_pts * QUANTITY
    net = gross - friction * QUANTITY
    outcome = "win" if net > 0 else ("loss" if net < 0 else "flat")

    return {
        "exit_reason": exit_reason,
        "exit_timestamp": exit_timestamp.isoformat() if exit_timestamp is not None else None,
        "t1_hit": t1_hit,
        "banked_half_pts": round(banked_half_pts, 4),
        "remaining_exit_pts": round(remaining_exit_pts, 4),
        "total_pts": round(total_pts, 4),
        "gross_dollar": round(gross, 4),
        "friction_round_trip_dollar": round(friction, 4),
        "net_dollar": round(net, 4),
        "outcome": outcome,
    }


# ---------------------------------------------------------------------------
# Entrypoints
# ---------------------------------------------------------------------------

def _plan_id(symbol: str, session_date: date) -> str:
    return f"{STRATEGY_ID}:{symbol}:{session_date.isoformat()}"


def _unsettled_entries_for_date(path: Path, session_date: date) -> list[dict[str, Any]]:
    matching = []
    for row in _records(path):
        if row.get("event_type") != "entry":
            continue
        if row.get("session_date") != session_date.isoformat():
            continue
        if row.get("settled"):
            continue
        matching.append(row)
    return matching


def run_entry(*, as_of: datetime | None = None, log_path: Path = LOG_PATH) -> int:
    as_of = as_of or datetime.now(ET)
    session_date = as_of.astimezone(ET).date()
    universe = load_universe()
    macro_veto, macro_names = _macro_veto(session_date)

    if macro_veto:
        record = _base_record("universe_skip", as_of, universe) | {
            "session_date": session_date.isoformat(),
            "reason": "macro_high_impact_veto",
            "macro_events": macro_names,
        }
        _append_record(record, log_path)
        print(json.dumps(record, separators=(",", ":"), sort_keys=True))
        return 0

    symbols = list(universe["symbols"])
    try:
        bars_1m = download_bars_1m(symbols)
        bars_5m = download_bars_5m(symbols)
    except Exception as exc:
        record = _base_record("universe_error", as_of, universe) | {
            "session_date": session_date.isoformat(),
            "reason": "market_data_incomplete",
            "error": str(exc)[:240],
        }
        _append_record(record, log_path)
        print(json.dumps(record, separators=(",", ":"), sort_keys=True))
        return 0

    setups: list[dict[str, Any]] = []
    existing = {row.get("plan_id") for row in _records(log_path) if row.get("event_type") == "entry"}

    for symbol in symbols:
        plan_id = _plan_id(symbol, session_date)
        if plan_id in existing:
            continue
        try:
            decision = build_symbol_plan(symbol, bars_1m, bars_5m, session_date)
        except Exception as exc:
            decision = {"symbol": symbol, "should_enter": False, "reason": f"error:{str(exc)[:120]}"}
        setups.append(decision)

    setups_eligible = [s for s in setups if s.get("should_enter") and s.get("plan")]
    setups_eligible.sort(key=lambda s: s["plan"]["grade"], reverse=True)

    for rank, setup in enumerate(setups, start=1):
        symbol = setup["symbol"]
        plan_id = _plan_id(symbol, session_date)
        plan = setup.get("plan")
        record = _base_record("entry", as_of, universe) | {
            "plan_id": plan_id,
            "trade_key": plan_id,
            "symbol": symbol,
            "session_date": session_date.isoformat(),
            "should_enter": bool(setup.get("should_enter")),
            "reason": setup.get("reason", "unknown"),
            "settled": not setup.get("should_enter"),
        }
        if plan:
            record["plan"] = plan
            record["direction"] = plan["direction"]
            record["entry_price"] = plan["entry_price"]
            record["entry_price_observed_proxy"] = plan["entry_price"]
            record["stop_price"] = plan["stop_price"]
            record["t1_price"] = plan["t1_price"]
            record["t2_price"] = plan["t2_price"]
            record["max_risk_per_contract"] = plan["max_risk_per_contract"]
            record["quantity"] = QUANTITY
            record["effective_qty"] = QUANTITY
            record["stop_distance_pts"] = plan["stop_distance_pts"]
            record["grade"] = plan["grade"]
            top_symbols = [s["symbol"] for s in setups_eligible[:TOP_N_DASHBOARD]]
            record["dashboard_rank_in_top_n"] = (top_symbols.index(symbol) + 1) if symbol in top_symbols else None
        _append_record(record, log_path)

    summary = {
        "event_type": "universe_summary",
        "session_date": session_date.isoformat(),
        "scanned": len(symbols),
        "setups_total": len(setups),
        "setups_eligible": len(setups_eligible),
        "top_symbols": [
            {"symbol": s["symbol"], "grade": s["plan"]["grade"], "direction": s["plan"]["direction"]}
            for s in setups_eligible[:TOP_N_DASHBOARD]
        ],
        "execution_enabled": False,
        "can_submit_orders": False,
    }
    print(json.dumps(summary, separators=(",", ":"), sort_keys=True))
    return 0


def run_resolve(*, as_of: datetime | None = None, log_path: Path = LOG_PATH) -> int:
    as_of = as_of or datetime.now(ET)
    session_date = as_of.astimezone(ET).date()
    universe = load_universe()
    open_entries = _unsettled_entries_for_date(log_path, session_date)
    if not open_entries:
        record = _base_record("resolve_noop", as_of, universe) | {
            "session_date": session_date.isoformat(),
            "reason": "no_unsettled_entries_for_session",
        }
        _append_record(record, log_path)
        print(json.dumps(record, separators=(",", ":"), sort_keys=True))
        return 0

    symbols_open = [entry["symbol"] for entry in open_entries if entry.get("symbol")]
    try:
        bars_1m = download_bars_1m(sorted(set(symbols_open)))
    except Exception as exc:
        record = _base_record("resolve_error", as_of, universe) | {
            "session_date": session_date.isoformat(),
            "reason": "market_data_incomplete",
            "error": str(exc)[:240],
        }
        _append_record(record, log_path)
        print(json.dumps(record, separators=(",", ":"), sort_keys=True))
        return 0

    rows = _records(log_path)
    resolved_symbols: list[str] = []
    for entry in open_entries:
        symbol = entry.get("symbol")
        plan = entry.get("plan") or {}
        plan_id = entry.get("plan_id")
        if not symbol or not plan_id or not plan:
            terminal = _base_record("exit", as_of, universe) | {
                "plan_id": plan_id,
                "trade_key": plan_id,
                "symbol": symbol,
                "session_date": session_date.isoformat(),
                "resolved_at": utc_now_z(as_of),
                "reason": "no_actionable_plan",
                "settled": True,
            }
            rows.append(terminal)
            continue
        try:
            summary = resolve_symbol(bars_1m, symbol, session_date, plan)
            pnl = summary["net_dollar"]
            max_risk = float(entry.get("max_risk_per_contract") or 0.0)
            outcome_r = (pnl / max_risk) if max_risk else None
            terminal = _base_record("exit", as_of, universe) | {
                "plan_id": plan_id,
                "trade_key": plan_id,
                "symbol": symbol,
                "session_date": session_date.isoformat(),
                "resolved_at": utc_now_z(as_of),
                "entry_price": entry.get("entry_price"),
                "entry_fill_executable": entry.get("entry_fill_executable"),
                "stop_price": entry.get("stop_price"),
                "t1_price": entry.get("t1_price"),
                "t2_price": entry.get("t2_price"),
                "exit_reason": summary["exit_reason"],
                "reason": summary["exit_reason"],
                "exit_timestamp": summary["exit_timestamp"],
                "exit_fill_executable": None,
                "exit_price": None,
                "exit_bid": None,
                "outcome": summary["outcome"],
                "outcome_r": outcome_r,
                "gross_dollar": summary["gross_dollar"],
                "friction_round_trip_dollar": summary["friction_round_trip_dollar"],
                "net_dollar": summary["net_dollar"],
                "pnl_before_fees": summary["gross_dollar"],
                "quantity": QUANTITY,
                "detail": summary,
                "settled": True,
            }
        except Exception as exc:
            terminal = _base_record("exit", as_of, universe) | {
                "plan_id": plan_id,
                "trade_key": plan_id,
                "symbol": symbol,
                "session_date": session_date.isoformat(),
                "resolved_at": utc_now_z(as_of),
                "reason": "market_data_incomplete",
                "error": str(exc)[:240],
                "settled": True,
            }
        for row in rows:
            if row.get("event_type") == "entry" and row.get("plan_id") == plan_id:
                row["settled"] = True
        rows.append(terminal)
        resolved_symbols.append(symbol)

    _replace_records(rows, log_path)
    summary = {
        "event_type": "resolve_summary",
        "session_date": session_date.isoformat(),
        "resolved": len(resolved_symbols),
        "symbols": resolved_symbols,
        "execution_enabled": False,
        "can_submit_orders": False,
    }
    print(json.dumps(summary, separators=(",", ":"), sort_keys=True))
    return 0


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

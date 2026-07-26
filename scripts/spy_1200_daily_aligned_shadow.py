#!/usr/bin/env python3
"""Forward-only SPY 12:00 daily-aligned shadow evidence lane.

Reads Alpaca market data and appends point-in-time evidence. It imports no
trading client and cannot submit, replace, or cancel orders.
"""
from __future__ import annotations

import argparse
import json
import math
import re
import sys
from datetime import date, datetime, time, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from research.green_day_htf_ltf_lab import asof_states, build_htf_table, ltf_signal
from scripts.point_in_time_quotes import (
    capture_lifecycle_sample,
    fetch_alpaca_underlying_price,
)

NY = ZoneInfo("America/New_York")
LANE = "spy_1200_daily_aligned_v1"
LOG_PATH = ROOT / "data" / "spy_1200_daily_aligned_forward_log.jsonl"
REPORT_PATH = Path.home() / ".vibe-trading" / "reports" / "spy-1200-daily-aligned-shadow.json"
QUOTE_PATH = Path.home() / ".vibe-trading" / "logs" / "spy-1200-daily-aligned-option-quotes.jsonl"
DATA_BASE = "https://data.alpaca.markets"
CHECKPOINT = time(12, 0)
SIGNAL_WINDOW = (time(11, 58), time(12, 10))
RESOLVE_WINDOW = (time(12, 58), time(13, 15))
ROUND_TRIP_BPS = 2.0
MIN_ABS_DELTA = 0.35
MAX_ABS_DELTA = 0.65
MAX_SPREAD_PCT = 20.0
MIN_DTE = 0
MAX_DTE = 2
MIN_REVIEW_DATES = 30
OPTION_QUOTE_SCOPE = "indicative_modified_not_opra_nbbo"
_OCC = re.compile(r"^(?P<underlying>[A-Z]+)(?P<date>\d{6})(?P<right>[CP])(?P<strike>\d{8})$")


def _now() -> datetime:
    return datetime.now(NY)


def _iso(value: datetime | pd.Timestamp) -> str:
    return value.isoformat()


def _headers() -> dict[str, str]:
    import scripts.market_data as market_data

    market_data._load_env()  # noqa: SLF001
    return {
        "APCA-API-KEY-ID": market_data._ALPACA_KEY or "",  # noqa: SLF001
        "APCA-API-SECRET-KEY": market_data._ALPACA_SECRET or "",  # noqa: SLF001
    }


def _within_window(now_et: datetime, window: tuple[time, time]) -> bool:
    return window[0] <= now_et.time().replace(tzinfo=None) <= window[1]


def _normalize_intraday(frame: pd.DataFrame) -> pd.DataFrame:
    work = frame.copy()
    work.columns = [str(column).lower() for column in work.columns]
    work.index = pd.to_datetime(work.index)
    if work.index.tz is None:
        work.index = work.index.tz_localize(NY)
    else:
        work.index = work.index.tz_convert(NY)
    if work.index.has_duplicates:
        work = work[~work.index.duplicated(keep="last")]
    return work.sort_index()


def complete_precheckpoint(frame: pd.DataFrame, trading_day: date) -> bool:
    expected = pd.date_range(
        f"{trading_day} 09:30",
        f"{trading_day} 11:59",
        freq="1min",
        tz=NY,
    )
    history = frame[
        (frame.index.date == trading_day)
        & (frame.index.time >= time(9, 30))
        & (frame.index.time < CHECKPOINT)
    ]
    return history.index.equals(expected)


def evaluate_frozen_signal(
    intraday: pd.DataFrame,
    daily_states: dict[str, str],
    trading_day: date,
) -> dict[str, Any] | None:
    frame = _normalize_intraday(intraday)
    if not complete_precheckpoint(frame, trading_day):
        return None
    checkpoint = pd.Timestamp.combine(trading_day, CHECKPOINT).tz_localize(NY)
    history = frame[frame.index < checkpoint]
    signal = ltf_signal(history)
    if signal is None:
        return None
    expected = "bullish" if signal["direction"] == "bull" else "bearish"
    if daily_states.get("daily") != expected:
        return None
    return {
        "symbol": "SPY",
        "lane": LANE,
        "checkpoint_et": "12:00",
        "direction": signal["direction"],
        "right": "CALL" if signal["direction"] == "bull" else "PUT",
        "daily_state": daily_states["daily"],
        "weekly_state": daily_states.get("weekly", "unavailable"),
        "monthly_state": daily_states.get("monthly", "unavailable"),
        "signal": signal,
        "bar_count": len(history),
        "signal_rule": "production_parity_vwap_ema50_9_of_9_daily_aligned",
    }


def fetch_intraday(trading_day: date, now_et: datetime, headers: dict[str, str]) -> pd.DataFrame:
    import requests

    start = datetime.combine(trading_day, time(9, 30), tzinfo=NY)
    response = requests.get(
        f"{DATA_BASE}/v2/stocks/SPY/bars",
        headers=headers,
        params={
            "timeframe": "1Min",
            "start": start.isoformat(),
            "end": now_et.isoformat(),
            "feed": "iex",
            "adjustment": "all",
            "limit": 1000,
            "sort": "asc",
        },
        timeout=20,
    )
    response.raise_for_status()
    rows = (response.json() or {}).get("bars") or []
    if not rows:
        return pd.DataFrame(columns=["open", "high", "low", "close", "volume"])
    frame = pd.DataFrame(
        {
            "open": [row.get("o") for row in rows],
            "high": [row.get("h") for row in rows],
            "low": [row.get("l") for row in rows],
            "close": [row.get("c") for row in rows],
            "volume": [row.get("v") for row in rows],
        },
        index=pd.to_datetime([row.get("t") for row in rows], utc=True),
    )
    return _normalize_intraday(frame)


def fetch_daily_states(trading_day: date) -> dict[str, str]:
    import scripts.market_data as market_data

    daily = market_data.fetch_ohlcv("SPY", lookback_days=900)
    daily = daily.copy()
    daily.columns = [str(column).lower() for column in daily.columns]
    daily.index = pd.to_datetime(daily.index).tz_localize(None).normalize()
    return asof_states(build_htf_table(daily), trading_day)


def parse_occ(symbol: str) -> dict[str, Any] | None:
    match = _OCC.fullmatch(str(symbol).upper())
    if not match:
        return None
    values = match.groupdict()
    try:
        expiry = datetime.strptime(values["date"], "%y%m%d").date()
    except ValueError:
        return None
    return {
        "underlying": values["underlying"],
        "expiry": expiry,
        "right": "CALL" if values["right"] == "C" else "PUT",
        "strike": int(values["strike"]) / 1000.0,
    }


def select_tracking_contract(
    candidates: list[dict[str, Any]],
    *,
    direction: str,
    spot: float,
    trading_day: date,
) -> dict[str, Any] | None:
    wanted = "CALL" if direction == "bull" else "PUT"
    eligible: list[tuple[tuple[Any, ...], dict[str, Any]]] = []
    for candidate in candidates:
        parsed = parse_occ(str(candidate.get("option_symbol") or ""))
        if parsed is None or parsed["underlying"] != "SPY" or parsed["right"] != wanted:
            continue
        dte = (parsed["expiry"] - trading_day).days
        delta = candidate.get("delta")
        bid = float(candidate.get("bid") or 0.0)
        ask = float(candidate.get("ask") or 0.0)
        if delta is None or not MIN_ABS_DELTA <= abs(float(delta)) <= MAX_ABS_DELTA:
            continue
        if not MIN_DTE <= dte <= MAX_DTE or bid <= 0 or ask < bid:
            continue
        midpoint = (bid + ask) / 2.0
        spread_pct = (ask - bid) / midpoint * 100.0 if midpoint > 0 else math.inf
        if spread_pct > MAX_SPREAD_PCT:
            continue
        row = {
            **candidate,
            "expiry": parsed["expiry"].isoformat(),
            "dte": dte,
            "right": wanted,
            "strike": parsed["strike"],
            "spread_pct": round(spread_pct, 4),
            "quote_scope": OPTION_QUOTE_SCOPE,
            "selection_rule": "earliest_expiry_delta50_atm_spread",
        }
        key = (
            dte,
            abs(abs(float(delta)) - 0.50),
            abs(parsed["strike"] - spot),
            spread_pct,
            str(candidate["option_symbol"]),
        )
        eligible.append((key, row))
    return min(eligible, key=lambda item: item[0])[1] if eligible else None


def fetch_contract_candidates(direction: str) -> list[dict[str, Any]]:
    from scripts.liquid_options_edge_shadow import fetch_contract_candidates as fetch

    mapped = "long" if direction == "bull" else "short"
    return fetch("SPY", mapped, min_dte=MIN_DTE, max_dte=MAX_DTE)


def _read_log(path: Path = LOG_PATH) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            value = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            rows.append(value)
    return rows


def _append(record: dict[str, Any], path: Path = LOG_PATH) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, sort_keys=True, allow_nan=False) + "\n")


def _signal_id(trading_day: date, direction: str) -> str:
    return f"{LANE}:{trading_day}:{direction}"


def _existing_signal(rows: list[dict[str, Any]], trading_day: date) -> dict[str, Any] | None:
    matches = [
        row
        for row in rows
        if row.get("event") == "signal"
        and row.get("trading_date") == trading_day.isoformat()
        and row.get("lane") == LANE
    ]
    return matches[-1] if matches else None


def _existing_outcome(rows: list[dict[str, Any]], signal_id: str) -> dict[str, Any] | None:
    matches = [
        row
        for row in rows
        if row.get("event") == "outcome" and row.get("signal_id") == signal_id
    ]
    return matches[-1] if matches else None


def _blocked(stage: str, exc: Exception, rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Return an observable fail-closed state without leaking credentials."""
    return {
        "status": f"blocked_{stage}_error",
        "error_type": type(exc).__name__,
        "summary": summarize(rows),
    }


def build_outcome(
    signal: dict[str, Any],
    *,
    exit_underlying: dict[str, Any],
    exit_option_record: dict[str, Any] | None,
    resolved_at: datetime,
) -> dict[str, Any] | None:
    entry_price = float((signal.get("underlying_entry") or {}).get("price") or 0.0)
    exit_price = float(exit_underlying.get("price") or 0.0)
    if entry_price <= 0 or exit_price <= 0:
        return None
    direction = str((signal.get("signal") or {}).get("direction"))
    side = 1.0 if direction == "bull" else -1.0
    gross_bps = (exit_price / entry_price - 1.0) * 10_000.0 * side
    contract = signal.get("selected_contract") or {}
    entry_ask = float(contract.get("ask") or 0.0)
    exit_bid = float(
        (((exit_option_record or {}).get("quote") or {}).get("bid")) or 0.0
    )
    option_return = (
        (exit_bid / entry_ask - 1.0) * 100.0
        if entry_ask > 0 and exit_bid > 0
        else None
    )
    return {
        "schema_version": 1,
        "event": "outcome",
        "lane": LANE,
        "signal_id": signal["signal_id"],
        "trading_date": signal["trading_date"],
        "resolved_at": _iso(resolved_at),
        "direction": direction,
        "underlying_entry": signal["underlying_entry"],
        "underlying_exit": exit_underlying,
        "underlying_gross_bps": round(gross_bps, 4),
        "underlying_net_bps": round(gross_bps - ROUND_TRIP_BPS, 4),
        "selected_contract": contract or None,
        "option_entry_ask": entry_ask if entry_ask > 0 else None,
        "option_exit_bid": exit_bid if exit_bid > 0 else None,
        "option_ask_to_bid_return_pct": round(option_return, 4) if option_return is not None else None,
        "option_quote_scope": OPTION_QUOTE_SCOPE,
        "option_outcome_status": "complete" if option_return is not None else "incomplete_quote",
        "execution_enabled": False,
        "can_submit_orders": False,
    }


def moving_block_mean_ci(
    values: np.ndarray,
    *,
    block_size: int = 5,
    replications: int = 2000,
    seed: int = 1200,
) -> dict[str, Any]:
    """Deterministic moving-block bootstrap interval for serially related dates."""
    clean = np.asarray(values, dtype=float)
    clean = clean[np.isfinite(clean)]
    if len(clean) < 20 or len(clean) < block_size:
        return {
            "status": "insufficient_n",
            "block_size": block_size,
            "replications": replications,
            "lower": None,
            "upper": None,
        }
    blocks = [clean[start : start + block_size] for start in range(len(clean) - block_size + 1)]
    draws_per_replication = math.ceil(len(clean) / block_size)
    rng = np.random.default_rng(seed)
    means = np.empty(replications, dtype=float)
    for index in range(replications):
        selected = rng.integers(0, len(blocks), size=draws_per_replication)
        sample = np.concatenate([blocks[position] for position in selected])[: len(clean)]
        means[index] = float(sample.mean())
    lower, upper = np.quantile(means, [0.025, 0.975])
    return {
        "status": "ok",
        "block_size": block_size,
        "replications": replications,
        "lower": round(float(lower), 4),
        "upper": round(float(upper), 4),
    }


def _frozen_rule_drift(signals: list[dict[str, Any]], outcomes: list[dict[str, Any]]) -> list[str]:
    reasons: list[str] = []
    date_counts: dict[str, int] = {}
    for record in signals:
        trading_date = str(record.get("trading_date") or "")
        date_counts[trading_date] = date_counts.get(trading_date, 0) + 1
        frozen = record.get("signal") or {}
        if frozen.get("checkpoint_et") != "12:00":
            reasons.append(f"{trading_date}:checkpoint")
        if frozen.get("bar_count") != 150:
            reasons.append(f"{trading_date}:bar_count")
        if frozen.get("signal_rule") != "production_parity_vwap_ema50_9_of_9_daily_aligned":
            reasons.append(f"{trading_date}:signal_rule")
        try:
            captured = pd.Timestamp(record["captured_at"]).tz_convert(NY).to_pydatetime()
            if not _within_window(captured, SIGNAL_WINDOW):
                reasons.append(f"{trading_date}:signal_time")
        except (KeyError, TypeError, ValueError):
            reasons.append(f"{trading_date}:signal_time_missing")
        if record.get("option_quote_scope") != OPTION_QUOTE_SCOPE:
            reasons.append(f"{trading_date}:quote_scope")
    for trading_date, count in date_counts.items():
        if count > 1:
            reasons.append(f"{trading_date}:duplicate_signals")

    outcome_counts: dict[str, int] = {}
    for record in outcomes:
        signal_id = str(record.get("signal_id") or "")
        outcome_counts[signal_id] = outcome_counts.get(signal_id, 0) + 1
        try:
            resolved = pd.Timestamp(record["resolved_at"]).tz_convert(NY).to_pydatetime()
            if not _within_window(resolved, RESOLVE_WINDOW):
                reasons.append(f"{signal_id}:resolve_time")
        except (KeyError, TypeError, ValueError):
            reasons.append(f"{signal_id}:resolve_time_missing")
        if record.get("option_quote_scope") != OPTION_QUOTE_SCOPE:
            reasons.append(f"{signal_id}:outcome_quote_scope")
    for signal_id, count in outcome_counts.items():
        if count > 1:
            reasons.append(f"{signal_id}:duplicate_outcomes")
    return sorted(set(reasons))


def summarize(rows: list[dict[str, Any]]) -> dict[str, Any]:
    signals = sorted(
        [row for row in rows if row.get("event") == "signal" and row.get("lane") == LANE],
        key=lambda row: str(row.get("trading_date") or ""),
    )
    outcomes = sorted(
        [row for row in rows if row.get("event") == "outcome" and row.get("lane") == LANE],
        key=lambda row: str(row.get("trading_date") or ""),
    )
    underlying = np.asarray(
        [float(row["underlying_net_bps"]) for row in outcomes if row.get("underlying_net_bps") is not None],
        dtype=float,
    )
    option = np.asarray(
        [
            float(row["option_ask_to_bid_return_pct"])
            for row in outcomes
            if row.get("option_ask_to_bid_return_pct") is not None
        ],
        dtype=float,
    )

    def _stats(values: np.ndarray) -> dict[str, Any]:
        if not len(values):
            return {"count": 0, "win_rate": None, "expectancy": None, "top_1pct_removed_expectancy": None}
        remove = max(1, math.ceil(len(values) * 0.01))
        trimmed = np.sort(values)[:-remove] if len(values) > remove else np.asarray([])
        return {
            "count": int(len(values)),
            "win_rate": round(float((values > 0).mean()), 4),
            "expectancy": round(float(values.mean()), 4),
            "top_1pct_removed_expectancy": round(float(trimmed.mean()), 4) if len(trimmed) else None,
            "five_date_moving_block_interval": moving_block_mean_ci(values),
        }

    signals_by_id = {str(row.get("signal_id")): row for row in signals}
    by_direction = {
        direction: _stats(
            np.asarray(
                [
                    float(row["underlying_net_bps"])
                    for row in outcomes
                    if row.get("direction") == direction and row.get("underlying_net_bps") is not None
                ],
                dtype=float,
            )
        )
        for direction in ("bull", "bear")
    }
    context_values: dict[str, list[float]] = {}
    for outcome in outcomes:
        if outcome.get("underlying_net_bps") is None:
            continue
        source = signals_by_id.get(str(outcome.get("signal_id"))) or {}
        frozen = source.get("signal") or {}
        key = f"weekly={frozen.get('weekly_state', 'unavailable')}|monthly={frozen.get('monthly_state', 'unavailable')}"
        context_values.setdefault(key, []).append(float(outcome["underlying_net_bps"]))
    by_htf_context = {
        key: _stats(np.asarray(values, dtype=float))
        for key, values in sorted(context_values.items())
    }
    spreads = np.asarray(
        [
            float((row.get("selected_contract") or {}).get("spread_pct"))
            for row in signals
            if (row.get("selected_contract") or {}).get("spread_pct") is not None
        ],
        dtype=float,
    )
    spread_distribution = {
        "count": int(len(spreads)),
        "median_pct": round(float(np.median(spreads)), 4) if len(spreads) else None,
        "p90_pct": round(float(np.quantile(spreads, 0.90)), 4) if len(spreads) else None,
        "max_pct": round(float(spreads.max()), 4) if len(spreads) else None,
    }
    drift_reasons = _frozen_rule_drift(signals, outcomes)
    resolved_dates = {row["trading_date"] for row in outcomes if row.get("underlying_net_bps") is not None}
    return {
        "lane": LANE,
        "signal_dates": len({row["trading_date"] for row in signals}),
        "resolved_independent_dates": len(resolved_dates),
        "review_target_dates": MIN_REVIEW_DATES,
        "ready_for_human_review": len(resolved_dates) >= MIN_REVIEW_DATES,
        "promotion": "none_human_review_required",
        "underlying_net_bps": _stats(underlying),
        "option_ask_to_bid_return_pct": _stats(option),
        "option_quote_coverage": round(len(option) / len(outcomes), 4) if outcomes else None,
        "option_entry_spread_distribution": spread_distribution,
        "underlying_by_direction": by_direction,
        "underlying_by_htf_context": by_htf_context,
        "vix_context": {"status": "not_captured"},
        "frozen_rule_drift_count": len(drift_reasons),
        "frozen_rule_drift_reasons": drift_reasons,
        "execution_enabled": False,
        "can_submit_orders": False,
    }


def run_signal(
    now_et: datetime,
    *,
    intraday_fetcher=fetch_intraday,
    daily_state_fetcher=fetch_daily_states,
    underlying_fetcher=fetch_alpaca_underlying_price,
    contract_fetcher=fetch_contract_candidates,
    quote_capturer=capture_lifecycle_sample,
    log_path: Path = LOG_PATH,
) -> dict[str, Any]:
    trading_day = now_et.date()
    rows = _read_log(log_path)
    if _existing_signal(rows, trading_day):
        return {"status": "duplicate_skipped", "summary": summarize(rows)}
    try:
        headers = _headers()
        frame = intraday_fetcher(trading_day, now_et, headers)
        states = daily_state_fetcher(trading_day)
    except Exception as exc:
        return _blocked("signal_data", exc, rows)
    signal = evaluate_frozen_signal(frame, states, trading_day)
    if signal is None:
        return {"status": "no_qualified_signal", "summary": summarize(rows)}
    try:
        underlying = underlying_fetcher("SPY", headers)
    except Exception as exc:
        return _blocked("underlying_entry", exc, rows)
    if float(underlying.get("price") or 0.0) <= 0:
        return {"status": "blocked_missing_underlying_entry", "summary": summarize(rows)}
    try:
        contracts = contract_fetcher(signal["direction"])
        selected = select_tracking_contract(
            contracts,
            direction=signal["direction"],
            spot=float(underlying["price"]),
            trading_day=trading_day,
        )
    except Exception:
        selected = None
    signal_id = _signal_id(trading_day, signal["direction"])
    record = {
        "schema_version": 1,
        "event": "signal",
        "lane": LANE,
        "signal_id": signal_id,
        "trading_date": trading_day.isoformat(),
        "captured_at": _iso(now_et),
        "signal": signal,
        "underlying_entry": underlying,
        "selected_contract": selected,
        "option_contract_status": "selected" if selected else "unavailable",
        "option_quote_scope": OPTION_QUOTE_SCOPE,
        "execution_enabled": False,
        "can_submit_orders": False,
    }
    _append(record, log_path)
    if selected:
        quote_capturer(
            "signal",
            selected["option_symbol"],
            bot=LANE,
            headers=headers,
            trade_id=signal_id,
            underlying_symbol="SPY",
            context={"frozen_signal": signal, "quote_scope": OPTION_QUOTE_SCOPE},
            path=QUOTE_PATH,
        )
    rows.append(record)
    return {"status": "signal_recorded", "record": record, "summary": summarize(rows)}


def run_resolve(
    now_et: datetime,
    *,
    underlying_fetcher=fetch_alpaca_underlying_price,
    quote_capturer=capture_lifecycle_sample,
    log_path: Path = LOG_PATH,
) -> dict[str, Any]:
    rows = _read_log(log_path)
    signal = _existing_signal(rows, now_et.date())
    if signal is None:
        return {"status": "no_open_signal", "summary": summarize(rows)}
    if _existing_outcome(rows, signal["signal_id"]):
        return {"status": "already_resolved", "summary": summarize(rows)}
    try:
        headers = _headers()
        underlying_exit = underlying_fetcher("SPY", headers)
    except Exception as exc:
        return _blocked("underlying_exit", exc, rows)
    selected = signal.get("selected_contract") or {}
    option_record = None
    if selected.get("option_symbol"):
        option_record = quote_capturer(
            "exit",
            selected["option_symbol"],
            bot=LANE,
            headers=headers,
            trade_id=signal["signal_id"],
            underlying_symbol="SPY",
            context={"quote_scope": OPTION_QUOTE_SCOPE},
            path=QUOTE_PATH,
        )
    outcome = build_outcome(
        signal,
        exit_underlying=underlying_exit,
        exit_option_record=option_record,
        resolved_at=now_et,
    )
    if outcome is None:
        return {"status": "blocked_missing_underlying_exit", "summary": summarize(rows)}
    _append(outcome, log_path)
    rows.append(outcome)
    return {"status": "outcome_recorded", "record": outcome, "summary": summarize(rows)}


def run(
    phase: str,
    *,
    now_et: datetime | None = None,
    allow_outside_window: bool = False,
    log_path: Path = LOG_PATH,
) -> dict[str, Any]:
    now_et = now_et or _now()
    if now_et.weekday() >= 5:
        return {"status": "market_closed", "summary": summarize(_read_log(log_path))}
    selected_phase = phase
    if phase == "auto":
        if _within_window(now_et, SIGNAL_WINDOW):
            selected_phase = "signal"
        elif _within_window(now_et, RESOLVE_WINDOW):
            selected_phase = "resolve"
        else:
            return {"status": "outside_frozen_window", "summary": summarize(_read_log(log_path))}
    window = SIGNAL_WINDOW if selected_phase == "signal" else RESOLVE_WINDOW
    if not allow_outside_window and not _within_window(now_et, window):
        return {"status": "outside_frozen_window", "summary": summarize(_read_log(log_path))}
    return run_signal(now_et, log_path=log_path) if selected_phase == "signal" else run_resolve(now_et, log_path=log_path)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--phase", choices=("auto", "signal", "resolve", "summary"), default="auto")
    parser.add_argument("--report", type=Path, default=REPORT_PATH)
    args = parser.parse_args()
    if args.phase == "summary":
        result = {"status": "summary", "summary": summarize(_read_log())}
    else:
        result = run(args.phase)
    result = {
        "schema_version": 1,
        "generated_at": _iso(_now()),
        "lane": LANE,
        "mode": "forward_shadow_only",
        "execution_enabled": False,
        "can_submit_orders": False,
        **result,
    }
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

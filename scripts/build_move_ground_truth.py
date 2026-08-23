#!/usr/bin/env python3
"""Build the frozen MOVE denominator from completed OHLC bars.

The labeling core is pure and accepts injected bars. Network acquisition is an
explicit production option: equities use Alpaca and futures use an entitled
Databento continuous-contract feed.
This module creates research evidence; it has no order path or execution
authority.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import requests


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.move_universe_ground_truth import MOVE_GROUND_TRUTH_SPEC, ground_truth_spec_status
from scripts.premarket_opportunity_radar import _credentials
from scripts.fetch_databento_futures import _load_api_key


MARKET_TZ = ZoneInfo("America/New_York")
SPEC_VERSION = "2026-08-20"
EQUITY_SYMBOLS = frozenset({"SPY", "QQQ", "IWM"})
FUTURES_SYMBOLS = frozenset({"MES", "ES", "NQ"})
TIMEFRAMES = ("5m", "15m", "1h", "D")
FULL_UNIVERSE = tuple((symbol, timeframe) for symbol in ("SPY", "QQQ", "IWM", "MES", "ES", "NQ") for timeframe in TIMEFRAMES)
HORIZON_BARS = {"5m": 12, "15m": 8, "1h": 6, "D": 3}
TIMEFRAME_DELTA = {"5m": timedelta(minutes=5), "15m": timedelta(minutes=15), "1h": timedelta(hours=1)}
ALPACA_TIMEFRAME = {"5m": "5Min", "15m": "15Min", "1h": "1Hour", "D": "1Day"}
DATABENTO_DATASET = "GLBX.MDP3"
DATABENTO_SCHEMA = "ohlcv-1m"
# This account's historical CME entitlement is delayed. Keeping a full-day
# buffer prevents a current-day request from being silently downgraded or
# rejected; current-session futures truth is expected to mature next day.
DATABENTO_AVAILABILITY_LAG = timedelta(hours=24)
ETF_MAGNITUDE_PCT = {"5m": 0.30, "15m": 0.50, "1h": 0.75, "D": 1.25}
FUTURES_MAGNITUDE_POINTS = {"5m": 5.0, "15m": 8.0, "1h": 12.0, "D": 25.0}
MIN_R = 1.5
MIN_RETENTION = 0.60
STOP_ATR_MULTIPLE = 0.5

MacroWindow = tuple[datetime, datetime, str]
RequestGet = Callable[..., Any]


def frozen_rule_contract() -> dict[str, Any]:
    return {
        "spec_version": SPEC_VERSION,
        "horizon_bars": dict(HORIZON_BARS),
        "equity_magnitude_pct": dict(ETF_MAGNITUDE_PCT),
        "futures_magnitude_points": dict(FUTURES_MAGNITUDE_POINTS),
        "atr": "simple mean of true range on fourteen completed pre-trigger bars",
        "atr_lookback_bars": 14,
        "minimum_r": MIN_R,
        "stop_atr_multiple": STOP_ATR_MULTIPLE,
        "intrabar_resolution": "stop first when target and stop occur in the same OHLC bar",
        "minimum_retention": MIN_RETENTION,
        "retention": "at least 60% of horizon closes retain at least 50% of peak favorable close excursion",
        "opening_rule": "equity triggers before 10:00 ET measure from 10:00 ET",
        "macro_rule": "CPI/FOMC-decision/NFP trigger inside release +/-15 minutes is excluded",
        "futures_session_rule": "RTH and explicitly flagged ETH horizons are never blended",
    }


def frozen_rule_hash() -> str:
    encoded = json.dumps(frozen_rule_contract(), separators=(",", ":"), sort_keys=True).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


@dataclass(frozen=True)
class Bar:
    timestamp: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float | None
    session: str | None
    session_date: str | None


def _utc_text(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _datetime(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        parsed = value
    else:
        try:
            parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except (TypeError, ValueError):
            return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _number(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _field(row: Mapping[str, Any], short: str, long: str) -> Any:
    return row.get(short) if row.get(short) is not None else row.get(long)


def _bar(row: Mapping[str, Any]) -> Bar | None:
    stamp = _datetime(row.get("bar_close_ts") or row.get("close_ts") or row.get("t") or row.get("timestamp"))
    open_price = _number(_field(row, "o", "open"))
    high = _number(_field(row, "h", "high"))
    low = _number(_field(row, "l", "low"))
    close = _number(_field(row, "c", "close"))
    if stamp is None or None in {open_price, high, low, close} or high < low:
        return None
    return Bar(
        timestamp=stamp,
        open=float(open_price),
        high=float(high),
        low=float(low),
        close=float(close),
        volume=_number(_field(row, "v", "volume")),
        session=str(row.get("session") or "").upper() or None,
        session_date=str(row.get("session_date") or "") or None,
    )


def _bars(rows: Iterable[Mapping[str, Any]], *, strict: bool = False) -> list[Bar]:
    normalized: list[Bar] = []
    for row in rows:
        parsed = _bar(row)
        if parsed is None:
            if strict:
                raise ValueError("invalid_or_incomplete_ohlc_bar")
            continue
        normalized.append(parsed)
    ordered = sorted(normalized, key=lambda item: item.timestamp)
    if strict and (
        ordered != normalized
        or any(current.timestamp <= previous.timestamp for previous, current in zip(ordered, ordered[1:]))
    ):
        raise ValueError("bars_must_be_strictly_chronological_and_unique")
    return ordered


def _true_range(current: Bar, previous_close: float) -> float:
    return max(current.high - current.low, abs(current.high - previous_close), abs(current.low - previous_close))


def compute_prior_atr14(bars: Sequence[Mapping[str, Any]], trigger_index: int) -> float | None:
    """Return simple ATR14 from fourteen completed pre-trigger true ranges.

    Fifteen pre-trigger bars are required because the oldest included true
    range also needs its causal previous close.  The trigger and all future
    bars are intentionally inaccessible to this calculation.
    """
    if trigger_index < 15 or trigger_index >= len(bars):
        return None
    window = [_bar(row) for row in bars[trigger_index - 15 : trigger_index]]
    if any(item is None for item in window):
        return None
    valid = [item for item in window if item is not None]
    ranges = [_true_range(valid[index], valid[index - 1].close) for index in range(1, 15)]
    return sum(ranges) / 14.0 if len(ranges) == 14 else None


def _prior_atr14_normalized(bars: Sequence[Bar], trigger_index: int) -> float | None:
    if trigger_index < 15 or trigger_index >= len(bars):
        return None
    window = bars[trigger_index - 15 : trigger_index]
    ranges = [_true_range(window[index], window[index - 1].close) for index in range(1, 15)]
    return sum(ranges) / 14.0 if len(ranges) == 14 else None


def _session(bar: Bar, symbol: str, timeframe: str) -> str:
    if timeframe == "D":
        return bar.session or "RTH"
    if symbol in EQUITY_SYMBOLS:
        return "RTH"
    if bar.session in {"RTH", "ETH"}:
        return bar.session
    return "UNKNOWN"


def _trigger_in_session(bar: Bar, symbol: str, timeframe: str) -> bool:
    if timeframe == "D" and symbol in EQUITY_SYMBOLS:
        return True
    if symbol in FUTURES_SYMBOLS:
        if bar.session not in {"RTH", "ETH"}:
            return False
        if timeframe == "D":
            return True
        local = bar.timestamp.astimezone(MARKET_TZ).time()
        if bar.session == "RTH":
            return time(9, 30) <= local <= time(16, 0)
        return local >= time(18, 0) or local < time(9, 30) or time(16, 0) < local <= time(17, 0)
    local = bar.timestamp.astimezone(MARKET_TZ).time()
    return time(9, 30) <= local <= time(16, 0)


def _futures_session_date(bar: Bar) -> str:
    if bar.session_date:
        return bar.session_date
    local = bar.timestamp.astimezone(MARKET_TZ)
    trading_date = local.date() + timedelta(days=1) if local.time() >= time(18, 0) else local.date()
    return trading_date.isoformat()


def _measurement_bars(bars: Sequence[Bar], trigger_index: int, symbol: str, timeframe: str) -> list[Bar]:
    trigger = bars[trigger_index]
    horizon = HORIZON_BARS[timeframe]
    if timeframe == "D":
        return list(bars[trigger_index + 1 : trigger_index + 1 + horizon])

    trigger_local = trigger.timestamp.astimezone(MARKET_TZ)
    start = trigger.timestamp
    if symbol in EQUITY_SYMBOLS and trigger_local.time() < time(10, 0):
        start = datetime.combine(trigger_local.date(), time(10, 0), MARKET_TZ).astimezone(timezone.utc)
    trigger_session = _session(trigger, symbol, timeframe)
    futures_session_date = _futures_session_date(trigger) if symbol in FUTURES_SYMBOLS else None
    output: list[Bar] = []
    for candidate in bars[trigger_index + 1 :]:
        if candidate.timestamp < start:
            continue
        if symbol in EQUITY_SYMBOLS:
            local = candidate.timestamp.astimezone(MARKET_TZ)
            if local.date() != trigger_local.date() or not (time(9, 30) <= local.time() <= time(16, 0)):
                continue
        elif _session(candidate, symbol, timeframe) != trigger_session:
            # Do not blend RTH and ETH futures structures.
            continue
        elif _futures_session_date(candidate) != futures_session_date:
            continue
        if trigger.session_date and candidate.session_date and trigger.session_date != candidate.session_date:
            continue
        output.append(candidate)
        if len(output) == horizon:
            break
    return output


def _macro_reason(trigger: datetime, macro_windows: Iterable[MacroWindow]) -> str | None:
    for start, end, label in macro_windows:
        normalized_start = _datetime(start)
        normalized_end = _datetime(end)
        if normalized_start is not None and normalized_end is not None and normalized_start <= trigger <= normalized_end:
            return f"macro_event_window:{label}"
    return None


def frozen_macro_windows(target_date: date) -> tuple[list[MacroWindow], bool]:
    """Return CPI/FOMC/NFP release windows from the maintained calendar.

    The MOVE specification freezes a +/-15 minute exclusion around those
    releases.  Coverage is explicitly false after the maintained calendar's
    declared end date, preventing an empty calendar from masquerading as proof
    that no event existed.
    """
    from scripts.market_catalyst_calendar import CALENDAR_COVERAGE_END, events_for_date

    if target_date > CALENDAR_COVERAGE_END:
        return [], False
    windows: list[MacroWindow] = []
    for event in events_for_date(target_date):
        name = str(event.get("name") or "")
        normalized_name = name.lower()
        if not any(marker in normalized_name for marker in ("cpi", "fomc decision", "employment situation", "nonfarm", "nfp")):
            continue
        raw_time = str(event.get("time_et") or "")
        try:
            hour, minute = (int(value) for value in raw_time.split(":", 1))
        except (TypeError, ValueError):
            return [], False
        release = datetime.combine(target_date, time(hour, minute), MARKET_TZ).astimezone(timezone.utc)
        windows.append((release - timedelta(minutes=15), release + timedelta(minutes=15), name))
    return windows, True


def _base_row(
    trigger: Bar,
    *,
    symbol: str,
    timeframe: str,
    data_source: str,
    macro_context_qualified: bool,
) -> dict[str, Any]:
    session = _session(trigger, symbol, timeframe)
    if symbol in FUTURES_SYMBOLS and timeframe != "D":
        session_date = date.fromisoformat(_futures_session_date(trigger))
    else:
        session_date = trigger.timestamp.date() if timeframe == "D" else trigger.timestamp.astimezone(MARKET_TZ).date()
    return {
        "move_id": f"{symbol}:{timeframe}:{_utc_text(trigger.timestamp)}",
        # A deterministic evidence timestamp keeps the pure labeling result
        # reproducible.  Report generation time is tracked only at report level.
        "ts_utc": _utc_text(trigger.timestamp),
        "date": session_date.isoformat(),
        "trigger_bar_ts": _utc_text(trigger.timestamp),
        "bar_close_ts": _utc_text(trigger.timestamp),
        "instrument": symbol,
        "symbol": symbol,
        "asset_class": "equity_etf" if symbol in EQUITY_SYMBOLS else "futures",
        "timeframe": timeframe,
        "session": session,
        "trigger_price": round(trigger.close, 8),
        "data_source": data_source,
        "spec_version": SPEC_VERSION,
        "rule_hash": frozen_rule_hash(),
        "spec_status": "approved_frozen",
        "evidence_role": "independent_ground_truth_denominator",
        "macro_context_qualified": macro_context_qualified,
        "execution_enabled": False,
        "can_submit_orders": False,
    }


def _excluded_row(
    base: dict[str, Any],
    reason: str,
    *,
    atr14: float | None = None,
    observed: Sequence[Bar] = (),
) -> dict[str, Any]:
    return {
        **base,
        "atr14": round(atr14, 8) if atr14 is not None else None,
        "horizon_bars": HORIZON_BARS[base["timeframe"]],
        "horizon_bars_observed": len(observed),
        "horizon_end_ts": _utc_text(observed[-1].timestamp) if observed else None,
        "measurement_start_ts": _utc_text(observed[0].timestamp) if observed else None,
        "label": None,
        "direction": None,
        "label_reason": "excluded",
        "excluded": True,
        "excluded_reason": reason,
        "metrics_qualified": False,
    }


def _retention(closes: Sequence[float], trigger: float, *, direction: int) -> tuple[float, float]:
    excursions = [max(0.0, direction * (close - trigger)) for close in closes]
    peak = max(excursions, default=0.0)
    if peak <= 0 or not excursions:
        return peak, 0.0
    retained = sum(excursion >= peak * 0.5 for excursion in excursions)
    return peak, retained / len(excursions)


def _target_before_stop(
    bars: Sequence[Bar],
    *,
    trigger: float,
    stop_distance: float,
    direction: int,
) -> tuple[bool, bool]:
    """Conservatively resolve whether 1.5R was reachable before the stop.

    With OHLC bars the intrabar path is unknown.  If stop and target coexist in
    one candle, stop wins so retrospective labels never get optimistic credit.
    """
    stop = trigger - direction * stop_distance
    target = trigger + direction * stop_distance * MIN_R
    for bar in bars:
        stop_hit = bar.low <= stop if direction == 1 else bar.high >= stop
        target_hit = bar.high >= target if direction == 1 else bar.low <= target
        if stop_hit:
            return False, target_hit
        if target_hit:
            return True, False
    return False, False


def label_trigger(
    raw_bars: Sequence[Mapping[str, Any]],
    trigger_index: int,
    *,
    symbol: str,
    timeframe: str,
    data_source: str,
    macro_windows: Iterable[MacroWindow] = (),
    macro_context_qualified: bool = True,
) -> dict[str, Any]:
    """Label one trigger using only prior ATR bars and its completed horizon."""
    symbol = symbol.upper()
    if symbol not in EQUITY_SYMBOLS | FUTURES_SYMBOLS:
        raise ValueError(f"unsupported instrument: {symbol}")
    if timeframe not in HORIZON_BARS:
        raise ValueError(f"unsupported timeframe: {timeframe}")
    bars = _bars(raw_bars, strict=True)
    if trigger_index < 0 or trigger_index >= len(bars):
        raise IndexError("trigger index outside normalized bars")
    trigger = bars[trigger_index]
    base = _base_row(
        trigger,
        symbol=symbol,
        timeframe=timeframe,
        data_source=data_source,
        macro_context_qualified=macro_context_qualified,
    )
    if not _trigger_in_session(trigger, symbol, timeframe):
        return _excluded_row(base, "trigger_outside_eligible_session")
    if not macro_context_qualified:
        return _excluded_row(base, "macro_calendar_coverage_unavailable")
    if reason := _macro_reason(trigger.timestamp, macro_windows):
        return _excluded_row(base, reason)

    atr14 = _prior_atr14_normalized(bars, trigger_index)
    if atr14 is None or atr14 <= 0:
        return _excluded_row(base, "insufficient_prior_atr14_bars")
    future = _measurement_bars(bars, trigger_index, symbol, timeframe)
    horizon = HORIZON_BARS[timeframe]
    if len(future) < horizon:
        return _excluded_row(base, "insufficient_completed_horizon", atr14=atr14, observed=future)

    trigger_price = trigger.close
    stop_distance = STOP_ATR_MULTIPLE * atr14
    closes = [bar.close for bar in future]
    peak_close_long, retention_long = _retention(closes, trigger_price, direction=1)
    peak_close_short, retention_short = _retention(closes, trigger_price, direction=-1)
    peak_favorable_long = max(0.0, max(bar.high for bar in future) - trigger_price)
    peak_favorable_short = max(0.0, trigger_price - min(bar.low for bar in future))
    peak_adverse_long = max(0.0, trigger_price - min(bar.low for bar in future))
    peak_adverse_short = max(0.0, max(bar.high for bar in future) - trigger_price)
    achievable_r_long = peak_favorable_long / stop_distance
    achievable_r_short = peak_favorable_short / stop_distance
    target_before_stop_long, ambiguous_long = _target_before_stop(
        future, trigger=trigger_price, stop_distance=stop_distance, direction=1
    )
    target_before_stop_short, ambiguous_short = _target_before_stop(
        future, trigger=trigger_price, stop_distance=stop_distance, direction=-1
    )
    final_move = future[-1].close - trigger_price
    realized_r_long = final_move / stop_distance
    realized_r_short = -final_move / stop_distance

    if symbol in EQUITY_SYMBOLS:
        threshold = ETF_MAGNITUDE_PCT[timeframe]
        magnitude_long = peak_close_long / trigger_price * 100.0
        magnitude_short = peak_close_short / trigger_price * 100.0
        threshold_unit = "percent"
    else:
        threshold = FUTURES_MAGNITUDE_POINTS[timeframe]
        magnitude_long = peak_close_long
        magnitude_short = peak_close_short
        threshold_unit = "points"

    long_checks = {
        "magnitude": magnitude_long + 1e-12 >= threshold,
        "r_multiple": achievable_r_long + 1e-12 >= MIN_R and target_before_stop_long,
        "retention": retention_long + 1e-12 >= MIN_RETENTION,
    }
    short_checks = {
        "magnitude": magnitude_short + 1e-12 >= threshold,
        "r_multiple": achievable_r_short + 1e-12 >= MIN_R and target_before_stop_short,
        "retention": retention_short + 1e-12 >= MIN_RETENTION,
    }
    long_qualifies = all(long_checks.values())
    short_qualifies = all(short_checks.values())
    if long_qualifies and short_qualifies:
        label = 1 if achievable_r_long > achievable_r_short else -1 if achievable_r_short > achievable_r_long else 0
        reason = (
            f"{'long' if label == 1 else 'short'}_move_both_sides_qualified_higher_r"
            if label
            else "no_move_ambiguous_equal_two_sided_displacement"
        )
    elif long_qualifies:
        label, reason = 1, f"long_move_{achievable_r_long:.2f}R_{retention_long:.0%}_retention"
    elif short_qualifies:
        label, reason = -1, f"short_move_{achievable_r_short:.2f}R_{retention_short:.0%}_retention"
    else:
        label = 0
        failed = sorted(
            {
                f"{name}_below_{'60pct' if name == 'retention' else 'threshold'}"
                for checks in (long_checks, short_checks)
                for name, passed in checks.items()
                if not passed
            }
        )
        reason = "no_move:" + ",".join(failed)

    return {
        **base,
        "atr14": round(atr14, 8),
        "stop_distance": round(stop_distance, 8),
        "stop_method": "0.5_x_prior_14_completed_bar_simple_true_range_atr",
        "horizon_bars": horizon,
        "horizon_bars_observed": len(future),
        "measurement_start_ts": _utc_text(future[0].timestamp),
        "horizon_end_ts": _utc_text(future[-1].timestamp),
        "magnitude_threshold": threshold,
        "magnitude_threshold_unit": threshold_unit,
        "magnitude_long": round(magnitude_long, 8),
        "magnitude_short": round(magnitude_short, 8),
        "peak_favorable_long": round(peak_favorable_long, 8),
        "peak_favorable_short": round(peak_favorable_short, 8),
        "peak_adverse_long": round(peak_adverse_long, 8),
        "peak_adverse_short": round(peak_adverse_short, 8),
        "achievable_r_long": round(achievable_r_long, 8),
        "achievable_r_short": round(achievable_r_short, 8),
        "target_before_stop_long": target_before_stop_long,
        "target_before_stop_short": target_before_stop_short,
        "ambiguous_same_bar_long": ambiguous_long,
        "ambiguous_same_bar_short": ambiguous_short,
        "intrabar_resolution": "stop_first_when_target_and_stop_share_one_ohlc_bar",
        "realized_r_long": round(realized_r_long, 8),
        "realized_r_short": round(realized_r_short, 8),
        "retention_long": round(retention_long, 8),
        "retention_short": round(retention_short, 8),
        "retention_definition": "share_of_horizon_closes_retaining_at_least_50pct_of_peak_close_excursion",
        "long_checks": long_checks,
        "short_checks": short_checks,
        "label": label,
        "direction": "bullish" if label == 1 else "bearish" if label == -1 else None,
        "label_reason": reason,
        "excluded": False,
        "excluded_reason": None,
        "metrics_qualified": True,
    }


def build_labels(
    *,
    symbol: str,
    timeframe: str,
    bars: Sequence[Mapping[str, Any]],
    target_date: date,
    data_source: str,
    macro_windows: Iterable[MacroWindow] = (),
    macro_context_qualified: bool = True,
) -> list[dict[str, Any]]:
    """Label every bar on one target session, including explicit exclusions."""
    normalized = _bars(bars, strict=True)
    normalized_rows = [
        {
            "bar_close_ts": _utc_text(bar.timestamp),
            "o": bar.open,
            "h": bar.high,
            "l": bar.low,
            "c": bar.close,
            "v": bar.volume,
            "session": bar.session,
            "session_date": bar.session_date,
        }
        for bar in normalized
    ]
    output: list[dict[str, Any]] = []
    for index, bar in enumerate(normalized):
        if symbol.upper() in FUTURES_SYMBOLS and timeframe != "D":
            bar_date = date.fromisoformat(_futures_session_date(bar))
        else:
            bar_date = bar.timestamp.astimezone(MARKET_TZ).date() if timeframe != "D" else bar.timestamp.date()
        if bar_date != target_date:
            continue
        output.append(
            label_trigger(
                normalized_rows,
                index,
                symbol=symbol,
                timeframe=timeframe,
                data_source=data_source,
                macro_windows=macro_windows,
                macro_context_qualified=macro_context_qualified,
            )
        )
    return output


def build_ground_truth_report(
    *,
    bars_by_pair: Mapping[tuple[str, str], Sequence[Mapping[str, Any]]],
    target_date: date,
    requested_pairs: Sequence[tuple[str, str]] = FULL_UNIVERSE,
    data_sources: Mapping[tuple[str, str], str] | None = None,
    macro_windows: Iterable[MacroWindow] = (),
    macro_context_qualified: bool = True,
) -> dict[str, Any]:
    """Build a report and fail global qualification closed on missing pairs."""
    sources = data_sources or {}
    macro_windows = tuple(macro_windows)
    rows: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []
    pair_status: list[dict[str, Any]] = []
    if not macro_context_qualified:
        failures.append(
            {
                "instrument": "ALL",
                "timeframe": "ALL",
                "reason": "macro_calendar_coverage_unavailable",
                "execution_enabled": False,
                "can_submit_orders": False,
            }
        )
    for raw_symbol, timeframe in requested_pairs:
        symbol = raw_symbol.upper()
        pair = (symbol, timeframe)
        raw = bars_by_pair.get(pair)
        if not raw:
            failure = {
                "instrument": symbol,
                "timeframe": timeframe,
                "reason": "bars_unavailable_or_not_entitled",
                "execution_enabled": False,
                "can_submit_orders": False,
            }
            failures.append(failure)
            pair_status.append({**failure, "qualified": False})
            continue
        data_source = str(sources.get(pair) or "")
        if not data_source or data_source.lower() in {"unknown", "injected_unknown"}:
            failure = {
                "instrument": symbol,
                "timeframe": timeframe,
                "reason": "data_source_provenance_unavailable",
                "execution_enabled": False,
                "can_submit_orders": False,
            }
            failures.append(failure)
            pair_status.append({**failure, "qualified": False})
            continue
        try:
            pair_rows = build_labels(
                symbol=symbol,
                timeframe=timeframe,
                bars=raw,
                target_date=target_date,
                data_source=data_source,
                macro_windows=macro_windows,
                macro_context_qualified=macro_context_qualified,
            )
        except (IndexError, ValueError):
            failure = {
                "instrument": symbol,
                "timeframe": timeframe,
                "reason": "invalid_or_noncausal_bar_sequence",
                "execution_enabled": False,
                "can_submit_orders": False,
            }
            failures.append(failure)
            pair_status.append({**failure, "qualified": False})
            continue
        rows.extend(pair_rows)
        pair_qualified = bool(pair_rows) and any(not row["excluded"] for row in pair_rows)
        pair_status.append(
            {
                "instrument": symbol,
                "timeframe": timeframe,
                "qualified": pair_qualified,
                "rows": len(pair_rows),
                "data_source": data_source,
                "execution_enabled": False,
                "can_submit_orders": False,
            }
        )
        if not pair_qualified:
            failures.append(
                {
                    "instrument": symbol,
                    "timeframe": timeframe,
                    "reason": "no_matured_eligible_rows",
                    "execution_enabled": False,
                    "can_submit_orders": False,
                }
            )
    acquisition_failure_reasons = {
        "macro_calendar_coverage_unavailable",
        "bars_unavailable_or_not_entitled",
        "data_source_provenance_unavailable",
        "invalid_or_noncausal_bar_sequence",
    }
    producer_failures = [row for row in failures if row.get("reason") in acquisition_failure_reasons]
    evidence_pending = [row for row in failures if row.get("reason") == "no_matured_eligible_rows"]
    producer_healthy = not producer_failures
    metrics_qualified = not failures
    ground_truth_status = (
        "qualified"
        if metrics_qualified
        else "awaiting_horizon_maturity"
        if producer_healthy and evidence_pending
        else "partial_fail_closed"
    )
    return {
        "schema_version": 2,
        "provider": "independent_move_ground_truth_builder",
        "generated_at": _utc_text(datetime.now(timezone.utc)),
        "date": target_date.isoformat(),
        "spec_version": SPEC_VERSION,
        "ground_truth_status": ground_truth_status,
        "producer_healthy": producer_healthy,
        "acquisition_complete": producer_healthy,
        "evidence_pending_count": len(evidence_pending),
        "metrics_qualified": metrics_qualified,
        "pattern_annotation_qualified": False,
        "pattern_annotation_status": "independent_price_move_denominator_has_no_hindsight_pattern_family_labels",
        "rule_hash": frozen_rule_hash(),
        "definition": frozen_rule_contract(),
        "macro_context": {
            "qualified": macro_context_qualified,
            "windows": [
                {"start_utc": _utc_text(start), "end_utc": _utc_text(end), "event": label}
                for start, end, label in macro_windows
            ],
        },
        "requested_pairs": [{"instrument": symbol, "timeframe": timeframe} for symbol, timeframe in requested_pairs],
        "pair_status": pair_status,
        "source_failures": failures,
        "rows": rows,
        "moves": [row for row in rows if row["label"] in {-1, 1}],
        "excluded": [row for row in rows if row["excluded"]],
        "summary": {
            "rows": len(rows),
            "positive_long": sum(row["label"] == 1 for row in rows),
            "positive_short": sum(row["label"] == -1 for row in rows),
            "no_move": sum(row["label"] == 0 for row in rows),
            "excluded": sum(row["excluded"] for row in rows),
            "source_failures": len(failures),
        },
        "warnings": [
            "Ground truth is a retrospective detection denominator, not a trade recommendation.",
            "IEX rows cover the IEX venue only; SIP should be preferred when entitled.",
            "Futures fail closed whenever entitled Databento bars or explicit RTH/ETH flags are unavailable.",
        ],
        "execution_enabled": False,
        "can_submit_orders": False,
    }


def fetch_alpaca_bars(
    symbol: str,
    timeframe: str,
    *,
    start: datetime,
    end: datetime,
    feed: str,
    request_get: RequestGet = requests.get,
) -> list[dict[str, Any]]:
    """Fetch completed ETF bars; raise rather than downgrade or synthesize data."""
    symbol = symbol.upper()
    if symbol not in EQUITY_SYMBOLS:
        raise RuntimeError("futures_feed_not_configured_or_entitled")
    if timeframe not in ALPACA_TIMEFRAME:
        raise ValueError(f"unsupported timeframe: {timeframe}")
    if feed not in {"iex", "sip"}:
        raise ValueError("feed must be iex or sip")
    headers = _credentials()
    if not headers.get("APCA-API-KEY-ID") or not headers.get("APCA-API-SECRET-KEY"):
        raise RuntimeError("alpaca_credentials_unavailable")
    params: dict[str, Any] = {
        "timeframe": ALPACA_TIMEFRAME[timeframe],
        "start": _utc_text(start),
        "end": _utc_text(end),
        "adjustment": "raw",
        "feed": feed,
        "sort": "asc",
        "limit": 10_000,
    }
    output: list[dict[str, Any]] = []
    while True:
        response = request_get(
            f"https://data.alpaca.markets/v2/stocks/{symbol}/bars",
            headers=headers,
            params=params,
            timeout=30,
        )
        response.raise_for_status()
        payload = response.json()
        for raw in payload.get("bars") or []:
            if not isinstance(raw, dict):
                continue
            row = dict(raw)
            stamp = _datetime(row.get("t"))
            if stamp is None:
                continue
            # Alpaca timestamps bars at the interval start.  The frozen spec is
            # keyed to completed-bar closes, so preserve and normalize both.
            row["source_bar_start_ts"] = _utc_text(stamp)
            row["bar_close_ts"] = _utc_text(stamp + TIMEFRAME_DELTA[timeframe]) if timeframe != "D" else _utc_text(stamp)
            output.append(row)
        token = payload.get("next_page_token")
        if not token:
            break
        params["page_token"] = token
    return output


def _futures_session_label(stamp: datetime) -> tuple[str, str]:
    local = stamp.astimezone(MARKET_TZ)
    wall = local.time().replace(tzinfo=None)
    session = "RTH" if time(9, 30) < wall <= time(16, 0) else "ETH"
    session_date = local.date() + timedelta(days=1) if wall >= time(18, 0) else local.date()
    return session, session_date.isoformat()


def _databento_rows(frame: Any, timeframe: str) -> list[dict[str, Any]]:
    import pandas as pd

    if frame.empty:
        return []
    data = frame.copy()
    data.index = pd.to_datetime(data.index, utc=True)
    required = ["open", "high", "low", "close", "volume"]
    if any(column not in data.columns for column in required):
        raise ValueError("databento_ohlcv_columns_missing")
    data = data[required].sort_index()
    for column in required:
        data[column] = pd.to_numeric(data[column], errors="raise")
    if timeframe == "D":
        session_dates = [
            date.fromisoformat(
                _futures_session_label(stamp.to_pydatetime() + timedelta(minutes=1))[1]
            )
            for stamp in data.index
        ]
        grouped = data.assign(session_date=session_dates).groupby("session_date").agg(
            open=("open", "first"), high=("high", "max"), low=("low", "min"),
            close=("close", "last"), volume=("volume", "sum")
        )
        rows: list[dict[str, Any]] = []
        for session_date, row in grouped.iterrows():
            close = datetime.combine(session_date, time(17, 0), MARKET_TZ).astimezone(timezone.utc)
            rows.append({
                "bar_close_ts": _utc_text(close), "o": row.open, "h": row.high,
                "l": row.low, "c": row.close, "v": row.volume,
                "session": "RTH", "session_date": session_date.isoformat(),
            })
        return rows
    rule = {"5m": "5min", "15m": "15min", "1h": "1h"}[timeframe]
    grouped = data.resample(rule, label="left", closed="left").agg(
        open=("open", "first"), high=("high", "max"), low=("low", "min"),
        close=("close", "last"), volume=("volume", "sum")
    ).dropna(subset=["open", "high", "low", "close"])
    delta = TIMEFRAME_DELTA[timeframe]
    rows = []
    for start, row in grouped.iterrows():
        close = start.to_pydatetime() + delta
        session, session_date = _futures_session_label(close)
        rows.append({
            "source_bar_start_ts": _utc_text(start.to_pydatetime()),
            "bar_close_ts": _utc_text(close),
            "o": row.open, "h": row.high, "l": row.low, "c": row.close, "v": row.volume,
            "session": session, "session_date": session_date,
        })
    return rows


def fetch_databento_timeframes(
    symbol: str,
    *,
    start: datetime,
    end: datetime,
    client: Any | None = None,
    max_cost_usd: float = 5.0,
) -> tuple[dict[str, list[dict[str, Any]]], dict[str, Any]]:
    """Fetch one continuous futures product once, then derive every frozen timeframe."""
    symbol = symbol.upper()
    if symbol not in FUTURES_SYMBOLS:
        raise ValueError("Databento acquisition is futures-only")
    if client is None:
        import databento as db

        client = db.Historical(_load_api_key())
    kwargs = {
        "dataset": DATABENTO_DATASET,
        "schema": DATABENTO_SCHEMA,
        "symbols": f"{symbol}.v.0",
        "stype_in": "continuous",
        "start": start,
        "end": end,
    }
    cost = float(client.metadata.get_cost(**kwargs))
    if cost > max(0.0, max_cost_usd):
        raise RuntimeError("databento_cost_limit_exceeded")
    conditions = client.metadata.get_dataset_condition(
        dataset=DATABENTO_DATASET,
        start_date=start,
        end_date=end,
    )
    excluded_dates = sorted({
        str(row.get("date"))
        for row in conditions
        if isinstance(row, Mapping) and row.get("condition") != "available"
    })
    frame = client.timeseries.get_range(**kwargs).to_df()
    if excluded_dates and not frame.empty:
        import pandas as pd

        utc_dates = pd.to_datetime(frame.index, utc=True).date.astype(str)
        frame = frame[~pd.Index(utc_dates).isin(excluded_dates)]
    outputs = {timeframe: _databento_rows(frame, timeframe) for timeframe in TIMEFRAMES}
    return outputs, {
        "provider": "databento",
        "dataset": DATABENTO_DATASET,
        "schema": DATABENTO_SCHEMA,
        "symbol": f"{symbol}.v.0",
        "stype_in": "continuous",
        "cost_usd": round(cost, 6),
        "excluded_dataset_condition_dates": excluded_dates,
        "execution_enabled": False,
        "can_submit_orders": False,
    }


def _read_injected(path: Path) -> tuple[dict[tuple[str, str], list[dict[str, Any]]], dict[tuple[str, str], str]]:
    payload = json.loads(path.read_text(encoding="utf-8-sig"))
    entries = payload.get("pairs") if isinstance(payload, dict) else None
    if not isinstance(entries, list):
        raise ValueError("input JSON must contain a pairs array")
    bars: dict[tuple[str, str], list[dict[str, Any]]] = {}
    sources: dict[tuple[str, str], str] = {}
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        pair = (str(entry.get("instrument") or "").upper(), str(entry.get("timeframe") or ""))
        if pair[0] and pair[1] and isinstance(entry.get("bars"), list):
            bars[pair] = entry["bars"]
            sources[pair] = str(entry.get("data_source") or "injected_file")
    return bars, sources


def _atomic_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(path)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--date", required=True, help="Target session date (YYYY-MM-DD)")
    parser.add_argument("--input-json", type=Path, help="Injected pair/bar payload; avoids all network access")
    parser.add_argument(
        "--production-alpaca",
        action="store_true",
        help="Explicitly acquire ETFs from Alpaca and entitled futures from Databento",
    )
    parser.add_argument("--feed", choices=("iex", "sip"), default="iex")
    parser.add_argument("--max-databento-cost-usd", type=float, default=5.0)
    parser.add_argument("--spec", type=Path, default=MOVE_GROUND_TRUTH_SPEC)
    parser.add_argument("--output", type=Path, help="Optional JSON report path; stdout is the default")
    args = parser.parse_args()
    if bool(args.input_json) == bool(args.production_alpaca):
        parser.error("select exactly one of --input-json or --production-alpaca")
    target = date.fromisoformat(args.date)
    status = ground_truth_spec_status(args.spec)
    if not status["approved"]:
        report = {
            "schema_version": 2,
            "provider": "independent_move_ground_truth_builder",
            "generated_at": _utc_text(datetime.now(timezone.utc)),
            "date": target.isoformat(),
            "ground_truth_status": "spec_not_approved_fail_closed",
            "metrics_qualified": False,
            "pattern_annotation_qualified": False,
            "spec": status,
            "rows": [],
            "moves": [],
            "source_failures": [],
            "execution_enabled": False,
            "can_submit_orders": False,
        }
    else:
        macro_windows, macro_context_qualified = frozen_macro_windows(target)
        acquisition: list[dict[str, Any]] = []
        if args.input_json:
            bars_by_pair, sources = _read_injected(args.input_json)
            acquisition.append({
                "provider": "injected_file",
                "path": str(args.input_json),
                "execution_enabled": False,
                "can_submit_orders": False,
            })
        else:
            bars_by_pair, sources = {}, {}
            start = datetime.combine(target - timedelta(days=45), time.min, timezone.utc)
            replay_end = datetime.combine(target + timedelta(days=7), time.max, timezone.utc)
            alpaca_end = min(replay_end, datetime.now(timezone.utc))
            databento_end = min(replay_end, datetime.now(timezone.utc) - DATABENTO_AVAILABILITY_LAG)
            for symbol in sorted(EQUITY_SYMBOLS):
                for timeframe in TIMEFRAMES:
                    try:
                        bars_by_pair[(symbol, timeframe)] = fetch_alpaca_bars(
                            symbol, timeframe, start=start, end=alpaca_end, feed=args.feed
                        )
                        sources[(symbol, timeframe)] = f"alpaca_{args.feed}"
                        acquisition.append({
                            "provider": "alpaca",
                            "feed": args.feed,
                            "symbol": symbol,
                            "timeframe": timeframe,
                            "execution_enabled": False,
                            "can_submit_orders": False,
                        })
                    except Exception:
                        # Report-level pair reconciliation carries the failure;
                        # never print broker responses, credentials, or secrets.
                        continue
            remaining_databento_cost = max(0.0, args.max_databento_cost_usd)
            for symbol in sorted(FUTURES_SYMBOLS):
                try:
                    timeframes, provenance = fetch_databento_timeframes(
                        symbol,
                        start=start,
                        end=databento_end,
                        max_cost_usd=remaining_databento_cost,
                    )
                    remaining_databento_cost -= float(provenance["cost_usd"])
                    acquisition.append(provenance)
                    for timeframe, rows in timeframes.items():
                        bars_by_pair[(symbol, timeframe)] = rows
                        sources[(symbol, timeframe)] = (
                            f"databento:{provenance['dataset']}:{provenance['schema']}:continuous"
                        )
                except Exception:
                    # Full-universe reconciliation records missing entitlement,
                    # cost-limit refusal, and provider failures without leaking responses.
                    continue
        report = build_ground_truth_report(
            bars_by_pair=bars_by_pair,
            data_sources=sources,
            target_date=target,
            macro_windows=macro_windows,
            macro_context_qualified=macro_context_qualified,
        )
        report["spec"] = status
        report["acquisition"] = acquisition
    if args.output:
        _atomic_json(args.output, report)
        print(f"move_ground_truth status={report['ground_truth_status']} rows={len(report['rows'])} output={args.output}")
    else:
        print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["metrics_qualified"] else 2


if __name__ == "__main__":
    raise SystemExit(main())

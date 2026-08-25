#!/usr/bin/env python3
"""Causal, read-only market-structure recognition for the trading dashboard.

The module only evaluates completed OHLCV bars.  Every swing is delayed until
its right-hand confirmation bars exist, so a chart shape cannot repaint into a
historical signal.  Outputs are research priorities for manual review and have
no execution authority.
"""
from __future__ import annotations

import math
from datetime import datetime, time as wall_time, timezone
from statistics import median
from typing import Any, Mapping, Sequence
from zoneinfo import ZoneInfo

from agent.src.tools.pattern_grade_scorer import score_pattern_grade


PATTERN_CATALOG: tuple[dict[str, Any], ...] = (
    {"id": "trend_pullback", "family": "trend", "complexity": "simple", "role": "setup", "confirmation": "trend resumes after a controlled pullback"},
    {"id": "support_resistance_rejection", "family": "price_action", "complexity": "simple", "role": "setup", "confirmation": "closed-bar rejection at a confirmed swing level"},
    {"id": "range_break_retest", "family": "classical", "complexity": "simple", "role": "setup", "confirmation": "break, retest, and close back in the break direction"},
    {"id": "vwap_reclaim_reject", "family": "anchored_volume", "complexity": "simple", "role": "setup", "confirmation": "closed-bar cross and hold around session VWAP"},
    {"id": "double_top_bottom", "family": "classical", "complexity": "intermediate", "role": "setup", "confirmation": "two confirmed extrema plus neckline break"},
    {"id": "head_and_shoulders", "family": "classical", "complexity": "intermediate", "role": "setup", "confirmation": "three confirmed extrema plus neckline break"},
    {"id": "compression_breakout", "family": "volatility", "complexity": "intermediate", "role": "setup", "confirmation": "contracting range followed by volume-confirmed expansion"},
    {"id": "flag_continuation", "family": "classical", "complexity": "intermediate", "role": "setup", "confirmation": "impulse, shallow countertrend flag, and resumption close"},
    {"id": "liquidity_sweep_mss_retest", "family": "liquidity_structure", "complexity": "advanced", "role": "setup", "confirmation": "sweep, structural displacement, and level hold"},
    {"id": "cbc_strong_flip", "family": "candle_control", "complexity": "intermediate", "role": "setup", "confirmation": "completed candle sweeps both prior-candle extremes and closes through the opposite extreme"},
    {"id": "session_liquidity_sweep_reclaim", "family": "session_liquidity", "complexity": "advanced", "role": "setup", "confirmation": "completed candle sweeps a causal prior-session or opening-range level and closes back through it"},
    {"id": "ict_cisd_universal_model", "family": "liquidity_delivery", "complexity": "advanced", "role": "setup", "confirmation": "HTF FVG context, third-candle range, liquidity sweep, chronological IFVG, and closed-body CISD"},
    {"id": "multi_timeframe_alignment", "family": "multi_timeframe", "complexity": "advanced", "role": "confirmation", "confirmation": "5m trigger agrees with available higher frames"},
    {"id": "failed_breakout_trap", "family": "anti_pattern", "complexity": "anti_pattern", "role": "veto", "confirmation": "breakout closes back through the broken range"},
    {"id": "late_chase_exhaustion", "family": "anti_pattern", "complexity": "anti_pattern", "role": "veto", "confirmation": "entry is extended beyond preregistered ATR distance"},
    {"id": "midrange_chop", "family": "anti_pattern", "complexity": "anti_pattern", "role": "veto", "confirmation": "low directional efficiency near the range midpoint"},
    {"id": "broadening_instability", "family": "anti_pattern", "complexity": "anti_pattern", "role": "veto", "confirmation": "expanding ranges without directional control"},
    {"id": "weak_breakout_no_participation", "family": "anti_pattern", "complexity": "anti_pattern", "role": "veto", "confirmation": "level break lacks relative volume confirmation"},
    {"id": "wide_spread_or_stale", "family": "market_quality", "complexity": "anti_pattern", "role": "veto", "confirmation": "quote freshness or spread fails the live gate"},
)

PATTERN_BASE_RATE_PRIORS: dict[str, float] = {
    "trend_pullback": 55.0,
    "support_resistance_rejection": 55.0,
    "range_break_retest": 55.0,
    "vwap_reclaim_reject": 55.0,
    "double_top_bottom": 64.0,
    "head_and_shoulders": 61.0,
    "compression_breakout": 55.0,
    "flag_continuation": 68.0,
    "liquidity_sweep_mss_retest": 55.0,
    "ict_cisd_universal_model": 55.0,
}

MAX_SPREAD_BPS = 35.0
MIN_RVOL = 1.25
MIN_DOLLAR_LIQUIDITY = 20_000_000.0
MIN_BARS = 8
MARKET_TZ = ZoneInfo("America/New_York")

# Timeframes have distinct jobs.  A lower timeframe is not allowed to stand in
# for regime context, and a higher timeframe is not treated as an entry
# trigger.  The thresholds are data-sufficiency gates, not performance claims.
APLUS_TIMEFRAME_MATRIX: tuple[dict[str, Any], ...] = (
    {"timeframe": "1m", "role": "execution_refinement", "minimum_bars": 8, "required_for_aplus": False},
    {"timeframe": "5m", "role": "primary_trigger", "minimum_bars": 8, "required_for_aplus": True},
    {"timeframe": "15m", "role": "trigger_confirmation", "minimum_bars": 8, "required_for_aplus": True},
    {"timeframe": "30m", "role": "session_state", "minimum_bars": 4, "required_for_aplus": True},
    {"timeframe": "60m", "role": "structure_bias", "minimum_bars": 4, "required_for_aplus": True},
    {"timeframe": "4h", "role": "higher_timeframe_bias", "minimum_bars": 8, "required_for_aplus": False},
    {"timeframe": "1d", "role": "daily_regime", "minimum_bars": 20, "required_for_aplus": True},
    {"timeframe": "1w", "role": "major_structure", "minimum_bars": 8, "required_for_aplus": False},
)

# Maximum completed-bar lag versus the primary 5m data cut. These are
# freshness/causality gates, not performance parameters. Daily/weekly limits
# include ordinary weekends and market holidays.
TIMEFRAME_MAX_LAG_MINUTES: dict[str, int] = {
    "1m": 15,
    "5m": 15,
    "15m": 35,
    "30m": 65,
    "60m": 125,
    "4h": 2 * 24 * 60,
    "1d": 4 * 24 * 60,
    "1w": 14 * 24 * 60,
}


def _finite(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _normalize(rows: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    for row in rows:
        mapped = {
            "t": row.get("t") or row.get("timestamp"),
            "o": _finite(row.get("o") if "o" in row else row.get("open")),
            "h": _finite(row.get("h") if "h" in row else row.get("high")),
            "l": _finite(row.get("l") if "l" in row else row.get("low")),
            "c": _finite(row.get("c") if "c" in row else row.get("close")),
            "v": _finite(row.get("v") if "v" in row else row.get("volume")),
        }
        if all(mapped[key] is not None for key in ("o", "h", "l", "c", "v")):
            output.append(mapped)
    return output


def _round(value: float | None, digits: int = 4) -> float | None:
    return round(value, digits) if value is not None and math.isfinite(value) else None


def _true_ranges(rows: Sequence[Mapping[str, Any]]) -> list[float]:
    output: list[float] = []
    for index, row in enumerate(rows):
        high, low = float(row["h"]), float(row["l"])
        prior_close = float(rows[index - 1]["c"]) if index else float(row["o"])
        output.append(max(high - low, abs(high - prior_close), abs(low - prior_close)))
    return output


def _atr(rows: Sequence[Mapping[str, Any]], length: int = 14) -> float:
    ranges = _true_ranges(rows)
    values = ranges[-min(length, len(ranges)) :]
    return sum(values) / len(values) if values else 0.0


def _ema(values: Sequence[float], length: int) -> float:
    if not values:
        return 0.0
    alpha = 2.0 / (length + 1.0)
    result = float(values[0])
    for value in values[1:]:
        result = alpha * float(value) + (1.0 - alpha) * result
    return result


def _vwap(rows: Sequence[Mapping[str, Any]]) -> float | None:
    denominator = sum(max(0.0, float(row["v"])) for row in rows)
    if denominator <= 0:
        return None
    numerator = sum(((float(row["h"]) + float(row["l"]) + float(row["c"])) / 3.0) * max(0.0, float(row["v"])) for row in rows)
    return numerator / denominator


def confirmed_swings(
    bars: Sequence[Mapping[str, Any]], *, left: int = 2, right: int = 2
) -> list[dict[str, Any]]:
    """Return pivots only when the required right-hand bars have completed."""
    rows = _normalize(bars)
    if len(rows) < left + right + 1:
        return []
    output: list[dict[str, Any]] = []
    for position in range(left, len(rows) - right):
        high = float(rows[position]["h"])
        low = float(rows[position]["l"])
        window = rows[position - left : position + right + 1]
        if high == max(float(row["h"]) for row in window) and sum(float(row["h"]) == high for row in window) == 1:
            output.append({"kind": "high", "position": position, "confirmed_position": position + right, "price": high, "timestamp": rows[position]["t"], "causal": True})
        if low == min(float(row["l"]) for row in window) and sum(float(row["l"]) == low for row in window) == 1:
            output.append({"kind": "low", "position": position, "confirmed_position": position + right, "price": low, "timestamp": rows[position]["t"], "causal": True})
    return sorted(output, key=lambda row: (int(row["confirmed_position"]), int(row["position"]), str(row["kind"])))


def _trend(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    closes = [float(row["c"]) for row in rows]
    if len(closes) < 4:
        return {"bias": "neutral", "strength": 0.0}
    length = min(20, len(closes))
    segment = closes[-length:]
    x_mean = (length - 1) / 2.0
    y_mean = sum(segment) / length
    denominator = sum((index - x_mean) ** 2 for index in range(length))
    slope = sum((index - x_mean) * (value - y_mean) for index, value in enumerate(segment)) / denominator if denominator else 0.0
    atr = max(_atr(rows), max(abs(y_mean), 1.0) * 0.0005)
    normalized = slope * length / atr
    bias = "bullish" if normalized >= 0.8 else "bearish" if normalized <= -0.8 else "neutral"
    return {"bias": bias, "strength": _round(min(100.0, abs(normalized) * 25.0), 1), "slope_per_bar": _round(slope, 5)}


def _resample(rows: Sequence[Mapping[str, Any]], factor: int) -> list[dict[str, Any]]:
    # Anchor aggregation to the 09:30 ET equity session so bars never bridge
    # lunch-to-next-open or cross a session boundary.
    buckets: dict[tuple[Any, int], list[dict[str, Any]]] = {}
    unstamped = False
    for row in rows:
        stamp = _timestamp(row.get("t"))
        if stamp is None:
            unstamped = True
            break
        local = stamp.astimezone(MARKET_TZ)
        elapsed = local.hour * 60 + local.minute - (9 * 60 + 30)
        if 0 <= elapsed < 390:
            buckets.setdefault((local.date(), elapsed // (factor * 5)), []).append(dict(row))
    groups = [buckets[key] for key in sorted(buckets)] if not unstamped else [list(rows[start : start + factor]) for start in range(0, len(rows), factor)]
    output: list[dict[str, Any]] = []
    for group in groups:
        # Never manufacture a higher-timeframe signal from an unfinished bar.
        if len(group) < factor:
            continue
        output.append({
            "t": group[0].get("t"),
            "o": float(group[0]["o"]),
            "h": max(float(row["h"]) for row in group),
            "l": min(float(row["l"]) for row in group),
            "c": float(group[-1]["c"]),
            "v": sum(float(row["v"]) for row in group),
        })
    return output


def _canonical_timeframe(value: str) -> str:
    normalized = value.strip().lower()
    return {
        "1min": "1m",
        "5min": "5m",
        "15min": "15m",
        "30min": "30m",
        "1h": "60m",
        "60min": "60m",
        "4hour": "4h",
        "240min": "4h",
        "1day": "1d",
        "day": "1d",
        "1week": "1w",
        "week": "1w",
    }.get(normalized, normalized)


def _timeframe_rows(
    rows: Sequence[Mapping[str, Any]],
    higher_timeframes: Mapping[str, Sequence[Mapping[str, Any]]] | None,
) -> tuple[dict[str, list[dict[str, Any]]], dict[str, str]]:
    """Build causal role frames, preferring whichever completed source is fresher."""
    base = _normalize(rows)
    frames: dict[str, list[dict[str, Any]]] = {"5m": base}
    provenance: dict[str, str] = {"5m": "primary_completed_bars"}
    for timeframe, factor in (("15m", 3), ("30m", 6), ("60m", 12)):
        derived = _resample(base, factor)
        if derived:
            frames[timeframe] = derived
            provenance[timeframe] = "derived_from_completed_5m"

    for raw_name, raw_rows in (higher_timeframes or {}).items():
        name = _canonical_timeframe(str(raw_name))
        supplied = _normalize(raw_rows)
        if not supplied:
            continue
        current = frames.get(name) or []
        if not current:
            frames[name] = supplied[-120:]
            provenance[name] = "supplied_completed_bars"
            continue
        combined = {
            str(row.get("t") or f"untimed:{index}"): row
            for index, row in enumerate([*supplied, *current])
        }
        frames[name] = sorted(combined.values(), key=lambda row: str(row.get("t") or ""))[-120:]
        provenance[name] = "supplied_plus_derived_completed_5m"
    return frames, provenance


def _timeframe_coverage(
    rows: Sequence[Mapping[str, Any]],
    higher_timeframes: Mapping[str, Sequence[Mapping[str, Any]]] | None,
) -> dict[str, Any]:
    frames, provenance = _timeframe_rows(rows, higher_timeframes)
    report_rows: list[dict[str, Any]] = []
    missing_required: list[str] = []
    primary_rows = frames.get("5m") or []
    primary_cut = _timestamp(primary_rows[-1].get("t")) if primary_rows else None
    for spec in APLUS_TIMEFRAME_MATRIX:
        timeframe = str(spec["timeframe"])
        timeframe_rows = frames.get(timeframe) or []
        completed = len(timeframe_rows)
        minimum = int(spec["minimum_bars"])
        required = bool(spec["required_for_aplus"])
        last_completed = _timestamp(timeframe_rows[-1].get("t")) if timeframe_rows else None
        lag_minutes = (
            max(0.0, (primary_cut - last_completed).total_seconds() / 60.0)
            if primary_cut is not None and last_completed is not None
            else None
        )
        max_lag = TIMEFRAME_MAX_LAG_MINUTES.get(timeframe)
        stale = bool(
            completed >= minimum
            and lag_minutes is not None
            and max_lag is not None
            and lag_minutes > max_lag
            and "derived" not in provenance.get(timeframe, "")
        )
        if completed >= minimum and not stale:
            status = "available"
        elif stale and required:
            status = "required_stale"
            missing_required.append(timeframe)
        elif stale:
            status = "optional_stale"
        elif required:
            status = "required_missing" if completed == 0 else "required_insufficient_history"
            missing_required.append(timeframe)
        else:
            status = "optional_unavailable" if completed == 0 else "optional_insufficient_history"
        report_rows.append({
            **spec,
            "completed_bars": completed,
            "status": status,
            "provenance": provenance.get(timeframe, "unavailable"),
            "last_completed_bar_at": last_completed.isoformat().replace("+00:00", "Z") if last_completed else None,
            "lag_minutes_vs_primary": round(lag_minutes, 1) if lag_minutes is not None else None,
            "max_lag_minutes": max_lag,
        })
    return {
        "status": "complete_for_aplus_review" if not missing_required else "incomplete_for_aplus_review",
        "missing_required": missing_required,
        "frames": report_rows,
        "closed_bar_only": True,
        "execution_enabled": False,
        "can_submit_orders": False,
    }


def _timeframe_scan(
    rows: Sequence[Mapping[str, Any]],
    higher_timeframes: Mapping[str, Sequence[Mapping[str, Any]]] | None,
) -> list[dict[str, Any]]:
    """Run existing causal detectors on every available role frame.

    These observations are context-only.  They do not duplicate detections into
    the canonical 5m grade, which avoids accidental confluence inflation.
    """
    frames, provenance = _timeframe_rows(rows, higher_timeframes)
    roles = {str(row["timeframe"]): str(row["role"]) for row in APLUS_TIMEFRAME_MATRIX}
    output: list[dict[str, Any]] = []
    for timeframe in ("5m", "15m", "30m", "60m", "4h", "1d", "1w", "1m"):
        frame_rows = frames.get(timeframe) or []
        if not frame_rows:
            continue
        trend = _trend(frame_rows)
        positives: list[dict[str, Any]] = []
        negatives: list[dict[str, Any]] = []
        if len(frame_rows) >= MIN_BARS:
            atr = max(_atr(frame_rows), abs(float(frame_rows[-1]["c"])) * 0.0005)
            range_positive, range_negative = _range_events(frame_rows, atr)
            swing_positive, swing_negative = _swing_patterns(frame_rows, atr)
            continuation = _continuation_patterns(frame_rows, atr, trend)
            if timeframe in {"1d", "1w"}:
                continuation = [row for row in continuation if row["pattern_id"] != "vwap_reclaim_reject"]
            positives.extend(range_positive)
            positives.extend(swing_positive)
            positives.extend(continuation)
            positives.extend(_sweep_pattern(frame_rows, atr))
            positives.extend(_cbc_patterns(frame_rows))
            negatives.extend(range_negative)
            negatives.extend(swing_negative)
        annotated_positive = [{**row, "timeframe": timeframe} for row in positives]
        annotated_negative = [{**row, "timeframe": timeframe} for row in negatives]
        best = max(
            annotated_positive,
            key=lambda row: (row.get("trigger_state") == "confirmed", float(row.get("confidence_score") or 0.0)),
            default=None,
        )
        worst = max(annotated_negative, key=lambda row: float(row.get("confidence_score") or 0.0), default=None)
        output.append({
            "timeframe": timeframe,
            "role": roles.get(timeframe, "supplemental_context"),
            "completed_bars": len(frame_rows),
            "trend": trend,
            "best_setup": best,
            "worst_setup": worst,
            "source_label": f"completed_{timeframe}_bars",
            "provenance": provenance.get(timeframe, "unavailable"),
            "score_effect": "context_only_no_duplicate_confluence_credit",
            "closed_bar_only": True,
            "execution_enabled": False,
            "can_submit_orders": False,
        })
    return output


def _pattern(
    pattern_id: str,
    direction: str,
    confidence: float,
    trigger_state: str,
    reason: str,
    *,
    trigger: float | None = None,
    invalidation: float | None = None,
    reference_level: float | None = None,
) -> dict[str, Any]:
    spec = next(row for row in PATTERN_CATALOG if row["id"] == pattern_id)
    return {
        "pattern_id": pattern_id,
        "family": spec["family"],
        "complexity": spec["complexity"],
        "direction": direction,
        "confidence_score": _round(max(0.0, min(100.0, confidence)), 1),
        "trigger_state": trigger_state,
        "reason": reason,
        "trigger": _round(trigger),
        "invalidation": _round(invalidation),
        "reference_level": _round(reference_level),
        "closed_bar_only": True,
        "execution_enabled": False,
        "can_submit_orders": False,
    }


def _timestamp(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        parsed = value
    else:
        text = str(value or "").strip().replace("Z", "+00:00")
        if not text:
            return None
        try:
            parsed = datetime.fromisoformat(text)
        except ValueError:
            return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _cbc_patterns(rows: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Detect only the strict two-sided, completed-candle CBC flip."""
    if len(rows) < 2:
        return []
    prior, current = rows[-2], rows[-1]
    bullish = float(current["l"]) < float(prior["l"]) and float(current["c"]) > float(prior["h"])
    bearish = float(current["h"]) > float(prior["h"]) and float(current["c"]) < float(prior["l"])
    if bullish:
        pattern = _pattern(
            "cbc_strong_flip", "bullish", 86.0, "confirmed",
            "Completed candle swept the prior low and closed above the prior high; wait for fresh-quote and higher-timeframe review.",
            trigger=float(prior["h"]), invalidation=float(current["l"]), reference_level=float(prior["h"]),
        )
    elif bearish:
        pattern = _pattern(
            "cbc_strong_flip", "bearish", 86.0, "confirmed",
            "Completed candle swept the prior high and closed below the prior low; wait for fresh-quote and higher-timeframe review.",
            trigger=float(prior["l"]), invalidation=float(current["h"]), reference_level=float(prior["l"]),
        )
    else:
        return []
    pattern.update({
        "model_version": "cbc_strong_flip_v1",
        "claim_status": "mechanical_hypothesis_unvalidated",
        "historical_probability": {"status": "unavailable_pending_local_outcomes", "value": None},
        "source_label": "independent_completed_ohlcv_rules_from_public_cbc_description",
    })
    return [pattern]


def _level(
    level_id: str, label: str, price: float, side: str, source_label: str
) -> dict[str, Any]:
    return {
        "id": level_id,
        "label": label,
        "price": _round(price),
        "side": side,
        "source_label": source_label,
        "freshness": "completed_period",
        "historical_probability": {"status": "unavailable_pending_local_outcomes", "value": None},
        "execution_enabled": False,
        "can_submit_orders": False,
    }


def _derive_liquidity_levels(
    rows: Sequence[Mapping[str, Any]],
    higher_timeframes: Mapping[str, Sequence[Mapping[str, Any]]] | None,
) -> list[dict[str, Any]]:
    latest = _timestamp(rows[-1].get("t")) if rows else None
    if latest is None:
        return []
    current_local = latest.astimezone(MARKET_TZ)
    levels: list[dict[str, Any]] = []

    supplied = higher_timeframes or {}
    preferred = supplied.get("60m") or supplied.get("1h") or supplied.get("4h") or []
    completed_by_date: dict[Any, list[dict[str, Any]]] = {}
    for row in _normalize(preferred):
        stamp = _timestamp(row.get("t"))
        if stamp is not None:
            completed_by_date.setdefault(stamp.astimezone(MARKET_TZ).date(), []).append(row)
    prior_dates = sorted(day for day in completed_by_date if day < current_local.date())
    if prior_dates:
        prior_rows = completed_by_date[prior_dates[-1]]
        levels.extend([
            _level("pdh", "PDH", max(float(row["h"]) for row in prior_rows), "buy_side", "completed_prior_session_60m"),
            _level("pdl", "PDL", min(float(row["l"]) for row in prior_rows), "sell_side", "completed_prior_session_60m"),
        ])

        current_week = current_local.date().isocalendar()[:2]
        prior_week_keys = sorted({day.isocalendar()[:2] for day in prior_dates if day.isocalendar()[:2] < current_week})
        if prior_week_keys:
            week = prior_week_keys[-1]
            week_rows = [row for day, day_rows in completed_by_date.items() if day.isocalendar()[:2] == week for row in day_rows]
            levels.extend([
                _level("pwh", "PWH", max(float(row["h"]) for row in week_rows), "buy_side", "completed_prior_week_60m"),
                _level("pwl", "PWL", min(float(row["l"]) for row in week_rows), "sell_side", "completed_prior_week_60m"),
            ])

    daily_rows = _normalize(supplied.get("1d") or supplied.get("1Day") or [])
    if daily_rows:
        prior_close = float(daily_rows[-1]["c"])
        levels.append(
            _level(
                "prior_close",
                "Prior close",
                prior_close,
                "buy_side" if prior_close >= float(rows[-1]["c"]) else "sell_side",
                "latest_completed_daily_close",
            )
        )

    same_session = [
        row for row in rows
        if (stamp := _timestamp(row.get("t"))) is not None
        and stamp.astimezone(MARKET_TZ).date() == current_local.date()
    ]
    session_vwap = _vwap(same_session)
    if session_vwap is not None:
        levels.append(
            _level(
                "session_vwap",
                "VWAP",
                session_vwap,
                "buy_side" if session_vwap >= float(rows[-1]["c"]) else "sell_side",
                "completed_current_session_ohlcv_vwap",
            )
        )

    premarket_rows = [
        row for row in same_session
        if (stamp := _timestamp(row.get("t"))) is not None
        and wall_time(4, 0) <= stamp.astimezone(MARKET_TZ).time() < wall_time(9, 30)
    ]
    if premarket_rows and current_local.time() >= wall_time(9, 30):
        levels.extend([
            _level("pmh", "PMH", max(float(row["h"]) for row in premarket_rows), "buy_side", "completed_0400_0930_et_premarket"),
            _level("pml", "PML", min(float(row["l"]) for row in premarket_rows), "sell_side", "completed_0400_0930_et_premarket"),
        ])

    opening_rows: list[dict[str, Any]] = []
    for row in rows:
        stamp = _timestamp(row.get("t"))
        if stamp is None:
            continue
        local = stamp.astimezone(MARKET_TZ)
        if local.date() == current_local.date() and wall_time(9, 30) <= local.time() < wall_time(10, 0):
            opening_rows.append(dict(row))
    if opening_rows and current_local.time() >= wall_time(10, 0):
        levels.extend([
            _level("orh", "ORH", max(float(row["h"]) for row in opening_rows), "buy_side", "completed_0930_1000_et_opening_range"),
            _level("orl", "ORL", min(float(row["l"]) for row in opening_rows), "sell_side", "completed_0930_1000_et_opening_range"),
        ])
    return levels


def _liquidity_target_map(
    rows: Sequence[Mapping[str, Any]], levels: Sequence[Mapping[str, Any]]
) -> dict[str, Any]:
    if not rows:
        return {"current_price": None, "nearest_upside": None, "nearest_downside": None, "dealing_range": None}
    current = float(rows[-1]["c"])
    upside = [level for level in levels if float(level["price"]) > current]
    downside = [level for level in levels if float(level["price"]) < current]
    window = list(rows[-min(24, len(rows)) :])
    high = max(float(row["h"]) for row in window)
    low = min(float(row["l"]) for row in window)
    midpoint = (high + low) / 2.0
    tolerance = max((high - low) * 0.05, abs(current) * 0.0005)
    location = "equilibrium" if abs(current - midpoint) <= tolerance else "premium" if current > midpoint else "discount"

    def compact(level: Mapping[str, Any] | None) -> dict[str, Any] | None:
        if level is None:
            return None
        return {"id": level["id"], "label": level["label"], "price": level["price"], "source_label": level["source_label"]}

    return {
        "current_price": _round(current),
        "nearest_upside": compact(min(upside, key=lambda level: float(level["price"]), default=None)),
        "nearest_downside": compact(max(downside, key=lambda level: float(level["price"]), default=None)),
        "dealing_range": {
            "low": _round(low),
            "midpoint": _round(midpoint),
            "high": _round(high),
            "location": location,
            "source_label": "last_24_completed_5m_bars",
        },
    }


def _session_liquidity_patterns(
    rows: Sequence[Mapping[str, Any]], levels: Sequence[Mapping[str, Any]], atr: float
) -> list[dict[str, Any]]:
    if not rows or not levels:
        return []
    current = rows[-1]
    tolerance = max(atr * 0.04, abs(float(current["c"])) * 0.0001)
    output: list[dict[str, Any]] = []
    for level in levels:
        price = float(level["price"])
        if level["side"] == "buy_side":
            confirmed = float(current["h"]) > price + tolerance and float(current["c"]) < price
            direction, trigger, invalidation = "bearish", float(current["l"]), float(current["h"])
        else:
            confirmed = float(current["l"]) < price - tolerance and float(current["c"]) > price
            direction, trigger, invalidation = "bullish", float(current["h"]), float(current["l"])
        if not confirmed:
            continue
        pattern = _pattern(
            "session_liquidity_sweep_reclaim", direction, 88.0, "confirmed",
            f"Completed candle swept {level['label']} and closed back through the causal level.",
            trigger=trigger, invalidation=invalidation, reference_level=price,
        )
        pattern.update({
            "level_id": level["id"],
            "level_label": level["label"],
            "level_source": level["source_label"],
            "claim_status": "mechanical_hypothesis_unvalidated",
            "historical_probability": {"status": "unavailable_pending_local_outcomes", "value": None},
        })
        output.append(pattern)
    return output


def _participation_context(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    base = {
        "method": "ohlcv_participation_curvature_proxy_v1",
        "true_order_flow": False,
        "probability": {"status": "unavailable_pending_local_outcomes", "value": None},
        "source_labels": ["completed_ohlcv_proxy", "not_true_order_flow"],
        "execution_enabled": False,
        "can_submit_orders": False,
    }
    if len(rows) < 8:
        return {**base, "status": "unavailable", "direction": "neutral", "score": None, "reason": "Need at least eight completed bars."}
    flows: list[float] = []
    for row in rows[-8:]:
        span = max(float(row["h"]) - float(row["l"]), abs(float(row["c"])) * 0.0001)
        control = max(-1.0, min(1.0, (float(row["c"]) - float(row["o"])) / span))
        flows.append(control * max(0.0, float(row["v"])) * float(row["c"]))
    scale = median(abs(value) for value in flows) or 1.0
    prior_slope = (sum(flows[3:5]) / 2.0 - sum(flows[0:3]) / 3.0) / scale
    recent_slope = (sum(flows[6:8]) / 2.0 - sum(flows[3:6]) / 3.0) / scale
    curvature = max(-3.0, min(3.0, recent_slope - prior_slope))
    score = min(100.0, abs(curvature) / 3.0 * 100.0)
    if curvature >= 0.35:
        status, direction = "buy_pressure_accelerating", "bullish"
    elif curvature <= -0.35:
        status, direction = "sell_pressure_accelerating", "bearish"
    else:
        status, direction = "neutral_or_mixed", "neutral"
    return {
        **base,
        "status": status,
        "direction": direction,
        "score": _round(score, 1),
        "curvature_proxy": _round(curvature, 3),
        "reason": "Signed completed-bar dollar-volume curvature; contextual proxy only, not bid/ask-classified order flow.",
    }


def _smt_divergence_context(
    rows: Sequence[Mapping[str, Any]],
    correlated_bars: Mapping[str, Sequence[Mapping[str, Any]]] | None,
) -> dict[str, Any]:
    """Compare completed correlated bars for asymmetric high/low sweeps.

    This is deliberately named a price-divergence proxy. It is not true order
    flow and it has no score effect until local outcomes validate it.
    """
    base = {
        "method": "paired_index_completed_bar_price_divergence_v1",
        "true_order_flow": False,
        "score_effect": "none_until_local_validation",
        "probability": {"status": "unavailable_pending_local_outcomes", "value": None},
        "source_labels": ["completed_5m_correlated_price_bars", "not_true_order_flow"],
        "execution_enabled": False,
        "can_submit_orders": False,
    }
    primary = _normalize(rows)
    peers = [(str(symbol).upper(), _normalize(peer_rows)) for symbol, peer_rows in (correlated_bars or {}).items()]
    peers = [(symbol, peer_rows) for symbol, peer_rows in peers if len(peer_rows) >= 8]
    if len(primary) < 8 or not peers:
        return {
            **base,
            "status": "unavailable_without_correlated_completed_bars",
            "direction": "neutral",
            "peer_symbol": None,
            "divergence": None,
            "reason": "Need at least eight completed bars for both correlated instruments.",
        }
    peer_symbol, peer = peers[0]
    primary = primary[-8:]
    peer = peer[-8:]
    primary_high = float(primary[-1]["h"]) > max(float(row["h"]) for row in primary[:-1])
    peer_high = float(peer[-1]["h"]) > max(float(row["h"]) for row in peer[:-1])
    primary_low = float(primary[-1]["l"]) < min(float(row["l"]) for row in primary[:-1])
    peer_low = float(peer[-1]["l"]) < min(float(row["l"]) for row in peer[:-1])
    high_divergence = primary_high != peer_high
    low_divergence = primary_low != peer_low
    if high_divergence and low_divergence:
        status, direction, divergence = "conflicting_divergence", "neutral", "both_high_and_low_asymmetry"
    elif high_divergence:
        status, direction, divergence = "divergence_observed", "bearish", "asymmetric_buy_side_sweep"
    elif low_divergence:
        status, direction, divergence = "divergence_observed", "bullish", "asymmetric_sell_side_sweep"
    else:
        status, direction, divergence = "no_divergence", "neutral", None
    return {
        **base,
        "status": status,
        "direction": direction,
        "peer_symbol": peer_symbol,
        "divergence": divergence,
        "legs": {
            "primary_took_prior_high": primary_high,
            "peer_took_prior_high": peer_high,
            "primary_took_prior_low": primary_low,
            "peer_took_prior_low": peer_low,
        },
        "reason": (
            "One correlated instrument swept a completed-bar extreme while the other did not."
            if status == "divergence_observed"
            else "No single-sided paired-index sweep is currently confirmed."
        ),
    }


def _clc_entry_context(
    *,
    rows: Sequence[Mapping[str, Any]],
    direction: str,
    best: Mapping[str, Any] | None,
    alignment: Mapping[str, Any],
    entry_plan: Mapping[str, Any],
    target_map: Mapping[str, Any],
    participation: Mapping[str, Any],
    smt: Mapping[str, Any],
    blockers: Sequence[str],
) -> dict[str, Any]:
    frames = alignment.get("frames") if isinstance(alignment.get("frames"), Mapping) else {}
    context_frames = {
        name: str((frames.get(name) or {}).get("bias") or "unavailable")
        for name in ("60m", "4h", "1d")
    }
    context_complete = all(value == direction for value in context_frames.values())
    current = _finite(target_map.get("current_price"))
    zone = entry_plan.get("entry_zone") if isinstance(entry_plan.get("entry_zone"), Mapping) else {}
    zone_low, zone_high = _finite(zone.get("low")), _finite(zone.get("high"))
    in_zone = bool(current is not None and zone_low is not None and zone_high is not None and zone_low <= current <= zone_high)
    reference_level = _finite((best or {}).get("reference_level"))
    location_complete = bool(in_zone or reference_level is not None)
    trigger_complete = bool(best and best.get("trigger_state") == "confirmed")
    quality_complete = not any(value in blockers for value in ("stale_quote", "spread_too_wide_or_missing"))
    confirmation_complete = trigger_complete and quality_complete

    if blockers:
        status = "blocked"
        next_required = f"Clear blocker: {str(blockers[0]).replace('_', ' ')}."
    elif not context_complete:
        status = "waiting_context"
        missing = [name for name, value in context_frames.items() if value != direction]
        next_required = f"Wait for completed {'/'.join(missing)} bias to align {direction}."
    elif not location_complete:
        status = "waiting_location"
        next_required = "Wait for price to reach the objective entry zone or a sourced reference level."
    elif not confirmation_complete:
        status = "waiting_confirmation"
        next_required = "Wait for the completed 5m trigger, then recheck quote freshness and spread."
    else:
        status = "manual_review_ready"
        next_required = "All CLC observations are present; Kenny still decides whether to act manually."

    sequence = [
        {"step": 1, "name": "context", "status": "complete" if context_complete else "pending", "requirement": "60m, 4H, and daily completed-bar bias agree."},
        {"step": 2, "name": "location", "status": "complete" if location_complete else "pending", "requirement": "Price is at objective trigger geometry or a sourced market level."},
        {"step": 3, "name": "confirmation", "status": "complete" if confirmation_complete else "pending", "requirement": "Completed 5m trigger plus fresh, tradeable quote; 1m may refine but never originate."},
    ]
    return {
        "status": status,
        "direction": direction,
        "next_required": next_required,
        "context": {"status": "complete" if context_complete else "pending", "frames": context_frames, "reason": "Higher-timeframe bias from completed bars only."},
        "location": {
            "status": "complete" if location_complete else "pending",
            "current_price": current,
            "entry_zone": {"low": zone_low, "high": zone_high},
            "reference_level": reference_level,
            "dealing_range": target_map.get("dealing_range"),
            "nearest_upside": target_map.get("nearest_upside"),
            "nearest_downside": target_map.get("nearest_downside"),
        },
        "confirmation": {
            "status": "complete" if confirmation_complete else "pending",
            "completed_bar_trigger": trigger_complete,
            "quote_quality": "pass" if quality_complete else "fail",
            "participation_proxy": participation.get("status"),
            "smt_proxy": smt.get("status"),
            "true_order_flow": "unavailable_without_tick_or_mbo",
            "sequence": sequence,
        },
        "source_labels": ["clc_completed_bar_contract_v1", "objective_level_map_v1", "paired_index_price_divergence_v1"],
        "score_effect": "none_separate_gate_only",
        "execution_enabled": False,
        "can_submit_orders": False,
    }


def _macro_context(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    stamp = _timestamp(rows[-1].get("t")) if rows else None
    windows = (
        ("ny_am_0850_0910", wall_time(8, 50), wall_time(9, 10), "NY AM 08:50–09:10 ET"),
        ("ny_am_0950_1010", wall_time(9, 50), wall_time(10, 10), "NY AM 09:50–10:10 ET"),
        ("ny_am_1050_1110", wall_time(10, 50), wall_time(11, 10), "NY AM 10:50–11:10 ET"),
        ("ny_am_1150_1210", wall_time(11, 50), wall_time(12, 10), "NY AM 11:50–12:10 ET"),
    )
    active = None
    if stamp is not None:
        current = stamp.astimezone(MARKET_TZ).time()
        active = next((row for row in windows if row[1] <= current <= row[2]), None)
    return {
        "status": "context_only_unvalidated",
        "active_window": active[0] if active else None,
        "active": active is not None,
        "label": active[3] if active else "Outside tracked NY AM macro windows",
        "source_label": "public_ict_macro_schedule_context",
        "score_effect": "none_until_validated",
        "execution_enabled": False,
        "can_submit_orders": False,
    }


def _strat_scenario(prior: Mapping[str, Any], current: Mapping[str, Any]) -> str:
    took_high = float(current["h"]) > float(prior["h"])
    took_low = float(current["l"]) < float(prior["l"])
    if took_high and took_low:
        return "3"
    if took_high:
        return "2u"
    if took_low:
        return "2d"
    return "1"


def _strat_context(
    rows: Sequence[Mapping[str, Any]],
    higher_timeframes: Mapping[str, Sequence[Mapping[str, Any]]] | None,
    liquidity_levels: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    """Describe completed-bar STRAT scenarios without treating them as edge."""
    base = {
        "probability": {"status": "unavailable_pending_local_outcomes", "value": None},
        "score_effect": "none_until_local_validation",
        "source_labels": ["completed_ohlcv_strat_scenarios_v1", "public_strat_framework_description"],
        "closed_bar_only": True,
        "execution_enabled": False,
        "can_submit_orders": False,
    }
    if len(rows) < 2:
        return {
            **base,
            "status": "unavailable_insufficient_completed_bars",
            "current_scenario": None,
            "sequence": [],
            "ftfc": {"state": "unavailable", "strict": False, "frame_count": 0, "frames": {}},
            "magnitude": {"direction": "neutral", "target_label": None, "target": None},
        }

    sequence = [_strat_scenario(rows[index - 1], rows[index]) for index in range(1, len(rows))][-4:]
    frame_rows: dict[str, list[dict[str, Any]]] = {"5m": [dict(row) for row in rows]}
    for name, supplied_rows in (higher_timeframes or {}).items():
        normalized = _normalize(supplied_rows)
        if normalized:
            frame_rows[str(name)] = normalized

    frames: dict[str, str] = {}
    for name, values in frame_rows.items():
        latest = values[-1]
        close, open_price = float(latest["c"]), float(latest["o"])
        frames[name] = "bullish" if close > open_price else "bearish" if close < open_price else "neutral"
    directional = [value for value in frames.values() if value != "neutral"]
    strict = len(directional) >= 4 and len(directional) == len(frames) and len(set(directional)) == 1
    ftfc_state = directional[0] if strict else "incomplete" if len(directional) < 4 else "conflict"

    current_scenario = sequence[-1]
    direction = "bullish" if current_scenario == "2u" else "bearish" if current_scenario == "2d" else "neutral"
    current_price = float(rows[-1]["c"])
    if direction == "bullish":
        targets = [level for level in liquidity_levels if float(level["price"]) > current_price]
        target = min(targets, key=lambda level: float(level["price"]), default=None)
    elif direction == "bearish":
        targets = [level for level in liquidity_levels if float(level["price"]) < current_price]
        target = max(targets, key=lambda level: float(level["price"]), default=None)
    else:
        target = None
    return {
        **base,
        "status": "context_available",
        "current_scenario": current_scenario,
        "sequence": sequence,
        "ftfc": {"state": ftfc_state, "strict": strict, "frame_count": len(frames), "frames": frames},
        "magnitude": {
            "direction": direction,
            "target_label": target.get("label") if target else None,
            "target": _round(float(target["price"])) if target else None,
        },
    }


def _ny_0800_0900_range_context(
    rows: Sequence[Mapping[str, Any]], cisd_patterns: Sequence[Mapping[str, Any]]
) -> dict[str, Any]:
    """Track the NY 08:00-09:00 ET balance range and later causal events."""
    base = {
        "historical_probability": {"status": "unavailable_pending_local_outcomes", "value": None},
        "external_claim_status": "excluded_until_independently_reproduced",
        "source_labels": ["completed_0800_0900_et_bars", "ict_cisd_sequence_v1"],
        "closed_bar_only": True,
        "score_effect": "none_until_local_validation",
        "execution_enabled": False,
        "can_submit_orders": False,
    }
    stamped = [(row, _timestamp(row.get("t"))) for row in rows]
    stamped = [(row, stamp) for row, stamp in stamped if stamp is not None]
    if not stamped:
        return {**base, "status": "unavailable_missing_timestamps", "range": None, "first_sweep": None, "cisd": None, "target": None}
    latest_local = stamped[-1][1].astimezone(MARKET_TZ)
    range_rows = [
        row for row, stamp in stamped
        if stamp.astimezone(MARKET_TZ).date() == latest_local.date()
        and wall_time(8, 0) <= stamp.astimezone(MARKET_TZ).time() < wall_time(9, 0)
    ]
    if latest_local.time() < wall_time(9, 0) or not range_rows:
        return {**base, "status": "unavailable_range_not_complete", "range": None, "first_sweep": None, "cisd": None, "target": None}
    range_high = max(float(row["h"]) for row in range_rows)
    range_low = min(float(row["l"]) for row in range_rows)
    later = [
        (row, stamp) for row, stamp in stamped
        if stamp.astimezone(MARKET_TZ).date() == latest_local.date()
        and stamp.astimezone(MARKET_TZ).time() >= wall_time(9, 0)
    ]
    first_sweep: dict[str, Any] | None = None
    for row, stamp in later:
        took_high = float(row["h"]) > range_high
        took_low = float(row["l"]) < range_low
        if not (took_high or took_low):
            continue
        side = "both_sides_same_bar" if took_high and took_low else "buy_side" if took_high else "sell_side"
        first_sweep = {"side": side, "timestamp": stamp.isoformat().replace("+00:00", "Z")}
        break

    expected_direction = None
    if first_sweep and first_sweep["side"] == "buy_side":
        expected_direction = "bearish"
    elif first_sweep and first_sweep["side"] == "sell_side":
        expected_direction = "bullish"
    sweep_timestamp = _timestamp(first_sweep.get("timestamp")) if first_sweep else None

    def _confirmed_after_sweep(pattern: Mapping[str, Any]) -> bool:
        if pattern.get("trigger_state") != "confirmed" or pattern.get("direction") != expected_direction:
            return False
        stages = pattern.get("model_sequence", {}).get("stages", [])
        cisd_stage = next((stage for stage in stages if stage.get("name") == "cisd"), {})
        confirmation_timestamp = _timestamp(cisd_stage.get("timestamp"))
        return sweep_timestamp is not None and confirmation_timestamp is not None and confirmation_timestamp >= sweep_timestamp

    confirmed = next(
        (pattern for pattern in cisd_patterns if _confirmed_after_sweep(pattern)),
        None,
    )
    status = "range_complete_waiting_sweep" if first_sweep is None else "sweep_observed_waiting_cisd" if confirmed is None else "cisd_confirmed_after_sweep"
    target = range_low if expected_direction == "bearish" else range_high if expected_direction == "bullish" else None
    return {
        **base,
        "status": status,
        "range": {"high": _round(range_high), "low": _round(range_low), "bar_count": len(range_rows)},
        "first_sweep": first_sweep,
        "cisd": ({"direction": confirmed.get("direction"), "confirmed": True} if confirmed else {"direction": expected_direction, "confirmed": False}),
        "target": _round(target),
    }


def _range_events(rows: Sequence[Mapping[str, Any]], atr: float) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    positives: list[dict[str, Any]] = []
    negatives: list[dict[str, Any]] = []
    if len(rows) < 11:
        return positives, negatives
    base = rows[-11:-3]
    break_bar, retest_bar, confirm_bar = rows[-3], rows[-2], rows[-1]
    resistance = max(float(row["h"]) for row in base)
    support = min(float(row["l"]) for row in base)
    tolerance = max(atr * 0.32, float(confirm_bar["c"]) * 0.0008)
    break_buffer = max(atr * 0.08, float(confirm_bar["c"]) * 0.0003)
    average_volume = median(float(row["v"]) for row in base)
    breakout_volume = float(break_bar["v"]) / average_volume if average_volume > 0 else 0.0

    broke_up = float(break_bar["c"]) > resistance + break_buffer
    broke_down = float(break_bar["c"]) < support - break_buffer
    if broke_up:
        failed = float(confirm_bar["c"]) < resistance - tolerance
        retested = float(retest_bar["l"]) <= resistance + tolerance and float(retest_bar["c"]) >= resistance - tolerance
        confirmed = retested and float(confirm_bar["c"]) > resistance and float(confirm_bar["c"]) > float(confirm_bar["o"])
        if failed:
            negatives.append(_pattern("failed_breakout_trap", "bearish", 98, "confirmed", "Upside range break closed back beneath resistance.", trigger=float(confirm_bar["c"]), invalidation=float(break_bar["h"]), reference_level=resistance))
        elif confirmed:
            positives.append(_pattern("range_break_retest", "bullish", 88 + min(8, max(0, breakout_volume - 1) * 8), "confirmed", "Upside range break retested the prior ceiling and closed back above it.", trigger=max(float(confirm_bar["h"]), resistance + break_buffer), invalidation=min(float(retest_bar["l"]), resistance - tolerance), reference_level=resistance))
        elif float(confirm_bar["c"]) > resistance:
            positives.append(_pattern("range_break_retest", "bullish", 67, "waiting_retest", "Range break is valid but the retest-and-hold sequence is incomplete.", trigger=float(confirm_bar["h"]), invalidation=resistance - tolerance, reference_level=resistance))
        if breakout_volume < 1.2:
            negatives.append(_pattern("weak_breakout_no_participation", "bearish", 62, "confirmed", "Upside range break occurred without 1.2x local volume.", reference_level=resistance))
    if broke_down:
        failed = float(confirm_bar["c"]) > support + tolerance
        retested = float(retest_bar["h"]) >= support - tolerance and float(retest_bar["c"]) <= support + tolerance
        confirmed = retested and float(confirm_bar["c"]) < support and float(confirm_bar["c"]) < float(confirm_bar["o"])
        if failed:
            negatives.append(_pattern("failed_breakout_trap", "bullish", 98, "confirmed", "Downside range break closed back above support.", trigger=float(confirm_bar["c"]), invalidation=float(break_bar["l"]), reference_level=support))
        elif confirmed:
            positives.append(_pattern("range_break_retest", "bearish", 88 + min(8, max(0, breakout_volume - 1) * 8), "confirmed", "Downside range break retested the prior floor and closed back below it.", trigger=min(float(confirm_bar["l"]), support - break_buffer), invalidation=max(float(retest_bar["h"]), support + tolerance), reference_level=support))
        elif float(confirm_bar["c"]) < support:
            positives.append(_pattern("range_break_retest", "bearish", 67, "waiting_retest", "Range breakdown is valid but the retest-and-reject sequence is incomplete.", trigger=float(confirm_bar["l"]), invalidation=support + tolerance, reference_level=support))
        if breakout_volume < 1.2:
            negatives.append(_pattern("weak_breakout_no_participation", "bullish", 62, "confirmed", "Downside range break occurred without 1.2x local volume.", reference_level=support))
    return positives, negatives


def _swing_patterns(rows: Sequence[Mapping[str, Any]], atr: float) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    positives: list[dict[str, Any]] = []
    negatives: list[dict[str, Any]] = []
    swings = confirmed_swings(rows, left=2, right=2)
    highs = [row for row in swings if row["kind"] == "high"]
    lows = [row for row in swings if row["kind"] == "low"]
    last_close = float(rows[-1]["c"])
    tolerance = max(atr * 0.55, last_close * 0.003)

    last_bar = rows[-1]
    if highs:
        level = float(highs[-1]["price"])
        if float(last_bar["h"]) >= level - atr * 0.2 and float(last_bar["c"]) < level and float(last_bar["c"]) < float(last_bar["o"]):
            positives.append(_pattern("support_resistance_rejection", "bearish", 72, "confirmed", "Completed bar rejected a causally confirmed swing-high resistance level.", trigger=float(last_bar["l"]), invalidation=max(float(last_bar["h"]), level + atr * 0.15), reference_level=level))
    if lows:
        level = float(lows[-1]["price"])
        if float(last_bar["l"]) <= level + atr * 0.2 and float(last_bar["c"]) > level and float(last_bar["c"]) > float(last_bar["o"]):
            positives.append(_pattern("support_resistance_rejection", "bullish", 72, "confirmed", "Completed bar rejected a causally confirmed swing-low support level.", trigger=float(last_bar["h"]), invalidation=min(float(last_bar["l"]), level - atr * 0.15), reference_level=level))

    if len(highs) >= 2:
        first, second = highs[-2:]
        between = [row for row in lows if int(first["position"]) < int(row["position"]) < int(second["position"])]
        if abs(float(first["price"]) - float(second["price"])) <= tolerance and between:
            neckline = min(float(row["price"]) for row in between)
            state = "confirmed" if last_close < neckline else "waiting_neckline"
            positives.append(_pattern("double_top_bottom", "bearish", 86 if state == "confirmed" else 66, state, "Two confirmed highs are within tolerance; bearish confirmation requires a neckline close.", trigger=neckline, invalidation=max(float(first["price"]), float(second["price"])), reference_level=neckline))
    if len(lows) >= 2:
        first, second = lows[-2:]
        between = [row for row in highs if int(first["position"]) < int(row["position"]) < int(second["position"])]
        if abs(float(first["price"]) - float(second["price"])) <= tolerance and between:
            neckline = max(float(row["price"]) for row in between)
            state = "confirmed" if last_close > neckline else "waiting_neckline"
            positives.append(_pattern("double_top_bottom", "bullish", 86 if state == "confirmed" else 66, state, "Two confirmed lows are within tolerance; bullish confirmation requires a neckline close.", trigger=neckline, invalidation=min(float(first["price"]), float(second["price"])), reference_level=neckline))

    if len(highs) >= 3:
        left, head, right = highs[-3:]
        shoulders_match = abs(float(left["price"]) - float(right["price"])) <= tolerance
        head_clear = float(head["price"]) >= max(float(left["price"]), float(right["price"])) + atr * 0.35
        neck_lows = [row for row in lows if int(left["position"]) < int(row["position"]) < int(right["position"])]
        if shoulders_match and head_clear and len(neck_lows) >= 2:
            neckline = sum(float(row["price"]) for row in neck_lows[-2:]) / 2
            state = "confirmed" if last_close < neckline else "waiting_neckline"
            positives.append(_pattern("head_and_shoulders", "bearish", 90 if state == "confirmed" else 69, state, "Confirmed left shoulder, higher head, matching right shoulder, and neckline test.", trigger=neckline, invalidation=float(right["price"]), reference_level=neckline))
    if len(lows) >= 3:
        left, head, right = lows[-3:]
        shoulders_match = abs(float(left["price"]) - float(right["price"])) <= tolerance
        head_clear = float(head["price"]) <= min(float(left["price"]), float(right["price"])) - atr * 0.35
        neck_highs = [row for row in highs if int(left["position"]) < int(row["position"]) < int(right["position"])]
        if shoulders_match and head_clear and len(neck_highs) >= 2:
            neckline = sum(float(row["price"]) for row in neck_highs[-2:]) / 2
            state = "confirmed" if last_close > neckline else "waiting_neckline"
            positives.append(_pattern("head_and_shoulders", "bullish", 90 if state == "confirmed" else 69, state, "Confirmed inverse shoulders, lower head, and neckline test.", trigger=neckline, invalidation=float(right["price"]), reference_level=neckline))
    return positives, negatives


def _continuation_patterns(rows: Sequence[Mapping[str, Any]], atr: float, trend: Mapping[str, Any]) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    if len(rows) < 8 or atr <= 0:
        return output
    closes = [float(row["c"]) for row in rows]
    ema = _ema(closes, min(10, len(closes)))
    last, prior = rows[-1], rows[-2]
    if trend["bias"] == "bullish" and float(prior["l"]) <= ema + atr * 0.35 and float(last["c"]) > ema and float(last["c"]) > float(last["o"]):
        output.append(_pattern("trend_pullback", "bullish", 78, "confirmed", "Bull trend made a controlled EMA-area pullback and closed back upward.", trigger=float(last["h"]), invalidation=min(float(prior["l"]), ema - atr * 0.25), reference_level=ema))
    elif trend["bias"] == "bearish" and float(prior["h"]) >= ema - atr * 0.35 and float(last["c"]) < ema and float(last["c"]) < float(last["o"]):
        output.append(_pattern("trend_pullback", "bearish", 78, "confirmed", "Bear trend made a controlled EMA-area pullback and closed back downward.", trigger=float(last["l"]), invalidation=max(float(prior["h"]), ema + atr * 0.25), reference_level=ema))

    vwap = _vwap(rows)
    if vwap is not None and float(prior["c"]) <= vwap < float(last["c"]) and float(last["c"]) > float(last["o"]):
        output.append(_pattern("vwap_reclaim_reject", "bullish", 74, "confirmed", "Completed bar reclaimed session VWAP.", trigger=float(last["h"]), invalidation=min(float(last["l"]), vwap - atr * 0.2), reference_level=vwap))
    elif vwap is not None and float(prior["c"]) >= vwap > float(last["c"]) and float(last["c"]) < float(last["o"]):
        output.append(_pattern("vwap_reclaim_reject", "bearish", 74, "confirmed", "Completed bar rejected session VWAP.", trigger=float(last["l"]), invalidation=max(float(last["h"]), vwap + atr * 0.2), reference_level=vwap))

    if len(rows) >= 12:
        recent_ranges = [float(row["h"]) - float(row["l"]) for row in rows[-7:-1]]
        prior_ranges = [float(row["h"]) - float(row["l"]) for row in rows[-12:-7]]
        compressed = median(recent_ranges) <= median(prior_ranges) * 0.72 if prior_ranges else False
        ceiling = max(float(row["h"]) for row in rows[-7:-1])
        floor = min(float(row["l"]) for row in rows[-7:-1])
        base_volume = median(float(row["v"]) for row in rows[-7:-1])
        volume_expansion = float(last["v"]) >= base_volume * 1.25 if base_volume > 0 else False
        if compressed and volume_expansion and float(last["c"]) > ceiling:
            output.append(_pattern("compression_breakout", "bullish", 84, "confirmed", "Contracting ranges expanded above the compression ceiling with volume.", trigger=float(last["h"]), invalidation=floor, reference_level=ceiling))
        elif compressed and volume_expansion and float(last["c"]) < floor:
            output.append(_pattern("compression_breakout", "bearish", 84, "confirmed", "Contracting ranges expanded below the compression floor with volume.", trigger=float(last["l"]), invalidation=ceiling, reference_level=floor))

    if len(rows) >= 10:
        pole = float(rows[-6]["c"]) - float(rows[-10]["c"])
        flag = float(rows[-2]["c"]) - float(rows[-6]["c"])
        if pole >= atr * 2.0 and -abs(pole) * 0.55 <= flag <= 0 and float(last["c"]) > max(float(row["h"]) for row in rows[-5:-1]):
            output.append(_pattern("flag_continuation", "bullish", 82, "confirmed", "Bullish impulse, shallow countertrend flag, and resumption close.", trigger=float(last["h"]), invalidation=min(float(row["l"]) for row in rows[-5:]), reference_level=float(rows[-6]["c"])))
        elif pole <= -atr * 2.0 and 0 <= flag <= abs(pole) * 0.55 and float(last["c"]) < min(float(row["l"]) for row in rows[-5:-1]):
            output.append(_pattern("flag_continuation", "bearish", 82, "confirmed", "Bearish impulse, shallow countertrend flag, and resumption close.", trigger=float(last["l"]), invalidation=max(float(row["h"]) for row in rows[-5:]), reference_level=float(rows[-6]["c"])))
    return output


def _sweep_pattern(rows: Sequence[Mapping[str, Any]], atr: float) -> list[dict[str, Any]]:
    if len(rows) < 8:
        return []
    base = rows[-8:-3]
    sweep, displacement, hold = rows[-3], rows[-2], rows[-1]
    prior_low = min(float(row["l"]) for row in base)
    prior_high = max(float(row["h"]) for row in base)
    tolerance = max(atr * 0.2, float(hold["c"]) * 0.0005)
    output: list[dict[str, Any]] = []
    if float(sweep["l"]) < prior_low - tolerance and float(sweep["c"]) > prior_low and float(displacement["c"]) > float(sweep["h"]) and float(hold["l"]) >= prior_low - tolerance:
        output.append(_pattern("liquidity_sweep_mss_retest", "bullish", 92, "confirmed", "Sell-side sweep reclaimed the level, displaced above local structure, and held the retest.", trigger=float(hold["h"]), invalidation=float(sweep["l"]), reference_level=prior_low))
    elif float(sweep["h"]) > prior_high + tolerance and float(sweep["c"]) < prior_high and float(displacement["c"]) < float(sweep["l"]) and float(hold["h"]) <= prior_high + tolerance:
        output.append(_pattern("liquidity_sweep_mss_retest", "bearish", 92, "confirmed", "Buy-side sweep rejected the level, displaced below local structure, and held the retest.", trigger=float(hold["l"]), invalidation=float(sweep["h"]), reference_level=prior_high))
    return output


def _fvg_events(rows: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Return mechanically observable three-candle gaps from completed bars."""
    output: list[dict[str, Any]] = []
    for position in range(2, len(rows)):
        first, third = rows[position - 2], rows[position]
        if float(third["l"]) > float(first["h"]):
            output.append({
                "direction": "bullish",
                "position": position,
                "lower": float(first["h"]),
                "upper": float(third["l"]),
                "third_candle_low": float(third["l"]),
                "third_candle_high": float(third["h"]),
                "timestamp": third.get("t"),
            })
        elif float(third["h"]) < float(first["l"]):
            output.append({
                "direction": "bearish",
                "position": position,
                "lower": float(third["h"]),
                "upper": float(first["l"]),
                "third_candle_low": float(third["l"]),
                "third_candle_high": float(third["h"]),
                "timestamp": third.get("t"),
            })
    return output


def _cisd_event(
    rows: Sequence[Mapping[str, Any]], direction: str, *, after_position: int
) -> dict[str, Any] | None:
    """Find the first body close through the opposing delivery leg's open."""
    opposing = (
        (lambda row: float(row["c"]) < float(row["o"]))
        if direction == "bullish"
        else (lambda row: float(row["c"]) > float(row["o"]))
    )
    opposing_positions = [
        position for position in range(0, max(0, len(rows) - 1)) if opposing(rows[position])
    ]
    if not opposing_positions:
        return None
    eligible_positions = [position for position in opposing_positions if position < after_position]
    if not eligible_positions:
        return None
    leg_end = eligible_positions[-1]
    leg_start = leg_end
    while leg_start > 0 and opposing(rows[leg_start - 1]):
        leg_start -= 1
    anchor = float(rows[leg_start]["o"])
    for position in range(max(after_position + 1, leg_end + 1), len(rows)):
        close = float(rows[position]["c"])
        confirmed = close > anchor if direction == "bullish" else close < anchor
        if confirmed:
            return {
                "position": position,
                "timestamp": rows[position].get("t"),
                "anchor": anchor,
                "leg_start": leg_start,
                "leg_end": leg_end,
                "close": close,
            }
    return {"position": None, "timestamp": None, "anchor": anchor, "leg_start": leg_start, "leg_end": leg_end, "close": float(rows[-1]["c"])}


def detect_cisd_universal_model(
    bars: Sequence[Mapping[str, Any]],
    *,
    higher_timeframes: Mapping[str, Sequence[Mapping[str, Any]]] | None = None,
) -> list[dict[str, Any]]:
    """Detect an independently specified, causal CISD sequence.

    This is not a reproduction of any protected indicator.  It converts the
    publicly described sequence into falsifiable OHLC rules and deliberately
    makes no win-rate claim until local forward outcomes qualify it.
    """
    rows = _normalize(bars)
    if len(rows) < 6 or not higher_timeframes:
        return []
    atr = max(_atr(rows), abs(float(rows[-1]["c"])) * 0.0005)
    tolerance = max(atr * 0.08, abs(float(rows[-1]["c"])) * 0.0002)
    ltf_fvgs = _fvg_events(rows)
    output: list[dict[str, Any]] = []
    mapped_execution = {"15m": "1m", "30m": "3m", "60m": "5m", "1h": "5m", "4h": "15m"}

    for direction in ("bullish", "bearish"):
        contexts: list[dict[str, Any]] = []
        for timeframe, frame_bars in higher_timeframes.items():
            normalized_frame = _normalize(frame_bars)
            for event in _fvg_events(normalized_frame):
                if event["direction"] != direction:
                    continue
                interacted = any(
                    float(row["l"]) <= float(event["upper"])
                    and float(row["h"]) >= float(event["lower"])
                    for row in rows
                )
                if interacted:
                    contexts.append({**event, "timeframe": str(timeframe), "mapped_execution": mapped_execution.get(str(timeframe).lower(), "explicit_input")})
        if not contexts:
            continue
        context = contexts[-1]

        inverse_source_direction = "bearish" if direction == "bullish" else "bullish"
        candidates = [event for event in ltf_fvgs if event["direction"] == inverse_source_direction]
        sequence: dict[str, Any] | None = None
        for fvg in reversed(candidates):
            for sweep_position in range(int(fvg["position"]) + 1, len(rows)):
                prior = rows[max(0, sweep_position - 5) : sweep_position]
                if len(prior) < 3:
                    continue
                sweep_bar = rows[sweep_position]
                if direction == "bullish":
                    level = min(float(row["l"]) for row in prior)
                    swept = float(sweep_bar["l"]) < level - tolerance and float(sweep_bar["c"]) > level
                    sweep_extreme = float(sweep_bar["l"])
                else:
                    level = max(float(row["h"]) for row in prior)
                    swept = float(sweep_bar["h"]) > level + tolerance and float(sweep_bar["c"]) < level
                    sweep_extreme = float(sweep_bar["h"])
                if not swept:
                    continue
                inversion_position = next((
                    position
                    for position in range(sweep_position + 1, len(rows))
                    if (
                        float(rows[position]["c"]) > float(fvg["upper"])
                        if direction == "bullish"
                        else float(rows[position]["c"]) < float(fvg["lower"])
                    )
                ), None)
                if inversion_position is None:
                    continue
                cisd = _cisd_event(rows, direction, after_position=inversion_position)
                if cisd is None:
                    continue
                sequence = {
                    "fvg": fvg,
                    "sweep_position": sweep_position,
                    "sweep_timestamp": sweep_bar.get("t"),
                    "sweep_level": level,
                    "sweep_extreme": sweep_extreme,
                    "inversion_position": inversion_position,
                    "inversion_timestamp": rows[inversion_position].get("t"),
                    "cisd": cisd,
                }
                break
            if sequence:
                break
        if not sequence:
            continue

        cisd = sequence["cisd"]
        confirmed = cisd["position"] is not None
        confirmation_bar = rows[int(cisd["position"])] if confirmed else rows[-1]
        body = abs(float(confirmation_bar["c"]) - float(confirmation_bar["o"]))
        bar_range = max(float(confirmation_bar["h"]) - float(confirmation_bar["l"]), tolerance)
        close_location = (float(confirmation_bar["c"]) - float(confirmation_bar["l"])) / bar_range
        displacement = body >= atr * 0.8 and (close_location >= 0.70 if direction == "bullish" else close_location <= 0.30)
        stages = [
            {"name": "htf_fvg_context", "status": "complete", "timeframe": context["timeframe"], "zone": {"low": _round(float(context["lower"])), "high": _round(float(context["upper"]))}},
            {"name": "third_candle_range", "status": "complete", "timestamp": context.get("timestamp"), "range": {"low": _round(float(context["third_candle_low"])), "high": _round(float(context["third_candle_high"]))}},
            {"name": "liquidity_sweep", "status": "complete", "position": sequence["sweep_position"], "timestamp": sequence["sweep_timestamp"], "level": _round(float(sequence["sweep_level"]))},
            {"name": "ifvg", "status": "complete", "position": sequence["inversion_position"], "timestamp": sequence["inversion_timestamp"], "zone": {"low": _round(float(sequence["fvg"]["lower"])), "high": _round(float(sequence["fvg"]["upper"]))}},
            {"name": "cisd", "status": "complete" if confirmed else "pending", "position": cisd["position"], "timestamp": cisd["timestamp"], "anchor": _round(float(cisd["anchor"])), "body_close_required": True},
        ]
        pattern = _pattern(
            "ict_cisd_universal_model",
            direction,
            97.0 if confirmed and displacement else 94.0 if confirmed else 72.0,
            "confirmed" if confirmed else "pending_cisd",
            (
                "Completed HTF-FVG → third-candle range → sweep → IFVG → body-close CISD sequence."
                if confirmed
                else "HTF-FVG → third-candle range → sweep → IFVG is complete; the CISD anchor still requires a candle-body close."
            ),
            trigger=float(cisd["anchor"]),
            invalidation=float(sequence["sweep_extreme"]),
            reference_level=float(sequence["fvg"]["upper"] if direction == "bullish" else sequence["fvg"]["lower"]),
        )
        pattern["model_sequence"] = {
            "model_version": "ict_cisd_sequence_v1",
            "core_complete": confirmed,
            "chronology_valid": True,
            "mapped_execution_timeframe": context["mapped_execution"],
            "stages": stages,
            "bonus_confluences": {
                "displacement": displacement,
                "liquidity_sweep": True,
                "smt": "unavailable_without_correlated_completed_bars",
                "consequent_encroachment": {
                    "level": _round((float(context["third_candle_low"]) + float(context["third_candle_high"])) / 2.0),
                    "status": "context_only_unvalidated",
                },
            },
            "probability_status": "unvalidated_pattern_hypothesis",
            "source_label": "independent_ohlc_rules_from_public_model_description",
            "execution_enabled": False,
            "can_submit_orders": False,
        }
        output.append(pattern)
    return output


def _anti_patterns(rows: Sequence[Mapping[str, Any]], atr: float, quote: Mapping[str, Any]) -> list[dict[str, Any]]:
    negatives: list[dict[str, Any]] = []
    closes = [float(row["c"]) for row in rows]
    last_close = closes[-1]
    ema20 = _ema(closes, min(20, len(closes)))
    distance_atr = abs(last_close - ema20) / atr if atr > 0 else 0.0
    last_direction = 1 if closes[-1] > closes[-2] else -1 if closes[-1] < closes[-2] else 0
    consecutive = all((closes[index] - closes[index - 1]) * last_direction > 0 for index in range(max(1, len(closes) - 3), len(closes))) if last_direction else False
    if distance_atr >= 2.25 or (distance_atr >= 1.75 and consecutive):
        negatives.append(_pattern("late_chase_exhaustion", "bearish" if last_direction > 0 else "bullish", min(96, 70 + distance_atr * 8), "confirmed", f"Price is {distance_atr:.2f} ATR from its short trend mean; new entry is path-consumed.", reference_level=ema20))

    window = rows[-min(14, len(rows)) :]
    high = max(float(row["h"]) for row in window)
    low = min(float(row["l"]) for row in window)
    path = sum(abs(closes[index] - closes[index - 1]) for index in range(max(1, len(closes) - len(window) + 1), len(closes)))
    displacement = abs(float(window[-1]["c"]) - float(window[0]["o"]))
    efficiency = displacement / path if path > 0 else 0.0
    location = (last_close - low) / (high - low) if high > low else 0.5
    if efficiency < 0.25 and 0.32 <= location <= 0.68:
        negatives.append(_pattern("midrange_chop", "neutral", 78, "confirmed", "Directional efficiency is low and price is near the range midpoint.", reference_level=(high + low) / 2))

    ranges = [float(row["h"]) - float(row["l"]) for row in rows[-6:]]
    if len(ranges) >= 6 and sum(ranges[-3:]) / 3 > (sum(ranges[:3]) / 3) * 1.55 and efficiency < 0.45:
        negatives.append(_pattern("broadening_instability", "neutral", 75, "confirmed", "Recent bar ranges expanded while directional efficiency remained weak."))

    freshness = str(quote.get("freshness") or "missing")
    spread = _finite(quote.get("spread_bps"))
    if freshness not in {"live", "recent"} or spread is None or spread > MAX_SPREAD_BPS:
        negatives.append(_pattern("wide_spread_or_stale", "neutral", 99, "confirmed", "The live quote freshness or spread gate failed."))
    return negatives


def _timeframe_alignment(
    rows: Sequence[Mapping[str, Any]], direction: str | None, higher_timeframes: Mapping[str, Sequence[Mapping[str, Any]]] | None
) -> dict[str, Any]:
    frame_rows, provenance = _timeframe_rows(rows, higher_timeframes)
    frames: dict[str, dict[str, Any]] = {}
    for name, values in frame_rows.items():
        if not values:
            continue
        frames[name] = {
            **_trend(values),
            "completed_bars": len(values),
            "provenance": provenance.get(name, "unavailable"),
        }
    alignment_names = {
        str(spec["timeframe"])
        for spec in APLUS_TIMEFRAME_MATRIX
        if bool(spec["required_for_aplus"])
    }
    directional = [
        frame["bias"]
        for name, frame in frames.items()
        if name in alignment_names and frame["bias"] != "neutral"
    ]
    if not direction or direction == "neutral" or not directional:
        state = "mixed"
    elif all(value == direction for value in directional):
        state = "aligned"
    elif any(value != direction for value in directional if value != "neutral"):
        state = "conflict"
    else:
        state = "mixed"
    return {
        "state": state,
        "frames": frames,
        "closed_bar_only": True,
        "execution_enabled": False,
        "can_submit_orders": False,
    }


def _empty_result(quote: Mapping[str, Any], bars: int) -> dict[str, Any]:
    pattern_grade = score_pattern_grade(
        components={},
        penalties={"stale_feed": str(quote.get("freshness") or "missing") not in {"live", "recent"}},
        evidence={"base_rate": "unavailable_insufficient_bars"},
    )
    return {
        "schema_version": 6,
        "decision": "STAND_ASIDE",
        "grade": pattern_grade["grade"],
        "score": pattern_grade["final_score"],
        "pattern_grade": pattern_grade,
        "structure_regime": "insufficient_data",
        "best_setup": None,
        "worst_setup": None,
        "positive_patterns": [],
        "negative_patterns": [],
        "timeframe_alignment": {"state": "unavailable", "frames": {}, "closed_bar_only": True, "execution_enabled": False, "can_submit_orders": False},
        "timeframe_coverage": _timeframe_coverage([], None),
        "timeframe_scan": [],
        "timeframe_plan": {
            "primary_trigger": "5m",
            "execution_refinement": "1m_optional_not_standalone",
            "confirmation": ["15m", "30m"],
            "structure": ["60m", "4h"],
            "regime": ["1d", "1w"],
            "coverage_status": "incomplete_for_aplus_review",
            "closed_bar_only": True,
            "execution_enabled": False,
            "can_submit_orders": False,
        },
        "liquidity_level_context": {"status": "unavailable", "levels": [], "active_sweeps": [], "nearest_upside": None, "nearest_downside": None, "dealing_range": None, "probability_status": "unavailable_pending_local_outcomes", "execution_enabled": False, "can_submit_orders": False},
        "participation_context": _participation_context([]),
        "smt_divergence_context": _smt_divergence_context([], None),
        "clc_entry_context": {
            "status": "blocked",
            "direction": "neutral",
            "next_required": f"Need at least {MIN_BARS} completed bars; received {bars}.",
            "context": {"status": "pending", "frames": {"60m": "unavailable", "4h": "unavailable", "1d": "unavailable"}},
            "location": {"status": "pending", "current_price": None, "entry_zone": {"low": None, "high": None}},
            "confirmation": {"status": "pending", "completed_bar_trigger": False, "quote_quality": "fail", "true_order_flow": "unavailable_without_tick_or_mbo", "sequence": []},
            "source_labels": ["clc_completed_bar_contract_v1"],
            "score_effect": "none_separate_gate_only",
            "execution_enabled": False,
            "can_submit_orders": False,
        },
        "macro_context": _macro_context([]),
        "strat_context": _strat_context([], None, []),
        "ny_0800_0900_range_context": _ny_0800_0900_range_context([], []),
        "entry_plan": {"status": "unavailable", "timeframe": "5m", "trigger": None, "entry_zone": {"low": None, "high": None}, "invalidation": None, "instruction": f"Need at least {MIN_BARS} completed bars; received {bars}."},
        "exit_plan": {"status": "unavailable", "targets": [], "time_stop_bars": None, "time_stop": None, "management": "No entry, so no exit plan."},
        "factor_scores": {},
        "hard_blockers": ["insufficient_completed_bars"],
        "warnings": ["Pattern recognition is descriptive research, not a guarantee of future returns."],
        "freshness": str(quote.get("freshness") or "missing"),
        "source_labels": ["completed_5m_bars", "latest_quote", "pattern_grade_v1", "ict_cisd_sequence_v1", "cbc_strong_flip_v1", "session_liquidity_levels_v1", "ohlcv_participation_curvature_proxy_v1", "completed_ohlcv_strat_scenarios_v1", "completed_0800_0900_et_bars"],
        "bar_count": bars,
        "closed_bar_only": True,
        "execution_enabled": False,
        "can_submit_orders": False,
    }


def analyze_market_structure(
    bars: Sequence[Mapping[str, Any]],
    *,
    quote: Mapping[str, Any] | None = None,
    rvol: float | None = None,
    average_dollar_volume: float | None = None,
    direction_hint: str | None = None,
    higher_timeframes: Mapping[str, Sequence[Mapping[str, Any]]] | None = None,
    correlated_bars: Mapping[str, Sequence[Mapping[str, Any]]] | None = None,
    macro_event_window: bool = False,
) -> dict[str, Any]:
    """Recognize, grade, and plan a completed-bar setup without execution rights."""
    rows = _normalize(bars)
    quote_data = dict(quote or {})
    if len(rows) < MIN_BARS:
        return _empty_result(quote_data, len(rows))

    atr = max(_atr(rows), abs(float(rows[-1]["c"])) * 0.0005)
    trend = _trend(rows)
    positive, range_negatives = _range_events(rows, atr)
    swing_positive, swing_negatives = _swing_patterns(rows, atr)
    positive.extend(swing_positive)
    positive.extend(_continuation_patterns(rows, atr, trend))
    positive.extend(_sweep_pattern(rows, atr))
    positive.extend(_cbc_patterns(rows))
    liquidity_levels = _derive_liquidity_levels(rows, higher_timeframes)
    target_map = _liquidity_target_map(rows, liquidity_levels)
    liquidity_patterns = _session_liquidity_patterns(rows, liquidity_levels, atr)
    positive.extend(liquidity_patterns)
    cisd_patterns = detect_cisd_universal_model(rows, higher_timeframes=higher_timeframes)
    positive.extend(cisd_patterns)
    negatives = range_negatives + swing_negatives + _anti_patterns(rows, atr, quote_data)

    direction = str(direction_hint or "").lower()
    if direction not in {"bullish", "bearish"}:
        confirmed = [row for row in positive if row["trigger_state"] == "confirmed"]
        direction = str((max(confirmed or positive, key=lambda row: float(row["confidence_score"]), default={"direction": trend["bias"]}))["direction"])
    if direction not in {"bullish", "bearish"}:
        direction = trend["bias"] if trend["bias"] in {"bullish", "bearish"} else "neutral"
    alignment = _timeframe_alignment(rows, direction, higher_timeframes)
    timeframe_coverage = _timeframe_coverage(rows, higher_timeframes)
    timeframe_scan = _timeframe_scan(rows, higher_timeframes)
    participation = _participation_context(rows)
    smt_context = _smt_divergence_context(rows, correlated_bars)

    matching = [row for row in positive if row["direction"] == direction] if direction != "neutral" else positive
    best = max(matching or positive, key=lambda row: (row["trigger_state"] == "confirmed", float(row["confidence_score"])), default=None)
    worst = max(negatives, key=lambda row: float(row["confidence_score"]), default=None)

    blockers: list[str] = []
    freshness = str(quote_data.get("freshness") or "missing")
    spread = _finite(quote_data.get("spread_bps"))
    if freshness not in {"live", "recent"}:
        blockers.append("stale_quote")
    if spread is None or spread > MAX_SPREAD_BPS:
        blockers.append("spread_too_wide_or_missing")
    if average_dollar_volume is not None and average_dollar_volume < MIN_DOLLAR_LIQUIDITY:
        blockers.append("insufficient_dollar_liquidity")
    if rvol is not None and rvol < MIN_RVOL:
        blockers.append("rvol_below_preregistered_threshold")
    if alignment["state"] == "conflict":
        blockers.append("higher_timeframe_conflict")
    if timeframe_coverage["missing_required"]:
        blockers.append("incomplete_aplus_timeframe_coverage")
    failed = next((row for row in negatives if row["pattern_id"] == "failed_breakout_trap"), None)
    if failed and direction != "neutral" and failed["direction"] != direction:
        blockers.append("failed_breakout_against_direction")

    structure_score = float(best["confidence_score"]) if best else 35.0
    trigger_score = 100.0 if best and best["trigger_state"] == "confirmed" else 62.0 if best else 25.0
    alignment_score = 92.0 if alignment["state"] == "aligned" else 58.0 if alignment["state"] == "mixed" else 20.0
    participation_score = min(100.0, max(0.0, (rvol if rvol is not None else 1.25) * 50.0))
    location_score = 90.0
    if any(row["pattern_id"] == "late_chase_exhaustion" for row in negatives):
        location_score = 20.0
    elif any(row["pattern_id"] == "midrange_chop" for row in negatives):
        location_score = 38.0
    quality_score = max(0.0, 100.0 - (spread if spread is not None else 100.0) * 2.0)

    trigger = _finite(best.get("trigger")) if best else None
    invalidation = _finite(best.get("invalidation")) if best else None
    planned_reward_risk = 2.0 if trigger is not None and invalidation is not None and trigger != invalidation else None
    volume_score = 100.0 if rvol is not None and rvol >= 2.0 else 70.0 if rvol is not None and rvol >= 1.5 else 40.0 if rvol is not None and rvol >= 1.2 else 0.0
    mtf_score = 100.0 if alignment["state"] == "aligned" else 50.0 if alignment["state"] == "mixed" else 0.0
    if timeframe_coverage["missing_required"]:
        mtf_score = min(mtf_score, 50.0)
    regime_score = 100.0 if trend["bias"] == direction else 50.0 if trend["bias"] == "neutral" else 0.0
    confirmed_families = {
        str(row.get("family") or "unknown")
        for row in positive
        if row.get("trigger_state") == "confirmed" and (direction == "neutral" or row.get("direction") == direction)
    }
    confluence_score = min(100.0, 25.0 * len(confirmed_families))
    reward_risk_score = 100.0 if planned_reward_risk is not None and planned_reward_risk >= 3.0 else 75.0 if planned_reward_risk is not None and planned_reward_risk >= 2.0 else 50.0 if planned_reward_risk is not None and planned_reward_risk >= 1.5 else 0.0
    base_rate = PATTERN_BASE_RATE_PRIORS.get(str((best or {}).get("pattern_id") or ""), 55.0)
    anti_pattern_active = any(float(row["confidence_score"]) >= 75.0 for row in negatives)
    pattern_grade = score_pattern_grade(
        components={
            "base_rate": base_rate,
            "volume_rvol": volume_score,
            "mtf_alignment": mtf_score,
            "regime_fit": regime_score,
            "confluence": confluence_score,
            "reward_risk": reward_risk_score,
        },
        penalties={
            "anti_pattern": anti_pattern_active,
            "macro_window": macro_event_window,
            "wide_spread": spread is None or spread > MAX_SPREAD_BPS,
            "stale_feed": freshness not in {"live", "recent"},
        },
        evidence={
            "base_rate": "research_prior_not_local_probability",
            "volume_rvol": "completed_bar_volume_and_time_adjusted_rvol",
            "mtf_alignment": "completed_bars_only",
            "regime_fit": "price_trend_proxy_only",
            "confluence": "distinct_implemented_detector_families",
            "reward_risk": "objective_trigger_invalidation_geometry",
            "order_flow": "unavailable_without_tick_or_mbo_feed",
            "dealer_gamma": "unavailable_without_provenance_gated_options_surface",
        },
    )
    score = float(pattern_grade["final_score"])

    if "failed_breakout_against_direction" in blockers or "spread_too_wide_or_missing" in blockers or "stale_quote" in blockers:
        decision = "REJECT"
    elif "higher_timeframe_conflict" in blockers:
        decision = "REJECT" if best and best["trigger_state"] == "confirmed" else "WAIT"
    elif not best:
        decision = "STAND_ASIDE"
    elif best["trigger_state"] != "confirmed" or blockers:
        decision = "WAIT"
    elif pattern_grade["grade"] == "A":
        decision = "READY_TO_REVIEW"
    else:
        decision = "WAIT"

    if trigger is not None and invalidation is not None:
        risk = abs(trigger - invalidation)
        sign = 1.0 if best["direction"] == "bullish" else -1.0
        targets = [
            {"name": "target_1r", "price": _round(trigger + sign * risk), "reward_risk": 1.0},
            {"name": "target_2r", "price": _round(trigger + sign * risk * 2.0), "reward_risk": 2.0},
        ]
        zone_half = min(atr * 0.12, risk * 0.15)
        entry_plan = {
            "status": "actionable_manual_review" if decision == "READY_TO_REVIEW" else "conditional",
            "timeframe": "5m",
            "trigger": _round(trigger),
            "entry_zone": {"low": _round(trigger - zone_half), "high": _round(trigger + zone_half)},
            "invalidation": _round(invalidation),
            "risk_per_share": _round(risk),
            "instruction": "Act only after the completed-bar trigger remains valid and the live spread/freshness gates still pass.",
        }
        exit_plan = {
            "status": "defined",
            "targets": targets,
            "time_stop_bars": 6,
            "time_stop": {
                "bars": 6,
                "timeframe": "5m",
                "minutes": 30,
                "status": "research_default_pending_local_validation",
            },
            "management": "At +1R, reduce risk or trail behind the last confirmed swing; exit on invalidation or after six 5m bars without progress. Never widen the invalidation.",
        }
    else:
        entry_plan = {"status": "unavailable", "timeframe": "5m", "trigger": None, "entry_zone": {"low": None, "high": None}, "invalidation": None, "risk_per_share": None, "instruction": "Wait for a pattern with objective trigger and invalidation geometry."}
        exit_plan = {"status": "unavailable", "targets": [], "time_stop_bars": None, "time_stop": None, "management": "No valid entry geometry; stand aside."}

    clc_context = _clc_entry_context(
        rows=rows,
        direction=direction,
        best=best,
        alignment=alignment,
        entry_plan=entry_plan,
        target_map=target_map,
        participation=participation,
        smt=smt_context,
        blockers=blockers,
    )

    regime = "trend" if trend["bias"] != "neutral" else "range_or_transition"
    if any(row["pattern_id"] in {"midrange_chop", "broadening_instability"} for row in negatives):
        regime = "chop_or_instability"
    return {
        "schema_version": 6,
        "decision": decision,
        "grade": pattern_grade["grade"],
        "score": score,
        "pattern_grade": pattern_grade,
        "structure_regime": regime,
        "trend": trend,
        "atr": _round(atr),
        "best_setup": best,
        "worst_setup": worst,
        "positive_patterns": sorted(positive, key=lambda row: -float(row["confidence_score"])),
        "negative_patterns": sorted(negatives, key=lambda row: -float(row["confidence_score"])),
        "timeframe_alignment": alignment,
        "timeframe_coverage": timeframe_coverage,
        "timeframe_scan": timeframe_scan,
        "timeframe_plan": {
            "primary_trigger": "5m",
            "execution_refinement": "1m_optional_not_standalone",
            "confirmation": ["15m", "30m"],
            "structure": ["60m", "4h"],
            "regime": ["1d", "1w"],
            "coverage_status": timeframe_coverage["status"],
            "closed_bar_only": True,
            "execution_enabled": False,
            "can_submit_orders": False,
        },
        "liquidity_level_context": {
            "status": "available" if liquidity_levels else "unavailable",
            "levels": liquidity_levels,
            "active_sweeps": [
                {"level_id": row["level_id"], "level_label": row["level_label"], "direction": row["direction"], "status": "confirmed_reclaim"}
                for row in liquidity_patterns
            ],
            "nearest_upside": target_map["nearest_upside"],
            "nearest_downside": target_map["nearest_downside"],
            "dealing_range": target_map["dealing_range"],
            "probability_status": "unavailable_pending_local_outcomes",
            "execution_enabled": False,
            "can_submit_orders": False,
        },
        "participation_context": participation,
        "smt_divergence_context": smt_context,
        "clc_entry_context": clc_context,
        "macro_context": _macro_context(rows),
        "strat_context": _strat_context(rows, higher_timeframes, liquidity_levels),
        "ny_0800_0900_range_context": _ny_0800_0900_range_context(rows, cisd_patterns),
        "entry_plan": entry_plan,
        "exit_plan": exit_plan,
        "factor_scores": {
            "structure": _round(structure_score, 1),
            "trigger": _round(trigger_score, 1),
            "timeframe_alignment": _round(alignment_score, 1),
            "participation": _round(participation_score, 1),
            "location": _round(location_score, 1),
            "market_quality": _round(quality_score, 1),
        },
        "hard_blockers": list(dict.fromkeys(blockers)),
        "warnings": [
            "Pattern recognition is descriptive research, not a guarantee of future returns.",
            "Scores rank observable setup quality; they are not win probabilities.",
        ],
        "freshness": freshness,
        "source_labels": list(dict.fromkeys([
            "completed_5m_bars",
            *[f"completed_{name}_bars" for name in ("15m", "30m", "60m", "4h", "1d", "1w") if name in alignment["frames"]],
            "latest_quote",
            "pattern_grade_v1",
            "aplus_timeframe_matrix_v1",
            "ict_cisd_sequence_v1",
            "cbc_strong_flip_v1",
            "session_liquidity_levels_v1",
            "ohlcv_participation_curvature_proxy_v1",
            "completed_ohlcv_strat_scenarios_v1",
            "completed_0800_0900_et_bars",
            "clc_completed_bar_contract_v1",
            "objective_level_map_v1",
            "paired_index_price_divergence_v1",
        ])),
        "bar_count": len(rows),
        "closed_bar_only": True,
        "execution_enabled": False,
        "can_submit_orders": False,
    }


__all__ = ["APLUS_TIMEFRAME_MATRIX", "PATTERN_CATALOG", "analyze_market_structure", "confirmed_swings", "detect_cisd_universal_model"]

"""Point-in-time Fibonacci market-structure analysis.

The module deliberately separates measurement from execution. Swing anchors
are confirmed pivots, so a pivot is unavailable until ``right_bars`` later.
This avoids the common backtest error of anchoring to a future-visible extreme.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
import math
from typing import Any

import pandas as pd


FIBONACCI_VERSION = "causal-fibonacci-v1"
FIBONACCI_EXECUTION_VERSION = "causal-fibonacci-execution-v1"
GOLDEN_RATIO = (1.0 + math.sqrt(5.0)) / 2.0
GOLDEN_RETRACEMENT = 1.0 / GOLDEN_RATIO
RETRACEMENTS = (0.382, 0.5, round(GOLDEN_RETRACEMENT, 6), 0.65, 0.786)
EXTENSIONS = (1.272, round(GOLDEN_RATIO, 6))


@dataclass(frozen=True)
class FibonacciConfig:
    left_bars: int = 3
    right_bars: int = 2
    atr_length: int = 14
    min_impulse_atr: float = 2.0
    zigzag_reversal_atr: float = 0.75
    max_anchor_age_bars: int = 72
    golden_zone_low: float = 0.588
    golden_zone_high: float = 0.648
    invalidation_ratio: float = 0.786
    structural_stop_buffer_atr: float = 0.05


@dataclass(frozen=True)
class FibonacciExecutionConfig:
    limit_ratio: float = round(GOLDEN_RETRACEMENT, 6)
    order_ttl_completed_bars: int = 1
    underlying_round_trip_cost_bps_proxy: float = 2.0
    minimum_reward_risk: float = 1.0
    minimum_target_to_cost: float = 3.0


def _normalize_bars(bars: pd.DataFrame) -> pd.DataFrame:
    frame = bars.copy()
    aliases = {str(column).lower(): column for column in frame.columns}
    required = {}
    for name in ("open", "high", "low", "close"):
        source = aliases.get(name)
        if source is None:
            raise ValueError(f"missing_{name}_column")
        required[source] = name
    frame = frame.rename(columns=required)[["open", "high", "low", "close"]]
    frame = frame.apply(pd.to_numeric, errors="coerce").dropna().sort_index()
    if frame.index.has_duplicates:
        frame = frame[~frame.index.duplicated(keep="last")]
    return frame


def _atr(frame: pd.DataFrame, length: int) -> float | None:
    previous = frame["close"].shift(1)
    true_range = pd.concat(
        [
            frame["high"] - frame["low"],
            (frame["high"] - previous).abs(),
            (frame["low"] - previous).abs(),
        ],
        axis=1,
    ).max(axis=1)
    values = true_range.tail(length).dropna()
    if values.empty:
        return None
    result = float(values.mean())
    return result if math.isfinite(result) and result > 0 else None


def confirmed_pivots(
    bars: pd.DataFrame,
    *,
    left_bars: int = 3,
    right_bars: int = 2,
) -> list[dict[str, Any]]:
    """Return pivots observable at the final bar, including confirmation time."""
    frame = _normalize_bars(bars)
    if left_bars < 1 or right_bars < 1:
        raise ValueError("pivot_windows_must_be_positive")
    pivots: list[dict[str, Any]] = []
    high = frame["high"].to_numpy()
    low = frame["low"].to_numpy()
    index = list(frame.index)
    for position in range(left_bars, len(frame) - right_bars):
        start = position - left_bars
        stop = position + right_bars + 1
        window_high = high[start:stop]
        window_low = low[start:stop]
        if high[position] == window_high.max() and int((window_high == high[position]).sum()) == 1:
            pivots.append(
                {
                    "kind": "high",
                    "position": position,
                    "timestamp": str(index[position]),
                    "confirmed_position": position + right_bars,
                    "confirmed_at": str(index[position + right_bars]),
                    "price": float(high[position]),
                }
            )
        if low[position] == window_low.min() and int((window_low == low[position]).sum()) == 1:
            pivots.append(
                {
                    "kind": "low",
                    "position": position,
                    "timestamp": str(index[position]),
                    "confirmed_position": position + right_bars,
                    "confirmed_at": str(index[position + right_bars]),
                    "price": float(low[position]),
                }
            )
    pivots.sort(key=lambda row: (row["position"], row["kind"]))
    return pivots


def confirmed_zigzag_pivots(
    bars: pd.DataFrame,
    *,
    atr_length: int = 14,
    reversal_atr: float = 0.75,
) -> list[dict[str, Any]]:
    """Return ATR-ZigZag pivots only after the reversal confirms each extreme.

    The extreme's timestamp and its later confirmation timestamp are both
    retained. This makes the series usable in causal replay without pretending
    the swing endpoint was known when it first printed.
    """
    frame = _normalize_bars(bars)
    if atr_length < 2 or reversal_atr <= 0:
        raise ValueError("invalid_zigzag_configuration")
    previous = frame["close"].shift(1)
    tr = pd.concat(
        [
            frame["high"] - frame["low"],
            (frame["high"] - previous).abs(),
            (frame["low"] - previous).abs(),
        ],
        axis=1,
    ).max(axis=1)
    atr = tr.rolling(atr_length, min_periods=atr_length).mean().to_numpy()
    high = frame["high"].to_numpy()
    low = frame["low"].to_numpy()
    index = list(frame.index)
    if len(frame) <= atr_length:
        return []

    start = atr_length - 1
    high_position = low_position = start
    direction = 0
    pivots: list[dict[str, Any]] = []

    def append(kind: str, position: int, confirmed_position: int) -> None:
        price = high[position] if kind == "high" else low[position]
        row = {
            "kind": kind,
            "position": int(position),
            "timestamp": str(index[position]),
            "confirmed_position": int(confirmed_position),
            "confirmed_at": str(index[confirmed_position]),
            "price": float(price),
        }
        if pivots and pivots[-1]["kind"] == kind:
            prior = pivots[-1]
            more_extreme = price > prior["price"] if kind == "high" else price < prior["price"]
            if more_extreme:
                pivots[-1] = row
            return
        pivots.append(row)

    for position in range(start + 1, len(frame)):
        threshold = float(atr[position]) * reversal_atr if math.isfinite(float(atr[position])) else 0.0
        if threshold <= 0:
            continue
        if direction == 0:
            if high[position] >= high[high_position]:
                high_position = position
            if low[position] <= low[low_position]:
                low_position = position
            if high[high_position] - low[low_position] < threshold:
                continue
            if low_position < high_position:
                append("low", low_position, position)
                direction = 1
            elif high_position < low_position:
                append("high", high_position, position)
                direction = -1
            continue

        if direction == 1:
            if high[position] >= high[high_position]:
                high_position = position
            if high[high_position] - low[position] >= threshold:
                append("high", high_position, position)
                direction = -1
                low_position = position
        else:
            if low[position] <= low[low_position]:
                low_position = position
            if high[position] - low[low_position] >= threshold:
                append("low", low_position, position)
                direction = 1
                high_position = position
    return pivots


def _latest_impulse(
    pivots: list[dict[str, Any]],
    *,
    direction: str,
    final_position: int,
    max_anchor_age_bars: int,
) -> tuple[dict[str, Any], dict[str, Any]] | None:
    end_kind = "high" if direction == "bullish" else "low"
    start_kind = "low" if direction == "bullish" else "high"
    for end in reversed(pivots):
        if end["kind"] != end_kind or final_position - end["position"] > max_anchor_age_bars:
            continue
        for start in reversed(pivots):
            if start["position"] >= end["position"] or start["kind"] != start_kind:
                continue
            if direction == "bullish" and end["price"] > start["price"]:
                return start, end
            if direction == "bearish" and start["price"] > end["price"]:
                return start, end
    return None


def analyze_fibonacci_structure(
    bars: pd.DataFrame,
    direction: str,
    *,
    config: FibonacciConfig = FibonacciConfig(),
) -> dict[str, Any]:
    """Analyze the latest completed bar against a causally anchored impulse."""
    desired = str(direction or "").lower()
    base: dict[str, Any] = {
        "version": FIBONACCI_VERSION,
        "direction": desired,
        "golden_ratio": round(GOLDEN_RATIO, 9),
        "golden_retracement": round(GOLDEN_RETRACEMENT, 9),
        "retracements": list(RETRACEMENTS),
        "extensions": list(EXTENSIONS),
        "config": asdict(config),
        "execution_authority": "analysis_only_pending_out_of_sample_validation",
        "can_submit_orders": False,
    }
    if desired not in {"bullish", "bearish"}:
        return {**base, "status": "error", "reason": "unknown_direction"}
    try:
        frame = _normalize_bars(bars)
    except ValueError as exc:
        return {**base, "status": "error", "reason": str(exc)}
    minimum = config.left_bars + config.right_bars + config.atr_length + 3
    if len(frame) < minimum:
        return {
            **base,
            "status": "unavailable",
            "reason": "insufficient_completed_bars",
            "bars_observed": len(frame),
            "minimum_bars": minimum,
        }
    atr = _atr(frame, config.atr_length)
    pivots = confirmed_zigzag_pivots(
        frame,
        atr_length=config.atr_length,
        reversal_atr=config.zigzag_reversal_atr,
    )
    impulse = None
    if len(pivots) >= 2:
        candidate = (pivots[-2], pivots[-1])
        if desired == "bullish" and candidate[0]["kind"] == "low" and candidate[1]["kind"] == "high":
            impulse = candidate
        elif desired == "bearish" and candidate[0]["kind"] == "high" and candidate[1]["kind"] == "low":
            impulse = candidate
    if impulse is None or atr is None:
        return {
            **base,
            "status": "unavailable",
            "reason": "no_valid_confirmed_impulse",
            "bars_observed": len(frame),
            "confirmed_pivot_count": len(pivots),
        }
    start, end = impulse
    impulse_size = abs(float(end["price"]) - float(start["price"]))
    impulse_atr = impulse_size / atr
    if impulse_atr < config.min_impulse_atr:
        return {
            **base,
            "status": "unavailable",
            "reason": "impulse_below_atr_threshold",
            "impulse_atr": round(impulse_atr, 4),
            "minimum_impulse_atr": config.min_impulse_atr,
        }

    current = frame.iloc[-1]
    previous = frame.iloc[-2]
    ema20 = frame["close"].ewm(span=20, adjust=False).mean()
    ema50 = frame["close"].ewm(span=50, adjust=False).mean()
    ema20_slope = float(ema20.iloc[-1] - ema20.iloc[-6]) if len(ema20) >= 6 else 0.0
    if desired == "bullish":
        retracement = (float(end["price"]) - float(current["close"])) / impulse_size
        level = lambda ratio: float(end["price"]) - impulse_size * ratio
        touched = float(current["low"]) <= level(config.golden_zone_low)
        confirmation = (
            float(current["close"]) >= level(config.golden_zone_low)
            and float(current["close"]) > float(current["open"])
            and float(current["close"]) > float(previous["close"])
        )
        structural_stop = float(start["price"]) - atr * config.structural_stop_buffer_atr
        invalidated = float(current["close"]) < structural_stop
        trend_aligned = float(current["close"]) > float(ema20.iloc[-1]) > float(ema50.iloc[-1]) and ema20_slope > 0
        prior_extreme = float(end["price"])
        extension_1272 = float(start["price"]) + impulse_size * 1.272
        extension_1618 = float(start["price"]) + impulse_size * GOLDEN_RATIO
    else:
        retracement = (float(current["close"]) - float(end["price"])) / impulse_size
        level = lambda ratio: float(end["price"]) + impulse_size * ratio
        touched = float(current["high"]) >= level(config.golden_zone_low)
        confirmation = (
            float(current["close"]) <= level(config.golden_zone_low)
            and float(current["close"]) < float(current["open"])
            and float(current["close"]) < float(previous["close"])
        )
        structural_stop = float(start["price"]) + atr * config.structural_stop_buffer_atr
        invalidated = float(current["close"]) > structural_stop
        trend_aligned = float(current["close"]) < float(ema20.iloc[-1]) < float(ema50.iloc[-1]) and ema20_slope < 0
        prior_extreme = float(end["price"])
        extension_1272 = float(start["price"]) - impulse_size * 1.272
        extension_1618 = float(start["price"]) - impulse_size * GOLDEN_RATIO

    in_zone = config.golden_zone_low <= retracement <= config.golden_zone_high
    deep_retracement = retracement > config.invalidation_ratio
    if invalidated:
        status, reason = "invalidated", "close_beyond_buffered_impulse_origin"
    elif deep_retracement:
        status, reason = "deep_retracement", "beyond_0_786_but_impulse_origin_intact"
    elif in_zone and touched and confirmation:
        status, reason = "confirmed", "golden_zone_rejection_confirmed"
    elif in_zone or touched:
        status, reason = "awaiting_confirmation", "golden_zone_touched_without_rejection"
    else:
        status, reason = "outside_zone", "price_not_in_golden_retracement_zone"

    levels = {str(ratio): round(level(ratio), 6) for ratio in RETRACEMENTS}
    return {
        **base,
        "status": status,
        "reason": reason,
        "as_of": str(frame.index[-1]),
        "bars_observed": len(frame),
        "confirmed_pivot_count": len(pivots),
        "anchor_start": start,
        "anchor_end": end,
        "anchor_end_was_confirmed_at": end["confirmed_at"],
        "impulse_size": round(impulse_size, 6),
        "atr": round(atr, 6),
        "impulse_atr": round(impulse_atr, 4),
        "retracement_ratio": round(retracement, 6),
        "levels": levels,
        "golden_zone": {
            "ratio_low": config.golden_zone_low,
            "ratio_high": config.golden_zone_high,
            "price_a": round(level(config.golden_zone_low), 6),
            "price_b": round(level(config.golden_zone_high), 6),
        },
        "deep_retracement_level_0_786": round(level(config.invalidation_ratio), 6),
        "invalidation_level": round(structural_stop, 6),
        "planned_limit_entry_0_618": round(level(GOLDEN_RETRACEMENT), 6),
        "trend_confirmation": {
            "aligned": bool(trend_aligned),
            "ema20": round(float(ema20.iloc[-1]), 6),
            "ema50": round(float(ema50.iloc[-1]), 6),
            "ema20_slope_5_bars": round(ema20_slope, 6),
        },
        "paper_research_candidate": bool(status == "confirmed" and trend_aligned),
        "targets": {
            "prior_impulse_extreme": round(prior_extreme, 6),
            "extension_1_272": round(extension_1272, 6),
            "extension_1_618": round(extension_1618, 6),
        },
        "confirmation": {
            "zone_touched": bool(touched),
            "rejection_bar_confirmed": bool(confirmation),
        },
    }


def build_fibonacci_execution_plan(
    analysis: dict[str, Any],
    *,
    config: FibonacciExecutionConfig = FibonacciExecutionConfig(),
) -> dict[str, Any]:
    """Build a non-authoritative, no-chase execution benchmark.

    Prices in this plan are underlying reference levels. They are not option
    premium limits and cannot be sent to a broker. The short TTL prevents a
    confirmed setup from turning into a late chase after the level has moved.
    """
    base: dict[str, Any] = {
        "version": FIBONACCI_EXECUTION_VERSION,
        "mode": "shadow_underlying_trigger_only",
        "price_domain": "underlying_not_option_premium",
        "execution_authority": "shadow_only_pending_preregistered_validation",
        "can_submit_orders": False,
        "can_change_size": False,
        "can_block_production_entry": False,
        "config": asdict(config),
    }
    if config.order_ttl_completed_bars < 1:
        return {**base, "status": "error", "reason": "invalid_order_ttl"}
    if str(analysis.get("status")) != "confirmed":
        return {
            **base,
            "status": "inactive",
            "reason": "fibonacci_rejection_not_confirmed",
        }
    trend = analysis.get("trend_confirmation") or {}
    if not bool(trend.get("aligned")):
        return {
            **base,
            "status": "inactive",
            "reason": "higher_order_trend_not_aligned",
        }

    levels = analysis.get("levels") or {}
    ratio_key = str(round(config.limit_ratio, 6))
    entry = levels.get(ratio_key)
    if entry is None and abs(config.limit_ratio - GOLDEN_RETRACEMENT) < 1e-5:
        entry = analysis.get("planned_limit_entry_0_618")
    target = (analysis.get("targets") or {}).get("prior_impulse_extreme")
    stop = analysis.get("invalidation_level")
    atr = analysis.get("atr")
    direction = str(analysis.get("direction") or "")
    try:
        entry_value = float(entry)
        target_value = float(target)
        stop_value = float(stop)
        atr_value = float(atr)
    except (TypeError, ValueError):
        return {**base, "status": "error", "reason": "missing_plan_prices"}

    valid_geometry = (
        stop_value < entry_value < target_value
        if direction == "bullish"
        else target_value < entry_value < stop_value
        if direction == "bearish"
        else False
    )
    if not valid_geometry or atr_value <= 0:
        return {**base, "status": "error", "reason": "invalid_plan_geometry"}
    risk = abs(entry_value - stop_value)
    reward = abs(target_value - entry_value)
    cost_proxy = entry_value * config.underlying_round_trip_cost_bps_proxy / 10_000.0
    reward_risk = reward / risk
    target_to_cost = reward / cost_proxy if cost_proxy > 0 else math.inf
    eligible = (
        reward_risk >= config.minimum_reward_risk
        and target_to_cost >= config.minimum_target_to_cost
    )
    return {
        **base,
        "status": "eligible_shadow" if eligible else "rejected_shadow",
        "reason": "confirmed_retest_limit_benchmark" if eligible else "execution_economics_below_floor",
        "activation": "confirmed_golden_zone_rejection_and_aligned_ema_trend",
        "entry_reference": round(entry_value, 6),
        "entry_rule": "rest_at_reference_after_confirmation_no_market_conversion",
        "stop_reference": round(stop_value, 6),
        "stop_rule": "buffered_impulse_origin",
        "target_reference": round(target_value, 6),
        "target_rule": "prior_impulse_extreme",
        "order_ttl_completed_bars": config.order_ttl_completed_bars,
        "cancel_rules": [
            "ttl_expired",
            "completed_bar_closes_beyond_buffered_impulse_origin",
            "confirmed_anchor_is_superseded",
            "market_data_becomes_stale_or_unavailable",
        ],
        "no_chase": True,
        "replace_or_concede_price": False,
        "risk_points": round(risk, 6),
        "reward_points": round(reward, 6),
        "reward_risk": round(reward_risk, 6),
        "target_to_underlying_cost_proxy": round(target_to_cost, 6),
    }


def direction_from_option_right(right: Any) -> str:
    value = str(right or "").upper()
    return "bullish" if value == "CALL" else "bearish" if value == "PUT" else "unknown"

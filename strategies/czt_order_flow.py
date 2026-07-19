"""Condition-Zone-Trigger research engine for intraday options context.

The engine is deliberately execution-agnostic.  OHLCV bars can establish
condition and bar-derived volume-profile zones, but they cannot prove resting
liquidity or transaction-level order flow.  Callers must preserve the
provenance fields and must not treat proxy triggers as live authority.
"""
from __future__ import annotations

from dataclasses import dataclass
from math import isfinite
from statistics import mean
from typing import Any, Iterable


@dataclass(frozen=True)
class Bar:
    timestamp: str
    open: float
    high: float
    low: float
    close: float
    volume: float
    ask_volume: float | None = None
    bid_volume: float | None = None


def _number(value: Any) -> float | None:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if isfinite(result) else None


def normalize_bars(rows: Iterable[dict[str, Any] | Bar]) -> list[Bar]:
    bars: list[Bar] = []
    for row in rows:
        if isinstance(row, Bar):
            bar = row
        else:
            values = {key: _number(row.get(key)) for key in ("open", "high", "low", "close", "volume")}
            if any(values[key] is None for key in values):
                continue
            bar = Bar(
                timestamp=str(row.get("timestamp") or row.get("time") or ""),
                open=float(values["open"]),
                high=float(values["high"]),
                low=float(values["low"]),
                close=float(values["close"]),
                volume=max(0.0, float(values["volume"])),
                ask_volume=_number(row.get("ask_volume") or row.get("up_volume")),
                bid_volume=_number(row.get("bid_volume") or row.get("down_volume")),
            )
        if bar.high >= bar.low and bar.open > 0 and bar.close > 0:
            bars.append(bar)
    return bars


def _atr(bars: list[Bar], length: int = 14) -> float:
    ranges: list[float] = []
    for index, bar in enumerate(bars):
        prior_close = bars[index - 1].close if index else bar.open
        ranges.append(max(bar.high - bar.low, abs(bar.high - prior_close), abs(bar.low - prior_close)))
    return mean(ranges[-length:]) if ranges else 0.0


def _vwap_series(bars: list[Bar]) -> list[float]:
    total_volume = 0.0
    total_value = 0.0
    values: list[float] = []
    for bar in bars:
        volume = max(bar.volume, 0.0)
        typical = (bar.high + bar.low + bar.close) / 3.0
        total_volume += volume
        total_value += typical * volume
        values.append(total_value / total_volume if total_volume else typical)
    return values


def volume_profile(bars: list[Bar], bins: int = 48, value_area_fraction: float = 0.70) -> dict[str, Any]:
    """Return a range-distributed, bar-derived volume profile.

    Each bar's volume is spread across the price bins its range touched.  This
    is less biased than assigning all volume to the close, while remaining an
    approximation rather than a true volume-at-price feed.
    """
    low = min(bar.low for bar in bars)
    high = max(bar.high for bar in bars)
    width = (high - low) / max(1, bins)
    if width <= 0:
        return {"poc": low, "vah": high, "val": low, "bin_width": 0.0, "bins": 1}

    totals = [0.0] * bins
    for bar in bars:
        start = max(0, min(bins - 1, int((bar.low - low) / width)))
        end = max(0, min(bins - 1, int((bar.high - low) / width)))
        touched = max(1, end - start + 1)
        share = bar.volume / touched
        for index in range(start, end + 1):
            totals[index] += share

    total = sum(totals)
    poc_index = max(range(bins), key=totals.__getitem__)
    selected: set[int] = set()
    accumulated = 0.0
    for index in sorted(range(bins), key=totals.__getitem__, reverse=True):
        selected.add(index)
        accumulated += totals[index]
        if not total or accumulated / total >= value_area_fraction:
            break

    center = lambda index: low + (index + 0.5) * width
    return {
        "poc": center(poc_index),
        "vah": center(max(selected)),
        "val": center(min(selected)),
        "bin_width": width,
        "bins": bins,
        "value_area_fraction": value_area_fraction,
        "provenance": "bar_range_distributed_volume_proxy",
    }


def _condition(bars: list[Bar], vwaps: list[float], atr: float) -> dict[str, Any]:
    latest = bars[-1]
    slope_lookback = min(10, len(vwaps) - 1)
    slope = vwaps[-1] - vwaps[-1 - slope_lookback] if slope_lookback else 0.0
    normalized_slope = slope / atr if atr > 0 else 0.0
    distance = (latest.close - vwaps[-1]) / atr if atr > 0 else 0.0
    if normalized_slope >= 0.20 and distance >= 0.15:
        regime, direction = "trend_up", "call"
    elif normalized_slope <= -0.20 and distance <= -0.15:
        regime, direction = "trend_down", "put"
    else:
        regime, direction = "balanced", None
    return {
        "regime": regime,
        "direction": direction,
        "vwap": vwaps[-1],
        "vwap_slope_atr": normalized_slope,
        "close_vs_vwap_atr": distance,
    }


def _trigger(bars: list[Bar], profile: dict[str, Any], condition: dict[str, Any], atr: float) -> dict[str, Any]:
    latest = bars[-1]
    prior = bars[-2]
    recent_volumes = [bar.volume for bar in bars[-21:-1] if bar.volume > 0]
    baseline_volume = mean(recent_volumes) if recent_volumes else latest.volume
    relative_volume = latest.volume / baseline_volume if baseline_volume else 0.0
    direction = condition["direction"]
    accepted_above = prior.close > profile["vah"] and latest.close > profile["vah"]
    accepted_below = prior.close < profile["val"] and latest.close < profile["val"]
    bullish_reclaim = latest.low <= profile["vah"] and latest.close > profile["vah"] and latest.close > latest.open
    bearish_reclaim = latest.high >= profile["val"] and latest.close < profile["val"] and latest.close < latest.open

    proxy_name: str | None = None
    if direction == "call" and relative_volume >= 1.10 and (accepted_above or bullish_reclaim):
        proxy_name = "value_area_high_acceptance" if accepted_above else "value_area_high_reclaim"
    elif direction == "put" and relative_volume >= 1.10 and (accepted_below or bearish_reclaim):
        proxy_name = "value_area_low_acceptance" if accepted_below else "value_area_low_reclaim"

    print_rows = [bar for bar in bars[-3:] if bar.ask_volume is not None and bar.bid_volume is not None]
    print_delta_ratio: float | None = None
    print_confirmation = False
    if len(print_rows) == 3:
        ask = sum(float(bar.ask_volume or 0.0) for bar in print_rows)
        bid = sum(float(bar.bid_volume or 0.0) for bar in print_rows)
        denominator = ask + bid
        print_delta_ratio = (ask - bid) / denominator if denominator else 0.0
        print_confirmation = bool(
            (direction == "call" and print_delta_ratio >= 0.15)
            or (direction == "put" and print_delta_ratio <= -0.15)
        )

    quality = "prints_confirmed" if proxy_name and print_confirmation else "bar_proxy" if proxy_name else "none"
    return {
        "name": proxy_name,
        "detected": bool(proxy_name),
        "quality": quality,
        "relative_volume": relative_volume,
        "print_delta_ratio": print_delta_ratio,
        "print_confirmation": print_confirmation,
        "resting_liquidity_observed": False,
        "absorption_observed": False,
        "atr": atr,
        "provenance": "transaction_prints" if quality == "prints_confirmed" else "ohlcv_bar_proxy",
    }


def evaluate_czt(rows: Iterable[dict[str, Any] | Bar], *, symbol: str) -> dict[str, Any]:
    bars = normalize_bars(rows)
    if len(bars) < 30:
        raise ValueError("CZT evaluation requires at least 30 valid bars")
    profile = volume_profile(bars)
    vwaps = _vwap_series(bars)
    atr = _atr(bars)
    condition = _condition(bars, vwaps, atr)
    trigger = _trigger(bars, profile, condition, atr)
    aligned = bool(condition["direction"] and trigger["detected"])
    direction = condition["direction"] if aligned else None
    entry = bars[-1].close
    risk = max(atr * 0.75, profile["bin_width"] * 2)
    return {
        "schema_version": 1,
        "symbol": symbol.upper(),
        "as_of": bars[-1].timestamp,
        "condition": condition,
        "zone": profile,
        "trigger": trigger,
        "czt_aligned": aligned,
        "shadow_direction": direction,
        "counterfactual": {
            "entry": entry,
            "stop": entry - risk if direction == "call" else entry + risk if direction == "put" else None,
            "target": entry + risk * 2 if direction == "call" else entry - risk * 2 if direction == "put" else None,
            "horizon_minutes": 60,
        },
        "authority": "shadow_research_only",
        "execution_enabled": False,
        "can_submit_orders": False,
        "live_execution_allowed": False,
        "limitations": [
            "volume profile is derived from OHLCV bar ranges, not exchange volume-at-price",
            "resting liquidity and queue behavior are unavailable",
            "bar proxy triggers cannot authorize a live trade",
        ],
    }

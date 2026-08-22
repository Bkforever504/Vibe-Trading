#!/usr/bin/env python3
"""Separate Topstep-style futures prop bot arena.

This module is paper/shadow infrastructure. It does not connect to Topstep or
submit live orders. The first strategy is intentionally simple and testable:
opening-range breakout with VWAP confirmation on MNQ/MES-style futures.
"""
from __future__ import annotations

import argparse
import csv
import json
import statistics
from dataclasses import asdict, dataclass
from datetime import datetime, time, timedelta, timezone
from pathlib import Path
from typing import Literal

try:
    from strategies.decision_intelligence import Evidence, assess_decision_intelligence
except ModuleNotFoundError:
    from decision_intelligence import Evidence, assess_decision_intelligence

try:
    from strategies.prop_rule_gate import (
        AccountState,
        PropGateDecision,
        ProposedTrade,
        evaluate_prop_trade,
        load_rule_profile,
    )
except ModuleNotFoundError:
    from prop_rule_gate import AccountState, PropGateDecision, ProposedTrade, evaluate_prop_trade, load_rule_profile

Side = Literal["buy", "sell"]
PROFITABILITY_CONTROL_PATH = Path.home() / ".vibe-trading" / "reports" / "profitability-control-plane.json"
PROFITABILITY_CONTROL_MAX_AGE_SECONDS = 26 * 60 * 60


@dataclass(frozen=True)
class Candle:
    timestamp: datetime
    open: float
    high: float
    low: float
    close: float
    volume: int
    instrument_id: str | None = None


@dataclass(frozen=True)
class FuturesContract:
    symbol: str
    point_value: float
    tick_size: float


@dataclass(frozen=True)
class OpeningRangeConfig:
    range_minutes: int = 15
    min_breakout_points: float = 2.0
    reward_risk: float = 1.5
    max_risk_per_trade: float = 100.0
    max_contracts: int = 2


@dataclass(frozen=True)
class PropSignal:
    symbol: str
    strategy: str
    side: Side
    entry: float
    stop: float
    target: float
    opening_range_high: float
    opening_range_low: float
    vwap: float
    confidence: float

    @property
    def risk_points(self) -> float:
        return abs(self.entry - self.stop)

    def evaluate_rules(
        self,
        *,
        profile: dict,
        account: AccountState,
        contracts: int,
        running_on_vps: bool,
    ) -> PropGateDecision:
        return evaluate_prop_trade(
            profile,
            ProposedTrade(
                symbol=self.symbol,
                side=self.side,
                contracts=contracts,
                risk_dollars=self.risk_points * contracts * contract_for_symbol(self.symbol).point_value,
                automated=True,
                running_on_vps=running_on_vps,
            ),
            account,
        )


@dataclass(frozen=True)
class FuturesRegime:
    classification: str
    direction: str
    efficiency_ratio: float
    vwap_displacement_atr: float
    volume_impulse: float
    bars_observed: int


def apply_profitability_control(
    assessment: dict,
    *,
    lane: str,
    report: dict,
    now: datetime | None = None,
) -> dict:
    """Demote a futures paper candidate unless the daily capital vote selects it."""
    result = dict(assessment)
    generated = None
    try:
        generated = datetime.fromisoformat(str(report.get("generated_at") or "").replace("Z", "+00:00"))
        if generated.tzinfo is None:
            generated = generated.replace(tzinfo=timezone.utc)
    except ValueError:
        generated = None
    current = False
    if generated is not None:
        reference = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
        current = 0 <= (reference - generated.astimezone(timezone.utc)).total_seconds() <= PROFITABILITY_CONTROL_MAX_AGE_SECONDS
    capital = report.get("capital_decision") if isinstance(report.get("capital_decision"), dict) else {}
    selected_lanes = {
        str(row.get("lane") or "")
        for row in capital.get("selected") or []
        if isinstance(row, dict)
    }
    allows_practice = bool(
        current
        and capital.get("action") == "paper_candidates_available"
        and lane in selected_lanes
    )
    if result.get("status") == "paper_candidate" and not allows_practice:
        result["status"] = "shadow_observe"
        result["recommendation"] = "collect_counterfactual_only"
        result["reasons"] = sorted(set(result.get("reasons") or []) | {"profitability_control_not_selected"})
    result["profitability_control"] = {
        "lane": lane,
        "source_status": "current" if current else "stale_or_missing",
        "capital_action": capital.get("action"),
        "selected_lanes": sorted(selected_lanes),
        "allows_practice": allows_practice,
        "authority": "demotion_only",
    }
    result["can_submit_orders"] = False
    return result


def _read_profitability_control(path: Path = PROFITABILITY_CONTROL_PATH) -> dict:
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def classify_futures_regime(candles: list[Candle]) -> FuturesRegime:
    """Classify the causal prefix as trend, range, or transition."""
    if len(candles) < 4:
        return FuturesRegime("insufficient", "unknown", 0.0, 0.0, 0.0, len(candles))
    closes = [c.close for c in candles]
    path = sum(abs(current - prior) for prior, current in zip(closes, closes[1:]))
    efficiency = abs(closes[-1] - closes[0]) / path if path > 0 else 0.0
    ranges = [max(c.high - c.low, 1e-9) for c in candles]
    average_range = statistics.fmean(ranges)
    vwap = session_vwap(candles)
    displacement = (closes[-1] - vwap) / average_range if average_range > 0 else 0.0
    prior_volumes = [max(0, c.volume) for c in candles[:-1]]
    baseline_volume = statistics.median(prior_volumes) if prior_volumes else 0.0
    volume_impulse = candles[-1].volume / baseline_volume if baseline_volume > 0 else 0.0
    if efficiency >= 0.45 and abs(displacement) >= 0.25:
        classification = "trend"
        direction = "bullish" if displacement > 0 else "bearish"
    elif efficiency <= 0.25:
        classification = "range"
        direction = "neutral"
    else:
        classification = "transition"
        direction = "bullish" if displacement > 0 else "bearish" if displacement < 0 else "neutral"
    return FuturesRegime(
        classification=classification,
        direction=direction,
        efficiency_ratio=round(efficiency, 4),
        vwap_displacement_atr=round(displacement, 4),
        volume_impulse=round(volume_impulse, 4),
        bars_observed=len(candles),
    )


def assess_futures_signal_intelligence(
    signal: PropSignal,
    candles: list[Candle],
    *,
    entry_index: int,
    round_trip_commission: float = 2.48,
    forward_validated_edge: bool = False,
) -> dict:
    """Evaluate a futures signal using only candles available at entry."""
    prefix = candles[: entry_index + 1]
    desired = "bullish" if signal.side == "buy" else "bearish"
    regime = classify_futures_regime(prefix)
    trend_strategies = {"opening_range_vwap", "first_pullback", "intraday_range_breakout", "delta_fingerprint"}
    range_strategies = {"false_breakout_fade", "vwap_deviation_fade"}
    evidence = [Evidence(
        source=signal.strategy,
        family="price_structure",
        direction=desired,
        confidence=signal.confidence,
        reliability=0.70,
        detail="causal_signal_builder",
    )]
    if signal.strategy in range_strategies:
        vwap_direction = (
            "bearish" if signal.entry > signal.vwap
            else "bullish" if signal.entry < signal.vwap
            else "neutral"
        )
    else:
        vwap_direction = (
            "bullish" if signal.entry > signal.vwap
            else "bearish" if signal.entry < signal.vwap
            else "neutral"
        )
    evidence.append(Evidence(
        source="session_vwap",
        family="value_location",
        direction=vwap_direction,
        confidence=min(0.85, 0.55 + abs(regime.vwap_displacement_atr) * 0.10),
        reliability=0.70,
        detail=f"entry={signal.entry:.4f},vwap={signal.vwap:.4f}",
    ))
    if regime.volume_impulse >= 1.20:
        evidence.append(Evidence(
            source="entry_volume_impulse",
            family="participation",
            direction=desired,
            confidence=min(0.90, 0.55 + (regime.volume_impulse - 1.0) * 0.15),
            reliability=0.65,
            detail=f"volume_impulse={regime.volume_impulse:.4f}",
        ))
    if regime.direction in {"bullish", "bearish"}:
        evidence.append(Evidence(
            source="causal_efficiency_regime",
            family="regime",
            direction=regime.direction,
            confidence=min(0.90, 0.50 + regime.efficiency_ratio * 0.50),
            reliability=0.65,
            detail=regime.classification,
        ))
    elif regime.classification == "range" and signal.strategy in range_strategies:
        evidence.append(Evidence(
            source="causal_efficiency_regime",
            family="regime",
            direction=desired,
            confidence=min(0.85, 0.60 + (0.25 - regime.efficiency_ratio)),
            reliability=0.65,
            detail="range_regime_supports_mean_reversion",
        ))

    if regime.classification == "trend":
        regime_compatible = signal.strategy in trend_strategies and regime.direction == desired
    elif regime.classification == "range":
        regime_compatible = signal.strategy in range_strategies
    else:
        regime_compatible = None

    contract = contract_for_symbol(signal.symbol)
    risk_points = abs(signal.entry - signal.stop)
    reward_points = abs(signal.target - signal.entry)
    reward_risk = reward_points / risk_points if risk_points > 0 else None
    expected_reward_dollars = reward_points * contract.point_value
    modeled_friction = round_trip_commission + 2.0 * contract.tick_size * contract.point_value
    friction_to_reward = modeled_friction / expected_reward_dollars if expected_reward_dollars > 0 else None
    data_completeness = min(1.0, len(prefix) / 15.0)
    assessment = assess_decision_intelligence(
        candidate_id=f"{signal.symbol}:{signal.strategy}:{prefix[-1].timestamp.isoformat() if prefix else 'unknown'}",
        desired_direction=desired,
        evidence=evidence,
        data_completeness=data_completeness,
        regime=regime.classification,
        regime_compatible=regime_compatible,
        reward_risk=reward_risk,
        friction_to_reward=friction_to_reward,
        forward_validated_edge=forward_validated_edge,
    )
    assessment["futures_regime"] = asdict(regime)
    assessment["causal_entry_index"] = entry_index
    assessment["future_bars_consumed"] = 0
    assessment["modeled_round_trip_friction_dollars"] = round(modeled_friction, 2)
    return assessment


def contract_for_symbol(symbol: str) -> FuturesContract:
    root = symbol.upper()
    if root.startswith("MNQ"):
        return FuturesContract("MNQ", point_value=2.0, tick_size=0.25)
    if root.startswith("NQ"):
        return FuturesContract("NQ", point_value=20.0, tick_size=0.25)
    if root.startswith("MES"):
        return FuturesContract("MES", point_value=5.0, tick_size=0.25)
    if root.startswith("ES"):
        return FuturesContract("ES", point_value=50.0, tick_size=0.25)
    raise ValueError(f"Unsupported futures symbol for prop bot: {symbol}")


def load_candles_csv(path: Path) -> list[Candle]:
    candles: list[Candle] = []
    with path.open("r", newline="", encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            candles.append(
                Candle(
                    timestamp=datetime.fromisoformat(row["timestamp"]),
                    open=float(row["open"]),
                    high=float(row["high"]),
                    low=float(row["low"]),
                    close=float(row["close"]),
                    volume=int(float(row.get("volume") or 0)),
                    instrument_id=str(row["instrument_id"]) if row.get("instrument_id") not in (None, "") else None,
                )
            )
    return candles


def session_vwap(candles: list[Candle]) -> float:
    volume_sum = sum(max(0, c.volume) for c in candles)
    if volume_sum <= 0:
        return candles[-1].close if candles else 0.0
    typical_value_sum = sum(((c.high + c.low + c.close) / 3) * c.volume for c in candles)
    return typical_value_sum / volume_sum


def build_opening_range_signal(candles: list[Candle], config: OpeningRangeConfig, symbol: str = "MNQ") -> PropSignal | None:
    if len(candles) <= config.range_minutes:
        return None

    opening = candles[: config.range_minutes]
    trigger = candles[config.range_minutes]
    range_high = max(c.high for c in opening)
    range_low = min(c.low for c in opening)
    vwap = session_vwap(candles[: config.range_minutes + 1])

    long_breakout = trigger.close >= range_high + config.min_breakout_points and trigger.close > vwap
    short_breakout = trigger.close <= range_low - config.min_breakout_points and trigger.close < vwap

    if not long_breakout and not short_breakout:
        return None

    if long_breakout:
        side: Side = "buy"
        entry = trigger.close
        stop = range_low
        target = entry + (entry - stop) * config.reward_risk
    else:
        side = "sell"
        entry = trigger.close
        stop = range_high
        target = entry - (stop - entry) * config.reward_risk

    return PropSignal(
        symbol=symbol.upper(),
        strategy="opening_range_vwap",
        side=side,
        entry=entry,
        stop=stop,
        target=target,
        opening_range_high=range_high,
        opening_range_low=range_low,
        vwap=round(vwap, 4),
        confidence=0.65,
    )


def build_first_pullback_signal(
    candles: list[Candle],
    config: OpeningRangeConfig,
    symbol: str = "MNQ",
    *,
    pullback_tolerance_ticks: int = 4,
    pullback_stop_ticks: int = 8,
    max_scan_candles: int = 30,
    require_bos_confirm: bool = False,
) -> tuple[PropSignal, int] | None:
    """ORB direction + first pullback-to-range-level entry.

    Returns (signal, entry_candle_index) or None.
    Stop is pullback_stop_ticks below range_high (long) or above range_low (short).
    """
    if len(candles) <= config.range_minutes + 1:
        return None

    opening = candles[: config.range_minutes]
    trigger = candles[config.range_minutes]
    range_high = max(c.high for c in opening)
    range_low = min(c.low for c in opening)
    vwap = session_vwap(candles[: config.range_minutes + 1])

    long_breakout = trigger.close >= range_high + config.min_breakout_points and trigger.close > vwap
    short_breakout = trigger.close <= range_low - config.min_breakout_points and trigger.close < vwap

    if not long_breakout and not short_breakout:
        return None

    side: Side = "buy" if long_breakout else "sell"
    contract = contract_for_symbol(symbol)
    tolerance = pullback_tolerance_ticks * contract.tick_size
    breakout_high = trigger.high
    breakout_low = trigger.low
    bos_confirmed = not require_bos_confirm

    scan_start = config.range_minutes + 1
    scan_end = min(len(candles), scan_start + max_scan_candles)

    for idx in range(scan_start, scan_end):
        c = candles[idx]
        if side == "buy":
            touched = c.low <= range_high + tolerance
            held = c.close > range_high - tolerance
            if touched and held and bos_confirmed:
                entry = c.close
                stop = range_high - pullback_stop_ticks * contract.tick_size
                stop_dist = entry - stop
                if stop_dist <= 0:
                    continue
                target = entry + stop_dist * config.reward_risk
                return PropSignal(
                    symbol=symbol.upper(),
                    strategy="first_pullback",
                    side=side,
                    entry=entry,
                    stop=stop,
                    target=target,
                    opening_range_high=range_high,
                    opening_range_low=range_low,
                    vwap=round(vwap, 4),
                    confidence=0.70,
                ), idx
            if c.high > breakout_high:
                bos_confirmed = True
        else:
            touched = c.high >= range_low - tolerance
            held = c.close < range_low + tolerance
            if touched and held and bos_confirmed:
                entry = c.close
                stop = range_low + pullback_stop_ticks * contract.tick_size
                stop_dist = stop - entry
                if stop_dist <= 0:
                    continue
                target = entry - stop_dist * config.reward_risk
                return PropSignal(
                    symbol=symbol.upper(),
                    strategy="first_pullback",
                    side=side,
                    entry=entry,
                    stop=stop,
                    target=target,
                    opening_range_high=range_high,
                    opening_range_low=range_low,
                    vwap=round(vwap, 4),
                    confidence=0.70,
                ), idx
            if c.low < breakout_low:
                bos_confirmed = True

    return None


def build_late_orb_retest_signal(
    candles: list[Candle],
    config: OpeningRangeConfig,
    symbol: str = "MNQ",
    *,
    pullback_tolerance_ticks: int = 4,
    pullback_stop_ticks: int = 8,
    max_breakout_bars: int | None = None,
    max_retest_bars: int = 12,
) -> tuple[PropSignal, int] | None:
    """Detect a causal opening-range break followed by a later retest hold.

    Unlike ``build_first_pullback_signal``, the breakout may occur on any
    completed bar after the opening range. A wick through the level is not a
    breakout: the bar must close beyond the range and on the correct side of
    the live session VWAP. Entry occurs only after a subsequent completed bar
    touches the broken level and closes back on the breakout side.
    """
    if pullback_tolerance_ticks < 0 or pullback_stop_ticks <= 0:
        raise ValueError("pullback tick parameters must be non-negative/positive")
    if max_retest_bars <= 0:
        raise ValueError("max_retest_bars must be positive")
    if len(candles) <= config.range_minutes + 1:
        return None

    opening = candles[: config.range_minutes]
    range_high = max(c.high for c in opening)
    range_low = min(c.low for c in opening)
    contract = contract_for_symbol(symbol)
    tolerance = pullback_tolerance_ticks * contract.tick_size
    scan_end = len(candles) if max_breakout_bars is None else min(
        len(candles), config.range_minutes + max_breakout_bars
    )

    for breakout_idx in range(config.range_minutes, scan_end):
        breakout = candles[breakout_idx]
        breakout_vwap = session_vwap(candles[: breakout_idx + 1])
        long_breakout = (
            breakout.close >= range_high + config.min_breakout_points
            and breakout.close > breakout_vwap
        )
        short_breakout = (
            breakout.close <= range_low - config.min_breakout_points
            and breakout.close < breakout_vwap
        )
        if not long_breakout and not short_breakout:
            continue

        side: Side = "buy" if long_breakout else "sell"
        retest_end = min(len(candles), breakout_idx + max_retest_bars + 1)
        for entry_idx in range(breakout_idx + 1, retest_end):
            retest = candles[entry_idx]
            live_vwap = session_vwap(candles[: entry_idx + 1])
            if side == "buy":
                invalidated = retest.close < range_high - tolerance
                touched = retest.low <= range_high + tolerance
                held = retest.close > range_high and retest.close > live_vwap
                if invalidated:
                    break
                if not (touched and held):
                    continue
                entry = retest.close
                stop = range_high - pullback_stop_ticks * contract.tick_size
                risk = entry - stop
                if risk < contract.tick_size:
                    continue
                target = entry + risk * config.reward_risk
            else:
                invalidated = retest.close > range_low + tolerance
                touched = retest.high >= range_low - tolerance
                held = retest.close < range_low and retest.close < live_vwap
                if invalidated:
                    break
                if not (touched and held):
                    continue
                entry = retest.close
                stop = range_low + pullback_stop_ticks * contract.tick_size
                risk = stop - entry
                if risk < contract.tick_size:
                    continue
                target = entry - risk * config.reward_risk

            return PropSignal(
                symbol=symbol.upper(),
                strategy="late_orb_retest",
                side=side,
                entry=entry,
                stop=stop,
                target=target,
                opening_range_high=range_high,
                opening_range_low=range_low,
                vwap=round(live_vwap, 4),
                confidence=0.72,
            ), entry_idx

    return None


def build_intraday_range_signal(
    candles: list[Candle],
    config: OpeningRangeConfig,
    *,
    range_start_hour: int,
    range_start_minute: int,
    symbol: str = "MNQ",
) -> tuple["PropSignal", int] | None:
    """Signal from an intraday consolidation window.

    Collects `config.range_minutes` bars starting at `range_start_hour:range_start_minute`,
    then looks for the first bar after that window that breaks the range high or low.
    Returns (signal, entry_candle_index) or None.
    """
    from datetime import time as _time

    range_start = _time(range_start_hour, range_start_minute)
    in_range: list[Candle] = []
    post_range_idx: int | None = None

    for i, c in enumerate(candles):
        t = c.timestamp.time()
        if t < range_start:
            continue
        if len(in_range) < config.range_minutes:
            in_range.append(c)
        elif post_range_idx is None:
            post_range_idx = i
            break

    if len(in_range) < config.range_minutes or post_range_idx is None:
        return None

    trigger = candles[post_range_idx]
    range_high = max(c.high for c in in_range)
    range_low = min(c.low for c in in_range)
    vwap = session_vwap(candles[: post_range_idx + 1])

    long_breakout = trigger.close >= range_high + config.min_breakout_points and trigger.close > vwap
    short_breakout = trigger.close <= range_low - config.min_breakout_points and trigger.close < vwap

    if not long_breakout and not short_breakout:
        return None

    side: Side = "buy" if long_breakout else "sell"
    entry = trigger.close
    if long_breakout:
        stop = range_low
        target = entry + (entry - stop) * config.reward_risk
    else:
        stop = range_high
        target = entry - (stop - entry) * config.reward_risk

    return PropSignal(
        symbol=symbol.upper(),
        strategy="intraday_range_breakout",
        side=side,
        entry=entry,
        stop=stop,
        target=target,
        opening_range_high=range_high,
        opening_range_low=range_low,
        vwap=round(vwap, 4),
        confidence=0.65,
    ), post_range_idx


def build_false_breakout_signal(
    candles: list[Candle],
    config: OpeningRangeConfig,
    symbol: str = "MNQ",
    *,
    max_scan_bars: int = 40,
    max_reversal_bars: int = 3,
) -> tuple["PropSignal", int] | None:
    """False breakout fade (FBF): enter OPPOSITE the initial OR breakout attempt.

    Thesis: in low-VIX mean-reverting regimes, initial ORB breakouts are stop
    hunts. When price closes beyond the range then reverses back inside, algos
    have exhausted the directional order flow. The fade captures the snap-back.

    Steps:
      1. Compute N-bar opening range.
      2. Scan for the first bar that CLOSES beyond the range by min_breakout_points.
      3. Wait up to max_reversal_bars for a bar that CLOSES back inside the range.
      4. On confirmed reversal: enter in the OPPOSITE direction of the fake break.
         Stop = fake extreme + 1 tick (beyond the liquidity sweep high/low).
         Target = entry ± risk * reward_risk (using RR from config).
      5. Require VWAP inside OR: confirms the range is a meaningful mid-range level.
    """
    if len(candles) <= config.range_minutes + 2:
        return None

    opening = candles[: config.range_minutes]
    range_high = max(c.high for c in opening)
    range_low = min(c.low for c in opening)

    if range_high - range_low < 0.75:
        return None

    vwap = session_vwap(candles[: config.range_minutes + 1])
    if not (range_low <= vwap <= range_high):
        return None

    contract = contract_for_symbol(symbol)
    scan_end = min(len(candles) - 1, config.range_minutes + max_scan_bars)

    for idx in range(config.range_minutes, scan_end):
        c = candles[idx]

        # False break ABOVE range high → SHORT fade
        if c.close > range_high + config.min_breakout_points:
            fake_extreme = c.high
            for rev in range(idx + 1, min(idx + max_reversal_bars + 1, len(candles))):
                rc = candles[rev]
                if rc.close < range_high:
                    entry = rc.close
                    stop = fake_extreme + contract.tick_size
                    risk = stop - entry
                    if risk < contract.tick_size:
                        break
                    target = entry - risk * config.reward_risk
                    return PropSignal(
                        symbol=symbol.upper(),
                        strategy="false_breakout_fade",
                        side="sell",
                        entry=entry,
                        stop=stop,
                        target=target,
                        opening_range_high=range_high,
                        opening_range_low=range_low,
                        vwap=round(vwap, 4),
                        confidence=0.72,
                    ), rev

        # False break BELOW range low → LONG fade
        elif c.close < range_low - config.min_breakout_points:
            fake_extreme = c.low
            for rev in range(idx + 1, min(idx + max_reversal_bars + 1, len(candles))):
                rc = candles[rev]
                if rc.close > range_low:
                    entry = rc.close
                    stop = fake_extreme - contract.tick_size
                    risk = entry - stop
                    if risk < contract.tick_size:
                        break
                    target = entry + risk * config.reward_risk
                    return PropSignal(
                        symbol=symbol.upper(),
                        strategy="false_breakout_fade",
                        side="buy",
                        entry=entry,
                        stop=stop,
                        target=target,
                        opening_range_high=range_high,
                        opening_range_low=range_low,
                        vwap=round(vwap, 4),
                        confidence=0.72,
                    ), rev

    return None


def _aggregate_candles(candles: list[Candle], minutes: int = 5) -> list[Candle]:
    """Aggregate completed minute candles without using future bars."""
    if minutes <= 0:
        raise ValueError("minutes must be positive")
    buckets: list[Candle] = []
    current_key: datetime | None = None
    current: list[Candle] = []
    for candle in sorted(candles, key=lambda row: row.timestamp):
        bucket_minute = candle.timestamp.minute - candle.timestamp.minute % minutes
        key = candle.timestamp.replace(minute=bucket_minute, second=0, microsecond=0)
        if current_key is not None and key != current_key:
            first, last = current[0], current[-1]
            buckets.append(Candle(
                timestamp=current_key,
                open=first.open,
                high=max(row.high for row in current),
                low=min(row.low for row in current),
                close=last.close,
                volume=sum(row.volume for row in current),
                instrument_id=first.instrument_id,
            ))
            current = []
        current_key = key
        current.append(candle)
    if current and current_key is not None:
        first, last = current[0], current[-1]
        buckets.append(Candle(
            timestamp=current_key,
            open=first.open,
            high=max(row.high for row in current),
            low=min(row.low for row in current),
            close=last.close,
            volume=sum(row.volume for row in current),
            instrument_id=first.instrument_id,
        ))
    return buckets


def build_liquidity_sweep_mss_retest_signal(
    candles: list[Candle],
    config: OpeningRangeConfig,
    symbol: str = "MNQ",
    *,
    key_levels: dict[str, float] | None,
    entry_start: time = time(9, 45),
    entry_end: time = time(11, 0),
    structure_lookback: int = 3,
    atr_lookback: int = 3,
    min_body_atr: float = 0.50,
    max_confirm_bars: int = 6,
    max_retest_bars: int = 6,
    min_gap_ticks: int = 1,
    min_risk_ticks: int = 4,
) -> tuple[PropSignal, int] | None:
    """Causal HTF sweep -> LTF MSS/FVG -> rejection entry.

    The setup is intentionally binary. A prior-day high/low must be swept and
    reclaimed on a completed 5-minute bar. A later displacement bar must close
    through the pre-sweep three-bar structure and create a classic three-bar
    fair-value gap. Entry occurs only after a later bar retests the gap midpoint
    and closes back in the intended direction. No score can waive a missing
    state and no trade is emitted from an incomplete sequence.
    """
    if not key_levels or "high" not in key_levels or "low" not in key_levels:
        return None
    if structure_lookback < 2 or atr_lookback < 2:
        raise ValueError("lookbacks must be at least 2")

    five = _aggregate_candles(candles, 5)
    warmup = max(structure_lookback, atr_lookback) + 2
    if len(five) <= warmup:
        return None

    contract = contract_for_symbol(symbol)
    prior_high = float(key_levels["high"])
    prior_low = float(key_levels["low"])
    opening = five[:3]
    opening_high = max(row.high for row in opening)
    opening_low = min(row.low for row in opening)
    upper_liquidity = {prior_high, opening_high}
    lower_liquidity = {prior_low, opening_low}
    max_risk_points = config.max_risk_per_trade / contract.point_value

    for sweep_idx in range(warmup, len(five)):
        sweep = five[sweep_idx]
        completed_at = (sweep.timestamp + timedelta(minutes=5)).time()
        if completed_at < entry_start or completed_at >= entry_end:
            continue
        short_level = next(
            (level for level in sorted(upper_liquidity) if sweep.high >= level + contract.tick_size and sweep.close < level),
            None,
        )
        long_level = next(
            (level for level in sorted(lower_liquidity, reverse=True) if sweep.low <= level - contract.tick_size and sweep.close > level),
            None,
        )
        short_sweep = short_level is not None
        long_sweep = long_level is not None
        if not short_sweep and not long_sweep:
            continue

        direction = -1 if short_sweep else 1
        swept_extreme = sweep.high if direction < 0 else sweep.low
        pre_sweep = five[sweep_idx - structure_lookback:sweep_idx]
        structure_level = min(row.low for row in pre_sweep) if direction < 0 else max(row.high for row in pre_sweep)

        confirm_end = min(len(five), sweep_idx + max_confirm_bars + 1)
        for mss_idx in range(sweep_idx + 1, confirm_end):
            mss = five[mss_idx]
            mss_completed = (mss.timestamp + timedelta(minutes=5)).time()
            if mss_completed >= entry_end:
                break
            prior_ranges = [row.high - row.low for row in five[mss_idx - atr_lookback:mss_idx]]
            atr_proxy = statistics.mean(prior_ranges) if prior_ranges else 0.0
            body = abs(mss.close - mss.open)
            if atr_proxy <= 0 or body < min_body_atr * atr_proxy:
                continue

            two_back = five[mss_idx - 2]
            if direction < 0:
                shifted = mss.close < structure_level and mss.close < mss.open
                gap_bottom, gap_top = mss.high, two_back.low
            else:
                shifted = mss.close > structure_level and mss.close > mss.open
                gap_bottom, gap_top = two_back.high, mss.low
            if not shifted or gap_top - gap_bottom < min_gap_ticks * contract.tick_size:
                continue

            midpoint = (gap_bottom + gap_top) / 2.0
            retest_end = min(len(five), mss_idx + max_retest_bars + 1)
            for retest_idx in range(mss_idx + 1, retest_end):
                retest = five[retest_idx]
                retest_completed = (retest.timestamp + timedelta(minutes=5)).time()
                if retest_completed >= entry_end:
                    break
                invalidated = retest.high >= swept_extreme if direction < 0 else retest.low <= swept_extreme
                if invalidated:
                    break
                rejected = (
                    retest.high >= midpoint and retest.close < midpoint
                    if direction < 0
                    else retest.low <= midpoint and retest.close > midpoint
                )
                if not rejected:
                    continue

                entry = retest.close
                stop = swept_extreme + contract.tick_size if direction < 0 else swept_extreme - contract.tick_size
                risk = abs(entry - stop)
                risk_ticks = risk / contract.tick_size
                if risk_ticks < min_risk_ticks or risk > max_risk_points:
                    break
                target = entry + direction * risk * config.reward_risk
                prefix_end = next(
                    (idx for idx, row in enumerate(candles) if row.timestamp >= retest.timestamp + timedelta(minutes=5)),
                    len(candles),
                )
                return PropSignal(
                    symbol=symbol.upper(),
                    strategy="liquidity_sweep_mss_retest",
                    side="sell" if direction < 0 else "buy",
                    entry=entry,
                    stop=stop,
                    target=target,
                    opening_range_high=opening_high,
                    opening_range_low=opening_low,
                    vwap=round(session_vwap(candles[:prefix_end]), 4),
                    confidence=0.75,
                ), min(prefix_end - 1, len(candles) - 1)
    return None


def build_vwap_deviation_signal(
    candles: list[Candle],
    config: OpeningRangeConfig,
    symbol: str = "MNQ",
    *,
    deviation_points: float = 4.0,
    min_session_bars: int = 30,
    max_scan_bars: int = 90,
) -> tuple["PropSignal", int] | None:
    """VWAP deviation fade (VDF): fade extreme intraday VWAP extensions.

    Thesis: in choppy/mean-reverting regimes, price stretching far from the
    session VWAP is unsustainable. A bearish/bullish reversal candle at the
    extreme confirms exhaustion and targets a return to VWAP.

    Entry conditions:
      - Price extends > deviation_points from running session VWAP.
      - The extreme candle closes in the opposite half (bearish or bullish body).
      - Stop: 1 tick beyond the candle extreme.
      - Target: running VWAP at entry time × reward_risk for RR check.
      - Only trigger after min_session_bars have formed (avoids opening noise).
    """
    if len(candles) < min_session_bars + 2:
        return None

    contract = contract_for_symbol(symbol)
    scan_end = min(len(candles) - 1, min_session_bars + max_scan_bars)
    or_high = max(c.high for c in candles[: config.range_minutes])
    or_low = min(c.low for c in candles[: config.range_minutes])

    for idx in range(min_session_bars, scan_end):
        c = candles[idx]
        vwap = session_vwap(candles[: idx + 1])
        bar_mid = (c.high + c.low) / 2

        # Extended above VWAP + bearish close → SHORT fade
        if c.high > vwap + deviation_points and c.close < bar_mid:
            entry = c.close
            stop = c.high + contract.tick_size
            risk = stop - entry
            if risk < contract.tick_size:
                continue
            target = entry - risk * config.reward_risk
            if target >= vwap:
                continue  # target doesn't reach VWAP — not worth it
            return PropSignal(
                symbol=symbol.upper(),
                strategy="vwap_deviation_fade",
                side="sell",
                entry=entry,
                stop=stop,
                target=target,
                opening_range_high=or_high,
                opening_range_low=or_low,
                vwap=round(vwap, 4),
                confidence=0.68,
            ), idx

        # Extended below VWAP + bullish close → LONG fade
        if c.low < vwap - deviation_points and c.close > bar_mid:
            entry = c.close
            stop = c.low - contract.tick_size
            risk = entry - stop
            if risk < contract.tick_size:
                continue
            target = entry + risk * config.reward_risk
            if target <= vwap:
                continue  # target doesn't reach VWAP — not worth it
            return PropSignal(
                symbol=symbol.upper(),
                strategy="vwap_deviation_fade",
                side="buy",
                entry=entry,
                stop=stop,
                target=target,
                opening_range_high=or_high,
                opening_range_low=or_low,
                vwap=round(vwap, 4),
                confidence=0.68,
            ), idx

    return None


def _bar_delta(candle: Candle) -> float:
    """Approximate net buying pressure for a single 1-min bar.

    Uses the close position within the bar range to partition volume into
    estimated buy vs sell. A bar closing near its high = buyers dominated.
    Returns positive (net buying) or negative (net selling).
    """
    bar_range = candle.high - candle.low
    if bar_range < 1e-9 or candle.volume <= 0:
        return 0.0
    buy_fraction = (candle.close - candle.low) / bar_range
    buy_vol = candle.volume * buy_fraction
    sell_vol = candle.volume * (1.0 - buy_fraction)
    return buy_vol - sell_vol


def build_delta_fingerprint_signal(
    candles: list[Candle],
    config: OpeningRangeConfig,
    symbol: str = "MNQ",
    *,
    delta_threshold: float = 0.20,
    vwap_touch_ticks: int = 4,
    max_entry_scan: int = 60,
) -> tuple["PropSignal", int] | None:
    """Delta Fingerprint (DF): order-flow-driven VWAP-entry strategy.

    Novel combination:
      1. Cumulative delta proxy from first range_minutes bars — identifies
         which side (buyers or sellers) controlled the opening window.
      2. VWAP as entry timing — enter only when price visits VWAP, giving
         a tight natural stop and high-probability reversion toward the
         dominant direction.
      3. Bias/entry separation — delta sets the bias; VWAP touch is the
         trigger. These are two independent signals that must agree.

    delta_ratio = cum_delta / cum_volume:
      > +threshold → net buyers → look for VWAP touch from ABOVE (dip to
        VWAP, bullish close) → LONG toward the day's high.
      < -threshold → net sellers → look for VWAP touch from BELOW (rally
        to VWAP, bearish close) → SHORT toward the day's low.

    Stop: one tick beyond the deepest penetration of the VWAP-touch candle.
    Target: entry ± risk × reward_risk.
    """
    regime_bars = config.range_minutes
    if len(candles) < regime_bars + 2:
        return None

    # --- 1. Compute delta ratio over regime window ---
    cum_delta = sum(_bar_delta(c) for c in candles[:regime_bars])
    cum_volume = sum(max(c.volume, 1) for c in candles[:regime_bars])
    delta_ratio = cum_delta / cum_volume  # −1 to +1

    if abs(delta_ratio) < delta_threshold:
        return None  # no clear institutional bias

    contract = contract_for_symbol(symbol)
    touch_dist = vwap_touch_ticks * contract.tick_size
    or_high = max(c.high for c in candles[:regime_bars])
    or_low = min(c.low for c in candles[:regime_bars])

    bullish_bias = delta_ratio > 0
    scan_start = regime_bars
    scan_end = min(len(candles) - 1, regime_bars + max_entry_scan)

    for idx in range(scan_start, scan_end):
        c = candles[idx]
        # Running VWAP tracks the true intraday reference level as the session progresses
        running_vwap = session_vwap(candles[: idx + 1])
        bar_mid = (c.high + c.low) / 2

        if bullish_bias:
            # Price dips to running VWAP and closes bullish (close above bar mid and VWAP)
            touched = c.low <= running_vwap + touch_dist
            bullish_close = c.close > bar_mid and c.close >= running_vwap
            if touched and bullish_close:
                entry = c.close
                stop = c.low - contract.tick_size
                risk = entry - stop
                if risk < contract.tick_size:
                    continue
                target = entry + risk * config.reward_risk
                return PropSignal(
                    symbol=symbol.upper(),
                    strategy="delta_fingerprint",
                    side="buy",
                    entry=entry,
                    stop=stop,
                    target=target,
                    opening_range_high=or_high,
                    opening_range_low=or_low,
                    vwap=round(running_vwap, 4),
                    confidence=round(min(0.85, 0.60 + abs(delta_ratio)), 2),
                ), idx

        else:
            # Price rallies to running VWAP and closes bearish (close below bar mid and VWAP)
            touched = c.high >= running_vwap - touch_dist
            bearish_close = c.close < bar_mid and c.close <= running_vwap
            if touched and bearish_close:
                entry = c.close
                stop = c.high + contract.tick_size
                risk = stop - entry
                if risk < contract.tick_size:
                    continue
                target = entry - risk * config.reward_risk
                return PropSignal(
                    symbol=symbol.upper(),
                    strategy="delta_fingerprint",
                    side="sell",
                    entry=entry,
                    stop=stop,
                    target=target,
                    opening_range_high=or_high,
                    opening_range_low=or_low,
                    vwap=round(running_vwap, 4),
                    confidence=round(min(0.85, 0.60 + abs(delta_ratio)), 2),
                ), idx

    return None


def size_contracts(
    *,
    entry: float,
    stop: float,
    contract: FuturesContract,
    risk_budget: float,
    max_contracts: int,
) -> int:
    risk_per_contract = abs(entry - stop) * contract.point_value
    if risk_per_contract <= 0:
        return 0
    return max(0, min(max_contracts, int(risk_budget // risk_per_contract)))


def evaluate_csv_setup(
    *,
    csv_path: Path,
    profile_path: Path,
    symbol: str,
    account: AccountState,
    config: OpeningRangeConfig,
    running_on_vps: bool = False,
    profitability_control_path: Path = PROFITABILITY_CONTROL_PATH,
) -> dict:
    candles = load_candles_csv(csv_path)
    signal = build_opening_range_signal(candles, config, symbol=symbol)
    if signal is None:
        return {"status": "no_signal", "symbol": symbol.upper(), "strategy": "opening_range_vwap"}

    contract = contract_for_symbol(symbol)
    contracts = size_contracts(
        entry=signal.entry,
        stop=signal.stop,
        contract=contract,
        risk_budget=config.max_risk_per_trade,
        max_contracts=config.max_contracts,
    )
    if contracts <= 0:
        return {"status": "blocked", "reason": "risk_budget_too_small", "signal": asdict(signal)}

    profile = load_rule_profile(profile_path)
    decision = signal.evaluate_rules(profile=profile, account=account, contracts=contracts, running_on_vps=running_on_vps)
    intelligence = assess_futures_signal_intelligence(
        signal,
        candles,
        entry_index=config.range_minutes,
        forward_validated_edge=False,
    )
    intelligence = apply_profitability_control(
        intelligence,
        lane="topstep_intraday_futures",
        report=_read_profitability_control(profitability_control_path),
    )
    return {
        "status": "paper_order_ready" if decision.allowed else "blocked",
        "mode": "paper_only",
        "contracts": contracts,
        "contract": asdict(contract),
        "signal": asdict(signal),
        "rule_gate": asdict(decision),
        "intelligence_assessment": intelligence,
        "practice_eligible": bool(decision.allowed and intelligence.get("status") == "paper_candidate"),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Topstep-style futures prop bot paper scanner")
    parser.add_argument("--csv", type=Path, required=True, help="Minute candle CSV with timestamp,open,high,low,close,volume")
    parser.add_argument("--profile", type=Path, default=Path("rules/prop_firms/topstep_topstepx_api.json"))
    parser.add_argument("--symbol", default="MNQ")
    parser.add_argument("--equity", type=float, default=50_000)
    parser.add_argument("--start-equity", type=float, default=50_000)
    parser.add_argument("--day-pnl", type=float, default=0)
    parser.add_argument("--drawdown-remaining", type=float, default=2_000)
    parser.add_argument("--range-minutes", type=int, default=15)
    parser.add_argument("--min-breakout-points", type=float, default=2.0)
    parser.add_argument("--risk", type=float, default=100)
    parser.add_argument("--max-contracts", type=int, default=2)
    parser.add_argument("--vps", action="store_true")
    args = parser.parse_args()

    result = evaluate_csv_setup(
        csv_path=args.csv,
        profile_path=args.profile,
        symbol=args.symbol,
        account=AccountState(
            equity=args.equity,
            start_equity=args.start_equity,
            day_pnl=args.day_pnl,
            trailing_drawdown_remaining=args.drawdown_remaining,
        ),
        config=OpeningRangeConfig(
            range_minutes=args.range_minutes,
            min_breakout_points=args.min_breakout_points,
            max_risk_per_trade=args.risk,
            max_contracts=args.max_contracts,
        ),
        running_on_vps=args.vps,
    )
    print(json.dumps(result, indent=2, sort_keys=True, default=str))


if __name__ == "__main__":
    main()

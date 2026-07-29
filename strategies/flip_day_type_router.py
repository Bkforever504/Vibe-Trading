"""Point-in-time SPY day classification for strategy routing research.

The router has no order authority. It converts observations available at the
classification time into an explicit continuation, reversal, or observe lane.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime
from typing import Literal

import pandas as pd


DayType = Literal["trend", "range", "failed_extension", "unknown"]
Strategy = Literal["orb_continuation", "orb_extension_reversal", "flat", "observe"]


@dataclass(frozen=True)
class DayTypeSignals:
    overnight_futures_gap_pct: float = 0.0
    econ_calendar_high_impact: bool = False
    prior_session_tick_range: tuple[float, float] | None = None
    spy_vs_vwap_at_930: float = 0.0
    orb_range_pct: float = 0.0
    adx_5min: float = 0.0
    vix_current: float = 0.0
    extension_direction: Literal["bull", "bear", "none"] = "none"
    extension_fraction: float = 0.0
    extension_stalled_candles: int = 0
    reversal_confirmed: bool = False
    current_above_vwap: bool | None = None


@dataclass(frozen=True)
class DayTypeResult:
    day_type: DayType
    trend_probability: float
    reversal_probability: float
    confidence: Literal["high", "medium", "low"]
    signals_supporting: list[str]
    signals_conflicting: list[str]
    recommended_strategy: Strategy
    classification_time_et: str
    authority: str = "advisory_shadow_router"
    execution_enabled: bool = False
    can_submit_orders: bool = False

    def to_dict(self) -> dict:
        return asdict(self)


def classify_day_type(
    signals: DayTypeSignals,
    *,
    classification_time_et: str | None = None,
) -> DayTypeResult:
    """Classify a session without looking beyond ``classification_time_et``."""
    timestamp = classification_time_et or datetime.now().isoformat(timespec="seconds")
    supporting: list[str] = []
    conflicting: list[str] = []

    failed_extension = (
        signals.extension_fraction >= 1.5
        and signals.extension_stalled_candles >= 2
        and signals.reversal_confirmed
        and signals.extension_direction in {"bull", "bear"}
    )
    if failed_extension:
        supporting.extend([
            f"extension={signals.extension_fraction:.2f}x_orb",
            f"stall_candles={signals.extension_stalled_candles}",
            "reversal_structure_confirmed",
        ])
        if signals.current_above_vwap is not None:
            vwap_context_ok = (
                signals.extension_direction == "bull" and signals.current_above_vwap
            ) or (
                signals.extension_direction == "bear" and not signals.current_above_vwap
            )
            (supporting if vwap_context_ok else conflicting).append(
                "extension_side_vwap_context" if vwap_context_ok else "vwap_context_conflict"
            )
        return DayTypeResult(
            day_type="failed_extension",
            trend_probability=0.25,
            reversal_probability=0.85 if not conflicting else 0.72,
            confidence="high" if not conflicting else "medium",
            signals_supporting=supporting,
            signals_conflicting=conflicting,
            recommended_strategy="orb_extension_reversal",
            classification_time_et=timestamp,
        )

    trend_checks = [
        (abs(signals.overnight_futures_gap_pct) > 0.5, "gap_over_0.5pct"),
        (signals.econ_calendar_high_impact, "high_impact_calendar"),
        (signals.adx_5min > 25.0, "adx_over_25"),
        (signals.orb_range_pct > 0.4, "orb_range_over_0.4pct"),
        (abs(signals.spy_vs_vwap_at_930) > 0.15, "open_displaced_from_vwap"),
    ]
    trend_hits = [name for passed, name in trend_checks if passed]

    tick_range_bound = False
    if signals.prior_session_tick_range is not None:
        tick_low, tick_high = signals.prior_session_tick_range
        tick_range_bound = tick_low >= -400 and tick_high <= 400
    range_checks = [
        (abs(signals.overnight_futures_gap_pct) <= 0.3, "gap_under_0.3pct"),
        (0 < signals.adx_5min < 20.0, "adx_under_20"),
        (signals.orb_range_pct < 0.25, "orb_range_under_0.25pct"),
        (tick_range_bound, "tick_contained_400"),
    ]
    range_hits = [name for passed, name in range_checks if passed]

    if len(trend_hits) >= 3:
        supporting.extend(trend_hits)
        conflicting.extend(range_hits)
        return DayTypeResult(
            day_type="trend",
            trend_probability=min(0.95, 0.50 + 0.09 * len(trend_hits)),
            reversal_probability=0.15,
            confidence="high",
            signals_supporting=supporting,
            signals_conflicting=conflicting,
            recommended_strategy="orb_continuation",
            classification_time_et=timestamp,
        )

    if len(range_hits) == len(range_checks):
        supporting.extend(range_hits)
        conflicting.extend(trend_hits)
        return DayTypeResult(
            day_type="range",
            trend_probability=0.15,
            reversal_probability=0.45,
            confidence="high",
            signals_supporting=supporting,
            signals_conflicting=conflicting,
            recommended_strategy="flat",
            classification_time_et=timestamp,
        )

    supporting.extend(trend_hits if len(trend_hits) >= len(range_hits) else range_hits)
    conflicting.extend(range_hits if len(trend_hits) >= len(range_hits) else trend_hits)
    return DayTypeResult(
        day_type="unknown",
        trend_probability=round(0.25 + 0.08 * len(trend_hits), 2),
        reversal_probability=round(0.20 + 0.06 * len(range_hits), 2),
        confidence="medium" if max(len(trend_hits), len(range_hits)) >= 2 else "low",
        signals_supporting=supporting,
        signals_conflicting=conflicting,
        recommended_strategy="observe",
        classification_time_et=timestamp,
    )


def _adx(frame: pd.DataFrame, period: int = 3) -> float:
    """Return a fast ADX that is mature by the 10:00 ET classification."""
    if len(frame) < period + 2:
        return 0.0
    high, low, close = frame["high"], frame["low"], frame["close"]
    up = high.diff()
    down = -low.diff()
    plus_dm = up.where((up > down) & (up > 0), 0.0)
    minus_dm = down.where((down > up) & (down > 0), 0.0)
    true_range = pd.concat(
        [high - low, (high - close.shift()).abs(), (low - close.shift()).abs()], axis=1
    ).max(axis=1)
    atr = true_range.rolling(period).mean().replace(0, pd.NA)
    plus_di = 100.0 * plus_dm.rolling(period).mean() / atr
    minus_di = 100.0 * minus_dm.rolling(period).mean() / atr
    denominator = (plus_di + minus_di).replace(0, pd.NA)
    dx = 100.0 * (plus_di - minus_di).abs() / denominator
    value = dx.rolling(period).mean().iloc[-1]
    return float(value) if pd.notna(value) else 0.0


def classify_intraday_day_type(
    bars: pd.DataFrame,
    *,
    prior_close: float,
    econ_calendar_high_impact: bool = False,
    vix_current: float = 0.0,
    tick_range: tuple[float, float] | None = None,
    now_et: datetime | None = None,
) -> DayTypeResult:
    """Derive point-in-time inputs from one-minute bars and classify the day."""
    now_et = now_et or datetime.now()
    if now_et.hour < 10:
        return DayTypeResult(
            day_type="unknown", trend_probability=0.0, reversal_probability=0.0,
            confidence="low", signals_supporting=["waiting_for_10_et"],
            signals_conflicting=[], recommended_strategy="observe",
            classification_time_et=now_et.isoformat(timespec="seconds"),
        )
    frame = bars.copy()
    frame.columns = [str(column).lower() for column in frame.columns]
    for column in ("open", "high", "low", "close", "volume"):
        if column in frame.columns:
            frame[column] = pd.to_numeric(frame[column], errors="coerce")
    frame = frame.dropna(subset=["high", "low", "close"])
    if len(frame) < 6:
        return classify_day_type(
            DayTypeSignals(), classification_time_et=now_et.isoformat(timespec="seconds")
        )

    opening = frame.iloc[:5]
    orb_high = float(opening["high"].max())
    orb_low = float(opening["low"].min())
    orb_range = orb_high - orb_low
    session_open = float(frame.iloc[0].get("open", frame.iloc[0]["close"]))
    gap_pct = ((session_open - prior_close) / prior_close * 100.0) if prior_close > 0 else 0.0

    volume = frame.get("volume")
    typical = (frame["high"] + frame["low"] + frame["close"]) / 3.0
    if volume is not None and float(volume.fillna(0).sum()) > 0:
        vwap_series = (typical * volume).cumsum() / volume.cumsum().replace(0, pd.NA)
        vwap = float(vwap_series.iloc[-1])
        opening_vwap = float(vwap_series.iloc[min(4, len(vwap_series) - 1)])
    else:
        vwap = float(frame["close"].expanding().mean().iloc[-1])
        opening_vwap = float(frame["close"].iloc[:5].mean())

    five_minute = frame.resample("5min").agg({"high": "max", "low": "min", "close": "last"}).dropna()
    adx = _adx(five_minute)
    post = five_minute.iloc[1:]
    bull_extreme_pos = int(five_minute.index.get_loc(post["high"].idxmax()))
    bear_extreme_pos = int(five_minute.index.get_loc(post["low"].idxmin()))
    bull_extension = (
        (float(five_minute.iloc[bull_extreme_pos]["high"]) - orb_high) / orb_range
        if orb_range > 0 else 0.0
    )
    bear_extension = (
        (orb_low - float(five_minute.iloc[bear_extreme_pos]["low"])) / orb_range
        if orb_range > 0 else 0.0
    )
    direction = "bull" if bull_extension >= bear_extension else "bear"
    extreme_pos = bull_extreme_pos if direction == "bull" else bear_extreme_pos
    extension = max(bull_extension, bear_extension)
    after = five_minute.iloc[extreme_pos + 1:]
    stalled = len(after)
    reversal_confirmed = False
    if len(after) >= 1:
        for pos in range(extreme_pos + 1, len(five_minute)):
            current, prior = five_minute.iloc[pos], five_minute.iloc[pos - 1]
            if direction == "bull" and float(current["high"]) < float(prior["high"]):
                reversal_confirmed = True
                break
            if direction == "bear" and float(current["low"]) > float(prior["low"]):
                reversal_confirmed = True
                break

    signals = DayTypeSignals(
        overnight_futures_gap_pct=gap_pct,
        econ_calendar_high_impact=econ_calendar_high_impact,
        prior_session_tick_range=tick_range,
        spy_vs_vwap_at_930=(session_open - opening_vwap) / opening_vwap * 100.0 if opening_vwap else 0.0,
        orb_range_pct=orb_range / orb_low * 100.0 if orb_low > 0 else 0.0,
        adx_5min=adx,
        vix_current=vix_current,
        extension_direction=direction,
        extension_fraction=max(0.0, extension),
        extension_stalled_candles=stalled,
        reversal_confirmed=reversal_confirmed,
        current_above_vwap=float(frame["close"].iloc[-1]) > vwap,
    )
    return classify_day_type(signals, classification_time_et=now_et.isoformat(timespec="seconds"))

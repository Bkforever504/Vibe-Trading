"""Point-in-time ORB retest quality scoring with no execution authority."""
from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Literal

import pandas as pd


@dataclass(frozen=True)
class RetestQualityScore:
    raw_score: float
    grade: Literal["A", "B", "C", "rejected"]
    pre_retest_extension_pct: float
    minutes_since_breakout: int
    candles_at_level: int
    volume_on_test_vs_breakout: float | None
    tick_at_touch: int | None
    vwap_aligned: bool | None
    ema_aligned: bool | None
    details: dict[str, float | str | None]
    authority: str = "telemetry_only_until_forward_validation"

    def to_dict(self) -> dict:
        return asdict(self)


def _alignment(value: float, reference: float, direction: str) -> tuple[float, bool]:
    aligned = value >= reference if direction == "bull" else value <= reference
    return (2.0 if aligned else 0.0), aligned


def score_retest_quality(
    bars: pd.DataFrame,
    *,
    breakout_pos: int,
    retest_pos: int,
    direction: Literal["bull", "bear"],
    orb_high: float,
    orb_low: float,
    tick_at_touch: int | None = None,
) -> RetestQualityScore:
    frame = bars.copy()
    frame.columns = [str(column).lower() for column in frame.columns]
    orb_range = orb_high - orb_low
    if orb_range <= 0 or breakout_pos < 0 or retest_pos <= breakout_pos or retest_pos >= len(frame):
        return RetestQualityScore(
            raw_score=0.0, grade="rejected", pre_retest_extension_pct=0.0,
            minutes_since_breakout=0, candles_at_level=0,
            volume_on_test_vs_breakout=None, tick_at_touch=tick_at_touch,
            vwap_aligned=None, ema_aligned=None,
            details={"reason": "invalid_retest_positions"},
        )

    segment = frame.iloc[breakout_pos:retest_pos + 1]
    if direction == "bull":
        extension = max(0.0, (float(segment["high"].max()) - orb_high) / orb_range)
        level = orb_high
        touches = ((segment["low"] <= level) & (segment["high"] >= level)).sum()
    else:
        extension = max(0.0, (orb_low - float(segment["low"].min())) / orb_range)
        level = orb_low
        touches = ((segment["low"] <= level) & (segment["high"] >= level)).sum()
    extension_score = 2.0 if extension < 0.8 else 1.0 if extension <= 1.5 else 0.0

    if isinstance(frame.index, pd.DatetimeIndex):
        elapsed = frame.index[retest_pos] - frame.index[breakout_pos]
        minutes = max(0, int(elapsed.total_seconds() // 60))
    else:
        minutes = retest_pos - breakout_pos
    time_score = 2.0 if minutes < 8 else 1.0 if minutes <= 20 else 0.0

    volume_ratio = None
    volume_score = 1.0
    if "volume" in frame.columns:
        breakout_volume = float(frame.iloc[breakout_pos].get("volume") or 0.0)
        test_volume = float(frame.iloc[retest_pos].get("volume") or 0.0)
        if breakout_volume > 0:
            volume_ratio = test_volume / breakout_volume
            volume_score = 2.0 if volume_ratio < 0.60 else 1.0 if volume_ratio <= 0.90 else 0.0

    retest_close = float(frame.iloc[retest_pos]["close"])
    vwap_score = 1.0
    vwap_aligned = None
    if "vwap" in frame.columns and pd.notna(frame.iloc[retest_pos].get("vwap")):
        vwap_score, vwap_aligned = _alignment(retest_close, float(frame.iloc[retest_pos]["vwap"]), direction)
    elif "volume" in frame.columns and float(frame["volume"].fillna(0).sum()) > 0:
        typical = (frame["high"] + frame["low"] + frame["close"]) / 3.0
        vwap = (typical * frame["volume"]).cumsum() / frame["volume"].cumsum().replace(0, pd.NA)
        if pd.notna(vwap.iloc[retest_pos]):
            vwap_score, vwap_aligned = _alignment(retest_close, float(vwap.iloc[retest_pos]), direction)

    ema_score = 1.0
    ema_aligned = None
    ema_column = "ema50" if "ema50" in frame.columns else None
    if ema_column:
        ema_score, ema_aligned = _alignment(retest_close, float(frame.iloc[retest_pos][ema_column]), direction)
    elif len(frame.iloc[:retest_pos + 1]) >= 3:
        ema = frame["close"].ewm(span=50, adjust=False).mean()
        ema_score, ema_aligned = _alignment(retest_close, float(ema.iloc[retest_pos]), direction)

    total = round(extension_score + time_score + volume_score + vwap_score + ema_score, 2)
    if extension > 1.5:
        grade = "rejected"
    elif total >= 7.5:
        grade = "A"
    elif total >= 4.5:
        grade = "B"
    else:
        grade = "C"
    return RetestQualityScore(
        raw_score=total,
        grade=grade,
        pre_retest_extension_pct=round(extension, 4),
        minutes_since_breakout=minutes,
        candles_at_level=int(touches),
        volume_on_test_vs_breakout=round(volume_ratio, 4) if volume_ratio is not None else None,
        tick_at_touch=tick_at_touch,
        vwap_aligned=vwap_aligned,
        ema_aligned=ema_aligned,
        details={
            "extension_score": extension_score,
            "time_score": time_score,
            "volume_score": volume_score,
            "vwap_score": vwap_score,
            "ema_score": ema_score,
            "volume_status": "observed" if volume_ratio is not None else "unavailable_neutral",
        },
    )

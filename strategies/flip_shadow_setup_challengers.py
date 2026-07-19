"""Pure shadow evaluators for 15-minute ORB and failed-level sweeps."""
from __future__ import annotations

from typing import Any

import pandas as pd

from strategies.flip_retest_quality import score_retest_quality


def _ratchet_floor(best_return_pct: float) -> float:
    floor = max(25.0, best_return_pct - 15.0)
    if best_return_pct >= 60.0:
        floor = max(floor, 45.0)
    elif best_return_pct >= 50.0:
        floor = max(floor, 35.0)
    return floor


def simulate_structural_exit_tournament(observations: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Race the current ratchet against two point-in-time structural trails.

    Each observation must be forward captured. Missing underlying marks make
    the structural paths unavailable rather than guessed from later candles.
    """
    if not observations:
        return {}
    rows = sorted(observations, key=lambda row: str(row.get("scanned_at") or ""))
    required_marks = ("underlying_close", "underlying_vwap", "underlying_prior_5m_close")
    if any(
        row.get("underlying_mark_status") != "observed_forward"
        or any(row.get(field) is None for field in required_marks)
        for row in rows
    ):
        return {}
    right = str(rows[0].get("right") or "").upper()
    paths = {
        "current_ratchet": None,
        "structural_vwap_trail": None,
        "structural_5m_close_trail": None,
    }
    best = 0.0
    structural_armed = False
    for row in rows:
        current = row.get("return_pct_at_mark")
        if current is None:
            continue
        current = float(current)
        best = max(best, current)
        timestamp = row.get("scanned_at")
        if paths["current_ratchet"] is None:
            if current <= -30.0:
                paths["current_ratchet"] = {
                    "hypothetical_exit_pct": current, "hypothetical_exit_time": timestamp,
                    "exit_trigger": "stop_30_hit",
                }
            elif best >= 40.0 and 0 < current <= _ratchet_floor(best):
                paths["current_ratchet"] = {
                    "hypothetical_exit_pct": current, "hypothetical_exit_time": timestamp,
                    "exit_trigger": "current_profit_ratchet",
                }
        structural_armed = structural_armed or best >= 20.0
        close = row.get("underlying_close")
        vwap = row.get("underlying_vwap")
        prior_5m = row.get("underlying_prior_5m_close")
        if structural_armed and close is not None:
            close = float(close)
            if paths["structural_vwap_trail"] is None and vwap is not None:
                crossed = close < float(vwap) if right == "CALL" else close > float(vwap)
                if crossed:
                    paths["structural_vwap_trail"] = {
                        "hypothetical_exit_pct": current, "hypothetical_exit_time": timestamp,
                        "exit_trigger": "vwap_cross",
                    }
            if paths["structural_5m_close_trail"] is None and prior_5m is not None:
                crossed = close < float(prior_5m) if right == "CALL" else close > float(prior_5m)
                if crossed:
                    paths["structural_5m_close_trail"] = {
                        "hypothetical_exit_pct": current, "hypothetical_exit_time": timestamp,
                        "exit_trigger": "prior_5m_close_cross",
                    }

    last = next((row for row in reversed(rows) if row.get("return_pct_at_mark") is not None), None)
    if last:
        for name, result in list(paths.items()):
            if result is None:
                paths[name] = {
                    "hypothetical_exit_pct": float(last["return_pct_at_mark"]),
                    "hypothetical_exit_time": last.get("scanned_at"),
                    "exit_trigger": "observed_path_end",
                }
    return {name: result for name, result in paths.items() if result is not None}


def _frame(bars: pd.DataFrame) -> pd.DataFrame:
    result = bars.copy()
    result.columns = [str(column).lower() for column in result.columns]
    return result.dropna(subset=["high", "low", "close"])


def _time_text(index: Any) -> str:
    return pd.Timestamp(index).isoformat() if isinstance(index, (pd.Timestamp,)) else str(index)


def _tolerance(level: float, reference_range: float) -> float:
    return max(level * 0.0002, min(reference_range * 0.10, level * 0.0010))


def evaluate_15m_orb_retest(
    bars: pd.DataFrame,
    *,
    prior_day_high: float | None,
    prior_day_low: float | None,
    max_retest_age_bars: int = 30,
) -> dict[str, Any]:
    """Find a completed 15-minute ORB breakout, retest, and hold."""
    frame = _frame(bars)
    base = {
        "strategy": "orb_15m_retest",
        "shadow_signal": False,
        "authority": "shadow_challenger_only",
        "execution_enabled": False,
        "can_submit_orders": False,
        "live_execution_allowed": False,
    }
    if len(frame) < 17:
        return {**base, "status": "waiting_for_completed_15m_range"}

    opening = frame.iloc[:15]
    orb_high = float(opening["high"].max())
    orb_low = float(opening["low"].min())
    if orb_high <= orb_low:
        return {**base, "status": "invalid_opening_range"}
    tolerance = _tolerance((orb_high + orb_low) / 2.0, orb_high - orb_low)

    breakout_pos = None
    direction = None
    for pos in range(15, len(frame)):
        close = float(frame.iloc[pos]["close"])
        if close > orb_high:
            breakout_pos, direction = pos, "call"
            break
        if close < orb_low:
            breakout_pos, direction = pos, "put"
            break
    if breakout_pos is None or direction is None:
        return {
            **base, "status": "no_breakout", "opening_15m_high": round(orb_high, 4),
            "opening_15m_low": round(orb_low, 4),
        }

    level = orb_high if direction == "call" else orb_low
    retest_pos = None
    invalidated = False
    for pos in range(breakout_pos + 1, len(frame)):
        row = frame.iloc[pos]
        if direction == "call":
            if float(row["close"]) < level - tolerance:
                invalidated = True
                break
            touched = level - tolerance <= float(row["low"]) <= level + tolerance
            held = float(row["close"]) > level
        else:
            if float(row["close"]) > level + tolerance:
                invalidated = True
                break
            touched = level - tolerance <= float(row["high"]) <= level + tolerance
            held = float(row["close"]) < level
        if touched and held:
            retest_pos = pos
            break
    if retest_pos is None:
        return {
            **base,
            "status": "breakout_invalidated" if invalidated else "awaiting_retest",
            "shadow_direction": direction,
            "opening_15m_high": round(orb_high, 4),
            "opening_15m_low": round(orb_low, 4),
            "breakout_at": _time_text(frame.index[breakout_pos]),
        }

    later = frame.iloc[retest_pos + 1:]
    if direction == "call" and any(float(value) < level - tolerance for value in later["close"]):
        return {**base, "status": "retest_invalidated_after_signal"}
    if direction == "put" and any(float(value) > level + tolerance for value in later["close"]):
        return {**base, "status": "retest_invalidated_after_signal"}

    age = len(frame) - 1 - retest_pos
    if age > max_retest_age_bars:
        return {**base, "status": "retest_stale", "retest_age_bars": age}
    retest = frame.iloc[retest_pos]
    entry = float(retest["close"])
    stop = float(retest["low"] - tolerance) if direction == "call" else float(retest["high"] + tolerance)
    risk = abs(entry - stop)
    target = entry + 2.0 * risk if direction == "call" else entry - 2.0 * risk
    prior_day_aligned = bool(
        direction == "call" and prior_day_high is not None and orb_high > prior_day_high
        or direction == "put" and prior_day_low is not None and orb_low < prior_day_low
    )
    quality = score_retest_quality(
        frame,
        breakout_pos=breakout_pos,
        retest_pos=retest_pos,
        direction="bull" if direction == "call" else "bear",
        orb_high=orb_high,
        orb_low=orb_low,
    ).to_dict()
    return {
        **base,
        "status": "signal",
        "shadow_signal": True,
        "shadow_direction": direction,
        "setup_grade_context": "a_plus_prior_day_aligned" if prior_day_aligned else "standard_orb_retest",
        "prior_day_aligned": prior_day_aligned,
        "prior_day_high": round(prior_day_high, 4) if prior_day_high is not None else None,
        "prior_day_low": round(prior_day_low, 4) if prior_day_low is not None else None,
        "opening_15m_high": round(orb_high, 4),
        "opening_15m_low": round(orb_low, 4),
        "breakout_at": _time_text(frame.index[breakout_pos]),
        "retest_at": _time_text(frame.index[retest_pos]),
        "retest_age_bars": age,
        "retest_tolerance": round(tolerance, 4),
        "retest_quality_score": quality["raw_score"],
        "retest_grade": quality["grade"],
        "pre_retest_extension_pct": quality["pre_retest_extension_pct"],
        "minutes_since_breakout": quality["minutes_since_breakout"],
        "retest_volume_ratio": quality["volume_on_test_vs_breakout"],
        "retest_quality_details": quality["details"],
        "retest_quality_authority": "shadow_only_until_forward_validation",
        "counterfactual": {
            "entry_underlying": round(entry, 4),
            "stop_underlying": round(stop, 4),
            "target_underlying_2r": round(target, 4),
            "reward_risk": 2.0,
        },
    }


def evaluate_level_sweep_reversal(
    bars: pd.DataFrame,
    *,
    levels: dict[str, float | None],
    first_minutes: int = 90,
) -> dict[str, Any]:
    """Find a failed break of a prior level with next-bar confirmation."""
    frame = _frame(bars).iloc[:first_minutes]
    base = {
        "strategy": "level_sweep_reversal",
        "shadow_signal": False,
        "authority": "shadow_challenger_only",
        "execution_enabled": False,
        "can_submit_orders": False,
        "live_execution_allowed": False,
        "claim_status": "social_70pct_reversal_claim_unverified",
    }
    valid_levels = {
        str(name): float(value) for name, value in levels.items()
        if value is not None and float(value) > 0
    }
    if len(frame) < 2 or not valid_levels:
        return {**base, "status": "insufficient_bars_or_levels"}
    reference_range = float((frame["high"] - frame["low"]).median())

    for pos in range(0, len(frame) - 1):
        sweep = frame.iloc[pos]
        confirmation = frame.iloc[pos + 1]
        for level_name, level in valid_levels.items():
            tolerance = _tolerance(level, reference_range)
            bearish = float(sweep["high"]) > level + tolerance and float(sweep["close"]) < level
            bullish = float(sweep["low"]) < level - tolerance and float(sweep["close"]) > level
            if bearish:
                held = float(confirmation["close"]) < level and float(confirmation["close"]) <= float(sweep["close"])
                direction = "put"
            elif bullish:
                held = float(confirmation["close"]) > level and float(confirmation["close"]) >= float(sweep["close"])
                direction = "call"
            else:
                continue
            if not held:
                continue

            entry = float(confirmation["close"])
            stop = float(sweep["high"] + tolerance) if direction == "put" else float(sweep["low"] - tolerance)
            candidates = sorted(valid_levels.items(), key=lambda item: item[1])
            if direction == "put":
                target_rows = [(name, value) for name, value in candidates if value < entry]
                next_target = target_rows[-1] if target_rows else None
            else:
                target_rows = [(name, value) for name, value in candidates if value > entry]
                next_target = target_rows[0] if target_rows else None
            risk = abs(entry - stop)
            modeled_2r = entry - 2 * risk if direction == "put" else entry + 2 * risk
            target_name, target = next_target if next_target else ("modeled_2r_fallback", modeled_2r)
            reward = abs(target - entry)
            return {
                **base,
                "status": "signal",
                "shadow_signal": True,
                "shadow_direction": direction,
                "swept_level_name": level_name,
                "swept_level": round(level, 4),
                "sweep_at": _time_text(frame.index[pos]),
                "confirmation_at": _time_text(frame.index[pos + 1]),
                "sweep_tolerance": round(tolerance, 4),
                "target_level_name": target_name,
                "counterfactual": {
                    "entry_underlying": round(entry, 4),
                    "stop_underlying": round(stop, 4),
                    "target_underlying": round(target, 4),
                    "reward_risk": round(reward / risk, 3) if risk > 0 else None,
                },
            }
    return {**base, "status": "no_confirmed_sweep"}


def evaluate_orb_extension_reversal(
    bars: pd.DataFrame,
    *,
    opening_minutes: int = 5,
    minimum_extension_fraction: float = 1.0,
    max_confirmation_age_bars: int = 5,
) -> dict[str, Any]:
    """Find a confirmed reversal after price extends at least one ORB range.

    This deliberately remains a shadow challenger. A single lower-high/lower-low
    turn after a bull extension (or the inverse after a bear extension) creates
    a measurable counterfactual, never an executable order.
    """
    frame = _frame(bars)
    base = {
        "strategy": "orb_extension_reversal",
        "shadow_signal": False,
        "authority": "shadow_challenger_only",
        "execution_enabled": False,
        "can_submit_orders": False,
        "live_execution_allowed": False,
    }
    if len(frame) < opening_minutes + 3:
        return {**base, "status": "insufficient_bars"}

    opening = frame.iloc[:opening_minutes]
    orb_high = float(opening["high"].max())
    orb_low = float(opening["low"].min())
    orb_range = orb_high - orb_low
    if orb_range <= 0:
        return {**base, "status": "invalid_opening_range"}

    candidates: list[dict[str, Any]] = []
    post = frame.iloc[opening_minutes:]
    bull_extreme_pos = int(frame.index.get_loc(post["high"].idxmax()))
    bull_extreme = float(frame.iloc[bull_extreme_pos]["high"])
    bull_extension = (bull_extreme - orb_high) / orb_range
    if bull_extension >= minimum_extension_fraction:
        for pos in range(bull_extreme_pos + 1, len(frame)):
            prior = frame.iloc[pos - 1]
            current = frame.iloc[pos]
            current_open = float(current.get("open", current["close"]))
            confirmed = (
                float(current["close"]) < float(prior["low"])
                and float(current["close"]) <= current_open
                and float(current["high"]) < bull_extreme
            )
            if confirmed:
                entry = float(current["close"])
                stop = bull_extreme + _tolerance(orb_high, orb_range)
                risk = stop - entry
                target = orb_high if orb_high < entry else entry - 2.0 * risk
                candidates.append({
                    "pos": pos,
                    "direction": "put",
                    "extreme": bull_extreme,
                    "extension_fraction": bull_extension,
                    "entry": entry,
                    "stop": stop,
                    "target": target,
                    "confirmation": "lower_high_close_below_prior_low",
                })
                break

    bear_extreme_pos = int(frame.index.get_loc(post["low"].idxmin()))
    bear_extreme = float(frame.iloc[bear_extreme_pos]["low"])
    bear_extension = (orb_low - bear_extreme) / orb_range
    if bear_extension >= minimum_extension_fraction:
        for pos in range(bear_extreme_pos + 1, len(frame)):
            prior = frame.iloc[pos - 1]
            current = frame.iloc[pos]
            current_open = float(current.get("open", current["close"]))
            confirmed = (
                float(current["close"]) > float(prior["high"])
                and float(current["close"]) >= current_open
                and float(current["low"]) > bear_extreme
            )
            if confirmed:
                entry = float(current["close"])
                stop = bear_extreme - _tolerance(orb_low, orb_range)
                risk = entry - stop
                target = orb_low if orb_low > entry else entry + 2.0 * risk
                candidates.append({
                    "pos": pos,
                    "direction": "call",
                    "extreme": bear_extreme,
                    "extension_fraction": bear_extension,
                    "entry": entry,
                    "stop": stop,
                    "target": target,
                    "confirmation": "higher_low_close_above_prior_high",
                })
                break

    if not candidates:
        status = "extension_without_reversal" if max(bull_extension, bear_extension) >= minimum_extension_fraction else "no_material_extension"
        return {
            **base,
            "status": status,
            "opening_5m_high": round(orb_high, 4),
            "opening_5m_low": round(orb_low, 4),
            "max_bull_extension_fraction": round(bull_extension, 3),
            "max_bear_extension_fraction": round(bear_extension, 3),
        }

    winner = min(candidates, key=lambda candidate: candidate["pos"])
    confirmation_age_bars = len(frame) - 1 - int(winner["pos"])
    if confirmation_age_bars > max_confirmation_age_bars:
        return {
            **base,
            "status": "signal_stale",
            "shadow_direction": winner["direction"],
            "confirmation_at": _time_text(frame.index[int(winner["pos"])]),
            "confirmation_age_bars": confirmation_age_bars,
            "orb_extension_fraction": round(float(winner["extension_fraction"]), 3),
        }
    risk = abs(float(winner["entry"]) - float(winner["stop"]))
    reward = abs(float(winner["target"]) - float(winner["entry"]))
    return {
        **base,
        "status": "signal",
        "shadow_signal": True,
        "shadow_direction": winner["direction"],
        "setup_grade_context": "orb_extension_confirmed_reversal",
        "opening_5m_high": round(orb_high, 4),
        "opening_5m_low": round(orb_low, 4),
        "orb_extension_fraction": round(float(winner["extension_fraction"]), 3),
        "orb_extension_extreme": round(float(winner["extreme"]), 4),
        "confirmation_at": _time_text(frame.index[int(winner["pos"])]),
        "confirmation_age_bars": confirmation_age_bars,
        "reversal_confirmation": winner["confirmation"],
        "counterfactual": {
            "entry_underlying": round(float(winner["entry"]), 4),
            "stop_underlying": round(float(winner["stop"]), 4),
            "target_underlying": round(float(winner["target"]), 4),
            "reward_risk": round(reward / risk, 3) if risk > 0 else None,
        },
    }

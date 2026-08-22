#!/usr/bin/env python3
"""Preregistered tournament of deterministic public MES strategy translations.

Research only. This module has no broker adapter and cannot submit orders.
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from dataclasses import asdict, dataclass
from datetime import time
from pathlib import Path
from statistics import median
from typing import Any, Callable

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from strategies.topstep_combine_simulator import CombineRules, bootstrap_combine


DEFAULT_CSV = ROOT / "examples" / "mes_v0_1m_2022-01-01_2026-07-19_rth.csv"
DEFAULT_OUT = ROOT / "data" / "mes_public_strategy_replication_results.json"
PREREGISTRATION = "research/MES_PUBLIC_STRATEGY_REPLICATION_PREREGISTRATION_2026-08-10.md"

EXPERIMENT = "MES-PUBLIC-REPLICATION-01"
TICK = 0.25
POINT_VALUE = 5.0
COMMISSION_PER_SIDE = 1.24
SLIPPAGE_TICKS_PER_SIDE = 1
MIN_RISK_TICKS = 4
MAX_RISK_TICKS = 60
RTH_OPEN = time(9, 30)
COMPLETE_THROUGH = time(15, 55)
FLATTEN_TIME = time(15, 55)
SELECTION_START = "2025-01-01"
HOLDOUT_START = "2026-01-01"
BOOTSTRAP_SEED = 20260810
BOOTSTRAP_SAMPLES = 5_000
BOOTSTRAP_BLOCK_SESSIONS = 20
FAMILYWISE_ALPHA = 0.05 / 5


PUBLIC_SOURCES = {
    "orb_breakout_control": {
        "concept": "opening range continuation",
        "urls": ["https://www.nexural.io/blog/es-futures-trading-strategies"],
        "translation_note": "Mechanical public-concept control; no proprietary code or verified PnL copied.",
    },
    "ib_failure_to_vwap": {
        "concept": "failed initial-balance auction toward VWAP",
        "urls": ["https://www.reddit.com/r/FuturesTrading/comments/1uto3kr/initial_balance_strategy/"],
        "translation_note": "Frozen interpretation of the described failed-IB or Tyson-style fade.",
    },
    "vwap_reclaim_retest": {
        "concept": "VWAP reclaim followed by a retest",
        "urls": [
            "https://www.reddit.com/r/FuturesTrading/comments/1vhffuf/vwap_reclaim_strategy_from_beginners/",
            "https://www.bullsonwallstreet.com/post/vwap-reclaim-trading-strategy",
        ],
        "translation_note": "Frozen synthesis of public descriptions; source profitability is not assumed.",
    },
    "vwap_band_reentry": {
        "concept": "VWAP deviation-band exhaustion and reentry",
        "urls": ["https://www.reddit.com/r/FuturesTrading/comments/1e9mptg/"],
        "translation_note": "The causal 1.5-standard-deviation rule is frozen by the preregistration.",
    },
    "opening_drive_vwap_pullback": {
        "concept": "opening drive followed by first VWAP pullback",
        "urls": ["https://www.nexural.io/blog/es-futures-trading-strategies"],
        "translation_note": "Causal research translation; exact thresholds are not attributed to the source.",
    },
}


@dataclass(frozen=True)
class ReplicationTrade:
    strategy: str
    day: str
    side: str
    signal_time: str
    entry_time: str
    exit_time: str
    entry_price: float
    exit_price: float
    stop_price: float
    target_price: float
    risk_ticks: float
    reward_risk: float
    raw_points: float
    exit_reason: str


def _normalize(frame: pd.DataFrame) -> pd.DataFrame:
    required = {"timestamp", "open", "high", "low", "close", "volume", "instrument_id"}
    missing = sorted(required - set(frame.columns))
    if missing:
        raise ValueError(f"missing required columns: {', '.join(missing)}")
    work = frame.copy()
    work["dt"] = pd.to_datetime(work["timestamp"], errors="raise")
    if work["dt"].dt.tz is not None:
        work["dt"] = work["dt"].dt.tz_convert("America/New_York").dt.tz_localize(None)
    work["date"] = work["dt"].dt.date.astype(str)
    for column in ("open", "high", "low", "close", "volume"):
        work[column] = pd.to_numeric(work[column], errors="raise")
    return work.sort_values("dt").reset_index(drop=True)


def prepare_sessions(
    frame: pd.DataFrame,
    *,
    start_date: str = "2024-01-01",
) -> tuple[list[str], dict[str, pd.DataFrame], dict[str, int]]:
    work = _normalize(frame)
    sessions: dict[str, pd.DataFrame] = {}
    skipped = {"before_start": 0, "incomplete": 0, "intraday_contract_change": 0}
    for day, bars in work.groupby("date", sort=True):
        bars = bars.sort_values("dt").reset_index(drop=True)
        if day < start_date:
            skipped["before_start"] += 1
            continue
        if (
            len(bars) < 300
            or bars.iloc[0]["dt"].time() != RTH_OPEN
            or bars.iloc[-1]["dt"].time() < COMPLETE_THROUGH
        ):
            skipped["incomplete"] += 1
            continue
        if bars["instrument_id"].astype(str).nunique() != 1:
            skipped["intraday_contract_change"] += 1
            continue
        sessions[day] = bars
    return sorted(sessions), sessions, skipped


def _live_vwap_and_std(bars: pd.DataFrame) -> tuple[np.ndarray, np.ndarray]:
    typical = ((bars["high"] + bars["low"] + bars["close"]) / 3.0).to_numpy(dtype=float)
    volume = bars["volume"].clip(lower=0).to_numpy(dtype=float)
    cumulative_volume = np.cumsum(volume)
    fallback = bars["close"].to_numpy(dtype=float)
    weighted_mean = np.divide(
        np.cumsum(typical * volume),
        cumulative_volume,
        out=fallback.copy(),
        where=cumulative_volume > 0,
    )
    weighted_second = np.divide(
        np.cumsum(typical * typical * volume),
        cumulative_volume,
        out=typical * typical,
        where=cumulative_volume > 0,
    )
    variance = np.maximum(0.0, weighted_second - weighted_mean * weighted_mean)
    return weighted_mean, np.sqrt(variance)


def _time_between(value: Any, start: time, end: time) -> bool:
    current = value.time()
    return start <= current <= end


def _simulate(
    bars: pd.DataFrame,
    *,
    strategy: str,
    side: int,
    signal_idx: int,
    entry_idx: int,
    stop: float,
    fixed_target: float | None = None,
    target_r: float | None = None,
    min_reward_risk: float = 1.0,
) -> ReplicationTrade | None:
    if entry_idx >= len(bars) or signal_idx >= entry_idx:
        return None
    entry_row = bars.iloc[entry_idx]
    if entry_row["dt"].time() >= FLATTEN_TIME:
        return None
    entry = float(entry_row["open"])
    risk_points = side * (entry - stop)
    if risk_points <= 0:
        return None
    risk_ticks = risk_points / TICK
    if not MIN_RISK_TICKS <= risk_ticks <= MAX_RISK_TICKS:
        return None
    if target_r is not None:
        target = entry + side * risk_points * target_r
    elif fixed_target is not None:
        target = fixed_target
    else:
        raise ValueError("fixed_target or target_r is required")
    reward_points = side * (target - entry)
    reward_risk = reward_points / risk_points
    if reward_points <= 0 or reward_risk < min_reward_risk:
        return None

    exit_price = float(bars.iloc[-1]["close"])
    exit_time = bars.iloc[-1]["dt"]
    exit_reason = "eod"
    for _, row in bars.iloc[entry_idx:].iterrows():
        if row["dt"].time() >= FLATTEN_TIME:
            exit_price = float(row["open"])
            exit_time = row["dt"]
            exit_reason = "time"
            break
        high = float(row["high"])
        low = float(row["low"])
        stop_hit = low <= stop if side > 0 else high >= stop
        target_hit = high >= target if side > 0 else low <= target
        if stop_hit:
            exit_price = stop
            exit_time = row["dt"]
            exit_reason = "stop"
            break
        if target_hit:
            exit_price = target
            exit_time = row["dt"]
            exit_reason = "target"
            break

    return ReplicationTrade(
        strategy=strategy,
        day=str(entry_row["date"]),
        side="buy" if side > 0 else "sell",
        signal_time=bars.iloc[signal_idx]["dt"].isoformat(),
        entry_time=entry_row["dt"].isoformat(),
        exit_time=exit_time.isoformat(),
        entry_price=round(entry, 4),
        exit_price=round(exit_price, 4),
        stop_price=round(stop, 4),
        target_price=round(target, 4),
        risk_ticks=round(risk_ticks, 2),
        reward_risk=round(reward_risk, 4),
        raw_points=round(side * (exit_price - entry), 4),
        exit_reason=exit_reason,
    )


def orb_breakout_control(
    bars: pd.DataFrame,
    *,
    entry_delay_bars: int = 0,
    prior_opening_range_median: float | None = None,
) -> ReplicationTrade | None:
    del prior_opening_range_median
    if len(bars) < 20:
        return None
    vwap, _ = _live_vwap_and_std(bars)
    opening = bars.iloc[:15]
    opening_high = float(opening["high"].max())
    opening_low = float(opening["low"].min())
    for idx in range(15, len(bars) - 1 - entry_delay_bars):
        row = bars.iloc[idx]
        if not _time_between(row["dt"], time(9, 45), time(10, 30)):
            if row["dt"].time() > time(10, 30):
                break
            continue
        long_signal = float(row["close"]) >= opening_high + TICK and float(row["close"]) > vwap[idx]
        short_signal = float(row["close"]) <= opening_low - TICK and float(row["close"]) < vwap[idx]
        if long_signal == short_signal:
            continue
        side = 1 if long_signal else -1
        stop = float(row["low"]) - TICK if side > 0 else float(row["high"]) + TICK
        trade = _simulate(
            bars,
            strategy="orb_breakout_control",
            side=side,
            signal_idx=idx,
            entry_idx=idx + 1 + entry_delay_bars,
            stop=stop,
            target_r=1.5,
            min_reward_risk=1.5,
        )
        if trade:
            return trade
    return None


def ib_failure_to_vwap(
    bars: pd.DataFrame,
    *,
    entry_delay_bars: int = 0,
    prior_opening_range_median: float | None = None,
) -> ReplicationTrade | None:
    del prior_opening_range_median
    if len(bars) < 65:
        return None
    vwap, _ = _live_vwap_and_std(bars)
    initial_balance = bars.iloc[:60]
    ib_high = float(initial_balance["high"].max())
    ib_low = float(initial_balance["low"].min())
    for idx in range(60, len(bars) - 1 - entry_delay_bars):
        row = bars.iloc[idx]
        if not _time_between(row["dt"], time(10, 30), time(13, 0)):
            if row["dt"].time() > time(13, 0):
                break
            continue
        failed_high = (
            float(row["high"]) >= ib_high + TICK
            and float(row["close"]) < ib_high
            and float(row["close"]) > vwap[idx]
        )
        failed_low = (
            float(row["low"]) <= ib_low - TICK
            and float(row["close"]) > ib_low
            and float(row["close"]) < vwap[idx]
        )
        if failed_high == failed_low:
            continue
        side = -1 if failed_high else 1
        stop = float(row["high"]) + TICK if side < 0 else float(row["low"]) - TICK
        trade = _simulate(
            bars,
            strategy="ib_failure_to_vwap",
            side=side,
            signal_idx=idx,
            entry_idx=idx + 1 + entry_delay_bars,
            stop=stop,
            fixed_target=float(vwap[idx]),
            min_reward_risk=1.0,
        )
        if trade:
            return trade
    return None


def vwap_reclaim_retest(
    bars: pd.DataFrame,
    *,
    entry_delay_bars: int = 0,
    prior_opening_range_median: float | None = None,
) -> ReplicationTrade | None:
    del prior_opening_range_median
    if len(bars) < 25:
        return None
    vwap, _ = _live_vwap_and_std(bars)
    for reclaim_idx in range(20, len(bars) - 5 - entry_delay_bars):
        row = bars.iloc[reclaim_idx]
        if not _time_between(row["dt"], time(9, 45), time(13, 30)):
            if row["dt"].time() > time(13, 30):
                break
            continue
        prior_indices = range(reclaim_idx - 5, reclaim_idx)
        prior_below = all(float(bars.iloc[idx]["close"]) < vwap[idx] for idx in prior_indices)
        prior_above = all(float(bars.iloc[idx]["close"]) > vwap[idx] for idx in prior_indices)
        long_reclaim = prior_below and float(row["close"]) > vwap[reclaim_idx]
        short_reclaim = prior_above and float(row["close"]) < vwap[reclaim_idx]
        if long_reclaim == short_reclaim:
            continue
        side = 1 if long_reclaim else -1
        for retest_idx in range(reclaim_idx + 1, min(reclaim_idx + 4, len(bars) - 1 - entry_delay_bars)):
            retest = bars.iloc[retest_idx]
            midpoint = (float(retest["high"]) + float(retest["low"])) / 2.0
            if side > 0:
                confirmed = (
                    float(retest["low"]) <= vwap[retest_idx] + 2 * TICK
                    and float(retest["close"]) >= vwap[retest_idx]
                    and float(retest["close"]) >= midpoint
                )
                stop = float(retest["low"]) - TICK
            else:
                confirmed = (
                    float(retest["high"]) >= vwap[retest_idx] - 2 * TICK
                    and float(retest["close"]) <= vwap[retest_idx]
                    and float(retest["close"]) <= midpoint
                )
                stop = float(retest["high"]) + TICK
            if not confirmed:
                continue
            trade = _simulate(
                bars,
                strategy="vwap_reclaim_retest",
                side=side,
                signal_idx=retest_idx,
                entry_idx=retest_idx + 1 + entry_delay_bars,
                stop=stop,
                target_r=1.5,
                min_reward_risk=1.5,
            )
            if trade:
                return trade
    return None


def vwap_band_reentry(
    bars: pd.DataFrame,
    *,
    entry_delay_bars: int = 0,
    prior_opening_range_median: float | None = None,
) -> ReplicationTrade | None:
    del prior_opening_range_median
    if len(bars) < 35:
        return None
    vwap, std = _live_vwap_and_std(bars)
    for idx in range(30, len(bars) - 1 - entry_delay_bars):
        row = bars.iloc[idx]
        if not _time_between(row["dt"], time(10, 0), time(13, 30)):
            if row["dt"].time() > time(13, 30):
                break
            continue
        if not math.isfinite(std[idx]) or std[idx] < TICK:
            continue
        upper = vwap[idx] + 1.5 * std[idx]
        lower = vwap[idx] - 1.5 * std[idx]
        long_signal = float(row["open"]) < lower <= float(row["close"]) < vwap[idx]
        short_signal = float(row["open"]) > upper >= float(row["close"]) > vwap[idx]
        if long_signal == short_signal:
            continue
        side = 1 if long_signal else -1
        stop = float(row["low"]) - TICK if side > 0 else float(row["high"]) + TICK
        trade = _simulate(
            bars,
            strategy="vwap_band_reentry",
            side=side,
            signal_idx=idx,
            entry_idx=idx + 1 + entry_delay_bars,
            stop=stop,
            fixed_target=float(vwap[idx]),
            min_reward_risk=1.0,
        )
        if trade:
            return trade
    return None


def opening_drive_vwap_pullback(
    bars: pd.DataFrame,
    *,
    entry_delay_bars: int = 0,
    prior_opening_range_median: float | None = None,
) -> ReplicationTrade | None:
    if len(bars) < 25 or prior_opening_range_median is None:
        return None
    vwap, _ = _live_vwap_and_std(bars)
    opening = bars.iloc[:15]
    opening_high = float(opening["high"].max())
    opening_low = float(opening["low"].min())
    opening_range = opening_high - opening_low
    if opening_range <= 0 or opening_range < prior_opening_range_median:
        return None
    opening_close = float(opening.iloc[-1]["close"])
    displacement = opening_close - float(opening.iloc[0]["open"])
    close_location = (opening_close - opening_low) / opening_range
    long_drive = displacement >= 0.60 * opening_range and close_location >= 0.80 and opening_close > vwap[14]
    short_drive = displacement <= -0.60 * opening_range and close_location <= 0.20 and opening_close < vwap[14]
    if long_drive == short_drive:
        return None
    side = 1 if long_drive else -1
    for idx in range(15, len(bars) - 1 - entry_delay_bars):
        row = bars.iloc[idx]
        if row["dt"].time() > time(11, 30):
            break
        midpoint = (float(row["high"]) + float(row["low"])) / 2.0
        if side > 0:
            confirmed = (
                float(row["low"]) <= vwap[idx] + 2 * TICK
                and float(row["close"]) > vwap[idx]
                and float(row["close"]) >= midpoint
            )
            stop = float(row["low"]) - TICK
        else:
            confirmed = (
                float(row["high"]) >= vwap[idx] - 2 * TICK
                and float(row["close"]) < vwap[idx]
                and float(row["close"]) <= midpoint
            )
            stop = float(row["high"]) + TICK
        if not confirmed:
            continue
        trade = _simulate(
            bars,
            strategy="opening_drive_vwap_pullback",
            side=side,
            signal_idx=idx,
            entry_idx=idx + 1 + entry_delay_bars,
            stop=stop,
            target_r=2.0,
            min_reward_risk=2.0,
        )
        if trade:
            return trade
    return None


STRATEGIES: dict[str, Callable[..., ReplicationTrade | None]] = {
    "orb_breakout_control": orb_breakout_control,
    "ib_failure_to_vwap": ib_failure_to_vwap,
    "vwap_reclaim_retest": vwap_reclaim_retest,
    "vwap_band_reentry": vwap_band_reentry,
    "opening_drive_vwap_pullback": opening_drive_vwap_pullback,
}


def trade_pnl(trade: ReplicationTrade, *, cost_multiple: float = 1.0) -> float:
    if cost_multiple < 0:
        raise ValueError("cost_multiple must be non-negative")
    per_side_friction = COMMISSION_PER_SIDE + SLIPPAGE_TICKS_PER_SIDE * TICK * POINT_VALUE
    return trade.raw_points * POINT_VALUE - 2.0 * per_side_friction * cost_multiple


def execution_edge_budget(trades: list[ReplicationTrade]) -> dict[str, float | int | None]:
    """Report the maximum average friction the raw trade path can support.

    This is diagnostic only and is deliberately excluded from every promotion
    gate. A negative gross expectancy has no non-negative break-even budget.
    """
    if not trades:
        return {
            "trades": 0,
            "gross_expectancy_before_friction": None,
            "base_round_trip_friction": round(2 * (COMMISSION_PER_SIDE + TICK * POINT_VALUE), 2),
            "break_even_friction_per_side": None,
            "base_friction_per_side": round(COMMISSION_PER_SIDE + TICK * POINT_VALUE, 2),
            "edge_budget_survives_base_friction": False,
        }
    gross_expectancy = sum(trade.raw_points * POINT_VALUE for trade in trades) / len(trades)
    base_per_side = COMMISSION_PER_SIDE + SLIPPAGE_TICKS_PER_SIDE * TICK * POINT_VALUE
    return {
        "trades": len(trades),
        "gross_expectancy_before_friction": round(gross_expectancy, 4),
        "base_round_trip_friction": round(2 * base_per_side, 2),
        "break_even_friction_per_side": round(max(0.0, gross_expectancy / 2.0), 4),
        "base_friction_per_side": round(base_per_side, 2),
        "edge_budget_survives_base_friction": gross_expectancy > 2 * base_per_side,
    }


def _drawdown(pnls: list[float]) -> float:
    equity = 0.0
    peak = 0.0
    maximum = 0.0
    for pnl in pnls:
        equity += pnl
        peak = max(peak, equity)
        maximum = max(maximum, peak - equity)
    return maximum


def _loss_streak(pnls: list[float]) -> int:
    maximum = 0
    current = 0
    for pnl in pnls:
        current = current + 1 if pnl <= 0 else 0
        maximum = max(maximum, current)
    return maximum


def metrics(
    trades: list[ReplicationTrade],
    *,
    cost_multiple: float = 1.0,
    remove_top_pct: float = 0.0,
) -> dict[str, Any]:
    pnls = [trade_pnl(trade, cost_multiple=cost_multiple) for trade in trades]
    if remove_top_pct and pnls:
        remove_count = max(1, math.ceil(len(pnls) * remove_top_pct))
        for index in sorted(range(len(pnls)), key=pnls.__getitem__, reverse=True)[:remove_count]:
            pnls[index] = 0.0
    if not pnls:
        return {
            "trades": 0,
            "total_pnl": 0.0,
            "expectancy": None,
            "win_rate": None,
            "profit_factor": None,
            "max_drawdown": 0.0,
            "max_consecutive_losses": 0,
        }
    wins = [pnl for pnl in pnls if pnl > 0]
    losses = [pnl for pnl in pnls if pnl <= 0]
    gross_wins = sum(wins)
    gross_losses = -sum(losses)
    return {
        "trades": len(pnls),
        "total_pnl": round(sum(pnls), 2),
        "expectancy": round(sum(pnls) / len(pnls), 4),
        "win_rate": round(len(wins) / len(pnls), 4),
        "profit_factor": round(gross_wins / gross_losses, 4) if gross_losses else None,
        "average_win": round(gross_wins / len(wins), 4) if wins else None,
        "average_loss": round(sum(losses) / len(losses), 4) if losses else None,
        "max_drawdown": round(_drawdown(pnls), 2),
        "max_consecutive_losses": _loss_streak(pnls),
    }


def _quarter(day: str) -> str:
    stamp = pd.Timestamp(day)
    return f"{stamp.year}-Q{stamp.quarter}"


def _daily_pnls(trades: list[ReplicationTrade], dates: list[str], *, cost_multiple: float) -> list[float]:
    by_day = {trade.day: trade_pnl(trade, cost_multiple=cost_multiple) for trade in trades}
    return [float(by_day.get(day, 0.0)) for day in dates]


def block_bootstrap_mean(
    daily_pnls: list[float],
    *,
    samples: int = BOOTSTRAP_SAMPLES,
    block_size: int = BOOTSTRAP_BLOCK_SESSIONS,
    alpha: float = FAMILYWISE_ALPHA,
    seed: int = BOOTSTRAP_SEED,
) -> dict[str, Any]:
    if not daily_pnls:
        return {"sessions": 0, "samples": samples, "mean_daily_pnl": None, "lower_bound": None}
    if samples <= 0 or block_size <= 0 or not 0 < alpha < 1:
        raise ValueError("invalid bootstrap configuration")
    values = np.asarray(daily_pnls, dtype=float)
    rng = np.random.default_rng(seed)
    block_count = math.ceil(len(values) / block_size)
    means = np.empty(samples, dtype=float)
    offsets = np.arange(block_size)
    for idx in range(samples):
        starts = rng.integers(0, len(values), size=block_count)
        indices = (starts[:, None] + offsets[None, :]) % len(values)
        means[idx] = float(values[indices.ravel()[: len(values)]].mean())
    return {
        "sessions": len(values),
        "samples": samples,
        "block_size_sessions": block_size,
        "one_sided_alpha": alpha,
        "mean_daily_pnl": round(float(values.mean()), 6),
        "lower_bound": round(float(np.quantile(means, alpha)), 6),
        "probability_mean_positive": round(float(np.mean(means > 0)), 6),
    }


def _gate_results(row: dict[str, Any]) -> dict[str, bool]:
    selection = row["stages"]["selection_2025"]["double_cost"]
    holdout = row["stages"]["holdout_2026"]["double_cost"]
    aggregate = row["aggregate"]["double_cost"]
    annual = row["annual_double_cost"]
    quarter_values = list(row["quarterly_double_cost"].values())
    positive_quarters = sum((value.get("expectancy") or 0) > 0 for value in quarter_values)
    represented_quarters = len(quarter_values)
    return {
        "selection_sample": selection["trades"] >= 15,
        "holdout_sample": holdout["trades"] >= 8,
        "selection_edge": (selection.get("expectancy") or 0) > 0 and (selection.get("profit_factor") or 0) >= 1.10,
        "holdout_edge": (holdout.get("expectancy") or 0) > 0 and (holdout.get("profit_factor") or 0) >= 1.10,
        "every_year_positive": bool(annual) and all((value.get("expectancy") or 0) > 0 for value in annual.values()),
        "aggregate_edge": (aggregate.get("expectancy") or 0) > 0 and (aggregate.get("profit_factor") or 0) >= 1.15,
        "one_bar_delay": (row["aggregate"]["double_cost_one_bar_delay"].get("expectancy") or 0) > 0,
        "best_one_pct_removed": (row["aggregate"]["double_cost_without_top_1pct"].get("expectancy") or 0) > 0,
        "quarter_stability": represented_quarters > 0 and positive_quarters / represented_quarters >= 2 / 3,
        "bootstrap_lower_bound": (row["block_bootstrap"].get("lower_bound") or 0) > 0,
    }


def _rank(row: dict[str, Any]) -> tuple[Any, ...]:
    gates = row["gates"]
    return (
        row["historical_survivor"],
        sum(gates.values()),
        row["stages"]["holdout_2026"]["double_cost"].get("expectancy") or float("-inf"),
        row["aggregate"]["double_cost"].get("expectancy") or float("-inf"),
    )


def evaluate(
    frame: pd.DataFrame,
    *,
    bootstrap_samples: int = BOOTSTRAP_SAMPLES,
    combine_simulations: int = 5_000,
) -> dict[str, Any]:
    dates, sessions, skipped = prepare_sessions(frame)
    opening_ranges = {
        day: float(sessions[day].iloc[:15]["high"].max() - sessions[day].iloc[:15]["low"].min())
        for day in dates
    }
    prior_medians: dict[str, float | None] = {}
    for idx, day in enumerate(dates):
        history = [opening_ranges[prior] for prior in dates[max(0, idx - 20) : idx]]
        prior_medians[day] = median(history) if len(history) == 20 else None

    rows: list[dict[str, Any]] = []
    trade_cache: dict[str, list[ReplicationTrade]] = {}
    for strategy, builder in STRATEGIES.items():
        trades = [
            trade
            for day in dates
            if (
                trade := builder(
                    sessions[day],
                    entry_delay_bars=0,
                    prior_opening_range_median=prior_medians[day],
                )
            )
            is not None
        ]
        delayed = [
            trade
            for day in dates
            if (
                trade := builder(
                    sessions[day],
                    entry_delay_bars=1,
                    prior_opening_range_median=prior_medians[day],
                )
            )
            is not None
        ]
        trade_cache[strategy] = trades
        discovery = [trade for trade in trades if trade.day < SELECTION_START]
        selection = [trade for trade in trades if SELECTION_START <= trade.day < HOLDOUT_START]
        holdout = [trade for trade in trades if trade.day >= HOLDOUT_START]
        years = sorted({trade.day[:4] for trade in trades})
        quarters = sorted({_quarter(trade.day) for trade in trades})
        daily_double = _daily_pnls(trades, dates, cost_multiple=2.0)
        row = {
            "strategy": strategy,
            "public_source": PUBLIC_SOURCES[strategy],
            "stages": {
                "discovery_2024": {"base_cost": metrics(discovery), "double_cost": metrics(discovery, cost_multiple=2.0)},
                "selection_2025": {"base_cost": metrics(selection), "double_cost": metrics(selection, cost_multiple=2.0)},
                "holdout_2026": {"base_cost": metrics(holdout), "double_cost": metrics(holdout, cost_multiple=2.0)},
            },
            "annual_double_cost": {
                year: metrics([trade for trade in trades if trade.day.startswith(year)], cost_multiple=2.0)
                for year in years
            },
            "quarterly_double_cost": {
                quarter: metrics([trade for trade in trades if _quarter(trade.day) == quarter], cost_multiple=2.0)
                for quarter in quarters
            },
            "aggregate": {
                "frictionless": metrics(trades, cost_multiple=0.0),
                "base_cost": metrics(trades),
                "double_cost": metrics(trades, cost_multiple=2.0),
                "triple_cost": metrics(trades, cost_multiple=3.0),
                "double_cost_one_bar_delay": metrics(delayed, cost_multiple=2.0),
                "double_cost_without_top_1pct": metrics(trades, cost_multiple=2.0, remove_top_pct=0.01),
            },
            "execution_edge_budget": execution_edge_budget(trades),
            "block_bootstrap": block_bootstrap_mean(
                daily_double,
                samples=bootstrap_samples,
                seed=BOOTSTRAP_SEED + len(rows),
            ),
            "exit_reasons": pd.Series([trade.exit_reason for trade in trades]).value_counts().to_dict(),
            "trades": [asdict(trade) for trade in trades],
        }
        row["gates"] = _gate_results(row)
        row["historical_survivor"] = all(row["gates"].values())
        rows.append(row)

    rows.sort(key=_rank, reverse=True)
    survivors = [row["strategy"] for row in rows if row["historical_survivor"]]
    combine: dict[str, Any] = {}
    rules = CombineRules(max_sessions=252)
    for strategy in survivors:
        daily = _daily_pnls(trade_cache[strategy], dates, cost_multiple=2.0)
        combine[strategy] = {
            "method": "circular_block_bootstrap_of_2024plus_double_cost_daily_pnl_including_no_trade_sessions",
            "one_mes": bootstrap_combine(daily, contracts=1, rules=rules, simulations=combine_simulations),
            "two_mes": bootstrap_combine(daily, contracts=2, rules=rules, simulations=combine_simulations),
            "warning": "Consumed-history diagnostic; this cannot authorize a Combine purchase.",
        }

    return {
        "schema_version": 1,
        "experiment": EXPERIMENT,
        "preregistration": PREREGISTRATION,
        "mode": "research_only_consumed_history_diagnostic",
        "evidence_status": "not_independent_confirmation",
        "execution_enabled": False,
        "can_submit_orders": False,
        "orders_submitted": 0,
        "dataset_period": [dates[0], dates[-1]] if dates else None,
        "eligible_sessions": len(dates),
        "skipped_sessions": skipped,
        "chronology": {
            "discovery": "2024",
            "selection": "2025",
            "holdout": "2026 through dataset end",
            "warning": "Other repository experiments have consumed this history; the holdout is only sealed within this experiment.",
        },
        "execution_model": {
            "instrument": "MES",
            "contracts": 1,
            "next_bar_entry": True,
            "same_bar_ambiguity": "stop_first",
            "commission_per_side": COMMISSION_PER_SIDE,
            "slippage_ticks_per_side": SLIPPAGE_TICKS_PER_SIDE,
            "flatten_time_et": FLATTEN_TIME.isoformat(timespec="minutes"),
        },
        "family_attempts": len(STRATEGIES),
        "familywise_alpha": FAMILYWISE_ALPHA,
        "historical_survivor_count": len(survivors),
        "historical_survivors": survivors,
        "top_diagnostic_candidate": rows[0]["strategy"] if rows else None,
        "topstep_combine_diagnostics": combine,
        "promotion": {
            "ready": False,
            "decision": "frozen_forward_practice_review_required" if survivors else "historical_gate_failed",
            "requirements_before_any_execution_change": [
                "independent code review",
                "at least 60 resolved frozen forward-practice outcomes",
                "at least three forward calendar months",
                "positive forward 2x-cost expectancy and profit factor >= 1.20",
                "separate explicit human approval for any execution authority",
            ],
        },
        "limitations": [
            "Public descriptions are translated into deterministic rules; they do not verify any source trader's PnL.",
            "One-minute bars cannot reveal intrabar path, queue position, or live spread variation.",
            "Stop-first handling and friction stresses are conservative but cannot reproduce every real fill.",
            "Historical bootstrap resamples consumed outcomes and is not a forecast.",
        ],
        "all_candidates": rows,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--csv", type=Path, default=DEFAULT_CSV)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--bootstrap-samples", type=int, default=BOOTSTRAP_SAMPLES)
    parser.add_argument("--combine-simulations", type=int, default=5_000)
    args = parser.parse_args()
    report = evaluate(
        pd.read_csv(args.csv),
        bootstrap_samples=args.bootstrap_samples,
        combine_simulations=args.combine_simulations,
    )
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "experiment": report["experiment"],
        "dataset_period": report["dataset_period"],
        "eligible_sessions": report["eligible_sessions"],
        "historical_survivors": report["historical_survivors"],
        "top_diagnostic_candidate": report["top_diagnostic_candidate"],
        "candidates": [
            {
                "strategy": row["strategy"],
                "gates_passed": sum(row["gates"].values()),
                "historical_survivor": row["historical_survivor"],
                "double_cost": row["aggregate"]["double_cost"],
                "holdout_double_cost": row["stages"]["holdout_2026"]["double_cost"],
            }
            for row in report["all_candidates"]
        ],
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

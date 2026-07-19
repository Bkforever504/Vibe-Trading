#!/usr/bin/env python3
"""Replay backtester for MNQ/MES opening-range + VWAP prop-firm strategy.

Paper/replay only. No broker connection. Reads minute-bar CSVs grouped by
trading date, simulates one opening-range trade per day with configurable
slippage and commission, and reports win rate, profit factor, expectancy,
max drawdown, and Topstep consistency-rule violations.
"""
from __future__ import annotations

import argparse
import csv
import json
from collections import defaultdict
from dataclasses import asdict, dataclass, field
from datetime import date, datetime, time
from pathlib import Path
from typing import Literal

try:
    from strategies.topstep_prop_bot import (
        Candle,
        OpeningRangeConfig,
        build_first_pullback_signal,
        build_opening_range_signal,
        contract_for_symbol,
        load_candles_csv,
        session_vwap,
    )
except ModuleNotFoundError:
    from topstep_prop_bot import (
        Candle,
        OpeningRangeConfig,
        build_first_pullback_signal,
        build_opening_range_signal,
        contract_for_symbol,
        load_candles_csv,
        session_vwap,
    )

ExitReason = Literal["target", "stop", "eod", "partial_breakeven", "partial_target", "partial_eod"]
RTH_START = time(9, 30)


@dataclass(frozen=True)
class BacktestConfig:
    slippage_ticks: int = 1
    commission_per_rt: float = 4.00
    max_trades_per_day: int = 1
    daily_loss_limit: float = 1000.0
    session_entry_start_hour: int = 0
    session_entry_start_minute: int = 0
    session_entry_cutoff_hour: int = 13
    session_entry_cutoff_minute: int = 0
    consistency_rule_pct: float = 0.50
    fixed_stop_ticks: int | None = None  # overrides signal.stop with entry ± N ticks
    signal_type: str = "orb"  # "orb" or "pullback"
    pullback_tolerance_ticks: int = 4  # how close price must come to range level to count as pullback
    pullback_stop_ticks: int = 8  # ticks below range_high (long) or above range_low (short)
    require_daily_trend_confirm: bool = False
    daily_trend_sma_days: int = 20
    require_opening_gap_bias: bool = False
    min_opening_gap_pct: float = 0.0
    consistency_penalty_per_violation: float = 25.0
    require_ema_confirm: bool = False
    ema_period: int = 20
    require_live_vwap_confirm: bool = False
    require_volume_confirm: bool = False
    volume_lookback: int = 20
    min_volume_ratio: float = 1.0
    require_key_level_proximity: bool = False
    key_level_tolerance_ticks: int = 16
    require_bos_confirm: bool = False
    exit_model: str = "full_target_stop"
    require_vix_range: bool = False
    vix_csv_path: str = "examples/vix_daily.csv"
    vix_min: float = 15.0   # below = too calm, breakouts fail to follow through
    vix_max: float = 28.0   # above = too chaotic, stops blow through on news
    overnight_csv_path: str = ""  # path to nq_1h_overnight.csv; empty = disabled


@dataclass
class TradeResult:
    date: str
    entry_time: datetime
    exit_time: datetime | None
    side: str
    entry_price: float
    exit_price: float
    contracts: int
    pnl: float
    win: bool
    exit_reason: ExitReason
    rule_violations: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class BacktestResult:
    trades: list[TradeResult]
    total_pnl: float
    win_rate: float
    profit_factor: float
    expectancy: float
    max_drawdown: float
    rule_violations: list[str]
    days_traded: int
    days_no_signal: int
    consistency_adjusted_score: float = 0.0


@dataclass(frozen=True)
class ValidationSplitResult:
    train_end: str
    train: BacktestResult
    test: BacktestResult
    expectancy_gap: float
    profit_factor_gap: float | str
    win_rate_gap: float


def _within_session(ts: datetime, cfg: BacktestConfig) -> bool:
    start = ts.replace(
        hour=cfg.session_entry_start_hour,
        minute=cfg.session_entry_start_minute,
        second=0,
        microsecond=0,
    )
    cutoff = ts.replace(
        hour=cfg.session_entry_cutoff_hour,
        minute=cfg.session_entry_cutoff_minute,
        second=0,
        microsecond=0,
    )
    return start <= ts < cutoff


def _ema(values: list[float], period: int) -> float:
    if period <= 0:
        raise ValueError("ema_period must be positive")
    if not values:
        return 0.0
    alpha = 2 / (period + 1)
    ema = values[0]
    for value in values[1:]:
        ema = value * alpha + ema * (1 - alpha)
    return ema


def _passes_ema_confirm(candles: list[Candle], *, entry_idx: int, side: str, period: int) -> bool:
    if entry_idx < 0 or entry_idx >= len(candles):
        return False
    closes = [c.close for c in candles[: entry_idx + 1]]
    ema = _ema(closes, period)
    close = candles[entry_idx].close
    return close > ema if side == "buy" else close < ema


def _passes_volume_confirm(candles: list[Candle], *, entry_idx: int, lookback: int, min_ratio: float) -> bool:
    if lookback <= 0:
        raise ValueError("volume_lookback must be positive")
    if entry_idx <= 0 or entry_idx >= len(candles):
        return False
    start = max(0, entry_idx - lookback)
    prior = candles[start:entry_idx]
    if not prior:
        return False
    avg_volume = sum(c.volume for c in prior) / len(prior)
    if avg_volume <= 0:
        return False
    return candles[entry_idx].volume >= avg_volume * min_ratio


def _passes_live_vwap_confirm(candles: list[Candle], *, entry_idx: int, side: str) -> bool:
    live_vwap = session_vwap(candles[: entry_idx + 1])
    close = candles[entry_idx].close
    return close > live_vwap if side == "buy" else close < live_vwap


def _simulate_exit(
    candles: list[Candle],
    *,
    side: str,
    stop: float,
    target: float,
    fallback: Candle,
) -> tuple[float, datetime | None, ExitReason]:
    """Scan forward candles for stop or target. Stop takes priority on same candle."""
    for c in candles:
        if side == "buy":
            if c.low <= stop:
                return stop, c.timestamp, "stop"
            if c.high >= target:
                return target, c.timestamp, "target"
        else:
            if c.high >= stop:
                return stop, c.timestamp, "stop"
            if c.low <= target:
                return target, c.timestamp, "target"
    if candles:
        last = candles[-1]
        return last.close, last.timestamp, "eod"
    return fallback.close, fallback.timestamp, "eod"


def _simulate_partial_exit(
    candles: list[Candle],
    *,
    side: str,
    entry: float,
    stop: float,
    fallback: Candle,
) -> tuple[float, datetime | None, ExitReason]:
    """Half at 1R, move runner stop to breakeven, runner target at 2R."""
    risk = abs(entry - stop)
    if risk <= 0:
        return entry, fallback.timestamp, "eod"

    if side == "buy":
        one_r = entry + risk
        two_r = entry + risk * 2
        initial_stop = stop
        be_stop = entry
        partial_filled = False
        last = fallback
        for c in candles:
            last = c
            if not partial_filled:
                if c.low <= initial_stop:
                    return initial_stop, c.timestamp, "stop"
                if c.high >= one_r:
                    partial_filled = True
                    if c.high >= two_r:
                        return (one_r + two_r) / 2, c.timestamp, "partial_target"
            else:
                if c.low <= be_stop:
                    return (one_r + be_stop) / 2, c.timestamp, "partial_breakeven"
                if c.high >= two_r:
                    return (one_r + two_r) / 2, c.timestamp, "partial_target"
        if partial_filled:
            return (one_r + last.close) / 2, last.timestamp, "partial_eod"
        return last.close, last.timestamp, "eod"

    one_r = entry - risk
    two_r = entry - risk * 2
    initial_stop = stop
    be_stop = entry
    partial_filled = False
    last = fallback
    for c in candles:
        last = c
        if not partial_filled:
            if c.high >= initial_stop:
                return initial_stop, c.timestamp, "stop"
            if c.low <= one_r:
                partial_filled = True
                if c.low <= two_r:
                    return (one_r + two_r) / 2, c.timestamp, "partial_target"
        else:
            if c.high >= be_stop:
                return (one_r + be_stop) / 2, c.timestamp, "partial_breakeven"
            if c.low <= two_r:
                return (one_r + two_r) / 2, c.timestamp, "partial_target"
    if partial_filled:
        return (one_r + last.close) / 2, last.timestamp, "partial_eod"
    return last.close, last.timestamp, "eod"


def replay_day(
    candles: list[Candle],
    *,
    orb_config: OpeningRangeConfig,
    bt_config: BacktestConfig,
    symbol: str,
    day_pnl_running: float = 0.0,
    trades_today: int = 0,
    allowed_side: str | None = None,
    key_levels: dict[str, float] | None = None,
) -> list[TradeResult]:
    """Simulate up to one opening-range trade for a single trading day."""
    if trades_today >= bt_config.max_trades_per_day:
        return []
    if day_pnl_running <= -bt_config.daily_loss_limit:
        return []
    if len(candles) <= orb_config.range_minutes:
        return []

    if bt_config.signal_type == "pullback":
        result = build_first_pullback_signal(
            candles,
            orb_config,
            symbol=symbol,
            pullback_tolerance_ticks=bt_config.pullback_tolerance_ticks,
            pullback_stop_ticks=bt_config.pullback_stop_ticks,
            require_bos_confirm=bt_config.require_bos_confirm,
        )
        if result is None:
            return []
        signal, entry_idx = result
        trigger = candles[entry_idx]
    else:
        signal = build_opening_range_signal(candles, orb_config, symbol=symbol)
        if signal is None:
            return []
        entry_idx = orb_config.range_minutes
        trigger = candles[entry_idx]

    if allowed_side is not None and signal.side != allowed_side:
        return []

    if not _within_session(trigger.timestamp, bt_config):
        return []
    if bt_config.require_live_vwap_confirm and not _passes_live_vwap_confirm(candles, entry_idx=entry_idx, side=signal.side):
        return []
    if bt_config.require_ema_confirm and not _passes_ema_confirm(
        candles,
        entry_idx=entry_idx,
        side=signal.side,
        period=bt_config.ema_period,
    ):
        return []
    if bt_config.require_volume_confirm and not _passes_volume_confirm(
        candles,
        entry_idx=entry_idx,
        lookback=bt_config.volume_lookback,
        min_ratio=bt_config.min_volume_ratio,
    ):
        return []
    if bt_config.require_key_level_proximity:
        contract = contract_for_symbol(symbol)
        tolerance = bt_config.key_level_tolerance_ticks * contract.tick_size
        levels = list((key_levels or {}).values())
        if not levels or not any(abs(signal.entry - level) <= tolerance for level in levels):
            return []

    contract = contract_for_symbol(symbol)
    slippage = bt_config.slippage_ticks * contract.tick_size
    entry_price = signal.entry + slippage if signal.side == "buy" else signal.entry - slippage

    if bt_config.fixed_stop_ticks is not None:
        fixed_dist = bt_config.fixed_stop_ticks * contract.tick_size
        stop = entry_price - fixed_dist if signal.side == "buy" else entry_price + fixed_dist
        target = entry_price + fixed_dist * orb_config.reward_risk if signal.side == "buy" else entry_price - fixed_dist * orb_config.reward_risk
    else:
        stop = signal.stop
        target = signal.target

    candles_after = candles[entry_idx + 1 :]
    if bt_config.exit_model == "partial_1r_be_2r":
        exit_price, exit_time, exit_reason = _simulate_partial_exit(
            candles_after,
            side=signal.side,
            entry=entry_price,
            stop=stop,
            fallback=trigger,
        )
    elif bt_config.exit_model == "full_target_stop":
        exit_price, exit_time, exit_reason = _simulate_exit(
            candles_after,
            side=signal.side,
            stop=stop,
            target=target,
            fallback=trigger,
        )
    else:
        raise ValueError(f"Unsupported exit_model: {bt_config.exit_model}")

    if signal.side == "buy":
        gross = (exit_price - entry_price) * contract.point_value
    else:
        gross = (entry_price - exit_price) * contract.point_value

    pnl = round(gross - bt_config.commission_per_rt, 2)

    return [
        TradeResult(
            date=trigger.timestamp.date().isoformat(),
            entry_time=trigger.timestamp,
            exit_time=exit_time,
            side=signal.side,
            entry_price=round(entry_price, 4),
            exit_price=round(exit_price, 4),
            contracts=1,
            pnl=pnl,
            win=pnl > 0,
            exit_reason=exit_reason,
        )
    ]


def _group_by_date(candles: list[Candle]) -> dict[str, list[Candle]]:
    groups: dict[str, list[Candle]] = defaultdict(list)
    for c in candles:
        groups[c.timestamp.date().isoformat()].append(c)
    return dict(groups)


def build_daily_trend_sides(candles: list[Candle], *, sma_days: int = 20) -> dict[str, str | None]:
    """Return allowed trade side by date using prior completed daily closes.

    If the previous close is above its SMA, only longs are allowed on the
    current date. If below, only shorts are allowed. Equal/insufficient history
    returns None, which blocks entries when the filter is required.
    """
    if sma_days <= 0:
        raise ValueError("sma_days must be positive")

    days = _group_by_date(candles)
    dates = sorted(days.keys())
    closes = {date_str: days[date_str][-1].close for date_str in dates}
    sides: dict[str, str | None] = {}

    for idx, date_str in enumerate(dates):
        if idx < sma_days:
            sides[date_str] = None
            continue
        prior_dates = dates[idx - sma_days : idx]
        sma = sum(closes[d] for d in prior_dates) / sma_days
        prior_close = closes[dates[idx - 1]]
        if prior_close > sma:
            sides[date_str] = "buy"
        elif prior_close < sma:
            sides[date_str] = "sell"
        else:
            sides[date_str] = None
    return sides


def build_opening_gap_sides(candles: list[Candle], *, min_gap_pct: float = 0.0) -> dict[str, str | None]:
    """Return allowed side by date from prior close to current first open."""
    if min_gap_pct < 0:
        raise ValueError("min_gap_pct must be non-negative")

    days = _group_by_date(candles)
    dates = sorted(days.keys())
    sides: dict[str, str | None] = {}
    prior_close: float | None = None

    for date_str in dates:
        day = days[date_str]
        if prior_close is None or prior_close <= 0:
            sides[date_str] = None
        else:
            gap_pct = (day[0].open - prior_close) / prior_close
            if gap_pct >= min_gap_pct:
                sides[date_str] = "buy"
            elif gap_pct <= -min_gap_pct:
                sides[date_str] = "sell"
            else:
                sides[date_str] = None
        prior_close = day[-1].close

    return sides


def build_vix_filter(csv_path: str, *, vix_min: float, vix_max: float) -> dict[str, bool]:
    """Return {date_str: allowed} from a VIX daily CSV (date, vix_close columns).

    Dates where VIX is outside [vix_min, vix_max] map to False — skip those days.
    Missing dates map to False (conservative: block if no VIX data).
    """
    if not csv_path:
        return {}
    path = Path(csv_path)
    if not path.exists():
        return {}
    allowed: dict[str, bool] = {}
    with path.open("r", newline="", encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            try:
                date_str = row["date"][:10]
                vix = float(row["vix_close"])
                allowed[date_str] = vix_min <= vix <= vix_max
            except (ValueError, KeyError):
                pass
    return allowed


def build_prior_day_levels(candles: list[Candle]) -> dict[str, dict[str, float] | None]:
    """Return each date's previous completed day's key levels."""
    days = _group_by_date(candles)
    dates = sorted(days.keys())
    levels: dict[str, dict[str, float] | None] = {}
    prior_day: list[Candle] | None = None

    for date_str in dates:
        if prior_day is None:
            levels[date_str] = None
        else:
            day_levels = {
                "high": max(c.high for c in prior_day),
                "low": min(c.low for c in prior_day),
                "close": prior_day[-1].close,
            }
            premarket = [c for c in prior_day if c.timestamp.time() < RTH_START]
            if premarket:
                day_levels["premarket_high"] = max(c.high for c in premarket)
                day_levels["premarket_low"] = min(c.low for c in premarket)
            levels[date_str] = day_levels
        prior_day = days[date_str]

    return levels


def build_overnight_levels(csv_path: str) -> dict[str, dict[str, float]]:
    """Return {date_str: {overnight_high, overnight_low}} from the overnight CSV.

    The CSV is produced by scripts/fetch_nq_overnight.py.  Each row's date is
    the RTH session the overnight period precedes (pre-market + prior after-hours).
    """
    if not csv_path:
        return {}
    path = Path(csv_path)
    if not path.exists():
        return {}
    levels: dict[str, dict[str, float]] = {}
    with path.open("r", newline="", encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            try:
                date_str = row["date"][:10]
                levels[date_str] = {
                    "overnight_high": float(row["overnight_high"]),
                    "overnight_low":  float(row["overnight_low"]),
                }
            except (ValueError, KeyError):
                pass
    return levels


def _merge_key_levels(
    prior: dict[str, float] | None,
    overnight: dict[str, float] | None,
) -> dict[str, float] | None:
    """Combine prior-day H/L/close with overnight H/L into one flat dict."""
    merged: dict[str, float] = {}
    if prior:
        merged.update(prior)
    if overnight:
        merged.update(overnight)
    return merged if merged else None


def _merge_allowed_sides(*sides: str | None) -> str | None:
    active = [side for side in sides if side is not None]
    if not active:
        return None
    first = active[0]
    if all(side == first for side in active):
        return first
    return "__blocked__"


def consistency_adjusted_score(result: BacktestResult, *, penalty_per_violation: float = 25.0) -> float:
    return round(result.expectancy - len(result.rule_violations) * penalty_per_violation, 2)


def run_backtest(
    candles: list[Candle],
    *,
    orb_config: OpeningRangeConfig,
    bt_config: BacktestConfig,
    symbol: str,
) -> BacktestResult:
    """Replay all trading days; return aggregated metrics and rule violations."""
    days = _group_by_date(candles)
    trend_sides = (
        build_daily_trend_sides(candles, sma_days=bt_config.daily_trend_sma_days)
        if bt_config.require_daily_trend_confirm
        else {}
    )
    gap_sides = (
        build_opening_gap_sides(candles, min_gap_pct=bt_config.min_opening_gap_pct)
        if bt_config.require_opening_gap_bias
        else {}
    )
    prior_levels = build_prior_day_levels(candles) if bt_config.require_key_level_proximity else {}
    overnight_levels = build_overnight_levels(bt_config.overnight_csv_path)
    vix_allowed = (
        build_vix_filter(bt_config.vix_csv_path, vix_min=bt_config.vix_min, vix_max=bt_config.vix_max)
        if bt_config.require_vix_range
        else {}
    )
    all_trades: list[TradeResult] = []
    days_no_signal = 0
    rule_violations: list[str] = []

    cum_pnl = 0.0
    peak_pnl = 0.0
    max_drawdown = 0.0
    total_gross_profit = 0.0
    daily_profit: dict[str, float] = {}

    for date_str in sorted(days.keys()):
        if bt_config.require_vix_range and not vix_allowed.get(date_str, False):
            days_no_signal += 1
            continue
        day_trades = replay_day(
            days[date_str],
            orb_config=orb_config,
            bt_config=bt_config,
            symbol=symbol,
            allowed_side=_merge_allowed_sides(
                trend_sides.get(date_str) if bt_config.require_daily_trend_confirm else None,
                gap_sides.get(date_str) if bt_config.require_opening_gap_bias else None,
            ),
            key_levels=_merge_key_levels(
                prior_levels.get(date_str) if bt_config.require_key_level_proximity else None,
                overnight_levels.get(date_str),
            ),
        )

        if not day_trades:
            days_no_signal += 1
            continue

        for trade in day_trades:
            cum_pnl += trade.pnl

            if trade.pnl > 0:
                total_gross_profit += trade.pnl
                daily_profit[trade.date] = daily_profit.get(trade.date, 0.0) + trade.pnl

            peak_pnl = max(peak_pnl, cum_pnl)
            max_drawdown = max(max_drawdown, peak_pnl - cum_pnl)

            # Topstep 50% consistency rule: best single profitable day must
            # not exceed 50% of total gross profit. Only evaluated once there
            # are at least 2 different profitable days (first day is exempt).
            if total_gross_profit > 0 and len(daily_profit) >= 2:
                best_day = max(daily_profit.values())
                if best_day / total_gross_profit > bt_config.consistency_rule_pct:
                    if "consistency_rule" not in trade.rule_violations:
                        trade.rule_violations.append("consistency_rule")
                    violation_key = f"{trade.date}:consistency_rule"
                    if violation_key not in rule_violations:
                        rule_violations.append(violation_key)

        all_trades.extend(day_trades)

    if not all_trades:
        return BacktestResult(
            trades=[],
            total_pnl=0.0,
            win_rate=0.0,
            profit_factor=0.0,
            expectancy=0.0,
            max_drawdown=0.0,
            rule_violations=rule_violations,
            days_traded=0,
            days_no_signal=days_no_signal,
            consistency_adjusted_score=0.0,
        )

    wins = [t for t in all_trades if t.win]
    losses = [t for t in all_trades if not t.win]
    n = len(all_trades)
    win_rate = len(wins) / n
    gross_profit = sum(t.pnl for t in wins)
    gross_loss = abs(sum(t.pnl for t in losses))
    profit_factor = (gross_profit / gross_loss) if gross_loss > 0 else float("inf")
    avg_win = gross_profit / len(wins) if wins else 0.0
    avg_loss = gross_loss / len(losses) if losses else 0.0
    expectancy = (win_rate * avg_win) - ((1 - win_rate) * avg_loss)

    result = BacktestResult(
        trades=all_trades,
        total_pnl=round(cum_pnl, 2),
        win_rate=round(win_rate, 4),
        profit_factor=round(profit_factor, 4) if profit_factor != float("inf") else float("inf"),
        expectancy=round(expectancy, 2),
        max_drawdown=round(max_drawdown, 2),
        rule_violations=rule_violations,
        days_traded=len(set(t.date for t in all_trades)),
        days_no_signal=days_no_signal,
    )
    return BacktestResult(
        trades=result.trades,
        total_pnl=result.total_pnl,
        win_rate=result.win_rate,
        profit_factor=result.profit_factor,
        expectancy=result.expectancy,
        max_drawdown=result.max_drawdown,
        rule_violations=result.rule_violations,
        days_traded=result.days_traded,
        days_no_signal=result.days_no_signal,
        consistency_adjusted_score=consistency_adjusted_score(
            result,
            penalty_per_violation=bt_config.consistency_penalty_per_violation,
        ),
    )


def _coerce_date(value: str | date) -> date:
    if isinstance(value, date):
        return value
    return datetime.fromisoformat(value).date()


def split_train_test(candles: list[Candle], train_end: str | date) -> tuple[list[Candle], list[Candle]]:
    cutoff = _coerce_date(train_end)
    train: list[Candle] = []
    test: list[Candle] = []
    for candle in candles:
        if candle.timestamp.date() <= cutoff:
            train.append(candle)
        else:
            test.append(candle)
    return train, test


def _gap(test_value: float, train_value: float) -> float:
    return round(test_value - train_value, 4)


def _profit_factor_gap(test_pf: float, train_pf: float) -> float | str:
    if test_pf == float("inf") or train_pf == float("inf"):
        return "inf" if test_pf == train_pf else "n/a"
    return round(test_pf - train_pf, 4)


def run_validation_split(
    candles: list[Candle],
    *,
    train_end: str | date,
    orb_config: OpeningRangeConfig,
    bt_config: BacktestConfig,
    symbol: str,
) -> ValidationSplitResult:
    train_candles, test_candles = split_train_test(candles, train_end)
    train_result = run_backtest(train_candles, orb_config=orb_config, bt_config=bt_config, symbol=symbol)
    test_result = run_backtest(test_candles, orb_config=orb_config, bt_config=bt_config, symbol=symbol)
    train_end_text = _coerce_date(train_end).isoformat()
    return ValidationSplitResult(
        train_end=train_end_text,
        train=train_result,
        test=test_result,
        expectancy_gap=_gap(test_result.expectancy, train_result.expectancy),
        profit_factor_gap=_profit_factor_gap(test_result.profit_factor, train_result.profit_factor),
        win_rate_gap=_gap(test_result.win_rate, train_result.win_rate),
    )


def _to_json(result: BacktestResult) -> str:
    def _serialize(obj):
        if isinstance(obj, datetime):
            return obj.isoformat()
        if isinstance(obj, float) and obj == float("inf"):
            return "inf"
        raise TypeError(f"Not serializable: {type(obj)}")

    trades_out = []
    for t in result.trades:
        d = {
            "date": t.date,
            "entry_time": t.entry_time.isoformat(),
            "exit_time": t.exit_time.isoformat() if t.exit_time else None,
            "side": t.side,
            "entry_price": t.entry_price,
            "exit_price": t.exit_price,
            "contracts": t.contracts,
            "pnl": t.pnl,
            "win": t.win,
            "exit_reason": t.exit_reason,
            "rule_violations": t.rule_violations,
        }
        trades_out.append(d)

    out = {
        "summary": {
            "total_pnl": result.total_pnl,
            "win_rate": result.win_rate,
            "profit_factor": result.profit_factor if result.profit_factor != float("inf") else "inf",
            "expectancy": result.expectancy,
            "max_drawdown": result.max_drawdown,
            "days_traded": result.days_traded,
            "days_no_signal": result.days_no_signal,
            "rule_violations": result.rule_violations,
            "consistency_adjusted_score": result.consistency_adjusted_score,
        },
        "trades": trades_out,
    }
    return json.dumps(out, indent=2, default=_serialize)


def _summary_dict(result: BacktestResult) -> dict:
    return {
        "total_pnl": result.total_pnl,
        "win_rate": result.win_rate,
        "profit_factor": result.profit_factor if result.profit_factor != float("inf") else "inf",
        "expectancy": result.expectancy,
        "max_drawdown": result.max_drawdown,
        "days_traded": result.days_traded,
        "days_no_signal": result.days_no_signal,
        "rule_violations": result.rule_violations,
        "consistency_adjusted_score": result.consistency_adjusted_score,
    }


def _validation_to_json(result: ValidationSplitResult) -> str:
    out = {
        "validation": {
            "train_end": result.train_end,
            "expectancy_gap": result.expectancy_gap,
            "profit_factor_gap": result.profit_factor_gap,
            "win_rate_gap": result.win_rate_gap,
            "train": _summary_dict(result.train),
            "test": _summary_dict(result.test),
        }
    }
    return json.dumps(out, indent=2)


def main() -> None:
    parser = argparse.ArgumentParser(description="Topstep MNQ/MES replay backtester (paper only)")
    parser.add_argument("--csv", type=Path, required=True)
    parser.add_argument("--symbol", default="MNQ")
    parser.add_argument("--range-minutes", type=int, default=15)
    parser.add_argument("--min-breakout-points", type=float, default=2.0)
    parser.add_argument("--reward-risk", type=float, default=1.5)
    parser.add_argument("--slippage-ticks", type=int, default=1)
    parser.add_argument("--commission", type=float, default=4.00)
    parser.add_argument("--max-trades-per-day", type=int, default=1)
    parser.add_argument("--daily-loss-limit", type=float, default=1000.0)
    parser.add_argument("--cutoff-hour", type=int, default=13)
    parser.add_argument("--start-hour", type=int, default=0)
    parser.add_argument("--start-minute", type=int, default=0)
    parser.add_argument("--fixed-stop-ticks", type=int, default=None,
                        help="Override range stop with fixed N-tick stop from entry (e.g. 40 for 10pt on MNQ)")
    parser.add_argument("--signal-type", choices=["orb", "pullback"], default="orb")
    parser.add_argument("--pullback-tolerance-ticks", type=int, default=4)
    parser.add_argument("--pullback-stop-ticks", type=int, default=8)
    parser.add_argument("--train-end", default=None, help="Inclusive YYYY-MM-DD train/test split date")
    parser.add_argument("--require-daily-trend-confirm", action="store_true",
                        help="Only long above prior completed daily SMA, only short below it")
    parser.add_argument("--daily-trend-sma-days", type=int, default=20)
    parser.add_argument("--require-opening-gap-bias", action="store_true",
                        help="Only long after a gap up and only short after a gap down using prior close to first open")
    parser.add_argument("--min-opening-gap-pct", type=float, default=0.0,
                        help="Minimum absolute opening gap percentage, e.g. 0.003 for 0.3%%")
    parser.add_argument("--consistency-penalty", type=float, default=25.0,
                        help="Expectancy penalty per Topstep consistency-rule violation")
    parser.add_argument("--require-ema-confirm", action="store_true",
                        help="Only long above EMA and only short below EMA at entry")
    parser.add_argument("--ema-period", type=int, default=20)
    parser.add_argument("--require-live-vwap-confirm", action="store_true",
                        help="Only long above current session VWAP and only short below it at entry")
    parser.add_argument("--require-volume-confirm", action="store_true",
                        help="Require entry-candle volume to exceed average prior volume by min ratio")
    parser.add_argument("--volume-lookback", type=int, default=20)
    parser.add_argument("--min-volume-ratio", type=float, default=1.0)
    parser.add_argument("--require-key-level-proximity", action="store_true",
                        help="Require entry to be near prior-day high, low, or close")
    parser.add_argument("--key-level-tolerance-ticks", type=int, default=16)
    parser.add_argument("--require-bos-confirm", action="store_true",
                        help="Require a higher high/lower low after OR breakout before first pullback entry")
    parser.add_argument("--exit-model", choices=["full_target_stop", "partial_1r_be_2r"], default="full_target_stop")
    parser.add_argument("--require-vix-range", action="store_true",
                        help="Skip days where VIX is outside vix-min/vix-max (chop and news filter)")
    parser.add_argument("--vix-csv", type=str, default="examples/vix_daily.csv",
                        help="Path to VIX daily CSV (columns: date, vix_close)")
    parser.add_argument("--vix-min", type=float, default=15.0,
                        help="Minimum VIX close to allow trading (below = too calm)")
    parser.add_argument("--vix-max", type=float, default=28.0,
                        help="Maximum VIX close to allow trading (above = too chaotic)")
    parser.add_argument("--overnight-csv", type=str, default="",
                        help="Path to nq_1h_overnight.csv for Asian/pre-market H/L key levels")
    args = parser.parse_args()

    candles = load_candles_csv(args.csv)
    orb = OpeningRangeConfig(
        range_minutes=args.range_minutes,
        min_breakout_points=args.min_breakout_points,
        reward_risk=args.reward_risk,
    )
    bt = BacktestConfig(
        slippage_ticks=args.slippage_ticks,
        commission_per_rt=args.commission,
        max_trades_per_day=args.max_trades_per_day,
        daily_loss_limit=args.daily_loss_limit,
        session_entry_start_hour=args.start_hour,
        session_entry_start_minute=args.start_minute,
        session_entry_cutoff_hour=args.cutoff_hour,
        fixed_stop_ticks=args.fixed_stop_ticks,
        signal_type=args.signal_type,
        pullback_tolerance_ticks=args.pullback_tolerance_ticks,
        pullback_stop_ticks=args.pullback_stop_ticks,
        require_daily_trend_confirm=args.require_daily_trend_confirm,
        daily_trend_sma_days=args.daily_trend_sma_days,
        require_opening_gap_bias=args.require_opening_gap_bias,
        min_opening_gap_pct=args.min_opening_gap_pct,
        consistency_penalty_per_violation=args.consistency_penalty,
        require_ema_confirm=args.require_ema_confirm,
        ema_period=args.ema_period,
        require_live_vwap_confirm=args.require_live_vwap_confirm,
        require_volume_confirm=args.require_volume_confirm,
        volume_lookback=args.volume_lookback,
        min_volume_ratio=args.min_volume_ratio,
        require_key_level_proximity=args.require_key_level_proximity,
        key_level_tolerance_ticks=args.key_level_tolerance_ticks,
        require_bos_confirm=args.require_bos_confirm,
        exit_model=args.exit_model,
        require_vix_range=args.require_vix_range,
        vix_csv_path=args.vix_csv,
        vix_min=args.vix_min,
        vix_max=args.vix_max,
        overnight_csv_path=args.overnight_csv,
    )
    if args.train_end:
        split = run_validation_split(candles, train_end=args.train_end, orb_config=orb, bt_config=bt, symbol=args.symbol)
        print(_validation_to_json(split))
    else:
        result = run_backtest(candles, orb_config=orb, bt_config=bt, symbol=args.symbol)
        print(_to_json(result))


if __name__ == "__main__":
    main()

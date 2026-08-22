#!/usr/bin/env python3
"""Research-only rule engines for five Milkman Trades candidates.

The module creates deterministic candidate and exit decisions. It has no
broker imports, credentials, order methods, scheduler registration, or
authority to alter production strategy gates.
"""
from __future__ import annotations

import argparse
import json
import math
from dataclasses import asdict, dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = ROOT / "data" / "milkman_strategy_suite_status.json"

SOURCE_URLS = {
    "spx_weekly_atr": "https://milkmantrades.com/atr-premium-selling.html",
    "daily_bilbo": "https://milkmantrades.com/bilbo-daily.html",
    "bilbo_options_v2": "https://milkmantrades.com/bilbo-box-options-v2.html",
    "swing_golden_gate": "https://milkmantrades.com/swing-gg-stocks.html",
    "zero_dte_pin": "https://milkmantrades.com/#strategies",
}


def _finite(value: Any, name: str) -> float:
    result = float(value)
    if not math.isfinite(result):
        raise ValueError(f"{name} must be finite")
    return result


def _blocked(strategy: str, reason: str, **details: Any) -> dict[str, Any]:
    return {
        "strategy": strategy,
        "status": "blocked",
        "reason": reason,
        "execution_enabled": False,
        "can_submit_orders": False,
        **details,
    }


def _candidate(strategy: str, **details: Any) -> dict[str, Any]:
    return {
        "strategy": strategy,
        "status": "shadow_candidate",
        "execution_enabled": False,
        "can_submit_orders": False,
        **details,
    }


def round_half_up(value: float, increment: float = 5.0) -> float:
    value = _finite(value, "value")
    increment = _finite(increment, "increment")
    if increment <= 0:
        raise ValueError("increment must be positive")
    return math.floor((value / increment) + 0.5) * increment


def spx_weekly_atr_candidate(
    prior_week_close: float,
    prior_week_atr14: float,
    *,
    short_bid: float | None = None,
    long_ask: float | None = None,
) -> dict[str, Any]:
    """Construct the exact strike geometry and natural-fill research mark."""
    close = _finite(prior_week_close, "prior_week_close")
    atr = _finite(prior_week_atr14, "prior_week_atr14")
    if close <= 0 or atr <= 0:
        raise ValueError("price and ATR must be positive")
    short_strike = round_half_up(close - atr, 5.0)
    long_strike = short_strike - 50.0
    geometry = {
        "short_strike": short_strike,
        "long_strike": long_strike,
        "wing_width_points": 50.0,
        "expiry": "last_SPXW_session_of_current_week",
        "entry_time_et": "10:00_first_trading_day",
        "exit": "hold_to_cash_settlement",
        "source_credit_to_risk_global_gate_applicable": False,
    }
    if short_bid is None or long_ask is None:
        return _blocked(
            "spx_weekly_minus_1atr_put_spread",
            "point_in_time_natural_quotes_required",
            geometry=geometry,
        )
    credit = _finite(short_bid, "short_bid") - _finite(long_ask, "long_ask")
    if credit <= 0:
        return _blocked(
            "spx_weekly_minus_1atr_put_spread",
            "non_positive_natural_credit",
            geometry=geometry,
            natural_credit_points=round(credit, 4),
        )
    return _candidate(
        "spx_weekly_minus_1atr_put_spread",
        geometry=geometry,
        natural_credit_points=round(credit, 4),
        max_loss_dollars=round((50.0 - credit) * 100.0, 2),
        evidence_state="quote_observation_only",
    )


@dataclass(frozen=True)
class CompressionBar:
    session_date: date
    open: float
    high: float
    low: float
    close: float
    compression: bool
    ema21: float | None = None
    ema50: float | None = None

    def __post_init__(self) -> None:
        for name in ("open", "high", "low", "close"):
            _finite(getattr(self, name), name)
        if self.high < self.low:
            raise ValueError("bar high cannot be below bar low")


@dataclass(frozen=True)
class CompressionBox:
    start_index: int
    lock_index: int
    start_date: date
    lock_date: date
    high: float
    low: float
    compression_bars: int


def first_five_compression_boxes(bars: Sequence[CompressionBar]) -> list[CompressionBox]:
    """Lock first-five boxes without using the resolution bar intraday."""
    boxes: list[CompressionBox] = []
    episode: list[tuple[int, CompressionBar]] = []

    def lock_episode() -> None:
        if not episode:
            return
        selected = episode[:5]
        first_index, first = selected[0]
        lock_index, locked = selected[-1]
        boxes.append(
            CompressionBox(
                start_index=first_index,
                lock_index=lock_index,
                start_date=first.session_date,
                lock_date=locked.session_date,
                high=max(row.high for _, row in selected),
                low=min(row.low for _, row in selected),
                compression_bars=len(selected),
            )
        )

    for index, bar in enumerate(bars):
        if bar.compression:
            episode.append((index, bar))
            continue
        if episode:
            lock_episode()
            episode = []
    if episode:
        lock_episode()
    return boxes


def daily_bilbo_entry(
    bars: Sequence[CompressionBar],
    box: CompressionBox,
    *,
    working_days: int = 20,
) -> dict[str, Any]:
    """Replay the armable daily breakout entry after a box is locked."""
    if working_days <= 0:
        raise ValueError("working_days must be positive")
    start = box.lock_index + 1
    stop = min(len(bars), start + working_days)
    for index in range(start, stop):
        bar = bars[index]
        previous = bars[index - 1]
        touched_low = bar.low <= box.low
        touched_high = bar.high >= box.high
        if touched_low:
            return _blocked(
                "daily_bilbo_equity_breakout",
                "box_low_touched_before_entry",
                decision_date=bar.session_date.isoformat(),
                conservative_same_bar_ordering=touched_high,
            )
        if not touched_high:
            continue
        if previous.ema21 is None or previous.close <= previous.ema21:
            continue
        fill = max(bar.open, box.high)
        return _candidate(
            "daily_bilbo_equity_breakout",
            entry_date=bar.session_date.isoformat(),
            entry_price=round(fill, 6),
            initial_stop=round(box.low, 6),
            box=asdict(box),
            exit_policy="ratchet_to_prior_daily_ema50_with_optional_scr3",
            compression_source="externally_verified_saty_phase_oscillator_state",
        )
    return _blocked(
        "daily_bilbo_equity_breakout",
        "working_order_expired_without_eligible_breakout",
        working_days=working_days,
    )


def daily_bilbo_exit(
    *,
    current_open: float,
    current_low: float,
    current_close: float,
    prior_ema50: float,
    current_stop: float,
    box_high: float,
    sessions_since_entry: int,
    scratch_three_day: bool,
    earnings_next_session: bool = False,
) -> dict[str, Any]:
    stop = max(_finite(current_stop, "current_stop"), _finite(prior_ema50, "prior_ema50"))
    open_price = _finite(current_open, "current_open")
    low = _finite(current_low, "current_low")
    close = _finite(current_close, "current_close")
    if low <= stop:
        return {
            "action": "shadow_exit",
            "reason": "initial_or_ema50_stop",
            "fill_price": round(min(open_price, stop), 6),
            "next_stop": round(stop, 6),
        }
    if earnings_next_session:
        return {
            "action": "shadow_exit",
            "reason": "flatten_before_earnings",
            "fill_price": round(close, 6),
            "next_stop": round(stop, 6),
        }
    if scratch_three_day and sessions_since_entry <= 3 and close < box_high:
        return {
            "action": "shadow_exit",
            "reason": "scr3_close_back_inside_box",
            "fill_price": round(close, 6),
            "next_stop": round(stop, 6),
        }
    return {"action": "hold", "next_stop": round(stop, 6)}


@dataclass(frozen=True)
class OptionQuote:
    symbol: str
    expiry: date
    strike: float
    bid: float
    ask: float

    @property
    def mid(self) -> float:
        return (self.bid + self.ask) / 2.0

    @property
    def spread_pct(self) -> float | None:
        return (self.ask - self.bid) / self.mid if self.bid > 0 and self.ask >= self.bid and self.mid > 0 else None


def select_bilbo_option(
    *,
    as_of: date,
    spot: float,
    daily_atr14: float,
    quotes: Sequence[OptionQuote],
) -> dict[str, Any]:
    spot_value = _finite(spot, "spot")
    atr = _finite(daily_atr14, "daily_atr14")
    eligible = [
        quote
        for quote in quotes
        if 21 <= (quote.expiry - as_of).days <= 37 and quote.spread_pct is not None
    ]
    if not eligible:
        return _blocked("bilbo_box_options_v2", "no_two_sided_quote_in_21_37_dte")
    expiry = min({quote.expiry for quote in eligible}, key=lambda value: (abs((value - as_of).days - 28), value))
    target_strike = spot_value + 0.75 * atr
    expiry_quotes = [quote for quote in eligible if quote.expiry == expiry]
    quote = min(expiry_quotes, key=lambda value: (abs(value.strike - target_strike), value.strike))
    if quote.spread_pct is None or quote.spread_pct > 0.05:
        return _blocked(
            "bilbo_box_options_v2",
            "option_spread_above_5pct",
            contract=quote.symbol,
            spread_pct=quote.spread_pct,
        )
    modeled_fill = quote.mid + 0.5 * (quote.ask - quote.mid)
    return _candidate(
        "bilbo_box_options_v2",
        contract=quote.symbol,
        expiry=quote.expiry.isoformat(),
        dte=(quote.expiry - as_of).days,
        strike=quote.strike,
        target_strike=round(target_strike, 6),
        quote={"bid": quote.bid, "ask": quote.ask, "spread_pct": round(quote.spread_pct, 6)},
        modeled_entry_fill=round(modeled_fill, 6),
        source_allocation_pct=4.0,
        research_risk_cap_pct=2.0,
    )


def bilbo_option_entry_gate(
    *,
    confirmed_hour_close: float,
    box_high: float,
    signal_volume: float,
    same_clock_median_volume_20: float,
    prior_daily_close: float,
    prior_daily_ema21: float,
    confirming_hour_et: int,
    weekday: int,
) -> dict[str, Any]:
    gates = {
        "published_entry_window": 10 <= confirming_hour_et <= 15 and 0 <= weekday <= 4,
        "confirmed_close_above_box": confirmed_hour_close > box_high,
        "same_clock_volume_confirmation": signal_volume >= same_clock_median_volume_20,
        "prior_daily_uptrend": prior_daily_close > prior_daily_ema21,
    }
    return {
        "eligible": all(gates.values()),
        "gates": gates,
        "entry_timing": "after_confirming_hourly_close_only",
    }


def bilbo_option_exit(
    *,
    current_underlying_close_5m: float,
    box_low: float,
    entry_underlying: float,
    daily_atr14_at_entry: float,
    peak_underlying: float,
    trading_days_held: int,
) -> dict[str, Any]:
    current = _finite(current_underlying_close_5m, "current_underlying_close_5m")
    entry = _finite(entry_underlying, "entry_underlying")
    peak = max(_finite(peak_underlying, "peak_underlying"), current)
    atr = _finite(daily_atr14_at_entry, "daily_atr14_at_entry")
    if current < box_low:
        return {"action": "shadow_exit", "reason": "five_minute_close_below_box_low"}
    trail_armed = peak >= entry + atr
    trail_level = entry + 0.25 * (peak - entry)
    if trail_armed and current <= trail_level:
        return {
            "action": "shadow_exit",
            "reason": "giveback_75pct_after_plus_1atr",
            "trail_level": round(trail_level, 6),
        }
    if trading_days_held >= 10:
        return {"action": "shadow_exit", "reason": "ten_trading_day_cap"}
    return {"action": "hold", "trail_armed": trail_armed, "trail_level": round(trail_level, 6)}


@dataclass(frozen=True)
class SwingGoldenGateLevels:
    pivot: float
    open_trigger: float
    entry: float
    target: float
    stop: float


def swing_golden_gate_levels(prior_month_close: float, prior_month_atr14: float) -> SwingGoldenGateLevels:
    pivot = _finite(prior_month_close, "prior_month_close")
    atr = _finite(prior_month_atr14, "prior_month_atr14")
    if pivot <= 0 or atr <= 0:
        raise ValueError("price and ATR must be positive")
    return SwingGoldenGateLevels(
        pivot=pivot,
        open_trigger=pivot - 0.382 * atr,
        entry=pivot - 0.618 * atr,
        target=pivot - atr,
        stop=pivot,
    )


def swing_golden_gate_entry(
    *,
    levels: SwingGoldenGateLevels,
    gate_opened_above_prior_ema21: bool,
    gate_was_opened: bool,
    current_open: float,
    current_low: float,
) -> dict[str, Any]:
    if not gate_opened_above_prior_ema21:
        return _blocked("swing_golden_gate_short", "gate_opened_without_uptrend")
    if not gate_was_opened:
        return _blocked("swing_golden_gate_short", "minus_0382_gate_not_opened")
    if current_low > levels.entry:
        return _blocked("swing_golden_gate_short", "minus_0618_entry_not_reached")
    fill = min(_finite(current_open, "current_open"), levels.entry)
    return _candidate(
        "swing_golden_gate_short",
        side="short_stock_research_expression",
        entry_price=round(fill, 6),
        target=round(levels.target, 6),
        stop=round(levels.stop, 6),
        expiry="month_end_if_target_or_stop_not_hit",
        cluster_risk_budget_required=True,
    )


def swing_golden_gate_exit(
    *,
    levels: SwingGoldenGateLevels,
    current_open: float,
    current_high: float,
    current_low: float,
    month_end: bool,
    current_close: float,
) -> dict[str, Any]:
    if current_high >= levels.stop:
        return {
            "action": "shadow_exit",
            "reason": "pivot_stop_stop_first_same_bar",
            "fill_price": round(max(current_open, levels.stop), 6),
        }
    if current_low <= levels.target:
        return {"action": "shadow_exit", "reason": "minus_1atr_target", "fill_price": levels.target}
    if month_end:
        return {"action": "shadow_exit", "reason": "month_end", "fill_price": current_close}
    return {"action": "hold"}


def zero_dte_pin_convergence_candidate(context: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """Fail closed until the source publishes deterministic rules and evidence."""
    supplied = sorted(str(key) for key in (context or {}).keys())
    return _blocked(
        "zero_dte_pin_convergence",
        "source_strategy_coming_soon_no_reproducible_specification",
        supplied_context_fields=supplied,
        required_before_implementation=[
            "pin_definition",
            "gamma_data_source_and_snapshot_time",
            "entry_window",
            "structure_selection",
            "entry_thresholds",
            "exit_rules",
            "fill_model",
            "frozen_validation_sample",
        ],
    )


def build_suite_report() -> dict[str, Any]:
    return {
        "schema_version": 1,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "mode": "research_and_shadow_only",
        "execution_enabled": False,
        "can_submit_orders": False,
        "can_change_production_gates_or_sizing": False,
        "sources": SOURCE_URLS,
        "candidates": {
            "spx_weekly_atr": {
                "implementation": "exact_geometry_plus_natural_quote_gate",
                "existing_audit": "research/spx_weekly_atr_put_spread_lab.py",
                "status": "awaiting_historical_spxw_quotes_and_forward_shadow",
            },
            "daily_bilbo": {
                "implementation": "first_five_box_entry_and_exit_engine",
                "status": "awaiting_verified_phase_oscillator_compression_series",
            },
            "bilbo_options_v2": {
                "implementation": "entry_gates_contract_selection_and_underlying_exit_engine",
                "status": "awaiting_verified_phase_oscillator_compression_series_and_forward_quotes",
            },
            "swing_golden_gate": {
                "implementation": "monthly_level_short_entry_and_exit_engine",
                "status": "independent_replay_required_broker_bar_conflict",
            },
            "zero_dte_pin": asdict_status(zero_dte_pin_convergence_candidate()),
        },
        "portfolio_constraints": {
            "max_single_candidate_risk_pct": 0.5,
            "max_correlated_cluster_risk_pct": 1.0,
            "source_sizing_is_not_accepted": True,
            "strategy_specific_economics_required": True,
        },
    }


def asdict_status(decision: Mapping[str, Any]) -> dict[str, Any]:
    return {key: decision[key] for key in ("status", "reason") if key in decision}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--print", action="store_true", dest="print_report")
    args = parser.parse_args()
    report = build_suite_report()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    if args.print_report:
        print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

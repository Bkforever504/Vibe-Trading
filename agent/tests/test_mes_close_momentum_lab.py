from __future__ import annotations

from datetime import datetime, timedelta

from research.mes_close_momentum_lab import (
    CloseMomentumConfig,
    _daily_setup,
    _trade_pnl,
    chronological_partitions,
)
from strategies.topstep_prop_bot import Candle


def _day(*, opening_up: bool = True, stop_out: bool = False) -> list[Candle]:
    start = datetime(2026, 7, 1, 9, 30)
    bars: list[Candle] = []
    for minute in range(390):
        timestamp = start + timedelta(minutes=minute)
        price = 100.0
        if minute >= 29:
            price = 101.0 if opening_up else 99.0
        if minute == 389:
            price = 102.0 if opening_up else 98.0
        low = price - (6.0 if stop_out and minute == 361 and opening_up else 0.25)
        high = price + (6.0 if stop_out and minute == 361 and not opening_up else 0.25)
        bars.append(Candle(timestamp, price, high, low, price, 100))
    return bars


def test_daily_setup_uses_first_and_final_half_hours() -> None:
    setup = _daily_setup(_day(opening_up=True))
    assert setup is not None
    assert setup["opening_return"] > 0
    assert len(setup["final_bars"]) == 30


def test_trade_follows_opening_direction_and_applies_costs() -> None:
    setup = _daily_setup(_day(opening_up=True))
    assert setup is not None
    pnl = _trade_pnl(setup, CloseMomentumConfig(0.0, 20), doubled_costs=False)
    assert pnl == -1.5


def test_stop_caps_adverse_move() -> None:
    setup = _daily_setup(_day(opening_up=True, stop_out=True))
    assert setup is not None
    pnl = _trade_pnl(setup, CloseMomentumConfig(0.0, 20), doubled_costs=False)
    assert pnl == -31.5


def test_chronological_partitions_are_complete() -> None:
    dates = [f"day-{index:03d}" for index in range(100)]
    development, selection, final_test = chronological_partitions(dates)
    assert [len(development), len(selection), len(final_test)] == [70, 15, 15]
    assert development + selection + final_test == dates

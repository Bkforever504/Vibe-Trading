from __future__ import annotations

import sys
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from strategies.topstep_prop_bot import Candle, OpeningRangeConfig, build_first_pullback_signal
from strategies.topstep_replay_backtester import (
    BacktestConfig,
    build_daily_trend_sides,
    build_opening_gap_sides,
    build_prior_day_levels,
    consistency_adjusted_score,
    replay_day,
    run_backtest,
    run_validation_split,
    split_train_test,
)

# Shared ORB config used across most tests:
#   range_minutes=2, min_breakout_points=0.5, reward_risk=1.5
# This gives consistent, predictable signals.
_ORB = OpeningRangeConfig(range_minutes=2, min_breakout_points=0.5, reward_risk=1.5)

# BacktestConfig with no slippage and no commission for clean P&L math.
_CLEAN = BacktestConfig(slippage_ticks=0, commission_per_rt=0.0)


# ---------------------------------------------------------------------------
# Candle helpers
# ---------------------------------------------------------------------------

def _c(minute: int, open_: float, high: float, low: float, close: float, volume: int = 100, base: datetime | None = None) -> Candle:
    b = base or datetime(2026, 6, 22, 9, 30)
    return Candle(timestamp=b + timedelta(minutes=minute), open=open_, high=high, low=low, close=close, volume=volume)


def _long_day(*, date: datetime | None = None, exit_high: float = 115.0, exit_low: float = 108.0) -> list[Candle]:
    """Opening range high=102 low=98, trigger at 103.5 (long). Target=111.75."""
    base = date or datetime(2026, 6, 22, 9, 30)
    return [
        _c(0, 100, 102, 98, 100, 100, base),    # opening range candle 1
        _c(1, 100, 101, 99, 100, 100, base),    # opening range candle 2
        _c(2, 100, 105, 103, 103.5, 50, base),  # trigger: close=103.5 > 102.5, above VWAP
        _c(3, 103, exit_high, exit_low, 110, 100, base),  # post-entry
    ]


def _long_day_stop(*, date: datetime | None = None) -> list[Candle]:
    """Same signal but stop is hit: exit_high=102, exit_low=97 → low<=98=stop."""
    base = date or datetime(2026, 6, 22, 9, 30)
    return [
        _c(0, 100, 102, 98, 100, 100, base),
        _c(1, 100, 101, 99, 100, 100, base),
        _c(2, 100, 105, 103, 103.5, 50, base),
        _c(3, 103, 102, 97, 98, 100, base),  # low=97 <= stop=98
    ]


def _wide_long_day(*, date: datetime | None = None) -> list[Candle]:
    """Wide opening range: high=110 low=90, trigger at 112. Target=112+(112-90)*1.5=145."""
    base = date or datetime(2026, 6, 23, 9, 30)
    return [
        _c(0, 100, 110, 90, 100, 100, base),
        _c(1, 100, 109, 91, 100, 100, base),
        _c(2, 100, 115, 111, 112, 50, base),   # trigger: 112 >= 110.5, above VWAP
        _c(3, 112, 150, 140, 145, 100, base),  # high=150 >= target=145
    ]


def _no_signal_day(*, date: datetime | None = None) -> list[Candle]:
    """Candles that never break the opening range."""
    base = date or datetime(2026, 6, 22, 9, 30)
    return [
        _c(0, 100, 102, 98, 100, 100, base),
        _c(1, 100, 101, 99, 100, 100, base),
        _c(2, 100, 101, 99, 100, 50, base),    # close=100, does not break range_high=102
        _c(3, 100, 101, 99, 100, 100, base),
    ]


def _flat_day(*, date: datetime, close: float) -> list[Candle]:
    """Non-signal day whose last candle supplies a daily close for trend tests."""
    return [
        _c(0, close, close + 1, close - 1, close, 100, date),
        _c(1, close, close + 1, close - 1, close, 100, date),
        _c(2, close, close + 0.25, close - 0.25, close, 100, date),
    ]


def _late_trigger_day(*, date: datetime | None = None) -> list[Candle]:
    """Trigger candle timestamped at 13:00 ET — after session cutoff."""
    base = date or datetime(2026, 6, 22, 12, 58)
    return [
        _c(0, 100, 102, 98, 100, 100, base),
        _c(1, 100, 101, 99, 100, 100, base),
        _c(2, 100, 105, 103, 103.5, 50, base),  # 12:58 + 2min = 13:00, cutoff blocks
        _c(3, 103, 115, 108, 110, 100, base),
    ]


def _early_trigger_day(*, date: datetime | None = None) -> list[Candle]:
    """Trigger candle timestamped before a configured 10:00 entry window."""
    base = date or datetime(2026, 6, 22, 9, 30)
    return [
        _c(0, 100, 102, 98, 100, 100, base),
        _c(1, 100, 101, 99, 100, 100, base),
        _c(2, 100, 105, 103, 103.5, 50, base),  # 9:32 in this synthetic minute-bar test
        _c(3, 103, 115, 108, 110, 100, base),
    ]


def _pullback_long_below_ema(*, date: datetime | None = None) -> list[Candle]:
    """A valid pullback long whose entry close is below a short EMA after a sharp breakout."""
    base = date or datetime(2026, 6, 22, 9, 30)
    return [
        _c(0, 100, 102, 98, 100, 100, base),
        _c(1, 100, 101, 99, 100, 100, base),
        _c(2, 100, 140, 103, 138, 200, base),  # breakout lifts EMA sharply
        _c(3, 108, 103, 101, 102.5, 80, base), # pullback entry below 3-EMA
        _c(4, 103, 130, 102, 125, 100, base),
    ]


def _long_day_low_volume(*, date: datetime | None = None) -> list[Candle]:
    base = date or datetime(2026, 6, 22, 9, 30)
    return [
        _c(0, 100, 102, 98, 100, 200, base),
        _c(1, 100, 101, 99, 100, 200, base),
        _c(2, 100, 105, 103, 103.5, 50, base),
        _c(3, 103, 115, 108, 110, 100, base),
    ]


def _partial_then_breakeven_day(*, date: datetime | None = None) -> list[Candle]:
    base = date or datetime(2026, 6, 22, 9, 30)
    return [
        _c(0, 100, 102, 98, 100, 100, base),
        _c(1, 100, 101, 99, 100, 100, base),
        _c(2, 100, 105, 103, 103.5, 50, base),  # entry, stop=98, 1R=109, 2R=114.5
        _c(3, 103, 110, 104, 109, 100, base),  # partial fills at 1R
        _c(4, 109, 111, 103, 104, 100, base),  # runner stopped at breakeven
    ]


def _partial_then_runner_target_day(*, date: datetime | None = None) -> list[Candle]:
    base = date or datetime(2026, 6, 22, 9, 30)
    return [
        _c(0, 100, 102, 98, 100, 100, base),
        _c(1, 100, 101, 99, 100, 100, base),
        _c(2, 100, 105, 103, 103.5, 50, base),  # entry, stop=98, 1R=109, 2R=114.5
        _c(3, 103, 110, 104, 109, 100, base),  # partial fills at 1R
        _c(4, 109, 116, 109, 115, 100, base),  # runner reaches 2R
    ]


# ---------------------------------------------------------------------------
# replay_day — unit tests
# ---------------------------------------------------------------------------

def test_target_hit_returns_winning_trade() -> None:
    trades = replay_day(_long_day(exit_high=115.0), orb_config=_ORB, bt_config=_CLEAN, symbol="MNQ")

    assert len(trades) == 1
    t = trades[0]
    assert t.win is True
    assert t.exit_reason == "target"
    assert t.side == "buy"
    # entry=103.5, stop=98, target=103.5+(103.5-98)*1.5=103.5+8.25=111.75
    # pnl = (111.75 - 103.5) * 2.0 = 16.5
    assert t.pnl == pytest_approx(16.5)


def test_stop_hit_returns_losing_trade() -> None:
    trades = replay_day(_long_day_stop(), orb_config=_ORB, bt_config=_CLEAN, symbol="MNQ")

    assert len(trades) == 1
    t = trades[0]
    assert t.win is False
    assert t.exit_reason == "stop"
    # pnl = (98 - 103.5) * 2.0 = -11.0
    assert t.pnl == pytest_approx(-11.0)


def test_no_signal_returns_empty() -> None:
    trades = replay_day(_no_signal_day(), orb_config=_ORB, bt_config=_CLEAN, symbol="MNQ")
    assert trades == []


def test_daily_loss_limit_blocks_entry() -> None:
    trades = replay_day(
        _long_day(),
        orb_config=_ORB,
        bt_config=_CLEAN,
        symbol="MNQ",
        day_pnl_running=-1000.0,  # already at daily limit
    )
    assert trades == []


def test_max_trades_per_day_blocks_entry() -> None:
    trades = replay_day(
        _long_day(),
        orb_config=_ORB,
        bt_config=_CLEAN,
        symbol="MNQ",
        trades_today=1,  # already at limit of 1
    )
    assert trades == []


def test_slippage_reduces_win_pnl() -> None:
    cfg_no_slip = BacktestConfig(slippage_ticks=0, commission_per_rt=0.0)
    cfg_slip = BacktestConfig(slippage_ticks=2, commission_per_rt=0.0)

    no_slip = replay_day(_long_day(exit_high=115.0), orb_config=_ORB, bt_config=cfg_no_slip, symbol="MNQ")
    with_slip = replay_day(_long_day(exit_high=115.0), orb_config=_ORB, bt_config=cfg_slip, symbol="MNQ")

    assert len(no_slip) == 1 and len(with_slip) == 1
    assert with_slip[0].pnl < no_slip[0].pnl
    # 2-tick slippage on MNQ: 2 * 0.25 * 2.0 = 1.0 dollar less
    assert no_slip[0].pnl - with_slip[0].pnl == pytest_approx(1.0)


def test_commission_reduces_pnl() -> None:
    cfg_no_comm = BacktestConfig(slippage_ticks=0, commission_per_rt=0.0)
    cfg_comm = BacktestConfig(slippage_ticks=0, commission_per_rt=8.0)

    no_comm = replay_day(_long_day(exit_high=115.0), orb_config=_ORB, bt_config=cfg_no_comm, symbol="MNQ")
    with_comm = replay_day(_long_day(exit_high=115.0), orb_config=_ORB, bt_config=cfg_comm, symbol="MNQ")

    assert len(no_comm) == 1 and len(with_comm) == 1
    assert no_comm[0].pnl - with_comm[0].pnl == pytest_approx(8.0)


def test_session_cutoff_blocks_late_trigger() -> None:
    trades = replay_day(_late_trigger_day(), orb_config=_ORB, bt_config=_CLEAN, symbol="MNQ")
    assert trades == []


def test_session_start_blocks_early_trigger() -> None:
    cfg = BacktestConfig(
        slippage_ticks=0,
        commission_per_rt=0.0,
        session_entry_start_hour=10,
        session_entry_start_minute=0,
    )

    trades = replay_day(_early_trigger_day(), orb_config=_ORB, bt_config=cfg, symbol="MNQ")

    assert trades == []


def test_ema_confluence_blocks_long_below_ema() -> None:
    cfg = BacktestConfig(
        slippage_ticks=0,
        commission_per_rt=0.0,
        signal_type="pullback",
        pullback_tolerance_ticks=4,
        pullback_stop_ticks=8,
        require_ema_confirm=True,
        ema_period=3,
    )

    trades = replay_day(_pullback_long_below_ema(), orb_config=_ORB, bt_config=cfg, symbol="MNQ")

    assert trades == []


def test_volume_confluence_blocks_low_volume_trigger() -> None:
    cfg = BacktestConfig(
        slippage_ticks=0,
        commission_per_rt=0.0,
        require_volume_confirm=True,
        volume_lookback=2,
        min_volume_ratio=1.0,
    )

    trades = replay_day(_long_day_low_volume(), orb_config=_ORB, bt_config=cfg, symbol="MNQ")

    assert trades == []


def test_eod_exit_when_neither_target_nor_stop_hit() -> None:
    # exit candle high < target and low > stop → EOD exit at last close
    trades = replay_day(_long_day(exit_high=109.0, exit_low=104.0), orb_config=_ORB, bt_config=_CLEAN, symbol="MNQ")

    assert len(trades) == 1
    t = trades[0]
    assert t.exit_reason == "eod"
    assert t.exit_price == pytest_approx(110.0)  # last candle close


def test_eod_exit_without_post_entry_candle_uses_entry_candle_close() -> None:
    candles = _long_day()[:3]

    trades = replay_day(candles, orb_config=_ORB, bt_config=_CLEAN, symbol="MNQ")

    assert len(trades) == 1
    t = trades[0]
    assert t.exit_reason == "eod"
    assert t.exit_price == pytest_approx(103.5)
    assert t.pnl == pytest_approx(0.0)


def test_partial_exit_takes_half_at_1r_then_stops_runner_at_breakeven() -> None:
    cfg = BacktestConfig(slippage_ticks=0, commission_per_rt=0.0, exit_model="partial_1r_be_2r")

    trades = replay_day(_partial_then_breakeven_day(), orb_config=_ORB, bt_config=cfg, symbol="MNQ")

    assert len(trades) == 1
    t = trades[0]
    assert t.exit_reason == "partial_breakeven"
    assert t.exit_price == pytest_approx(106.25)  # blended: half at 109, half at 103.5
    assert t.pnl == pytest_approx(5.5)


def test_partial_exit_runner_reaches_2r_target() -> None:
    cfg = BacktestConfig(slippage_ticks=0, commission_per_rt=0.0, exit_model="partial_1r_be_2r")

    trades = replay_day(_partial_then_runner_target_day(), orb_config=_ORB, bt_config=cfg, symbol="MNQ")

    assert len(trades) == 1
    t = trades[0]
    assert t.exit_reason == "partial_target"
    assert t.exit_price == pytest_approx(111.75)  # blended: half at 109, half at 114.5
    assert t.pnl == pytest_approx(16.5)


# ---------------------------------------------------------------------------
# run_backtest — integration tests
# ---------------------------------------------------------------------------

def test_run_backtest_single_win_day() -> None:
    result = run_backtest(
        _long_day(),
        orb_config=_ORB,
        bt_config=_CLEAN,
        symbol="MNQ",
    )

    assert result.days_traded == 1
    assert result.days_no_signal == 0
    assert result.win_rate == pytest_approx(1.0)
    assert result.total_pnl == pytest_approx(16.5)


def test_run_backtest_metrics_two_wins_one_loss() -> None:
    # Day 1 (narrow win): +16.5
    # Day 2 (narrow loss): -11.0
    # Day 3 (wide win): P&L = (145-112)*2 = 66.0
    day1 = _long_day(date=datetime(2026, 6, 22, 9, 30))
    day2 = _long_day_stop(date=datetime(2026, 6, 23, 9, 30))
    day3 = _wide_long_day(date=datetime(2026, 6, 24, 9, 30))

    result = run_backtest(day1 + day2 + day3, orb_config=_ORB, bt_config=_CLEAN, symbol="MNQ")

    assert result.days_traded == 3
    assert result.win_rate == pytest_approx(2 / 3, abs=1e-4)
    assert result.total_pnl == pytest_approx(16.5 - 11.0 + 66.0)

    gross_profit = 16.5 + 66.0
    gross_loss = 11.0
    assert result.profit_factor == pytest_approx(gross_profit / gross_loss)

    avg_win = gross_profit / 2
    avg_loss = gross_loss
    expected_expectancy = (2 / 3) * avg_win - (1 / 3) * avg_loss
    assert result.expectancy == pytest_approx(expected_expectancy, abs=0.01)


def test_run_backtest_max_drawdown() -> None:
    # Sequence: win, loss, win
    # cum: +16.5 → +5.5 → +71.5
    # drawdown: 0 → 11.0 peak-to-trough → 0
    day1 = _long_day(date=datetime(2026, 6, 22, 9, 30))
    day2 = _long_day_stop(date=datetime(2026, 6, 23, 9, 30))
    day3 = _wide_long_day(date=datetime(2026, 6, 24, 9, 30))

    result = run_backtest(day1 + day2 + day3, orb_config=_ORB, bt_config=_CLEAN, symbol="MNQ")

    assert result.max_drawdown == pytest_approx(11.0)


def test_run_backtest_consistency_rule_violation() -> None:
    # Day 1 (narrow win): +16.5 — only 1 profitable day, no violation yet
    # Day 2 (wide win): +66.0 — 2 profitable days, 66/(16.5+66)=79.8% > 50% → violation
    day1 = _long_day(date=datetime(2026, 6, 22, 9, 30))
    day2 = _wide_long_day(date=datetime(2026, 6, 23, 9, 30))

    result = run_backtest(day1 + day2, orb_config=_ORB, bt_config=_CLEAN, symbol="MNQ")

    assert any("consistency_rule" in v for v in result.rule_violations)
    violated_trade = next(t for t in result.trades if "consistency_rule" in t.rule_violations)
    assert violated_trade.date == "2026-06-23"


def test_run_backtest_no_consistency_violation_when_evenly_distributed() -> None:
    # Two identical days: each win = 16.5, total = 33.0, best = 16.5 = 50% exactly
    # 50% is NOT > 50%, so no violation
    day1 = _long_day(date=datetime(2026, 6, 22, 9, 30))
    day2 = _long_day(date=datetime(2026, 6, 23, 9, 30))

    result = run_backtest(day1 + day2, orb_config=_ORB, bt_config=_CLEAN, symbol="MNQ")

    assert result.rule_violations == []


def test_run_backtest_no_signal_days_counted() -> None:
    day1 = _long_day(date=datetime(2026, 6, 22, 9, 30))
    day2 = _no_signal_day(date=datetime(2026, 6, 23, 9, 30))
    day3 = _no_signal_day(date=datetime(2026, 6, 24, 9, 30))

    result = run_backtest(day1 + day2 + day3, orb_config=_ORB, bt_config=_CLEAN, symbol="MNQ")

    assert result.days_traded == 1
    assert result.days_no_signal == 2


def test_run_backtest_empty_candles_returns_zero_result() -> None:
    result = run_backtest([], orb_config=_ORB, bt_config=_CLEAN, symbol="MNQ")

    assert result.trades == []
    assert result.total_pnl == 0.0
    assert result.win_rate == 0.0
    assert result.days_traded == 0


def test_split_train_test_uses_train_end_date_inclusively() -> None:
    day1 = _long_day(date=datetime(2026, 6, 22, 9, 30))
    day2 = _long_day(date=datetime(2026, 6, 23, 9, 30))
    day3 = _long_day(date=datetime(2026, 6, 24, 9, 30))

    train, test = split_train_test(day1 + day2 + day3, "2026-06-23")

    assert {c.timestamp.date().isoformat() for c in train} == {"2026-06-22", "2026-06-23"}
    assert {c.timestamp.date().isoformat() for c in test} == {"2026-06-24"}


def test_run_validation_split_reports_train_test_and_expectancy_gap() -> None:
    day1 = _wide_long_day(date=datetime(2026, 6, 22, 9, 30))  # strong train win
    day2 = _long_day_stop(date=datetime(2026, 6, 23, 9, 30))  # test loss

    split = run_validation_split(
        day1 + day2,
        train_end="2026-06-22",
        orb_config=_ORB,
        bt_config=_CLEAN,
        symbol="MNQ",
    )

    assert split.train.days_traded == 1
    assert split.test.days_traded == 1
    assert split.train.expectancy > 0
    assert split.test.expectancy < 0
    assert split.expectancy_gap == pytest_approx(split.test.expectancy - split.train.expectancy)


def test_build_daily_trend_sides_uses_prior_completed_closes_only() -> None:
    candles = (
        _flat_day(date=datetime(2026, 6, 22, 9, 30), close=100)
        + _flat_day(date=datetime(2026, 6, 23, 9, 30), close=101)
        + _flat_day(date=datetime(2026, 6, 24, 9, 30), close=102)
        + _flat_day(date=datetime(2026, 6, 25, 9, 30), close=90)
    )

    sides = build_daily_trend_sides(candles, sma_days=3)

    assert sides["2026-06-25"] == "buy"


def test_daily_trend_filter_blocks_long_below_prior_sma() -> None:
    prior_downtrend = (
        _flat_day(date=datetime(2026, 6, 22, 9, 30), close=102)
        + _flat_day(date=datetime(2026, 6, 23, 9, 30), close=101)
        + _flat_day(date=datetime(2026, 6, 24, 9, 30), close=100)
    )
    long_signal = _long_day(date=datetime(2026, 6, 25, 9, 30))
    cfg = BacktestConfig(
        slippage_ticks=0,
        commission_per_rt=0.0,
        require_daily_trend_confirm=True,
        daily_trend_sma_days=3,
    )

    result = run_backtest(prior_downtrend + long_signal, orb_config=_ORB, bt_config=cfg, symbol="MNQ")

    assert result.trades == []
    assert result.days_no_signal == 4


def test_daily_trend_filter_allows_long_above_prior_sma() -> None:
    prior_uptrend = (
        _flat_day(date=datetime(2026, 6, 22, 9, 30), close=100)
        + _flat_day(date=datetime(2026, 6, 23, 9, 30), close=101)
        + _flat_day(date=datetime(2026, 6, 24, 9, 30), close=102)
    )
    long_signal = _long_day(date=datetime(2026, 6, 25, 9, 30))
    cfg = BacktestConfig(
        slippage_ticks=0,
        commission_per_rt=0.0,
        require_daily_trend_confirm=True,
        daily_trend_sma_days=3,
    )

    result = run_backtest(prior_uptrend + long_signal, orb_config=_ORB, bt_config=cfg, symbol="MNQ")

    assert len(result.trades) == 1
    assert result.trades[0].side == "buy"


def test_build_opening_gap_sides_uses_prior_close_to_current_open() -> None:
    prior = _flat_day(date=datetime(2026, 6, 22, 9, 30), close=100)
    gap_up = _long_day(date=datetime(2026, 6, 23, 9, 30))
    gap_down = _long_day(date=datetime(2026, 6, 24, 9, 30))
    gap_down[0] = _c(0, 95, 102, 94, 100, 100, datetime(2026, 6, 24, 9, 30))

    sides = build_opening_gap_sides(prior + gap_up + gap_down, min_gap_pct=0.01)

    assert sides["2026-06-22"] is None
    assert sides["2026-06-23"] is None
    assert sides["2026-06-24"] == "sell"


def test_opening_gap_bias_blocks_long_on_gap_down_day() -> None:
    prior = _flat_day(date=datetime(2026, 6, 22, 9, 30), close=105)
    long_signal = _long_day(date=datetime(2026, 6, 23, 9, 30))
    cfg = BacktestConfig(
        slippage_ticks=0,
        commission_per_rt=0.0,
        require_opening_gap_bias=True,
        min_opening_gap_pct=0.01,
    )

    result = run_backtest(prior + long_signal, orb_config=_ORB, bt_config=cfg, symbol="MNQ")

    assert result.trades == []


def test_opening_gap_bias_allows_long_on_gap_up_day() -> None:
    prior = _flat_day(date=datetime(2026, 6, 22, 9, 30), close=98)
    long_signal = _long_day(date=datetime(2026, 6, 23, 9, 30))
    cfg = BacktestConfig(
        slippage_ticks=0,
        commission_per_rt=0.0,
        require_opening_gap_bias=True,
        min_opening_gap_pct=0.01,
    )

    result = run_backtest(prior + long_signal, orb_config=_ORB, bt_config=cfg, symbol="MNQ")

    assert len(result.trades) == 1
    assert result.trades[0].side == "buy"


def test_build_prior_day_levels_uses_previous_day_only() -> None:
    day1 = [
        _c(0, 100, 110, 90, 105, 100, datetime(2026, 6, 22, 9, 30)),
        _c(1, 105, 108, 95, 101, 100, datetime(2026, 6, 22, 9, 30)),
    ]
    day2 = _long_day(date=datetime(2026, 6, 23, 9, 30))

    levels = build_prior_day_levels(day1 + day2)

    assert levels["2026-06-22"] is None
    assert levels["2026-06-23"] == {"high": 110, "low": 90, "close": 101}


def test_build_prior_day_levels_includes_prior_premarket_high_low() -> None:
    day1 = [
        _c(0, 95, 120, 94, 118, 100, datetime(2026, 6, 22, 8, 00)),
        _c(90, 100, 110, 90, 105, 100, datetime(2026, 6, 22, 8, 00)),
        _c(91, 105, 108, 95, 101, 100, datetime(2026, 6, 22, 8, 00)),
    ]
    day2 = _long_day(date=datetime(2026, 6, 23, 9, 30))

    levels = build_prior_day_levels(day1 + day2)

    assert levels["2026-06-23"] == {
        "high": 120,
        "low": 90,
        "close": 101,
        "premarket_high": 120,
        "premarket_low": 94,
    }


def test_key_level_proximity_blocks_trade_far_from_prior_day_levels() -> None:
    prior = _flat_day(date=datetime(2026, 6, 22, 9, 30), close=50)
    long_signal = _long_day(date=datetime(2026, 6, 23, 9, 30))
    cfg = BacktestConfig(
        slippage_ticks=0,
        commission_per_rt=0.0,
        require_key_level_proximity=True,
        key_level_tolerance_ticks=4,
    )

    result = run_backtest(prior + long_signal, orb_config=_ORB, bt_config=cfg, symbol="MNQ")

    assert result.trades == []


def test_key_level_proximity_allows_trade_near_prior_day_high() -> None:
    prior = [
        _c(0, 100, 103, 95, 100, 100, datetime(2026, 6, 22, 9, 30)),
        _c(1, 100, 102, 96, 101, 100, datetime(2026, 6, 22, 9, 30)),
    ]
    long_signal = _long_day(date=datetime(2026, 6, 23, 9, 30))
    cfg = BacktestConfig(
        slippage_ticks=0,
        commission_per_rt=0.0,
        require_key_level_proximity=True,
        key_level_tolerance_ticks=4,
    )

    result = run_backtest(prior + long_signal, orb_config=_ORB, bt_config=cfg, symbol="MNQ")

    assert len(result.trades) == 1
    assert result.trades[0].side == "buy"


def test_consistency_adjusted_score_penalizes_rule_violations() -> None:
    clean = run_backtest(
        _long_day(date=datetime(2026, 6, 22, 9, 30)) + _long_day(date=datetime(2026, 6, 23, 9, 30)),
        orb_config=_ORB,
        bt_config=_CLEAN,
        symbol="MNQ",
    )
    violator = run_backtest(
        _long_day(date=datetime(2026, 6, 22, 9, 30)) + _wide_long_day(date=datetime(2026, 6, 23, 9, 30)),
        orb_config=_ORB,
        bt_config=_CLEAN,
        symbol="MNQ",
    )

    assert violator.expectancy > clean.expectancy
    assert consistency_adjusted_score(violator, penalty_per_violation=100.0) < consistency_adjusted_score(clean, penalty_per_violation=100.0)


# ---------------------------------------------------------------------------
# build_first_pullback_signal unit tests
# ---------------------------------------------------------------------------

def _pullback_long_day(*, date: datetime | None = None) -> list[Candle]:
    """ORB breaks high at candle 2, then candle 3 pulls back to range_high, candle 4 exits target."""
    base = date or datetime(2026, 6, 22, 9, 30)
    return [
        _c(0, 100, 102, 98, 100, 100, base),   # opening range
        _c(1, 100, 101, 99, 100, 100, base),   # opening range
        _c(2, 100, 110, 103, 108, 200, base),  # breakout: close=108 >= 102+0.5, above vwap
        _c(3, 108, 103, 101, 102.5, 80, base), # pullback: low=101 <= 102+1.0(4tks), close=102.5 > 101
        _c(4, 103, 130, 102, 125, 100, base),  # target hit: high=130
    ]


def _pullback_no_pullback_day(*, date: datetime | None = None) -> list[Candle]:
    """Breakout confirmed but price never pulls back to range level."""
    base = date or datetime(2026, 6, 22, 9, 30)
    return [
        _c(0, 100, 102, 98, 100, 100, base),
        _c(1, 100, 101, 99, 100, 100, base),
        _c(2, 100, 110, 103, 108, 200, base),  # breakout
        _c(3, 108, 115, 106, 112, 100, base),  # runs away, low=106 > 103 (102+4tks)
        _c(4, 112, 120, 108, 115, 100, base),  # still no pullback
    ]


def test_pullback_signal_detected() -> None:
    candles = _pullback_long_day()
    result = build_first_pullback_signal(candles, _ORB, symbol="MNQ", pullback_tolerance_ticks=4, pullback_stop_ticks=8)
    assert result is not None
    signal, idx = result
    assert signal.side == "buy"
    assert signal.strategy == "first_pullback"
    assert idx == 3  # pullback on candle index 3
    # stop = range_high - 8*0.25 = 102 - 2.0 = 100.0
    assert signal.stop == pytest_approx(100.0)


def test_pullback_signal_none_when_no_pullback() -> None:
    result = build_first_pullback_signal(
        _pullback_no_pullback_day(), _ORB, symbol="MNQ",
        pullback_tolerance_ticks=4, pullback_stop_ticks=8
    )
    assert result is None


def test_pullback_signal_none_when_no_breakout() -> None:
    result = build_first_pullback_signal(
        _no_signal_day(), _ORB, symbol="MNQ",
        pullback_tolerance_ticks=4, pullback_stop_ticks=8
    )
    assert result is None


def test_replay_day_pullback_signal_type_wins() -> None:
    cfg = BacktestConfig(slippage_ticks=0, commission_per_rt=0.0,
                         signal_type="pullback", pullback_tolerance_ticks=4, pullback_stop_ticks=8)
    trades = replay_day(_pullback_long_day(), orb_config=_ORB, bt_config=cfg, symbol="MNQ")
    assert len(trades) == 1
    t = trades[0]
    assert t.win is True
    assert t.exit_reason == "target"
    # entry=102.5, stop=100.0, stop_dist=2.5, target=102.5+2.5*1.5=106.25
    assert t.entry_price == pytest_approx(102.5)
    assert t.exit_price == pytest_approx(106.25)
    assert t.pnl == pytest_approx((106.25 - 102.5) * 2.0)


def test_replay_day_pullback_no_signal_returns_empty() -> None:
    cfg = BacktestConfig(slippage_ticks=0, commission_per_rt=0.0,
                         signal_type="pullback", pullback_tolerance_ticks=4, pullback_stop_ticks=8)
    trades = replay_day(_pullback_no_pullback_day(), orb_config=_ORB, bt_config=cfg, symbol="MNQ")
    assert trades == []


# ---------------------------------------------------------------------------
# fixed_stop_ticks tests
# ---------------------------------------------------------------------------

def test_fixed_stop_ticks_overrides_range_stop() -> None:
    # long_day: entry=103.5, range stop=98 (wide). With fixed_stop_ticks=8 and tick_size=0.25:
    # fixed_dist = 8 * 0.25 = 2.0, stop = 103.5 - 2.0 = 101.5, target = 103.5 + 2.0*1.5 = 106.5
    # post-entry candle has low=108 > 101.5 so stop NOT hit; high=115 >= 106.5 so target HIT
    cfg = BacktestConfig(slippage_ticks=0, commission_per_rt=0.0, fixed_stop_ticks=8)
    trades = replay_day(_long_day(exit_high=115.0, exit_low=108.0), orb_config=_ORB, bt_config=cfg, symbol="MNQ")

    assert len(trades) == 1
    t = trades[0]
    assert t.exit_reason == "target"
    assert t.exit_price == pytest_approx(106.5)
    # pnl = (106.5 - 103.5) * 2.0 = 6.0
    assert t.pnl == pytest_approx(6.0)


def test_fixed_stop_ticks_stop_hit() -> None:
    # With fixed_stop_ticks=8: stop=101.5. long_day_stop post-entry low=97 <= 101.5 → stop hit.
    # Without fixed stop, range stop=98; both are hit by low=97, but fixed stop exits at 101.5 (better fill).
    cfg = BacktestConfig(slippage_ticks=0, commission_per_rt=0.0, fixed_stop_ticks=8)
    trades = replay_day(_long_day_stop(), orb_config=_ORB, bt_config=cfg, symbol="MNQ")

    assert len(trades) == 1
    t = trades[0]
    assert t.exit_reason == "stop"
    assert t.exit_price == pytest_approx(101.5)
    # pnl = (101.5 - 103.5) * 2.0 = -4.0
    assert t.pnl == pytest_approx(-4.0)


# ---------------------------------------------------------------------------
# Import shim for pytest_approx (avoids global import cluttering the module)
# ---------------------------------------------------------------------------
try:
    from pytest import approx as pytest_approx
except ImportError:
    def pytest_approx(value, *, abs=1e-6, rel=None):  # type: ignore[override]
        return value

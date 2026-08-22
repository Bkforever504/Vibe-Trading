from __future__ import annotations

import csv
import sys
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from strategies.prop_rule_gate import AccountState, load_rule_profile
from strategies.topstep_prop_bot import (
    Candle,
    FuturesContract,
    OpeningRangeConfig,
    build_first_pullback_signal,
    build_late_orb_retest_signal,
    build_liquidity_sweep_mss_retest_signal,
    build_opening_range_signal,
    build_vwap_deviation_signal,
    load_candles_csv,
    size_contracts,
)


def _candle(minute: int, open_: float, high: float, low: float, close: float, volume: int = 100) -> Candle:
    return Candle(
        timestamp=datetime(2026, 6, 22, 9, 30) + timedelta(minutes=minute),
        open=open_,
        high=high,
        low=low,
        close=close,
        volume=volume,
    )


def _minute_bars_from_five(specs: list[tuple[float, float, float, float]]) -> list[Candle]:
    rows: list[Candle] = []
    for block, (open_, high, low, close) in enumerate(specs):
        for offset in range(5):
            rows.append(_candle(block * 5 + offset, open_, high, low, close, 100))
    return rows


def test_liquidity_sweep_mss_requires_full_sequence_and_is_causal() -> None:
    specs = [
        (100, 102, 99, 101),
        (101, 103, 100, 102),
        (102, 104, 101, 103),
        (103, 105, 102, 104),
        (104, 106, 103, 105),
        (105, 107, 104, 106),
        (106, 111, 105, 109),       # sweep/reclaim prior high 110
        (102, 103, 99, 100),        # bearish MSS + 1-point FVG
        (100, 104, 99.5, 102.5),    # midpoint retest and bearish rejection
    ]
    candles = _minute_bars_from_five(specs)
    config = OpeningRangeConfig(reward_risk=2.0, max_risk_per_trade=100.0)
    result = build_liquidity_sweep_mss_retest_signal(
        candles,
        config,
        symbol="MES",
        key_levels={"high": 110.0, "low": 90.0},
        atr_lookback=3,
    )
    assert result is not None
    signal, entry_idx = result
    assert signal.strategy == "liquidity_sweep_mss_retest"
    assert signal.side == "sell"
    assert signal.entry == 102.5
    assert signal.stop == 111.25
    assert signal.target == 85.0
    assert candles[entry_idx].timestamp == datetime(2026, 6, 22, 10, 14)

    future = candles + [_candle(minute, 102.5, 120, 80, 90) for minute in range(45, 50)]
    repeated = build_liquidity_sweep_mss_retest_signal(
        future,
        config,
        symbol="MES",
        key_levels={"high": 110.0, "low": 90.0},
        atr_lookback=3,
    )
    assert repeated is not None
    assert repeated[0] == signal
    assert repeated[1] == entry_idx


def test_liquidity_sweep_mss_does_not_trade_without_fvg() -> None:
    specs = [
        (100, 102, 99, 101),
        (101, 103, 100, 102),
        (102, 104, 101, 103),
        (103, 105, 102, 104),
        (104, 106, 103, 105),
        (105, 107, 104, 106),
        (106, 111, 105, 109),
        (102, 104, 99, 100),        # MSS, but no gap versus two-back low 104
        (100, 104, 99.5, 102.5),
    ]
    result = build_liquidity_sweep_mss_retest_signal(
        _minute_bars_from_five(specs),
        OpeningRangeConfig(reward_risk=2.0),
        symbol="MES",
        key_levels={"high": 110.0, "low": 90.0},
        atr_lookback=3,
    )
    assert result is None


def test_opening_range_signal_requires_completed_range_and_vwap_confirmation() -> None:
    candles = [
        _candle(0, 100, 101, 99, 100, 10),
        _candle(1, 100, 102, 99, 101, 10),
        _candle(2, 101, 102, 100, 101, 10),
        _candle(3, 101, 103, 101, 102, 10),
    ]

    signal = build_opening_range_signal(candles, OpeningRangeConfig(range_minutes=3, min_breakout_points=0.5))

    assert signal is None

    candles[-1] = _candle(3, 102, 104, 102, 103.25, 50)
    signal = build_opening_range_signal(candles, OpeningRangeConfig(range_minutes=3, min_breakout_points=0.5))

    assert signal is not None
    assert signal.side == "buy"
    assert signal.entry == 103.25
    assert signal.stop == 99
    assert signal.target > signal.entry
    assert signal.strategy == "opening_range_vwap"


def test_late_orb_retest_detects_break_well_after_opening_range() -> None:
    candles = [
        _candle(0, 100, 101, 99, 100, 100),
        _candle(1, 100, 102, 99, 101, 100),
        _candle(2, 101, 101.5, 100, 101, 100),
        _candle(3, 101, 101.75, 100.5, 101.25, 100),
        _candle(4, 101.25, 104, 101, 103.5, 200),
        _candle(5, 103.5, 104, 101.75, 102.5, 120),
    ]
    result = build_late_orb_retest_signal(
        candles,
        OpeningRangeConfig(range_minutes=2, min_breakout_points=0.5, reward_risk=2.0),
        symbol="MNQ",
        pullback_tolerance_ticks=4,
        pullback_stop_ticks=8,
    )
    assert result is not None
    signal, entry_idx = result
    assert entry_idx == 5
    assert signal.strategy == "late_orb_retest"
    assert signal.side == "buy"
    assert signal.entry == 102.5
    assert signal.stop == 100.0
    assert signal.target == 107.5


def test_late_orb_retest_rejects_wick_only_break_and_future_data() -> None:
    config = OpeningRangeConfig(range_minutes=2, min_breakout_points=0.5)
    prefix = [
        _candle(0, 100, 101, 99, 100),
        _candle(1, 100, 102, 99, 101),
        _candle(2, 101, 104, 100.5, 101.5),
        _candle(3, 101.5, 102, 100.5, 101.25),
    ]
    assert build_late_orb_retest_signal(prefix, config, symbol="MNQ") is None
    future = prefix + [
        _candle(4, 101.25, 104, 101, 103.5),
        _candle(5, 103.5, 104, 101.75, 102.5),
    ]
    result = build_late_orb_retest_signal(future, config, symbol="MNQ")
    assert result is not None
    assert result[1] == 5


def test_size_contracts_respects_risk_budget_and_firm_max_contracts() -> None:
    contract = FuturesContract(symbol="MNQ", point_value=2.0, tick_size=0.25)

    qty = size_contracts(
        entry=100.0,
        stop=90.0,
        contract=contract,
        risk_budget=100.0,
        max_contracts=3,
    )

    assert qty == 3


def test_signal_must_pass_prop_gate_before_paper_order() -> None:
    profile = load_rule_profile(ROOT / "rules" / "prop_firms" / "topstep_topstepx_api.json")
    candles = [
        _candle(0, 100, 101, 99, 100, 10),
        _candle(1, 100, 102, 99, 101, 10),
        _candle(2, 101, 102, 100, 101, 10),
        _candle(3, 102, 104, 102, 103.25, 50),
    ]

    signal = build_opening_range_signal(candles, OpeningRangeConfig(range_minutes=3, min_breakout_points=0.5))
    assert signal is not None
    decision = signal.evaluate_rules(
        profile=profile,
        account=AccountState(equity=50_000, start_equity=50_000, day_pnl=-995, trailing_drawdown_remaining=1900),
        contracts=1,
        running_on_vps=False,
    )

    assert decision.allowed is False
    assert "daily_loss_limit" in decision.reasons


def test_load_candles_csv_parses_minute_data(tmp_path: Path) -> None:
    csv_path = tmp_path / "mnq.csv"
    with csv_path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(
            fh,
            fieldnames=["timestamp", "open", "high", "low", "close", "volume", "instrument_id"],
        )
        writer.writeheader()
        writer.writerow(
            {
                "timestamp": "2026-06-22T09:30:00",
                "open": "100",
                "high": "101",
                "low": "99",
                "close": "100.5",
                "volume": "123",
                "instrument_id": "42003239",
            }
        )

    candles = load_candles_csv(csv_path)

    assert len(candles) == 1
    assert candles[0].close == 100.5
    assert candles[0].volume == 123
    assert candles[0].instrument_id == "42003239"


def test_first_pullback_bos_confirm_blocks_pullback_without_higher_high() -> None:
    candles = [
        _candle(0, 100, 102, 98, 100, 100),
        _candle(1, 100, 101, 99, 100, 100),
        _candle(2, 100, 110, 103, 108, 200),  # breakout
        _candle(3, 108, 103, 101, 102.5, 80), # immediate pullback, no higher high after breakout
        _candle(4, 103, 130, 102, 125, 100),
    ]

    result = build_first_pullback_signal(
        candles,
        OpeningRangeConfig(range_minutes=2, min_breakout_points=0.5),
        require_bos_confirm=True,
    )

    assert result is None


def test_first_pullback_bos_confirm_allows_higher_high_before_pullback() -> None:
    candles = [
        _candle(0, 100, 102, 98, 100, 100),
        _candle(1, 100, 101, 99, 100, 100),
        _candle(2, 100, 110, 103, 108, 200),  # breakout
        _candle(3, 108, 112, 106, 111, 100),  # higher high confirms structure
        _candle(4, 108, 103, 101, 102.5, 80), # pullback
        _candle(5, 103, 130, 102, 125, 100),
    ]

    result = build_first_pullback_signal(
        candles,
        OpeningRangeConfig(range_minutes=2, min_breakout_points=0.5),
        require_bos_confirm=True,
    )

    assert result is not None
    signal, idx = result
    assert signal.side == "buy"
    assert idx == 4


def test_vwap_deviation_entry_index_is_confirmation_bar_not_future_bar() -> None:
    candles = [
        _candle(0, 100, 101, 99, 100, 100),
        _candle(1, 100, 101, 99, 100, 100),
        _candle(2, 100, 101, 99, 100, 100),
        _candle(3, 108, 110, 103, 104, 200),
        _candle(4, 104, 105, 102, 103, 100),
    ]

    result = build_vwap_deviation_signal(
        candles,
        OpeningRangeConfig(range_minutes=2, min_breakout_points=0.5),
        deviation_points=4.0,
        min_session_bars=3,
    )

    assert result is not None
    signal, idx = result
    assert signal.side == "sell"
    assert idx == 3
    assert candles[idx].close == signal.entry

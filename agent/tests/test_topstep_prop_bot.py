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
    build_opening_range_signal,
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
        writer = csv.DictWriter(fh, fieldnames=["timestamp", "open", "high", "low", "close", "volume"])
        writer.writeheader()
        writer.writerow(
            {
                "timestamp": "2026-06-22T09:30:00",
                "open": "100",
                "high": "101",
                "low": "99",
                "close": "100.5",
                "volume": "123",
            }
        )

    candles = load_candles_csv(csv_path)

    assert len(candles) == 1
    assert candles[0].close == 100.5
    assert candles[0].volume == 123


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

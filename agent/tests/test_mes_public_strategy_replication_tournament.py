from __future__ import annotations

from datetime import datetime, timedelta

import pandas as pd
import pytest

from research.mes_public_strategy_replication_tournament import (
    PUBLIC_SOURCES,
    STRATEGIES,
    ReplicationTrade,
    _simulate,
    block_bootstrap_mean,
    evaluate,
    execution_edge_budget,
    ib_failure_to_vwap,
    prepare_sessions,
    trade_pnl,
)


def _bars(
    day: str,
    *,
    count: int = 386,
    instrument_id: str = "MES-TEST",
    price: float = 100.0,
) -> pd.DataFrame:
    start = datetime.fromisoformat(f"{day}T09:30:00")
    rows = []
    for idx in range(count):
        timestamp = start + timedelta(minutes=idx)
        rows.append({
            "timestamp": timestamp.isoformat(),
            "dt": timestamp,
            "date": day,
            "open": price,
            "high": price + 0.25,
            "low": price - 0.25,
            "close": price,
            "volume": 100,
            "instrument_id": instrument_id,
        })
    return pd.DataFrame(rows)


def test_prepare_sessions_excludes_incomplete_and_intraday_roll() -> None:
    complete = _bars("2024-01-02")
    incomplete = _bars("2024-01-03", count=100)
    roll = _bars("2024-01-04")
    roll.loc[200:, "instrument_id"] = "MES-NEXT"

    dates, sessions, skipped = prepare_sessions(pd.concat([complete, incomplete, roll], ignore_index=True))

    assert dates == ["2024-01-02"]
    assert list(sessions) == ["2024-01-02"]
    assert skipped["incomplete"] == 1
    assert skipped["intraday_contract_change"] == 1


def test_simulation_enters_next_bar_and_uses_stop_first() -> None:
    bars = _bars("2024-01-02", count=3)
    bars.loc[1, ["open", "high", "low", "close"]] = [100.0, 102.0, 98.0, 100.0]

    trade = _simulate(
        bars,
        strategy="test",
        side=1,
        signal_idx=0,
        entry_idx=1,
        stop=99.0,
        fixed_target=101.5,
        min_reward_risk=1.5,
    )

    assert trade is not None
    assert trade.entry_time.endswith("09:31:00")
    assert trade.exit_reason == "stop"
    assert trade.exit_price == 99.0
    assert trade.raw_points == -1.0


def test_round_trip_friction_is_applied_to_both_sides() -> None:
    trade = ReplicationTrade(
        strategy="test",
        day="2024-01-02",
        side="buy",
        signal_time="2024-01-02T09:30:00",
        entry_time="2024-01-02T09:31:00",
        exit_time="2024-01-02T09:32:00",
        entry_price=100.0,
        exit_price=101.0,
        stop_price=99.0,
        target_price=101.0,
        risk_ticks=4.0,
        reward_risk=1.0,
        raw_points=1.0,
        exit_reason="target",
    )

    assert trade_pnl(trade) == pytest.approx(0.02)
    assert trade_pnl(trade, cost_multiple=2.0) == pytest.approx(-4.96)
    assert trade_pnl(trade, cost_multiple=0.0) == pytest.approx(5.0)
    assert execution_edge_budget([trade]) == {
        "trades": 1,
        "gross_expectancy_before_friction": 5.0,
        "base_round_trip_friction": 4.98,
        "break_even_friction_per_side": 2.5,
        "base_friction_per_side": 2.49,
        "edge_budget_survives_base_friction": True,
    }


def test_initial_balance_failure_uses_next_open_and_vwap_target() -> None:
    bars = _bars("2024-01-02", count=70, price=98.0)
    bars.loc[:59, "high"] = 100.0
    bars.loc[:59, "low"] = 97.0
    bars.loc[60, ["open", "high", "low", "close"]] = [99.5, 100.25, 99.25, 99.75]
    bars.loc[61, ["open", "high", "low", "close"]] = [99.5, 99.75, 99.0, 99.25]
    bars.loc[62, ["open", "high", "low", "close"]] = [99.25, 99.5, 97.5, 98.0]

    trade = ib_failure_to_vwap(bars)

    assert trade is not None
    assert trade.side == "sell"
    assert trade.signal_time.endswith("10:30:00")
    assert trade.entry_time.endswith("10:31:00")
    assert trade.entry_price == 99.5
    assert trade.target_price < trade.entry_price


def test_block_bootstrap_is_deterministic_and_positive_for_constant_edge() -> None:
    first = block_bootstrap_mean([2.0] * 80, samples=100, block_size=10, seed=7)
    second = block_bootstrap_mean([2.0] * 80, samples=100, block_size=10, seed=7)

    assert first == second
    assert first["lower_bound"] == 2.0
    assert first["probability_mean_positive"] == 1.0


def test_report_has_five_public_sources_and_no_execution_authority() -> None:
    frame = pd.concat(
        [
            _bars("2024-01-02"),
            _bars("2025-01-02"),
            _bars("2026-01-02"),
        ],
        ignore_index=True,
    )

    report = evaluate(frame, bootstrap_samples=20, combine_simulations=20)

    assert set(PUBLIC_SOURCES) == set(STRATEGIES)
    assert report["family_attempts"] == 5
    assert report["execution_enabled"] is False
    assert report["can_submit_orders"] is False
    assert report["orders_submitted"] == 0
    assert report["promotion"]["ready"] is False

from datetime import datetime, timezone

import pytest

from strategies.micro_momentum_paper_bot import (
    PaperConfig,
    build_orders,
    initial_state,
    mark_to_market,
    run_cycle,
    target_notionals,
)


NOW = datetime(2026, 7, 20, 14, 0, tzinfo=timezone.utc)


def test_targets_half_equity_and_keeps_half_cash() -> None:
    targets = target_notionals(["XLK", "XLE"], 1000.0)
    assert targets == {"XLK": 250.0, "XLE": 250.0}


def test_virtual_rebalance_is_fractional_and_bounded() -> None:
    state = initial_state()
    signal = {"holdings": ["XLK", "XLE"], "signal_asof": "2026-07-17"}
    report, updated = run_cycle(
        signal,
        {"XLK": 175.0, "XLE": 57.0},
        state,
        market_open=True,
        execute_paper=True,
        now=NOW,
    )
    assert report["status"] == "weekly_rebalance_completed"
    assert report["broker_orders_enabled"] is False
    assert len(report["fills"]) == 2
    assert report["promotion"]["completed_weekly_decisions"] == 1
    assert report["promotion"]["live_execution_automatic"] is False
    assert updated["positions"]["XLK"]["qty"] == pytest.approx(250.0 / (175.0 * 1.0006))
    marks = mark_to_market(updated, {"XLK": 175.0, "XLE": 57.0})
    assert marks["gross_exposure_pct"] < 50.0
    assert updated["cash"] == pytest.approx(500.0)


def test_same_week_is_idempotent() -> None:
    signal = {"holdings": ["XLK", "XLE"], "signal_asof": "2026-07-17"}
    first, state = run_cycle(signal, {"XLK": 175.0, "XLE": 57.0}, initial_state(), market_open=True, execute_paper=True, now=NOW)
    second, state2 = run_cycle(signal, {"XLK": 176.0, "XLE": 58.0}, state, market_open=True, execute_paper=True, now=NOW)
    assert first["fills"]
    assert second["status"] == "already_rebalanced_this_week"
    assert second["fills"] == []
    assert second["promotion"]["completed_weekly_decisions"] == 1
    assert state2["positions"] == state["positions"]


def test_market_closed_fails_closed_without_mutating_state() -> None:
    signal = {"holdings": ["XLK", "XLE"], "signal_asof": "2026-07-17"}
    report, updated = run_cycle(signal, {"XLK": 175.0, "XLE": 57.0}, initial_state(), market_open=False, execute_paper=True, now=NOW)
    assert report["status"] == "market_closed_fail_closed"
    assert report["paper_ledger_changed"] is False
    assert updated["cash"] == 1000.0
    assert updated["positions"] == {}


def test_drawdown_halt_liquidates_and_blocks_new_targets() -> None:
    state = initial_state()
    state["cash"] = 500.0
    state["positions"] = {"XLK": {"qty": 5.0, "average_cost": 100.0}}
    state["high_water_mark"] = 1200.0
    state["last_rebalance_week"] = "2026-W29"
    report, updated = run_cycle(
        {"holdings": ["XLK", "XLE"], "signal_asof": "2026-07-17"},
        {"XLK": 100.0, "XLE": 50.0},
        state,
        market_open=True,
        execute_paper=True,
        now=NOW,
    )
    assert report["status"] == "drawdown_halt_liquidated"
    assert report["selected_holdings"] == []
    assert updated["halted"] is True
    assert updated["positions"] == {}


def test_missing_position_mark_fails_closed() -> None:
    state = initial_state()
    state["positions"] = {"XLK": {"qty": 1.0, "average_cost": 100.0}}
    with pytest.raises(ValueError, match="Missing mark"):
        mark_to_market(state, {})


def test_orders_sell_before_buy() -> None:
    state = initial_state()
    state["cash"] = 500.0
    state["positions"] = {"XLE": {"qty": 5.0, "average_cost": 50.0}}
    orders = build_orders(state, {"XLE": 50.0, "XLK": 100.0}, {"XLK": 250.0})
    assert [row["side"] for row in orders] == ["sell", "buy"]


def test_config_has_no_leverage_or_full_deployment() -> None:
    config = PaperConfig()
    assert config.deployment_fraction == 0.50
    assert config.max_drawdown_pct == 8.0

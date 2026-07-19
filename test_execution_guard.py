from pathlib import Path

import pytest

from strategies.execution_guard import ExecutionGuardConfig, evaluate_execution


@pytest.fixture(autouse=True)
def _isolate_portfolio_kill_switch(monkeypatch) -> None:
    monkeypatch.setattr("strategies.execution_guard.portfolio_kill_active", lambda: False)


def test_blocks_live_order_without_explicit_live_enable(tmp_path: Path) -> None:
    decision = evaluate_execution(
        bot="flip",
        symbol="SPY",
        action="entry",
        paper=False,
        live_enabled=False,
        confidence=9.0,
        estimated_notional=100.0,
        max_notional=200.0,
        contracts=1,
        max_contracts=5,
        block_file=tmp_path / "manual_reset.json",
    )

    assert decision.allowed is False
    assert decision.reason == "live_execution_not_enabled"


def test_allows_high_confidence_paper_order_inside_risk_limits(tmp_path: Path) -> None:
    decision = evaluate_execution(
        bot="flip",
        symbol="SPY",
        action="entry",
        paper=True,
        live_enabled=False,
        confidence=9.0,
        estimated_notional=100.0,
        max_notional=200.0,
        contracts=1,
        max_contracts=5,
        block_file=tmp_path / "manual_reset.json",
    )

    assert decision.allowed is True
    assert decision.reason == "allowed"


def test_blocks_low_confidence_and_writes_manual_reset_for_daily_loss(tmp_path: Path) -> None:
    block_file = tmp_path / "manual_reset.json"

    low_confidence = evaluate_execution(
        bot="flip",
        symbol="SPY",
        action="entry",
        paper=True,
        live_enabled=False,
        confidence=7.9,
        estimated_notional=100.0,
        max_notional=200.0,
        contracts=1,
        max_contracts=5,
        block_file=block_file,
    )
    assert low_confidence.allowed is False
    assert low_confidence.reason == "confidence_below_minimum"
    assert block_file.exists() is False

    daily_loss = evaluate_execution(
        bot="flip",
        symbol="SPY",
        action="entry",
        paper=True,
        live_enabled=False,
        confidence=9.0,
        estimated_notional=100.0,
        max_notional=200.0,
        contracts=1,
        max_contracts=5,
        daily_loss_pct=0.031,
        block_file=block_file,
    )
    assert daily_loss.allowed is False
    assert daily_loss.reason == "daily_loss_limit"
    assert block_file.exists() is True


def test_blocks_duplicate_symbol_and_wide_spread(tmp_path: Path) -> None:
    config = ExecutionGuardConfig(max_spread_cents=5)

    duplicate = evaluate_execution(
        bot="flip",
        symbol="SPY",
        action="entry",
        paper=True,
        live_enabled=False,
        confidence=9.0,
        estimated_notional=100.0,
        max_notional=200.0,
        contracts=1,
        max_contracts=5,
        open_symbols={"SPY"},
        block_file=tmp_path / "manual_reset.json",
        config=config,
    )
    assert duplicate.allowed is False
    assert duplicate.reason == "duplicate_symbol_exposure"

    wide = evaluate_execution(
        bot="flip",
        symbol="QQQ",
        action="entry",
        paper=True,
        live_enabled=False,
        confidence=9.0,
        estimated_notional=100.0,
        max_notional=200.0,
        contracts=1,
        max_contracts=5,
        spread_cents=6,
        block_file=tmp_path / "manual_reset.json",
        config=config,
    )
    assert wide.allowed is False
    assert wide.reason == "spread_too_wide"

    unknown = evaluate_execution(
        bot="flip",
        symbol="IWM",
        action="entry",
        paper=True,
        live_enabled=False,
        confidence=9.0,
        estimated_notional=100.0,
        max_notional=200.0,
        contracts=1,
        max_contracts=5,
        spread_cents=None,
        block_file=tmp_path / "manual_reset.json",
        config=config,
    )
    assert unknown.allowed is False
    assert unknown.reason == "spread_quote_unavailable"

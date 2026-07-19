from strategies.flip_live_readiness import (
    LIVE_APPROVAL_ACK,
    affordable_contracts,
    evaluate_live_readiness,
)


def _account(**overrides):
    row = {
        "status": "ACTIVE",
        "equity": "300.00",
        "buying_power": "300.00",
        "options_trading_level": 2,
        "account_blocked": False,
        "trading_blocked": False,
        "trade_suspended_by_user": False,
    }
    row.update(overrides)
    return row


def test_live_requires_separate_explicit_ack():
    result = evaluate_live_readiness(_account(), live_enabled=True, approval_ack="")
    assert result.ready is False
    assert "explicit_live_capital_ack_missing" in result.blockers


def test_healthy_approved_account_can_pass_preflight():
    result = evaluate_live_readiness(_account(), live_enabled=True, approval_ack=LIVE_APPROVAL_ACK)
    assert result.ready is True
    assert result.blockers == ()


def test_blocked_broker_account_fails_closed():
    result = evaluate_live_readiness(
        _account(trading_blocked=True),
        live_enabled=True,
        approval_ack=LIVE_APPROVAL_ACK,
    )
    assert result.ready is False
    assert "broker_trading_blocked" in result.blockers


def test_options_level_two_is_required():
    result = evaluate_live_readiness(
        _account(options_trading_level=1),
        live_enabled=True,
        approval_ack=LIVE_APPROVAL_ACK,
    )
    assert "long_options_level_2_not_approved" in result.blockers


def test_three_hundred_dollars_cannot_buy_typical_contract_at_two_percent_notional():
    result = affordable_contracts(
        account_equity=300,
        option_price=0.50,
        max_notional_pct=0.02,
        max_contracts=5,
    )
    assert result["premium_budget"] == 6.0
    assert result["contract_cost"] == 50.0
    assert result["contracts"] == 0
    assert result["affordable"] is False


def test_flip_live_entry_stops_before_market_scan_without_ack(monkeypatch):
    from strategies import flip_bot

    decisions = []
    monkeypatch.setattr(flip_bot, "PAPER", False)
    monkeypatch.setattr(flip_bot, "LIVE_EXECUTION_ENABLED", True)
    monkeypatch.setattr(flip_bot, "LIVE_APPROVAL_ACK_VALUE", "")
    monkeypatch.setattr(flip_bot, "_get", lambda path: _account())
    monkeypatch.setattr(flip_bot, "_alert", lambda message: None)
    monkeypatch.setattr(flip_bot, "_decision", lambda *args, **kwargs: decisions.append((args, kwargs)))
    monkeypatch.setattr(
        flip_bot,
        "_market_open",
        lambda: (_ for _ in ()).throw(AssertionError("market scan must not run")),
    )

    flip_bot.run_entry(300.0)

    assert decisions
    assert decisions[0][0][3] == "live_readiness_failed"
    assert "explicit_live_capital_ack_missing" in decisions[0][1]["blockers"]

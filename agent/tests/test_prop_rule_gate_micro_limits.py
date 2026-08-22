from strategies.prop_rule_gate import AccountState, ProposedTrade, evaluate_prop_trade


def _account() -> AccountState:
    return AccountState(
        equity=50_000,
        start_equity=50_000,
        day_pnl=0,
        trailing_drawdown_remaining=2_000,
    )


def _profile() -> dict:
    return {
        "firm": "Topstep",
        "account_type": "50K research",
        "automation": {"allowed": True, "status": "allowed", "requires_local_device": True},
        "risk": {
            "max_daily_loss": 1_000,
            "max_trailing_drawdown": 2_000,
            "max_contracts": 5,
            "max_micro_contracts": 50,
        },
        "unknown_rules_block": True,
    }


def test_micro_future_uses_micro_contract_limit() -> None:
    decision = evaluate_prop_trade(
        _profile(),
        ProposedTrade(symbol="MESU6", side="buy", contracts=6, risk_dollars=300),
        _account(),
    )

    assert decision.allowed is True


def test_mini_future_uses_standard_contract_limit() -> None:
    decision = evaluate_prop_trade(
        _profile(),
        ProposedTrade(symbol="ESU6", side="buy", contracts=6, risk_dollars=300),
        _account(),
    )

    assert decision.allowed is False
    assert "max_contracts" in decision.reasons

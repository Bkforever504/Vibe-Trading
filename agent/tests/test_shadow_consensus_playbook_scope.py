from __future__ import annotations

import json

from strategies.shadow_consensus import entry_advice


def test_long_premium_ignores_only_short_premium_blockers(tmp_path) -> None:
    report = tmp_path / "consensus.json"
    report.write_text(json.dumps({
        "portfolio_kill_switch": {"active": False},
        "decisions": [{
            "symbol": "SPY",
            "recommendation": "stand_aside",
            "options_playbook": "put_credit_spread",
            "blockers": [
                "adaptive_put_credit_spread_credit/risk_is_below_minimum",
                "catalyst_new_short_premium_blocked",
                "market_force_unclear",
                "options_liquidity_blocked",
            ],
        }],
    }), encoding="utf-8")

    result = entry_advice(
        "SPY",
        2,
        report_path=report,
        enabled=True,
        requested_playbook="directional_long_call",
    )

    assert result["ignored_wrong_playbook_blockers"] == [
        "adaptive_put_credit_spread_credit/risk_is_below_minimum",
        "catalyst_new_short_premium_blocked",
    ]
    assert "market_force_unclear" in result["blockers"]
    assert result["hard_blockers"] == []
    assert result["allowed"] is True
    assert result["adjusted_contracts"] == 1


def test_short_premium_keeps_credit_quality_blocker(tmp_path) -> None:
    report = tmp_path / "consensus.json"
    report.write_text(json.dumps({
        "portfolio_kill_switch": {"active": False},
        "decisions": [{
            "symbol": "IWM",
            "recommendation": "stand_aside",
            "blockers": ["adaptive_put_credit_spread_credit/risk_is_below_minimum"],
        }],
    }), encoding="utf-8")

    result = entry_advice(
        "IWM",
        1,
        report_path=report,
        enabled=True,
        requested_playbook="put_credit_spread",
    )

    assert result["blockers"] == ["adaptive_put_credit_spread_credit/risk_is_below_minimum"]
    assert result["ignored_wrong_playbook_blockers"] == []

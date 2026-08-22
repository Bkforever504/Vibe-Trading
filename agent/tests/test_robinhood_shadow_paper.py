from datetime import datetime, timedelta, timezone

import pytest

from strategies.robinhood_options_trader_intake import OptionsTraderProfile, evaluate_shared_trade, evaluate_trader
from strategies.robinhood_shadow_paper import ShadowConfig, close_shadow, initial_state, open_shadow


NOW = datetime(2026, 8, 3, 15, 0, tzinfo=timezone.utc)


def packet(*, packet_id="trade-1", max_loss=20.0, bid=0.20, ask=0.22, quoted_at=NOW, warnings=None):
    return {
        "source": "robinhood_official_trading_mcp",
        "packet_id": packet_id,
        "strategy": "long_call",
        "underlying": "SPY",
        "max_loss_dollars": max_loss,
        "profit_target": {"type": "return_pct", "value": 0.50},
        "stop_policy": {"type": "premium_loss_pct", "value": -0.50},
        "review": {"source": "robinhood_review_option_order", "status": "ok", "warnings": warnings or []},
        "legs": [{"symbol": "SPY260904C00700000", "side": "buy_to_open", "quantity": 1, "bid": bid, "ask": ask, "quoted_at": quoted_at.isoformat()}],
    }


def test_open_uses_ask_and_never_enables_execution():
    report, state = open_shadow(packet(ask=0.20), initial_state(), now=NOW, execute_paper=True)
    assert report["status"] == "paper_opened"
    assert report["execution_enabled"] is False
    assert report["can_submit_orders"] is False
    assert report["broker_client_present"] is False
    assert report["fills"][0]["fill_price"] == 0.20
    assert state["cash"] == 980.0


def test_risk_over_two_percent_is_blocked():
    report, state = open_shadow(packet(max_loss=21.0, ask=0.20), initial_state(), now=NOW, execute_paper=True)
    assert report["status"] == "blocked"
    assert "per_trade_risk_budget_exceeded" in report["blockers"]
    assert state["positions"] == {}


def test_stale_quote_fails_closed():
    with pytest.raises(ValueError, match="Stale"):
        open_shadow(packet(ask=0.20, quoted_at=NOW - timedelta(minutes=3)), initial_state(), now=NOW, execute_paper=True)


def test_review_warning_fails_closed():
    with pytest.raises(ValueError, match="warnings"):
        open_shadow(packet(ask=0.20, warnings=["insufficient buying power"]), initial_state(), now=NOW, execute_paper=True)


def test_duplicate_packet_is_idempotent():
    _, state = open_shadow(packet(ask=0.20), initial_state(), now=NOW, execute_paper=True)
    report, unchanged = open_shadow(packet(ask=0.20), state, now=NOW, execute_paper=True)
    assert report["status"] == "duplicate_packet"
    assert unchanged == state


def test_close_uses_bid_and_records_realized_pnl():
    _, state = open_shadow(packet(ask=0.20), initial_state(), now=NOW, execute_paper=True)
    close_packet = packet(bid=0.30, ask=0.32, quoted_at=NOW + timedelta(seconds=30))
    close_packet["close_reason"] = "profit_target"
    report, closed = close_shadow(close_packet, state, now=NOW + timedelta(seconds=30), execute_paper=True)
    assert report["status"] == "paper_closed"
    assert report["fills"][0]["fill_price"] == 0.30
    assert report["pnl"] == 10.0
    assert closed["cash"] == 1010.0
    assert closed["positions"] == {}


def qualified_profile():
    return OptionsTraderProfile(
        handle="verified_options_trader",
        source="robinhood_social_verified",
        verified_by_robinhood=True,
        complete_closed_history=True,
        losing_trades_included=True,
        closed_trades=180,
        distinct_trading_days=120,
        profit_factor=1.55,
        expectancy_per_trade=0.03,
        max_drawdown_pct=0.11,
        bounded_risk_trade_fraction=1.0,
        median_signal_delay_seconds=45,
    )


def test_only_complete_verified_trader_history_reaches_paper_watch():
    result = evaluate_trader(qualified_profile())
    assert result["status"] == "paper_watch"
    assert result["execution_enabled"] is False


def test_shared_trade_stays_paper_only_and_blocks_stale_copy():
    profile = evaluate_trader(qualified_profile())
    trade = {"trade_id": "social-1", "strategy": "call_debit_spread", "robinhood_verified_trade": True, "defined_risk": True, "max_loss_dollars": 20, "leader_executable_price": 0.50, "current_executable_price": 0.52, "observed_at": NOW.isoformat()}
    accepted = evaluate_shared_trade(trade, profile, now=NOW)
    assert accepted["action"] == "paper_candidate"
    assert accepted["can_submit_orders"] is False
    stale = evaluate_shared_trade({**trade, "observed_at": (NOW - timedelta(minutes=10)).isoformat()}, profile, now=NOW)
    assert stale["action"] == "skip"
    assert "stale_shared_trade" in stale["blockers"]


def test_kinfo_profile_with_hidden_contracts_is_not_copyable():
    base = qualified_profile()
    profile = OptionsTraderProfile(
        **{
            **base.__dict__,
            "source": "kinfo_broker_verified_public",
            "coverage_manifest_verified": False,
            "trades_visible": False,
            "exact_contracts_visible": False,
        }
    )

    result = evaluate_trader(profile)

    assert result["status"] == "reject"
    assert "kinfo_account_coverage_not_verified" in result["blockers"]
    assert "kinfo_trades_hidden_or_not_replicable" in result["blockers"]
    assert result["execution_enabled"] is False

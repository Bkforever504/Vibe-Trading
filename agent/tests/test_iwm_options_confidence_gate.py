from __future__ import annotations

import json
from datetime import date, timedelta
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _leg(symbol: str, *, delta: float, bid: float, ask: float, expiry: date | None = None, strike: float = 100.0):
    from strategies.iwm_options_bot import Leg

    return Leg(
        symbol=symbol,
        expiry=expiry or date.today() + timedelta(days=10),
        strike=strike,
        right="P",
        delta=delta,
        bid=bid,
        ask=ask,
    )


def test_options_candidate_confidence_blocks_low_quality_credit() -> None:
    from strategies import iwm_options_bot as bot

    short_put = _leg("IWM260717P00200000", delta=0.25, bid=1.00, ask=1.10)
    long_put = _leg("IWM260717P00197000", delta=0.12, bid=0.75, ask=0.85, strike=97.0)

    decision = bot._candidate_confidence(
        strategy="put_spread",
        symbol="IWM",
        legs=[short_put, long_put],
        net_credit=0.05,
        max_risk=295.0,
        dte=10,
        trend_ok=True,
    )

    assert decision["score"] < bot.MIN_CANDIDATE_CONFIDENCE
    assert decision["allowed"] is False
    assert "credit/risk too thin" in decision["reasons"]


def test_options_candidate_confidence_allows_clean_put_spread() -> None:
    from strategies import iwm_options_bot as bot

    short_put = _leg("IWM260717P00200000", delta=0.25, bid=1.00, ask=1.10)
    long_put = _leg("IWM260717P00197000", delta=0.12, bid=0.22, ask=0.24, strike=97.0)

    decision = bot._candidate_confidence(
        strategy="put_spread",
        symbol="IWM",
        legs=[short_put, long_put],
        net_credit=0.80,
        max_risk=220.0,
        dte=10,
        trend_ok=True,
    )

    assert decision["allowed"] is True
    assert decision["score"] >= bot.MIN_CANDIDATE_CONFIDENCE
    assert decision["reasons"]


def test_put_spread_records_trend_filter_skip(monkeypatch) -> None:
    from strategies import iwm_options_bot as bot

    decisions = []
    monkeypatch.setattr(bot, "_above_20sma", lambda symbol: False)
    monkeypatch.setattr(bot, "_decision", lambda *args, **kwargs: decisions.append((args, kwargs)))

    assert bot.run_put_spread(None, None, "SPY", 10_000) is False

    assert decisions == [(("SPY", "ps", "skip", "trend_filter_below_20sma"), {})]


def test_put_spread_records_credit_to_risk_skip(monkeypatch) -> None:
    from strategies import iwm_options_bot as bot

    expiry = date.today() + timedelta(days=10)
    short_put = _leg("SPY260717P00740000", delta=0.25, bid=1.00, ask=1.10, expiry=expiry, strike=740.0)
    long_put = _leg("SPY260717P00735000", delta=0.10, bid=0.24, ask=0.26, expiry=expiry, strike=735.0)
    decisions = []

    monkeypatch.setattr(bot, "_above_20sma", lambda symbol: True)
    monkeypatch.setattr(bot, "_fetch_chain", lambda data_client, symbol, dte_min, dte_max, right: [short_put, long_put])
    monkeypatch.setattr(bot, "_decision", lambda *args, **kwargs: decisions.append((args, kwargs)))

    assert bot.run_put_spread(None, None, "SPY", 10_000) is False

    assert decisions
    args, details = decisions[-1]
    assert args == ("SPY", "ps", "skip", "credit_to_risk_below_minimum")
    assert details["credit_to_risk"] < bot.MIN_CREDIT_TO_RISK


def test_place_mleg_records_candidate_confidence_in_trade_state(monkeypatch, tmp_path) -> None:
    from strategies import iwm_options_bot as bot

    state_file = tmp_path / "options-trades.json"
    monkeypatch.setattr(bot, "TRADE_STATE_FILE", state_file)
    monkeypatch.setattr(bot, "REQUIRE_MANUAL_APPROVAL", False)
    monkeypatch.setattr(bot, "_broker_open_underlying_symbols", lambda: set())
    monkeypatch.setattr(bot, "_guard_submission", lambda label, qty, trade_meta: True)
    monkeypatch.setattr(bot, "_post_order_with_retry", lambda body, label: {"id": "order-123"})
    monkeypatch.setattr(bot, "_alert", lambda message: None)

    submitted = bot._place_mleg(
        legs_payload=[
            {"symbol": "IWM260717P00200000", "side": "sell", "ratio_qty": "1"},
            {"symbol": "IWM260717P00197000", "side": "buy", "ratio_qty": "1"},
        ],
        limit_price=0.80,
        qty=1,
        label="Put Spread [IWM]",
        trade_meta={
            "label": "Put Spread [IWM]",
            "strategy": "put_spread",
            "underlying": "IWM",
            "legs": ["IWM260717P00200000", "IWM260717P00197000"],
            "net_credit": 0.80,
            "candidate_confidence": {"score": 8.5, "allowed": True, "reasons": ["clean candidate"]},
        },
    )

    assert submitted is True
    state = bot._load_trade_state()
    assert state["trades"][0]["candidate_confidence"]["score"] == 8.5


def test_place_mleg_blocks_when_shadow_consensus_says_stand_aside(monkeypatch, tmp_path) -> None:
    from strategies import iwm_options_bot as bot

    state_file = tmp_path / "options-trades.json"
    posted = []
    alerts = []

    monkeypatch.setattr(bot, "TRADE_STATE_FILE", state_file)
    monkeypatch.setattr(bot, "REQUIRE_MANUAL_APPROVAL", False)
    monkeypatch.setattr(bot, "_guard_submission", lambda label, qty, trade_meta: True)
    monkeypatch.setattr(bot, "_post_order_with_retry", lambda body, label: posted.append((body, label)) or {"id": "order-123"})
    monkeypatch.setattr(bot, "_alert", lambda message: alerts.append(message))
    monkeypatch.setattr(
        bot,
        "shadow_entry_advice",
        lambda symbol, contracts: {
            "enabled": True,
            "allowed": False,
            "adjusted_contracts": 0,
            "recommendation": "stand_aside",
            "blockers": ["portfolio_kill_switch_active"],
            "reasons": ["Daily loss kill switch is active"],
        },
        raising=False,
    )

    submitted = bot._place_mleg(
        legs_payload=[
            {"symbol": "TSLA260717P00400000", "side": "sell", "ratio_qty": "1"},
            {"symbol": "TSLA260717P00395000", "side": "buy", "ratio_qty": "1"},
        ],
        limit_price=0.80,
        qty=2,
        label="Put Spread [TSLA]",
        trade_meta={
            "label": "Put Spread [TSLA]",
            "strategy": "put_spread",
            "underlying": "TSLA",
            "legs": ["TSLA260717P00400000", "TSLA260717P00395000"],
            "net_credit": 0.80,
        },
    )

    assert submitted is False
    assert posted == []
    assert alerts
    assert "SHADOW CONSENSUS BLOCKED" in alerts[-1]


def test_options_group_stop_triggers_at_100_percent_of_credit(monkeypatch, tmp_path) -> None:
    from types import SimpleNamespace
    from strategies import iwm_options_bot as bot

    state_file = tmp_path / "options-trades.json"
    state_file.write_text(
        json.dumps(
            {
                "trades": [
                    {
                        "label": "Recovered MLEG [IWM]",
                        "status": "open",
                        "legs": ["IWM1", "IWM2"],
                        "net_credit": 0.27,
                        "qty": 2,
                        "profit_close_pct": 0.5,
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(bot, "TRADE_STATE_FILE", state_file)
    monkeypatch.setattr(bot, "AUTO_CLOSE_GROUPS", True)
    monkeypatch.setattr(bot, "_can_submit_option_close_orders", lambda: True)

    closed = []

    class FakeClient:
        def get_all_positions(self):
            return [
                SimpleNamespace(symbol="IWM1", asset_class="us_option", unrealized_pl=-30.0),
                SimpleNamespace(symbol="IWM2", asset_class="us_option", unrealized_pl=-24.0),
            ]

        def close_position(self, symbol):
            closed.append(symbol)

    bot.monitor_and_close(FakeClient())

    state = bot._load_trade_state()
    assert closed == ["IWM1", "IWM2"]
    assert state["trades"][0]["status"] == "closing"
    assert "stop loss hit: -100.0%" in state["trades"][0]["closing_reason"]


def test_options_group_exit_waits_when_option_market_closed(monkeypatch, tmp_path) -> None:
    from types import SimpleNamespace
    from strategies import iwm_options_bot as bot

    state_file = tmp_path / "options-trades.json"
    state_file.write_text(
        json.dumps(
            {
                "trades": [
                    {
                        "label": "Put Spread [AAPL]",
                        "status": "open",
                        "legs": ["AAPL1", "AAPL2"],
                        "net_credit": 0.87,
                        "qty": 3,
                        "profit_close_pct": 0.5,
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(bot, "TRADE_STATE_FILE", state_file)
    monkeypatch.setattr(bot, "AUTO_CLOSE_GROUPS", True)
    monkeypatch.setattr(bot, "_can_submit_option_close_orders", lambda: False)

    closed = []

    class FakeClient:
        def get_all_positions(self):
            return [
                SimpleNamespace(symbol="AAPL1", asset_class="us_option", unrealized_pl=-140.0),
                SimpleNamespace(symbol="AAPL2", asset_class="us_option", unrealized_pl=-122.0),
            ]

        def close_position(self, symbol):
            closed.append(symbol)

    bot.monitor_and_close(FakeClient())

    state = bot._load_trade_state()
    assert closed == []
    assert state["trades"][0]["status"] == "open"
    assert "stop loss hit" in state["trades"][0]["exit_pending_reason"]
    assert "exit_pending_at" in state["trades"][0]


def test_options_monitor_clears_stale_pending_exit_when_trade_recovers(monkeypatch, tmp_path) -> None:
    from types import SimpleNamespace
    from strategies import iwm_options_bot as bot

    state_file = tmp_path / "options-trades.json"
    state_file.write_text(
        json.dumps(
            {
                "trades": [
                    {
                        "label": "Put Spread [AAPL]",
                        "status": "open",
                        "legs": ["AAPL1", "AAPL2"],
                        "net_credit": 0.87,
                        "qty": 3,
                        "profit_close_pct": 0.5,
                        "exit_pending_reason": "stop loss hit: -106.9% of credit",
                        "exit_pending_at": "2026-07-06T11:12:09Z",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(bot, "TRADE_STATE_FILE", state_file)
    monkeypatch.setattr(bot, "AUTO_CLOSE_GROUPS", True)

    class FakeClient:
        def get_all_positions(self):
            return [
                SimpleNamespace(symbol="AAPL1", asset_class="us_option", unrealized_pl=10.0),
                SimpleNamespace(symbol="AAPL2", asset_class="us_option", unrealized_pl=11.0),
            ]

    bot.monitor_and_close(FakeClient())

    state = bot._load_trade_state()
    assert "exit_pending_reason" not in state["trades"][0]
    assert "exit_pending_at" not in state["trades"][0]


def test_options_monitor_profit_protects_credit_winner_after_giveback(monkeypatch, tmp_path) -> None:
    from types import SimpleNamespace
    from strategies import iwm_options_bot as bot

    state_file = tmp_path / "options-trades.json"
    state_file.write_text(
        json.dumps(
            {
                "trades": [
                    {
                        "label": "Put Spread [PLTR]",
                        "status": "open",
                        "legs": ["PLTR1", "PLTR2"],
                        "net_credit": 0.65,
                        "qty": 3,
                        "profit_close_pct": 0.5,
                        "best_pnl_pct": 0.44,
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(bot, "TRADE_STATE_FILE", state_file)
    monkeypatch.setattr(bot, "AUTO_CLOSE_GROUPS", True)
    monkeypatch.setattr(bot, "_can_submit_option_close_orders", lambda: True)

    closed = []

    class FakeClient:
        def get_all_positions(self):
            return [
                SimpleNamespace(symbol="PLTR1", asset_class="us_option", unrealized_pl=28.0),
                SimpleNamespace(symbol="PLTR2", asset_class="us_option", unrealized_pl=20.75),
            ]

        def close_position(self, symbol):
            closed.append(symbol)

    bot.monitor_and_close(FakeClient())

    state = bot._load_trade_state()
    assert closed == ["PLTR1", "PLTR2"]
    assert state["trades"][0]["status"] == "closing"
    assert "profit protect" in state["trades"][0]["closing_reason"]
    assert state["trades"][0]["best_pnl_pct"] == 0.44


def test_options_monitor_defensively_exits_on_shadow_liquidity_or_direction_review(monkeypatch, tmp_path) -> None:
    from types import SimpleNamespace
    from strategies import iwm_options_bot as bot

    state_file = tmp_path / "options-trades.json"
    state_file.write_text(
        json.dumps(
            {
                "trades": [
                    {
                        "label": "Put Spread [PLTR]",
                        "status": "open",
                        "underlying": "PLTR",
                        "legs": ["PLTR1", "PLTR2"],
                        "net_credit": 0.65,
                        "qty": 3,
                        "profit_close_pct": 0.5,
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(bot, "TRADE_STATE_FILE", state_file)
    monkeypatch.setattr(bot, "AUTO_CLOSE_GROUPS", True)
    monkeypatch.setattr(bot, "_can_submit_option_close_orders", lambda: True)
    monkeypatch.setattr(
        bot,
        "shadow_exit_advice",
        lambda symbol, right: {
            "enabled": True,
            "action": "review_exit",
            "recommendation": "stand_aside",
            "options_playbook": "none",
            "blockers": ["options_liquidity_unknown", "mixed_higher_timeframes"],
            "reasons": ["Liquidity/direction no longer support the open risk."],
        },
    )

    closed = []

    class FakeClient:
        def get_all_positions(self):
            return [
                SimpleNamespace(symbol="PLTR1", asset_class="us_option", unrealized_pl=-2.0),
                SimpleNamespace(symbol="PLTR2", asset_class="us_option", unrealized_pl=-1.0),
            ]

        def close_position(self, symbol):
            closed.append(symbol)

    bot.monitor_and_close(FakeClient())

    state = bot._load_trade_state()
    assert closed == ["PLTR1", "PLTR2"]
    assert state["trades"][0]["status"] == "closing"
    assert state["trades"][0]["closing_reason"].startswith("shadow defensive exit")


def test_options_monitor_protects_mid_profit_winner_before_full_stop(monkeypatch, tmp_path) -> None:
    from types import SimpleNamespace
    from strategies import iwm_options_bot as bot

    state_file = tmp_path / "options-trades.json"
    state_file.write_text(
        json.dumps(
            {
                "trades": [
                    {
                        "label": "Put Spread [PLTR]",
                        "status": "open",
                        "legs": ["PLTR1", "PLTR2"],
                        "net_credit": 0.65,
                        "qty": 3,
                        "profit_close_pct": 0.5,
                        "best_pnl_pct": 0.2154,
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(bot, "TRADE_STATE_FILE", state_file)
    monkeypatch.setattr(bot, "AUTO_CLOSE_GROUPS", True)
    monkeypatch.setattr(bot, "_can_submit_option_close_orders", lambda: True)

    closed = []

    class FakeClient:
        def get_all_positions(self):
            return [
                SimpleNamespace(symbol="PLTR1", asset_class="us_option", unrealized_pl=-2.0),
                SimpleNamespace(symbol="PLTR2", asset_class="us_option", unrealized_pl=-1.0),
            ]

        def close_position(self, symbol):
            closed.append(symbol)

    bot.monitor_and_close(FakeClient())

    state = bot._load_trade_state()
    assert closed == ["PLTR1", "PLTR2"]
    assert state["trades"][0]["status"] == "closing"
    assert "profit protect" in state["trades"][0]["closing_reason"]
    assert "best +21.5%" in state["trades"][0]["closing_reason"]


def test_options_monitor_marks_closing_groups_closed_when_no_positions_remain(monkeypatch, tmp_path) -> None:
    from strategies import iwm_options_bot as bot

    state_file = tmp_path / "options-trades.json"
    state_file.write_text(
        json.dumps(
            {
                "trades": [
                    {
                        "label": "Recovered MLEG [IWM]",
                        "status": "closing",
                        "legs": ["IWM1", "IWM2"],
                        "net_credit": 0.27,
                        "qty": 2,
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(bot, "TRADE_STATE_FILE", state_file)
    # Flat confirmation now also requires real time between observations
    # (see test_options_state_integrity.py); collapse the window here to
    # test the two-observation count in isolation.
    monkeypatch.setattr(bot, "FLAT_CONFIRM_MIN_SECONDS", 0)

    class FakeClient:
        def get_all_positions(self):
            return []

    first_result = bot.monitor_and_close(FakeClient())

    state = bot._load_trade_state()
    assert first_result is False
    assert state["trades"][0]["status"] == "closing"
    assert state["trades"][0]["flat_observation_count"] == 1

    second_result = bot.monitor_and_close(FakeClient())

    state = bot._load_trade_state()
    assert second_result is True
    assert state["trades"][0]["status"] == "closed"
    assert "closed_at" in state["trades"][0]


def test_options_monitor_clears_transient_flat_observation_when_positions_return(monkeypatch, tmp_path) -> None:
    from types import SimpleNamespace
    from strategies import iwm_options_bot as bot

    state_file = tmp_path / "options-trades.json"
    state_file.write_text(
        json.dumps(
            {
                "trades": [
                    {
                        "label": "Put Spread [IWM]",
                        "strategy": "put_spread",
                        "status": "open",
                        "legs": ["IWM260807P00277000", "IWM260807P00275000"],
                        "net_credit": 0.50,
                        "qty": 1,
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(bot, "TRADE_STATE_FILE", state_file)

    class EmptyClient:
        def get_all_positions(self):
            return []

    class RestoredClient:
        def get_all_positions(self):
            return [
                SimpleNamespace(
                    symbol="IWM260807P00277000", asset_class="us_option",
                    unrealized_pl=0.0, qty=-1,
                ),
                SimpleNamespace(
                    symbol="IWM260807P00275000", asset_class="us_option",
                    unrealized_pl=0.0, qty=1,
                ),
            ]

    assert bot.monitor_and_close(EmptyClient()) is False
    assert bot.monitor_and_close(RestoredClient()) is True

    state = bot._load_trade_state()
    assert state["trades"][0]["status"] == "open"
    assert "flat_observation_count" not in state["trades"][0]
    assert "flat_observed_at" not in state["trades"][0]


def test_options_main_blocks_entries_when_position_integrity_is_unresolved(monkeypatch) -> None:
    from strategies import iwm_options_bot as bot

    fake_client = object()
    monkeypatch.setattr(bot, "_build_clients", lambda: (fake_client, object()))
    monkeypatch.setattr(bot, "monitor_and_close", lambda client, data_client=None: False)

    market_checks = []
    monkeypatch.setattr(bot, "_market_is_open", lambda: market_checks.append(True) or True)

    bot.main()

    assert market_checks == []

from __future__ import annotations

import json
from datetime import date, datetime, timedelta
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


@pytest.fixture(autouse=True)
def _isolate_options_decision_log(monkeypatch, tmp_path) -> None:
    from strategies import iwm_options_bot as bot

    monkeypatch.setattr(bot, "DECISION_LOG_FILE", str(tmp_path / "options-decisions.jsonl"))


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

    assert bot.run_put_spread(None, None, "SPY", 100_000) is False

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
    monkeypatch.setattr(bot, "MIN_CREDIT_TO_RISK", 0.20)

    assert bot.run_put_spread(None, None, "SPY", 100_000) is False

    assert decisions
    args, details = decisions[-1]
    assert args == ("SPY", "ps", "skip", "credit_to_risk_below_minimum")
    assert details["credit_to_risk"] < bot.MIN_CREDIT_TO_RISK


def test_call_spread_records_above_sma_skip(monkeypatch) -> None:
    from strategies import iwm_options_bot as bot

    decisions = []
    monkeypatch.setattr(bot, "_above_20sma", lambda symbol: True)
    monkeypatch.setattr(bot, "_decision", lambda *args, **kwargs: decisions.append((args, kwargs)))

    assert bot.run_call_spread(None, None, "SPY", 10_000) is False
    assert decisions == [(("SPY", "cs", "skip", "trend_filter_above_20sma_use_ps"), {})]


def test_entry_window_allows_only_best_fill_windows(monkeypatch) -> None:
    from strategies import iwm_options_bot as bot

    monkeypatch.setattr(bot, "OPTIONS_ENTRY_WINDOWS_ET", "09:45-10:30,15:00-15:45")

    assert bot._entry_window_open(datetime(2026, 7, 29, 9, 45)) is True
    assert bot._entry_window_open(datetime(2026, 7, 29, 15, 30)) is True
    assert bot._entry_window_open(datetime(2026, 7, 29, 12, 0)) is False


def test_call_spread_builds_credit_mleg_when_below_sma(monkeypatch) -> None:
    from strategies import iwm_options_bot as bot

    expiry = date.today() + timedelta(days=10)
    short_call = _leg("SPY260807C00620000", delta=0.25, bid=2.00, ask=2.10, expiry=expiry, strike=620.0)
    long_call = _leg("SPY260807C00625000", delta=0.10, bid=0.30, ask=0.40, expiry=expiry, strike=625.0)
    submitted = []
    monkeypatch.setattr(bot, "_above_20sma", lambda symbol: False)
    monkeypatch.setattr(bot, "_fetch_chain", lambda *args: [short_call, long_call])
    monkeypatch.setattr(bot, "_candidate_confidence", lambda **kwargs: {"allowed": True})
    monkeypatch.setattr(bot, "_sized_qty", lambda *args: 1)
    monkeypatch.setattr(bot, "_place_mleg", lambda **kwargs: submitted.append(kwargs) or True)

    assert bot.run_call_spread(None, None, "SPY", 100_000) is True
    assert submitted[0]["trade_meta"]["strategy"] == "call_spread"
    assert submitted[0]["legs_payload"][0]["side"] == "sell"
    assert submitted[0]["legs_payload"][1]["side"] == "buy"


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
    assert state["trades"][0]["status"] == "pending"
    assert state["trades"][0]["submitted_limit_credit"] == 0.80


def test_place_mleg_records_actual_broker_fill_credit(monkeypatch, tmp_path) -> None:
    from strategies import iwm_options_bot as bot

    state_file = tmp_path / "options-trades.json"
    monkeypatch.setattr(bot, "TRADE_STATE_FILE", state_file)
    monkeypatch.setattr(bot, "REQUIRE_MANUAL_APPROVAL", False)
    monkeypatch.setattr(bot, "_guard_submission", lambda label, qty, trade_meta: True)
    monkeypatch.setattr(bot, "shadow_entry_advice", lambda *_args: {"enabled": False})
    monkeypatch.setattr(
        bot,
        "_post_order_with_retry",
        lambda body, label: {
            "id": "filled-order",
            "status": "filled",
            "filled_qty": "1",
            "filled_avg_price": "-0.86",
            "filled_at": "2026-07-21T15:00:00Z",
            "legs": [
                {"symbol": "AAPL260731P00315000"},
                {"symbol": "AAPL260731P00310000"},
            ],
        },
    )
    monkeypatch.setattr(bot, "_alert", lambda message: None)

    submitted = bot._place_mleg(
        legs_payload=[
            {"symbol": "AAPL260731P00315000", "side": "sell", "ratio_qty": "1"},
            {"symbol": "AAPL260731P00310000", "side": "buy", "ratio_qty": "1"},
        ],
        limit_price=1.04,
        qty=1,
        label="Put Spread [AAPL]",
        trade_meta={
            "label": "Put Spread [AAPL]",
            "strategy": "put_spread",
            "underlying": "AAPL",
            "legs": ["AAPL260731P00315000", "AAPL260731P00310000"],
            "net_credit": 1.04,
            "max_risk_per_contract": 396.0,
        },
    )

    assert submitted is True
    trade = bot._load_trade_state()["trades"][0]
    assert trade["status"] == "open"
    assert trade["submitted_limit_credit"] == 1.04
    assert trade["net_credit"] == 0.86
    assert trade["entry_filled_avg_price_signed"] == -0.86
    assert trade["entry_fill_source"] == "alpaca_filled_avg_price"
    assert trade["max_risk_per_contract"] == 414.0


def test_options_caution_gate_blocks_multi_warning_stand_aside(monkeypatch, tmp_path) -> None:
    from strategies import iwm_options_bot as bot

    state_file = tmp_path / "options-trades.json"
    posted = []
    decisions = []
    twin_decisions = []
    monkeypatch.setattr(bot, "TRADE_STATE_FILE", state_file)
    monkeypatch.setattr(bot, "REQUIRE_MANUAL_APPROVAL", False)
    monkeypatch.setattr(bot, "OPTIONS_STRICT_SHADOW_CAUTION_GATE", True)
    monkeypatch.setattr(bot, "OPTIONS_STRICT_CAUTION_MIN_WARNINGS", 2)
    monkeypatch.setattr(bot, "shadow_twin_record_candidate", lambda *_args, **_kwargs: "candidate-1")
    monkeypatch.setattr(
        bot,
        "shadow_twin_record_decision",
        lambda *args, **kwargs: twin_decisions.append((args, kwargs)),
    )
    monkeypatch.setattr(bot, "_guard_submission", lambda *_args: True)
    monkeypatch.setattr(
        bot,
        "_post_order_with_retry",
        lambda body, label: posted.append((body, label)) or {"id": "should-not-post"},
    )
    monkeypatch.setattr(bot, "_alert", lambda message: None)
    monkeypatch.setattr(
        bot,
        "_decision",
        lambda *args, **kwargs: decisions.append((args, kwargs)),
    )
    monkeypatch.setattr(
        bot,
        "shadow_entry_advice",
        lambda *_args: {
            "enabled": True,
            "allowed": True,
            "adjusted_contracts": 1,
            "recommendation": "stand_aside",
            "options_playbook": "none",
            "blockers": ["market_force_unclear", "htf_intraday_not_aligned"],
            "reasons": ["two independent warnings"],
        },
    )

    submitted = bot._place_mleg(
        legs_payload=[
            {"symbol": "NVDA260731P00200000", "side": "sell", "ratio_qty": "1"},
            {"symbol": "NVDA260731P00197500", "side": "buy", "ratio_qty": "1"},
        ],
        limit_price=0.57,
        qty=1,
        label="Put Spread [NVDA]",
        trade_meta={
            "strategy": "put_spread",
            "underlying": "NVDA",
            "net_credit": 0.57,
        },
    )

    assert submitted is False
    assert posted == []
    assert decisions
    assert decisions[0][0][3] == "shadow_consensus_stand_aside"
    assert decisions[0][1]["recommendation"] == "stand_aside"
    assert twin_decisions[0][0][:2] == ("candidate-1", "blocked_strict_caution")


def test_options_consensus_allows_single_advisory_warning_in_paper_exploration(monkeypatch, tmp_path) -> None:
    from strategies import iwm_options_bot as bot

    state_file = tmp_path / "options-trades.json"
    posted = []
    monkeypatch.setattr(bot, "TRADE_STATE_FILE", state_file)
    monkeypatch.setattr(bot, "REQUIRE_MANUAL_APPROVAL", False)
    monkeypatch.setattr(bot, "OPTIONS_STRICT_SHADOW_CAUTION_GATE", True)
    monkeypatch.setattr(bot, "OPTIONS_STRICT_CAUTION_MIN_WARNINGS", 2)
    monkeypatch.setattr(bot, "ENABLE_OPTIONS_QUANT_RISK_BUDGET", False)
    monkeypatch.setattr(bot, "_garch_entry_adjustment", lambda symbol, qty: (qty, {}, True))
    monkeypatch.setattr(bot, "_guard_submission", lambda *_args: True)
    monkeypatch.setattr(
        bot,
        "_post_order_with_retry",
        lambda body, label: posted.append((body, label)) or {"id": "pending-order", "status": "accepted"},
    )
    monkeypatch.setattr(bot, "_alert", lambda message: None)
    monkeypatch.setattr(
        bot,
        "shadow_entry_advice",
        lambda *_args: {
            "enabled": True,
            "allowed": True,
            "adjusted_contracts": 1,
            "recommendation": "stand_aside",
            "blockers": ["market_force_unclear"],
            "reasons": ["one warning is not enough"],
        },
    )

    assert bot._place_mleg(
        legs_payload=[
            {"symbol": "IWM260731P00300000", "side": "sell", "ratio_qty": "1"},
            {"symbol": "IWM260731P00298000", "side": "buy", "ratio_qty": "1"},
        ],
        limit_price=0.40,
        qty=1,
        label="Put Spread [IWM]",
        trade_meta={"strategy": "put_spread", "underlying": "IWM", "net_credit": 0.40},
    ) is True
    assert len(posted) == 1


def test_options_consensus_blocks_when_options_bot_assist_false(monkeypatch, tmp_path) -> None:
    from strategies import iwm_options_bot as bot

    state_file = tmp_path / "options-trades.json"
    posted = []
    monkeypatch.setattr(bot, "TRADE_STATE_FILE", state_file)
    monkeypatch.setattr(bot, "REQUIRE_MANUAL_APPROVAL", False)
    monkeypatch.setattr(bot, "OPTIONS_BYPASS_BOT_ASSIST_DISABLE", False)
    monkeypatch.setattr(bot, "_guard_submission", lambda *_args: True)
    monkeypatch.setattr(bot, "_post_order_with_retry", lambda body, label: posted.append((body, label)) or {"id": "bad"})
    monkeypatch.setattr(bot, "_alert", lambda message: None)
    monkeypatch.setattr(
        bot,
        "shadow_entry_advice",
        lambda *_args: {
            "enabled": True,
            "allowed": True,
            "adjusted_contracts": 1,
            "recommendation": "size_down",
            "options_playbook": "bullish_put_spread",
            "blockers": ["weak_shadow_pnl_evidence"],
            "reasons": ["Options bot assist is disabled for this symbol."],
            "decision": {"bot_assist": {"options_bot": False}},
        },
    )

    assert bot._place_mleg(
        legs_payload=[
            {"symbol": "NVDA260731P00200000", "side": "sell", "ratio_qty": "1"},
            {"symbol": "NVDA260731P00197500", "side": "buy", "ratio_qty": "1"},
        ],
        limit_price=0.49,
        qty=1,
        label="Put Spread [NVDA]",
        trade_meta={"strategy": "put_spread", "underlying": "NVDA", "net_credit": 0.49},
    ) is False
    assert posted == []


def test_options_consensus_paper_bypass_allows_disabled_assist_without_hard_block(
    monkeypatch,
    tmp_path,
) -> None:
    from strategies import iwm_options_bot as bot

    posted = []
    monkeypatch.setattr(bot, "TRADE_STATE_FILE", tmp_path / "options-trades.json")
    monkeypatch.setattr(bot, "REQUIRE_MANUAL_APPROVAL", False)
    monkeypatch.setattr(bot, "OPTIONS_BYPASS_BOT_ASSIST_DISABLE", True)
    monkeypatch.setattr(bot, "ENABLE_OPTIONS_QUANT_RISK_BUDGET", False)
    monkeypatch.setattr(bot, "_garch_entry_adjustment", lambda symbol, qty: (qty, {}, True))
    monkeypatch.setattr(bot, "_guard_submission", lambda *_args: True)
    monkeypatch.setattr(
        bot,
        "_post_order_with_retry",
        lambda body, label: posted.append((body, label)) or {"id": "paper-order"},
    )
    monkeypatch.setattr(bot, "_alert", lambda message: None)
    monkeypatch.setattr(
        bot,
        "shadow_entry_advice",
        lambda *_args: {
            "enabled": True,
            "allowed": True,
            "adjusted_contracts": 1,
            "recommendation": "size_down",
            "options_playbook": "bullish_put_spread",
            "blockers": ["weak_shadow_pnl_evidence"],
            "reasons": ["Options bot assist is disabled for this symbol."],
            "decision": {"bot_assist": {"options_bot": False}},
        },
    )

    assert bot._place_mleg(
        legs_payload=[
            {"symbol": "NVDA260731P00200000", "side": "sell", "ratio_qty": "1"},
            {"symbol": "NVDA260731P00197500", "side": "buy", "ratio_qty": "1"},
        ],
        limit_price=0.49,
        qty=1,
        label="Put Spread [NVDA]",
        trade_meta={"strategy": "put_spread", "underlying": "NVDA", "net_credit": 0.49},
    ) is True
    assert len(posted) == 1


def test_garch_storm_report_blocks_mleg_entry(monkeypatch, tmp_path) -> None:
    from strategies import iwm_options_bot as bot

    report = tmp_path / "garch.json"
    report.write_text(
        json.dumps(
            {
                "symbols": [
                    {
                        "symbol": "SPY",
                        "status": "ok",
                        "regime": "storm",
                        "position_size_multiplier": 0.75,
                        "forecast_vol_annualized_pct": 32.0,
                        "vol_percentile_1y": 90.0,
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    posted = []
    decisions = []
    monkeypatch.setattr(bot, "GARCH_RISK_REPORT", report)
    monkeypatch.setattr(bot, "ENABLE_GARCH_RISK_GATE", True)
    monkeypatch.setattr(bot, "OPTIONS_GARCH_STORM_BLOCK", True)
    monkeypatch.setattr(bot, "REQUIRE_MANUAL_APPROVAL", False)
    monkeypatch.setattr(bot, "_guard_submission", lambda *_args: True)
    monkeypatch.setattr(bot, "_post_order_with_retry", lambda body, label: posted.append((body, label)) or {"id": "bad"})
    monkeypatch.setattr(bot, "_alert", lambda message: None)
    monkeypatch.setattr(bot, "_decision", lambda *args, **kwargs: decisions.append((args, kwargs)))
    monkeypatch.setattr(bot, "shadow_entry_advice", lambda *_args: {"enabled": False})

    assert bot._place_mleg(
        legs_payload=[
            {"symbol": "SPY260731P00600000", "side": "sell", "ratio_qty": "1"},
            {"symbol": "SPY260731P00595000", "side": "buy", "ratio_qty": "1"},
        ],
        limit_price=0.80,
        qty=1,
        label="Put Spread [SPY]",
        trade_meta={"strategy": "put_spread", "underlying": "SPY", "net_credit": 0.80},
    ) is False

    assert posted == []
    assert decisions[-1][0][3] == "garch_storm_regime"


def test_garch_missing_report_allows_entry_by_default(monkeypatch, tmp_path) -> None:
    from strategies import iwm_options_bot as bot

    posted = []
    monkeypatch.setattr(bot, "GARCH_RISK_REPORT", tmp_path / "missing.json")
    monkeypatch.setattr(bot, "ENABLE_GARCH_RISK_GATE", True)
    monkeypatch.setattr(bot, "OPTIONS_REQUIRE_GARCH_REPORT", False)
    monkeypatch.setattr(bot, "TRADE_STATE_FILE", tmp_path / "options-trades.json")
    monkeypatch.setattr(bot, "REQUIRE_MANUAL_APPROVAL", False)
    monkeypatch.setattr(bot, "_guard_submission", lambda *_args: True)
    monkeypatch.setattr(bot, "_post_order_with_retry", lambda body, label: posted.append((body, label)) or {"id": "order-123"})
    monkeypatch.setattr(bot, "_alert", lambda message: None)
    monkeypatch.setattr(bot, "shadow_entry_advice", lambda *_args: {"enabled": False})

    assert bot._place_mleg(
        legs_payload=[
            {"symbol": "IWM260731P00300000", "side": "sell", "ratio_qty": "1"},
            {"symbol": "IWM260731P00298000", "side": "buy", "ratio_qty": "1"},
        ],
        limit_price=0.40,
        qty=1,
        label="Put Spread [IWM]",
        trade_meta={"strategy": "put_spread", "underlying": "IWM", "net_credit": 0.40},
    ) is True

    assert posted
    trade = bot._load_trade_state()["trades"][0]
    assert trade["garch_volatility_risk"]["reason"] == "garch_report_missing"


def test_garch_reduces_mleg_quantity_without_increasing(monkeypatch, tmp_path) -> None:
    from strategies import iwm_options_bot as bot

    report = tmp_path / "garch.json"
    report.write_text(
        json.dumps(
            {
                "symbols": [
                    {
                        "symbol": "TSLA",
                        "status": "ok",
                        "regime": "normal",
                        "position_size_multiplier": 0.60,
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    posted = []
    monkeypatch.setattr(bot, "GARCH_RISK_REPORT", report)
    monkeypatch.setattr(bot, "ENABLE_GARCH_RISK_GATE", True)
    monkeypatch.setattr(bot, "OPTIONS_GARCH_MIN_ENTRY_MULTIPLIER", 0.50)
    monkeypatch.setattr(bot, "TRADE_STATE_FILE", tmp_path / "options-trades.json")
    monkeypatch.setattr(bot, "REQUIRE_MANUAL_APPROVAL", False)
    monkeypatch.setattr(bot, "_guard_submission", lambda *_args: True)
    monkeypatch.setattr(bot, "_post_order_with_retry", lambda body, label: posted.append(body) or {"id": "order-123"})
    monkeypatch.setattr(bot, "_alert", lambda message: None)
    monkeypatch.setattr(bot, "shadow_entry_advice", lambda *_args: {"enabled": False})

    assert bot._place_mleg(
        legs_payload=[
            {"symbol": "TSLA260731P00400000", "side": "sell", "ratio_qty": "1"},
            {"symbol": "TSLA260731P00395000", "side": "buy", "ratio_qty": "1"},
        ],
        limit_price=0.80,
        qty=3,
        label="Put Spread [TSLA]",
        trade_meta={"strategy": "put_spread", "underlying": "TSLA", "net_credit": 0.80},
    ) is True

    assert posted[0]["qty"] == "1"
    assert bot._load_trade_state()["trades"][0]["qty"] == 1


def test_garch_storm_report_blocks_single_leg_entry(monkeypatch, tmp_path) -> None:
    from strategies import iwm_options_bot as bot

    report = tmp_path / "garch.json"
    report.write_text(
        json.dumps(
            {
                "symbols": [
                    {
                        "symbol": "AAPL",
                        "status": "ok",
                        "regime": "storm",
                        "position_size_multiplier": 0.90,
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    posted = []
    decisions = []
    monkeypatch.setattr(bot, "GARCH_RISK_REPORT", report)
    monkeypatch.setattr(bot, "ENABLE_GARCH_RISK_GATE", True)
    monkeypatch.setattr(bot, "OPTIONS_GARCH_STORM_BLOCK", True)
    monkeypatch.setattr(bot, "REQUIRE_MANUAL_APPROVAL", False)
    monkeypatch.setattr(bot, "_guard_submission", lambda *_args: True)
    monkeypatch.setattr(bot, "_post_order_with_retry", lambda body, label: posted.append(body) or {"id": "bad"})
    monkeypatch.setattr(bot, "_alert", lambda message: None)
    monkeypatch.setattr(bot, "_decision", lambda *args, **kwargs: decisions.append((args, kwargs)))
    monkeypatch.setattr(bot, "shadow_entry_advice", lambda *_args: {"enabled": False})

    assert bot._place_single_leg(
        "AAPL260731P00200000",
        "sell",
        1.25,
        1,
        "Cash Secured Put [AAPL]",
        trade_meta={"strategy": "wheel_csp", "underlying": "AAPL"},
    ) is False

    assert posted == []
    assert decisions[-1][0][3] == "garch_storm_regime"


def test_refresh_entry_fill_backfills_legacy_open_group_without_double_risk_adjustment(
    monkeypatch,
) -> None:
    from strategies import iwm_options_bot as bot

    state = {
        "trades": [
            {
                "id": "legacy-open",
                "order_id": "entry-order",
                "status": "open",
                "label": "Put Spread [NVDA]",
                "legs": ["NVDA1", "NVDA2"],
                "net_credit": 0.57,
                "max_risk_per_contract": 193.0,
                "qty": 1,
            }
        ]
    }
    order = {
        "id": "entry-order",
        "status": "filled",
        "filled_qty": "1",
        "filled_avg_price": "-0.49",
        "legs": [{"symbol": "NVDA1"}, {"symbol": "NVDA2"}],
    }
    monkeypatch.setattr(bot, "_order_snapshot", lambda order_id: order)

    assert bot._refresh_entry_order_fills(state)
    trade = state["trades"][0]
    assert trade["net_credit"] == 0.49
    assert trade["max_risk_per_contract"] == 201.0
    assert trade["submitted_max_risk_per_contract"] == 193.0
    assert not bot._refresh_entry_order_fills(state)
    assert trade["max_risk_per_contract"] == 201.0


def test_partial_entry_fill_updates_to_final_filled_quantity(monkeypatch) -> None:
    from strategies import iwm_options_bot as bot

    state = {
        "trades": [
            {
                "id": "partial",
                "order_id": "entry-order",
                "status": "pending",
                "entry_order_status": "accepted",
                "label": "Put Spread [SPY]",
                "legs": ["SPY1", "SPY2"],
                "net_credit": 0.80,
                "max_risk_per_contract": 420.0,
                "qty": 2,
            }
        ]
    }
    responses = iter(
        [
            {
                "status": "partially_filled",
                "filled_qty": "1",
                "filled_avg_price": "-0.75",
                "legs": [{"symbol": "SPY1"}, {"symbol": "SPY2"}],
            },
            {
                "status": "filled",
                "filled_qty": "2",
                "filled_avg_price": "-0.74",
                "legs": [{"symbol": "SPY1"}, {"symbol": "SPY2"}],
            },
        ]
    )
    monkeypatch.setattr(bot, "_order_snapshot", lambda order_id: next(responses))

    assert bot._refresh_entry_order_fills(state)
    assert state["trades"][0]["qty"] == 1
    assert bot._refresh_entry_order_fills(state)
    assert state["trades"][0]["qty"] == 2
    assert state["trades"][0]["net_credit"] == 0.74


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


def test_options_group_stop_triggers_at_200_percent_of_credit(monkeypatch, tmp_path) -> None:
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
                            "leg_details": [
                                {"symbol": "IWM1", "side": "sell", "ratio_qty": 1},
                                {"symbol": "IWM2", "side": "buy", "ratio_qty": 1},
                            ],
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
    monkeypatch.setattr(
        bot.options_state,
        "reconcile",
        lambda *_args: {"entries_allowed": True, "findings": [], "group_states": {}},
    )

    closed = []

    class FakeClient:
        def get_all_positions(self):
            return [
                SimpleNamespace(symbol="IWM1", asset_class="us_option", qty=-2, unrealized_pl=-60.0),
                SimpleNamespace(symbol="IWM2", asset_class="us_option", qty=2, unrealized_pl=-54.0),
            ]

        def close_position(self, symbol):
            closed.append(symbol)

    bot.monitor_and_close(FakeClient())

    state = bot._load_trade_state()
    assert closed == ["IWM1", "IWM2"]
    assert state["trades"][0]["status"] == "closing"
    assert "stop loss hit: -211.1%" in state["trades"][0]["closing_reason"]


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
                            "leg_details": [
                                {"symbol": "AAPL1", "side": "sell", "ratio_qty": 1},
                                {"symbol": "AAPL2", "side": "buy", "ratio_qty": 1},
                            ],
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
    monkeypatch.setattr(
        bot.options_state,
        "reconcile",
        lambda *_args: {"entries_allowed": True, "findings": [], "group_states": {}},
    )

    closed = []

    class FakeClient:
        def get_all_positions(self):
            return [
                SimpleNamespace(symbol="AAPL1", asset_class="us_option", qty=-3, unrealized_pl=-300.0),
                SimpleNamespace(symbol="AAPL2", asset_class="us_option", qty=3, unrealized_pl=-290.0),
            ]

        def close_position(self, symbol):
            closed.append(symbol)

    bot.monitor_and_close(FakeClient())

    state = bot._load_trade_state()
    assert closed == []
    assert state["trades"][0]["status"] == "open"
    assert "stop loss hit" in state["trades"][0]["exit_pending_reason"]
    assert "exit_pending_at" in state["trades"][0]


def test_close_group_ignores_stale_netted_quote_mark_when_all_legs_present(monkeypatch) -> None:
    from strategies import iwm_options_bot as bot

    closed = []
    alerts = []

    class FakeClient:
        def close_position(self, symbol):
            closed.append(symbol)

    monkeypatch.setattr(bot, "_alert", lambda message: alerts.append(message))
    trade = {
        "id": "iwm-stale-net",
        "label": "Iron Condor [IWM]",
        "status": "open",
        "strategy": "iron_condor",
        "qty": 1,
        "legs": ["IWM-P1", "IWM-P2", "IWM-C1", "IWM-C2"],
        "quote_mark": {
            "status": "ok",
            "marked_at": "2026-07-14T17:00:05Z",
            "netted_legs": ["IWM-P1"],
            "close_plan": {"status": "ok", "transition_legs": ["IWM-P1"]},
        },
    }

    assert bot._close_trade_group(FakeClient(), trade, "stop loss hit") is False
    assert closed == []
    assert alerts == []


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
                SimpleNamespace(symbol="AAPL1", asset_class="us_option", qty=3, unrealized_pl=10.0),
                SimpleNamespace(symbol="AAPL2", asset_class="us_option", qty=3, unrealized_pl=11.0),
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
                            "leg_details": [
                                {"symbol": "PLTR1", "side": "sell", "ratio_qty": 1},
                                {"symbol": "PLTR2", "side": "buy", "ratio_qty": 1},
                            ],
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
                SimpleNamespace(symbol="PLTR1", asset_class="us_option", qty=3, unrealized_pl=28.0),
                SimpleNamespace(symbol="PLTR2", asset_class="us_option", qty=3, unrealized_pl=20.75),
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
                SimpleNamespace(symbol="PLTR1", asset_class="us_option", qty=-3, unrealized_pl=-2.0),
                SimpleNamespace(symbol="PLTR2", asset_class="us_option", qty=3, unrealized_pl=-1.0),
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
    monkeypatch.setattr(
        bot,
        "_credit_near_target_reason",
        lambda *_args: "profit protect: test (best +21.5%)",
    )
    monkeypatch.setattr(
        bot.options_state,
        "reconcile",
        lambda *_args: {"entries_allowed": True, "findings": [], "group_states": {}},
    )

    closed = []

    class FakeClient:
        def get_all_positions(self):
            return [
                SimpleNamespace(symbol="PLTR1", asset_class="us_option", qty=3, unrealized_pl=-2.0),
                SimpleNamespace(symbol="PLTR2", asset_class="us_option", qty=3, unrealized_pl=-1.0),
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

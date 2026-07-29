from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def test_flip_bot_submit_blocks_live_mid_above_risk_budget(monkeypatch) -> None:
    from strategies import flip_bot

    posted = []
    monkeypatch.setattr(flip_bot, "_option_mid", lambda symbol: 2.52)
    monkeypatch.setattr(flip_bot, "_post", lambda path, body: posted.append((path, body)) or {"id": "order"})
    monkeypatch.setattr(flip_bot, "manual_reset_required", lambda: False)
    monkeypatch.setattr(flip_bot, "_alert", lambda msg: None)

    result = flip_bot._submit("SPY260623P00733000", 5, "buy", max_notional=100.0)

    assert result is None
    assert posted == []


def test_flip_bot_submit_supports_resting_sell_limit(monkeypatch) -> None:
    from strategies import flip_bot

    posted = []
    monkeypatch.setattr(flip_bot, "_post", lambda path, body: posted.append((path, body)) or {"id": "tp-1"})
    monkeypatch.setattr(flip_bot, "manual_reset_required", lambda: False)

    result = flip_bot._submit("SPY260720C00750000", 2, "sell", limit_price=1.75)

    assert result == {"id": "tp-1"}
    assert posted == [
        (
            "/v2/orders",
            {
                "symbol": "SPY260720C00750000",
                "qty": "2",
                "side": "sell",
                "time_in_force": "day",
                "type": "limit",
                "limit_price": "1.75",
            },
        )
    ]


def test_manual_reset_blocks_new_buys_but_allows_protective_sells(monkeypatch) -> None:
    from strategies import flip_bot

    posted = []
    monkeypatch.setattr(flip_bot, "manual_reset_required", lambda: True)
    monkeypatch.setattr(flip_bot, "_post", lambda path, body: posted.append(body) or {"id": "sell-1"})
    monkeypatch.setattr(flip_bot, "_alert", lambda msg: None)

    assert flip_bot._submit("SPY260720C00750000", 1, "buy") is None
    assert flip_bot._submit("SPY260720C00750000", 1, "sell") == {"id": "sell-1"}
    assert posted == [
        {
            "symbol": "SPY260720C00750000",
            "qty": "1",
            "side": "sell",
            "time_in_force": "day",
            "type": "market",
        }
    ]


def test_flip_bot_entry_submits_bear_trend_spread_as_two_leg_order(monkeypatch, tmp_path) -> None:
    from types import SimpleNamespace
    from strategies import flip_bot

    state_file = tmp_path / "flip-trades.json"
    submitted_spreads = []
    submitted_singles = []

    monkeypatch.setattr(flip_bot, "STATE_FILE", state_file)
    monkeypatch.setattr(flip_bot, "_market_open", lambda: True)
    monkeypatch.setattr(flip_bot, "_load", lambda: [])
    monkeypatch.setattr(flip_bot, "log_shadow_0dte_candidates", lambda account: [])
    monkeypatch.setattr(flip_bot, "find_bear_trend_day", lambda account: {
        "strategy": "bear_trend_spread",
        "symbol": "SPY",
        "right": "PUT",
        "option_symbol": "SPY260626P00735000",
        "short_option_symbol": "SPY260626P00730000",
        "strike": 735.0,
        "short_strike": 730.0,
        "expiry": "2026-06-26",
        "contracts": 2,
        "entry_price_est": 1.25,
        "max_loss": 250.0,
        "max_gain": 750.0,
        "confidence": 9,
        "hard_close_date": "2026-06-25",
        "hard_close_time": "13:45",
        "catalyst": "VWAP/50EMA bear spread 9/10",
    })
    monkeypatch.setattr(flip_bot, "find_bull_trend_day", lambda account: None)
    monkeypatch.setattr(flip_bot, "find_0dte", lambda account: None)
    monkeypatch.setattr(flip_bot, "find_earnings", lambda account: [])
    monkeypatch.setattr(flip_bot, "find_breakouts", lambda account: [])
    monkeypatch.setattr(flip_bot, "_fetch_broker_open_symbols", lambda: set())
    monkeypatch.setattr(
        flip_bot,
        "evaluate_execution",
        lambda **kwargs: SimpleNamespace(allowed=True, reason="", details={}),
    )
    monkeypatch.setattr(flip_bot, "_submit", lambda *args, **kwargs: submitted_singles.append((args, kwargs)) or {"id": "single"})
    monkeypatch.setattr(
        flip_bot,
        "_submit_spread",
        lambda setup, max_notional: submitted_spreads.append((setup, max_notional)) or {"id": "spread-order"},
    )
    monkeypatch.setattr(
        flip_bot,
        "_get",
        lambda path: {"id": "spread-order", "status": "filled", "filled_avg_price": "1.25", "filled_qty": "2"},
    )
    monkeypatch.setattr(flip_bot, "_alert", lambda msg: None)

    flip_bot.run_entry(88_000)

    assert submitted_singles == []
    assert len(submitted_spreads) == 1
    setup, max_notional = submitted_spreads[0]
    assert setup["option_symbol"] == "SPY260626P00735000"
    assert setup["short_option_symbol"] == "SPY260626P00730000"
    assert max_notional == 1760.0
    saved = state_file.read_text(encoding="utf-8")
    assert '"strategy": "bear_trend_spread"' in saved
    assert '"short_option_symbol": "SPY260626P00730000"' in saved


def test_flip_bot_entry_blocks_when_shadow_consensus_says_stand_aside(monkeypatch, tmp_path) -> None:
    from types import SimpleNamespace
    from strategies import flip_bot

    state_file = tmp_path / "flip-trades.json"
    submitted_spreads = []
    alerts = []

    monkeypatch.setattr(flip_bot, "STATE_FILE", state_file)
    monkeypatch.setattr(flip_bot, "_market_open", lambda: True)
    monkeypatch.setattr(flip_bot, "_load", lambda: [])
    monkeypatch.setattr(flip_bot, "log_shadow_0dte_candidates", lambda account: None)
    monkeypatch.setattr(flip_bot, "find_bear_trend_day", lambda account: {
        "strategy": "bear_trend_spread",
        "symbol": "SPY",
        "right": "PUT",
        "option_symbol": "SPY260626P00735000",
        "short_option_symbol": "SPY260626P00730000",
        "strike": 735.0,
        "short_strike": 730.0,
        "expiry": "2026-06-26",
        "contracts": 2,
        "entry_price_est": 1.25,
        "confidence": 9,
        "catalyst": "VWAP/50EMA bear spread",
    })
    monkeypatch.setattr(flip_bot, "find_bull_trend_day", lambda account: None)
    monkeypatch.setattr(flip_bot, "find_0dte", lambda account: None)
    monkeypatch.setattr(flip_bot, "find_earnings", lambda account: [])
    monkeypatch.setattr(flip_bot, "find_breakouts", lambda account: [])
    monkeypatch.setattr(flip_bot, "_fetch_broker_open_symbols", lambda: set())
    monkeypatch.setattr(
        flip_bot,
        "evaluate_execution",
        lambda **kwargs: SimpleNamespace(allowed=True, reason="", details={}),
    )
    monkeypatch.setattr(
        flip_bot,
        "shadow_entry_advice",
        lambda symbol, contracts: {
            "enabled": True,
            "allowed": False,
            "adjusted_contracts": 0,
            "recommendation": "stand_aside",
            "blockers": ["market_force_unclear"],
            "reasons": ["No clean directional edge"],
        },
        raising=False,
    )
    monkeypatch.setattr(
        flip_bot,
        "_submit_spread",
        lambda setup, max_notional: submitted_spreads.append((setup, max_notional)) or {"id": "order"},
    )
    monkeypatch.setattr(flip_bot, "_alert", lambda msg: alerts.append(msg))

    flip_bot.run_entry(88_000)

    assert submitted_spreads == []
    assert alerts
    assert "SHADOW CONSENSUS BLOCKED" in alerts[-1]


def test_flip_scanner_uses_same_risk_and_contract_cap_as_bot(monkeypatch) -> None:
    from strategies import flip_scanner

    monkeypatch.setattr(flip_scanner, "_pre_market_gap", lambda symbol: (0.02, "DOWN"))
    monkeypatch.setattr(flip_scanner, "_atm_0dte_cost", lambda symbol: (0.01, 0.01, 500.0, "2026-06-24"))
    monkeypatch.setattr(flip_scanner, "_last_price", lambda symbol: 500.0)

    result = flip_scanner.check_0dte(5000.0)

    assert flip_scanner.MAX_RISK_PCT == 0.02
    assert flip_scanner.MAX_CONTRACTS == 5
    assert result["contracts_straddle"] == 5
    assert result["contracts_directional"] == 5


def test_flip_shadow_universe_adds_only_recent_qualified_allowlisted_symbols(tmp_path) -> None:
    import json
    from datetime import date
    from strategies import flip_bot

    report_path = tmp_path / "options-liquidity-feasibility.json"
    report_path.write_text(
        json.dumps(
            {
                "date": "2026-07-11",
                "qualified_symbols": ["IWM", "HOOD", "RIVN", "NFLX", "REGN", "SPY"],
            }
        ),
        encoding="utf-8",
    )

    symbols = flip_bot._resolve_shadow_candidate_symbols(report_path, today=date(2026, 7, 12))

    assert symbols == ["SPY", "QQQ", "IWM", "NVDA", "TSLA", "AAPL", "GOOGL", "META", "HOOD", "RIVN", "NFLX"]
    assert "REGN" not in symbols
    assert symbols.count("SPY") == 1


def test_flip_shadow_universe_ignores_stale_liquidity_report(tmp_path) -> None:
    import json
    from datetime import date
    from strategies import flip_bot

    report_path = tmp_path / "options-liquidity-feasibility.json"
    report_path.write_text(
        json.dumps({"date": "2026-07-01", "qualified_symbols": ["HOOD", "RIVN", "NFLX"]}),
        encoding="utf-8",
    )

    assert flip_bot._resolve_shadow_candidate_symbols(report_path, today=date(2026, 7, 12)) == flip_bot.SHADOW_CANDIDATES


def test_flip_bot_finds_bull_trend_day_call_setup(monkeypatch) -> None:
    import pandas as pd
    from datetime import datetime
    from zoneinfo import ZoneInfo
    from strategies import flip_bot

    def bars() -> pd.DataFrame:
        closes = [100 + i * 0.03 for i in range(67)] + [101.60, 101.50, 101.90]
        return pd.DataFrame(
            {
                "Open": [100.0 for _ in closes],
                "High": [c + 0.2 for c in closes],
                "Low": [c - 0.2 for c in closes],
                "Close": closes,
                "Volume": [1000 + i for i in range(len(closes))],
            }
        )

    monkeypatch.setattr(flip_bot, "_now_et", lambda: datetime(2026, 6, 25, 11, 0, tzinfo=ZoneInfo("America/New_York")))
    monkeypatch.setattr(flip_bot, "_intraday_bars", lambda symbol: bars())
    monkeypatch.setattr(
        flip_bot,
        "_orb_breakout_retest_signal",
        lambda symbol: {
            "orb_high": 101.0,
            "orb_low": 100.0,
            "direction": "bull",
            "entry_ready": True,
            "retest_status": "retest_confirmed_fresh",
            "retest_age_bars": 1,
        },
    )
    monkeypatch.setattr(flip_bot, "_atm_option", lambda sym, right: ("SPY260626C00735000", 735.0, 1.20, "2026-06-26"))
    monkeypatch.setattr(flip_bot, "_fetch_vix_term_structure", lambda: {"regime": "contango", "ratio": 1.1})

    setup = flip_bot.find_bull_trend_day(88_000)

    assert setup is not None
    assert setup["strategy"] == "bull_trend"
    assert setup["right"] == "CALL"
    assert setup["contracts"] >= 1
    assert "VWAP/50EMA bull trend" in setup["catalyst"]


def test_flip_bot_does_not_pad_unanimous_eight_score_bull_reclaim(monkeypatch) -> None:
    from datetime import datetime
    from zoneinfo import ZoneInfo
    from strategies import flip_bot

    signal = {
        "score": 8,
        "close": 748.03,
        "vwap": 747.71,
        "ema50": 747.14,
        "vwap_distance": 0.0004,
        "reasons": ["above VWAP", "above 50EMA", "50EMA sloping up", "not extended from VWAP", "pullback held trend"],
    }

    monkeypatch.setattr(flip_bot, "_now_et", lambda: datetime(2026, 7, 7, 11, 15, tzinfo=ZoneInfo("America/New_York")))
    monkeypatch.setattr(flip_bot, "_fetch_vix_term_structure", lambda: {"regime": "contango", "ratio": 1.2})
    monkeypatch.setattr(flip_bot, "_intraday_bars", lambda symbol: object())
    monkeypatch.setattr(flip_bot, "_vwap_50ema_bull_signal", lambda hist, sym="?": dict(signal))
    monkeypatch.setattr(flip_bot, "_ttm_squeeze_context", lambda bars: {"state": "neutral", "first_release": False})
    monkeypatch.setattr(flip_bot, "_atm_option", lambda sym, right: ("SPY260707C00747000", 747.0, 1.30, "2026-07-07"))
    monkeypatch.setattr(flip_bot, "_option_bid_ask_spread_cents", lambda occ: 8)

    setup = flip_bot.find_bull_trend_day(90_000)

    assert setup is None


def test_flip_bot_blocks_weak_same_day_same_direction_reentry(monkeypatch, tmp_path) -> None:
    import json
    from strategies import flip_bot

    state_file = tmp_path / "flip-trades.json"
    state_file.write_text(
        json.dumps(
            [
                {
                    "strategy": "bull_trend",
                    "symbol": "SPY",
                    "right": "CALL",
                    "option_symbol": "SPY260706C00750000",
                    "contracts": 5,
                    "entry_price": 0.78,
                    "target_price": 1.365,
                    "stop_price": 0.39,
                    "entry_date": "2026-07-06",
                    "status": "closed",
                    "exit_reason": "PROFIT PROTECT +17.3% (best +66.0%)",
                    "exit_date": "2026-07-06",
                    "pnl": 67.5,
                }
            ]
        ),
        encoding="utf-8",
    )
    submitted = []
    alerts = []

    class FrozenDate(flip_bot.date):
        @classmethod
        def today(cls):
            return cls(2026, 7, 6)

    monkeypatch.setattr(flip_bot, "STATE_FILE", state_file)
    monkeypatch.setattr(flip_bot, "date", FrozenDate)
    monkeypatch.setattr(flip_bot, "_market_open", lambda: True)
    monkeypatch.setattr(flip_bot, "log_shadow_0dte_candidates", lambda account: [])
    monkeypatch.setattr(flip_bot, "find_bear_trend_day", lambda account: None)
    monkeypatch.setattr(
        flip_bot,
        "find_bull_trend_day",
        lambda account: {
            "strategy": "bull_trend",
            "symbol": "SPY",
            "right": "CALL",
            "option_symbol": "SPY260706C00751000",
            "strike": 751.0,
            "expiry": "2026-07-06",
            "contracts": 5,
            "entry_price_est": 0.78,
            "confidence": 9,
            "hard_close_date": "2026-07-06",
            "hard_close_time": "13:45",
            "catalyst": "VWAP/50EMA bull trend 9/10: pullback held trend | TTM=off",
            "ttm_squeeze": {"first_release": False, "momentum_rising": False},
        },
    )
    monkeypatch.setattr(flip_bot, "find_0dte", lambda account: None)
    monkeypatch.setattr(flip_bot, "find_earnings", lambda account: [])
    monkeypatch.setattr(flip_bot, "find_breakouts", lambda account: [])
    monkeypatch.setattr(flip_bot, "_fetch_broker_open_symbols", lambda: set())
    monkeypatch.setattr(flip_bot, "_submit", lambda *args, **kwargs: submitted.append((args, kwargs)) or {"id": "order"})
    monkeypatch.setattr(flip_bot, "_alert", lambda msg: alerts.append(msg))

    flip_bot.run_entry(88_000)

    assert submitted == []
    assert any("same_day_reentry_blocked" in msg for msg in alerts)


def test_flip_bot_allows_fresh_confirmed_same_day_reentry(monkeypatch, tmp_path) -> None:
    import json
    from strategies import flip_bot

    state_file = tmp_path / "flip-trades.json"
    state_file.write_text(
        json.dumps(
            [
                {
                    "strategy": "bull_trend",
                    "symbol": "SPY",
                    "right": "CALL",
                    "option_symbol": "SPY260706C00750000",
                    "contracts": 5,
                    "entry_price": 0.78,
                    "target_price": 1.365,
                    "stop_price": 0.39,
                    "entry_date": "2026-07-06",
                    "status": "closed",
                    "exit_reason": "PROFIT TARGET +80.0%",
                    "exit_date": "2026-07-06",
                    "pnl": 300.0,
                }
            ]
        ),
        encoding="utf-8",
    )
    submitted = []

    setup = {
        "strategy": "bull_trend",
        "symbol": "SPY",
        "right": "CALL",
        "option_symbol": "SPY260706C00752000",
        "strike": 752.0,
        "expiry": "2026-07-06",
        "contracts": 5,
        "entry_price_est": 0.70,
        "confidence": 10,
        "hard_close_date": "2026-07-06",
        "hard_close_time": "13:45",
        "catalyst": "VWAP/50EMA bull trend 10/10: fresh squeeze release | TTM=off",
        "ttm_squeeze": {"first_release": True, "momentum_rising": True},
    }

    class FrozenDate(flip_bot.date):
        @classmethod
        def today(cls):
            return cls(2026, 7, 6)

    monkeypatch.setattr(flip_bot, "STATE_FILE", state_file)
    monkeypatch.setattr(flip_bot, "MAX_ENTRY_SLIPPAGE_PCT", 3.0)
    monkeypatch.setattr(flip_bot, "date", FrozenDate)
    monkeypatch.setattr(flip_bot, "_market_open", lambda: True)
    monkeypatch.setattr(flip_bot, "log_shadow_0dte_candidates", lambda account: [])
    monkeypatch.setattr(flip_bot, "find_bear_trend_day", lambda account: None)
    monkeypatch.setattr(flip_bot, "find_bull_trend_day", lambda account: setup)
    monkeypatch.setattr(flip_bot, "find_0dte", lambda account: None)
    monkeypatch.setattr(flip_bot, "find_earnings", lambda account: [])
    monkeypatch.setattr(flip_bot, "find_breakouts", lambda account: [])
    monkeypatch.setattr(flip_bot, "_fetch_broker_open_symbols", lambda: set())
    monkeypatch.setattr(
        flip_bot,
        "_selection_quote_fields",
        lambda _occ: {"selection_bid": 0.69, "selection_ask": 0.70, "quote_age_seconds": 0.5},
    )
    monkeypatch.setattr(flip_bot, "evaluate_execution", lambda **kwargs: type("Decision", (), {"allowed": True})())
    def fake_submit(*args, **kwargs):
        submitted.append((args, kwargs))
        if args[2] == "buy":
            return {"id": "entry-order", "status": "accepted"}
        return {"id": "resting-target", "status": "new"}

    monkeypatch.setattr(flip_bot, "_submit", fake_submit)
    monkeypatch.setattr(
        flip_bot,
        "_get",
        lambda path: {
            "id": "entry-order",
            "status": "filled",
            "filled_avg_price": "0.70",
            "filled_qty": "5",
        },
    )
    monkeypatch.setattr(flip_bot.time, "sleep", lambda _seconds: None)
    monkeypatch.setattr(flip_bot, "_alert", lambda msg: None)

    flip_bot.run_entry(88_000)

    assert submitted == [
        (("SPY260706C00752000", 5, "buy"), {"max_notional": 1760.0, "limit_price": 0.72}),
        (("SPY260706C00752000", 5, "sell"), {"limit_price": 1.23}),
    ]
    saved = json.loads(state_file.read_text(encoding="utf-8"))
    assert len(saved) == 2
    assert saved[1]["option_symbol"] == "SPY260706C00752000"
    assert saved[1]["resting_tp_order_id"] == "resting-target"


def test_flip_bot_cancels_unfilled_entry_without_tracking_trade(monkeypatch, tmp_path) -> None:
    import json
    from strategies import flip_bot

    state_file = tmp_path / "flip-trades.json"
    state_file.write_text("[]", encoding="utf-8")
    events = []
    order_states = iter([
        {"id": "entry-order", "status": "accepted", "filled_qty": "0"},
        {"id": "entry-order", "status": "canceled", "filled_qty": "0"},
    ])

    setup = {
        "strategy": "bull_trend",
        "symbol": "SPY",
        "right": "CALL",
        "option_symbol": "SPY260706C00752000",
        "strike": 752.0,
        "expiry": "2026-07-06",
        "contracts": 5,
        "entry_price_est": 0.70,
        "confidence": 10,
        "hard_close_date": "2026-07-06",
        "hard_close_time": "13:45",
        "catalyst": "VWAP/50EMA bull trend 10/10",
        "ttm_squeeze": {},
    }

    monkeypatch.setattr(flip_bot, "STATE_FILE", state_file)
    monkeypatch.setattr(flip_bot, "_market_open", lambda: True)
    monkeypatch.setattr(flip_bot, "log_shadow_0dte_candidates", lambda account: [])
    monkeypatch.setattr(flip_bot, "find_bear_trend_day", lambda account: None)
    monkeypatch.setattr(flip_bot, "find_bull_trend_day", lambda account: setup)
    monkeypatch.setattr(flip_bot, "find_0dte", lambda account: None)
    monkeypatch.setattr(flip_bot, "find_earnings", lambda account: [])
    monkeypatch.setattr(flip_bot, "find_breakouts", lambda account: [])
    monkeypatch.setattr(flip_bot, "_fetch_broker_open_symbols", lambda: set())
    monkeypatch.setattr(
        flip_bot,
        "_selection_quote_fields",
        lambda _occ: {"selection_bid": 0.69, "selection_ask": 0.70, "quote_age_seconds": 0.5},
    )
    monkeypatch.setattr(flip_bot, "evaluate_execution", lambda **kwargs: type("Decision", (), {"allowed": True})())
    monkeypatch.setattr(
        flip_bot,
        "_submit",
        lambda *args, **kwargs: events.append(("submit", args[2])) or {"id": "entry-order", "status": "accepted"},
    )
    monkeypatch.setattr(flip_bot, "_get", lambda path: events.append(("get", path)) or next(order_states))
    monkeypatch.setattr(flip_bot, "_delete", lambda path: events.append(("cancel", path)))
    monkeypatch.setattr(flip_bot.time, "sleep", lambda _seconds: None)
    monkeypatch.setattr(flip_bot, "_alert", lambda msg: None)

    flip_bot.run_entry(88_000)

    assert events == [
        ("submit", "buy"),
        ("get", "/v2/orders/entry-order"),
        ("cancel", "/v2/orders/entry-order"),
        ("get", "/v2/orders/entry-order"),
    ]
    assert json.loads(state_file.read_text(encoding="utf-8")) == []


def test_flip_bot_tracks_only_broker_confirmed_partial_entry_quantity(monkeypatch, tmp_path) -> None:
    import json
    from strategies import flip_bot

    state_file = tmp_path / "flip-trades.json"
    state_file.write_text("[]", encoding="utf-8")
    submitted = []
    order_states = iter([
        {"id": "entry-order", "status": "partially_filled", "filled_qty": "2", "filled_avg_price": "0.71"},
        {"id": "entry-order", "status": "canceled", "filled_qty": "2", "filled_avg_price": "0.71"},
    ])

    setup = {
        "strategy": "bull_trend",
        "symbol": "SPY",
        "right": "CALL",
        "option_symbol": "SPY260706C00752000",
        "strike": 752.0,
        "expiry": "2026-07-06",
        "contracts": 5,
        "entry_price_est": 0.70,
        "confidence": 10,
        "hard_close_date": "2026-07-06",
        "hard_close_time": "13:45",
        "catalyst": "VWAP/50EMA bull trend 10/10",
        "ttm_squeeze": {},
    }

    def fake_submit(*args, **kwargs):
        submitted.append((args, kwargs))
        if args[2] == "buy":
            return {"id": "entry-order", "status": "accepted"}
        return {"id": "resting-target", "status": "new"}

    monkeypatch.setattr(flip_bot, "STATE_FILE", state_file)
    monkeypatch.setattr(flip_bot, "MAX_ENTRY_SLIPPAGE_PCT", 3.0)
    monkeypatch.setattr(flip_bot, "_market_open", lambda: True)
    monkeypatch.setattr(flip_bot, "log_shadow_0dte_candidates", lambda account: [])
    monkeypatch.setattr(flip_bot, "find_bear_trend_day", lambda account: None)
    monkeypatch.setattr(flip_bot, "find_bull_trend_day", lambda account: setup)
    monkeypatch.setattr(flip_bot, "find_0dte", lambda account: None)
    monkeypatch.setattr(flip_bot, "find_earnings", lambda account: [])
    monkeypatch.setattr(flip_bot, "find_breakouts", lambda account: [])
    monkeypatch.setattr(flip_bot, "_fetch_broker_open_symbols", lambda: set())
    monkeypatch.setattr(
        flip_bot,
        "_selection_quote_fields",
        lambda _occ: {"selection_bid": 0.69, "selection_ask": 0.70, "quote_age_seconds": 0.5},
    )
    monkeypatch.setattr(flip_bot, "evaluate_execution", lambda **kwargs: type("Decision", (), {"allowed": True})())
    monkeypatch.setattr(flip_bot, "_submit", fake_submit)
    monkeypatch.setattr(flip_bot, "_get", lambda path: next(order_states))
    monkeypatch.setattr(flip_bot, "_delete", lambda path: None)
    monkeypatch.setattr(flip_bot.time, "sleep", lambda _seconds: None)
    monkeypatch.setattr(flip_bot, "_alert", lambda msg: None)

    flip_bot.run_entry(88_000)

    assert submitted == [
        (("SPY260706C00752000", 5, "buy"), {"max_notional": 1760.0, "limit_price": 0.72}),
        (("SPY260706C00752000", 2, "sell"), {"limit_price": 1.24}),
    ]
    saved = json.loads(state_file.read_text(encoding="utf-8"))
    assert len(saved) == 1
    assert saved[0]["contracts"] == 2
    assert saved[0]["requested_contracts"] == 5
    assert saved[0]["entry_partial_fill"] is True
    assert saved[0]["entry_price"] == 0.71
    assert saved[0]["resting_tp_order_id"] == "resting-target"


def test_vix_term_structure_blocks_bull_in_backwardation_but_allows_bear() -> None:
    from strategies import flip_bot

    backwardation = flip_bot._vix_term_structure_regime(24.0, 20.0)
    contango = flip_bot._vix_term_structure_regime(18.0, 22.0)

    assert backwardation["regime"] == "backwardation"
    assert flip_bot._vix_term_structure_direction_ok("bull", backwardation) is False
    assert flip_bot._vix_term_structure_direction_ok("bear", backwardation) is True
    assert contango["regime"] == "contango"
    assert flip_bot._vix_term_structure_direction_ok("bull", contango) is True


def test_fetch_vix_term_structure_uses_cboe_context(monkeypatch) -> None:
    from strategies import flip_bot

    monkeypatch.setattr(
        flip_bot,
        "fetch_vix_term_structure_context",
        lambda: {
            "source": "cboe_vix_vix3m_history",
            "date": "2026-06-26",
            "vix": 18.0,
            "vix3m": 22.0,
            "vix3m_over_vix": 1.2222,
            "regime": "contango",
        },
    )

    regime = flip_bot._fetch_vix_term_structure()

    assert regime["source"] == "cboe_vix_vix3m_history"
    assert regime["regime"] == "contango"
    assert regime["ratio"] == 1.2222


def test_flip_bot_monitor_closes_both_spread_legs(monkeypatch, tmp_path) -> None:
    import json
    from strategies import flip_bot

    state_file = tmp_path / "flip-trades.json"
    state_file.write_text(
        json.dumps(
            [
                {
                    "strategy": "bear_trend_spread",
                    "symbol": "SPY",
                    "option_symbol": "SPY260626P00735000",
                    "short_option_symbol": "SPY260626P00730000",
                    "contracts": 2,
                    "entry_price": 1.25,
                    "target_price": 2.188,
                    "stop_price": 0.625,
                    "hard_close_date": "2026-06-25",
                    "hard_close_time": "13:45",
                    "entry_date": "2026-06-25",
                    "status": "open",
                }
            ]
        ),
        encoding="utf-8",
    )
    closed_spreads = []
    single_closes = []

    monkeypatch.setattr(flip_bot, "STATE_FILE", state_file)
    monkeypatch.setattr(flip_bot, "_market_open", lambda: True)
    monkeypatch.setattr(flip_bot, "_spread_mid", lambda long_symbol, short_symbol: 0.50)
    monkeypatch.setattr(flip_bot, "_submit", lambda *args, **kwargs: single_closes.append((args, kwargs)) or {"id": "single"})
    monkeypatch.setattr(
        flip_bot,
        "_close_spread",
        lambda trade: closed_spreads.append((trade["option_symbol"], trade["short_option_symbol"]))
        or {"id": "close-spread", "status": "filled", "filled_avg_price": "0.50"},
    )
    monkeypatch.setattr(flip_bot, "_alert", lambda msg: None)

    flip_bot.run_monitor()

    assert single_closes == []
    assert closed_spreads == [("SPY260626P00735000", "SPY260626P00730000")]
    saved = json.loads(state_file.read_text(encoding="utf-8"))
    assert saved[0]["status"] == "closed"
    assert saved[0]["exit_reason"].startswith("STOP LOSS")


def test_flip_bot_monitor_profit_protects_fading_winner(monkeypatch, tmp_path) -> None:
    import json
    from strategies import flip_bot

    state_file = tmp_path / "flip-trades.json"
    state_file.write_text(
        json.dumps(
            [
                {
                    "strategy": "bull_trend",
                    "symbol": "SPY",
                    "option_symbol": "SPY260701C00748000",
                    "contracts": 5,
                    "entry_price": 1.00,
                    "target_price": 1.75,
                    "stop_price": 0.50,
                    "entry_date": "2026-07-01",
                    "status": "open",
                    "best_pnl_pct": 55.0,
                }
            ]
        ),
        encoding="utf-8",
    )
    submitted = []

    monkeypatch.setattr(flip_bot, "STATE_FILE", state_file)
    monkeypatch.setattr(flip_bot, "_market_open", lambda: True)
    monkeypatch.setattr(flip_bot, "_option_mid", lambda symbol: 1.29)
    monkeypatch.setattr(
        flip_bot,
        "_submit",
        lambda *args, **kwargs: submitted.append((args, kwargs))
        or {"id": "close", "status": "filled", "filled_avg_price": "1.29"},
    )
    monkeypatch.setattr(flip_bot, "_alert", lambda msg: None)
    monkeypatch.setattr(flip_bot, "ACCELERATED_SHADOW_LEARNING", True)
    monkeypatch.setattr(
        flip_bot,
        "log_shadow_0dte_candidates",
        lambda account: (_ for _ in ()).throw(RuntimeError("research feed unavailable")),
    )

    flip_bot.run_monitor()

    assert submitted == [(("SPY260701C00748000", 5, "sell"), {})]
    saved = json.loads(state_file.read_text(encoding="utf-8"))
    assert saved[0]["status"] == "closed"
    assert saved[0]["exit_reason"].startswith("PROFIT PROTECT")
    assert saved[0]["pnl"] == 145.0
    assert saved[0]["exit_order_id"] == "close"


def test_flip_bot_exits_armed_winner_even_after_it_slips_negative(monkeypatch, tmp_path) -> None:
    import json
    from strategies import flip_bot

    state_file = tmp_path / "flip-trades.json"
    state_file.write_text(
        json.dumps([
            {
                "strategy": "bull_trend",
                "symbol": "SPY",
                "right": "CALL",
                "option_symbol": "SPY260710C00750000",
                "contracts": 1,
                "entry_price": 1.00,
                "target_price": 1.75,
                "stop_price": 0.50,
                "entry_date": "2026-07-10",
                "status": "open",
                "best_pnl_pct": 55.0,
            }
        ]),
        encoding="utf-8",
    )
    submitted = []
    monkeypatch.setattr(flip_bot, "STATE_FILE", state_file)
    monkeypatch.setattr(flip_bot, "_market_open", lambda: True)
    monkeypatch.setattr(flip_bot, "_option_mid", lambda symbol: 0.95)
    monkeypatch.setattr(
        flip_bot,
        "_submit",
        lambda *args, **kwargs: submitted.append((args, kwargs))
        or {"id": "close", "status": "filled", "filled_avg_price": "0.95"},
    )
    monkeypatch.setattr(flip_bot, "_alert", lambda msg: None)

    flip_bot.run_monitor()

    saved = json.loads(state_file.read_text(encoding="utf-8"))
    assert submitted == [(("SPY260710C00750000", 1, "sell"), {})]
    assert saved[0]["status"] == "closed"
    assert saved[0]["exit_reason"].startswith("PROFIT PROTECT -5.0%")


def test_flip_bot_monitor_defensively_exits_on_shadow_direction_flip(monkeypatch, tmp_path) -> None:
    import json
    from strategies import flip_bot

    state_file = tmp_path / "flip-trades.json"
    state_file.write_text(
        json.dumps(
            [
                {
                    "strategy": "bull_trend",
                    "symbol": "SPY",
                    "right": "CALL",
                    "option_symbol": "SPY260707C00750000",
                    "contracts": 5,
                    "entry_price": 1.00,
                    "target_price": 1.75,
                    "stop_price": 0.50,
                    "entry_date": "2026-07-07",
                    "status": "open",
                }
            ]
        ),
        encoding="utf-8",
    )
    submitted = []

    monkeypatch.setattr(flip_bot, "STATE_FILE", state_file)
    monkeypatch.setattr(flip_bot, "_market_open", lambda: True)
    monkeypatch.setattr(flip_bot, "_option_mid", lambda symbol: 0.98)
    monkeypatch.setattr(
        flip_bot,
        "_submit",
        lambda *args, **kwargs: submitted.append((args, kwargs))
        or {"id": "close", "status": "filled", "filled_avg_price": "0.98"},
    )
    monkeypatch.setattr(flip_bot, "_alert", lambda msg: None)
    monkeypatch.setattr(
        flip_bot,
        "shadow_exit_advice",
        lambda symbol, right: {
            "enabled": True,
            "action": "review_exit",
            "recommendation": "stand_aside",
            "options_playbook": "directional_long_put",
            "blockers": ["shadow_direction_flip"],
            "reasons": ["Shadow playbook flipped bearish."],
        },
    )

    flip_bot.run_monitor()

    assert submitted == [(("SPY260707C00750000", 5, "sell"), {})]
    saved = json.loads(state_file.read_text(encoding="utf-8"))
    assert saved[0]["status"] == "closed"
    assert saved[0]["exit_reason"].startswith("SHADOW DEFENSIVE EXIT")



def test_flip_bot_monitor_ratchets_profit_protection_for_0dte_winner(monkeypatch, tmp_path) -> None:
    import json
    from strategies import flip_bot

    state_file = tmp_path / "flip-trades.json"
    state_file.write_text(
        json.dumps(
            [
                {
                    "strategy": "bull_trend",
                    "symbol": "SPY",
                    "option_symbol": "SPY260706C00750000",
                    "contracts": 5,
                    "entry_price": 1.00,
                    "target_price": 1.75,
                    "stop_price": 0.50,
                    "entry_date": "2026-07-06",
                    "status": "open",
                    "best_pnl_pct": 66.0,
                }
            ]
        ),
        encoding="utf-8",
    )
    submitted = []

    monkeypatch.setattr(flip_bot, "STATE_FILE", state_file)
    monkeypatch.setattr(flip_bot, "_market_open", lambda: True)
    monkeypatch.setattr(flip_bot, "_option_mid", lambda symbol: 1.50)
    monkeypatch.setattr(
        flip_bot,
        "_submit",
        lambda *args, **kwargs: submitted.append((args, kwargs))
        or {"id": "close", "status": "filled", "filled_avg_price": "1.50"},
    )
    monkeypatch.setattr(flip_bot, "_alert", lambda msg: None)

    flip_bot.run_monitor()

    assert submitted == [(("SPY260706C00750000", 5, "sell"), {})]
    saved = json.loads(state_file.read_text(encoding="utf-8"))
    assert saved[0]["status"] == "closed"
    assert saved[0]["exit_reason"] == "PROFIT PROTECT +50.0% (best +66.0%, lock +51.0%)"
    assert saved[0]["pnl"] == 250.0


def test_flip_bot_monitor_does_not_date_exit_before_same_day_cutoff(monkeypatch, tmp_path) -> None:
    import json
    from datetime import datetime
    from strategies import flip_bot

    state_file = tmp_path / "flip-trades.json"
    state_file.write_text(
        json.dumps(
            [
                {
                    "strategy": "bear_trend",
                    "symbol": "SPY",
                    "option_symbol": "SPY260707P00746000",
                    "contracts": 5,
                    "entry_price": 1.54,
                    "target_price": 2.695,
                    "stop_price": 0.77,
                    "hard_close_date": "2026-07-07",
                    "hard_close_time": "13:45",
                    "entry_date": "2026-07-07",
                    "status": "open",
                }
            ]
        ),
        encoding="utf-8",
    )
    submitted = []

    class FrozenDate(flip_bot.date):
        @classmethod
        def today(cls):
            return cls(2026, 7, 7)

    class FrozenDateTime(datetime):
        @classmethod
        def now(cls, tz=None):
            return cls(2026, 7, 7, 9, 50)

    monkeypatch.setattr(flip_bot, "STATE_FILE", state_file)
    monkeypatch.setattr(flip_bot, "date", FrozenDate)
    monkeypatch.setattr(flip_bot, "datetime", FrozenDateTime)
    monkeypatch.setattr(flip_bot, "_market_open", lambda: True)
    monkeypatch.setattr(flip_bot, "_option_mid", lambda symbol: 1.255)
    monkeypatch.setattr(
        flip_bot,
        "_submit",
        lambda *args, **kwargs: submitted.append((args, kwargs))
        or {"id": "close", "status": "filled", "filled_avg_price": "1.00"},
    )
    monkeypatch.setattr(flip_bot, "_alert", lambda msg: None)

    flip_bot.run_monitor()

    assert submitted == []
    saved = json.loads(state_file.read_text(encoding="utf-8"))
    assert saved[0]["status"] == "open"


def test_flip_bot_monitor_uses_eastern_time_for_intraday_cutoff(monkeypatch, tmp_path) -> None:
    import json
    from datetime import datetime
    from zoneinfo import ZoneInfo
    from strategies import flip_bot

    state_file = tmp_path / "flip-trades.json"
    state_file.write_text(
        json.dumps([{
            "strategy": "bull_trend",
            "symbol": "SPY",
            "right": "CALL",
            "option_symbol": "SPY260714C00750000",
            "contracts": 1,
            "entry_price": 1.0,
            "target_price": 1.75,
            "stop_price": 0.70,
            "hard_close_date": "2026-07-14",
            "hard_close_time": "13:45",
            "entry_date": "2026-07-14",
            "status": "open",
        }]),
        encoding="utf-8",
    )
    submitted = []
    monkeypatch.setattr(flip_bot, "STATE_FILE", state_file)
    monkeypatch.setattr(flip_bot, "_market_open", lambda: True)
    monkeypatch.setattr(
        flip_bot,
        "_now_et",
        lambda: datetime(2026, 7, 14, 13, 45, tzinfo=ZoneInfo("America/New_York")),
    )
    monkeypatch.setattr(flip_bot, "_option_mid", lambda symbol: 1.0)
    monkeypatch.setattr(
        flip_bot,
        "_submit",
        lambda *args, **kwargs: submitted.append((args, kwargs))
        or {"id": "close", "status": "filled", "filled_avg_price": "1.00"},
    )
    monkeypatch.setattr(flip_bot, "_alert", lambda msg: None)
    monkeypatch.setattr(flip_bot, "_capture_point_in_time", lambda *args, **kwargs: [])
    monkeypatch.setattr(flip_bot, "shadow_exit_advice", lambda *args, **kwargs: {"enabled": False})

    flip_bot.run_monitor()

    assert submitted == [(("SPY260714C00750000", 1, "sell"), {})]
    saved = json.loads(state_file.read_text(encoding="utf-8"))
    assert saved[0]["status"] == "closed"
    assert saved[0]["exit_reason"] == "TIME EXIT 13:45"

def test_flip_bot_logs_shadow_0dte_candidates_without_execution(monkeypatch, tmp_path) -> None:
    import json
    from datetime import datetime
    from zoneinfo import ZoneInfo
    from strategies import flip_bot

    assert "SPY" in flip_bot.SHADOW_CANDIDATES
    assert "IWM" in flip_bot.SHADOW_CANDIDATES

    log_path = tmp_path / "flip_shadow_candidates_log.jsonl"
    monkeypatch.setattr(flip_bot, "SHADOW_CANDIDATE_LOG_PATH", log_path)
    monkeypatch.setattr(flip_bot, "SHADOW_CANDIDATES", ["QQQ", "IWM", "NVDA"])
    monkeypatch.setattr(flip_bot, "_spot", lambda symbol: 105.0)
    monkeypatch.setattr(flip_bot, "_prev_close", lambda symbol: 100.0)
    monkeypatch.setattr(flip_bot, "_orb_breakout_retest_signal", lambda symbol: None)
    monkeypatch.setattr(
        flip_bot,
        "_now_et",
        lambda: datetime(2026, 7, 2, 11, 0, tzinfo=ZoneInfo("America/New_York")),
    )
    monkeypatch.setattr(
        flip_bot,
        "_atm_option",
        lambda sym, right: (f"{sym}260702C00105000", 105.0, 1.25, "2026-07-02"),
    )
    monkeypatch.setattr(flip_bot, "_option_bid_ask_spread_cents", lambda occ: 4)

    entries = flip_bot.log_shadow_0dte_candidates(10_000, symbols=flip_bot.SHADOW_CANDIDATES)

    assert len(entries) == 3
    assert all(entry["execution_mode"] == "shadow_only" for entry in entries)
    assert all(entry["live_execution_allowed"] is False for entry in entries)
    rows = [json.loads(line) for line in log_path.read_text(encoding="utf-8").splitlines()]
    assert [row["symbol"] for row in rows] == ["QQQ", "IWM", "NVDA"]
    assert rows[0]["option_symbol"] == "QQQ260702C00105000"
    assert rows[1]["option_symbol"] == "IWM260702C00105000"
    assert all(row["schema_version"] == 3 for row in rows)
    assert all(row["lifecycle_id"] for row in rows)
    assert all(row["episode_horizon_minutes"] == 60 for row in rows)
    assert all(row["learner_tracks"] == [
        "flip_entry_exit", "options_directional_contract_selection",
    ] for row in rows)
    assert all(row["action"] == "enter_shadow" for row in rows)


def test_spy_accelerated_shadow_logs_without_live_consensus_gate(monkeypatch, tmp_path) -> None:
    import json
    from datetime import datetime
    from zoneinfo import ZoneInfo
    from strategies import flip_bot

    log_path = tmp_path / "flip_shadow_candidates_log.jsonl"
    monkeypatch.setattr(flip_bot, "SHADOW_CANDIDATE_LOG_PATH", log_path)
    monkeypatch.setattr(flip_bot, "_spot", lambda symbol: 505.0)
    monkeypatch.setattr(flip_bot, "_prev_close", lambda symbol: 500.0)
    monkeypatch.setattr(
        flip_bot,
        "_orb_breakout_retest_signal",
        lambda symbol: {"direction": "bull", "range_pct": 0.8, "orb_high": 504.0, "orb_low": 500.0, "close": 505.0},
    )
    monkeypatch.setattr(
        flip_bot,
        "_now_et",
        lambda: datetime(2026, 7, 15, 10, 0, tzinfo=ZoneInfo("America/New_York")),
    )
    monkeypatch.setattr(
        flip_bot,
        "_atm_option",
        lambda sym, right: ("SPY260715C00505000", 505.0, 1.25, "2026-07-15"),
    )
    monkeypatch.setattr(flip_bot, "_option_bid_ask_spread_cents", lambda occ: 3)
    monkeypatch.setattr(flip_bot, "_selection_quote_fields", lambda occ: {})
    monkeypatch.setattr(
        flip_bot,
        "shadow_entry_advice",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("live gate must not run for shadow logging")),
    )

    entries = flip_bot.log_shadow_0dte_candidates(10_000, symbols=["SPY"])

    assert len(entries) == 1
    assert entries[0]["symbol"] == "SPY"
    assert entries[0]["execution_mode"] == "shadow_only"
    assert entries[0]["live_execution_allowed"] is False
    rows = [json.loads(line) for line in log_path.read_text(encoding="utf-8").splitlines()]
    assert rows[0]["lifecycle_id"].endswith("|SPY|CALL|0dte|10:00")


def test_shadow_reversal_challenger_is_not_starved_by_generic_episodes(monkeypatch, tmp_path) -> None:
    import json
    from datetime import datetime
    from zoneinfo import ZoneInfo
    from strategies import flip_bot

    assert flip_bot.SHADOW_MAX_ACTIVE_PER_SYMBOL >= 4
    log_path = tmp_path / "flip_shadow_candidates_log.jsonl"
    active = []
    for index in range(3):
        active.append({
            "lifecycle_id": f"2026-07-17|SPY|CALL|0dte|{index}",
            "date": "2026-07-17",
            "schema_version": flip_bot.SHADOW_CANDIDATE_SCHEMA_VERSION,
            "event_type": "shadow_entry",
            "symbol": "SPY",
            "strategy": "0dte",
            "right": "CALL",
            "option_symbol": f"SPY260717C0074{index}000",
            "entry_price_est": 1.0,
            "episode_expires_at": "2026-07-17T18:30:00Z",
        })
    log_path.write_text("\n".join(json.dumps(row) for row in active) + "\n", encoding="utf-8")

    monkeypatch.setattr(flip_bot, "SHADOW_CANDIDATE_LOG_PATH", log_path)
    monkeypatch.setattr(
        flip_bot,
        "_now_et",
        lambda: datetime(2026, 7, 17, 12, 55, tzinfo=ZoneInfo("America/New_York")),
    )
    monkeypatch.setattr(flip_bot, "_option_mid", lambda _symbol: 1.0)
    monkeypatch.setattr(flip_bot, "_option_bid_ask_spread_cents", lambda _symbol: 2)
    monkeypatch.setattr(flip_bot, "_selection_quote_fields", lambda _symbol: {})
    monkeypatch.setattr(flip_bot, "_market_force_shadow_snapshot", lambda *_args, **_kwargs: {})
    monkeypatch.setattr(
        flip_bot,
        "_find_0dte_for_symbol",
        lambda *_args, **_kwargs: {
            "symbol": "SPY",
            "strategy": "0dte",
            "right": "CALL",
            "option_symbol": "SPY260717C00747000",
            "entry_price_est": 1.0,
        },
    )
    monkeypatch.setattr(
        flip_bot,
        "_shadow_setup_challenger_candidates",
        lambda *_args, **_kwargs: [{
            "symbol": "SPY",
            "strategy": "orb_extension_reversal",
            "right": "PUT",
            "option_symbol": "SPY260717P00745000",
            "entry_price_est": 0.5,
            "live_execution_allowed": False,
            "execution_enabled": False,
            "can_submit_orders": False,
        }],
    )

    observations = flip_bot.log_shadow_0dte_candidates(10_000, symbols=["SPY"])

    new_entries = [row for row in observations if row.get("event_type") == "shadow_entry"]
    assert [row["strategy"] for row in new_entries] == ["orb_extension_reversal"]
    assert new_entries[0]["can_submit_orders"] is False


def test_flip_shadow_candidates_track_lifecycle_after_entry(monkeypatch, tmp_path) -> None:
    import json
    from datetime import datetime
    from zoneinfo import ZoneInfo
    from strategies import flip_bot

    log_path = tmp_path / "flip_shadow_candidates_log.jsonl"
    monkeypatch.setattr(flip_bot, "SHADOW_CANDIDATE_LOG_PATH", log_path)
    monkeypatch.setattr(flip_bot, "SHADOW_CANDIDATES", ["QQQ"])
    monkeypatch.setattr(flip_bot, "_spot", lambda symbol: 105.0)
    monkeypatch.setattr(flip_bot, "_prev_close", lambda symbol: 100.0)
    monkeypatch.setattr(flip_bot, "_orb_breakout_retest_signal", lambda symbol: None)
    monkeypatch.setattr(
        flip_bot,
        "_atm_option",
        lambda sym, right: ("QQQ260710C00105000", 105.0, 1.00, "2026-07-10"),
    )
    monkeypatch.setattr(flip_bot, "_option_bid_ask_spread_cents", lambda occ: 2)
    monkeypatch.setattr(flip_bot, "_option_mid", lambda occ: 1.40)
    monkeypatch.setattr(
        flip_bot,
        "_now_et",
        lambda: datetime(2026, 7, 10, 11, 0, tzinfo=ZoneInfo("America/New_York")),
    )

    first = flip_bot.log_shadow_0dte_candidates(10_000, symbols=flip_bot.SHADOW_CANDIDATES)
    second = flip_bot.log_shadow_0dte_candidates(10_000, symbols=flip_bot.SHADOW_CANDIDATES)

    assert [row["event_type"] for row in first] == ["shadow_entry"]
    assert [row["event_type"] for row in second] == ["shadow_mark"]
    rows = [json.loads(line) for line in log_path.read_text(encoding="utf-8").splitlines()]
    assert [row["action"] for row in rows] == ["enter_shadow", "hold_shadow"]
    assert rows[1]["option_symbol"] == rows[0]["option_symbol"]
    assert rows[1]["entry_price_est"] == 1.40


def test_flip_shadow_episode_closes_at_fixed_horizon(monkeypatch, tmp_path) -> None:
    import json
    from datetime import datetime
    from zoneinfo import ZoneInfo
    from strategies import flip_bot

    log_path = tmp_path / "flip_shadow_candidates_log.jsonl"
    clock = {"now": datetime(2026, 7, 10, 11, 0, tzinfo=ZoneInfo("America/New_York"))}
    monkeypatch.setattr(flip_bot, "SHADOW_CANDIDATE_LOG_PATH", log_path)
    monkeypatch.setattr(flip_bot, "SHADOW_CANDIDATES", ["QQQ"])
    monkeypatch.setattr(flip_bot, "_now_et", lambda: clock["now"])
    monkeypatch.setattr(flip_bot, "_spot", lambda symbol: 105.0)
    monkeypatch.setattr(flip_bot, "_prev_close", lambda symbol: 100.0)
    monkeypatch.setattr(flip_bot, "_orb_breakout_retest_signal", lambda symbol: None)
    monkeypatch.setattr(
        flip_bot,
        "_atm_option",
        lambda sym, right: ("QQQ260710C00105000", 105.0, 1.00, "2026-07-10"),
    )
    monkeypatch.setattr(flip_bot, "_option_bid_ask_spread_cents", lambda occ: 2)
    monkeypatch.setattr(flip_bot, "_selection_quote_fields", lambda occ: {})
    monkeypatch.setattr(flip_bot, "_option_mid", lambda occ: 1.10)

    flip_bot.log_shadow_0dte_candidates(10_000, symbols=["QQQ"])
    clock["now"] = datetime(2026, 7, 10, 12, 1, tzinfo=ZoneInfo("America/New_York"))
    observations = flip_bot.log_shadow_0dte_candidates(10_000, symbols=[])

    assert observations[0]["event_type"] == "shadow_exit"
    assert observations[0]["mark_reason"] == "episode_horizon"
    rows = [json.loads(line) for line in log_path.read_text(encoding="utf-8").splitlines()]
    assert rows[0]["lifecycle_id"] == rows[1]["lifecycle_id"]


def test_flip_shadow_keeps_observing_after_target_for_runner_research(monkeypatch) -> None:
    from datetime import datetime
    from zoneinfo import ZoneInfo
    from strategies import flip_bot

    monkeypatch.setattr(flip_bot, "SHADOW_CONTINUE_AFTER_TARGET", True)
    now = datetime(2026, 7, 10, 11, 15, tzinfo=ZoneInfo("America/New_York"))
    rows = [{
        "entry_price_est": 1.0,
        "episode_expires_at": "2026-07-10T16:00:00Z",
        "hard_close_time": "13:45",
    }]

    reason, current, best = flip_bot._shadow_exit_reason(rows, 1.80, now)

    assert reason == ""
    assert current == 80.0
    assert best == 80.0


def test_flip_shadow_runner_closes_on_post_target_ratchet(monkeypatch) -> None:
    from datetime import datetime
    from zoneinfo import ZoneInfo
    from strategies import flip_bot

    monkeypatch.setattr(flip_bot, "SHADOW_CONTINUE_AFTER_TARGET", True)
    now = datetime(2026, 7, 10, 11, 20, tzinfo=ZoneInfo("America/New_York"))
    rows = [
        {"entry_price_est": 1.0, "episode_expires_at": "2026-07-10T16:00:00Z", "hard_close_time": "13:45"},
        {"entry_price_est": 1.80, "return_pct_at_mark": 80.0},
    ]

    reason, current, best = flip_bot._shadow_exit_reason(rows, 1.60, now)

    assert reason == "ratchet_lock_65.0"
    assert round(current, 2) == 60.0
    assert best == 80.0


def test_intraday_bars_reject_previous_session(monkeypatch) -> None:
    import pandas as pd
    from strategies import flip_bot

    stale = pd.DataFrame(
        {"Close": [100.0, 101.0]},
        index=pd.date_range("2026-07-09 09:30", periods=2, freq="1min", tz="America/New_York"),
    )

    class FakeTicker:
        def history(self, **kwargs):
            return stale

    monkeypatch.setattr(flip_bot.yf, "Ticker", lambda symbol: FakeTicker())

    assert flip_bot._intraday_bars("SPY") is None


def test_day_type_snapshot_waits_until_1000_without_fetching(monkeypatch) -> None:
    from datetime import datetime

    from strategies import flip_bot

    monkeypatch.setattr(
        flip_bot,
        "_intraday_bars",
        lambda _symbol: (_ for _ in ()).throw(AssertionError("unexpected fetch")),
    )

    result = flip_bot._day_type_snapshot(
        "SPY", now_et=datetime(2026, 7, 17, 9, 55)
    )

    assert result["day_type"] == "unknown"
    assert result["signals_supporting"] == ["waiting_for_10_et"]
    assert result["can_submit_orders"] is False


def test_underlying_mark_requires_complete_structural_fields(monkeypatch) -> None:
    import pandas as pd

    from strategies import flip_bot

    bars = pd.DataFrame(
        {"High": [101.0], "Low": [99.0], "Close": [100.0]},
        index=pd.DatetimeIndex(["2026-07-17 10:00:00"]),
    )
    monkeypatch.setattr(flip_bot, "_intraday_bars", lambda _symbol: bars)
    monkeypatch.setattr(
        flip_bot,
        "_completed_intraday_bars",
        lambda frame, now_et=None: frame,
    )

    result = flip_bot._underlying_mark_snapshot("SPY")

    assert result["underlying_mark_status"] == "incomplete_forward"
    assert result["underlying_close"] == 100.0


def test_atm_option_prefers_live_mid_over_stale_last_trade(monkeypatch) -> None:
    import pandas as pd
    from types import SimpleNamespace
    from strategies import flip_bot

    chain = SimpleNamespace(
        calls=pd.DataFrame([{"strike": 750.0, "lastPrice": 0.40}]),
        puts=pd.DataFrame([{"strike": 750.0, "lastPrice": 0.45}]),
    )

    class FakeTicker:
        options = [str(flip_bot.date.today())]

        def option_chain(self, expiry):
            return chain

    monkeypatch.setattr(flip_bot.yf, "Ticker", lambda symbol: FakeTicker())
    monkeypatch.setattr(flip_bot, "_spot", lambda symbol: 750.0)
    monkeypatch.setattr(flip_bot, "_option_mid", lambda symbol: 1.25)

    _occ, _strike, price, _expiry = flip_bot._atm_option("SPY", "CALL")

    assert price == 1.25


def test_shadow_contract_challengers_capture_atm_and_two_otm_without_execution(monkeypatch) -> None:
    import pandas as pd
    from types import SimpleNamespace
    from strategies import flip_bot

    chain = SimpleNamespace(
        calls=pd.DataFrame([{"strike": 320.0}, {"strike": 322.5}, {"strike": 325.0}, {"strike": 327.5}]),
        puts=pd.DataFrame([{"strike": 315.0}, {"strike": 317.5}, {"strike": 320.0}]),
    )

    class FakeTicker:
        def option_chain(self, expiry):
            return chain

    prices = {
        "AAPL260715C00322500": 0.80,
        "AAPL260715C00325000": 0.35,
    }
    monkeypatch.setattr(flip_bot.yf, "Ticker", lambda symbol: FakeTicker())
    monkeypatch.setattr(flip_bot, "_option_snapshot_map", lambda symbols: {})
    monkeypatch.setattr(flip_bot, "_option_mid", lambda occ: prices.get(occ, 0.0))
    monkeypatch.setattr(
        flip_bot,
        "_selection_quote_fields",
        lambda occ: {
            "selection_bid": prices.get(occ, 2.00) - 0.05,
            "selection_ask": prices.get(occ, 2.00) + 0.05,
            "quote_timestamp": "2026-07-15T13:45:00Z",
            "quote_age_seconds": 1.0,
        },
    )

    rows = flip_bot._shadow_contract_challengers({
        "symbol": "AAPL",
        "right": "CALL",
        "expiry": "2026-07-15",
        "strike": 320.0,
        "option_symbol": "AAPL260715C00320000",
        "entry_price_est": 2.00,
    })

    assert [row["variant"] for row in rows] == ["atm", "otm_1", "otm_2"]
    assert [row["strike"] for row in rows] == [320.0, 322.5, 325.0]
    assert all(row["execution_mode"] == "shadow_only" for row in rows)
    assert all(row["live_execution_allowed"] is False for row in rows)


def test_shadow_contract_challengers_add_delta_itm_and_limit_policies(monkeypatch) -> None:
    import pandas as pd
    from types import SimpleNamespace
    from strategies import flip_bot

    chain = SimpleNamespace(
        calls=pd.DataFrame([{"strike": 317.5}, {"strike": 320.0}, {"strike": 322.5}]),
        puts=pd.DataFrame([{"strike": 317.5}, {"strike": 320.0}, {"strike": 322.5}]),
    )

    class FakeTicker:
        def option_chain(self, expiry):
            return chain

    itm_occ = "AAPL260715C00317500"
    monkeypatch.setattr(flip_bot.yf, "Ticker", lambda symbol: FakeTicker())
    monkeypatch.setattr(
        flip_bot,
        "_option_snapshot_map",
        lambda symbols: {
            itm_occ: {
                "latestQuote": {"bp": 2.00, "ap": 2.10, "t": "2026-07-15T13:45:00Z"},
                "greeks": {"delta": 0.61},
            }
        },
    )
    prices = {itm_occ: 2.05, "AAPL260715C00322500": 0.80}
    monkeypatch.setattr(flip_bot, "_option_mid", lambda occ: prices.get(occ, 1.05))
    monkeypatch.setattr(
        flip_bot,
        "_selection_quote_fields",
        lambda occ: {
            "selection_bid": 2.00 if occ == itm_occ else 1.00,
            "selection_ask": 2.10 if occ == itm_occ else 1.10,
            "quote_timestamp": "2026-07-15T13:45:00Z",
            "quote_age_seconds": 1.0,
        },
    )

    rows = flip_bot._shadow_contract_challengers({
        "symbol": "AAPL",
        "right": "CALL",
        "expiry": "2026-07-15",
        "strike": 320.0,
        "option_symbol": "AAPL260715C00320000",
        "entry_price_est": 1.05,
    })

    by_variant = {row["variant"]: row for row in rows}
    assert by_variant["itm_delta_60"]["strike"] == 317.5
    assert by_variant["itm_delta_60"]["selection_delta"] == 0.61
    assert by_variant["itm_delta_60"]["passive_limit_mid"] == 2.05
    assert by_variant["itm_delta_60"]["passive_limit_mid_plus_tick"] == 2.06
    assert by_variant["itm_delta_60"]["marketable_limit_ask"] == 2.10
    assert by_variant["itm_delta_60"]["live_execution_allowed"] is False


def test_shadow_contract_challenger_marks_use_entry_ask_and_exit_bid(monkeypatch) -> None:
    from strategies import flip_bot

    monkeypatch.setattr(flip_bot, "_option_mid", lambda occ: 1.50)
    monkeypatch.setattr(
        flip_bot,
        "_selection_quote_fields",
        lambda occ: {
            "selection_bid": 1.45,
            "selection_ask": 1.55,
            "quote_timestamp": "2026-07-15T14:05:00Z",
            "quote_age_seconds": 1.0,
        },
    )
    marked = flip_bot._mark_shadow_contract_challengers({
        "contract_selection_challengers": [{
            "variant": "otm_1",
            "option_symbol": "AAPL260715C00322500",
            "entry_mid": 0.80,
            "entry_ask": 0.85,
            "passive_limit_mid": 1.50,
            "passive_limit_mid_plus_tick": 1.51,
        }],
    })

    assert marked[0]["gross_mid_return_pct"] == 87.5
    assert marked[0]["executable_return_pct"] == 70.59
    assert marked[0]["passive_mid_fill_observed"] is False
    assert marked[0]["passive_plus_tick_fill_observed"] is False


def test_bear_trend_requires_spy_confirmation(monkeypatch) -> None:
    from datetime import datetime
    from zoneinfo import ZoneInfo
    from strategies import flip_bot

    monkeypatch.setattr(
        flip_bot,
        "_now_et",
        lambda: datetime(2026, 7, 10, 11, 0, tzinfo=ZoneInfo("America/New_York")),
    )
    monkeypatch.setattr(flip_bot, "_fetch_vix_term_structure", lambda: {"regime": "contango"})
    monkeypatch.setattr(flip_bot, "_intraday_bars", lambda symbol: object())
    monkeypatch.setattr(
        flip_bot,
        "_vwap_50ema_signal",
        lambda bars, sym: {
            "score": 8 if sym == "SPY" else 9,
            "vwap_distance": 0.001,
            "reasons": ["test"],
        },
    )

    assert flip_bot.find_bear_trend_day(90_000) is None


def test_flip_execution_universe_defaults_to_spy(monkeypatch, tmp_path) -> None:
    from strategies import flip_bot

    monkeypatch.setattr(flip_bot, "STATE_FILE", tmp_path / "flip-trades.json")
    monkeypatch.setattr(flip_bot, "EXECUTION_SYMBOLS", {"SPY"})
    monkeypatch.setattr(flip_bot, "_market_open", lambda: True)
    monkeypatch.setattr(flip_bot, "log_shadow_0dte_candidates", lambda account: [])
    monkeypatch.setattr(flip_bot, "find_bear_trend_day", lambda account: None)
    monkeypatch.setattr(flip_bot, "find_bull_trend_day", lambda account: None)
    monkeypatch.setattr(flip_bot, "find_0dte", lambda account: None)
    monkeypatch.setattr(
        flip_bot,
        "find_earnings",
        lambda account: [{
            "strategy": "earnings",
            "symbol": "AAPL",
            "right": "CALL",
            "option_symbol": "AAPL260717C00315000",
            "contracts": 1,
            "entry_price_est": 1.0,
        }],
    )
    monkeypatch.setattr(flip_bot, "find_breakouts", lambda account: [])
    monkeypatch.setattr(flip_bot, "_fetch_broker_open_symbols", lambda: set())
    submitted = []
    monkeypatch.setattr(flip_bot, "_submit", lambda *args, **kwargs: submitted.append(args))

    flip_bot.run_entry(90_000)

    assert submitted == []


def test_paper_challenger_is_authorized_at_one_contract(monkeypatch) -> None:
    from strategies import flip_bot

    monkeypatch.setattr(flip_bot, "PAPER", True)
    monkeypatch.setattr(flip_bot, "EXECUTION_SYMBOLS", {"SPY"})
    monkeypatch.setattr(flip_bot, "PAPER_CHALLENGER_SYMBOLS", {"AAPL", "NVDA"})

    result = flip_bot._execution_authorization("AAPL", 5)

    assert result == {
        "allowed": True,
        "lane": "paper_challenger",
        "contracts": 1,
        "reason": "paper_challenger_one_contract_cap",
    }


def test_paper_challenger_fails_closed_outside_paper_mode(monkeypatch) -> None:
    from strategies import flip_bot

    monkeypatch.setattr(flip_bot, "PAPER", False)
    monkeypatch.setattr(flip_bot, "EXECUTION_SYMBOLS", {"SPY"})
    monkeypatch.setattr(flip_bot, "PAPER_CHALLENGER_SYMBOLS", {"AAPL", "NVDA"})

    result = flip_bot._execution_authorization("NVDA", 3)

    assert result["allowed"] is False
    assert result["contracts"] == 0
    assert result["reason"] == "symbol_not_promoted"


def test_flip_bot_default_shadow_candidates_include_social_hot_megacap_options() -> None:
    from strategies import flip_bot

    assert "AAPL" in flip_bot.SHADOW_CANDIDATES
    assert "GOOGL" in flip_bot.SHADOW_CANDIDATES
    assert "META" in flip_bot.SHADOW_CANDIDATES


def test_market_force_shadow_snapshot_is_point_in_time_and_read_only(tmp_path: Path) -> None:
    import json
    from datetime import datetime, timezone
    from strategies import flip_bot

    path = tmp_path / "market-force.json"
    path.write_text(json.dumps({
        "timestamp": "2026-07-16T15:00:00Z",
        "classification": "bearish_confirmation",
        "execution_enabled": False,
    }), encoding="utf-8")

    snapshot = flip_bot._market_force_shadow_snapshot(
        datetime(2026, 7, 16, 15, 5, tzinfo=timezone.utc), path
    )

    assert snapshot["market_force_snapshot_status"] == "current"
    assert snapshot["market_force_classification"] == "bearish_confirmation"
    assert snapshot["market_force_age_seconds"] == 300.0
    assert snapshot["market_force_shadow_only"] is True


def test_scheduled_runner_orders_challengers_by_cumulative_shadow_ev() -> None:
    runner = (ROOT / "scripts" / "run_flip_bot_entry.ps1").read_text(encoding="utf-8")
    monitor = (ROOT / "scripts" / "run_flip_bot_monitor.ps1").read_text(encoding="utf-8")

    expected = '$env:FLIP_PAPER_CHALLENGER_SYMBOLS = "RIVN,AAPL,NVDA,QQQ"'
    assert expected in runner
    assert expected in monitor
    assert "IWM" not in runner.split("FLIP_PAPER_CHALLENGER_SYMBOLS", 1)[1].splitlines()[0]


def test_paper_challenger_0dte_scans_promoted_symbols_only_in_paper(monkeypatch) -> None:
    from strategies import flip_bot

    calls = []
    monkeypatch.setattr(flip_bot, "PAPER", True)
    monkeypatch.setattr(flip_bot, "EXECUTION_SYMBOLS", {"SPY"})
    monkeypatch.setattr(flip_bot, "PAPER_CHALLENGER_SYMBOL_ORDER", ["QQQ", "IWM", "REGN"])
    monkeypatch.setattr(flip_bot, "PAPER_CHALLENGER_SYMBOLS", {"QQQ", "IWM", "REGN"})

    def fake_find(account, symbol, *, allow_calendar_catalyst):
        calls.append((symbol, allow_calendar_catalyst))
        return {
            "strategy": "0dte",
            "symbol": symbol,
            "right": "PUT",
            "option_symbol": f"{symbol}260716P00100000",
            "contracts": 5,
            "entry_price_est": 1.0,
        }

    monkeypatch.setattr(flip_bot, "_find_0dte_for_symbol", fake_find)

    setups = flip_bot.find_paper_challenger_0dte(90_000)

    assert calls == [("QQQ", False), ("IWM", False)]
    assert [setup["symbol"] for setup in setups] == ["QQQ", "IWM"]
    assert {setup["execution_lane"] for setup in setups} == {"paper_challenger"}
    assert {setup["promotion_source"] for setup in setups} == {"paper_challenger_0dte"}


def test_paper_challenger_0dte_fails_closed_in_live_mode(monkeypatch) -> None:
    from strategies import flip_bot

    monkeypatch.setattr(flip_bot, "PAPER", False)
    monkeypatch.setattr(flip_bot, "PAPER_CHALLENGER_SYMBOLS", {"QQQ", "IWM"})
    monkeypatch.setattr(
        flip_bot,
        "_find_0dte_for_symbol",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("should not scan live challengers")),
    )

    assert flip_bot.find_paper_challenger_0dte(90_000) == []


def test_monitor_keeps_pending_exit_open_until_broker_fill(monkeypatch, tmp_path) -> None:
    import json
    from strategies import flip_bot

    state_file = tmp_path / "flip-trades.json"
    state_file.write_text(
        json.dumps([
            {
                "strategy": "bull_trend",
                "symbol": "SPY",
                "right": "CALL",
                "option_symbol": "SPY260720C00750000",
                "contracts": 1,
                "entry_price": 1.00,
                "target_price": 1.75,
                "stop_price": 0.70,
                "entry_date": "2026-07-20",
                "status": "open",
            }
        ]),
        encoding="utf-8",
    )
    submissions = []
    order_states = iter([
        {"id": "exit-1", "status": "new", "filled_avg_price": None},
        {"id": "exit-1", "status": "filled", "filled_avg_price": "0.68"},
    ])

    monkeypatch.setattr(flip_bot, "STATE_FILE", state_file)
    monkeypatch.setattr(flip_bot, "_market_open", lambda: True)
    monkeypatch.setattr(flip_bot, "_option_mid", lambda symbol: 0.69)
    monkeypatch.setattr(
        flip_bot,
        "_submit",
        lambda *args, **kwargs: submissions.append((args, kwargs))
        or {"id": "exit-1", "status": "accepted", "filled_avg_price": None},
    )
    monkeypatch.setattr(flip_bot, "_get", lambda path: next(order_states))
    monkeypatch.setattr(flip_bot, "_alert", lambda msg: None)
    monkeypatch.setattr(flip_bot, "_capture_point_in_time", lambda *args, **kwargs: [])
    monkeypatch.setattr(flip_bot, "shadow_exit_advice", lambda *args, **kwargs: {"enabled": False})
    monkeypatch.setattr(flip_bot, "ACCELERATED_SHADOW_LEARNING", False)

    flip_bot.run_monitor()
    pending = json.loads(state_file.read_text(encoding="utf-8"))[0]
    assert pending["status"] == "open"
    assert pending["exit_pending_order_id"] == "exit-1"
    assert "pnl" not in pending

    flip_bot.run_monitor()
    still_pending = json.loads(state_file.read_text(encoding="utf-8"))[0]
    assert still_pending["status"] == "open"
    assert len(submissions) == 1

    flip_bot.run_monitor()
    closed = json.loads(state_file.read_text(encoding="utf-8"))[0]
    assert closed["status"] == "closed"
    assert closed["exit_price"] == 0.68
    assert closed["exit_price_source"] == "broker_filled_avg_price"
    assert closed["exit_order_status"] == "filled"
    assert closed["pnl"] == -32.0
    assert len(submissions) == 1


def test_monitor_uses_broker_fill_not_trigger_mid_for_immediate_exit(monkeypatch, tmp_path) -> None:
    import json
    from strategies import flip_bot

    state_file = tmp_path / "flip-trades.json"
    state_file.write_text(
        json.dumps([
            {
                "strategy": "bull_trend",
                "symbol": "SPY",
                "right": "CALL",
                "option_symbol": "SPY260720C00750000",
                "contracts": 2,
                "entry_price": 1.00,
                "target_price": 1.75,
                "stop_price": 0.70,
                "entry_date": "2026-07-20",
                "status": "open",
            }
        ]),
        encoding="utf-8",
    )

    monkeypatch.setattr(flip_bot, "STATE_FILE", state_file)
    monkeypatch.setattr(flip_bot, "_market_open", lambda: True)
    monkeypatch.setattr(flip_bot, "_option_mid", lambda symbol: 0.69)
    monkeypatch.setattr(
        flip_bot,
        "_submit",
        lambda *args, **kwargs: {
            "id": "exit-filled",
            "status": "filled",
            "filled_avg_price": "0.66",
        },
    )
    monkeypatch.setattr(flip_bot, "_alert", lambda msg: None)
    monkeypatch.setattr(flip_bot, "_capture_point_in_time", lambda *args, **kwargs: [])
    monkeypatch.setattr(flip_bot, "shadow_exit_advice", lambda *args, **kwargs: {"enabled": False})
    monkeypatch.setattr(flip_bot, "ACCELERATED_SHADOW_LEARNING", False)

    flip_bot.run_monitor()

    closed = json.loads(state_file.read_text(encoding="utf-8"))[0]
    assert closed["status"] == "closed"
    assert closed["exit_price"] == 0.66
    assert closed["exit_price_source"] == "broker_filled_avg_price"
    assert closed["pnl"] == -68.0


def test_resting_take_profit_fill_stamps_broker_exit() -> None:
    from strategies import flip_bot

    trade = {
        "strategy": "bull_trend",
        "symbol": "SPY",
        "option_symbol": "SPY260720C00750000",
        "contracts": 2,
        "entry_price": 1.00,
        "status": "open",
        "resting_tp_order_id": "tp-filled",
        "resting_tp_status": "new",
    }

    assert flip_bot._finalize_resting_take_profit(
        trade,
        {"id": "tp-filled", "status": "filled", "filled_avg_price": "1.76"},
    ) is True
    assert trade["status"] == "closed"
    assert trade["exit_reason"] == "PROFIT TARGET (resting limit)"
    assert trade["exit_price"] == 1.76
    assert trade["exit_price_source"] == "broker_filled_avg_price"
    assert trade["pnl"] == 152.0


def test_monitor_cancel_confirms_resting_target_before_software_sell(monkeypatch, tmp_path) -> None:
    import json
    from strategies import flip_bot

    state_file = tmp_path / "flip-trades.json"
    state_file.write_text(
        json.dumps([{
            "strategy": "bull_trend",
            "symbol": "SPY",
            "right": "CALL",
            "option_symbol": "SPY260720C00750000",
            "contracts": 1,
            "entry_price": 1.00,
            "target_price": 1.75,
            "stop_price": 0.70,
            "entry_date": "2026-07-20",
            "status": "open",
            "resting_tp_order_id": "tp-1",
            "resting_tp_status": "new",
        }]),
        encoding="utf-8",
    )
    events = []
    order_states = iter([
        {"id": "tp-1", "status": "new"},
        {"id": "tp-1", "status": "canceled"},
    ])

    monkeypatch.setattr(flip_bot, "STATE_FILE", state_file)
    monkeypatch.setattr(flip_bot, "_market_open", lambda: True)
    monkeypatch.setattr(flip_bot, "_option_mid", lambda symbol: 0.69)
    monkeypatch.setattr(
        flip_bot,
        "_get",
        lambda path: events.append("get") or next(order_states),
    )
    monkeypatch.setattr(flip_bot, "_delete", lambda path: events.append("cancel"))
    monkeypatch.setattr(
        flip_bot,
        "_submit",
        lambda *args, **kwargs: events.append("sell")
        or {"id": "stop-exit", "status": "filled", "filled_avg_price": "0.68"},
    )
    monkeypatch.setattr(flip_bot, "_alert", lambda msg: None)
    monkeypatch.setattr(flip_bot, "_capture_point_in_time", lambda *args, **kwargs: [])
    monkeypatch.setattr(flip_bot, "shadow_exit_advice", lambda *args, **kwargs: {"enabled": False})
    monkeypatch.setattr(flip_bot, "ACCELERATED_SHADOW_LEARNING", False)

    flip_bot.run_monitor()

    assert events == ["get", "cancel", "get", "sell"]
    closed = json.loads(state_file.read_text(encoding="utf-8"))[0]
    assert closed["status"] == "closed"
    assert closed["exit_reason"].startswith("STOP LOSS")
    assert closed["exit_order_id"] == "stop-exit"


def test_monitor_resting_fill_wins_cancel_race_without_second_sell(monkeypatch, tmp_path) -> None:
    import json
    from strategies import flip_bot

    state_file = tmp_path / "flip-trades.json"
    state_file.write_text(
        json.dumps([{
            "strategy": "bull_trend",
            "symbol": "SPY",
            "right": "CALL",
            "option_symbol": "SPY260720C00750000",
            "contracts": 1,
            "entry_price": 1.00,
            "target_price": 1.75,
            "stop_price": 0.70,
            "entry_date": "2026-07-20",
            "status": "open",
            "resting_tp_order_id": "tp-race",
            "resting_tp_status": "new",
        }]),
        encoding="utf-8",
    )
    events = []
    order_states = iter([
        {"id": "tp-race", "status": "new"},
        {"id": "tp-race", "status": "filled", "filled_avg_price": "1.75"},
    ])

    monkeypatch.setattr(flip_bot, "STATE_FILE", state_file)
    monkeypatch.setattr(flip_bot, "_market_open", lambda: True)
    monkeypatch.setattr(flip_bot, "_option_mid", lambda symbol: 0.69)
    monkeypatch.setattr(flip_bot, "_get", lambda path: events.append("get") or next(order_states))
    monkeypatch.setattr(flip_bot, "_delete", lambda path: events.append("cancel"))
    monkeypatch.setattr(
        flip_bot,
        "_submit",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("must not double-sell")),
    )
    monkeypatch.setattr(flip_bot, "_alert", lambda msg: None)
    monkeypatch.setattr(flip_bot, "_capture_point_in_time", lambda *args, **kwargs: [])
    monkeypatch.setattr(flip_bot, "shadow_exit_advice", lambda *args, **kwargs: {"enabled": False})
    monkeypatch.setattr(flip_bot, "ACCELERATED_SHADOW_LEARNING", False)

    flip_bot.run_monitor()

    assert events == ["get", "cancel", "get"]
    closed = json.loads(state_file.read_text(encoding="utf-8"))[0]
    assert closed["status"] == "closed"
    assert closed["exit_reason"] == "PROFIT TARGET (resting limit)"
    assert closed["exit_order_id"] == "tp-race"



def test_monitor_protect_loop_exits_immediately_with_no_open_trades(monkeypatch):
    from strategies import flip_bot

    passes = []

    def fake_pass():
        passes.append(1)
        return False  # no open trades remain

    sleeps = []
    monkeypatch.setattr(flip_bot, "_monitor_pass", fake_pass)
    monkeypatch.setattr(flip_bot, "_market_open", lambda: True)
    monkeypatch.setattr(flip_bot.time, "sleep", lambda s: sleeps.append(s))
    monkeypatch.setattr(flip_bot, "ACCELERATED_SHADOW_LEARNING", False)

    flip_bot.run_monitor(protect_loop=True)

    assert len(passes) == 1
    assert sleeps == []


def test_monitor_protect_loop_rescans_while_positions_open(monkeypatch):
    from strategies import flip_bot

    results = iter([True, True, False])
    passes = []

    def fake_pass():
        passes.append(1)
        return next(results)

    sleeps = []
    monkeypatch.setattr(flip_bot, "_monitor_pass", fake_pass)
    monkeypatch.setattr(flip_bot, "_market_open", lambda: True)
    monkeypatch.setattr(flip_bot.time, "sleep", lambda s: sleeps.append(s))
    monkeypatch.setattr(flip_bot, "ACCELERATED_SHADOW_LEARNING", False)

    flip_bot.run_monitor(protect_loop=True)

    assert len(passes) == 3
    assert len(sleeps) == 2
    assert all(s == flip_bot.MONITOR_PROTECT_LOOP_SECONDS for s in sleeps)


def test_monitor_single_pass_unchanged_without_protect_loop(monkeypatch):
    from strategies import flip_bot

    passes = []
    monkeypatch.setattr(flip_bot, "_monitor_pass", lambda: passes.append(1) or True)
    monkeypatch.setattr(flip_bot, "_market_open", lambda: True)
    monkeypatch.setattr(
        flip_bot.time, "sleep",
        lambda s: (_ for _ in ()).throw(AssertionError("single-pass monitor must not sleep")),
    )
    monkeypatch.setattr(flip_bot, "ACCELERATED_SHADOW_LEARNING", False)

    flip_bot.run_monitor()

    assert len(passes) == 1


def test_monitor_protect_loop_stops_when_market_closes(monkeypatch):
    from strategies import flip_bot

    market_states = iter([True, False])  # open at start, closed at loop check
    passes = []
    monkeypatch.setattr(flip_bot, "_monitor_pass", lambda: passes.append(1) or True)
    monkeypatch.setattr(flip_bot, "_market_open", lambda: next(market_states))
    monkeypatch.setattr(
        flip_bot.time, "sleep",
        lambda s: (_ for _ in ()).throw(AssertionError("must not sleep after market close")),
    )
    monkeypatch.setattr(flip_bot, "ACCELERATED_SHADOW_LEARNING", False)

    flip_bot.run_monitor(protect_loop=True)

    assert len(passes) == 1

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timedelta, timezone

import requests

from scripts import flip_event_monitor
from strategies import flip_bot
from strategies.spy_spx_execution_policy import (
    edge_gate_decision,
    evaluate_underlying_exit,
    executable_ev_lower_bound,
    execution_ladder_prices,
    marketable_exit_limits,
    rank_instruments,
)


def test_entry_ladder_is_bounded_and_never_emits_market_sentinel():
    assert execution_ladder_prices(1.00, 1.04, 1.03) == [1.02, 1.03]
    assert execution_ladder_prices(0.0, 1.04, 1.03) == []
    assert marketable_exit_limits(0.88, concessions=2) == [0.88, 0.87, 0.86]


def test_executable_ev_lower_bound_penalizes_uncertainty_and_cost():
    strong = executable_ev_lower_bound([8.0, 9.0, 10.0, 11.0], extra_cost_pct=1.0)
    weak = executable_ev_lower_bound([-1.0, 1.0, -1.0, 1.0], extra_cost_pct=0.5)
    assert strong["status"] == "positive"
    assert strong["executable_ev_lower_bound_pct"] > 0
    assert weak["status"] == "non_positive"


def test_edge_gate_prefers_specific_chronological_cohort():
    report = {
        "generated_at": "2026-08-08T12:00:00Z",
        "cohorts": [
            {
                "cohort_type": "setup_symbol",
                "cohort": "SPY|0dte",
                "paper_gate_ready": True,
                "chronological_holdout": {"executable_ev_lower_bound_pct": 1.2},
                "paper_gate_blockers": [],
            },
            {
                "cohort_type": "setup_symbol_time",
                "cohort": "SPY|0dte|10:00",
                "paper_gate_ready": False,
                "chronological_holdout": {"executable_ev_lower_bound_pct": -0.2},
                "paper_gate_blockers": ["holdout_executable_ev_lower_bound_not_positive"],
            },
        ],
    }
    result = edge_gate_decision(report, symbol="SPY", strategy="0dte", time_bucket="10:00")
    assert result["allowed"] is False
    assert result["cohort_type"] == "setup_symbol_time"


def test_underlying_controller_exits_confirmed_structure_failure_before_premium_stop():
    trade = {
        "right": "CALL",
        "underlying_structure_level": 100.0,
        "entry_underlying_price": 101.0,
        "entry_at": (datetime.now(timezone.utc) - timedelta(minutes=5)).isoformat(),
    }
    mark = {"underlying_close": 99.7, "underlying_prior_5m_close": 99.8, "underlying_vwap": 100.2}
    decision = evaluate_underlying_exit(trade, mark, pnl_pct=-8.0)
    assert decision["exit"] is True
    assert decision["status"] == "structure_invalidated"


def test_underlying_controller_time_stops_stalled_trade():
    trade = {
        "right": "PUT",
        "entry_underlying_price": 100.0,
        "entry_at": (datetime.now(timezone.utc) - timedelta(minutes=30)).isoformat(),
    }
    mark = {"underlying_close": 100.2, "underlying_prior_5m_close": 100.1, "underlying_vwap": 100.0}
    decision = evaluate_underlying_exit(trade, mark, pnl_pct=-2.0, time_stop_minutes=25)
    assert decision["exit"] is True
    assert decision["status"] == "time_stop"


def test_router_requires_broker_support_opra_and_positive_net_payoff():
    report = rank_instruments(
        [
            {
                "instrument": "SPY",
                "broker_support_verified": True,
                "quote_authority": "opra",
                "gross_expected_payoff": 40,
                "spread_cost": 4,
                "fees": 1,
                "slippage": 2,
                "staleness_penalty": 0,
                "model_uncertainty": 5,
            },
            {
                "instrument": "SPX",
                "broker_support_verified": False,
                "quote_authority": "opra",
                "gross_expected_payoff": 100,
            },
        ]
    )
    assert report["selected"]["instrument"] == "SPY"
    assert report["execution_enabled"] is False
    assert report["can_submit_orders"] is False


def test_flip_submit_rejects_automatic_market_order(monkeypatch):
    posted = []
    monkeypatch.setattr(flip_bot, "_option_mid", lambda _symbol: 0.88)
    monkeypatch.setattr(flip_bot, "_post", lambda _path, body: posted.append(body) or {"id": "exit"})
    assert flip_bot._submit("SPY260810C00600000", 1, "buy") is None
    assert flip_bot._submit("SPY260810C00600000", 1, "sell") == {"id": "exit"}
    assert posted == [
        {
            "symbol": "SPY260810C00600000",
            "qty": "1",
            "side": "sell",
            "time_in_force": "day",
            "type": "limit",
            "limit_price": "0.88",
        }
    ]


def test_ambiguous_order_timeout_is_not_retried(monkeypatch):
    attempts = []
    monkeypatch.setattr(
        flip_bot,
        "_post",
        lambda *_args, **_kwargs: attempts.append(1) or (_ for _ in ()).throw(requests.Timeout("ambiguous")),
    )
    monkeypatch.setattr(flip_bot, "_alert", lambda _message: None)
    assert flip_bot._submit("SPY260810C00600000", 1, "buy", limit_price=1.00) is None
    assert attempts == [1]


def test_flip_entry_ladder_records_arrival_and_replacement(monkeypatch):
    setup = {
        "option_symbol": "SPY260810C00600000",
        "contracts": 1,
        "entry_limit_price": 1.04,
    }
    monkeypatch.setattr(flip_bot, "ENTRY_LADDER_WAIT_SECONDS", 0.0)
    monkeypatch.setattr(flip_bot, "_option_mid", lambda _symbol: 1.02)
    monkeypatch.setattr(
        flip_bot,
        "_selection_quote_fields",
        lambda _symbol: {
            "selection_bid": 1.00,
            "selection_ask": 1.04,
            "quote_timestamp": "2026-08-08T12:00:00Z",
            "quote_authority": "opra",
        },
    )
    submitted = []
    monkeypatch.setattr(
        flip_bot,
        "_submit",
        lambda *_args, **kwargs: submitted.append(kwargs["limit_price"]) or {"id": "one", "status": "new"},
    )
    monkeypatch.setattr(flip_bot, "_get", lambda _path: {"id": "one", "status": "new", "filled_qty": "0"})
    monkeypatch.setattr(
        flip_bot,
        "_patch",
        lambda _path, body: {"id": f"replace-{body['limit_price']}", "status": "new", "filled_qty": "0"},
    )
    response = flip_bot._submit_entry_ladder(setup, max_notional=500)
    assert response is not None
    assert submitted == [1.02]
    assert setup["entry_execution_ladder"]["submitted_prices"] == [1.02, 1.03, 1.04]
    assert setup["entry_execution_ladder"]["replacement_count"] == 2


def test_indicative_stream_quote_never_triggers_monitor(monkeypatch, tmp_path):
    triggered = []
    monkeypatch.setattr(flip_event_monitor, "FEED_NAME", "indicative")
    monkeypatch.setattr(flip_event_monitor, "CACHE_PATH", tmp_path / "quotes.json")
    monkeypatch.setattr(flip_event_monitor, "_trigger_monitor", lambda source: triggered.append(source))
    asyncio.run(
        flip_event_monitor._on_quote(
            {"S": "SPY260810C00600000", "bp": 1.0, "ap": 1.1, "t": "2026-08-08T12:00:00Z"}
        )
    )
    assert triggered == []
    cached = json.loads((tmp_path / "quotes.json").read_text(encoding="utf-8"))
    assert cached["quote_authority"] == "indicative_telemetry_only"

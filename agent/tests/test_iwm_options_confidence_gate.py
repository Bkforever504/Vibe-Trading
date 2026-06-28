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


def test_place_mleg_records_candidate_confidence_in_trade_state(monkeypatch, tmp_path) -> None:
    from strategies import iwm_options_bot as bot

    state_file = tmp_path / "options-trades.json"
    monkeypatch.setattr(bot, "TRADE_STATE_FILE", state_file)
    monkeypatch.setattr(bot, "REQUIRE_MANUAL_APPROVAL", False)
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

    class FakeClient:
        def get_all_positions(self):
            return []

    bot.monitor_and_close(FakeClient())

    state = bot._load_trade_state()
    assert state["trades"][0]["status"] == "closed"
    assert "closed_at" in state["trades"][0]

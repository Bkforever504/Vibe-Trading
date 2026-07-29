from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _base_bot(monkeypatch):
    from strategies import iwm_options_bot as bot

    monkeypatch.setattr(bot, "ENABLE_GARCH_RISK_GATE", False)
    monkeypatch.setattr(bot, "ENABLE_OPTIONS_QUANT_RISK_BUDGET", True)
    monkeypatch.setattr(bot, "REQUIRE_MANUAL_APPROVAL", False)
    monkeypatch.setattr(bot, "shadow_entry_advice", lambda *_args, **_kwargs: {"enabled": False})
    monkeypatch.setattr(bot, "_guard_submission", lambda *_args, **_kwargs: True)
    monkeypatch.setattr(bot, "_alert", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(bot, "_record_trade_group", lambda *_args, **_kwargs: None)
    return bot


def test_quant_risk_budget_sizes_down_mleg_before_submit(monkeypatch) -> None:
    bot = _base_bot(monkeypatch)
    posted = []

    def fake_allocation(**kwargs):
        return {
            "allowed": True,
            "adjusted_qty": 1,
            "requested_qty": kwargs["requested_qty"],
            "reason": "quant_risk_size_cap",
            "risk_cap_dollars": 250.0,
        }

    monkeypatch.setattr(bot, "quant_risk_allocation", fake_allocation)
    monkeypatch.setattr(bot, "_post_order_with_retry", lambda body, _label: posted.append(body) or {"id": "ok"})

    submitted = bot._place_mleg(
        legs_payload=[
            {"symbol": "AAPL260731P00315000", "side": "sell", "ratio_qty": "1"},
            {"symbol": "AAPL260731P00310000", "side": "buy", "ratio_qty": "1"},
        ],
        limit_price=0.80,
        qty=3,
        label="Put Spread [AAPL]",
        trade_meta={
            "strategy": "put_spread",
            "underlying": "AAPL",
            "max_risk_per_contract": 420,
            "sizing_equity": 100_000,
            "candidate_confidence": {"score": 9},
        },
    )

    assert submitted is True
    assert posted[0]["qty"] == "1"


def test_quant_risk_budget_blocks_mleg_when_budget_zero(monkeypatch) -> None:
    bot = _base_bot(monkeypatch)
    posted = []
    decisions = []

    monkeypatch.setattr(
        bot,
        "quant_risk_allocation",
        lambda **_kwargs: {
            "allowed": False,
            "adjusted_qty": 0,
            "requested_qty": 2,
            "reason": "quant_risk_size_cap",
        },
    )
    monkeypatch.setattr(bot, "_post_order_with_retry", lambda body, _label: posted.append(body) or {"id": "bad"})
    monkeypatch.setattr(bot, "_decision", lambda *args, **kwargs: decisions.append((args, kwargs)))

    submitted = bot._place_mleg(
        legs_payload=[
            {"symbol": "TSLA260731C00400000", "side": "sell", "ratio_qty": "1"},
            {"symbol": "TSLA260731C00405000", "side": "buy", "ratio_qty": "1"},
        ],
        limit_price=1.00,
        qty=2,
        label="Call Spread [TSLA]",
        trade_meta={
            "strategy": "call_spread",
            "underlying": "TSLA",
            "max_risk_per_contract": 400,
            "sizing_equity": 100_000,
            "candidate_confidence": {"score": 9},
        },
    )

    assert submitted is False
    assert posted == []
    assert decisions[0][0][3] == "quant_risk_size_cap"

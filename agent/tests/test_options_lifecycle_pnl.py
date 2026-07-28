from __future__ import annotations

import pytest

from scripts import lifecycle_normalizer as canon
from strategies import iwm_options_bot as bot


def _trade(**overrides):
    row = {
        "id": "spread-1",
        "status": "closing",
        "strategy": "put_spread",
        "underlying": "IWM",
        "net_credit": 0.52,
        "qty": 3,
        "max_risk_per_contract": 248.0,
    }
    row.update(overrides)
    return row


def _order(**overrides):
    row = {
        "status": "filled",
        "filled_avg_price": "0.23",
        "filled_qty": "3",
    }
    row.update(overrides)
    return row


def test_closing_fill_sets_fill_derived_fields():
    trade = _trade()
    assert bot._apply_closing_fill(trade, _order()) is True
    assert trade["closing_filled_avg_price"] == pytest.approx(0.23)
    assert trade["closing_filled_qty"] == 3
    assert trade["realized_pnl_dollars"] == pytest.approx(87.0)
    assert trade["pnl_source"] == "fill_derived"


def test_put_spread_realized_pnl_uses_credit_minus_closing_debit():
    trade = _trade()
    bot._apply_closing_fill(trade, _order())
    assert trade["realized_pnl_dollars"] == pytest.approx(
        (0.52 - 0.23) * 3 * 100
    )


def test_filled_group_refresh_persists_realized_pnl(monkeypatch):
    state = {
        "trades": [{
            **_trade(),
            "closing_order_id": "close-1",
            "legs": ["IWM-P1", "IWM-P2"],
        }]
    }
    monkeypatch.setattr(bot, "_order_snapshot", lambda _: {
        **_order(),
        "id": "close-1",
        "order_class": "mleg",
        "filled_at": "2026-07-25T18:00:00Z",
        "legs": [{"symbol": "IWM-P1"}, {"symbol": "IWM-P2"}],
    })
    assert bot._refresh_filled_group_closes(state) is True
    closed = state["trades"][0]
    assert closed["status"] == "closed"
    assert closed["realized_pnl_dollars"] == pytest.approx(87.0)
    assert closed["pnl_source"] == "fill_derived"
    assert closed["close_verified_by"] == "alpaca_filled_mleg_order"


def test_normalizer_accepts_explicit_fill_derived_pnl():
    trade = _trade(
        status="closed",
        realized_pnl_dollars=87.0,
        pnl_source="fill_derived",
    )
    view = canon.normalize_options_trade(trade)
    assert view["pnl_dollars"] == pytest.approx(87.0)
    assert view["pnl_source"] == "fill_derived"
    assert view["legacy_no_fill_pnl"] is False
    assert view["quarantined"] is False


def test_normalizer_quarantines_legacy_close_without_fill_pnl():
    view = canon.normalize_options_trade(_trade(status="closed"))
    assert view["pnl_dollars"] is None
    assert view["legacy_no_fill_pnl"] is True
    assert view["quarantined"] is True
    assert "closed_without_resolvable_pnl" in view["unknown_reasons"]


@pytest.mark.parametrize("closing_price", [0.0, -0.01])
def test_zero_or_negative_closing_price_caps_loss_at_zero(closing_price):
    trade = _trade()
    assert bot._apply_closing_fill(
        trade, _order(filled_avg_price=closing_price)
    ) is True
    assert trade["closing_filled_avg_price"] == 0.0
    assert trade["realized_pnl_dollars"] == pytest.approx(156.0)

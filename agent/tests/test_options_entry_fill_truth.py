from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from strategies import iwm_options_bot as bot


def _trade(**overrides):
    trade = {
        "label": "Test spread",
        "status": "pending",
        "legs": ["IWM260821P00200000", "IWM260821P00195000"],
        "net_credit": 0.62,
        "submitted_limit_credit": 0.62,
        "max_risk_per_contract": 438.0,
        "qty": 1,
    }
    trade.update(overrides)
    return trade


def _order(**overrides):
    order = {
        "status": "filled",
        "filled_qty": 1,
        "filled_avg_price": -0.40,
        "filled_at": "2026-07-25T14:31:00Z",
        "legs": [
            {"symbol": "IWM260821P00200000"},
            {"symbol": "IWM260821P00195000"},
        ],
    }
    order.update(overrides)
    return order


def test_credit_fill_uses_broker_price_and_recomputes_risk() -> None:
    trade = _trade()

    assert bot._apply_entry_fill(trade, _order()) is True
    assert trade["net_credit"] == 0.40
    assert trade["entry_filled_avg_price_signed"] == -0.40
    # Risk grows by the credit shortfall: (0.62 - 0.40) * 100.
    assert trade["max_risk_per_contract"] == 460.0
    assert trade["status"] == "open"
    assert trade["entry_fill_leg_verification"] == "verified"


def test_risk_adjustment_is_idempotent_across_repeat_applications() -> None:
    trade = _trade()

    assert bot._apply_entry_fill(trade, _order()) is True
    assert bot._apply_entry_fill(trade, _order()) is True

    assert trade["max_risk_per_contract"] == 460.0
    assert trade["submitted_max_risk_per_contract"] == 438.0


def test_positive_debit_fill_is_refused_not_absorbed_as_credit() -> None:
    trade = _trade()

    applied = bot._apply_entry_fill(trade, _order(filled_avg_price=0.40))

    assert applied is False
    assert trade["status"] == "pending"
    assert trade["net_credit"] == 0.62  # untouched
    assert trade["entry_fill_review"] == "non_credit_filled_avg_price"


def test_canceled_order_with_partial_fill_still_applies_real_exposure() -> None:
    trade = _trade()

    applied = bot._apply_entry_fill(
        trade, _order(status="canceled", filled_qty=1, filled_avg_price=-0.40)
    )

    assert applied is True
    assert trade["status"] == "open"
    assert trade["qty"] == 1
    assert trade["net_credit"] == 0.40


def test_canceled_order_without_fill_is_not_applied() -> None:
    trade = _trade()

    applied = bot._apply_entry_fill(
        trade, _order(status="canceled", filled_qty=0, filled_avg_price=None)
    )

    assert applied is False
    assert trade["status"] == "pending"


def test_leg_mismatch_keeps_order_pending() -> None:
    trade = _trade()
    order = _order(legs=[{"symbol": "IWM260821P00200000"}, {"symbol": "IWM260821P00190000"}])

    assert bot._apply_entry_fill(trade, order) is False
    assert trade["status"] == "pending"


def test_missing_order_legs_marks_verification_unavailable() -> None:
    trade = _trade()

    assert bot._apply_entry_fill(trade, _order(legs=[])) is True
    assert trade["entry_fill_leg_verification"] == "unavailable"

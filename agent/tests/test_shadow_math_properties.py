"""Property checks for shadow ranking and the existing profit ratchet.

These tests do not call a broker or alter any strategy configuration.
"""
from __future__ import annotations

import math

from hypothesis import given, settings, strategies as st

from strategies import flip_bot


@settings(max_examples=200, deadline=None)
@given(st.floats(min_value=-100, max_value=1000, allow_nan=False, allow_infinity=False), st.floats(min_value=0, max_value=500, allow_nan=False, allow_infinity=False))
def test_profit_protect_ratchet_never_widens(best: float, improvement: float):
    assert flip_bot._profit_protect_lock_floor(best + improvement) >= flip_bot._profit_protect_lock_floor(best)


@settings(max_examples=200)
@given(
    max_risk=st.floats(min_value=0, max_value=1_000_000, allow_nan=False, allow_infinity=False),
    premium=st.floats(min_value=.01, max_value=10_000, allow_nan=False, allow_infinity=False),
    cap=st.integers(min_value=1, max_value=100),
)
def test_contract_sizing_formula_never_exceeds_hard_cap(max_risk: float, premium: float, cap: int):
    contracts = min(int(max_risk // (premium * 100)), cap)
    assert 0 <= contracts <= cap
    assert math.isfinite(contracts)


@settings(max_examples=200)
@given(
    width=st.floats(min_value=.01, max_value=100, allow_nan=False, allow_infinity=False),
    credit_fraction=st.floats(min_value=0, max_value=1, allow_nan=False, allow_infinity=False),
)
def test_credit_spread_max_loss_is_bounded_by_width(width: float, credit_fraction: float):
    credit = width * credit_fraction
    max_loss = (width - credit) * 100
    assert 0 <= max_loss <= width * 100

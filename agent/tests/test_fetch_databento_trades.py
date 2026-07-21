from __future__ import annotations

import pytest

from scripts.fetch_databento_trades import credit_guard, request_kwargs


def test_trade_request_is_fixed_to_q4_continuous_mes() -> None:
    request = request_kwargs()
    assert request == {
        "dataset": "GLBX.MDP3",
        "schema": "trades",
        "symbols": "MES.v.0",
        "stype_in": "continuous",
        "start": "2025-10-01",
        "end": "2026-01-01",
    }


def test_credit_guard_preserves_buffer_without_card_fallback() -> None:
    result = credit_guard(29.33, 52.82)
    assert result["estimated_remaining_credits_usd"] == 23.49
    assert result["minimum_credit_buffer_usd"] == 10.0


def test_credit_guard_rejects_cost_above_cap() -> None:
    with pytest.raises(RuntimeError, match="exceeds hard cap"):
        credit_guard(30.01, 52.82)


def test_credit_guard_rejects_insufficient_credit_buffer() -> None:
    with pytest.raises(RuntimeError, match="safety buffer"):
        credit_guard(29.33, 35.0)

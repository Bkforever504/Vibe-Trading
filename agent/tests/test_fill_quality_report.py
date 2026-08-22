from __future__ import annotations

from datetime import datetime, timezone

import pytest

from scripts.fill_quality_report import build_report, decompose_slippage


NOW = datetime(2026, 8, 20, 22, 0, tzinfo=timezone.utc)


def test_signed_slippage_decomposition_for_buy_and_sell() -> None:
    buy = decompose_slippage({"side": "buy", "intent_price": 1.0, "arrival_price": 1.1, "fill_price": 1.15, "realized_price": 1.2})
    sell = decompose_slippage({"side": "sell", "intent_price": 2.0, "arrival_price": 1.9, "fill_price": 1.85, "realized_price": 1.8})

    assert buy["intent_to_arrival"] == pytest.approx(0.1)
    assert buy["arrival_to_fill"] == pytest.approx(0.05)
    assert sell["intent_to_arrival"] == pytest.approx(0.1)
    assert sell["arrival_to_fill"] == pytest.approx(0.05)


def test_fill_quality_report_is_explicit_when_unavailable_or_complete() -> None:
    unavailable = build_report([], generated_at=NOW)
    complete = build_report(
        [{"side": "buy", "intent_price": 1.0, "arrival_price": 1.1, "fill_price": 1.15, "realized_price": 1.2}],
        generated_at=NOW,
    )

    assert unavailable["status"] == "unavailable"
    assert complete["status"] == "ok"
    assert complete["complete_sample_count"] == 1
    assert complete["execution_enabled"] is False
    assert complete["can_submit_orders"] is False

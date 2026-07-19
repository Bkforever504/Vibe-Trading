from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from strategies.czt_order_flow import evaluate_czt, volume_profile, normalize_bars


def _bars(direction: str = "up", count: int = 60, with_prints: bool = False):
    start = datetime(2026, 7, 15, 9, 30)
    rows = []
    for index in range(count):
        drift = index * 0.08 * (1 if direction == "up" else -1)
        close = 600.0 + drift
        row = {
            "timestamp": (start + timedelta(minutes=index)).isoformat(),
            "open": close - (0.08 if direction == "up" else -0.08),
            "high": close + 0.12,
            "low": close - 0.12,
            "close": close,
            "volume": 1000 + index * 25,
        }
        if with_prints:
            row["ask_volume"] = row["volume"] * (0.7 if direction == "up" else 0.3)
            row["bid_volume"] = row["volume"] - row["ask_volume"]
        rows.append(row)
    rows[-2]["volume"] *= 2
    rows[-1]["volume"] *= 2
    return rows


def test_normalize_rejects_invalid_rows():
    rows = _bars()[:1] + [{"open": "bad"}]
    assert len(normalize_bars(rows)) == 1


def test_volume_profile_is_labeled_as_proxy():
    profile = volume_profile(normalize_bars(_bars()))
    assert profile["val"] <= profile["poc"] <= profile["vah"]
    assert profile["provenance"] == "bar_range_distributed_volume_proxy"


@pytest.mark.parametrize(("direction", "option_side"), [("up", "call"), ("down", "put")])
def test_aligned_trend_remains_shadow_only(direction, option_side):
    result = evaluate_czt(_bars(direction), symbol="SPY")
    assert result["condition"]["direction"] == option_side
    assert result["authority"] == "shadow_research_only"
    assert result["execution_enabled"] is False
    assert result["can_submit_orders"] is False
    assert result["live_execution_allowed"] is False


def test_print_data_can_confirm_but_not_authorize():
    result = evaluate_czt(_bars("up", with_prints=True), symbol="SPY")
    if result["trigger"]["detected"]:
        assert result["trigger"]["quality"] == "prints_confirmed"
    assert result["live_execution_allowed"] is False
    assert result["trigger"]["resting_liquidity_observed"] is False


def test_requires_minimum_history():
    with pytest.raises(ValueError, match="at least 30"):
        evaluate_czt(_bars(count=12), symbol="SPY")

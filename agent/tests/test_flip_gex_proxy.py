from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace

import pandas as pd

from strategies import flip_bot as bot


def test_yahoo_gex_profile_is_explicitly_unqualified(monkeypatch) -> None:
    calls = pd.DataFrame(
        [
            {"strike": 99.0, "openInterest": 100, "impliedVolatility": 0.20},
            {"strike": 101.0, "openInterest": 50, "impliedVolatility": 0.20},
        ]
    )
    puts = pd.DataFrame(
        [
            {"strike": 99.0, "openInterest": 40, "impliedVolatility": 0.20},
            {"strike": 101.0, "openInterest": 80, "impliedVolatility": 0.20},
        ]
    )

    class FakeTicker:
        options = ["2099-01-01"]

        @staticmethod
        def option_chain(_expiry: str):
            return SimpleNamespace(calls=calls, puts=puts)

    monkeypatch.setattr(bot.yf, "Ticker", lambda _symbol: FakeTicker())
    monkeypatch.setattr(bot, "_spot", lambda _symbol: 100.0)
    monkeypatch.setattr(bot, "_now_et", lambda: datetime(2026, 8, 14, 12, 0))

    result = bot._gex_profile_yf("SPY")

    assert result["status"] == "ok"
    assert result["authority"] == "unqualified_proxy"
    assert result["dealer_positioning_observed"] is False
    assert result["sign_assumption"] == "calls_positive_puts_negative"
    assert result["gamma_flip_method"] == "cumulative_strike_gamma_oi_crossing_not_spot_revaluation"
    assert result["gamma_flip_regime"] == "unavailable_without_spot_revaluation"
    assert result["price_role"] == "unclassified"
    assert result["profile"].startswith(("positive_proxy_", "negative_proxy_"))
    assert result["profile_interpretation"] == "descriptive_only_not_a_pin_or_direction_signal"
    assert result["execution_enabled"] is False
    assert result["can_block_execution"] is False

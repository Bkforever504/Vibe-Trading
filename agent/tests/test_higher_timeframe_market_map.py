from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts import higher_timeframe_market_map as htf


def _trend_bars(start: float, step: float, count: int = 80) -> pd.DataFrame:
    closes = [start + step * i for i in range(count)]
    return pd.DataFrame(
        {
            "Open": [c - step * 0.25 for c in closes],
            "High": [c + 1.0 for c in closes],
            "Low": [c - 1.0 for c in closes],
            "Close": closes,
            "Volume": [1000 + i for i in range(count)],
        }
    )


def test_uptrend_daily_and_intraday_allows_long_call_playbook() -> None:
    context = htf.analyze_symbol(
        "SPY",
        daily=_trend_bars(700, 0.8),
        weekly=_trend_bars(600, 1.4),
        intraday=_trend_bars(745, 0.05),
    )

    assert context["primary_bias"] == "bullish"
    assert context["intraday_alignment"] == "aligned"
    assert "directional_long_call" in context["allowed_playbooks"]
    assert context["veto_reasons"] == []


def test_downtrend_daily_with_weak_intraday_blocks_bullish_premium_selling() -> None:
    context = htf.analyze_symbol(
        "QQQ",
        daily=_trend_bars(720, -0.8),
        weekly=_trend_bars(760, -1.1),
        intraday=_trend_bars(705, -0.04),
    )

    assert context["primary_bias"] == "bearish"
    assert "directional_long_put" in context["allowed_playbooks"]
    assert "bullish_put_spread_blocked_by_htf" in context["veto_reasons"]


def test_mixed_timeframes_require_review() -> None:
    context = htf.analyze_symbol(
        "IWM",
        daily=_trend_bars(295, 0.3),
        weekly=_trend_bars(310, -0.4),
        intraday=_trend_bars(297, 0.0),
    )

    assert context["primary_bias"] == "mixed"
    assert context["allowed_playbooks"] == ["stand_aside", "needs_review"]


def test_build_report_is_read_only(monkeypatch) -> None:
    monkeypatch.setattr(htf, "fetch_history", lambda symbol, period, interval: _trend_bars(100, 0.5))

    report = htf.build_report(["SPY"])

    assert report["execution_enabled"] is False
    assert report["can_submit_orders"] is False
    assert report["items"][0]["symbol"] == "SPY"

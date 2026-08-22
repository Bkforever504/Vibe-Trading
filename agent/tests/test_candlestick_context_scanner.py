from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts import candlestick_context_scanner as scanner


def test_detects_bullish_engulfing_after_vwap_reclaim() -> None:
    bars = pd.DataFrame(
        [
            {"Open": 100.0, "High": 101.0, "Low": 98.8, "Close": 99.2, "Volume": 1000},
            {"Open": 98.9, "High": 102.4, "Low": 98.7, "Close": 102.1, "Volume": 1800},
        ]
    )

    context = scanner.analyze_symbol("SPY", bars, reference_levels={"vwap": 100.5})

    assert context["primary_signal"] == "bullish_engulfing_reclaim"
    assert context["bias"] == "bullish"
    assert "directional_long_call" in context["allowed_playbooks"]


def test_detects_bearish_engulfing_failed_breakout() -> None:
    bars = pd.DataFrame(
        [
            {"Open": 100.0, "High": 102.0, "Low": 99.8, "Close": 101.7, "Volume": 1000},
            {"Open": 102.1, "High": 102.3, "Low": 98.9, "Close": 99.4, "Volume": 2200},
        ]
    )

    context = scanner.analyze_symbol("QQQ", bars, reference_levels={"prior_high": 102.0})

    assert context["primary_signal"] == "bearish_engulfing_failed_breakout"
    assert context["bias"] == "bearish"
    assert "directional_long_put" in context["allowed_playbooks"]


def test_detects_liquidity_grab_lower_wick_at_support() -> None:
    bars = pd.DataFrame(
        [
            {"Open": 100.0, "High": 101.0, "Low": 99.5, "Close": 100.2, "Volume": 900},
            {"Open": 100.1, "High": 101.4, "Low": 96.8, "Close": 100.9, "Volume": 2100},
        ]
    )

    context = scanner.analyze_symbol("IWM", bars, reference_levels={"prior_low": 97.0})

    assert context["primary_signal"] == "bullish_liquidity_grab"
    assert context["bias"] == "bullish"
    assert "support_wick_rejection" in context["features"]


def test_build_report_is_read_only_and_summarizes_symbols(monkeypatch) -> None:
    bars = pd.DataFrame(
        [
            {"Open": 100.0, "High": 101.0, "Low": 98.8, "Close": 99.2, "Volume": 1000},
            {"Open": 98.9, "High": 102.4, "Low": 98.7, "Close": 102.1, "Volume": 1800},
        ]
    )
    monkeypatch.setattr(scanner, "fetch_recent_bars", lambda symbol: bars)

    report = scanner.build_report(["SPY", "QQQ"])

    assert report["execution_enabled"] is False
    assert report["can_submit_orders"] is False
    assert report["summary"]["bullish"] == 2
    assert {row["symbol"] for row in report["items"]} == {"SPY", "QQQ"}


def test_reference_levels_use_current_and_prior_sessions_only() -> None:
    index = pd.to_datetime([
        "2026-08-02T14:30:00Z",
        "2026-08-02T14:45:00Z",
        "2026-08-03T14:30:00Z",
        "2026-08-03T14:45:00Z",
    ])
    bars = pd.DataFrame(
        [
            {"Open": 99.0, "High": 101.0, "Low": 98.0, "Close": 100.0, "Volume": 10},
            {"Open": 100.0, "High": 102.0, "Low": 99.0, "Close": 101.0, "Volume": 20},
            {"Open": 101.0, "High": 103.0, "Low": 100.0, "Close": 102.0, "Volume": 10},
            {"Open": 102.0, "High": 104.0, "Low": 101.0, "Close": 103.0, "Volume": 30},
        ],
        index=index,
    )

    levels = scanner.reference_levels_from_bars(bars)

    assert levels["status"] == "point_in_time_session_levels"
    assert levels["prior_high"] == 102.0
    assert levels["prior_low"] == 98.0
    assert levels["vwap"] == 102.416667

from __future__ import annotations

import sys
from datetime import date, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from strategies.topstep_prop_bot import Candle
from strategies.tradovate_market_data import (
    TradovateSettings,
    build_chart_request,
    current_front_month_symbol,
    extract_chart_candles,
    tradovate_endpoints,
)


def test_tradovate_endpoints_use_demo_market_data_by_default() -> None:
    endpoints = tradovate_endpoints("demo")

    assert endpoints.rest_base == "https://demo.tradovateapi.com/v1"
    assert endpoints.market_data_ws == "wss://md-demo.tradovateapi.com/v1/websocket"


def test_front_month_symbol_rolls_quarterly_contract_after_mid_month() -> None:
    assert current_front_month_symbol("MNQ", today=date(2026, 6, 10)) == "MNQM6"
    assert current_front_month_symbol("MNQ", today=date(2026, 6, 23)) == "MNQU6"


def test_build_chart_request_asks_for_minute_bars_with_histogram() -> None:
    request = build_chart_request("MNQU6", bars=100, interval_minutes=1)

    assert request == {
        "symbol": "MNQU6",
        "chartDescription": {
            "underlyingType": "MinuteBar",
            "elementSize": 1,
            "elementSizeUnit": "UnderlyingUnits",
            "withHistogram": True,
        },
        "timeRange": {"asMuchAsElements": 100},
    }


def test_extract_chart_candles_accepts_tradovate_bar_shapes() -> None:
    messages = [
        {
            "s": 200,
            "i": 2,
            "d": {
                "bars": [
                    {
                        "timestamp": "2026-06-23T14:30:00Z",
                        "openPrice": 20100.25,
                        "highPrice": 20105.5,
                        "lowPrice": 20098.0,
                        "closePrice": 20104.25,
                        "upVolume": 14,
                        "downVolume": 9,
                    }
                ]
            },
        }
    ]

    candles = extract_chart_candles(messages)

    assert candles == [
        Candle(
            timestamp=datetime(2026, 6, 23, 14, 30),
            open=20100.25,
            high=20105.5,
            low=20098.0,
            close=20104.25,
            volume=23,
        )
    ]


def test_settings_reports_missing_credentials_without_showing_values() -> None:
    settings = TradovateSettings(username="", password="", app_id="", app_version="1.0", cid="", sec="")

    assert settings.missing_fields() == [
        "TRADOVATE_USERNAME",
        "TRADOVATE_PASSWORD",
        "TRADOVATE_APP_ID",
        "TRADOVATE_CID",
        "TRADOVATE_SEC",
    ]

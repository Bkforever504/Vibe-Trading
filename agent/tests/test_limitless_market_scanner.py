from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts import limitless_market_scanner as scanner


def test_normalize_market_extracts_book_and_poly_flag() -> None:
    market = {
        "id": 1,
        "slug": "eth-up-or-down",
        "stableSlug": "eth-15min-price",
        "title": "ETH Up or Down",
        "volumeFormatted": "123.45",
        "prices": [0.54, 0.46],
        "tradePrices": {
            "buy": {"limit": "0.57 0.49"},
            "sell": {"limit": "0.51 0.43"},
        },
        "metadata": {"isPolyArbitrage": True, "maxSpread": 0.065, "openPrice": "2500"},
    }

    row = scanner.normalize_market(market)

    assert row["slug"] == "eth-up-or-down"
    assert row["volume"] == 123.45
    assert row["yes_price"] == 0.54
    assert row["book"]["yes_bid"] == 0.51
    assert row["book"]["yes_ask"] == 0.57
    assert row["yes_spread"] == 0.06
    assert row["is_poly_arbitrage"] is True


def test_normalize_feed_event_extracts_wallet_and_usd() -> None:
    event = {
        "id": "evt-1",
        "timestamp": "2026-06-30T12:00:00Z",
        "data": {
            "tradeAmountUSD": "550.25",
            "wallet": "0xABC",
            "outcome": "YES",
            "side": "BUY",
        },
    }
    market = {"slug": "fed-market", "title": "Will Fed cut?"}

    row = scanner.normalize_feed_event(event, market)

    assert row is not None
    assert row["usd"] == 550.25
    assert row["wallet"] == "0xABC"
    assert row["wallet_url"].endswith("/0xabc")
    assert row["market_slug"] == "fed-market"


def test_scan_limitless_is_read_only_and_filters_whales(monkeypatch) -> None:
    markets = [
        {
            "id": 1,
            "slug": "big",
            "title": "Big Market",
            "volumeFormatted": "1000",
            "prices": [0.5, 0.5],
            "tradePrices": {"buy": {"limit": "0.6 0.55"}, "sell": {"limit": "0.4 0.45"}},
            "metadata": {"isPolyArbitrage": True},
        },
        {
            "id": 2,
            "slug": "small",
            "title": "Small Market",
            "volumeFormatted": "10",
            "prices": [0.5, 0.5],
        },
    ]
    events = {
        "big": [
            {"id": "1", "data": {"tradeAmountUSD": 250, "wallet": "0x1", "outcome": "YES"}},
            {"id": "2", "data": {"tradeAmountUSD": 25, "wallet": "0x2", "outcome": "NO"}},
        ],
        "small": [],
    }

    monkeypatch.setattr(scanner, "fetch_active_markets", lambda pages=1, page_limit=25: markets)
    monkeypatch.setattr(scanner, "fetch_feed_events", lambda slug, limit=100: events[slug])
    monkeypatch.setattr(scanner.time, "sleep", lambda _: None)

    report = scanner.scan_limitless(top=2, min_usd=100)

    assert report["mode"] == "read_only"
    assert report["execution_enabled"] is False
    assert report["markets_scanned"] == 2
    assert report["poly_arbitrage_count"] == 1
    assert report["whale_event_count"] == 1
    assert report["whale_events"][0]["usd"] == 250


def test_append_log_and_write_report(tmp_path) -> None:
    entry = {"provider": "limitless_market_scanner", "mode": "read_only"}
    log_path = tmp_path / "limitless.jsonl"
    report_path = tmp_path / "limitless.json"

    scanner.append_log(entry, log_path)
    scanner.write_report(entry, report_path)

    assert json.loads(log_path.read_text(encoding="utf-8").strip()) == entry
    assert json.loads(report_path.read_text(encoding="utf-8")) == entry

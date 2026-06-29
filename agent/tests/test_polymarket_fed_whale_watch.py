from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from strategies.polymarket_fed_whale_watch import PolymarketFedClient, build_fed_whale_report, discover_fed_markets


class FakeResponse:
    def __init__(self, payload):
        self.payload = payload

    def raise_for_status(self) -> None:
        return None

    def json(self):
        return self.payload


class FakeSession:
    def __init__(self):
        self.calls: list[dict] = []

    def get(self, url, **kwargs):
        self.calls.append({"url": url, **kwargs})
        if url.endswith("/events"):
            return FakeResponse([
                {
                    "slug": "fed-decision-in-july",
                    "markets": [
                        {
                            "conditionId": "0xfed",
                            "question": "Will the Fed decrease interest rates after July meeting?",
                            "slug": "fed-cut-july",
                            "active": True,
                            "closed": False,
                            "acceptingOrders": True,
                            "volume": "1000000",
                            "liquidity": "50000",
                            "outcomes": "[\"Yes\", \"No\"]",
                            "outcomePrices": "[\"0.42\", \"0.58\"]",
                        },
                        {
                            "conditionId": "0xnoise",
                            "question": "Will a celebrity release an album?",
                            "active": True,
                            "closed": False,
                        },
                    ],
                }
            ])
        if url.endswith("/trades"):
            return FakeResponse([
                {
                    "proxyWallet": "0xaaa",
                    "side": "BUY",
                    "size": 100000,
                    "price": 0.40,
                    "timestamp": 1780000000,
                    "title": "Will the Fed decrease interest rates after July meeting?",
                    "slug": "fed-cut-july",
                    "eventSlug": "fed-decision-in-july",
                    "outcome": "Yes",
                    "transactionHash": "0x1",
                },
                {
                    "proxyWallet": "0xbbb",
                    "side": "BUY",
                    "size": 150000,
                    "price": 0.50,
                    "timestamp": 1780000100,
                    "title": "Will the Fed decrease interest rates after July meeting?",
                    "slug": "fed-cut-july",
                    "eventSlug": "fed-decision-in-july",
                    "outcome": "Yes",
                    "transactionHash": "0x2",
                },
                {
                    "proxyWallet": "0xccc",
                    "side": "BUY",
                    "size": 400000,
                    "price": 0.40,
                    "timestamp": 1780000200,
                    "title": "Will the Fed decrease interest rates after July meeting?",
                    "slug": "fed-cut-july",
                    "eventSlug": "fed-decision-in-july",
                    "outcome": "Yes",
                    "transactionHash": "0x3",
                },
                {
                    "proxyWallet": "0xsmall",
                    "side": "BUY",
                    "size": 10,
                    "price": 0.40,
                    "title": "Will the Fed decrease interest rates after July meeting?",
                    "outcome": "Yes",
                },
            ])
        raise AssertionError(f"unexpected URL {url}")


def test_discovers_fed_markets_from_event_slug() -> None:
    client = PolymarketFedClient(session=FakeSession())

    markets = discover_fed_markets(client, event_slugs=["fed-decision-in-july"])

    assert len(markets) == 1
    assert markets[0].condition_id == "0xfed"
    assert markets[0].prices == {"Yes": 0.42, "No": 0.58}


def test_fed_whale_report_builds_read_only_consensus(tmp_path) -> None:
    client = PolymarketFedClient(session=FakeSession())
    profiles = tmp_path / "profiles.json"
    profiles.write_text("[]", encoding="utf-8")

    report = build_fed_whale_report(
        client=client,
        event_slugs=["fed-decision-in-july"],
        min_trade_notional=10_000,
        consensus_notional=250_000,
        min_whales=3,
        profiles_path=profiles,
    )

    assert report["mode"] == "read_only"
    assert report["execution_enabled"] is False
    assert report["markets_scanned"] == 1
    assert report["whale_trade_count"] == 3
    assert report["consensus_count"] == 1
    assert report["consensus"][0]["action"] == "paper_watch"
    assert report["consensus"][0]["total_notional"] == 275000.0

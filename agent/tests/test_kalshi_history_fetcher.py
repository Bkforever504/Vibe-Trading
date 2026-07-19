from __future__ import annotations

import csv
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from strategies.kalshi_history_fetcher import (
    KalshiHistoryClient,
    build_fills_report,
    fill_to_trade_row,
    fills_to_csv,
    upsert_kalshi_profile,
)


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
        return FakeResponse(
            {
                "fills": [
                    {
                        "created_time": "2026-01-15T14:30:00Z",
                        "ticker": "HIGHNY-26JAN15-B72",
                        "market_ticker": "HIGHNY-26JAN15-B72",
                        "side": "yes",
                        "action": "buy",
                        "count": 10,
                        "yes_price": 42,
                        "fee_cents": 4,
                        "realized_pnl_cents": 280,
                    }
                ],
                "cursor": "",
            }
        )


def test_kalshi_history_client_fetches_signed_portfolio_fills() -> None:
    session = FakeSession()
    client = KalshiHistoryClient(
        key_id="key-123",
        private_key_pem="PRIVATE",
        session=session,
        signer=lambda key_id, pem, method, path: {"KALSHI-ACCESS-KEY": key_id, "SIGNED-PATH": path},
    )

    fills = client.fetch_fills(limit=100)

    assert len(fills) == 1
    assert session.calls[0]["url"].endswith("/portfolio/fills")
    assert session.calls[0]["params"]["limit"] == 100
    assert session.calls[0]["headers"]["KALSHI-ACCESS-KEY"] == "key-123"
    assert session.calls[0]["headers"]["SIGNED-PATH"] == "/trade-api/v2/portfolio/fills"


def test_fill_to_trade_row_normalizes_dollars_for_importer() -> None:
    row = fill_to_trade_row(
        {
            "created_time": "2026-01-15T14:30:00Z",
            "ticker": "HIGHNY-26JAN15-B72",
            "side": "yes",
            "count": 10,
            "yes_price": 42,
            "fee_cents": 4,
            "realized_pnl_cents": 280,
        }
    )

    assert row["date"] == "2026-01-15"
    assert row["market"] == "HIGHNY-26JAN15-B72"
    assert row["profit_loss"] == 2.8
    assert row["fee"] == 0.04
    assert row["notional"] == 4.2


def test_fill_to_trade_row_supports_current_fixed_point_fields() -> None:
    row = fill_to_trade_row(
        {
            "created_time": "2026-07-15T12:00:00Z",
            "ticker": "KXHIGHNY-26JUL16-B93.5",
            "side": "yes",
            "action": "buy",
            "count_fp": "2.00",
            "yes_price_dollars": "0.3000",
            "fee_cost": "0.0400",
        }
    )

    assert row["contracts"] == 2.0
    assert row["price"] == 0.30
    assert row["notional"] == 0.60
    assert row["fee"] == 0.04


def test_fills_to_csv_writes_importable_generic_history(tmp_path) -> None:
    out = tmp_path / "kalshi_fills.csv"

    fills_to_csv(
        [
            {
                "created_time": "2026-01-15T14:30:00Z",
                "ticker": "HIGHNY-26JAN15-B72",
                "side": "yes",
                "count": 10,
                "yes_price": 42,
                "fee_cents": 4,
                "realized_pnl_cents": 280,
            }
        ],
        out,
    )

    with out.open(newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    assert rows[0]["market"] == "HIGHNY-26JAN15-B72"
    assert rows[0]["profit_loss"] == "2.8"


def test_build_report_and_upsert_profile_are_read_only(tmp_path) -> None:
    fills = []
    for month in range(1, 7):
        fills.append(
            {
                "created_time": f"2026-{month:02d}-15T14:30:00Z",
                "ticker": f"WEATHER-{month}",
                "side": "yes",
                "count": 10,
                "yes_price": 40,
                "fee_cents": 2,
                "realized_pnl_cents": 200 + month,
            }
        )
    report = build_fills_report(fills, handle="kenny_kalshi")
    profiles = tmp_path / "profiles.json"

    profile = upsert_kalshi_profile(report, profiles_path=profiles)

    saved = json.loads(profiles.read_text(encoding="utf-8"))
    assert report["mode"] == "read_only"
    assert report["execution_enabled"] is False
    assert report["trades"] == 6
    assert profile.handle == "kenny_kalshi"
    assert saved[0]["platform"] == "kalshi"
    assert saved[0]["category"] == "prediction_market"

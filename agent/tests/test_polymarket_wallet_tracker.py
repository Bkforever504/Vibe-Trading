from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from strategies.copy_trader_watchlist import profile_from_dict, score_trader
from strategies.polymarket_wallet_tracker import (
    PolymarketPublicClient,
    build_wallet_report,
    fetch_wallet_trades,
    upsert_wallet_profile,
    wallet_to_csv,
)


class FakeResponse:
    def __init__(self, payload, status_code: int = 200):
        self.payload = payload
        self.status_code = status_code

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")

    def json(self):
        return self.payload


class FakeSession:
    def __init__(self):
        self.calls: list[dict] = []

    def get(self, url, **kwargs):
        self.calls.append({"url": url, **kwargs})
        if "activity" in url:
            return FakeResponse(
                {
                    "data": [
                        {
                            "timestamp": 1780246800,
                            "market": "Fed cuts by September?",
                            "outcome": "YES",
                            "side": "BUY",
                            "size": 120,
                            "price": 0.42,
                            "profit_loss": 14.5,
                            "fee": 0.1,
                        }
                    ]
                }
            )
        if "closed-positions" in url:
            rows = []
            for month, pnl in enumerate([25, 30, 22, 28, 35, 18], start=1):
                rows.append(
                    {
                        "timestamp": datetime(2026, month, 15, tzinfo=timezone.utc).timestamp(),
                        "market": f"Macro market {month}",
                        "outcome": "YES",
                        "realized_pnl": pnl,
                        "size": 100,
                        "avgPrice": 0.5,
                    }
                )
            return FakeResponse({"data": rows})
        raise AssertionError(f"unexpected url: {url}")


def test_fetch_wallet_trades_uses_public_get_without_auth_headers() -> None:
    session = FakeSession()
    client = PolymarketPublicClient(session=session)

    trades = fetch_wallet_trades("0xabc", limit=50, client=client)

    assert len(trades) == 1
    assert session.calls[0]["url"].endswith("/activity")
    assert session.calls[0]["params"]["user"] == "0xabc"
    assert "headers" not in session.calls[0] or not session.calls[0]["headers"]


def test_wallet_report_uses_activity_as_primary_source() -> None:
    # Activity data is preferred over closed-positions to avoid survivorship bias:
    # /closed-positions only returns winning resolved positions, producing 100% win rate.
    client = PolymarketPublicClient(session=FakeSession())

    report = build_wallet_report(["0xabc"], client=client)

    assert report["mode"] == "read_only"
    assert report["execution_enabled"] is False
    wallet = report["wallets"][0]
    assert wallet["handle"] == "0xabc"
    assert wallet["source"] == "public_wallet"
    assert wallet["trades"] == 1          # from activity (1 row), not closed-positions (6)
    assert wallet["realized_pnl"] == 14.5 # from activity profit_loss field
    assert wallet["raw_activity_count"] == 1
    assert wallet["closed_position_count"] == 6
    assert wallet["data_source"] == "data-api/activity"
    assert wallet["data_quality"] == "primary_all_activity"
    assert wallet["closed_positions_survivorship_warning"] is False
    assert wallet["endpoint_attempts"][0]["endpoint"] == "activity"


class ActivityErrorClobSession:
    def __init__(self):
        self.calls: list[dict] = []

    def get(self, url, **kwargs):
        self.calls.append({"url": url, **kwargs})
        if "activity" in url:
            return FakeResponse({"error": "blocked"}, status_code=500)
        if "trades" in url:
            return FakeResponse(
                {
                    "data": [
                        {
                            "timestamp": 1780246800,
                            "market": "Fed cuts by September?",
                            "outcome": "YES",
                            "size": 100,
                            "price": 0.4,
                            "profit_loss": -5,
                        }
                    ]
                }
            )
        if "closed-positions" in url:
            return FakeResponse({"data": []})
        raise AssertionError(f"unexpected url: {url}")


def test_wallet_report_falls_back_to_clob_with_diagnostics() -> None:
    client = PolymarketPublicClient(session=ActivityErrorClobSession())

    report = build_wallet_report(["0xabc"], client=client)
    wallet = report["wallets"][0]

    assert wallet["trades"] == 1
    assert wallet["realized_pnl"] == -5
    assert wallet["data_source"] == "clob/trades"
    assert wallet["data_quality"] == "fallback_clob_trades"
    assert wallet["endpoint_attempts"][0]["status"] == "error"
    assert wallet["endpoint_attempts"][1]["endpoint"] == "trades"


def test_closed_position_total_bought_counts_as_notional() -> None:
    from strategies.polymarket_wallet_tracker import _row_to_closed_position_trade

    trade = _row_to_closed_position_trade(
        {
            "timestamp": 1772845557,
            "title": "Will Real Madrid CF win?",
            "outcome": "Yes",
            "avgPrice": 0.3649,
            "totalBought": 1120614.676954,
            "realizedPnl": 711702.381299,
        }
    )

    assert trade.notional == 1120614.676954
    assert trade.pnl == 711702.381299


def test_wallet_to_csv_matches_trade_history_importer_polymarket_shape(tmp_path) -> None:
    client = PolymarketPublicClient(session=FakeSession())
    out = tmp_path / "wallet.csv"

    wallet_to_csv("0xabc", out, client=client)

    text = out.read_text(encoding="utf-8")
    assert text.splitlines()[0] == "timestamp,market,outcome,shares,price,profit_loss,fee"
    assert "Fed cuts by September?" in text


def test_upsert_wallet_profile_feeds_copy_trader_scoring(tmp_path) -> None:
    client = PolymarketPublicClient(session=FakeSession())
    report = build_wallet_report(["0xabc"], client=client)
    profiles = tmp_path / "profiles.json"

    profile = upsert_wallet_profile(report["wallets"][0], profiles_path=profiles)

    data = json.loads(profiles.read_text(encoding="utf-8"))
    scored = score_trader(profile_from_dict(data[0]))
    assert profile.handle == "0xabc"
    assert data[0]["platform"] == "polymarket"
    assert data[0]["category"] == "prediction_market"
    assert scored.status in {"paper_watch", "review"}

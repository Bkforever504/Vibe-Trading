import json
from pathlib import Path

from strategies.kalshi_profile_scraper import (
    KalshiProfileClient,
    build_profile_report,
    holding_to_trades,
    upsert_kalshi_public_profile,
)


class FakeResponse:
    def __init__(self, payload):
        self.payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self.payload


class FakeSession:
    def __init__(self):
        self.calls = []

    def get(self, url, params=None, headers=None, timeout=None):
        self.calls.append({"url": url, "params": params, "headers": headers, "timeout": timeout})
        if url.endswith("/social/profile/metrics"):
            return FakeResponse(
                {
                    "metrics": {
                        "pnl": 1234500,
                        "num_markets_traded": 3,
                        "volume": 5000,
                    },
                    "social_id": "social-1",
                }
            )
        if url.endswith("/social/profile/holdings"):
            return FakeResponse(
                {
                    "holdings": [
                        {
                            "event_ticker": "KXTEST-26JUN26",
                            "series_ticker": "KXTEST",
                            "total_absolute_position": 15,
                            "market_holdings": [
                                {
                                    "market_ticker": "KXTEST-26JUN26-YES",
                                    "signed_open_position": 10,
                                    "pnl": 250000,
                                },
                                {
                                    "market_ticker": "KXTEST-26JUN26-NO",
                                    "signed_open_position": -5,
                                    "pnl": -50000,
                                },
                            ],
                        }
                    ],
                    "cursor": None,
                    "visibility_state": "visible",
                }
            )
        raise AssertionError(f"unexpected URL: {url}")


def test_holding_to_trades_uses_closed_position_pnl_and_event_date():
    holding = {
        "event_ticker": "KXHIGHTSATX-26JUN26-B92.5",
        "market_holdings": [
            {
                "market_ticker": "KXHIGHTSATX-26JUN26-B92.5",
                "signed_open_position": -12,
                "pnl": -208800,
            }
        ],
    }

    trades = holding_to_trades(holding)

    assert len(trades) == 1
    assert trades[0].date == "2026-06-26"
    assert trades[0].symbol == "KXHIGHTSATX-26JUN26-B92.5"
    assert trades[0].pnl == -20.88
    assert trades[0].notional == 12


def test_build_profile_report_uses_public_endpoints_and_closed_position_win_rate():
    client = KalshiProfileClient(session=FakeSession())

    report = build_profile_report("weatherman.allday", client=client)

    assert report["handle"] == "weatherman.allday"
    assert report["platform"] == "kalshi"
    assert report["source"] == "public_profile"
    assert report["visibility_state"] == "visible"
    assert report["trades"] == 2
    assert report["win_rate"] == 0.5
    assert report["realized_pnl"] == 20.0
    assert report["public_metrics"]["pnl"] == 123.45


def test_upsert_kalshi_public_profile_marks_public_profile_verified(tmp_path: Path):
    profiles_path = tmp_path / "profiles.json"
    report = {
        "handle": "weatherman.allday",
        "platform": "kalshi",
        "source": "public_profile",
        "category": "prediction_market",
        "trades": 2,
        "win_rate": 0.5,
        "realized_pnl": 20.0,
        "max_drawdown_pct": 0.2,
        "profit_factor": 5.0,
    }

    profile = upsert_kalshi_public_profile(report, profiles_path=profiles_path)
    data = json.loads(profiles_path.read_text(encoding="utf-8"))

    assert profile.handle == "weatherman.allday"
    assert data[0]["verified"] is True
    assert data[0]["source"] == "public_profile"

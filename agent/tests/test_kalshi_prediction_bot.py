from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def test_kalshi_settings_defaults_to_demo_and_paper_only(monkeypatch) -> None:
    from strategies.kalshi_prediction_bot import KalshiSettings

    for key in ("KALSHI_ENV", "KALSHI_ENABLE_LIVE_TRADING"):
        monkeypatch.delenv(key, raising=False)

    settings = KalshiSettings.from_env()

    assert settings.env == "demo"
    assert settings.paper_only is True
    assert settings.base_url == "https://external-api.demo.kalshi.co/trade-api/v2"


def test_kalshi_opportunity_scores_wide_orderbook_discount() -> None:
    from strategies.kalshi_prediction_bot import MarketSnapshot, score_market

    market = MarketSnapshot(
        ticker="KXTEST-YES",
        title="Will test market resolve yes?",
        category="financials",
        close_time="2026-07-01T16:00:00Z",
        yes_bid=0.42,
        yes_ask=0.47,
        no_bid=0.51,
        no_ask=0.56,
        volume=250_000,
        liquidity=12_000,
        open_interest=50_000,
    )

    opportunity = score_market(market, fair_yes=0.55, source="model")

    assert opportunity is not None
    assert opportunity.side == "YES"
    assert opportunity.edge == 0.08
    assert opportunity.max_risk_dollars == 25.0
    assert opportunity.confidence >= 8
    assert "fair value edge" in opportunity.reason


def test_kalshi_report_is_paper_only_and_serializable(tmp_path) -> None:
    from strategies.kalshi_prediction_bot import MarketSnapshot, build_report, write_report

    report = build_report(
        [
            MarketSnapshot(
                ticker="KXTEST-YES",
                title="Will test market resolve yes?",
                category="financials",
                close_time="2026-07-01T16:00:00Z",
                yes_bid=0.42,
                yes_ask=0.47,
                no_bid=0.51,
                no_ask=0.56,
                volume=250_000,
                liquidity=12_000,
                open_interest=50_000,
            )
        ],
        fair_values={"KXTEST-YES": 0.55},
    )
    out = tmp_path / "kalshi-prediction-report.json"

    write_report(report, out)
    saved = json.loads(out.read_text(encoding="utf-8"))

    assert saved["mode"] == "paper_only"
    assert saved["execution_enabled"] is False
    assert saved["opportunities"][0]["ticker"] == "KXTEST-YES"
    assert saved["opportunities"][0]["confidence"] >= 8


def test_kalshi_client_fetches_markets_and_orderbooks_without_auth() -> None:
    from strategies.kalshi_prediction_bot import KalshiClient, KalshiSettings

    class Response:
        def __init__(self, payload: dict) -> None:
            self.payload = payload

        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict:
            return self.payload

    class Session:
        def __init__(self) -> None:
            self.calls: list[tuple[str, dict]] = []

        def get(self, url: str, **kwargs: object) -> Response:
            self.calls.append((url, kwargs))
            if url.endswith("/markets"):
                return Response(
                    {
                        "markets": [
                            {
                                "ticker": "KXTEST-YES",
                                "title": "Will test market resolve yes?",
                                "status": "active",
                                "volume": 250000,
                            }
                        ]
                    }
                )
            return Response({"orderbook": {"yes": [[42, 100]], "no": [[51, 100]]}})

    session = Session()
    client = KalshiClient(KalshiSettings(), session=session)

    markets = client.fetch_market_snapshots(limit=1)

    assert markets[0].ticker == "KXTEST-YES"
    assert markets[0].yes_bid == 0.42
    assert markets[0].yes_ask == 0.49
    assert all("headers" not in call[1] for call in session.calls)
    assert session.calls[0][1]["params"]["status"] == "open"


def test_kalshi_current_fixed_point_orderbook_schema() -> None:
    from strategies.kalshi_prediction_bot import market_from_api

    snapshot = market_from_api(
        {
            "ticker": "KXHIGHNY-26JUL16-B93.5",
            "title": "NYC high temp",
            "volume_fp": "4688.95",
            "open_interest_fp": "4349.16",
            "liquidity_dollars": "125.50",
        },
        {
            "yes_dollars": [["0.2800", "20.00"]],
            "no_dollars": [["0.7000", "15.00"]],
        },
    )

    assert snapshot.yes_bid == 0.28
    assert snapshot.yes_ask == 0.30
    assert snapshot.no_bid == 0.70
    assert snapshot.no_ask == 0.72
    assert snapshot.volume == 4688.95
    assert snapshot.open_interest == 4349.16
    assert snapshot.liquidity == 125.50


def test_kalshi_run_scan_writes_report_with_supplied_fair_values(tmp_path) -> None:
    from strategies.kalshi_prediction_bot import MarketSnapshot, run_scan

    class Client:
        def fetch_market_snapshots(self, *, limit: int = 25) -> list[MarketSnapshot]:
            return [
                MarketSnapshot(
                    ticker="KXTEST-YES",
                    title="Will test market resolve yes?",
                    yes_bid=0.42,
                    yes_ask=0.47,
                    no_bid=0.51,
                    no_ask=0.56,
                    volume=250_000,
                    liquidity=12_000,
                )
            ]

    out = tmp_path / "report.json"

    report = run_scan(client=Client(), fair_values={"KXTEST-YES": 0.55}, out=out, limit=1)

    assert report["markets_scanned"] == 1
    assert report["opportunities"][0]["ticker"] == "KXTEST-YES"
    assert json.loads(out.read_text(encoding="utf-8"))["execution_enabled"] is False


def test_weather_consensus_requires_sources_within_one_and_half_degrees() -> None:
    from strategies.kalshi_prediction_bot import weather_consensus_fair_temperature

    consensus = weather_consensus_fair_temperature(
        {"open_meteo": 85.0, "nws": 86.1, "actual_weather": 85.8}
    )

    assert consensus is not None
    assert consensus["allowed"] is True
    assert consensus["fair_temperature"] == 85.6
    assert consensus["source_range"] == 1.1

    rejected = weather_consensus_fair_temperature({"open_meteo": 85.0, "nws": 88.0})

    assert rejected is not None
    assert rejected["allowed"] is False
    assert "sources disagree" in rejected["reason"]


def test_trading_dashboard_renders_kalshi_panel(tmp_path) -> None:
    from strategies.trading_dashboard import kalshi_context, kalshi_panel

    report = tmp_path / "kalshi-prediction-report.json"
    report.write_text(
        json.dumps(
            {
                "provider": "kalshi",
                "mode": "paper_only",
                "execution_enabled": False,
                "markets_scanned": 12,
                "opportunities": [
                    {
                        "ticker": "KXTEST-YES",
                        "title": "Will test market resolve yes?",
                        "side": "YES",
                        "entry_price": 0.47,
                        "fair_value": 0.55,
                        "edge": 0.08,
                        "confidence": 8,
                        "max_risk_dollars": 25.0,
                        "reason": "fair value edge",
                    }
                ],
                "warnings": ["Paper-only: no Kalshi order submission is implemented."],
            }
        ),
        encoding="utf-8",
    )

    context = kalshi_context(report)
    html = kalshi_panel(context)

    assert context["available"] is True
    assert context["top_opportunities"][0]["ticker"] == "KXTEST-YES"
    assert "Kalshi Prediction Lab" in html
    assert "KXTEST-YES" in html
    assert "Paper-only" in html

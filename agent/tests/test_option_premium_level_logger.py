from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts import option_premium_level_logger as logger


def test_parse_occ_symbol() -> None:
    parsed = logger.parse_occ_symbol("SPY260716C00752000")
    assert parsed == {
        "underlying": "SPY",
        "expiry": "2026-07-16",
        "right": "CALL",
        "strike": 752.0,
    }
    assert logger.parse_occ_symbol("not-an-option") is None


def test_aggregate_premium_levels_ranks_executed_premium_by_strike() -> None:
    trades = {
        "SPY260716C00752000": [
            {"p": 1.0, "s": 10, "t": "2026-07-16T14:00:00Z", "c": ["A"]},
            {"p": 1.2, "s": 5, "t": "2026-07-16T14:01:00Z", "c": []},
        ],
        "SPY260716C00753000": [{"p": 2.0, "s": 3, "t": "2026-07-16T14:02:00Z"}],
        "SPY260716P00750000": [{"p": 0.5, "s": 20, "t": "2026-07-16T14:03:00Z"}],
    }

    levels = logger.aggregate_premium_levels(trades, top_n=4)

    assert [row["underlying_level"] for row in levels["CALL"]] == [752.0, 753.0]
    assert levels["CALL"][0]["total_premium_dollars"] == 1600.0
    assert levels["CALL"][0]["contracts_traded"] == 15
    assert levels["CALL"][0]["vwap_option_price"] == 1.0667
    assert levels["PUT"][0]["total_premium_dollars"] == 1000.0


def test_aggregate_premium_levels_ignores_invalid_prints() -> None:
    levels = logger.aggregate_premium_levels(
        {"SPY260716C00752000": [{"p": 0, "s": 5}, {"p": 1.0, "s": 0}, {"p": "bad", "s": 2}]}
    )
    assert levels == {"CALL": [], "PUT": []}


def test_report_fails_closed_without_credentials(monkeypatch) -> None:
    monkeypatch.setenv("ALPACA_API_KEY", "")
    monkeypatch.setenv("ALPACA_SECRET_KEY", "")

    report = logger.build_report(["SPY"])

    assert report["status"] == "credentials_missing"
    assert report["execution_enabled"] is False
    assert report["can_submit_orders"] is False


def test_unverified_feed_cannot_claim_provenance(monkeypatch) -> None:
    monkeypatch.setenv("ALPACA_API_KEY", "")
    monkeypatch.setenv("ALPACA_SECRET_KEY", "")
    monkeypatch.setenv("OPTION_PREMIUM_DATA_FEED", "indicative")

    report = logger.build_report(["SPY"])

    assert report["feed_provenance"] == "indicative"
    assert report["provenance_qualified"] is False


def test_trade_fetch_pages_each_contract_independently(monkeypatch) -> None:
    calls: list[str] = []

    def fake_get_json(_session, _url, *, params):
        symbol = params["symbols"]
        calls.append(symbol)
        return {"trades": {symbol: [{"p": 1.0, "s": 1}]}, "next_page_token": None}

    monkeypatch.setattr(logger, "_get_json", fake_get_json)
    symbols = ["SPY260716C00752000", "SPY260716P00750000"]

    trades, truncated = logger.fetch_option_trades(
        object(),
        symbols,
        datetime(2026, 7, 16, 13, 30, tzinfo=timezone.utc),
        datetime(2026, 7, 16, 14, 30, tzinfo=timezone.utc),
    )

    assert calls == symbols
    assert set(trades) == set(symbols)
    assert truncated == []

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from scripts import options_shadow_twin as twin
from scripts import point_in_time_quotes as pit
from scripts import tradier_options_data as tradier
from strategies import iwm_options_bot as bot


def _tradier_row(symbol: str, captured_at: datetime) -> dict:
    bid_at = captured_at - timedelta(seconds=4)
    ask_at = captured_at - timedelta(seconds=2)
    return {
        "symbol": symbol,
        "type": "option",
        "bid": 1.20,
        "ask": 1.30,
        "bidsize": 10,
        "asksize": 12,
        "bidexch": "W",
        "askexch": "Z",
        "bid_date": int(bid_at.timestamp() * 1000),
        "ask_date": int(ask_at.timestamp() * 1000),
        "last": 1.25,
        "last_volume": 2,
        "trade_date": int((captured_at - timedelta(seconds=3)).timestamp() * 1000),
        "volume": 500,
        "open_interest": 1000,
        "greeks": {
            "delta": -0.25,
            "gamma": 0.02,
            "theta": -0.03,
            "vega": 0.08,
            "rho": -0.01,
            "mid_iv": 0.27,
            "updated_at": "2026-08-03 14:00:00",
        },
    }


def test_normalize_quote_uses_older_side_timestamp_and_is_fresh() -> None:
    captured_at = datetime(2026, 8, 3, 15, 0, tzinfo=timezone.utc)
    parsed = tradier.normalize_quote(_tradier_row("IWM260821P00200000", captured_at), captured_at)

    assert parsed["quote"]["bid"] == pytest.approx(1.20)
    assert parsed["quote"]["ask"] == pytest.approx(1.30)
    assert parsed["quote"]["quote_age_seconds"] == pytest.approx(4.0)
    assert parsed["provenance"]["provider"] == tradier.PROVIDER_TRADIER
    assert parsed["provenance"]["quote_scope"] == tradier.TRADIER_QUOTE_SCOPE
    assert parsed["provenance"]["status"] == "ok"
    assert tradier.quote_is_fresh(parsed, max_age_seconds=5)


def test_fetch_quotes_batches_and_never_places_orders(monkeypatch) -> None:
    captured_at = datetime(2026, 8, 3, 15, 0, tzinfo=timezone.utc)
    calls = []

    class Response:
        status_code = 200
        headers = {"X-Ratelimit-Available": "119"}

        def __init__(self, symbols: list[str]):
            self.symbols = symbols

        def json(self):
            return {"quotes": {"quote": [_tradier_row(symbol, captured_at) for symbol in self.symbols]}}

    def fake_get(url, **kwargs):
        symbols = kwargs["params"]["symbols"].split(",")
        calls.append((url, kwargs))
        return Response(symbols)

    quotes, meta = tradier.fetch_quotes_with_meta(
        ["IWM1", "IWM2", "IWM3"],
        token="secret-token",
        request_get=fake_get,
        batch_size=2,
        captured_at=captured_at,
    )

    assert sorted(quotes) == ["IWM1", "IWM2", "IWM3"]
    assert len(calls) == 2
    assert all(call[0] == tradier.TRADIER_QUOTES_URL for call in calls)
    assert all(call[1]["headers"]["Authorization"] == "Bearer secret-token" for call in calls)
    assert meta["received_symbols"] == 3
    assert "secret-token" not in str(meta)


def test_fetch_quotes_requires_production_token(monkeypatch) -> None:
    monkeypatch.delenv("TRADIER_ACCESS_TOKEN", raising=False)
    with pytest.raises(tradier.TradierDataError, match="TRADIER_ACCESS_TOKEN"):
        tradier.fetch_quotes_with_meta(["IWM"])


def test_iwm_latest_quotes_uses_tradier_without_alpaca_fallback(monkeypatch) -> None:
    parsed = {
        "quote": {"bid": 1.0, "ask": 1.1, "quote_timestamp": "2026-08-03T15:00:00Z"},
        "provenance": {"status": "partial"},
    }
    monkeypatch.setattr(bot, "tradier_selected", lambda: True)
    monkeypatch.setattr(bot, "fetch_tradier_quotes", lambda symbols: {"IWM1": parsed})
    monkeypatch.setattr(bot, "tradier_quote_is_fresh", lambda value: value is parsed)

    class AlpacaMustNotRun:
        def get_option_latest_quote(self, _request):
            raise AssertionError("Alpaca fallback must not run")

    quotes = bot._latest_option_quotes(AlpacaMustNotRun(), ["IWM1", "IWM2"])

    assert quotes == {
        "IWM1": {
            "bid": 1.0,
            "ask": 1.1,
            "timestamp": "2026-08-03T15:00:00Z",
            "provider": tradier.PROVIDER_TRADIER,
            "quote_scope": tradier.TRADIER_QUOTE_SCOPE,
        }
    }


def test_iwm_chain_overlays_fresh_tradier_bid_ask(monkeypatch) -> None:
    option_symbol = "IWM260821P00200000"
    snapshot = SimpleNamespace(
        greeks=SimpleNamespace(delta=-0.25),
        latest_quote=SimpleNamespace(bid_price=0.10, ask_price=9.90, timestamp="indicative"),
        implied_volatility=0.30,
    )
    parsed = {
        "quote": {
            "bid": 1.20,
            "ask": 1.30,
            "quote_timestamp": "2026-08-03T15:00:00Z",
        },
        "provenance": {"status": "partial"},
    }
    monkeypatch.setattr(bot, "tradier_selected", lambda: True)
    monkeypatch.setattr(bot, "fetch_tradier_quotes", lambda symbols: {option_symbol: parsed})
    monkeypatch.setattr(bot, "tradier_quote_is_fresh", lambda value: value is parsed)

    class Client:
        def get_option_chain(self, _request):
            return {option_symbol: snapshot}

    legs = bot._fetch_chain(Client(), "IWM", 7, 30, "put")

    assert len(legs) == 1
    assert legs[0].bid == pytest.approx(1.20)
    assert legs[0].ask == pytest.approx(1.30)
    assert legs[0].quote_provider == tradier.PROVIDER_TRADIER
    assert legs[0].quote_scope == tradier.TRADIER_QUOTE_SCOPE


def test_shadow_marks_use_tradier_and_drop_stale_quotes(monkeypatch) -> None:
    fresh = {
        "quote": {"bid": 1.0, "ask": 1.1, "quote_timestamp": "2026-08-03T15:00:00Z"},
        "provenance": {"status": "partial", "quote_scope": tradier.TRADIER_QUOTE_SCOPE},
    }
    stale = {
        "quote": {"bid": 0.5, "ask": 0.6, "quote_timestamp": "2026-08-01T15:00:00Z"},
        "provenance": {"status": "partial", "quote_scope": tradier.TRADIER_QUOTE_SCOPE},
    }
    candidate = {"legs": [{"symbol": "IWM1"}, {"symbol": "IWM2"}]}
    monkeypatch.setattr(twin, "tradier_selected", lambda: True)
    monkeypatch.setattr(twin, "fetch_tradier_quotes", lambda symbols: {"IWM1": fresh, "IWM2": stale})
    monkeypatch.setattr(twin, "tradier_quote_is_fresh", lambda value: value is fresh)

    assert twin._default_quote_map([candidate]) == {"IWM1": fresh}


def test_lifecycle_capture_records_tradier_provenance_without_alpaca_headers(
    monkeypatch, tmp_path
) -> None:
    captured_at = datetime.now(timezone.utc)
    parsed = tradier.normalize_quote(_tradier_row("IWM1", captured_at), captured_at)
    monkeypatch.setattr(pit, "configured_quote_provider", lambda: "tradier")
    monkeypatch.setattr(
        pit,
        "fetch_tradier_option_snapshot",
        lambda symbol: (parsed, {"http_status": 200, "endpoint": tradier.TRADIER_QUOTES_URL}),
    )
    monkeypatch.setattr(
        pit,
        "fetch_tradier_underlying_price",
        lambda symbol: {
            "symbol": symbol,
            "price": 225.0,
            "price_timestamp": "2026-08-03T15:00:00Z",
            "source": tradier.PROVIDER_TRADIER,
        },
    )

    record = pit.capture_lifecycle_sample(
        "monitor",
        "IWM1",
        bot="test",
        underlying_symbol="IWM",
        path=tmp_path / "quotes.jsonl",
    )

    assert record is not None
    assert record["provenance"]["provider"] == tradier.PROVIDER_TRADIER
    assert record["provenance"]["quote_scope"] == tradier.TRADIER_QUOTE_SCOPE
    assert record["underlying"]["source"] == tradier.PROVIDER_TRADIER

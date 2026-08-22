from __future__ import annotations

from datetime import datetime, timezone

from fastapi.testclient import TestClient

import api_server


def _local_client() -> TestClient:
    return TestClient(api_server.app, client=("127.0.0.1", 50000))


def _remote_client() -> TestClient:
    return TestClient(api_server.app, client=("203.0.113.10", 50000))


def _clear_cache() -> None:
    cache = getattr(api_server, "_TRADING_QUOTES_CACHE", None)
    if cache is not None:
        cache.clear()


def test_trading_quotes_is_auth_gated_read_only_and_cached(monkeypatch) -> None:
    _clear_cache()
    calls: list[tuple[str, ...]] = []
    quoted_at = datetime.now(timezone.utc).isoformat()

    def fake_fetch(symbols: tuple[str, ...]) -> dict:
        calls.append(symbols)
        return {
            "SPY": {"bp": 500.0, "ap": 500.2, "t": quoted_at},
            "QQQ": {"bp": 450.0, "ap": 450.4, "t": quoted_at},
        }

    monkeypatch.setattr(api_server, "_fetch_alpaca_latest_quotes", fake_fetch, raising=False)
    client = _local_client()

    first = client.get("/trading/quotes", params={"symbols": " spy,QQQ,SPY "})
    second = client.get("/trading/quotes", params={"symbols": "QQQ,SPY"})

    assert first.status_code == 200
    assert second.status_code == 200
    assert calls == [("QQQ", "SPY")]
    body = first.json()
    assert body["source"] == {"provider": "alpaca", "feed": "iex", "label": "alpaca_iex_latest_quote"}
    assert body["execution_enabled"] is False
    assert body["can_submit_orders"] is False
    assert body["quotes"]["SPY"]["price"] == 500.1
    assert body["quotes"]["SPY"]["bid"] == 500.0
    assert body["quotes"]["SPY"]["ask"] == 500.2
    assert body["quotes"]["SPY"]["stale"] is False
    assert body["quotes"]["SPY"]["execution_enabled"] is False
    assert body["quotes"]["SPY"]["can_submit_orders"] is False
    assert client.post("/trading/quotes", params={"symbols": "SPY"}).status_code == 405


def test_trading_quotes_requires_auth_for_remote_callers(monkeypatch) -> None:
    monkeypatch.setenv("API_AUTH_KEY", "secret")
    monkeypatch.setattr(api_server, "_API_KEY", "secret")

    assert _remote_client().get("/trading/quotes", params={"symbols": "SPY"}).status_code == 401


def test_trading_quotes_rejects_invalid_symbol(monkeypatch) -> None:
    monkeypatch.delenv("API_AUTH_KEY", raising=False)
    monkeypatch.setattr(api_server, "_API_KEY", "")

    response = _local_client().get("/trading/quotes", params={"symbols": "SPY,$BAD"})

    assert response.status_code == 400


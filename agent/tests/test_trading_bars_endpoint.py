from __future__ import annotations

from fastapi.testclient import TestClient

import api_server


def _local_client() -> TestClient:
    return TestClient(api_server.app, client=("127.0.0.1", 50000))


def _remote_client() -> TestClient:
    return TestClient(api_server.app, client=("203.0.113.10", 50000))


def _clear_cache() -> None:
    cache = getattr(api_server, "_TRADING_BARS_CACHE", None)
    if cache is not None:
        cache.clear()


def test_trading_bars_is_auth_gated_read_only_lightweight_shaped_and_cached(monkeypatch) -> None:
    _clear_cache()
    calls: list[tuple[str, str, int]] = []

    def fake_fetch(symbol: str, timeframe: str, limit: int) -> list[dict]:
        calls.append((symbol, timeframe, limit))
        return [
            {
                "t": "2026-08-20T14:30:00Z",
                "o": 500.0,
                "h": 501.0,
                "l": 499.5,
                "c": 500.5,
                "v": 12345,
            }
        ]

    monkeypatch.setattr(api_server, "_fetch_alpaca_bars", fake_fetch, raising=False)
    client = _local_client()

    first = client.get("/trading/bars", params={"symbol": " spy ", "tf": "5m", "limit": 200})
    second = client.get("/trading/bars", params={"symbol": "SPY", "tf": "5m", "limit": 200})

    assert first.status_code == 200
    assert second.status_code == 200
    assert calls == [("SPY", "5m", 200)]
    body = first.json()
    assert body["symbol"] == "SPY"
    assert body["tf"] == "5m"
    assert body["source"] == {"provider": "alpaca", "feed": "iex", "label": "alpaca_iex_bars"}
    assert body["execution_enabled"] is False
    assert body["can_submit_orders"] is False
    assert body["bars"] == [
        {
            "time": 1787236200,
            "open": 500.0,
            "high": 501.0,
            "low": 499.5,
            "close": 500.5,
            "volume": 12345.0,
        }
    ]
    assert client.post("/trading/bars", params={"symbol": "SPY"}).status_code == 405


def test_trading_bars_requires_auth_for_remote_callers(monkeypatch) -> None:
    monkeypatch.setenv("API_AUTH_KEY", "secret")
    monkeypatch.setattr(api_server, "_API_KEY", "secret")

    assert _remote_client().get("/trading/bars", params={"symbol": "SPY"}).status_code == 401


def test_trading_bars_rejects_invalid_timeframe(monkeypatch) -> None:
    monkeypatch.delenv("API_AUTH_KEY", raising=False)
    monkeypatch.setattr(api_server, "_API_KEY", "")

    response = _local_client().get("/trading/bars", params={"symbol": "SPY", "tf": "2m"})

    assert response.status_code == 400

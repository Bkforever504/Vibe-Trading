from __future__ import annotations

import importlib
import json

from fastapi.testclient import TestClient


def _load_api(monkeypatch):
    monkeypatch.setenv("API_AUTH_KEY", "test-secret")
    import api_server

    return importlib.reload(api_server)


def test_opportunity_endpoint_is_authenticated_and_read_only(monkeypatch, tmp_path) -> None:
    api_server = _load_api(monkeypatch)
    report_path = tmp_path / "live-opportunity-engine.json"
    report_path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "generated_at": "2026-08-21T14:10:00Z",
                "candidates": [],
                "execution_enabled": False,
                "can_submit_orders": False,
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(api_server, "_LIVE_OPPORTUNITY_REPORT", report_path)
    client = TestClient(api_server.app, client=("203.0.113.10", 50000))

    assert client.get("/trading/opportunities").status_code == 401
    response = client.get("/trading/opportunities", headers={"Authorization": "Bearer test-secret"})
    assert response.status_code == 200
    assert response.json()["execution_enabled"] is False
    assert response.json()["can_submit_orders"] is False
    assert client.post("/trading/opportunities", headers={"Authorization": "Bearer test-secret"}).status_code == 405


def test_feed_status_never_exposes_credentials(monkeypatch) -> None:
    api_server = _load_api(monkeypatch)
    monkeypatch.setenv("ALPACA_API_KEY", "should-never-appear")
    monkeypatch.setenv("ALPACA_SECRET_KEY", "also-secret")
    client = TestClient(api_server.app, client=("203.0.113.10", 50000))

    response = client.get("/trading/feed-status", headers={"Authorization": "Bearer test-secret"})

    assert response.status_code == 200
    payload = response.json()
    assert payload["execution_enabled"] is False
    assert payload["can_submit_orders"] is False
    assert "should-never-appear" not in json.dumps(payload)
    assert "also-secret" not in json.dumps(payload)

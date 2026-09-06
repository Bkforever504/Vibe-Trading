from __future__ import annotations

import json
from datetime import UTC, datetime

import pytest

from agent.data_providers.options_chain_router import OptionsChainRouter
from agent.data_providers.polygon_options_client import PolygonBudgetExceededError, PolygonOptionsClient


class FakeHTTPError(RuntimeError):
    def __init__(self, status_code: int) -> None:
        self.status_code = status_code
        super().__init__(f"HTTP {status_code}")


class FakeClient:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = 0

    def list_snapshot_options_chain(self, symbol, params=None):
        self.calls += 1
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


def write_budget(path, *, enabled=True, used=0.0, cap=29.0):
    path.write_text(json.dumps({
        "providers": {"polygon_options": {
            "enabled": enabled, "monthly_budget_usd": cap,
            "hard_cutoff_multiplier": 1.05, "current_month_cost_usd": used,
            "estimated_monthly_cost_usd": cap,
        }}
    }), encoding="utf-8")


def contract(ticker="O:SPY260906C00700000"):
    return {
        "details": {"ticker": ticker, "contract_type": "call", "strike_price": 700, "expiration_date": "2026-09-06"},
        "last_quote": {"bid": 1.0, "ask": 1.1, "last_updated": 123},
        "greeks": {"delta": 0.5}, "open_interest": 100, "day": {"volume": 20},
    }


def make_client(tmp_path, fake, **kwargs):
    budget = tmp_path / "budget.json"
    if not budget.exists():
        write_budget(budget)
    return PolygonOptionsClient(
        api_key="test-key", budget_path=budget, ledger_path=tmp_path / "ledger.jsonl",
        cost_dir=tmp_path / "costs", client_factory=lambda _: fake,
        sleeper=lambda _: None, now=lambda: datetime(2026, 9, 6, tzinfo=UTC), **kwargs,
    )


def test_missing_key_fails_honestly_without_http(tmp_path):
    fake = FakeClient([[contract()]])
    budget = tmp_path / "budget.json"
    write_budget(budget)
    client = PolygonOptionsClient(api_key="", budget_path=budget, ledger_path=tmp_path / "ledger", client_factory=lambda _: fake)
    result = client.fetch_chain("SPY")
    assert result["status"] == "not_configured"
    assert result["contracts"] == []
    assert fake.calls == 0
    assert json.loads((tmp_path / "ledger").read_text(encoding="utf-8"))["status"] == "not_configured"


def test_budget_cutoff_blocks_before_http(tmp_path):
    fake = FakeClient([[contract()]])
    budget = tmp_path / "budget.json"
    write_budget(budget, used=30.45)
    client = PolygonOptionsClient(api_key="key", budget_path=budget, ledger_path=tmp_path / "ledger", client_factory=lambda _: fake)
    with pytest.raises(PolygonBudgetExceededError):
        client.assert_budget_available()
    result = client.fetch_chain("SPY")
    assert result["status"] == "budget_exceeded"
    assert fake.calls == 0


def test_chain_is_normalized_hashed_and_cached(tmp_path):
    fake = FakeClient([[contract()]])
    client = make_client(tmp_path, fake)
    first = client.fetch_chain("spy", expiration_date="2026-09-06")
    second = client.fetch_chain("SPY", expiration_date="2026-09-06")
    assert first["status"] == "ok"
    assert first["contracts"][0]["bid"] == 1.0
    assert len(first["response_hash"]) == 64
    assert second["cached"] is True
    assert fake.calls == 1
    ledger = (tmp_path / "ledger.jsonl").read_text(encoding="utf-8")
    assert first["response_hash"] in ledger
    assert "last_quote" not in ledger


def test_429_retries_then_succeeds(tmp_path):
    fake = FakeClient([FakeHTTPError(429), [contract()]])
    client = make_client(tmp_path, fake)
    assert client.fetch_chain("SPY")["status"] == "ok"
    assert fake.calls == 2


def test_timeout_is_fail_honest_and_ledgers_null_hash(tmp_path):
    fake = FakeClient([TimeoutError("slow")])
    client = make_client(tmp_path, fake, max_attempts=1)
    result = client.fetch_chain("QQQ")
    assert result["status"] == "timeout"
    assert result["contracts"] == []
    row = json.loads((tmp_path / "ledger.jsonl").read_text(encoding="utf-8"))
    assert row["response_hash"] is None


def test_router_falls_back_and_preserves_attempts():
    class Provider:
        def __init__(self, result):
            self.result = result
        def fetch_chain(self, symbol, **params):
            return dict(self.result)

    router = OptionsChainRouter({
        "polygon": Provider({"status": "http_429", "contracts": []}),
        "alpaca": Provider({"status": "ok", "contracts": [contract()], "provider": "alpaca"}),
    }, ["polygon", "alpaca", "databento"])
    result = router.fetch_chain("SPY")
    assert result["provider"] == "alpaca"
    assert result["route_attempts"] == [
        {"provider": "polygon", "status": "http_429"},
        {"provider": "alpaca", "status": "ok"},
    ]
    assert result["execution_enabled"] is False


def test_weekly_cost_report_contains_configured_plan(tmp_path):
    client = make_client(tmp_path, FakeClient([[contract()]]))
    client.fetch_chain("SPY")
    report = json.loads(client.write_weekly_cost_report().read_text(encoding="utf-8"))
    assert report["configured_monthly_plan_usd"] == 29.0
    assert report["calls"] == 1

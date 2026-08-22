from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from scripts.alpaca_resilience import (
    AlpacaReadUnavailable,
    configure_sdk_client,
    read_with_retry,
)


def test_read_with_retry_recovers_and_records_health(tmp_path) -> None:
    health = tmp_path / "health.jsonl"
    calls = []

    def transient_read():
        calls.append(1)
        if len(calls) < 3:
            raise TimeoutError("temporary")
        return ["position"]

    result = read_with_retry(
        transient_read,
        component="test",
        operation="positions",
        attempts=3,
        backoff_seconds=0,
        health_path=health,
    )

    assert result == ["position"]
    assert len(calls) == 3
    event = json.loads(health.read_text(encoding="utf-8"))
    assert event["status"] == "recovered_after_retry"
    assert event["attempts"] == 3
    assert event["can_submit_orders"] is False


def test_read_with_retry_exhaustion_is_not_empty_state(tmp_path) -> None:
    health = tmp_path / "health.jsonl"

    with pytest.raises(AlpacaReadUnavailable):
        read_with_retry(
            lambda: (_ for _ in ()).throw(TimeoutError("down")),
            component="test",
            operation="positions",
            attempts=2,
            backoff_seconds=0,
            health_path=health,
        )

    event = json.loads(health.read_text(encoding="utf-8"))
    assert event["status"] == "exhausted"
    assert event["error_type"] == "TimeoutError"


def test_sdk_configuration_sets_timeout_and_get_only_retries() -> None:
    class Session:
        def __init__(self):
            self.adapters = {}
            self.calls = []

        def mount(self, prefix, adapter):
            self.adapters[prefix] = adapter

        def request(self, method, url, **kwargs):
            self.calls.append((method, url, kwargs))
            return SimpleNamespace(status_code=200)

    client = SimpleNamespace(_session=Session())
    configure_sdk_client(client, connect_timeout=2, read_timeout=7, transport_retries=2)

    client._session.request("GET", "https://example.test")

    assert client._session.calls[0][2]["timeout"] == (2, 7)
    retry = client._session.adapters["https://"].max_retries
    assert "GET" in retry.allowed_methods
    assert "POST" not in retry.allowed_methods
    assert client._session._alpaca_resilience_configured is True


def test_options_monitor_blocks_and_preserves_state_when_positions_unknown(monkeypatch, tmp_path) -> None:
    from strategies import iwm_options_bot as bot

    state_file = tmp_path / "options-trades.json"
    original = {"trades": [{"status": "open", "label": "IC", "legs": ["A", "B", "C", "D"]}]}
    state_file.write_text(json.dumps(original), encoding="utf-8")
    alerts = []

    monkeypatch.setattr(bot, "TRADE_STATE_FILE", state_file)
    monkeypatch.setattr(
        bot,
        "_broker_read",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AlpacaReadUnavailable("down")),
    )
    monkeypatch.setattr(bot, "_alert", lambda message: alerts.append(message))

    assert bot.monitor_and_close(SimpleNamespace(get_all_positions=lambda: [])) is False
    assert json.loads(state_file.read_text(encoding="utf-8")) == original
    assert "positions could not be confirmed" in alerts[0]


def test_flip_execution_sizing_fails_closed_but_shadow_can_continue(monkeypatch) -> None:
    from strategies import flip_bot

    monkeypatch.setattr(flip_bot, "ACCOUNT_OVERRIDE", 0)
    monkeypatch.setattr(flip_bot, "_fetch_alpaca_equity", lambda: 0.0)
    monkeypatch.setenv("FLIP_SHADOW_ACCOUNT_SIZE", "4200")

    with pytest.raises(AlpacaReadUnavailable):
        flip_bot.resolve_account_size()
    assert flip_bot.resolve_account_size(allow_research_fallback=True) == 5000.0

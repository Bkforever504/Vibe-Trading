from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd

from scripts import fetch_databento_options_nbbo as client


NOW = datetime(2026, 9, 4, 13, 0, tzinfo=timezone.utc)


def _spec(suffix: str = "00000000") -> client.RequestSpec:
    return client.RequestSpec(
        (f"SPY   260904C{suffix}",),
        "2026-09-04T12:59:00.000Z",
        "2026-09-04T13:00:00.000Z",
    )


class _Metadata:
    def __init__(self, billable_bytes: int = 1024):
        self.billable_bytes = billable_bytes
        self.calls = 0

    def get_billable_size(self, **_kwargs):
        self.calls += 1
        return self.billable_bytes


class _Store:
    def to_df(self):
        return pd.DataFrame(
            {
                "symbol": ["SPY   260904C00000000"],
                "bid_px_00": [1.20],
                "ask_px_00": [1.22],
                "bid_sz_00": [10],
                "ask_sz_00": [12],
            },
            index=pd.to_datetime(["2026-09-04T12:59:59Z"]),
        )


class _Timeseries:
    def __init__(self, error: BaseException | None = None):
        self.error = error
        self.calls = 0

    def get_range(self, **_kwargs):
        self.calls += 1
        if self.error:
            raise self.error
        return _Store()


class _Client:
    def __init__(self, *, billable_bytes: int = 1024, error: BaseException | None = None):
        self.metadata = _Metadata(billable_bytes)
        self.timeseries = _Timeseries(error)


def _rows(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def test_missing_key_is_not_configured_and_does_not_construct_client(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(client, "_configured_api_key", lambda: None)
    constructed = []

    result = client.fetch_options_nbbo(
        _spec("00000001"),
        client_factory=lambda _key: constructed.append(True),
        ledger_path=tmp_path / "ledger.jsonl",
        cache_dir=tmp_path / "cache",
        now=NOW,
    )

    assert result["status"] == "not_configured"
    assert result["rows"] == []
    assert constructed == []


def test_projected_daily_cost_blocks_data_fetch(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(client, "_configured_api_key", lambda: "configured")
    provider = _Client(billable_bytes=1024**3)
    ledger = tmp_path / "ledger.jsonl"

    result = client.fetch_options_nbbo(
        _spec("00000002"), client=provider, ledger_path=ledger, cache_dir=tmp_path / "cache",
        now=NOW, daily_budget=1.0,
    )

    assert result["status"] == "budget_exceeded"
    assert result["projected_cost_usd"] == 2.0
    assert provider.timeseries.calls == 0
    assert _rows(ledger)[0]["response_hash"] is None


def test_timeout_is_sanitized_logged_and_conservatively_reserved(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(client, "_configured_api_key", lambda: "configured")
    provider = _Client(billable_bytes=1024, error=TimeoutError("secret provider detail"))
    ledger = tmp_path / "ledger.jsonl"

    result = client.fetch_options_nbbo(
        _spec("00000003"), client=provider, ledger_path=ledger, cache_dir=tmp_path / "cache",
        now=NOW, daily_budget=5.0,
    )

    assert result["status"] == "timeout"
    assert result["error_class"] == "TimeoutError"
    assert "secret" not in json.dumps(result)
    assert result["billable"] is True
    assert _rows(ledger)[0]["status"] == "timeout"


def test_identical_request_within_sixty_seconds_uses_cache(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(client, "_configured_api_key", lambda: "configured")
    provider = _Client()
    ledger = tmp_path / "ledger.jsonl"
    cache = tmp_path / "cache"
    spec = _spec()

    first = client.fetch_options_nbbo(
        spec, client=provider, ledger_path=ledger, cache_dir=cache, now=NOW,
    )
    second = client.fetch_options_nbbo(
        spec, client=provider, ledger_path=ledger, cache_dir=cache,
        now=NOW + timedelta(seconds=59),
    )

    assert first["status"] == second["status"] == "ok"
    assert first["cache_hit"] is False
    assert second["cache_hit"] is True
    assert second["cost_usd"] == 0.0
    assert provider.timeseries.calls == 1
    assert len(_rows(ledger)) == 1


def test_daily_cost_accumulates_and_blocks_next_call(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(client, "_configured_api_key", lambda: "configured")
    # Each call costs $0.50 at the frozen $2/GiB rate.
    provider = _Client(billable_bytes=1024**3 // 4)
    ledger = tmp_path / "ledger.jsonl"
    cache = tmp_path / "cache"

    first = client.fetch_options_nbbo(
        _spec("00000004"), client=provider, ledger_path=ledger, cache_dir=cache,
        now=NOW, daily_budget=1.0,
    )
    second = client.fetch_options_nbbo(
        _spec("00000005"), client=provider, ledger_path=ledger, cache_dir=cache,
        now=NOW + timedelta(seconds=1), daily_budget=1.0,
    )
    blocked = client.fetch_options_nbbo(
        _spec("00000006"), client=provider, ledger_path=ledger, cache_dir=cache,
        now=NOW + timedelta(seconds=2), daily_budget=1.0,
    )

    assert first["daily_cost_usd"] == 0.5
    assert second["daily_cost_usd"] == 1.0
    assert blocked["status"] == "budget_exceeded"
    assert provider.timeseries.calls == 2
    assert client.daily_spend_usd(ledger, now=NOW) == 1.0


def test_success_ledger_has_auditable_metadata_without_raw_payload(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(client, "_configured_api_key", lambda: "configured")
    ledger = tmp_path / "ledger.jsonl"

    result = client.fetch_options_nbbo(
        _spec(), client=_Client(), ledger_path=ledger, cache_dir=tmp_path / "cache",
        now=NOW,
    )
    row = _rows(ledger)[0]

    assert result["status"] == "ok"
    assert row["requested_dataset"] == row["returned_dataset"] == "OPRA.PILLAR"
    assert row["requested_schema"] == row["returned_schema"] == "cbbo-1s"
    assert row["bytes"] == 1024
    assert len(row["response_hash"]) == 64
    assert "rows" not in row
    assert row["execution_enabled"] is False
    assert row["can_submit_orders"] is False

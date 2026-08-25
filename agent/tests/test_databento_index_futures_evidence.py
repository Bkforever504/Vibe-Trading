from __future__ import annotations

from datetime import date, datetime, timezone

import pytest

from scripts.databento_mes_evidence import (
    DATASET,
    fetch_historical_cache,
    historical_request,
    index_future_front_contract,
)


@pytest.mark.parametrize(
    ("root", "expected"),
    [("MES", "MESU6"), ("MNQ", "MNQU6"), ("ES", "ESU6"), ("NQ", "NQU6")],
)
def test_supported_index_roots_share_frozen_quarterly_roll(root: str, expected: str) -> None:
    selected = index_future_front_contract(root, date(2026, 8, 24))
    assert selected.raw_symbol == expected
    assert selected.roll_at == date(2026, 9, 10)
    with pytest.raises(ValueError, match="unsupported CME"):
        index_future_front_contract("CL", date(2026, 8, 24))


def test_root_aware_request_preserves_raw_symbol_and_mbo_midnight_guard() -> None:
    request, selected = historical_request(
        root="MNQ",
        schema="mbo",
        start=datetime(2026, 8, 24, tzinfo=timezone.utc),
        end=datetime(2026, 8, 25, tzinfo=timezone.utc),
    )
    assert request["dataset"] == DATASET
    assert request["symbols"] == selected.raw_symbol == "MNQU6"
    assert request["stype_in"] == "raw_symbol"
    with pytest.raises(ValueError, match="midnight UTC"):
        historical_request(
            root="MNQ",
            schema="mbo",
            start=datetime(2026, 8, 24, 13, 30, tzinfo=timezone.utc),
            end=datetime(2026, 8, 25, tzinfo=timezone.utc),
        )


def test_context_request_can_pin_session_contract_across_roll_lookback() -> None:
    request, contract = historical_request(
        schema="ohlcv-1m",
        root="MNQ",
        start=datetime(2026, 6, 1, tzinfo=timezone.utc),
        end=datetime(2026, 6, 12, tzinfo=timezone.utc),
        contract_date=date(2026, 6, 11),
    )
    assert contract.raw_symbol == "MNQU6"
    assert request["symbols"] == "MNQU6"


def test_root_aware_cache_estimates_before_atomic_download(tmp_path) -> None:
    calls: list[tuple[str, str]] = []

    class Metadata:
        def get_cost(self, **request):
            calls.append(("cost", request["symbols"]))
            return 0.25

    class Timeseries:
        def get_range(self, **request):
            calls.append(("download", request["symbols"]))
            request["path"].write_bytes(b"fixture")

    class Client:
        metadata = Metadata()
        timeseries = Timeseries()

    manifest = fetch_historical_cache(
        root="MNQ",
        schema="ohlcv-1m",
        start=datetime(2026, 8, 24, tzinfo=timezone.utc),
        end=datetime(2026, 8, 25, tzinfo=timezone.utc),
        cache_dir=tmp_path,
        max_cost_usd=0.25,
        client=Client(),
    )
    assert calls == [("cost", "MNQU6"), ("download", "MNQU6")]
    assert manifest["root"] == "MNQ"
    assert manifest["raw_symbol"] == "MNQU6"
    assert manifest["execution_enabled"] is False
    assert manifest["can_submit_orders"] is False
    assert not list(tmp_path.glob("*.partial"))

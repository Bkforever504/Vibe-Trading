from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timezone

import pandas as pd
import pytest

from scripts.databento_mes_evidence import (
    DATASET,
    build_mbo_quote_frame,
    executable_fill,
    fetch_historical_cache,
    historical_request,
    load_api_key,
    mes_front_contract,
    normalize_bbo_1s,
    normalize_ohlcv_1m,
    resample_completed_bars,
    third_friday,
)


def test_exact_eight_calendar_day_roll_uses_raw_quarterly_symbols() -> None:
    assert third_friday(2026, 9) == date(2026, 9, 18)
    before = mes_front_contract(date(2026, 9, 9))
    on_roll = mes_front_contract(date(2026, 9, 10))
    assert (before.raw_symbol, before.roll_at) == ("MESU6", date(2026, 9, 10))
    assert (on_roll.raw_symbol, on_roll.roll_at) == ("MESZ6", date(2026, 12, 10))


def test_request_is_raw_symbol_and_refuses_cross_roll_window() -> None:
    request, contract = historical_request(
        schema="ohlcv-1m",
        start=datetime(2026, 9, 9, tzinfo=timezone.utc),
        end=datetime(2026, 9, 10, tzinfo=timezone.utc),
    )
    assert request["dataset"] == DATASET
    assert request["symbols"] == contract.raw_symbol == "MESU6"
    assert request["stype_in"] == "raw_symbol"
    with pytest.raises(ValueError, match="roll boundary"):
        historical_request(
            schema="bbo-1s",
            start=datetime(2026, 9, 9, tzinfo=timezone.utc),
            end=datetime(2026, 9, 11, tzinfo=timezone.utc),
        )
    with pytest.raises(ValueError, match="midnight UTC"):
        historical_request(
            schema="mbo",
            start=datetime(2026, 8, 24, 13, 0, tzinfo=timezone.utc),
            end=datetime(2026, 8, 25, tzinfo=timezone.utc),
        )


def test_credentials_are_environment_first_and_file_fallback(tmp_path) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text("DATABENTO_API_KEY=file-secret\n", encoding="utf-8")
    assert load_api_key(environ={"DATABENTO_API_KEY": "env-secret"}, env_path=env_file) == "env-secret"
    assert load_api_key(environ={}, env_path=env_file) == "file-secret"
    with pytest.raises(RuntimeError, match="not configured"):
        load_api_key(environ={}, env_path=tmp_path / "missing")


def test_cost_guard_runs_before_download_and_cache_is_atomic_and_hashed(tmp_path) -> None:
    calls: list[str] = []

    class Metadata:
        def __init__(self, cost: float):
            self.cost = cost

        def get_cost(self, **request):
            calls.append("cost")
            assert request["dataset"] == DATASET
            return self.cost

    class Timeseries:
        def get_range(self, **request):
            calls.append("download")
            assert str(request["path"]).endswith(".partial")
            request["path"].write_bytes(b"fixture-dbn")

    class Client:
        def __init__(self, cost: float):
            self.metadata = Metadata(cost)
            self.timeseries = Timeseries()

    args = dict(
        schema="ohlcv-1m",
        start=datetime(2026, 8, 24, tzinfo=timezone.utc),
        end=datetime(2026, 8, 25, tzinfo=timezone.utc),
        cache_dir=tmp_path / "cache",
        max_cost_usd=1.0,
    )
    with pytest.raises(RuntimeError, match="cost_limit"):
        fetch_historical_cache(**args, client=Client(1.01))
    assert calls == ["cost"]

    calls.clear()
    manifest_path = tmp_path / "manifest.json"
    manifest = fetch_historical_cache(**args, client=Client(0.25), manifest_path=manifest_path)
    assert calls == ["cost", "download"]
    assert manifest["sha256"]
    assert manifest["execution_enabled"] is False
    assert manifest["can_submit_orders"] is False
    assert manifest_path.exists()
    assert not list(tmp_path.rglob("*.partial"))

    calls.clear()
    reused = fetch_historical_cache(**args, client=Client(0.25))
    assert calls == ["cost"]
    assert reused["cache_reused"] is True

    calls.clear()
    reserved: list[float] = []
    fetch_historical_cache(
        **{**args, "cache_dir": tmp_path / "fresh-cache"},
        client=Client(0.20),
        reserve_cost=lambda amount: (reserved.append(amount), calls.append("reserve")),
    )
    assert calls == ["cost", "reserve", "download"]
    assert reserved == [0.20]


def _minute_frame(periods: int = 60, symbol: str = "MESU6") -> pd.DataFrame:
    index = pd.date_range("2026-08-24T13:30:00Z", periods=periods, freq="1min")
    return pd.DataFrame(
        {
            "open": [6500.0 + i for i in range(periods)],
            "high": [6500.75 + i for i in range(periods)],
            "low": [6499.75 + i for i in range(periods)],
            "close": [6500.5 + i for i in range(periods)],
            "volume": [10 + i for i in range(periods)],
            "symbol": [symbol] * periods,
        },
        index=index,
    )


def test_ohlcv_contract_validation_and_completed_resampling() -> None:
    minute = normalize_ohlcv_1m(_minute_frame(), expected_raw_symbol="MESU6")
    as_of = datetime(2026, 8, 24, 14, 29, 30, tzinfo=timezone.utc)
    assert len(resample_completed_bars(minute, "2m", as_of=as_of)) == 29
    assert len(resample_completed_bars(minute, "5m", as_of=as_of)) == 11
    assert len(resample_completed_bars(minute, "30m", as_of=as_of)) == 1
    assert len(resample_completed_bars(minute, "1h", as_of=as_of)) == 0
    wrong = _minute_frame(symbol="MESZ6")
    with pytest.raises(ValueError, match="contract mismatch"):
        normalize_ohlcv_1m(wrong, expected_raw_symbol="MESU6")


def _quotes(*, crossed: bool = False, spread: float = 0.25) -> pd.DataFrame:
    index = pd.to_datetime(["2026-08-24T13:32:00Z", "2026-08-24T13:32:01Z"])
    bids = [6500.0, 6500.25]
    asks = [bids[0] - 0.25 if crossed else bids[0] + spread, bids[1] + spread]
    return pd.DataFrame(
        {
            "bid_px_00": bids,
            "ask_px_00": asks,
            "bid_sz_00": [10, 11],
            "ask_sz_00": [12, 13],
            "symbol": ["MESU6", "MESU6"],
        },
        index=index,
    )


def test_bbo_normalization_rejects_crossed_and_stale_quotes() -> None:
    with pytest.raises(ValueError, match="crossed or locked"):
        normalize_bbo_1s(_quotes(crossed=True), expected_raw_symbol="MESU6")
    with pytest.raises(ValueError, match="stale"):
        normalize_bbo_1s(
            _quotes(),
            expected_raw_symbol="MESU6",
            as_of=datetime(2026, 8, 24, 13, 32, 10, tzinfo=timezone.utc),
            max_age_seconds=2,
        )


def test_executable_quote_side_mapping_and_fail_closed_limits() -> None:
    normalized = normalize_bbo_1s(_quotes(), expected_raw_symbol="MESU6")
    decision = datetime(2026, 8, 24, 13, 32, tzinfo=timezone.utc)
    assert executable_fill(normalized, direction="long", action="entry", decision_at=decision)["price_side"] == "ask"
    assert executable_fill(normalized, direction="long", action="exit", decision_at=decision)["price_side"] == "bid"
    assert executable_fill(normalized, direction="short", action="entry", decision_at=decision)["price_side"] == "bid"
    assert executable_fill(normalized, direction="short", action="exit", decision_at=decision)["price_side"] == "ask"
    assert executable_fill(normalized, direction="long", action="entry", decision_at=decision)["promotion_eligible"] is False
    with pytest.raises(ValueError, match="stale"):
        executable_fill(
            normalized,
            direction="long",
            action="entry",
            decision_at=datetime(2026, 8, 24, 13, 31, 50, tzinfo=timezone.utc),
        )
    wide = normalize_bbo_1s(_quotes(spread=1.25), expected_raw_symbol="MESU6")
    with pytest.raises(ValueError, match="too wide"):
        executable_fill(wide, direction="long", action="entry", decision_at=decision)


@dataclass
class MboEvent:
    ts_recv: int
    action: str
    side: str
    order_id: int
    price: int
    size: int
    flags: int
    symbol: str = "MESU6"


def _mbo_events() -> list[MboEvent]:
    base = int(pd.Timestamp("2026-08-24T00:00:00Z").value)
    return [
        # Real historical snapshots set F_BAD_TS_RECV alongside F_SNAPSHOT.
        MboEvent(base, "R", "N", 0, 0, 0, 32 | 8),
        MboEvent(base + 1, "A", "B", 1, 6_500_000_000_000, 10, 32 | 8),
        MboEvent(base + 2, "A", "A", 2, 6_500_250_000_000, 12, 32 | 128 | 8),
        MboEvent(base + 3, "A", "B", 3, 6_500_250_000_000 - 250_000_000, 5, 128),
    ]


def test_mbo_snapshot_reconstructs_time_ordered_promotion_grade_quotes() -> None:
    frame = build_mbo_quote_frame(_mbo_events(), expected_raw_symbol="MESU6")
    assert frame.index.is_monotonic_increasing
    assert frame.iloc[0]["bid"] == 6500.0
    assert frame.iloc[0]["ask"] == 6500.25
    assert frame.iloc[0]["bid_size"] == 10
    assert frame.iloc[0]["ask_size"] == 12
    assert bool(frame.iloc[0]["snapshot_clear_seen"]) is True
    assert bool(frame.iloc[0]["book_valid"]) is True
    assert bool(frame.iloc[0]["promotion_eligible"]) is True
    fill = executable_fill(
        frame,
        direction="long",
        action="entry",
        decision_at=datetime(2026, 8, 24, tzinfo=timezone.utc),
    )
    assert fill["price"] == 6500.25
    assert fill["promotion_eligible"] is True
    assert fill["evidence_tier"] == "databento_mbo_reconstructed_executable"


def test_mbo_missing_snapshot_and_missing_or_crossed_book_fail_closed() -> None:
    events = _mbo_events()
    with pytest.raises(ValueError, match="mandatory clear"):
        build_mbo_quote_frame(events[1:], expected_raw_symbol="MESU6")

    missing_side = events[:2] + [
        MboEvent(events[1].ts_recv + 1, "N", "N", 0, 0, 0, 32 | 128)
    ]
    with pytest.raises(ValueError, match="missing a side"):
        build_mbo_quote_frame(missing_side, expected_raw_symbol="MESU6")

    crossed = events[:2] + [
        MboEvent(events[1].ts_recv + 1, "A", "A", 2, 6_499_750_000_000, 12, 32 | 128)
    ]
    with pytest.raises(ValueError, match="crossed or locked"):
        build_mbo_quote_frame(crossed, expected_raw_symbol="MESU6")

    not_midnight = _mbo_events()
    not_midnight[0].ts_recv += 13 * 3_600_000_000_000
    with pytest.raises(ValueError, match="midnight UTC"):
        build_mbo_quote_frame(not_midnight, expected_raw_symbol="MESU6")


def test_mbo_incremental_bad_timestamp_and_book_anomalies_fail_closed() -> None:
    bad_timestamp = _mbo_events() + [
        MboEvent(_mbo_events()[-1].ts_recv + 1, "A", "B", 99, 6_499_000_000_000, 1, 128 | 8)
    ]
    with pytest.raises(ValueError, match="bad timestamp"):
        build_mbo_quote_frame(bad_timestamp, expected_raw_symbol="MESU6")

    duplicate = _mbo_events() + [
        MboEvent(_mbo_events()[-1].ts_recv + 1, "A", "B", 1, 6_499_000_000_000, 1, 128)
    ]
    with pytest.raises(ValueError, match="anomalous order"):
        build_mbo_quote_frame(duplicate, expected_raw_symbol="MESU6")

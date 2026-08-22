from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd
import pytest

from scripts import fetch_databento_options_nbbo as fetcher


def _candidate() -> dict:
    return {
        "type": "candidate",
        "candidate_id": "abc",
        "created_at": "2026-07-29T19:00:00Z",
        "expiry": "2026-08-06",
        "legs": [
            {"symbol": "SPY260806C00643000", "side": "sell"},
            {"symbol": "SPY260806C00648000", "side": "buy"},
        ],
    }


def test_occ_symbols_are_padded_for_opra_and_compacted_for_curriculum() -> None:
    padded = fetcher.padded_opra_symbol("SPY260806C00643000")

    assert padded == "SPY   260806C00643000"
    assert fetcher.compact_occ(padded) == "SPY260806C00643000"
    with pytest.raises(ValueError, match="invalid OCC"):
        fetcher.padded_opra_symbol("SPY-CALL")


def test_candidate_spec_requests_only_frozen_contracts() -> None:
    explicit_end = datetime(2026, 7, 30, 20, 0, tzinfo=timezone.utc)
    spec = fetcher.extract_candidate_spec(
        [_candidate()],
        end=explicit_end,
        now=datetime(2026, 8, 3, tzinfo=timezone.utc),
    )
    request = fetcher.request_kwargs(spec)

    assert spec.start == "2026-07-29T18:59:55.000Z"
    assert spec.end == "2026-07-30T20:00:00.000Z"
    assert request["dataset"] == "OPRA.PILLAR"
    assert request["schema"] == "cbbo-1s"
    assert request["stype_in"] == "raw_symbol"
    assert request["symbols"] == ["SPY   260806C00643000", "SPY   260806C00648000"]
    assert all(".OPT" not in symbol for symbol in request["symbols"])


def test_availability_cutoff_prevents_future_request() -> None:
    now = datetime(2026, 8, 3, 17, 45, tzinfo=timezone.utc)
    spec = fetcher.extract_candidate_spec([_candidate()], now=now)

    assert spec.end == "2026-08-03T17:15:00.000Z"


def test_provider_availability_boundary_caps_request() -> None:
    spec = fetcher.extract_candidate_spec(
        [_candidate()],
        now=datetime(2026, 8, 4, tzinfo=timezone.utc),
        availability_end=datetime(2026, 8, 3, 13, 30, tzinfo=timezone.utc),
    )

    assert spec.end == "2026-08-03T13:30:00.000Z"


def test_normalize_cbbo_frame_preserves_executable_sides_and_provenance(tmp_path: Path) -> None:
    frame = pd.DataFrame(
        {
            "symbol": ["SPY   260806C00643000", "SPY   260806C00643000"],
            "bid_px_00": [1.2, 1.3],
            "ask_px_00": [1.22, 1.1],
            "bid_sz_00": [10, 11],
            "ask_sz_00": [12, 13],
        },
        index=pd.to_datetime(["2026-07-29T19:00:00Z", "2026-07-29T19:00:01Z"]),
    )

    rows, audit = fetcher.normalize_cbbo_frame(frame, fingerprint="fingerprint", cache=tmp_path / "quotes.dbn.zst")

    assert len(rows) == 1
    assert rows[0]["symbol"] == "SPY260806C00643000"
    assert rows[0]["bid"] == 1.2
    assert rows[0]["ask"] == 1.22
    assert rows[0]["quote_scope"] == "databento_opra_cbbo_1s"
    assert rows[0]["provenance"]["licensed_consolidated_nbbo"] is True
    assert rows[0]["can_submit_orders"] is False
    assert audit == {
        "input_rows": 2,
        "invalid_timestamp": 0,
        "invalid_symbol": 0,
        "invalid_market": 1,
        "output_rows": 1,
    }


def test_cost_guard_blocks_overspend_and_invalid_estimates() -> None:
    fetcher.enforce_cost_guard(0.25, 1.0)
    with pytest.raises(RuntimeError, match="exceeds"):
        fetcher.enforce_cost_guard(1.01, 1.0)
    with pytest.raises(RuntimeError, match="invalid"):
        fetcher.enforce_cost_guard(float("nan"), 1.0)


def test_incremental_budget_selects_cheapest_candidate() -> None:
    expensive = {**_candidate(), "candidate_id": "expensive", "created_at": "2026-07-28T19:00:00Z"}
    cheap = {**_candidate(), "candidate_id": "cheap", "created_at": "2026-07-29T19:00:00Z"}
    specs = {
        "expensive": fetcher.RequestSpec(("EXP",), "a", "b"),
        "cheap": fetcher.RequestSpec(("CHEAP",), "a", "b"),
    }
    costs = {
        "EXP": fetcher.CostEstimate(0.09, 9, 2.0, "test"),
        "CHEAP": fetcher.CostEstimate(0.03, 3, 2.0, "test"),
    }

    row, spec, cost = fetcher.cheapest_budget_candidate(
        [expensive, cheap],
        build_spec=lambda candidate: specs[candidate["candidate_id"]],
        estimate=lambda candidate_spec: costs[candidate_spec.symbols[0]],
        max_cost=0.05,
    )

    assert row["candidate_id"] == "cheap"
    assert spec.symbols == ("CHEAP",)
    assert cost.cost_usd == 0.03


def test_incremental_budget_no_ops_when_cheapest_is_too_expensive() -> None:
    row, spec, cost = fetcher.cheapest_budget_candidate(
        [_candidate()],
        build_spec=lambda _candidate: fetcher.RequestSpec(("SPY",), "a", "b"),
        estimate=lambda _spec: fetcher.CostEstimate(0.06, 6, 2.0, "test"),
        max_cost=0.05,
    )

    assert row is None
    assert spec is not None
    assert cost.cost_usd == 0.06


def test_cost_estimate_uses_billable_bytes_and_frozen_official_rate() -> None:
    class Metadata:
        def get_billable_size(self, **_kwargs):
            return 1024 ** 3

    client = type("Client", (), {"metadata": Metadata()})()
    spec = fetcher.RequestSpec(("SPY   260806C00643000",), "2026-07-29T19:00:00Z", "2026-07-29T20:00:00Z")

    estimate = fetcher.estimate_cost(client, spec)

    assert estimate.cost_usd == 2.0
    assert estimate.billable_bytes == 1024 ** 3
    assert estimate.unit_price_source == "frozen_official_opra_unit_price_2026-08-03"


def test_empty_candidate_file_fails_before_provider_request() -> None:
    with pytest.raises(ValueError, match="no candidate OCC"):
        fetcher.extract_candidate_spec([], now=datetime.now(timezone.utc) + timedelta(days=1))


def test_incremental_lane_excludes_already_resolved_candidates() -> None:
    unresolved = {**_candidate(), "candidate_id": "open"}
    rows = [_candidate(), unresolved]
    results = {"outcomes": [{"candidate_id": "abc", "status": "resolved"}]}

    selected = fetcher.unresolved_candidate_rows(rows, results)

    assert [row["candidate_id"] for row in selected] == ["open"]


def test_incremental_spec_resumes_two_seconds_before_existing_coverage() -> None:
    coverage_end = datetime(2026, 7, 30, 19, 0, tzinfo=timezone.utc)
    coverage = {
        "SPY260806C00643000": coverage_end,
        "SPY260806C00648000": coverage_end,
    }

    spec = fetcher.incremental_candidate_spec(
        [_candidate()],
        coverage,
        end=datetime(2026, 7, 30, 20, 0, tzinfo=timezone.utc),
        now=datetime(2026, 8, 3, tzinfo=timezone.utc),
    )

    assert spec.start == "2026-07-30T18:59:58.000Z"
    assert spec.end == "2026-07-30T20:00:00.000Z"


def test_incremental_merge_deduplicates_overlap_and_preserves_history(tmp_path: Path) -> None:
    path = tmp_path / "quotes.jsonl"
    old = {
        "symbol": "SPY260806C00643000",
        "observed_at": "2026-07-29T19:00:00Z",
        "bid": 1.0,
    }
    fetcher._write_jsonl(path, [old])
    replacement = {**old, "bid": 1.1}
    new = {
        "symbol": "SPY260806C00643000",
        "observed_at": "2026-07-29T19:00:01Z",
        "bid": 1.2,
    }

    merged, added = fetcher.merge_normalized_rows(path, [replacement, new])

    assert added == 1
    assert len(merged) == 2
    assert merged[0]["bid"] == 1.1
    assert merged[1]["bid"] == 1.2

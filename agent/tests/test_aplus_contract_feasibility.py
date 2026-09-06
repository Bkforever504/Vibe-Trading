from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from scripts.aplus_contract_feasibility import (
    _normalise_quote,
    build_records,
    build_summary,
    evaluate_contract,
)


OCC = "SPY260831C00650000"


def candidate(**overrides):
    row = {
        "type": "candidate",
        "candidate_id": "cand-1",
        "move_id": "move-1",
        "date": "2026-08-31",
        "underlying_symbol": "SPY",
        "contract": OCC,
        "candidate_at": "2026-08-31T14:30:05Z",
        "contract_selected_at": "2026-08-31T14:30:05Z",
        "underlying_quote_timestamp": "2026-08-31T14:30:04Z",
        "evaluation_end_at": "2026-08-31T14:31:00Z",
    }
    row.update(overrides)
    return row


def quote(at: str, bid: float, ask: float, *, scope: str = "databento_opra_cbbo_1s", **overrides):
    row = {
        "symbol": OCC,
        "quote_timestamp": at,
        "observed_at": at,
        "bid": bid,
        "ask": ask,
        "bid_size": 20,
        "ask_size": 15,
        "quote_scope": scope,
        "underlying_quote_timestamp": at,
        "provenance": {"provider": "databento", "licensed_consolidated_nbbo": True},
        "execution_enabled": False,
        "can_submit_orders": False,
    }
    row.update(overrides)
    return row


def test_feasible_exact_contract_and_executable_sides():
    rows = [
        quote("2026-08-31T14:30:04Z", 1.00, 1.10),
        quote("2026-08-31T14:31:00Z", 1.24, 1.30),
    ]
    record = build_records([candidate()], rows)[0]
    assert record["contract"] == OCC
    assert record["contract_frozen_at_candidate"] is True
    assert record["feasible"] is True
    assert record["arrival_quote"]["quote_age_seconds"] == 1.0
    assert record["arrival_quote"]["spread_dollars"] == 0.1
    assert record["executable_round_trip"]["entry_ask"] == 1.1
    assert record["executable_round_trip"]["exit_bid"] == 1.24
    assert record["executable_round_trip"]["gross_return_dollars_per_contract"] == 14.0
    assert record["execution_enabled"] is False
    assert record["can_submit_orders"] is False


def test_indicative_quote_is_unavailable_even_when_prices_exist():
    rows = [quote("2026-08-31T14:30:05Z", 1.0, 1.05, scope="indicative_modified_not_opra_nbbo")]
    rows[0]["provenance"]["licensed_consolidated_nbbo"] = False
    record = build_records([candidate()], rows)[0]
    assert record["feasible"] is False
    assert record["data_status"] == "unavailable"
    assert "quote_not_opra_nbbo" in record["blockers"]


def test_future_quote_never_backfills_arrival():
    record = build_records(
        [candidate()],
        [quote("2026-08-31T14:30:06Z", 1.0, 1.05)],
    )[0]
    assert record["feasible"] is False
    assert record["reason"] == "missing_point_in_time_quote"


def test_stale_or_unsynchronised_quote_is_unavailable():
    stale = build_records(
        [candidate()],
        [quote("2026-08-31T14:29:50Z", 1.0, 1.05)],
    )[0]
    assert "stale_arrival_quote" in stale["blockers"]

    unsynchronised_candidate = candidate(underlying_quote_timestamp="2026-08-31T14:29:50Z")
    unsynchronised = build_records(
        [unsynchronised_candidate],
        [quote("2026-08-31T14:30:04Z", 1.0, 1.05, underlying_quote_timestamp=None)],
    )[0]
    assert "underlying_option_timestamp_skew" in unsynchronised["blockers"]


def test_missing_underlying_timestamp_is_unavailable():
    row = quote("2026-08-31T14:30:04Z", 1.0, 1.05, underlying_quote_timestamp=None)
    record = build_records([candidate(underlying_quote_timestamp=None)], [row])[0]
    assert record["feasible"] is False
    assert "missing_underlying_timestamp" in record["blockers"]


def test_future_synchronization_data_cannot_leak_into_arrival():
    row = quote(
        "2026-08-31T14:30:04Z",
        1.0,
        1.05,
        underlying_quote_timestamp="2026-08-31T14:30:06Z",
    )
    record = build_records([candidate()], [row])[0]
    assert record["feasible"] is False
    assert "future_underlying_timestamp" in record["blockers"]


def test_resting_limits_require_later_ask_cross_and_never_claim_fill():
    rows = [
        quote("2026-08-31T14:30:04Z", 1.00, 1.10),
        quote("2026-08-31T14:30:05Z", 1.00, 1.10),  # same timestamp as decision is excluded
        quote("2026-08-31T14:30:20Z", 1.02, 1.05),  # crosses arrival mid only
        quote("2026-08-31T14:31:00Z", 1.00, 1.10),
    ]
    record = build_records([candidate()], rows)[0]
    policies = {p["policy"]: p for p in record["shadow_resting_limits"]}
    mid = policies["arrival_mid"]
    tick = policies["arrival_bid_plus_one_tick"]
    assert mid["limit_price"] == 1.05
    assert mid["quote_marketable_later"] is True
    assert mid["marketable_quote_timestamp"] == "2026-08-31T14:30:20.000Z"
    assert mid["broker_fill_observed"] is False
    assert mid["assumed_fill_price"] is None
    assert tick["limit_price"] == 1.01
    assert tick["quote_marketable_later"] is False


def test_nested_lifecycle_quote_shape_and_optional_age_fields():
    row = {
        "contract": OCC,
        "captured_at": "2026-08-31T14:30:05Z",
        "quote": {
            "quote_timestamp": "2026-08-31T14:30:04Z",
            "bid": 1.0,
            "ask": 1.1,
            "bid_size": 3,
            "ask_size": 4,
        },
        "trade": {"price": 1.07, "trade_timestamp": "2026-08-31T14:30:01Z"},
        "greeks": {"delta": 0.51, "greeks_timestamp": "2026-08-31T14:30:00Z"},
        "underlying": {"price_timestamp": "2026-08-31T14:30:04Z"},
        "provenance": {
            "quote_scope": "alpaca_opra_nbbo",
            "status": "ok",
        },
    }
    normalised = _normalise_quote(row)
    assert normalised is not None
    record = evaluate_contract(candidate(), OCC, [normalised])
    assert record["arrival_quote"]["last_trade_age_seconds"] == 4.0
    assert record["arrival_quote"]["greeks_age_seconds"] == 5.0


def test_missing_exact_contract_emits_unavailable_record():
    row = candidate(contract=None)
    record = build_records([row], [])[0]
    assert record["contract"] is None
    assert record["feasible"] is False
    assert "missing_exact_occ_contract" in record["blockers"]


def test_summary_is_shadow_only_and_counts_blockers(tmp_path: Path):
    records = build_records(
        [candidate(), candidate(candidate_id="cand-2", contract_selected_at="2026-08-31T14:30:06Z")],
        [quote("2026-08-31T14:30:04Z", 1.0, 1.05)],
    )
    summary = build_summary(records, candidates_path=tmp_path / "c.jsonl", quotes_path=tmp_path / "q.jsonl")
    assert summary["record_count"] == 2
    assert summary["available_count"] == 1
    assert summary["unavailable_count"] == 1
    assert summary["blocker_counts"]["contract_selected_after_candidate"] == 1
    assert summary["execution_enabled"] is False
    assert summary["can_submit_orders"] is False

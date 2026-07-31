from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from scripts.options_shadow_twin import (
    build_report,
    executable_close_debit,
    executable_entry_credit,
    mark_open_candidates,
    read_records,
    record_candidate,
    record_decision,
    wilson_interval,
)


def _meta() -> dict:
    return {
        "strategy": "put_spread",
        "underlying": "SPY",
        "expiry": "2026-08-21",
        "qty": 1,
        "net_credit": 1.10,
        "max_risk_per_contract": 390.0,
        "profit_close_pct": 0.5,
        "stop_loss_pct": -1.0,
        "candidate_confidence": {"score": 8},
        "leg_market_snapshots": [
            {
                "symbol": "SPY260821P00600000",
                "expiry": "2026-08-21",
                "strike": 600,
                "right": "P",
                "delta": -0.25,
                "bid": 2.00,
                "ask": 2.10,
                "mid": 2.05,
            },
            {
                "symbol": "SPY260821P00595000",
                "expiry": "2026-08-21",
                "strike": 595,
                "right": "P",
                "delta": -0.18,
                "bid": 0.90,
                "ask": 1.00,
                "mid": 0.95,
            },
        ],
    }


def _payload() -> list[dict]:
    return [
        {"symbol": "SPY260821P00600000", "side": "sell", "ratio_qty": "1"},
        {"symbol": "SPY260821P00595000", "side": "buy", "ratio_qty": "1"},
    ]


def test_call_spread_candidate_is_supported(tmp_path: Path) -> None:
    path = tmp_path / "shadow.jsonl"
    meta = _meta()
    meta["strategy"] = "call_spread"

    candidate_id = record_candidate(meta, _payload(), path=path)

    assert candidate_id
    assert read_records(path)[0]["strategy"] == "call_spread"


def test_executable_credit_and_close_debit_use_adverse_sides() -> None:
    legs = [
        {"side": "sell", "ratio_qty": 1, "bid": 2.0, "ask": 2.1},
        {"side": "buy", "ratio_qty": 1, "bid": 0.9, "ask": 1.0},
    ]
    assert executable_entry_credit(legs) == pytest.approx(1.0)
    assert executable_close_debit(legs) == pytest.approx(1.2)


def test_incomplete_or_crossed_quotes_are_quarantined() -> None:
    missing = [{"side": "sell", "ratio_qty": 1, "bid": None, "ask": 2.1}]
    crossed = [{"side": "sell", "ratio_qty": 1, "bid": 2.2, "ask": 2.1}]
    assert executable_entry_credit(missing) is None
    assert executable_close_debit(crossed) is None


def test_candidate_is_append_only_and_deduped_within_five_minutes(tmp_path: Path) -> None:
    path = tmp_path / "shadow.jsonl"
    now = datetime(2026, 7, 25, 15, 0, tzinfo=timezone.utc)
    first = record_candidate(_meta(), _payload(), path=path, now=now)
    second = record_candidate(_meta(), _payload(), path=path, now=now + timedelta(minutes=4))
    third = record_candidate(_meta(), _payload(), path=path, now=now + timedelta(minutes=6))
    rows = read_records(path)
    assert first == second
    assert third != first
    assert [row["type"] for row in rows] == ["candidate", "candidate"]
    assert rows[0]["executable_entry_credit"] == pytest.approx(1.0)


def test_report_quantifies_midpoint_to_executable_entry_friction(tmp_path: Path) -> None:
    path = tmp_path / "shadow.jsonl"
    now = datetime(2026, 7, 25, 15, 0, tzinfo=timezone.utc)
    record_candidate(_meta(), _payload(), path=path, now=now)

    built = build_report(read_records(path), now=now + timedelta(minutes=1))
    quality = built["execution_cost_quality"]

    assert quality["status"] == "watch_execution_friction"
    assert quality["paired_coverage"] == pytest.approx(1.0)
    assert quality["avg_entry_edge_loss_credit"] == pytest.approx(0.1)
    assert quality["avg_entry_edge_loss_pct_of_mid"] == pytest.approx(0.0909)
    assert quality["benchmark"] == "arrival_mid_credit_vs_sell_bid_buy_ask_executable_entry_credit"
    assert quality["authority"] == "shadow_governance_only"


def test_mark_resolves_target_with_conservative_group_debit(tmp_path: Path) -> None:
    path = tmp_path / "shadow.jsonl"
    now = datetime(2026, 7, 25, 15, 0, tzinfo=timezone.utc)
    candidate_id = record_candidate(_meta(), _payload(), path=path, now=now)
    record_decision(candidate_id, "blocked_strict_caution", path=path, now=now)
    quotes = {
        "SPY260821P00600000": {"bid": 0.60, "ask": 0.70},
        "SPY260821P00595000": {"bid": 0.30, "ask": 0.40},
    }

    def factory(_candidate_id: str, _underlying: str):
        def fetch(symbol: str) -> dict:
            return {
                "quote": {**quotes[symbol], "quote_timestamp": "2026-07-25T15:30:00Z"},
                "provenance": {"status": "ok"},
            }

        return fetch

    stats = mark_open_candidates(
        path=path,
        quote_fetcher_factory=factory,
        now=now + timedelta(hours=1),
    )
    rows = read_records(path)
    outcome = next(row for row in rows if row["type"] == "outcome")
    assert stats["resolved"] == 1
    assert outcome["reason"] == "profit_target_50pct_credit"
    assert outcome["closing_debit"] == pytest.approx(0.4)
    assert outcome["pnl_before_fees"] == pytest.approx(60.0)


def test_mark_uses_candidate_stop_loss_policy(tmp_path: Path) -> None:
    path = tmp_path / "shadow.jsonl"
    now = datetime(2026, 7, 25, 15, 0, tzinfo=timezone.utc)
    meta = _meta()
    meta["stop_loss_pct"] = -2.0
    record_candidate(meta, _payload(), path=path, now=now)

    def quotes_for(short_ask: float, long_bid: float):
        quotes = {
            "SPY260821P00600000": {"bid": short_ask - 0.10, "ask": short_ask},
            "SPY260821P00595000": {"bid": long_bid, "ask": long_bid + 0.10},
        }

        def factory(_candidate_id: str, _underlying: str):
            return lambda symbol: {
                "quote": {**quotes[symbol], "quote_timestamp": "2026-07-25T16:00:00Z"},
                "provenance": {"status": "ok"},
            }

        return factory

    not_stopped = mark_open_candidates(
        path=path,
        quote_fetcher_factory=quotes_for(3.00, 0.50),
        now=now + timedelta(hours=1),
    )
    stopped = mark_open_candidates(
        path=path,
        quote_fetcher_factory=quotes_for(3.60, 0.50),
        now=now + timedelta(hours=2),
    )

    assert not_stopped["resolved"] == 0
    assert stopped["resolved"] == 1
    outcome = next(row for row in read_records(path) if row["type"] == "outcome")
    assert outcome["reason"] == "stop_200pct_credit"


def test_wilson_interval_does_not_report_false_certainty() -> None:
    lower, upper = wilson_interval(3, 3)
    assert lower is not None and lower < 0.5
    assert upper == pytest.approx(1.0)


def test_negative_expectancy_hard_caps_confidence_at_three() -> None:
    records: list[dict] = []
    start = datetime(2026, 1, 2, 15, 0, tzinfo=timezone.utc)
    for index in range(30):
        candidate_id = f"candidate-{index}"
        records.extend(
            [
                {
                    "type": "candidate",
                    "candidate_id": candidate_id,
                    "created_at": (start + timedelta(days=index)).isoformat(),
                    "entry_quote_complete": True,
                    "candidate_confidence": {"score": 9 if index % 2 == 0 else 1},
                },
                {
                    "type": "mark",
                    "candidate_id": candidate_id,
                    "quote_complete": True,
                },
                {
                    "type": "outcome",
                    "candidate_id": candidate_id,
                    "pnl_before_fees": 10.0 if index % 3 == 0 else -20.0,
                    "win": index % 3 == 0,
                },
            ]
        )
    report = build_report(records, now=start + timedelta(days=40))
    assert report["performance"]["expectancy_before_fees"] < 0
    assert report["earned_confidence"]["evidence_cap"] == 3.0
    assert report["earned_confidence"]["score"] <= 3.0
    assert report["promotion_eligible"] is False


def test_records_are_valid_jsonl(tmp_path: Path) -> None:
    path = tmp_path / "shadow.jsonl"
    record_candidate(_meta(), _payload(), path=path)
    for line in path.read_text(encoding="utf-8").splitlines():
        assert isinstance(json.loads(line), dict)

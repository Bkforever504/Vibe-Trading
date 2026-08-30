from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from scripts import spy_level_reaction_outcome_report as resolver


ET = ZoneInfo("America/New_York")
AVAILABLE = datetime(2026, 8, 28, 10, 0, tzinfo=ET)


def _candidate() -> dict:
    return {
        "candidate_id": "spy-level-test-1",
        "eligible_for_outcome_comparison": True,
        "reaction": {
            "direction": "bullish", "level": 100.0, "level_name": "previous_day_low",
            "observed_at": "2026-08-28T09:55:00-04:00", "decision_available_at": AVAILABLE.isoformat(),
        },
        "gap_context": {"fill_bucket": "filled_within_30m"},
        "breadth_context": {"regime": "mixed"},
        "intermarket_context": {"qqq_spy_regime": "qqq_leading_spy", "sector_leaders": [{"etf": "XLK"}]},
    }


def _bars() -> list[dict]:
    return [
        {
            "t": (AVAILABLE + timedelta(minutes=5 * offset)).isoformat(),
            "o": 100.0 + offset * 0.03,
            "h": 100.3 + offset * 0.03,
            "l": 99.85 + offset * 0.02,
            "c": 100.1 + offset * 0.04,
            "v": 1000,
        }
        for offset in range(12)
    ]


def test_resolver_requires_full_post_availability_horizon_and_records_context() -> None:
    candidate = _candidate()
    assert resolver.resolve_candidate(candidate, _bars(), now_et=AVAILABLE + timedelta(minutes=59)) is None

    outcome = resolver.resolve_candidate(candidate, _bars(), now_et=AVAILABLE + timedelta(minutes=60))

    assert outcome is not None
    assert outcome["gap_fill_bucket"] == "filled_within_30m"
    assert outcome["breadth_regime"] == "mixed"
    assert outcome["intermarket_regime"] == "qqq_leading_spy"
    assert outcome["mfe_points"] > 0
    assert outcome["cost_adjusted"] is False
    assert outcome["can_submit_orders"] is False


def test_outcome_slice_requires_minimum_sample_and_stays_blocked() -> None:
    outcome = resolver.resolve_candidate(_candidate(), _bars(), now_et=AVAILABLE + timedelta(minutes=60))
    assert outcome is not None
    report = resolver.build_report([outcome])

    row = report["summary"]["gap_time_to_fill_slices"][0]
    assert row["bucket"] == "filled_within_30m"
    assert row["sample_count"] == 1
    assert row["meets_minimum_sample"] is False
    assert report["summary"]["promotion_eligible"] is False


def test_outcome_ledger_is_durable_and_deduped(tmp_path: Path) -> None:
    outcome = resolver.resolve_candidate(_candidate(), _bars(), now_et=AVAILABLE + timedelta(minutes=60))
    assert outcome is not None
    ledger = tmp_path / "outcomes.jsonl"

    assert resolver.append_new_outcomes([outcome], ledger_path=ledger) == 1
    assert resolver.append_new_outcomes([outcome], ledger_path=ledger) == 0

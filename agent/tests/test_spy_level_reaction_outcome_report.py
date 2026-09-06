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
        "spy0dte_candidate_features": {
            "mapped_level_kind": "whole_dollar",
            "touch_count": 1,
            "touch_sequence": "first",
            "rsi_14_completed_5m": 29.4,
            "rsi_14_status": "available",
            "raw_approach_return_30m_points": -0.72,
            "atr_14_completed_5m_points": 0.28,
            "atr_normalized_approach_speed": -2.57,
            "early_session_eligible": True,
        },
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
    assert outcome["spy0dte_candidate_features"]["rsi_14_completed_5m"] == 29.4
    assert outcome["contract_feasibility"] == {
        "status": "unavailable",
        "reason": "quote_required",
        "required_data": "timestamped_selected_contract_bid_ask_nbbo_and_quote_freshness",
        "option_return_inferred": False,
    }
    assert outcome["fixed_premium_proxy_plan"]["target_pct"] == 20.0
    assert outcome["fixed_premium_proxy_plan"]["stop_pct"] == -12.5
    assert outcome["fixed_premium_proxy_plan"]["result"] == "not_inferred"


def test_outcome_slice_requires_minimum_sample_and_stays_blocked() -> None:
    outcome = resolver.resolve_candidate(_candidate(), _bars(), now_et=AVAILABLE + timedelta(minutes=60))
    assert outcome is not None
    report = resolver.build_report([outcome])

    row = report["summary"]["gap_time_to_fill_slices"][0]
    assert row["bucket"] == "filled_within_30m"
    assert row["sample_count"] == 1
    assert row["meets_minimum_sample"] is False
    assert report["summary"]["promotion_eligible"] is False
    assert report["summary"]["contract_feasibility"]["status"] == "unavailable"
    assert report["summary"]["contract_feasibility"]["option_return_inferred"] is False
    assert report["summary"]["spy0dte_candidate_feature_slices"]["rsi_14_completed_5m"][0]["bucket"] == "29.4"
    assert "non-executable" in report["warnings"][-1]


def test_absent_spy0dte_features_remain_backward_compatible_and_never_infer_option_returns() -> None:
    candidate = _candidate()
    candidate.pop("spy0dte_candidate_features")
    outcome = resolver.resolve_candidate(candidate, _bars(), now_et=AVAILABLE + timedelta(minutes=60))

    assert outcome is not None
    assert outcome["spy0dte_candidate_features"] == {}
    assert outcome["fixed_premium_proxy_plan"]["status"] == "non_executable_unvalidated"
    assert outcome["contract_feasibility"]["status"] == "unavailable"
    assert outcome["contract_feasibility"]["option_return_inferred"] is False
    assert "option_return_pct" not in outcome


def test_outcome_ledger_is_durable_and_deduped(tmp_path: Path) -> None:
    outcome = resolver.resolve_candidate(_candidate(), _bars(), now_et=AVAILABLE + timedelta(minutes=60))
    assert outcome is not None
    ledger = tmp_path / "outcomes.jsonl"

    assert resolver.append_new_outcomes([outcome], ledger_path=ledger) == 1
    assert resolver.append_new_outcomes([outcome], ledger_path=ledger) == 0

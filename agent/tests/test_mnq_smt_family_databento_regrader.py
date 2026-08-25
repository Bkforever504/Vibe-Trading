from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pandas as pd

from scripts import mnq_smt_family_databento_regrader as regrader
from scripts import mnq_smt_family_evidence_status as status


def _entry(session: str = "2026-08-25") -> dict:
    return {
        "event_type": "entry", "plan_id": "p1", "strategy_id": "mnq-cisd-only-v1",
        "candidate_id": "mnq-cisd-only-v1", "session_date": session,
        "should_enter": True, "direction": "long", "captured_at": f"{session}T14:00:00Z",
    }


def _terminal(session: str = "2026-08-25") -> dict:
    return {"event_type": "exit", "plan_id": "p1", "exit_timestamp": f"{session}T20:30:00Z",
            "resolved_at": f"{session}T23:30:00Z"}


def test_pending_uses_market_exit_timestamp_and_historical_delay() -> None:
    ready = datetime(2026, 8, 26, 5, 31, tzinfo=timezone.utc)
    assert regrader.pending_plans([_entry(), _terminal()], [], [], now=ready)
    assert not regrader.pending_plans([_entry(), _terminal()], [], [], now=ready - timedelta(minutes=2))


def test_completed_and_retrying_plans_are_not_reprocessed() -> None:
    now = datetime(2026, 8, 27, tzinfo=timezone.utc)
    qualified = [{"plan_id": "p1", "data_source": "databento_glbx_mdp3_mbo"}]
    assert regrader.pending_plans([_entry(), _terminal()], qualified, [], now=now) == []
    attempts = [{"plan_id": "p1", "status": "failed_closed", "attempted_at": "2026-08-26T20:00:00Z"}]
    assert regrader.pending_plans([_entry(), _terminal()], [], attempts, now=now) == []


def test_mbo_resolver_uses_executable_sides_and_frozen_scale_out() -> None:
    action = datetime(2026, 8, 25, 14, tzinfo=timezone.utc)
    quotes = [
        {"ts_recv": action, "bid": 100.0, "ask": 100.25},
        {"ts_recv": action + timedelta(seconds=1), "bid": 101.5, "ask": 101.75},
        {"ts_recv": action + timedelta(seconds=2), "bid": 102.5, "ask": 102.75},
    ]
    resolved = regrader.resolve_mbo_quotes(
        quotes, direction="long", actionable_at=action, stop_price=99.0,
        t1_price=101.25, t2_price=102.25, forced_exit_at=action + timedelta(hours=6),
    )
    assert resolved["entry_fill_executable"] == 100.25
    assert resolved["exit_fills_executable"] == [101.5, 102.5]
    assert resolved["exit_reason"] == "t2_after_t1"


def test_frozen_regime_labeler_emits_one_tag_from_each_axis() -> None:
    index = pd.date_range("2026-08-25T12:00:00Z", periods=120, freq="1min")
    closes = [100 + value * 0.01 for value in range(120)]
    frame = pd.DataFrame({"open": closes, "high": [v + 0.01 for v in closes],
                          "low": [v - 0.01 for v in closes], "close": closes,
                          "volume": 10, "symbol": "MNQU6"}, index=index)
    tags, metrics = regrader.regime_labels(frame, as_of=datetime(2026, 8, 25, 14, tzinfo=timezone.utc))
    assert len(set(tags) & {"trend", "chop"}) == 1
    assert len(set(tags) & {"high_vol", "low_vol"}) == 1
    assert metrics["directional_efficiency_24x5m"] == 1.0


def test_post_preregistration_mbo_row_can_count_but_prior_session_cannot() -> None:
    plan = {"direction": "long", "stop_price": 99.0, "signal_trigger_at": "2026-08-25T14:00:00Z",
            "regime_tags": ["trend", "high_vol"], "regime_metrics": {"directional_efficiency_24x5m": 0.5}}
    resolved = {"entry_fill_executable": 100.0, "exit_fill_executable": 102.0,
                "exit_fills_executable": [101.0, 103.0], "exit_quote_at": "2026-08-25T15:00:00Z",
                "exit_reason": "t2_after_t1", "gross_dollar": 4.0}
    manifests = {"MNQ_mbo": {"sha256": "mbo"}, **{f"{root}_ohlcv": {"sha256": root} for root in regrader.ROOTS}}
    current = regrader.build_outcome(entry=_entry(), plan=plan, resolved=resolved, manifests=manifests,
                                     now=datetime(2026, 8, 26, tzinfo=timezone.utc))
    assert current["promotion_eligible"] is True
    assert current["execution_enabled"] is False and current["can_submit_orders"] is False
    prior_entry = _entry("2026-08-24")
    prior_plan = plan | {"signal_trigger_at": "2026-08-24T14:00:00Z"}
    prior_resolved = resolved | {"exit_quote_at": "2026-08-24T15:00:00Z"}
    prior = regrader.build_outcome(entry=prior_entry, plan=prior_plan, resolved=prior_resolved,
                                   manifests=manifests, now=datetime(2026, 8, 26, tzinfo=timezone.utc))
    assert prior["promotion_eligible"] is False
    assert prior["evidence_blockers"] == ["pre_preregistration_session"]


def test_status_counts_only_explicitly_qualified_mbo_rows() -> None:
    rows = [
        {"plan_id": "a", "candidate_id": "mnq-cisd-only-v1", "session_date": "2026-08-25",
         "promotion_eligible": False, "data_source": "yfinance_proxy"},
        {"plan_id": "b", "candidate_id": "mnq-cisd-only-v1", "session_date": "2026-08-26",
         "promotion_eligible": True, "data_source": "databento_glbx_mdp3_mbo", "regime_tags": ["trend"]},
    ]
    report = status.build_status(rows, capability={"live_status": "unavailable", "live_reason": "live_data_license_required"},
                                 approval_present=True, now=datetime(2026, 8, 27, tzinfo=timezone.utc))
    candidate = next(value for value in report["candidates"] if value["candidate_id"] == "mnq-cisd-only-v1")
    assert candidate["qualified_outcomes"] == 1
    assert candidate["excluded_outcomes"] == 1
    assert report["live_feed"]["status"] == "unavailable"
    assert report["execution_enabled"] is False and report["can_submit_orders"] is False


def test_estimate_only_makes_no_provider_call(tmp_path) -> None:
    report = regrader.run_once(download=False, now=datetime(2026, 8, 27, tzinfo=timezone.utc),
                               outcomes_path=tmp_path / "outcomes.jsonl", attempt_log=tmp_path / "attempts.jsonl")
    assert report["status"] == "estimate_only_no_paid_calls"
    assert report["execution_enabled"] is False and report["can_submit_orders"] is False

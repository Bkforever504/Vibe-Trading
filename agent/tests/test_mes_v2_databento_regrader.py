from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from scripts.mes_v2_databento_regrader import (
    HISTORICAL_DELAY,
    RunBudget,
    _require_context,
    pending_plans,
    qualified_outcome,
    resolve_mbo_quotes,
)


NOW = datetime(2026, 8, 26, 18, 0, tzinfo=timezone.utc)


def quote(stamp: datetime, bid: float, ask: float) -> dict:
    return {"ts_recv": stamp, "bid": bid, "ask": ask, "bid_size": 10, "ask_size": 10}


def test_pending_requires_terminal_age_and_skips_existing_qualified() -> None:
    entry = {"event_type": "entry", "plan_id": "p1", "should_enter": True}
    old_terminal = {"event_type": "exit", "plan_id": "p1", "resolved_at": (NOW - HISTORICAL_DELAY - timedelta(minutes=1)).isoformat()}
    assert len(pending_plans([entry, old_terminal], [], now=NOW)) == 1
    recent = {**old_terminal, "resolved_at": (NOW - HISTORICAL_DELAY + timedelta(minutes=1)).isoformat()}
    assert pending_plans([entry, recent], [], now=NOW) == []
    assert pending_plans([entry, old_terminal], [{"plan_id": "p1", "promotion_eligible": True}], now=NOW) == []

    recent_failure = {
        "plan_id": "p1",
        "status": "failed_closed",
        "attempted_at": (NOW - timedelta(hours=1)).isoformat(),
    }
    assert pending_plans(
        [entry, old_terminal], [], now=NOW, attempt_rows=[recent_failure]
    ) == []


def test_aggregate_budget_fails_before_overspend() -> None:
    budget = RunBudget(2.25)
    budget.debit(0.25)
    budget.debit(2.0)
    assert budget.remaining_usd == 0
    with pytest.raises(RuntimeError, match="aggregate"):
        budget.debit(0.01)


def test_orb_mbo_resolution_uses_ask_entry_bid_exits_and_two_contract_scale() -> None:
    action = datetime(2026, 8, 24, 13, 35, tzinfo=timezone.utc)
    rows = [
        quote(action, 100.00, 100.25),
        quote(action + timedelta(seconds=1), 101.25, 101.50),
        quote(action + timedelta(seconds=2), 102.25, 102.50),
    ]
    result = resolve_mbo_quotes(
        rows,
        strategy_id="mes-orb-0932-vix-v2",
        direction="long",
        actionable_at=action,
        stop_price=99.0,
        target_one_distance=1.0,
        target_two_distance=2.0,
        forced_exit_at=action + timedelta(hours=2),
    )
    assert result["entry_fill_executable"] == 100.25
    assert result["exit_fills_executable"] == [101.25, 102.25]
    assert result["gross_dollar"] == 15.0
    assert result["quantity"] == 2
    assert result["exit_reason"] == "t2_after_t1"


def test_mbo_resolution_fails_closed_on_stale_or_wide_entry_quote() -> None:
    action = datetime(2026, 8, 24, 13, 35, tzinfo=timezone.utc)
    with pytest.raises(ValueError, match="two-second"):
        resolve_mbo_quotes(
            [quote(action + timedelta(seconds=3), 100, 100.25)],
            strategy_id="mes-orb-0932-vix-v2", direction="long", actionable_at=action,
            stop_price=99, target_one_distance=1, target_two_distance=2,
            forced_exit_at=action + timedelta(hours=2),
        )
    with pytest.raises(ValueError, match="spread/size"):
        resolve_mbo_quotes(
            [quote(action, 100, 101.25)],
            strategy_id="mes-orb-0932-vix-v2", direction="long", actionable_at=action,
            stop_price=99, target_one_distance=1, target_two_distance=2,
            forced_exit_at=action + timedelta(hours=2),
        )


def test_mbo_resolution_rejects_active_gaps_and_late_forced_exit() -> None:
    action = datetime(2026, 8, 24, 13, 35, tzinfo=timezone.utc)
    with pytest.raises(ValueError, match="continuity gap"):
        resolve_mbo_quotes(
            [
                quote(action, 100, 100.25),
                quote(action + timedelta(seconds=31), 100.25, 100.50),
            ],
            strategy_id="mes-orb-0932-vix-v2", direction="long", actionable_at=action,
            stop_price=99, target_one_distance=10, target_two_distance=20,
            forced_exit_at=action + timedelta(hours=2),
        )

    forced = action + timedelta(seconds=10)
    with pytest.raises(ValueError, match="forced-exit quote"):
        resolve_mbo_quotes(
            [
                quote(action, 100, 100.25),
                quote(forced + timedelta(seconds=3), 100.25, 100.50),
            ],
            strategy_id="mes-orb-0932-vix-v2", direction="long", actionable_at=action,
            stop_price=99, target_one_distance=10, target_two_distance=20,
            forced_exit_at=forced,
        )


def test_point_in_time_context_requires_source_timestamp_and_causality() -> None:
    captured = datetime(2026, 8, 24, 14, 0, tzinfo=timezone.utc)
    filters = {
        "macro_source": "market_catalyst_calendar",
        "macro_observed_at": "2026-08-24T13:59:00Z",
    }
    assert _require_context(
        filters,
        source_key="macro_source",
        timestamp_key="macro_observed_at",
        expected_source="market_catalyst_calendar",
        captured_at=captured,
    ) < captured
    with pytest.raises(ValueError, match="later than capture"):
        _require_context(
            {**filters, "macro_observed_at": "2026-08-24T14:01:00Z"},
            source_key="macro_source",
            timestamp_key="macro_observed_at",
            expected_source="market_catalyst_calendar",
            captured_at=captured,
        )


def test_qualified_outcome_has_exact_universe_cost_stress_and_no_authority() -> None:
    entry = {
        "plan_id": "mes-orb-0932-vix-v2:2026-08-24",
        "strategy_id": "mes-orb-0932-vix-v2",
        "session_date": "2026-08-24",
        "captured_at": "2026-08-24T13:36:00Z",
    }
    plan = {
        "direction": "long", "stop_price": 99.0,
        "actionable_at": "2026-08-24T13:35:00Z",
    }
    resolved = {
        "entry_fill_executable": 100.0,
        "exit_fill_executable": 102.0,
        "exit_fills_executable": [101.0, 103.0],
        "exit_quote_at": "2026-08-24T14:00:00Z",
        "exit_reason": "t2_after_t1",
        "gross_dollar": 20.0,
    }
    row = qualified_outcome(
        entry=entry, official_plan=plan, resolved=resolved,
        raw_symbol="MESU6", mbo_manifest={"sha256": "mbo"},
        ohlcv_manifest={"sha256": "ohlcv"}, now=NOW,
    )
    assert row["promotion_eligible"] is True
    assert row["evidence_tier"] == "databento_mbo_executable"
    assert row["universe"]["raw_symbol"] == "MESU6"
    assert row["outcome_r"] > row["doubled_cost_outcome_r"]
    assert row["alert_latency_seconds"] == 60
    assert row["execution_enabled"] is False
    assert row["can_submit_orders"] is False
    with pytest.raises(ValueError, match="roll universe"):
        qualified_outcome(
            entry=entry, official_plan=plan, resolved=resolved,
            raw_symbol="MESZ6", mbo_manifest={}, ohlcv_manifest={}, now=NOW,
        )

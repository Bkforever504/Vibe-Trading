from __future__ import annotations

import sys
from datetime import date, datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.multitimeframe_pattern_memory import (
    PatternMemoryConfig,
    advise_setup,
    build_fingerprint,
    fingerprint_similarity,
)
from strategies.methodical_decision_policy import evaluate_methodical_entry


def _setup(**updates):
    row = {
        "symbol": "SPY",
        "strategy": "0dte",
        "right": "CALL",
        "contracts": 2,
        "entry_evidence_gate": "passed_fresh_orb_retest",
        "day_type": "trend_up",
        "htf_primary_bias": "bullish",
        "htf_intraday_alignment": "aligned",
        "opening_range_bucket": "normal",
        "orb_direction": "bullish",
        "orb_entry_pattern": "fresh_vwap_ema_pullback",
        "orb_retest_status": "confirmed",
        "retest_grade": "a",
        "above_vwap": True,
        "above_ema50": True,
        "ema50_sloping_up": True,
        "confidence": 8.0,
        "spread_cents_at_signal": 3.0,
    }
    row.update(updates)
    return row


def _record(day: str, value: float, *, setup=None, lifecycle_id=None):
    source = setup or _setup()
    return {
        "lifecycle_id": lifecycle_id or f"life-{day}-{value}",
        "date": day,
        "fingerprint": build_fingerprint(source),
        "outcome": {
            "net_return_pct": value,
            "mfe_post_cost_pct": max(value, 15.0),
            "mae_post_cost_pct": min(value, -5.0),
        },
    }


def test_fingerprint_preserves_timeframe_structure_and_scale_normalization() -> None:
    fingerprint = build_fingerprint(_setup())

    assert fingerprint["direction"] == "bullish"
    assert fingerprint["frames"]["daily"]["bias"] == "bullish"
    assert fingerprint["frames"]["15m"]["break_direction"] == "bullish"
    assert fingerprint["frames"]["5m"]["retest"] == "confirmed"
    assert fingerprint["numeric"]["spread_cents_at_signal"] == 3.0


def test_similarity_rejects_opposite_direction() -> None:
    call = build_fingerprint(_setup(right="CALL"))
    put = build_fingerprint(_setup(right="PUT"))

    similarity, coverage = fingerprint_similarity(call, put)

    assert similarity == 0.0
    assert coverage == 0.0


def test_advice_uses_strictly_prior_dates_and_has_no_execution_authority() -> None:
    records = [
        _record("2026-08-06", 8.0),
        _record("2026-08-07", 10.0),
        _record("2026-08-08", 12.0),
        _record("2026-08-10", -90.0, lifecycle_id="same-day-must-not-leak"),
        _record("2026-08-11", -90.0, lifecycle_id="future-must-not-leak"),
    ]
    config = PatternMemoryConfig(
        min_matches=3,
        min_independent_dates=3,
        max_matches=10,
        min_similarity=0.5,
        min_feature_coverage=0.3,
    )

    advice = advise_setup(
        _setup(),
        as_of=date(2026, 8, 10),
        config=config,
        records=records,
    )

    assert advice["status"] == "positive_edge"
    assert advice["analog_summary"]["matches"] == 3
    assert advice["analog_summary"]["expectancy_post_cost_pct"] == 10.0
    assert advice["same_day_or_future_records_excluded"] == 2
    assert advice["strictly_prior_date_only"] is True
    assert advice["forward_validated"] is False
    assert advice["can_submit_orders"] is False
    assert advice["can_change_size"] is False
    assert advice["can_block_entry"] is False


def test_methodical_policy_logs_pattern_memory_without_granting_it_a_vote() -> None:
    setup = _setup(
        option_symbol="SPY260817C00780000",
        pattern_memory_advisory={
            "status": "positive_edge",
            "authority": "shadow_advisory_only",
            "can_submit_orders": False,
        },
    )
    context = {
        "portfolio_kill_switch_active": False,
        "source_health": {
            "higher_timeframe": {"status": "current"},
            "market_force": {"status": "current"},
            "garch": {"status": "current"},
            "catalyst": {"status": "current"},
        },
        "higher_timeframe": {"primary_bias": "bullish", "intraday_alignment": "aligned"},
        "market_force": {"classification": "bullish_confirmation", "confidence": 9.0},
        "garch": {"status": "ok", "position_size_multiplier": 1.0},
        "catalyst": {"max_impact": "none", "vetoes": []},
    }

    decision = evaluate_methodical_entry(setup, context, paper=True)

    assert decision["status"] == "primary_eligible"
    assert "pattern_memory_positive_edge_research_only" in decision["cautions"]
    assert {vote["source"] for vote in decision["confirmations"]} == {
        "higher_timeframe",
        "market_force",
    }
    assert decision["pattern_memory_advisory"]["authority"] == "shadow_advisory_only"
    assert decision["can_submit_orders"] is False


def test_nightly_challenger_runner_refreshes_pattern_memory() -> None:
    runner = (ROOT / "scripts" / "run_flip_execution_challenger_report.ps1").read_text(
        encoding="utf-8"
    )

    causal_index = runner.index("python research\\causal_trade_replay_lab.py")
    memory_index = runner.index("python scripts\\multitimeframe_pattern_memory.py")
    assert memory_index > causal_index

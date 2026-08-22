from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from strategies.methodical_decision_policy import (
    evaluate_methodical_entry,
    load_methodical_context,
)


NOW = datetime(2026, 8, 14, 15, 0, tzinfo=timezone.utc)


def _setup(**updates):
    row = {
        "symbol": "SPY",
        "strategy": "0dte",
        "right": "CALL",
        "option_symbol": "SPY260814C00780000",
        "contracts": 4,
        "entry_evidence_gate": "passed_fresh_orb_retest",
        "confidence_basis": "fresh_orb_breakout_retest",
        "underlying_structure_level": 779.0,
    }
    row.update(updates)
    return row


def _context(**updates):
    row = {
        "portfolio_kill_switch_active": False,
        "source_health": {
            "higher_timeframe": {"status": "current"},
            "market_force": {"status": "current"},
            "garch": {"status": "current"},
            "catalyst": {"status": "current"},
        },
        "higher_timeframe": {"primary_bias": "bullish", "intraday_alignment": "aligned"},
        "market_force": {"classification": "bullish_confirmation", "confidence": 9.0},
        "garch": {"status": "ok", "position_size_multiplier": 0.5},
        "catalyst": {"max_impact": "none", "vetoes": []},
    }
    row.update(updates)
    return row


def test_primary_requires_fresh_trigger_and_independent_confirmation() -> None:
    decision = evaluate_methodical_entry(_setup(), _context(), paper=True)

    assert decision["status"] == "primary_eligible"
    assert decision["adjusted_contracts"] == 2
    assert {row["source"] for row in decision["confirmations"]} == {
        "higher_timeframe",
        "market_force",
    }
    assert decision["can_submit_orders"] is False


def test_conflict_routes_to_one_contract_exploration_in_paper() -> None:
    context = _context(
        higher_timeframe={"primary_bias": "bearish", "intraday_alignment": "aligned"},
        market_force={"classification": "bullish_confirmation", "confidence": 9.0},
    )
    decision = evaluate_methodical_entry(_setup(), context, paper=True)

    assert decision["status"] == "exploration_only"
    assert decision["adjusted_contracts"] == 1
    assert decision["conflicts"][0]["source"] == "higher_timeframe"


def test_missing_optional_context_collects_bounded_evidence() -> None:
    decision = evaluate_methodical_entry(
        _setup(contracts=3),
        {"source_health": {}, "portfolio_kill_switch_active": False},
        paper=True,
    )

    assert decision["status"] == "exploration_only"
    assert decision["adjusted_contracts"] == 1
    assert "independent_directional_context_unavailable" in decision["cautions"]


def test_missing_trigger_or_kill_switch_blocks() -> None:
    missing_trigger = evaluate_methodical_entry(
        _setup(entry_evidence_gate=None), _context(), paper=True
    )
    killed = evaluate_methodical_entry(
        _setup(), _context(portfolio_kill_switch_active=True), paper=True
    )

    assert missing_trigger["status"] == "blocked"
    assert "fresh_price_trigger_not_confirmed" in missing_trigger["hard_blockers"]
    assert killed["adjusted_contracts"] == 0
    assert "portfolio_kill_switch_active" in killed["hard_blockers"]


def test_policy_never_grants_live_authority() -> None:
    decision = evaluate_methodical_entry(_setup(), _context(), paper=False)

    assert decision["status"] == "blocked"
    assert decision["can_submit_orders"] is False
    assert "methodical_policy_has_no_live_authority" in decision["hard_blockers"]


def test_required_trade_signal_contract_must_be_current_and_directionally_matched() -> None:
    context = _context()
    context["source_health"]["trade_signal_generator"] = {"status": "current"}
    context["trade_signal"] = {
        "signal_id": "sig-1",
        "paper_consumable": True,
        "direction": "bullish",
        "entry": 780.0,
        "stop": 778.0,
        "targets": [{"price": 784.0}],
    }
    matched = evaluate_methodical_entry(
        _setup(requires_trade_signal_contract=True), context, paper=True
    )
    assert matched["trade_signal_contract"]["matched"] is True
    assert matched["status"] == "primary_eligible"

    stale_context = _context()
    stale_context["source_health"]["trade_signal_generator"] = {"status": "stale"}
    stale_context["trade_signal"] = context["trade_signal"]
    blocked = evaluate_methodical_entry(
        _setup(requires_trade_signal_contract=True), stale_context, paper=True
    )
    assert "required_trade_signal_contract_missing_or_stale" in blocked["hard_blockers"]


def test_current_cash_control_plane_demotes_primary_to_exploration() -> None:
    context = _context()
    context["source_health"]["profitability_control_plane"] = {"status": "current"}
    context["profitability_control_plane"] = {
        "capital_decision": {
            "action": "hold_cash_collect_counterfactuals",
            "selected": [],
        }
    }

    decision = evaluate_methodical_entry(_setup(contracts=4), context, paper=True)

    assert decision["status"] == "exploration_only"
    assert decision["adjusted_contracts"] == 1
    assert decision["profitability_control"]["allows_primary"] is False
    assert "profitability_control_plane_demotes_to_exploration" in decision["cautions"]


def test_current_control_plane_can_only_preserve_existing_primary_eligibility() -> None:
    context = _context()
    context["source_health"]["profitability_control_plane"] = {"status": "current"}
    context["profitability_control_plane"] = {
        "capital_decision": {
            "action": "paper_candidates_available",
            "selected": [{"lane": "aggressive_long_0dte_options"}],
        }
    }

    decision = evaluate_methodical_entry(_setup(), context, paper=True)

    assert decision["status"] == "primary_eligible"
    assert decision["can_submit_orders"] is False


def _write(path: Path, payload: dict) -> None:
    path.write_text(json.dumps(payload), encoding="utf-8")


def test_context_loader_excludes_stale_votes_and_keeps_advisories(tmp_path: Path) -> None:
    current = NOW.isoformat().replace("+00:00", "Z")
    stale = (NOW - timedelta(days=2)).isoformat().replace("+00:00", "Z")
    _write(
        tmp_path / "higher-timeframe-market-map.json",
        {
            "generated_at": current,
            "items": [{"symbol": "SPY", "primary_bias": "bullish", "intraday_alignment": "aligned"}],
        },
    )
    _write(
        tmp_path / "market-force-score.json",
        {"timestamp": stale, "classification": "bearish_confirmation", "confidence": 10},
    )
    _write(
        tmp_path / "options-liquidation-heatmap.json",
        {"generated_at": current, "results": [{"symbol": "SPY", "gex_wall": 780}]},
    )
    _write(
        tmp_path / "timesfm-market-forecast.json",
        {"generated_at": current, "items": [{"symbol": "SPY", "forecast_direction": "bearish_range"}]},
    )
    _write(
        tmp_path / "trade-signal-generator.json",
        {
            "generated_at": current,
            "ready_signals": [{"symbol": "SPY", "signal_id": "sig-1", "direction": "bullish", "paper_consumable": True}],
        },
    )

    context = load_methodical_context("SPY", report_dir=tmp_path, now=NOW)

    assert context["source_health"]["higher_timeframe"]["status"] == "current"
    assert context["source_health"]["market_force"]["status"] == "stale"
    assert context["heatmap_advisory"]["gex_wall"] == 780
    assert context["timesfm_advisory"]["forecast_direction"] == "bearish_range"
    assert context["source_health"]["trade_signal_generator"]["status"] == "current"
    assert context["trade_signal"]["signal_id"] == "sig-1"

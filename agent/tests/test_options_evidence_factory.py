from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts import options_evidence_factory as factory
from scripts.options_shadow_twin import read_records as read_twin_records


NOW = datetime(2026, 8, 11, 15, 0, tzinfo=timezone.utc)


def _snapshot(symbol: str, right: str, strike: float, bid: float, ask: float, **overrides) -> dict:
    row = {
        "symbol": symbol,
        "expiry": "2026-09-18",
        "strike": strike,
        "right": right,
        "bid": bid,
        "ask": ask,
        "mid": (bid + ask) / 2,
        "quote_timestamp": NOW.isoformat(),
        "quote_provider": "synthetic_test",
        "quote_scope": "indicative_modified_not_opra_nbbo",
    }
    row.update(overrides)
    return row


def _put_spread() -> tuple[dict, list[dict]]:
    short = "SPY260918P00605000"
    long = "SPY260918P00600000"
    meta = {
        "strategy": "put_spread",
        "underlying": "SPY",
        "expiry": "2026-09-18",
        "qty": 1,
        "net_credit": 0.72,
        "max_risk_per_contract": 428.0,
        "profit_close_pct": 0.5,
        "stop_loss_pct": -1.0,
        "leg_market_snapshots": [
            _snapshot(short, "P", 605.0, 1.00, 1.04),
            _snapshot(long, "P", 600.0, 0.24, 0.28),
        ],
    }
    legs = [
        {"symbol": short, "side": "sell", "ratio_qty": 1},
        {"symbol": long, "side": "buy", "ratio_qty": 1},
    ]
    return meta, legs


def _iron_condor() -> tuple[dict, list[dict]]:
    snapshots = [
        _snapshot("SPY260918P00600000", "P", 600.0, 0.20, 0.24),
        _snapshot("SPY260918P00605000", "P", 605.0, 0.98, 1.02),
        _snapshot("SPY260918C00615000", "C", 615.0, 0.93, 0.97),
        _snapshot("SPY260918C00620000", "C", 620.0, 0.18, 0.22),
    ]
    meta = {
        "strategy": "iron_condor",
        "underlying": "SPY",
        "expiry": "2026-09-18",
        "qty": 1,
        "net_credit": 1.45,
        "max_risk_per_contract": 355.0,
        "profit_close_pct": 0.5,
        "stop_loss_pct": -1.0,
        "calibration_cohort": "ic-v1",
        "leg_market_snapshots": snapshots,
    }
    legs = [
        {"symbol": snapshots[0]["symbol"], "side": "buy", "ratio_qty": 1},
        {"symbol": snapshots[1]["symbol"], "side": "sell", "ratio_qty": 1},
        {"symbol": snapshots[2]["symbol"], "side": "sell", "ratio_qty": 1},
        {"symbol": snapshots[3]["symbol"], "side": "buy", "ratio_qty": 1},
    ]
    return meta, legs


def test_blocked_setup_still_records_read_only_counterfactual(tmp_path: Path) -> None:
    twin_path = tmp_path / "twin.jsonl"
    evidence_path = tmp_path / "factory.jsonl"
    meta, legs = _put_spread()

    result = factory.record_matched_setup(
        {
            "source_strategy": "vrp_defined_risk",
            "underlying": "SPY",
            "decision_at": NOW.isoformat(),
            "gate_states": {"liquidity": False, "event": True},
            "warning_states": ["blocked_liquidity"],
        },
        meta,
        legs,
        twin_path=twin_path,
        evidence_path=evidence_path,
        now=NOW,
    )

    assert result["primary_candidate_id"]
    candidate = next(row for row in read_twin_records(twin_path) if row["type"] == "candidate")
    assert candidate["setup_id"] == result["setup_id"]
    assert candidate["gate_states"]["liquidity"] is False
    assert candidate["expression_type"] == "primary"
    assert candidate["execution_enabled"] is False
    assert candidate["can_submit_orders"] is False
    expressions = factory.read_records(evidence_path)[0]["expressions"]
    assert any(row["expression_type"] == "no_trade" for row in expressions)


def test_iron_condor_creates_matched_component_spreads(tmp_path: Path) -> None:
    twin_path = tmp_path / "twin.jsonl"
    evidence_path = tmp_path / "factory.jsonl"
    meta, legs = _iron_condor()

    result = factory.record_matched_setup(
        {"source_strategy": "pin_range_0dte", "underlying": "SPY", "decision_at": NOW.isoformat()},
        meta,
        legs,
        twin_path=twin_path,
        evidence_path=evidence_path,
        now=NOW,
    )

    candidates = [row for row in read_twin_records(twin_path) if row["type"] == "candidate"]
    assert {row["strategy"] for row in candidates} == {"iron_condor", "put_spread", "call_spread"}
    assert {row["setup_id"] for row in candidates} == {result["setup_id"]}
    components = [row for row in candidates if row["strategy"] != "iron_condor"]
    assert all(row["max_risk_per_contract"] > 0 for row in components)
    decisions = [row for row in read_twin_records(twin_path) if row["type"] == "decision"]
    assert len(decisions) == 2
    assert {row["decision"] for row in decisions} == {"counterfactual_only_no_order_path"}


def test_future_quote_is_unavailable_and_never_reaches_twin(tmp_path: Path) -> None:
    twin_path = tmp_path / "twin.jsonl"
    evidence_path = tmp_path / "factory.jsonl"
    meta, legs = _put_spread()
    meta["leg_market_snapshots"][0]["quote_timestamp"] = (NOW + timedelta(seconds=1)).isoformat()

    result = factory.record_matched_setup(
        {"source_strategy": "vrp_defined_risk", "underlying": "SPY", "decision_at": NOW.isoformat()},
        meta,
        legs,
        twin_path=twin_path,
        evidence_path=evidence_path,
        now=NOW,
    )

    assert result["primary_candidate_id"] is None
    assert not twin_path.exists()
    primary = factory.read_records(evidence_path)[0]["expressions"][0]
    assert primary["status"] == "unavailable"
    assert primary["reason"] == "future_quote_timestamp"


def test_missing_leg_quote_fails_closed(tmp_path: Path) -> None:
    meta, legs = _put_spread()
    meta["leg_market_snapshots"].pop()

    result = factory.record_matched_setup(
        {"source_strategy": "vrp_defined_risk", "underlying": "SPY"},
        meta,
        legs,
        twin_path=tmp_path / "twin.jsonl",
        evidence_path=tmp_path / "factory.jsonl",
        now=NOW,
    )

    assert result["status"] == "primary_unavailable"
    assert result["expressions"][0]["reason"] == "missing_leg_quote"


def test_setup_id_is_stable_for_same_frozen_decision() -> None:
    base = {
        "source_strategy": "flip_directional_0dte",
        "underlying": "SPY",
        "decision_hash": "frozen-decision",
    }
    assert factory.stable_setup_id(base, NOW) == factory.stable_setup_id(dict(base), NOW)


def test_coverage_report_counts_candidates_outcomes_and_unavailable(tmp_path: Path) -> None:
    twin_path = tmp_path / "twin.jsonl"
    evidence_path = tmp_path / "factory.jsonl"
    meta, legs = _put_spread()
    result = factory.record_matched_setup(
        {"source_strategy": "vrp_defined_risk", "underlying": "SPY"},
        meta,
        legs,
        twin_path=twin_path,
        evidence_path=evidence_path,
        now=NOW,
    )
    with twin_path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps({
            "type": "outcome",
            "candidate_id": result["primary_candidate_id"],
            "pnl_before_fees": 20.0,
        }) + "\n")

    report = factory.build_report(factory.read_records(evidence_path), read_twin_records(twin_path))

    assert report["setup_count"] == 1
    assert report["recorded_candidate_count"] == 1
    assert report["resolved_candidate_count"] == 1
    assert report["entry_quote_coverage"] == 1.0
    assert report["by_strategy"] == {"put_spread": 1}
    assert report["execution_enabled"] is False


def test_shadow_and_opra_runners_refresh_evidence_reports() -> None:
    shadow_runner = (ROOT / "scripts" / "run_options_shadow_twin.ps1").read_text(encoding="utf-8")
    opra_runner = (ROOT / "scripts" / "run_databento_options_nbbo_curriculum.ps1").read_text(encoding="utf-8")

    assert '"scripts/options_evidence_factory.py"' in shadow_runner
    assert '"scripts/options_edge_attribution_report.py"' in shadow_runner
    assert '$failedSteps += "options_evidence_factory"' in shadow_runner
    assert '$failedSteps += "options_edge_attribution_report"' in shadow_runner
    assert "python scripts\\options_edge_attribution_report.py" in opra_runner

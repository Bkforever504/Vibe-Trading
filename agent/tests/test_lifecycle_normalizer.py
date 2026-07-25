from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts import lifecycle_normalizer as canon
from scripts import lifecycle_contamination_audit as audit


def _flip_put(**overrides):
    trade = {
        "id": "t1",
        "strategy": "0dte",
        "right": "PUT",
        "symbol": "SPY",
        "entry_price": 2.00,
        "exit_price": 3.00,
        "contracts": 1,
        "status": "closed",
    }
    trade.update(overrides)
    return trade


def test_bearish_flip_put_profits_when_underlying_falls() -> None:
    view = canon.normalize_flip_trade(_flip_put())

    assert view["bot_family"] == canon.FLIP_FAMILY
    assert view["direction"] == "bearish"
    assert view["pnl_dollars"] == 100.0
    assert view["outcome_status"] == "win"
    assert canon.underlying_move_is_favorable(view["direction"], -1.5) is True
    assert canon.underlying_move_is_favorable(view["direction"], +1.5) is False


def test_bullish_flip_call_profits_when_underlying_rises() -> None:
    view = canon.normalize_flip_trade(
        _flip_put(right="CALL", entry_price=1.00, exit_price=1.80)
    )

    assert view["direction"] == "bullish"
    assert view["pnl_dollars"] == 80.0
    assert view["outcome_status"] == "win"
    assert canon.underlying_move_is_favorable(view["direction"], +1.0) is True
    assert canon.underlying_move_is_favorable(view["direction"], -1.0) is False


def test_flip_conflicting_strategy_and_right_is_quarantined() -> None:
    view = canon.normalize_flip_trade(_flip_put(strategy="bull_trend", right="PUT"))

    assert view["direction"] == canon.UNKNOWN
    assert view["quarantined"] is True
    assert any("conflicting_direction_fields" in r for r in view["unknown_reasons"])


def test_credit_spread_uses_credit_and_max_risk_semantics() -> None:
    view = canon.normalize_options_trade({
        "id": "o1",
        "strategy": "put_spread",
        "underlying": "IWM",
        "qty": 2,
        "net_credit": 0.50,
        "closing_filled_avg_price": 0.10,
        "max_risk_per_contract": 1.50,
        "status": "closed",
    })

    assert view["bot_family"] == canon.OPTIONS_FAMILY
    # Bull put credit spread is bullish even though its legs are puts.
    assert view["direction"] == "bullish"
    assert view["right"] == canon.NOT_APPLICABLE
    assert view["pnl_dollars"] == 80.0          # (0.50 - 0.10) * 100 * 2
    assert view["risk_dollars"] == 300.0        # 1.50 * 100 * 2
    assert view["return_on_risk_pct"] == pytest.approx(26.667, abs=0.001)
    assert view["outcome_status"] == "win"


def test_iron_condor_is_neutral_and_recovered_mleg_is_quarantined() -> None:
    condor = canon.normalize_options_trade({"strategy": "iron_condor", "status": "open"})
    recovered = canon.normalize_options_trade({"strategy": "recovered_mleg", "status": "closed"})

    assert condor["direction"] == "neutral"
    assert canon.underlying_move_is_favorable("neutral", 1.0) == canon.NOT_APPLICABLE
    assert recovered["direction"] == canon.UNKNOWN
    assert recovered["quarantined"] is True
    assert any("unclassified_credit_structure" in r for r in recovered["unknown_reasons"])


def test_mes_uses_point_value_fees_and_short_semantics() -> None:
    view = canon.normalize_topstep_trade({
        "id": "m1",
        "side": "short",
        "entry_price": 6400.00,
        "exit_price": 6390.00,
        "contracts": 1,
        "fees": 2.50,
        "status": "closed",
    })

    assert view["bot_family"] == canon.TOPSTEP_FAMILY
    assert view["direction"] == "bearish"
    # 10 points favorable * $5 point value - $2.50 fees.
    assert view["pnl_dollars"] == 47.5
    assert view["point_value"] == 5.0
    assert view["outcome_status"] == "win"


def test_cross_family_rules_fail_closed() -> None:
    flip_view = canon.normalize_flip_trade(_flip_put())
    credit_view = canon.normalize_options_trade({"strategy": "put_spread", "status": "open"})

    canon.assert_rule_compatible(canon.FLIP_FAMILY, flip_view)
    with pytest.raises(canon.FamilyRuleViolation):
        canon.assert_rule_compatible(canon.OPTIONS_FAMILY, flip_view)
    with pytest.raises(canon.FamilyRuleViolation):
        canon.assert_rule_compatible(canon.FLIP_FAMILY, credit_view)
    with pytest.raises(canon.FamilyRuleViolation):
        canon.assert_rule_compatible("made_up_family", flip_view)


def test_trend_alignment_reports_missing_bearish_keys_instead_of_unconfirmed() -> None:
    bull_only_features = {"above_vwap": False, "above_ema50": False, "ema50_sloping_up": False}

    alignment, reason = canon.trend_alignment("bearish", bull_only_features)

    assert alignment == canon.UNKNOWN
    assert reason is not None and reason.startswith("missing_bearish_feature_keys")

    full_features = {**bull_only_features, "below_vwap": True, "below_ema50": True, "ema50_sloping_down": True}
    alignment, reason = canon.trend_alignment("bearish", full_features)
    assert alignment == "confirmed"
    assert reason is None


def test_closed_trade_without_pnl_is_quarantined_not_graded() -> None:
    view = canon.normalize_flip_trade(
        _flip_put(entry_price=None, exit_price=None, pnl=None)
    )

    assert view["outcome_status"] == canon.UNKNOWN
    assert view["quarantined"] is True
    assert "closed_without_resolvable_pnl" in view["unknown_reasons"]


def test_contamination_audit_counts_and_reports_by_family(tmp_path: Path) -> None:
    import json

    flip_path = tmp_path / "flip-trades.json"
    flip_path.write_text(json.dumps([
        _flip_put(),
        _flip_put(strategy="bull_trend", right="PUT"),
    ]), encoding="utf-8")
    options_path = tmp_path / "options-trades.json"
    options_path.write_text(json.dumps({"trades": [
        {"id": "o1", "strategy": "put_spread", "net_credit": 0.5,
         "max_risk_per_contract": 1.5, "qty": 1, "status": "open"},
        {"id": "o2", "strategy": "recovered_mleg", "status": "closed"},
    ]}), encoding="utf-8")
    shadow_path = tmp_path / "shadow.jsonl"
    shadow_path.write_text(json.dumps({
        "lifecycle_id": "s1", "right": "PUT", "date": "2026-07-01",
        "feature_snapshot": {"above_vwap": True, "above_ema50": True,
                             "ema50_sloping_up": True, "schema_version": 1},
    }) + "\n", encoding="utf-8")
    ledger_path = tmp_path / "ledger.jsonl"
    ledger_path.write_text(json.dumps({
        "event_id": "e1",
        "context": {"entry_pattern": "unknown", "trend_alignment": "unconfirmed",
                    "retest_status": "unknown", "expected_move_bucket": "unknown",
                    "spread_bucket": "tight_le_5"},
    }) + "\n", encoding="utf-8")

    report = audit.build_report(
        flip_path=flip_path, options_path=options_path,
        shadow_path=shadow_path, ledger_path=ledger_path,
    )

    assert report["mode"] == "read_only"
    assert report["summary"]["quarantined_flip"] == 1
    # recovered_mleg lacks positive credit: credit rules were misapplied.
    assert report["summary"]["options_credit_rule_misapplications"] == 1
    # PUT row graded with bullish-only feature keys is contaminated.
    assert report["summary"]["shadow_trend_alignment_unknowns"] == 1
    ledger = report["mistake_ledger_audit"]
    assert ledger["unknown_context_field_counts"]["entry_pattern"] == 1
    assert ledger["unknown_context_field_counts"]["expected_move_bucket"] == 1

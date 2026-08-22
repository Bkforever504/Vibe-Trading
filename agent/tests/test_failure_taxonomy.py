from __future__ import annotations

import json

from scripts import failure_taxonomy as taxonomy
from scripts import lifecycle_normalizer as canon


def _loss_view(**overrides):
    view = {
        "bot_family": canon.FLIP_FAMILY,
        "instrument_type": "equity_option",
        "strategy_family": "bull_trend",
        "direction": "bullish",
        "pnl_dollars": -25.0,
    }
    view.update(overrides)
    return view


def test_nbbo_cost_larger_than_move_is_cost_consumed_edge():
    raw = {
        "nbbo_spread_pct": 1.2,
        "underlying_move_pct": 0.5,
    }
    category, _ = taxonomy.classify_loss(raw, _loss_view())
    assert category == "COST_CONSUMED_EDGE"


def test_vix_tag_boundaries():
    assert taxonomy.regime_tags({"vix_at_entry": 14.9})["vix_tier"] == "low"
    assert taxonomy.regime_tags({"vix_at_entry": 15})["vix_tier"] == "medium"
    assert taxonomy.regime_tags({"vix_at_entry": 25})["vix_tier"] == "high"
    assert taxonomy.regime_tags({"vix_at_entry": 40})["vix_tier"] == "extreme"


def test_quarantined_records_are_excluded(tmp_path):
    flip_path = tmp_path / "flip.json"
    flip_path.write_text("[]", encoding="utf-8")
    options_path = tmp_path / "options.json"
    options_path.write_text(json.dumps({"trades": [{
        "id": "legacy",
        "status": "closed",
        "strategy": "put_spread",
        "underlying": "IWM",
        "net_credit": 0.5,
        "qty": 1,
        "max_risk_per_contract": 150,
    }]}), encoding="utf-8")
    topstep = tmp_path / "topstep.jsonl"
    topstep.write_text("", encoding="utf-8")
    ledger = tmp_path / "ledger.jsonl"
    ledger.write_text("", encoding="utf-8")
    report = taxonomy.build_report(flip_path, options_path, topstep, ledger)
    assert report["total_closed"] == 1
    assert report["excluded_quarantined"] == 1
    assert report["total_losses"] == 0


def test_categories_sum_to_total_losses(tmp_path):
    flip_path = tmp_path / "flip.json"
    flip_path.write_text(json.dumps([
        {
            "id": "wrong",
            "status": "closed",
            "strategy": "bull_trend",
            "right": "CALL",
            "symbol": "SPY",
            "contracts": 1,
            "entry_price": 1.0,
            "exit_price": 0.5,
            "underlying_change_pct": -0.8,
        },
        {
            "id": "unknown",
            "status": "closed",
            "strategy": "bull_trend",
            "right": "CALL",
            "symbol": "SPY",
            "contracts": 1,
            "entry_price": 1.0,
            "exit_price": 0.7,
        },
    ]), encoding="utf-8")
    options = tmp_path / "options.json"
    options.write_text('{"trades":[]}', encoding="utf-8")
    topstep = tmp_path / "topstep.jsonl"
    topstep.write_text("", encoding="utf-8")
    ledger = tmp_path / "ledger.jsonl"
    ledger.write_text("", encoding="utf-8")
    report = taxonomy.build_report(flip_path, options, topstep, ledger)
    assert report["total_losses"] == 2
    assert sum(row["count"] for row in report["by_category"].values()) == 2
    assert report["invariants"]["categories_mutually_exclusive"] is True


def test_systematic_requires_ten_independent_instances():
    base = {
        "category": "WRONG_DIRECTION",
        "regime": {
            "vix_tier": "medium",
            "session_phase": "morning",
            "dte_bucket": "0dte",
        },
    }
    nine = [
        {**base, "trade_id": f"t{index}", "date": f"2026-07-{index + 1:02d}"}
        for index in range(9)
    ]
    assert taxonomy.summarize_records(nine)["WRONG_DIRECTION"]["systematic"] is False
    ten = [
        *nine,
        {**base, "trade_id": "t9", "date": "2026-07-10"},
    ]
    summary = taxonomy.summarize_records(ten)["WRONG_DIRECTION"]
    assert summary["systematic"] is True
    assert summary["countermeasure_template"] is not None


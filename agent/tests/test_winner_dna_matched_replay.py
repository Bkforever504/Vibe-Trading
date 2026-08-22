from __future__ import annotations

import json

from research.winner_dna_matched_replay import (
    _gate,
    _window,
    actual_flip_seeds,
    actual_options_seed_status,
)


def test_actual_flip_seeds_retain_losing_twins(tmp_path):
    path = tmp_path / "flip.json"
    catalyst = (
        "VWAP/50EMA bull trend 9/10: above VWAP, above 50EMA, "
        "50EMA sloping up, green session, not extended from VWAP, "
        "pullback held trend"
    )
    rows = [
        {
            "id": "winner",
            "status": "closed",
            "right": "CALL",
            "strategy": "bull_trend",
            "contracts": 1,
            "entry_price": 1.0,
            "exit_price": 1.5,
            "pnl": 50.0,
            "entry_date": "2026-01-05",
            "entry_at": "2026-01-05T15:30:00Z",
            "catalyst": catalyst,
        },
        {
            "id": "loser",
            "status": "closed",
            "right": "CALL",
            "strategy": "bull_trend",
            "contracts": 1,
            "entry_price": 1.0,
            "exit_price": 0.7,
            "pnl": -30.0,
            "entry_date": "2026-01-06",
            "entry_at": "2026-01-06T15:30:00Z",
            "catalyst": catalyst,
        },
    ]
    path.write_text(json.dumps(rows), encoding="utf-8")
    report = actual_flip_seeds(path)
    bull = report["archetypes"]["bull"]
    assert bull["winner_seed_count"] == 1
    assert bull["actual_twin_count"] == 2
    assert bull["actual_twin_wins"] == 1
    assert bull["actual_twin_losses"] == 1


def test_options_seeds_require_fill_derived_pnl(tmp_path):
    path = tmp_path / "options.json"
    payload = {
        "trades": [{
            "id": "estimated-only",
            "status": "closed",
            "strategy": "put_spread",
            "underlying": "IWM",
            "qty": 1,
            "net_credit": 0.50,
            "max_risk_per_contract": 250,
            "closing_reason": "profit target hit: +50% of credit",
        }]
    }
    path.write_text(json.dumps(payload), encoding="utf-8")
    report = actual_options_seed_status(path)
    assert report["fill_derived_eligible_count"] == 0
    assert report["fill_derived_winner_count"] == 0
    assert report["archetype_status"] == "insufficient_fill_derived_winners"


def test_gate_fails_when_any_regime_is_negative():
    positive = {
        "count": 40,
        "expectancy": 2.0,
        "profit_factor": 1.2,
        "top_one_pct_removed_expectancy": 1.0,
        "block_bootstrap_ci95": [0.1, 4.0],
    }
    archetype = {
        "independent_dates": 40,
        "overall": positive,
        "partitions": {
            "development": dict(positive),
            "selection": {**positive, "expectancy": -0.1, "profit_factor": 0.99},
            "diagnostic": dict(positive),
        },
    }
    status, blockers = _gate(archetype)
    assert status == "not_nominated"
    assert "selection_expectancy_not_positive" in blockers
    assert "selection_profit_factor_not_above_1_10" in blockers


def test_window_labels_do_not_blend_consumed_periods():
    assert _window("2023-12-29") == "development_2022_2023"
    assert _window("2024-01-02") == "selection_2024"
    assert _window("2025-01-02") == "diagnostic_consumed_2025_plus"

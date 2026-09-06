from pathlib import Path

import pandas as pd

from research import multi_timeframe_edge_tournament as tournament


def test_frozen_attempt_count_and_alpha() -> None:
    assert tournament.TIMEFRAMES == (5, 10, 15, 30, 60)
    assert len(tournament.FAMILIES) == 8
    assert tournament.NEW_ATTEMPTS == 80
    assert tournament.BONFERRONI_ALPHA == 0.05 / 989


def test_simulation_is_conservative_when_stop_and_target_touch() -> None:
    bars = pd.DataFrame([
        {"time": "10:00", "open": 100.0, "high": 100.2, "low": 99.8, "close": 100.0},
        {"time": "10:05", "open": 100.0, "high": 102.5, "low": 98.5, "close": 101.0},
    ])
    pnl = tournament.simulate_fixed_horizon(bars, (0, 1, 99.0), 5)
    assert pnl == -100.0


def test_gate_requires_multiple_testing_significance() -> None:
    strong = {"trades": 100, "expectancy": 10.0, "profit_factor": 1.5, "p_value": tournament.BONFERRONI_ALPHA / 2}
    stress = {"expectancy": 2.0}
    folds = [{"expectancy": 1.0}, {"expectancy": 2.0}, {"expectancy": -1.0}]
    assert tournament._passes(strong, stress, folds)
    weak_p = {**strong, "p_value": tournament.BONFERRONI_ALPHA * 2}
    assert not tournament._passes(weak_p, stress, folds)


def test_shadow_payload_has_no_rank_or_execution_authority() -> None:
    payload = tournament.shadow_payload({
        "experiment": "x",
        "cross_market_robust_pairs": [{"family": "f", "timeframe_minutes": 15}],
    })
    assert payload["execution_enabled"] is False
    assert payload["rank_effect"] == "none"
    assert payload["candidate_count"] == 1
    assert payload["promotion_requirements"]["requires_manual_review"] is True


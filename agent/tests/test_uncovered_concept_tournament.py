import pandas as pd

from research import uncovered_concept_tournament as tournament


def test_attempt_count_and_cumulative_alpha_are_frozen() -> None:
    assert tournament.NEW_ATTEMPTS == 20
    assert tournament.EFFECTIVE_ATTEMPTS == 1012
    assert tournament.BONFERRONI_ALPHA == 0.05 / 1012


def test_cbc_requires_two_sided_sweep_and_close_beyond_prior_extreme() -> None:
    bars = pd.DataFrame([
        {"high": 101.0, "low": 99.0, "open": 100.0, "close": 100.0},
        {"high": 101.5, "low": 98.5, "open": 100.0, "close": 101.2},
        {"high": 101.3, "low": 100.0, "open": 101.2, "close": 101.1},
    ])
    assert tournament._cbc(bars, None) == (1, 1, 98.5)


def test_engulfing_requires_confirmation_and_volume() -> None:
    rows = []
    for idx in range(24):
        close = 100.0 - idx * 0.1
        rows.append({"open": close + 0.05, "close": close, "high": close + 0.1, "low": close - 0.1, "volume": 100.0})
    rows[20] = {"open": 97.95, "close": 98.4, "high": 98.5, "low": 97.8, "volume": 200.0}
    rows[21] = {"open": 98.4, "close": 98.6, "high": 98.7, "low": 98.3, "volume": 100.0}
    bars = pd.DataFrame(rows)
    assert tournament._engulfing(bars, None) == (21, 1, 97.8)


def test_market_gate_rejects_non_significant_result() -> None:
    aggregate = {"trades": 100, "expectancy": 2.0, "profit_factor": 1.3, "p_value": tournament.BONFERRONI_ALPHA * 2}
    stress = {"expectancy": 1.0}
    folds = [{"expectancy": 1.0}, {"expectancy": 1.0}, {"expectancy": -1.0}]
    assert not tournament._passes(aggregate, stress, folds)


from __future__ import annotations

from research.mes_close_reversal_confirmation import passes


def test_passes_requires_cost_resilience_and_drawdown_cap() -> None:
    base = {"trades": 40, "expectancy": 3.0, "profit_factor": 1.3, "max_drawdown": 180.0}
    stress = {"expectancy": 1.0, "profit_factor": 1.11}
    assert passes(base, stress)
    assert not passes({**base, "max_drawdown": 201.0}, stress)
    assert not passes(base, {**stress, "expectancy": -1.0})

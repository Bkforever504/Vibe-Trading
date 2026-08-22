import pandas as pd

from research.momentum_edge_ensemble_lab import (
    ALL_SYMBOLS,
    MAX_ASSET_WEIGHT,
    build_ensemble_weights,
    run_lab,
)


def _synthetic_prices(rows: int = 900) -> pd.DataFrame:
    index = pd.bdate_range("2020-01-02", periods=rows)
    data = {}
    for position, symbol in enumerate(ALL_SYMBOLS):
        daily = 1.00015 + position * 0.000015
        data[symbol] = [100.0 * daily**day for day in range(rows)]
    return pd.DataFrame(data, index=index)


def test_ensemble_caps_each_asset_and_never_uses_leverage():
    weights, sleeves = build_ensemble_weights(_synthetic_prices())

    assert len(sleeves) == 3
    assert float(weights.max().max()) <= MAX_ASSET_WEIGHT
    assert bool((weights.sum(axis=1) <= 1.0 + 1e-12).all())
    assert bool((weights >= 0.0).all().all())


def test_ensemble_requires_the_fixed_universe():
    prices = _synthetic_prices().drop(columns=[ALL_SYMBOLS[-1]])

    try:
        build_ensemble_weights(prices)
    except ValueError as exc:
        assert "missing required symbols" in str(exc)
    else:
        raise AssertionError("missing symbol should fail closed")


def test_report_is_research_only_even_when_gates_pass_or_fail():
    report = run_lab(_synthetic_prices())

    assert report["configuration_count"] == 1
    assert report["execution_enabled"] is False
    assert report["can_submit_orders"] is False
    assert report["promotion_authority"] in {"forward_shadow_only", "blocked"}
    assert report["promotion_authority"] != "live"
    assert report["portfolio_diagnostics"]["maximum_asset_weight"] <= MAX_ASSET_WEIGHT

import numpy as np

from agent.analytics.outcome_bootstrap import (bootstrap_ci, mean_expectancy,
                                                optimal_stationary_block_size)


def test_ci_widens_with_lower_n():
    small = bootstrap_ci(np.tile([-1.0, 1.0], 10), mean_expectancy, random_state=4)
    large = bootstrap_ci(np.tile([-1.0, 1.0], 100), mean_expectancy, random_state=4)
    assert small["ci_high"] - small["ci_low"] > large["ci_high"] - large["ci_low"]


def test_insufficient_data_returns_none():
    result = bootstrap_ci(range(19), mean_expectancy)
    assert result["point"] is None
    assert result["reason"] == "insufficient_data"
    assert result["n"] == 19


def test_optimal_block_length_bounds():
    block = optimal_stationary_block_size(np.sin(np.arange(50)))
    assert isinstance(block, int)
    assert 1 <= block <= 50


def test_iterations_at_least_1000_persisted():
    result = bootstrap_ci(range(20), mean_expectancy, iterations=10)
    assert result["iterations"] == 1000
    assert result["block_size"] >= 1
    assert len(result["model_version"]) == 12
    assert len(result["library_version_hash"]) == 12


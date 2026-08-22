from __future__ import annotations

import sys
from pathlib import Path

import numpy as np


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def test_stationary_bootstrap_preserves_constant_mean() -> None:
    from research.mes_reopen_sensitivity import stationary_block_bootstrap_mean

    samples = stationary_block_bootstrap_mean(
        np.array([7.5] * 20),
        n_boot=100,
        mean_block_len=5,
        rng=np.random.default_rng(123),
    )

    assert samples.shape == (100,)
    assert np.all(samples == 7.5)


def test_stationary_bootstrap_is_seed_reproducible() -> None:
    from research.mes_reopen_sensitivity import stationary_block_bootstrap_mean

    values = np.array([-2.0, 1.0, 4.0, 8.0, -1.0])
    first = stationary_block_bootstrap_mean(
        values, 50, 3, np.random.default_rng(20260817)
    )
    second = stationary_block_bootstrap_mean(
        values, 50, 3, np.random.default_rng(20260817)
    )

    assert np.array_equal(first, second)

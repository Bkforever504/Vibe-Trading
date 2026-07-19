from __future__ import annotations

import sys
from pathlib import Path
import math

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from research import worldquant_alpha_lab as lab


def _universe() -> dict[str, pd.DataFrame]:
    idx = pd.date_range("2024-01-01", periods=180, freq="B")
    out = {}
    for n, symbol in enumerate(["SPY", "QQQ", "IWM", "SMH", "GLD", "XLF"]):
        base = 100 + n * 5
        close = pd.Series([
            base
            + i * (0.06 + n * 0.005)
            + math.sin((i + n * 3) / (4 + n)) * (1.0 + n * 0.15)
            + ((i + n) % 11) * 0.05
            for i in range(len(idx))
        ], index=idx)
        out[symbol] = pd.DataFrame({
            "open": close.shift(1).fillna(close.iloc[0]) * 0.999,
            "high": close * 1.01,
            "low": close * 0.99,
            "close": close,
            "volume": [
                1_000_000 + n * 10_000 + i * (50 + n * 11) + math.cos((i + n) / 5) * 5000
                for i in range(len(idx))
            ],
        }, index=idx)
    return out


def test_alpha_scores_returns_cross_sectional_frame() -> None:
    scores = lab.alpha_scores(_universe(), "alpha_012")

    assert set(scores.columns) == {"SPY", "QQQ", "IWM", "SMH", "GLD", "XLF"}
    assert len(scores.dropna(how="all")) > 50


def test_portfolio_returns_are_aligned_to_scores() -> None:
    universe = _universe()
    scores = lab.alpha_scores(universe, "alpha_004")
    close = lab.panel(universe, "close").reindex(scores.index).ffill()

    returns, weights = lab.portfolio_returns(scores, close, top_n=2)

    assert len(returns) == len(scores)
    assert weights.abs().sum(axis=1).max() <= 2.0


def test_run_alpha_lab_returns_ranked_results() -> None:
    results = lab.run_alpha_lab(
        symbols=list(_universe()),
        start="2024-01-01",
        end="2024-09-01",
        alpha_ids=["alpha_003", "alpha_004"],
        universe=_universe(),
    )

    assert [result.alpha_id for result in results]
    assert all(result.status in {"rejected", "paper_candidate"} for result in results)
    assert all(result.metrics.pbo_score >= 0 for result in results)

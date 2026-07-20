from __future__ import annotations

import pandas as pd

from research import higher_timeframe_volume_screen_lab as lab


def frame(rows: int = 500) -> pd.DataFrame:
    index = pd.bdate_range("2024-01-02", periods=rows)
    close = [100 + pos * 0.1 for pos in range(rows)]
    return pd.DataFrame({
        "open": close, "high": [value + 1 for value in close], "low": [value - 1 for value in close],
        "close": close, "volume": [1_000_000 + (pos // 5) * 10_000 for pos in range(rows)],
    }, index=index)


def test_period_candidates_enter_after_completed_period() -> None:
    source = frame()
    rows = lab.period_candidates("SPY", source, "weekly")
    first = rows[0]
    decision = pd.Timestamp(first["decision_date"])
    entry_date = source.index[first["entry_pos"]]
    assert entry_date > decision


def test_volume_filter_reduces_candidate_set_and_is_read_only() -> None:
    source = frame()
    frames = {"SPY": source}
    candidates = lab.period_candidates("SPY", source, "weekly")
    baseline = lab.select_and_replay(frames, candidates, lab.VARIANTS[0], 10)
    filtered = lab.select_and_replay(frames, candidates, lab.VARIANTS[1], 10)
    assert len(filtered) <= len(baseline)


def test_metrics_counts_portfolio_dates_not_underlying_rows() -> None:
    rows = [
        {"decision_date": "2026-01-02", "return": 0.01, "symbol_count": 5},
        {"decision_date": "2026-01-09", "return": -0.005, "symbol_count": 4},
    ]
    result = lab.metrics(rows)
    assert result["periods"] == 2
    assert result["underlying_signals"] == 9


def test_pass_checks_rejects_nonpositive_bootstrap_lower_bound() -> None:
    metric = {
        "expectancy_bps": 10.0,
        "top_one_pct_removed_expectancy_bps": 5.0,
        "bootstrap": {"ci95_bps": [-0.01, 20.0]},
    }
    row = {
        "development_2015_2022": {"expectancy_bps": 10.0},
        "selection_2023": {"expectancy_bps": 10.0},
        "final_2024_plus": metric,
        "triple_cost_final_2024_plus": {"expectancy_bps": 5.0},
    }
    baseline = {"final_2024_plus": {"expectancy_bps": 9.0}}
    checks = lab.pass_checks(row, baseline)
    assert checks["positive_bootstrap_lower_bound"] is False
    assert all(value for key, value in checks.items() if key != "positive_bootstrap_lower_bound")

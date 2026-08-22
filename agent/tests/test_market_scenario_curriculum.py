from __future__ import annotations

from datetime import date, timedelta

import pandas as pd

from research import market_scenario_curriculum as curriculum


NY = "America/New_York"


def _session(day: date, *, future_step: float = 0.05) -> pd.DataFrame:
    index = pd.date_range(f"{day} 09:30", f"{day} 11:30", freq="5min", tz=NY)
    prices = []
    price = 100.0
    for stamp in index:
        price += 0.03 if stamp.strftime("%H:%M") < "10:30" else future_step
        prices.append(price)
    return pd.DataFrame({
        "open": prices,
        "high": [value + 0.02 for value in prices],
        "low": [value - 0.02 for value in prices],
        "close": [value + 0.01 for value in prices],
        "volume": [1000.0] * len(prices),
    }, index=index)


def _episode(day: date, gross: float, *, scenario: str = "trend=bull|or=above_or|range=normal") -> dict:
    return {
        "symbol": "SPY",
        "date": day.isoformat(),
        "checkpoint_et": "10:30",
        "entry_timestamp": f"{day}T10:30:00-04:00",
        "scenario": scenario,
        "gross_long_bps": gross,
        "gross_short_bps": -gross,
    }


def test_episode_features_are_frozen_before_entry() -> None:
    day = date(2026, 7, 1)
    original = _session(day, future_step=0.05)
    altered = original.copy()
    altered.loc[altered.index >= pd.Timestamp(f"{day} 10:30", tz=NY), "close"] += 10.0

    config = curriculum.CurriculumConfig(rolling_context_sessions=5)
    first = curriculum.build_episodes(original, "SPY", checkpoints=("10:30",), config=config)[0]
    second = curriculum.build_episodes(altered, "SPY", checkpoints=("10:30",), config=config)[0]

    for field in ("scenario", "trend_state", "opening_range_state", "range_regime", "vwap", "ema_fast", "ema_slow"):
        assert first[field] == second[field]
    assert first["gross_long_bps"] != second["gross_long_bps"]
    assert first["feature_cutoff"] < first["entry_timestamp"]


def test_policy_requires_cost_and_outlier_robustness() -> None:
    start = date(2026, 1, 1)
    robust = [_episode(start + timedelta(days=i), 20.0) for i in range(40)]
    fragile = [_episode(start + timedelta(days=i), 5.0, scenario="fragile") for i in range(40)]
    config = curriculum.CurriculumConfig(minimum_train_episodes=30, base_round_trip_cost_bps=4.0)

    policy = curriculum.train_policy(robust + fragile, config)

    assert "SPY|10:30|trend=bull|or=above_or|range=normal" in policy
    assert "SPY|10:30|fragile" not in policy


def test_locked_holdout_cannot_change_trained_policy() -> None:
    start = date(2025, 1, 1)
    episodes = [_episode(start + timedelta(days=i), 20.0) for i in range(80)]
    config = curriculum.CurriculumConfig(
        train_sessions=20,
        test_sessions=10,
        locked_holdout_sessions=10,
        minimum_train_episodes=5,
        minimum_review_folds=2,
        minimum_review_oos_trades=10,
        minimum_review_holdout_trades=5,
    )
    first = curriculum.run_curriculum(episodes, config=config)
    damaged = [dict(row) for row in episodes]
    for row in damaged[-10:]:
        row["gross_long_bps"] = -100.0
        row["gross_short_bps"] = 100.0
    second = curriculum.run_curriculum(damaged, config=config)

    assert first["locked_holdout"]["policy_fingerprint"] == second["locked_holdout"]["policy_fingerprint"]
    assert first["locked_holdout"]["result"]["base"]["expectancy_bps"] > 0
    assert second["locked_holdout"]["result"]["base"]["expectancy_bps"] < 0
    assert first["development_end"] < first["locked_holdout_start"]


def test_walk_forward_boundaries_and_execution_authority() -> None:
    start = date(2025, 1, 1)
    episodes = [_episode(start + timedelta(days=i), 20.0) for i in range(80)]
    config = curriculum.CurriculumConfig(
        train_sessions=20,
        test_sessions=10,
        locked_holdout_sessions=10,
        minimum_train_episodes=5,
        minimum_review_folds=2,
        minimum_review_oos_trades=10,
        minimum_review_holdout_trades=5,
    )

    report = curriculum.run_curriculum(episodes, config=config)

    assert report["walk_forward_folds"]
    assert all(fold["train_end"] < fold["test_start"] for fold in report["walk_forward_folds"])
    assert report["walk_forward_summary"]["base"]["expectancy_bps"] > 0
    assert report["execution_enabled"] is False
    assert report["can_submit_orders"] is False
    assert report["promotion_authority"] == "human_review_only"


def test_scenario_attribution_remembers_failures_without_promotion() -> None:
    decisions = [
        {
            "policy_key": "SPY|10:30|failed",
            "action": "long",
            "fold": 1 if i < 15 else 2,
            "base_return_bps": -5.0,
            "double_cost_return_bps": -9.0,
            "triple_cost_return_bps": -13.0,
        }
        for i in range(30)
    ]

    result = curriculum._scenario_attribution(decisions)

    assert result["authority"] == "diagnostic_only_new_trials_required"
    assert result["diagnostic_survivors"] == []
    assert result["recurring_failures"][0]["policy_key"] == "SPY|10:30|failed"
    assert result["recurring_failures"][0]["recurring_failure"] is True

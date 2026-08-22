from __future__ import annotations

import sys
from datetime import datetime, timedelta
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from research.intelligence_edge_meta_policy_lab import (
    ReplayTrade,
    build_report,
    metrics,
    passes_frozen_intelligence_filter,
)
from strategies.topstep_prop_bot import Candle


def _assessment(**overrides: object) -> dict[str, object]:
    row: dict[str, object] = {
        "regime_compatible": True,
        "data_completeness": 0.80,
        "independent_support_families": 3,
        "support_ratio": 0.75,
        "conflict_ratio": 0.10,
        "reward_risk": 1.5,
        "execution_economics_ok": True,
        "friction_to_reward": 0.10,
    }
    row.update(overrides)
    return row


def test_frozen_filter_requires_independent_support_and_low_conflict() -> None:
    assert passes_frozen_intelligence_filter(_assessment()) is True
    assert passes_frozen_intelligence_filter(_assessment(independent_support_families=1)) is False
    assert passes_frozen_intelligence_filter(_assessment(conflict_ratio=0.36)) is False


def test_metrics_remove_best_five_percent_and_measure_drawdown() -> None:
    values = [10.0] * 19 + [1000.0, -40.0]
    trades = [
        ReplayTrade(
            date=f"2026-01-{index + 1:02d}",
            strategy="test",
            side="buy",
            entry_time="",
            exit_time="",
            exit_reason="target",
            intelligence_score=0.8,
            baseline_pnl=value,
            stress_pnl=value,
        )
        for index, value in enumerate(values)
    ]

    result = metrics(trades)

    assert result["trades"] == 21
    assert result["max_drawdown"] == -40.0
    assert result["top5_removed_expectancy"] < result["expectancy"]


def test_report_has_no_execution_authority() -> None:
    start = datetime(2026, 1, 5, 9, 30)
    candles = [
        Candle(start + timedelta(minutes=index), 100, 101, 99, 100, 100)
        for index in range(40)
    ]

    report = build_report(candles)

    assert report["practice_eligible"] is False
    assert report["execution_enabled"] is False
    assert report["can_submit_orders"] is False
    assert report["authority"] == "research_only"

from __future__ import annotations

import sys
from datetime import datetime, timedelta
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from strategies.decision_intelligence import Evidence, assess_decision_intelligence
from strategies.topstep_prop_bot import (
    Candle,
    OpeningRangeConfig,
    assess_futures_signal_intelligence,
    build_opening_range_signal,
    classify_futures_regime,
)


def _candle(minute: int, close: float, *, volume: int = 100) -> Candle:
    return Candle(
        timestamp=datetime(2026, 8, 17, 9, 30) + timedelta(minutes=minute),
        open=close - 0.5,
        high=close + 0.75,
        low=close - 0.75,
        close=close,
        volume=volume,
    )


def test_independent_validated_evidence_can_only_reach_paper_candidate() -> None:
    assessment = assess_decision_intelligence(
        candidate_id="candidate-1",
        desired_direction="bullish",
        evidence=[
            Evidence("breakout", "price_structure", "bullish", 0.8, validated=True),
            Evidence("breadth", "breadth", "bullish", 0.75, validated=True),
            Evidence("regime", "regime", "bullish", 0.7, validated=True),
        ],
        data_completeness=1.0,
        regime="trend",
        regime_compatible=True,
        reward_risk=2.0,
        friction_to_reward=0.1,
        forward_validated_edge=True,
    )

    assert assessment["status"] == "paper_candidate"
    assert assessment["independent_support_families"] == 3
    assert assessment["can_submit_orders"] is False
    assert assessment["can_increase_size"] is False


def test_correlated_indicators_collapse_and_conflict_forces_abstention() -> None:
    assessment = assess_decision_intelligence(
        candidate_id="candidate-2",
        desired_direction="bullish",
        evidence=[
            Evidence("rsi", "price_structure", "bullish", 0.80),
            Evidence("macd", "price_structure", "bullish", 0.70),
            Evidence("higher_timeframe", "trend", "bearish", 0.90),
        ],
        data_completeness=1.0,
        regime="trend",
        regime_compatible=True,
        reward_risk=2.0,
        friction_to_reward=0.1,
        forward_validated_edge=True,
    )

    assert assessment["correlated_evidence_collapsed"] == 1
    assert assessment["independent_support_families"] == 1
    assert assessment["status"] == "abstain"
    assert "evidence_conflict_too_high" in assessment["reasons"]


def test_futures_regime_detects_directional_prefix() -> None:
    candles = [_candle(index, 100 + index * 0.8, volume=100 + index * 5) for index in range(8)]

    regime = classify_futures_regime(candles)

    assert regime.classification == "trend"
    assert regime.direction == "bullish"
    assert regime.efficiency_ratio > 0.9


def test_topstep_intelligence_cannot_see_bars_after_entry() -> None:
    causal = [
        _candle(0, 100.0, volume=100),
        _candle(1, 100.5, volume=100),
        _candle(2, 101.0, volume=100),
        _candle(3, 103.0, volume=300),
    ]
    config = OpeningRangeConfig(range_minutes=3, min_breakout_points=0.5)
    signal = build_opening_range_signal(causal, config, symbol="MES")
    assert signal is not None
    future_reversal = causal + [
        _candle(4, 90.0, volume=1000),
        _candle(5, 80.0, volume=1000),
    ]

    before = assess_futures_signal_intelligence(signal, causal, entry_index=3)
    after = assess_futures_signal_intelligence(signal, future_reversal, entry_index=3)

    assert before == after
    assert before["future_bars_consumed"] == 0
    assert before["forward_validated_edge"] is False
    assert before["status"] != "paper_candidate"

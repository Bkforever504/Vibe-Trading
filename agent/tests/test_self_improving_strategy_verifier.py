from __future__ import annotations

import json
from pathlib import Path

from scripts.self_improving_strategy_verifier import build_report


def _write_json(path: Path, payload: dict) -> Path:
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def test_blocks_high_win_rate_with_negative_expectancy(tmp_path: Path) -> None:
    shadow = _write_json(
        tmp_path / "shadow.json",
        {
            "by_symbol": {
                "TSLA": {
                    "sample_count": 12,
                    "completed_count": 12,
                    "trading_day_count": 30,
                    "winner_count": 8,
                    "win_rate": 0.667,
                    "target_hit_rate": 0.2,
                    "avg_capture_efficiency": 0.4,
                    "avg_win_return_pct": 12,
                    "avg_loss_return_pct": 50,
                    "expectancy_return_pct": -8,
                    "payoff_ratio": 0.24,
                }
            }
        },
    )
    hot = _write_json(tmp_path / "hot.json", {"candidates": [{"symbol": "TSLA", "score": 9, "action": "priority_shadow_review"}]})
    loop = _write_json(tmp_path / "loop.json", {"summary": {"unattended_ready_count": 0, "execution_capable_count": 0}})
    safety = _write_json(tmp_path / "safety.json", {"passed": True, "summary": {"high_risk_count": 0}})
    kronos = _write_json(tmp_path / "kronos.json", {"forecasts": [{"symbol": "TSLA", "confidence": 0.8, "expected_return_pct": 1.2}]})

    report = build_report(
        shadow_eval_path=shadow,
        hot_instrument_path=hot,
        loop_readiness_path=loop,
        incentive_safety_path=safety,
        kronos_forecast_path=kronos,
        today="2026-07-11",
    )

    tsla = report["instruments"][0]
    assert tsla["symbol"] == "TSLA"
    assert "expectancy_not_positive_enough" in tsla["promotion_blockers"]
    assert "losses_too_large_vs_winners" in tsla["promotion_blockers"]
    assert tsla["live_execution_allowed"] is False
    assert report["summary"]["promotion_ready_count"] == 0


def test_requires_out_of_sample_trading_days_even_with_good_sample(tmp_path: Path) -> None:
    shadow = _write_json(
        tmp_path / "shadow.json",
        {
            "by_symbol": {
                "NVDA": {
                    "sample_count": 10,
                    "completed_count": 10,
                    "trading_day_count": 4,
                    "winner_count": 8,
                    "win_rate": 0.8,
                    "target_hit_rate": 0.5,
                    "avg_capture_efficiency": 0.7,
                    "avg_win_return_pct": 55,
                    "avg_loss_return_pct": 20,
                    "expectancy_return_pct": 38,
                    "payoff_ratio": 2.75,
                }
            }
        },
    )
    hot = _write_json(tmp_path / "hot.json", {"candidates": [{"symbol": "NVDA", "score": 10, "social_day_count": 3}]})
    loop = _write_json(tmp_path / "loop.json", {"summary": {"unattended_ready_count": 0, "execution_capable_count": 0}})
    safety = _write_json(tmp_path / "safety.json", {"passed": True, "summary": {"high_risk_count": 0}})
    kronos = _write_json(tmp_path / "kronos.json", {"forecasts": []})

    report = build_report(
        shadow_eval_path=shadow,
        hot_instrument_path=hot,
        loop_readiness_path=loop,
        incentive_safety_path=safety,
        kronos_forecast_path=kronos,
        today="2026-07-11",
    )

    nvda = report["instruments"][0]
    assert "needs_30_trading_days" in nvda["promotion_blockers"]
    assert nvda["action"] == "continue_shadow_memory"


def test_clean_evidence_can_reach_human_review_but_not_live_execution(tmp_path: Path) -> None:
    shadow = _write_json(
        tmp_path / "shadow.json",
        {
            "by_symbol": {
                "SPY": {
                    "sample_count": 42,
                    "completed_count": 36,
                    "trading_day_count": 32,
                    "winner_count": 28,
                    "win_rate": 0.778,
                    "target_hit_rate": 0.52,
                    "avg_capture_efficiency": 0.82,
                    "avg_win_return_pct": 48,
                    "avg_loss_return_pct": 18,
                    "expectancy_return_pct": 33.3,
                    "payoff_ratio": 2.667,
                }
            }
        },
    )
    hot = _write_json(tmp_path / "hot.json", {"candidates": [{"symbol": "SPY", "score": 10, "social_day_count": 5}]})
    loop = _write_json(tmp_path / "loop.json", {"summary": {"unattended_ready_count": 0, "execution_capable_count": 0}})
    safety = _write_json(tmp_path / "safety.json", {"passed": True, "summary": {"high_risk_count": 0}})
    kronos = _write_json(tmp_path / "kronos.json", {"forecasts": [{"symbol": "SPY", "confidence": 0.9, "expected_return_pct": 1.6}]})

    report = build_report(
        shadow_eval_path=shadow,
        hot_instrument_path=hot,
        loop_readiness_path=loop,
        incentive_safety_path=safety,
        kronos_forecast_path=kronos,
        today="2026-07-11",
    )

    spy = report["instruments"][0]
    assert spy["promotion_blockers"] == []
    assert spy["action"] == "human_promotion_review_only"
    assert spy["live_execution_allowed"] is False


def test_reads_real_weekly_report_shape_and_propagates_liquidity_veto(tmp_path: Path) -> None:
    shadow = _write_json(
        tmp_path / "shadow.json",
        {
            "by_symbol": {
                "TSLA": {
                    "sample_count": 40,
                    "completed_count": 36,
                    "trading_day_count": 32,
                    "win_rate": 0.8,
                    "target_hit_rate": 0.6,
                    "avg_capture_efficiency": 0.8,
                    "avg_win_return_pct": 50,
                    "avg_loss_return_pct": 18,
                    "expectancy_return_pct": 35,
                    "payoff_ratio": 2.778,
                }
            }
        },
    )
    hot = _write_json(
        tmp_path / "hot.json",
        {
            "hot_instruments": [{"symbol": "NVDA", "hot_score": 6.0}],
            "verifier_instruments": [
                {
                    "symbol": "TSLA",
                    "hot_score": 9.5,
                    "social_day_count": 5,
                    "action": "research_only",
                    "options_liquidity_checked": True,
                    "options_execution_quality_ok": False,
                }
            ]
        },
    )
    loop = _write_json(tmp_path / "loop.json", {"summary": {"unattended_ready_count": 0, "execution_capable_count": 0}})
    safety = _write_json(tmp_path / "safety.json", {"passed": True, "summary": {"high_risk_count": 0}})
    kronos = _write_json(tmp_path / "kronos.json", {"forecasts": []})

    built = build_report(
        shadow_eval_path=shadow,
        hot_instrument_path=hot,
        loop_readiness_path=loop,
        incentive_safety_path=safety,
        kronos_forecast_path=kronos,
        today="2026-07-11",
    )

    tsla = built["instruments"][0]
    assert tsla["hot_instrument_action"] == "research_only"
    assert tsla["score_components"]["social_hotness"] == 7.0
    assert "instrument_research_only" in tsla["promotion_blockers"]
    assert "options_execution_quality_failed" in tsla["promotion_blockers"]
    assert tsla["action"] == "continue_shadow_memory"


def test_accelerated_thresholds_replace_calendar_wait_without_self_approval(tmp_path: Path) -> None:
    shadow = _write_json(tmp_path / "shadow.json", {
        "by_symbol": {"SPY": {
            "evidence_path": "accelerated_clustered_forward",
            "sample_count": 110,
            "completed_count": 100,
            "trading_day_count": 10,
            "required_completed_count": 100,
            "required_trading_day_count": 10,
            "required_out_of_sample_count": 30,
            "out_of_sample_count": 30,
            "out_of_sample_positive": True,
            "win_rate": 0.8,
            "target_hit_rate": 0.8,
            "avg_capture_efficiency": 0.9,
            "avg_win_return_pct": 55,
            "avg_loss_return_pct": 20,
            "expectancy_return_pct": 40,
            "payoff_ratio": 2.75,
        }}
    })
    hot = _write_json(tmp_path / "hot.json", {"candidates": [{"symbol": "SPY", "score": 10, "social_day_count": 5}]})
    loop = _write_json(tmp_path / "loop.json", {"summary": {"unattended_ready_count": 0, "execution_capable_count": 0}})
    safety = _write_json(tmp_path / "safety.json", {"passed": True, "summary": {"high_risk_count": 0}})
    kronos = _write_json(tmp_path / "kronos.json", {"forecasts": [{"symbol": "SPY", "confidence": 0.9}]})

    report = build_report(
        shadow_eval_path=shadow,
        hot_instrument_path=hot,
        loop_readiness_path=loop,
        incentive_safety_path=safety,
        kronos_forecast_path=kronos,
    )
    spy = report["instruments"][0]
    assert spy["promotion_blockers"] == []
    assert spy["action"] == "human_promotion_review_only"
    assert spy["live_execution_allowed"] is False

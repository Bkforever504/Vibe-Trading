from __future__ import annotations

import json

from scripts.kalshi_weather_readiness import build_report


def _write(path, payload):
    path.write_text(json.dumps(payload), encoding="utf-8")


def test_readiness_blocks_short_sample_and_missing_adapter(tmp_path) -> None:
    performance = tmp_path / "performance.json"
    bot = tmp_path / "bot.json"
    _write(performance, {
        "promotion_grade_closed_count": 12,
        "distinct_target_dates": 2,
        "distinct_city_days": 12,
        "metrics": {"net_pnl_dollars": 3.0, "profit_factor": 1.5, "drawdown_on_risk": 0.10},
        "calibration": {"model_brier_score": 0.18, "brier_skill_vs_market": 0.02},
    })
    _write(bot, {"series_monitored": 13, "events_discovered": 13, "errors": []})

    report = build_report(performance_path=performance, bot_report_path=bot)

    assert report["go_live_eligible"] is False
    assert "insufficient_promotion_grade_closures" in report["blockers"]
    assert "insufficient_target_dates" in report["blockers"]
    assert "authenticated_order_adapter_not_reviewed" in report["blockers"]
    assert report["execution_enabled"] is False
    assert report["can_submit_orders"] is False


def test_readiness_requires_model_to_beat_market_baseline(tmp_path) -> None:
    performance = tmp_path / "performance.json"
    bot = tmp_path / "bot.json"
    _write(performance, {
        "promotion_grade_closed_count": 220,
        "distinct_target_dates": 20,
        "distinct_city_days": 220,
        "metrics": {"net_pnl_dollars": 40.0, "profit_factor": 2.0, "drawdown_on_risk": 0.10},
        "calibration": {"model_brier_score": 0.17, "brier_skill_vs_market": -0.01},
    })
    _write(bot, {"series_monitored": 13, "events_discovered": 13, "errors": []})

    report = build_report(performance_path=performance, bot_report_path=bot, authenticated_adapter_reviewed=True)

    assert "model_does_not_beat_market_calibration" in report["blockers"]
    assert report["go_live_eligible"] is False

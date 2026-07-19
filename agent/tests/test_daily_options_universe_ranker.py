from __future__ import annotations

import json
from pathlib import Path

from scripts import daily_options_universe_ranker as ranker


def _write(path: Path, value: dict) -> Path:
    path.write_text(json.dumps(value), encoding="utf-8")
    return path


def test_ranker_keeps_spy_benchmark_and_challengers_shadow_only(tmp_path: Path) -> None:
    weekly = _write(tmp_path / "weekly.json", {"hot_instruments": [
        {"symbol": "SPY", "hot_score": 8, "deep_universe_score": 5},
        {"symbol": "NVDA", "hot_score": 11, "deep_universe_score": 8},
    ]})
    liquidity = _write(tmp_path / "liquidity.json", {"results": [
        {"symbol": "SPY", "status": "ok", "score": 4, "verdict": "qualified", "flip_shadow_eligible": True},
        {"symbol": "NVDA", "status": "ok", "score": 4, "verdict": "qualified", "flip_shadow_eligible": True},
    ]})
    shadow = _write(tmp_path / "shadow.json", {"by_symbol": {
        "NVDA": {"completed_count": 2, "trading_day_count": 2, "out_of_sample_count": 2, "out_of_sample_positive": False, "expectancy_return_pct": -20},
    }})
    catalyst = _write(tmp_path / "catalyst.json", {"today": {"max_impact": "high", "allowed_playbooks": ["stand_aside"], "vetoes": ["event"]}})

    result = ranker.build_report(weekly_path=weekly, liquidity_path=liquidity, shadow_path=shadow, catalyst_path=catalyst, surface_path=None, today="2026-07-13")
    nvda = next(row for row in result["rankings"] if row["symbol"] == "NVDA")

    assert result["execution_enabled"] is False
    assert result["can_submit_orders"] is False
    assert result["non_spy_execution_allowed"] is False
    assert result["execution_benchmark"]["symbol"] == "SPY"
    assert nvda["tier"] == "shadow_challenger"
    assert nvda["evidence_cap"] == 49.0
    assert "positive_out_of_sample_edge_not_proven" in nvda["blockers"]


def test_ranker_liquidity_veto_blocks_socially_hot_symbol(tmp_path: Path) -> None:
    weekly = _write(tmp_path / "weekly.json", {"hot_instruments": [{"symbol": "TSLA", "hot_score": 99, "deep_universe_score": 10}]})
    liquidity = _write(tmp_path / "liquidity.json", {"results": [{"symbol": "TSLA", "status": "ok", "score": 2, "verdict": "not_qualified", "flip_shadow_eligible": False}]})
    shadow = _write(tmp_path / "shadow.json", {"by_symbol": {}})
    catalyst = _write(tmp_path / "catalyst.json", {})

    result = ranker.build_report(weekly_path=weekly, liquidity_path=liquidity, shadow_path=shadow, catalyst_path=catalyst, surface_path=None)
    tsla = next(row for row in result["rankings"] if row["symbol"] == "TSLA")

    assert tsla["tier"] == "blocked"
    assert "options_liquidity_gate_failed" in tsla["blockers"]


def test_ranker_requires_full_forward_evidence_for_top_cap(tmp_path: Path) -> None:
    weekly = _write(tmp_path / "weekly.json", {"hot_instruments": [{"symbol": "QQQ", "hot_score": 12, "deep_universe_score": 10}]})
    liquidity = _write(tmp_path / "liquidity.json", {"results": [{"symbol": "QQQ", "status": "ok", "score": 5, "verdict": "qualified", "flip_shadow_eligible": True}]})
    shadow = _write(tmp_path / "shadow.json", {"by_symbol": {"QQQ": {
        "completed_count": 50, "trading_day_count": 60, "out_of_sample_count": 50,
        "out_of_sample_positive": True, "out_of_sample_expectancy_return_pct": 12,
        "out_of_sample_win_rate": 0.62, "promotion_eligible": True,
    }}})
    catalyst = _write(tmp_path / "catalyst.json", {})

    result = ranker.build_report(weekly_path=weekly, liquidity_path=liquidity, shadow_path=shadow, catalyst_path=catalyst, surface_path=None)
    qqq = next(row for row in result["rankings"] if row["symbol"] == "QQQ")

    assert qqq["tier"] == "promotion_review"
    assert qqq["evidence_cap"] == 100.0
    assert result["non_spy_execution_allowed"] is False


def test_surface_lottery_risk_blocks_only_shadow_ranking(tmp_path: Path) -> None:
    weekly = _write(tmp_path / "weekly.json", {"hot_instruments": [{"symbol": "RIVN", "hot_score": 12}]})
    liquidity = _write(tmp_path / "liquidity.json", {"results": [{"symbol": "RIVN", "status": "ok", "score": 5, "verdict": "qualified", "flip_shadow_eligible": True}]})
    shadow = _write(tmp_path / "shadow.json", {"by_symbol": {}})
    catalyst = _write(tmp_path / "catalyst.json", {})
    surface = _write(tmp_path / "surface.json", {"results": [{
        "symbol": "RIVN", "status": "ok", "surface_usable_for_shadow_research": True,
        "retail_lottery_risk": True, "retail_lottery_risk_reasons": ["cheap_high_iv_wide_spread_wings"],
        "institutional_flow_available": False,
    }]})

    result = ranker.build_report(
        weekly_path=weekly, liquidity_path=liquidity, shadow_path=shadow,
        catalyst_path=catalyst, surface_path=surface,
    )
    rivn = next(row for row in result["rankings"] if row["symbol"] == "RIVN")

    assert rivn["tier"] == "blocked"
    assert "cheap_option_retail_lottery_risk" in rivn["blockers"]
    assert rivn["institutional_flow_available"] is False
    assert result["non_spy_execution_allowed"] is False

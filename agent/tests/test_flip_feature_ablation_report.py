from __future__ import annotations

import json
from pathlib import Path

from scripts import flip_feature_ablation_report as report


def _trade(index: int, feature: bool, return_pct: float, strategy: str = "trend") -> dict:
    entry = 1.0
    return {
        "id": f"trade-{index}",
        "status": "closed",
        "entry_price": entry,
        "exit_price": entry * (1 + return_pct / 100),
        "entry_quality": {
            "feature_snapshot": {
                "schema_version": 1,
                "strategy": strategy,
                "above_vwap": feature,
                "breadth_count": 3 if feature else 1,
            }
        },
    }


def test_strong_forward_separation_is_review_only(tmp_path: Path) -> None:
    trades = [_trade(i, i < 20, 10 + i % 3 if i < 20 else -10 - i % 3) for i in range(40)]
    path = tmp_path / "trades.json"
    path.write_text(json.dumps(trades), encoding="utf-8")

    result = report.build_report(path)
    above_vwap = next(row for row in result["features"] if row["feature"] == "above_vwap")

    assert result["feature_telemetry_trade_count"] == 40
    assert above_vwap["present_count"] == 20
    assert above_vwap["absent_count"] == 20
    assert above_vwap["bonferroni_pass"] is True
    assert above_vwap["review_eligible"] is True
    assert result["execution_enabled"] is False
    assert result["can_submit_orders"] is False


def test_small_or_legacy_sample_cannot_be_review_eligible(tmp_path: Path) -> None:
    trades = [_trade(i, i < 6, 5 if i < 6 else -5) for i in range(12)]
    trades.append({"id": "legacy", "status": "closed", "entry_price": 1, "exit_price": 2})
    path = tmp_path / "trades.json"
    path.write_text(json.dumps(trades), encoding="utf-8")

    result = report.build_report(path)
    above_vwap = next(row for row in result["features"] if row["feature"] == "above_vwap")

    assert result["insufficient_or_legacy_count"] == 1
    assert above_vwap["review_eligible"] is False
    assert "fewer_than_30_known_feature_trades" in above_vwap["review_blockers"]
    assert above_vwap["p_value"] is None


def test_missing_trade_file_produces_safe_empty_report(tmp_path: Path) -> None:
    result = report.build_report(tmp_path / "missing.json")

    assert result["closed_trade_count"] == 0
    assert result["feature_family_count"] == 0
    assert result["review_eligible_count"] == 0


def test_categorical_feature_uses_other_known_category_as_absent(tmp_path: Path) -> None:
    trades = [
        _trade(i, True, 10, strategy="bull_trend" if i < 20 else "bear_trend")
        for i in range(40)
    ]
    path = tmp_path / "trades.json"
    path.write_text(json.dumps(trades), encoding="utf-8")

    result = report.build_report(path)
    bull = next(row for row in result["features"] if row["feature"] == "strategy__bull_trend")

    assert bull["present_count"] == 20
    assert bull["absent_count"] == 20

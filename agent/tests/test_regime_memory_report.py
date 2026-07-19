from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts import regime_memory_report as regime


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    path.write_text("\n".join(json.dumps(row) for row in rows) + "\n", encoding="utf-8")


def test_build_report_groups_outcomes_by_regime(tmp_path: Path) -> None:
    outcome = tmp_path / "outcome.jsonl"
    market_force = tmp_path / "market_force.jsonl"
    breadth = tmp_path / "breadth.jsonl"
    distribution = tmp_path / "distribution.jsonl"
    sector = tmp_path / "sector.jsonl"
    exposure = tmp_path / "exposure.jsonl"
    _write_jsonl(outcome, [
        {"date": "2026-06-29", "posture": "normal", "verdict": "posture_helpful", "event_summary": {"realized_pnl": 100, "trade_count": 1, "guard_block_count": 0}},
        {"date": "2026-06-30", "posture": "cautious", "verdict": "posture_helpful", "event_summary": {"realized_pnl": -50, "trade_count": 1, "guard_block_count": 2}},
    ])
    _write_jsonl(market_force, [
        {"date": "2026-06-29", "classification": "bullish_lean", "total_score": 2},
        {"date": "2026-06-30", "classification": "mixed", "total_score": 0},
    ])
    _write_jsonl(breadth, [{"date": "2026-06-30", "breadth": {"uptrend_status": "under_pressure"}}])
    _write_jsonl(distribution, [{"date": "2026-06-30", "aggregate": {"regime": "caution"}}])
    _write_jsonl(sector, [{"date": "2026-06-30", "rotation": {"leadership": "risk_on_leadership"}}])
    _write_jsonl(exposure, [{"date": "2026-06-30", "posture": "cautious"}])

    report = regime.build_report(
        paths={
            "outcome": outcome,
            "market_force": market_force,
            "breadth": breadth,
            "distribution": distribution,
            "sector_rotation": sector,
            "exposure": exposure,
        },
        min_days=2,
    )

    assert report["day_count"] == 2
    assert report["enough_data"] is True
    labels = {row["label"] for row in report["regime_groups"]["market_force"]}
    assert {"bullish_lean", "mixed"} <= labels


def test_regime_memory_warns_when_log_building(tmp_path: Path) -> None:
    paths = {name: tmp_path / f"{name}.jsonl" for name in regime.SOURCE_PATHS}
    _write_jsonl(paths["outcome"], [{"date": "2026-06-30", "event_summary": {"realized_pnl": 0}}])

    report = regime.build_report(paths=paths, min_days=3)

    assert report["enough_data"] is False
    assert any("LOG BUILDING" in warning for warning in report["warnings"])

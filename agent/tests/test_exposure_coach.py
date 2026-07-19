from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts import exposure_coach as coach


def test_derive_posture_cash_priority_on_risk_veto() -> None:
    posture = coach.derive_posture(
        {"total_score": 5, "classification": "bullish_confirmation", "risk_veto": {"active": True}},
        None,
        None,
    )

    assert posture["posture"] == "cash_priority"
    assert posture["advisory_settings"]["risk_multiplier"] == 0.0


def test_derive_posture_downgrades_for_severe_distribution() -> None:
    posture = coach.derive_posture(
        {"total_score": 1, "classification": "bullish_lean", "risk_veto": {"active": False}},
        {"breadth": {"uptrend_status": "uptrend_under_pressure"}},
        {"aggregate": {"regime": "severe"}},
    )

    assert posture["posture"] == "cautious"
    assert any("severe distribution" in reason for reason in posture["reasons"])


def test_build_report_is_read_only(tmp_path: Path, monkeypatch) -> None:
    paths = {name: tmp_path / f"{name}.jsonl" for name in coach.SOURCE_PATHS}
    paths["market_force"].write_text(json.dumps({"date": "2026-06-30", "total_score": 3, "classification": "bullish_confirmation", "risk_veto": {"active": False}}) + "\n", encoding="utf-8")
    paths["breadth"].write_text(json.dumps({"date": "2026-06-30", "breadth": {"uptrend_status": "confirmed_uptrend"}}) + "\n", encoding="utf-8")
    paths["distribution"].write_text(json.dumps({"date": "2026-06-30", "aggregate": {"regime": "normal"}}) + "\n", encoding="utf-8")

    report = coach.build_report(day="2026-06-30", paths=paths)

    assert report["execution_enabled"] is False
    assert report["posture"] == "aggressive"


def test_append_log_writes_jsonl(tmp_path: Path) -> None:
    path = tmp_path / "coach.jsonl"
    report = {"date": "2026-06-30", "provider": "exposure_coach"}

    coach.append_log(report, path)

    assert json.loads(path.read_text(encoding="utf-8").strip()) == report

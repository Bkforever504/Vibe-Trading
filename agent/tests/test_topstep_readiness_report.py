from __future__ import annotations

import json
from pathlib import Path

from scripts.topstep_readiness_report import build_report


def _write(path: Path, value: dict) -> Path:
    path.write_text(json.dumps(value), encoding="utf-8")
    return path


def test_readiness_stays_blocked_without_promoted_candidate_or_broker_fills(tmp_path: Path) -> None:
    reports = {
        "candidate": _write(tmp_path / "candidate.json", {"promotion": {"ready": False, "decision": "rejected"}}),
    }
    env = tmp_path / ".env"
    env.write_text(
        "TOPSTEPX_USERNAME=user\nTOPSTEPX_API_KEY=secret\nTOPSTEPX_LOCAL_DEVICE=PERSONAL_DEVICE_CONFIRMED\n",
        encoding="utf-8",
    )
    recorder = _write(tmp_path / "recorder.json", {"status": "ok"})
    reconciliation = _write(tmp_path / "reconciliation.json", {"status": "no_broker_confirmed_round_trips", "round_trip_count": 0})

    report = build_report(
        report_paths=reports,
        env_path=env,
        probe_path=tmp_path / "missing-probe.json",
        recorder_path=recorder,
        reconciliation_path=reconciliation,
        route_path=tmp_path / "missing-route.json",
    )

    assert report["overall_status"] == "blocked"
    assert "no_broker_confirmed_round_trips" in report["blockers"]
    assert "no_strategy_passed_promotion_gate" in report["blockers"]
    assert report["execution_enabled"] is False
    assert report["operations"]["credential_fields_present"]["TOPSTEPX_API_KEY"] is True


import json
import subprocess
from datetime import datetime, timedelta, timezone

from scripts import shadow_system_heartbeat as heartbeat


def test_scheduler_timeout_preserves_health_evidence(monkeypatch, tmp_path):
    def timeout(*args, **kwargs):
        raise subprocess.TimeoutExpired("powershell.exe", kwargs["timeout"])
    monkeypatch.setattr(heartbeat.subprocess, "run", timeout)
    monkeypatch.setattr(heartbeat, "is_halted", lambda _: False)
    monkeypatch.setattr(heartbeat, "read_state", lambda _: {})
    monkeypatch.setattr(heartbeat, "kill_switch_active", lambda: False)
    missing = tmp_path / "missing"
    report = heartbeat.build_report(now=datetime(2026, 9, 7, 17, tzinfo=timezone.utc),
        hmm_path=missing, catalyst_path=missing, databento_capability_path=missing,
        mnq_evidence_path=missing, pattern_outcomes_path=missing)
    assert report["status"] == "FAIL"
    assert report["task_probe"]["status"] == "unavailable"
    assert report["task_probe"]["errors"] == ["timeout"]
    assert report["marketwide_radar"]["tasks"][0]["state"] == "Unknown"
    assert report["hmm"]["status"] == "missing"
    assert report["execution_enabled"] is False


def test_holiday_has_no_phantom_gap(tmp_path):
    report = heartbeat.report_scanner_gaps((("radar", tmp_path / "absent"),),
        now=datetime(2026, 9, 7, 17, tzinfo=timezone.utc))
    assert report["session_started"] is False
    assert report["any_stalled"] is False
    assert report["status"] == "market_closed"


def test_early_close_and_after_hours_rows_do_not_invent_gap(tmp_path):
    path = tmp_path / "cadence.jsonl"
    start = datetime(2026, 11, 27, 14, 35, tzinfo=timezone.utc)
    stamps = [start + timedelta(minutes=10 * n) for n in range(21)]
    stamps += [datetime(2026, 11, 27, 23, tzinfo=timezone.utc)]
    path.write_text("\n".join(json.dumps({"generated_at": s.isoformat()}) for s in stamps))
    report = heartbeat.report_scanner_gaps((("radar", path),),
        now=datetime(2026, 11, 27, 22, tzinfo=timezone.utc))
    assert report["in_regular_session"] is False
    assert report["any_stalled"] is False
    assert report["worst_gap_minutes"] == 10


def test_calendar_failure_is_not_healthy(monkeypatch, tmp_path):
    def unavailable(_):
        raise RuntimeError("calendar unavailable")
    monkeypatch.setattr(heartbeat, "_equity_session", unavailable)
    result = heartbeat.report_scanner_gaps((("radar", tmp_path / "absent"),),
        now=datetime(2026, 9, 8, 17, tzinfo=timezone.utc))
    assert result["status"] == "calendar_unavailable"
    assert result["any_stalled"] is None


def test_probe_queries_single_scheduler_connection(monkeypatch):
    calls = []
    def run(command, **kwargs):
        calls.append((command, kwargs))
        return subprocess.CompletedProcess(command, 0, stdout='[]')
    monkeypatch.setattr(heartbeat.subprocess, "run", run)
    rows = heartbeat.probe_tasks()
    assert len(calls) == 1
    assert "Schedule.Service" in calls[0][0][-1]
    assert "Get-ScheduledTaskInfo" not in calls[0][0][-1]
    assert calls[0][1]["timeout"] <= 30
    assert len(rows) == len(heartbeat.EXPECTED_TASKS)
    assert all(row["ProbeError"] == "missing_probe_row" for row in rows)

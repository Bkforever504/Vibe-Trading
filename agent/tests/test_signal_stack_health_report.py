from __future__ import annotations

import json
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts import signal_stack_health_report as report


def test_latest_jsonl_ignores_bad_lines_and_returns_latest(tmp_path: Path) -> None:
    path = tmp_path / "sample.jsonl"
    path.write_text(
        '{"date":"2026-06-29","value":1}\n'
        'not-json\n'
        '{"date":"2026-06-30","value":2}\n',
        encoding="utf-8",
    )

    latest, count, warning = report._latest_jsonl(path)

    assert latest == {"date": "2026-06-30", "value": 2}
    assert count == 2
    assert warning == "invalid_json_lines=1"


def test_build_report_flags_missing_stale_error_and_ok(monkeypatch, tmp_path: Path) -> None:
    ok_log = tmp_path / "ok.jsonl"
    ok_log.write_text('{"date":"2026-06-30","primary":{"action":"flat"}}\n', encoding="utf-8")
    stale_log = tmp_path / "stale.jsonl"
    stale_log.write_text('{"date":"2026-06-29"}\n', encoding="utf-8")
    error_log = tmp_path / "error.jsonl"
    error_log.write_text(
        json.dumps({"date": "2026-06-30", "scans": [{"symbol": "IWM", "status": "error", "error": "no chain"}]}) + "\n",
        encoding="utf-8",
    )

    monkeypatch.setattr(
        report,
        "SIGNALS",
        [
            {"name": "OK", "task": "ok-task", "log": ok_log, "kind": "close"},
            {"name": "Stale", "task": "stale-task", "log": stale_log, "kind": "close"},
            {"name": "Missing", "task": "missing-task", "log": tmp_path / "missing.jsonl", "kind": "morning"},
            {"name": "Error", "task": "error-task", "log": error_log, "kind": "morning"},
        ],
    )
    monkeypatch.setattr(
        report,
        "_task_status",
        lambda task: {"available": True, "status": "Ready", "next_run_time": "6/30/2026 3:20:00 PM"},
    )

    built = report.build_report(today=date(2026, 6, 30))

    assert built["summary"] == {"ok": 1, "stale": 1, "missing": 1, "error": 1}
    statuses = {item["name"]: item["health"] for item in built["items"]}
    assert statuses == {"OK": "ok", "Stale": "stale", "Missing": "missing", "Error": "error"}

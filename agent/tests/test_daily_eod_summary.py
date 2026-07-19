from __future__ import annotations

import csv
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts import daily_eod_summary as eod


def test_activity_counts_rolls_up_csv_events() -> None:
    events = [
        {"event_type": "trade", "source": "flip_bot", "pnl": "100"},
        {"event_type": "trade", "source": "iwm_options_bot", "pnl": "-25"},
        {"event_type": "guard_block", "source": "alpaca_execution_guard", "reason": "duplicate_symbol_exposure"},
        {"event_type": "shadow_signal", "source": "rsi2_shadow"},
    ]

    result = eod._activity_counts(events)

    assert result["event_count"] == 4
    assert result["trade_count"] == 2
    assert result["guard_block_count"] == 1
    assert result["realized_pnl_from_csv"] == 75
    assert result["guard_reasons"]["duplicate_symbol_exposure"] == 1


def test_make_verdict_green_when_stack_clean() -> None:
    verdict, positives, actions = eod._make_verdict(
        {"summary": {"ok": 21, "missing": 0, "error": 0}},
        {"by_ops_grade": {"A": 20}, "promotion_ready_count": 0, "items": []},
        {"passed": True, "issue_count": 0},
        {"guard_block_count": 2},
        {"queue_count": 0},
        {"passed": True, "issue_count": 0},
    )

    assert verdict == "green"
    assert any("Execution audit passed" in item for item in positives)
    assert any("keep collecting evidence" in item for item in actions)


def test_make_verdict_action_required_on_audit_issue() -> None:
    verdict, _positives, actions = eod._make_verdict(
        {"summary": {"ok": 20, "missing": 1, "error": 0}},
        {"by_ops_grade": {"A": 20}, "promotion_ready_count": 0, "items": []},
        {"passed": False, "issue_count": 1},
        {"guard_block_count": 0},
        {"queue_count": 0},
        {"passed": True, "issue_count": 0},
    )

    assert verdict == "action_required"
    assert any("execution-gate-audit" in item for item in actions)


def test_make_verdict_action_required_on_option_position_mismatch() -> None:
    verdict, _positives, actions = eod._make_verdict(
        {"summary": {"ok": 44, "missing": 0, "error": 0}},
        {"by_ops_grade": {"A": 20}, "promotion_ready_count": 0, "items": []},
        {"passed": True, "issue_count": 0},
        {"guard_block_count": 0},
        {"queue_count": 0},
        {"passed": True, "issue_count": 0},
        {
            "status": "review_required",
            "option_position_integrity": {
                "status": "review_required",
                "missing_active_legs": ["IWM260807P00277000"],
            },
        },
    )

    assert verdict == "action_required"
    assert any("reconcile" in item.lower() for item in actions)


def test_build_report_reads_report_folder(tmp_path: Path, monkeypatch) -> None:
    report_dir = tmp_path / "reports"
    report_dir.mkdir()
    (report_dir / "signal-stack-health.json").write_text(json.dumps({"summary": {"ok": 21, "missing": 0, "error": 0}}), encoding="utf-8")
    (report_dir / "signal-stack-grades.json").write_text(json.dumps({
        "by_ops_grade": {"A": 2},
        "by_grade": {"F": 2},
        "by_maturity_stage": {"log_building": 2},
        "promotion_ready_count": 0,
        "items": [],
    }), encoding="utf-8")
    (report_dir / "execution-gate-audit.json").write_text(json.dumps({"passed": True, "issue_count": 0, "warning_count": 1}), encoding="utf-8")
    (report_dir / "market-schedule-alignment.json").write_text(json.dumps({"passed": True, "issue_count": 0, "warning_count": 0, "aligned_count": 38, "task_count": 38}), encoding="utf-8")
    (report_dir / "needs-review-queue.json").write_text(json.dumps({"queue_count": 0}), encoding="utf-8")
    (report_dir / "daily-outcome-review.json").write_text(json.dumps({"verdict": "no_execution_sample", "event_summary": {"realized_pnl": 0}}), encoding="utf-8")
    (report_dir / "bot-status-snapshot.json").write_text(
        json.dumps({"status": "normal", "status_flags": [], "option_position_integrity": {"status": "ok"}}),
        encoding="utf-8",
    )
    with (report_dir / "daily-bot-activity-2026-06-30.csv").open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["event_type", "source", "pnl", "reason"])
        writer.writeheader()
        writer.writerow({"event_type": "trade", "source": "flip_bot", "pnl": "10", "reason": ""})

    monkeypatch.setattr(eod, "REPORT_DIR", report_dir)

    report = eod.build_report("2026-06-30")

    assert report["execution_enabled"] is False
    assert report["verdict"] == "green"
    assert report["activity"]["trade_count"] == 1
    assert report["activity"]["realized_pnl_from_csv"] == 10
    assert report["schedule_alignment"]["passed"] is True

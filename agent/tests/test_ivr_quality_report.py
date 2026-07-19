from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts import ivr_quality_report as quality


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    path.write_text("\n".join(json.dumps(row) for row in rows) + "\n", encoding="utf-8")


def test_build_report_marks_clean_early_history_as_building(tmp_path: Path) -> None:
    log = tmp_path / "iv_history.jsonl"
    _write_jsonl(log, [
        {
            "date": "2026-07-01",
            "timestamp": "2026-07-01T13:35:00Z",
            "scans": [
                {"symbol": "SPY", "status": "accumulating", "atm_iv": 0.22, "ivr": None, "history_days": 2},
                {"symbol": "QQQ", "status": "accumulating", "atm_iv": 0.23, "ivr": None, "history_days": 2},
                {"symbol": "IWM", "status": "accumulating", "atm_iv": 0.17, "ivr": None, "history_days": 2},
            ],
        }
    ])

    report = quality.build_report(ivr_log_path=log, symbols=["SPY", "QQQ", "IWM"])

    assert report["execution_enabled"] is False
    assert report["overall_status"] == "building"
    assert report["summary"]["coverage_rate"] == 1.0
    assert report["summary"]["true_ivr_rate"] == 0.0


def test_build_report_flags_missing_symbol_or_errors(tmp_path: Path) -> None:
    log = tmp_path / "iv_history.jsonl"
    _write_jsonl(log, [
        {
            "date": "2026-07-01",
            "scans": [
                {"symbol": "SPY", "status": "error", "error": "ATM IV unavailable"},
                {"symbol": "QQQ", "status": "ok", "atm_iv": 0.23, "ivr": 54.1, "history_days": 31},
            ],
        }
    ])

    report = quality.build_report(ivr_log_path=log, symbols=["SPY", "QQQ", "IWM"])

    assert report["overall_status"] == "needs_attention"
    detail = {row["symbol"]: row for row in report["symbols_detail"]}
    assert detail["SPY"]["status"] == "needs_attention"
    assert detail["IWM"]["status"] == "missing"


def test_build_report_marks_mature_true_ivr_as_good(tmp_path: Path) -> None:
    log = tmp_path / "iv_history.jsonl"
    rows = []
    for idx in range(3):
        rows.append({
            "date": f"2026-07-0{idx + 1}",
            "scans": [
                {"symbol": "SPY", "status": "ok", "atm_iv": 0.2, "ivr": 50.0, "history_days": 31 + idx},
            ],
        })
    _write_jsonl(log, rows)

    report = quality.build_report(ivr_log_path=log, symbols=["SPY"])

    assert report["overall_status"] == "good"
    assert report["summary"]["true_ivr_rate"] == 1.0

from __future__ import annotations

import json
from pathlib import Path

from scripts import option_quote_sample_coverage as coverage


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    path.write_text("\n".join(json.dumps(row) for row in rows) + "\n", encoding="utf-8")


def _sample(event: str) -> dict:
    return {
        "event": event,
        "captured_at": f"2026-07-15T14:30:0{len(event)}Z",
        "trade_id": "trade-1",
        "order_id": "order-1",
        "contract": "SPY260715C00750000",
        "provenance": {"status": "ok"},
    }


def test_missing_sample_file_reports_zero_coverage(tmp_path: Path) -> None:
    built = coverage.build_report(tmp_path / "missing.jsonl")

    assert built["execution_enabled"] is False
    assert built["can_submit_orders"] is False
    assert built["samples_file_exists"] is False
    assert built["sample_count"] == 0
    assert built["complete_fill_monitor_exit_key_count"] == 0


def test_complete_key_requires_fill_monitor_and_exit(tmp_path: Path) -> None:
    path = tmp_path / "samples.jsonl"
    _write_jsonl(path, [_sample("fill"), _sample("monitor"), _sample("exit")])

    built = coverage.build_report(path)

    assert built["samples_file_exists"] is True
    assert built["sample_count"] == 3
    assert built["event_counts"] == {"exit": 1, "fill": 1, "monitor": 1}
    assert built["complete_fill_monitor_exit_key_count"] == 1

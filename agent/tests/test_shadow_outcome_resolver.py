from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from scripts.shadow_outcome_resolver import LEDGER_NAMES, build_resolutions, run_once


NOW = datetime(2026, 8, 20, 20, 30, tzinfo=timezone.utc)


def ledger_rows() -> list[dict]:
    return [
        {"type": "candidate", "candidate_id": "plan-1", "created_at": "2026-08-20T14:30:00Z", "executable_entry_credit": 1.0, "max_risk_per_contract": 400},
        {"type": "mark", "candidate_id": "plan-1", "marked_at": "2026-08-20T14:35:00Z", "executable_close_debit": 0.8},
        {"type": "mark", "candidate_id": "plan-1", "marked_at": "2026-08-20T14:40:00Z", "executable_close_debit": 1.25},
        {"type": "outcome", "candidate_id": "plan-1", "resolved_at": "2026-08-20T15:00:00Z", "closing_debit": 0.5, "pnl_before_fees": 50, "quantity": 1, "reason": "profit_target"},
    ]


def test_resolver_uses_executable_marks_and_terminal_fill() -> None:
    rows = build_resolutions({"ledger.jsonl": ledger_rows()}, resolved_at=NOW)

    assert len(rows) == 1
    row = rows[0]
    assert row["entry_fill_executable"] == 1.0
    assert row["exit_fill_executable"] == 0.5
    assert row["mfe"] == pytest.approx(0.2)
    assert row["mae"] == pytest.approx(-0.25)
    assert row["outcome_r"] == 0.125
    assert row["time_in_trade_minutes"] == 30.0
    assert row["execution_enabled"] is False
    assert row["can_submit_orders"] is False


def test_run_once_is_append_only_and_idempotent(tmp_path: Path) -> None:
    ledger = tmp_path / LEDGER_NAMES[0]
    ledger.write_text("".join(json.dumps(row) + "\n" for row in ledger_rows()), encoding="utf-8")
    output = tmp_path / "outcomes.jsonl"

    first = run_once(data_dir=tmp_path, output_path=output, now=NOW)
    original = output.read_bytes()
    second = run_once(data_dir=tmp_path, output_path=output, now=NOW)

    assert first["resolved_count"] == 1
    assert second["resolved_count"] == 0
    assert output.read_bytes() == original

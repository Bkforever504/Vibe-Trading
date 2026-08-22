from __future__ import annotations

import json
import subprocess
from datetime import date
from pathlib import Path

from scripts.post_trade_learning_cycle import DATED_STEPS, GLOBAL_STEPS, run_cycle


def _write(path: Path, value: object) -> None:
    path.write_text(json.dumps(value), encoding="utf-8")


def test_cycle_processes_each_closed_trade_once(tmp_path: Path) -> None:
    trades = tmp_path / "trades.json"
    state = tmp_path / "state.json"
    report = tmp_path / "report.json"
    _write(trades, [
        {"id": "closed-1", "status": "closed", "exit_date": "2026-08-18"},
        {"id": "open-1", "status": "open", "entry_date": "2026-08-18"},
    ])
    calls: list[list[str]] = []

    def runner(command, **kwargs):
        calls.append(command)
        return subprocess.CompletedProcess(command, 0, "", "")

    first, first_code = run_cycle(trades, state, report, runner, current_day=date(2026, 8, 18))
    second, second_code = run_cycle(trades, state, report, runner, current_day=date(2026, 8, 18))

    assert first_code == 0
    assert first["status"] == "processed"
    assert first["new_trade_ids"] == ["closed-1"]
    assert len(calls) == len(DATED_STEPS) + len(GLOBAL_STEPS)
    assert second_code == 0
    assert second["status"] == "no_new_closed_trades"
    assert json.loads(state.read_text(encoding="utf-8"))["processed_trade_ids"] == ["closed-1"]


def test_cycle_retries_when_a_learning_step_fails(tmp_path: Path) -> None:
    trades = tmp_path / "trades.json"
    state = tmp_path / "state.json"
    report = tmp_path / "report.json"
    _write(trades, [{"id": "closed-1", "status": "closed", "exit_date": "2026-08-18"}])

    def runner(command, **kwargs):
        code = 1 if command[1].endswith("daily_outcome_reviewer.py") else 0
        return subprocess.CompletedProcess(command, code, "", "failed")

    result, code = run_cycle(trades, state, report, runner, current_day=date(2026, 8, 18))

    assert code == 1
    assert result["status"] == "failed"
    assert result["new_trade_ids"] == ["closed-1"]
    assert not state.exists()


def test_cycle_bootstrap_does_not_reprocess_old_history(tmp_path: Path) -> None:
    trades = tmp_path / "trades.json"
    state = tmp_path / "state.json"
    report = tmp_path / "report.json"
    _write(trades, [
        {"id": "old", "status": "closed", "exit_date": "2026-08-15"},
        {"id": "today", "status": "closed", "exit_date": "2026-08-18"},
    ])
    calls: list[list[str]] = []

    def runner(command, **kwargs):
        calls.append(command)
        return subprocess.CompletedProcess(command, 0, "", "")

    result, code = run_cycle(trades, state, report, runner, current_day=date(2026, 8, 18))

    assert code == 0
    assert result["new_trade_ids"] == ["today"]
    assert set(json.loads(state.read_text(encoding="utf-8"))["processed_trade_ids"]) == {"old", "today"}

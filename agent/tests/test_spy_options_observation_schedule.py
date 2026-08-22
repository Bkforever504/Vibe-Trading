from __future__ import annotations

from pathlib import Path

from scripts import market_schedule_alignment as alignment


def test_spy_options_tasks_are_governed_at_central_times() -> None:
    assert alignment.EXPECTED_TASKS[r"\SPY-Theta-Harvester-Entry"] == {"08:45"}
    assert alignment.EXPECTED_TASKS[r"\SPY-Iron-Condor-Entry"] == {"08:45"}
    assert alignment.EXPECTED_TASKS[r"\SPY-Iron-Condor-Observation"] == {"08:50"}
    assert alignment.EXPECTED_TASKS[r"\Liquidity-Sweep-Scanner"] == {"08:43", "09:35", "10:40"}
    assert alignment.EXPECTED_TASKS[r"\SPY-0DTE-PM-Entry"] == {"11:05", "12:05"}
    assert alignment.EXPECTED_TASKS[r"\SPY-0DTE-PM-Monitor"] == {
        "11:15", "11:30", "11:45", "12:00", "12:15", "12:30", "12:45",
        "13:00", "13:15", "13:30", "13:45", "14:00", "14:15", "14:30", "14:45",
    }


def test_registration_script_uses_limited_tasks_and_timezone_guard() -> None:
    root = Path(__file__).resolve().parents[2]
    text = (root / "scripts" / "register_spy_options_observation_tasks.ps1").read_text(encoding="utf-8")

    assert "Central Standard Time" in text
    assert "-RunLevel Limited" in text
    assert "SPY-Theta-Harvester-Entry" in text
    assert "SPY-Iron-Condor-Entry" in text
    assert "SPY-Iron-Condor-Observation" in text
    assert "Liquidity-Sweep-Scanner" in text
    assert "run_liquidity_sweep_scanner.ps1" in text
    assert "SPY-0DTE-PM-Entry" in text
    assert "11:05AM" in text
    assert "12:05PM" in text


def test_iron_condor_observation_runner_cannot_use_entry_mode() -> None:
    root = Path(__file__).resolve().parents[2]
    text = (root / "scripts" / "run_spy_iron_condor_observation.ps1").read_text(encoding="utf-8")

    assert "--observe-only" in text

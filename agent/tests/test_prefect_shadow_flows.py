from pathlib import Path

import pytest

from orchestration.flows import common


def test_runner_rejects_unallowlisted_script_before_subprocess():
    with pytest.raises(ValueError, match="not_allowlisted"):
        common.run_shadow_script("../strategies/flip_bot.py")


def test_runner_forces_shadow_environment(monkeypatch):
    captured = {}
    class Result:
        returncode = 0; stdout = "ok"; stderr = ""
    def fake_run(command, **kwargs):
        captured.update(command=command, kwargs=kwargs); return Result()
    monkeypatch.setattr(common.subprocess, "run", fake_run)
    result = common.run_shadow_script("pattern_grader_scanner.py")
    assert Path(captured["command"][1]).name == "pattern_grader_scanner.py"
    assert captured["kwargs"]["shell"] is False
    assert captured["kwargs"]["env"]["EXECUTION_ENABLED"] == "false"
    assert result["can_submit_orders"] is False

from __future__ import annotations

from pathlib import Path


def test_setup_task_scheduler_registers_momentum_shadow_logger() -> None:
    script = Path("scripts/setup_task_scheduler.ps1").read_text(encoding="utf-8")

    assert "MomentumShadowLogger" in script
    assert "scripts/momentum_shadow_logger.py" in script
    assert "-DaysOfWeek Monday" in script
    assert "-At \"8:00AM\"" in script

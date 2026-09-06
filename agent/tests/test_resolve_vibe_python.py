from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.skipif(os.name != "nt", reason="Windows Task Scheduler runtime contract")
def test_resolver_returns_one_real_non_windowsapps_interpreter() -> None:
    script = ROOT / "scripts" / "resolve_vibe_python.ps1"
    command = f'. "{script}"; Get-VibePython'
    completed = subprocess.run(
        ["powershell.exe", "-NoProfile", "-Command", command],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    lines = [line.strip() for line in completed.stdout.splitlines() if line.strip()]
    assert len(lines) == 1
    assert Path(lines[0]).is_file()
    assert "windowsapps" not in lines[0].lower()

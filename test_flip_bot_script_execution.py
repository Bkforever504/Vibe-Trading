import subprocess
import sys
from pathlib import Path


def test_flip_bot_script_can_start_when_executed_by_path() -> None:
    script = Path("strategies") / "flip_bot.py"

    result = subprocess.run(
        [sys.executable, str(script), "--status"],
        cwd=Path(__file__).parent,
        text=True,
        capture_output=True,
        timeout=30,
    )

    assert result.returncode == 0, result.stderr

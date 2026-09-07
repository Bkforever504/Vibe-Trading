from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from typing import Any, Callable

ROOT = Path(__file__).resolve().parents[2]
ALLOWED_SCRIPTS = {
    "shadow_system_heartbeat.py", "pattern_grader_scanner.py", "momentum_sweep_runner.py",
    "blsh_bakeoff_shadow.py",
    "blsh_outcome_shadow.py",
}

try:
    from prefect import flow, task
except ImportError:
    def _identity_decorator(*_args: Any, **_kwargs: Any) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
        return lambda function: function
    flow = task = _identity_decorator


@task(retries=3, retry_delay_seconds=[30, 120, 600], log_prints=True)
def run_shadow_script(script_name: str, *arguments: str) -> dict[str, Any]:
    if script_name not in ALLOWED_SCRIPTS:
        raise ValueError("script_not_allowlisted")
    script = (ROOT / "scripts" / script_name).resolve()
    if script.parent != (ROOT / "scripts").resolve() or not script.exists():
        raise FileNotFoundError(script_name)
    environment = dict(os.environ)
    environment.update({"EXECUTION_ENABLED": "false", "LIVE_TRADING": "false", "PAPER_TRADING": "true"})
    completed = subprocess.run(
        [sys.executable, str(script), *arguments], cwd=ROOT, env=environment,
        capture_output=True, text=True, timeout=900, check=False, shell=False,
    )
    if completed.returncode:
        raise RuntimeError(f"{script_name}_exit_{completed.returncode}:{completed.stderr[-500:]}")
    return {
        "script": script_name, "returncode": completed.returncode,
        "stdout_tail": completed.stdout[-1000:], "execution_enabled": False,
        "can_submit_orders": False,
    }

"""Verify the scheduler's direct-script launch, not pytest's import path."""
import os
from pathlib import Path
import subprocess
import sys


def test_direct_confluence_help_bootstraps_repo_imports(tmp_path):
    root = Path(__file__).resolve().parents[2]
    env = dict(os.environ)
    env.pop('PYTHONPATH', None)
    result = subprocess.run(
        [sys.executable, str(root / 'scripts/institutional_confluence_shadow.py'), '--help'],
        cwd=tmp_path, env=env, capture_output=True, text=True, timeout=30,
    )
    assert result.returncode == 0, result.stderr
    assert 'usage:' in result.stdout

"""Repository-wide pytest isolation for durable runtime artifacts."""
from __future__ import annotations

import os
import tempfile
from pathlib import Path


# Set before test-module collection so top-level flip_bot imports cannot bind
# their decision logger to Kenny's real runtime directory.
_PYTEST_RUNTIME = Path(tempfile.gettempdir()) / f"vibe-trading-pytest-{os.getpid()}"
os.environ.setdefault(
    "FLIP_DECISION_LOG_FILE",
    str(_PYTEST_RUNTIME / "flip-decisions.jsonl"),
)
os.environ.setdefault(
    "OPTION_QUOTE_SAMPLES_FILE",
    str(_PYTEST_RUNTIME / "option-quote-samples.jsonl"),
)

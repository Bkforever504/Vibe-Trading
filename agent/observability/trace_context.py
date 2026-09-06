"""Dependency-light trace context for the shadow alert pipeline.

The identifiers and timestamps created here are observability metadata only.
They confer no order or broker authority.  Missing upstream times stay ``None``.
"""
from __future__ import annotations

import uuid
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import datetime, timezone
from typing import Iterator

_TRACE_ID: ContextVar[str | None] = ContextVar("vibe_trace_id", default=None)
_TRACE_NAMESPACE = uuid.UUID("45851fbe-8d76-4cef-8f9e-46cd6f286e9f")


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def new_trace_id(seed: str | None = None) -> str:
    """Return a UUID trace id; a stable seed preserves idempotent reruns."""
    return str(uuid.uuid5(_TRACE_NAMESPACE, seed)) if seed else str(uuid.uuid4())


def current_trace_id() -> str | None:
    return _TRACE_ID.get()


@contextmanager
def trace_scope(trace_id: str | None = None, *, seed: str | None = None) -> Iterator[str]:
    selected = trace_id or new_trace_id(seed)
    # Reject arbitrary log injection while accepting all UUID versions.
    selected = str(uuid.UUID(selected))
    token = _TRACE_ID.set(selected)
    try:
        yield selected
    finally:
        _TRACE_ID.reset(token)


def trace_fields(*, trace_id: str, bar_close_ts: str | None,
                 scanner_emit_ts: str | None = None) -> dict[str, object]:
    return {
        "trace_id": str(uuid.UUID(trace_id)),
        "bar_close_ts": bar_close_ts or None,
        "scanner_emit_ts": scanner_emit_ts or None,
        "execution_enabled": False,
        "can_submit_orders": False,
    }


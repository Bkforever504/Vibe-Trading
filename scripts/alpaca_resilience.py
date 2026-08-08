"""Bounded, read-only Alpaca retries with durable outage telemetry.

This module deliberately does not expose POST, PATCH, or DELETE helpers. Order
submission must never inherit automatic retries because an ambiguous response
can otherwise create a duplicate order.
"""
from __future__ import annotations

import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, TypeVar

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry


T = TypeVar("T")
DEFAULT_HEALTH_LOG = Path(
    os.path.expanduser(r"~\.vibe-trading\logs\alpaca-read-health.jsonl")
)
RETRYABLE_STATUS_CODES = frozenset({429, 500, 502, 503, 504})


class AlpacaReadUnavailable(RuntimeError):
    """Raised when broker truth cannot be established after bounded retries."""


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def record_health_event(
    *,
    component: str,
    operation: str,
    status: str,
    attempts: int,
    error: str | None = None,
    elapsed_ms: float | None = None,
    path: Path | str | None = None,
) -> None:
    event = {
        "timestamp": _utc_now(),
        "provider": "alpaca",
        "transport": "read_only",
        "component": component,
        "operation": operation,
        "status": status,
        "attempts": attempts,
        "elapsed_ms": round(elapsed_ms, 1) if elapsed_ms is not None else None,
        "error_type": error.split(":", 1)[0] if error else None,
        "error": error[:500] if error else None,
        "execution_enabled": False,
        "can_submit_orders": False,
    }
    target = Path(path) if path is not None else DEFAULT_HEALTH_LOG
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(event, sort_keys=True) + "\n")
    except OSError:
        # Health telemetry must not obscure the original broker-read failure.
        pass


def read_with_retry(
    call: Callable[[], T],
    *,
    component: str,
    operation: str,
    attempts: int = 3,
    backoff_seconds: float = 0.25,
    sleep: Callable[[float], None] = time.sleep,
    health_path: Path | str | None = None,
) -> T:
    """Run an idempotent broker read and raise on unresolved state."""
    attempts = max(1, int(attempts))
    started = time.monotonic()
    last_error: Exception | None = None
    for attempt in range(1, attempts + 1):
        try:
            result = call()
            if attempt > 1:
                record_health_event(
                    component=component,
                    operation=operation,
                    status="recovered_after_retry",
                    attempts=attempt,
                    elapsed_ms=(time.monotonic() - started) * 1000,
                    path=health_path,
                )
            return result
        except Exception as exc:  # callers define the read boundary
            last_error = exc
            if attempt < attempts:
                sleep(backoff_seconds * (2 ** (attempt - 1)))

    error = f"{type(last_error).__name__}: {last_error}"
    record_health_event(
        component=component,
        operation=operation,
        status="exhausted",
        attempts=attempts,
        error=error,
        elapsed_ms=(time.monotonic() - started) * 1000,
        path=health_path,
    )
    raise AlpacaReadUnavailable(
        f"Alpaca read unavailable for {component}.{operation} after {attempts} attempts: {last_error}"
    ) from last_error


def get_json(
    url: str,
    *,
    headers: dict[str, str],
    params: dict[str, Any] | None = None,
    component: str,
    operation: str,
    attempts: int = 3,
    timeout: tuple[float, float] = (3.05, 12.0),
    requester: Any = requests,
    health_path: Path | str | None = None,
) -> dict | list:
    """GET JSON with bounded retries; non-retryable HTTP failures fail closed."""
    def fetch() -> dict | list:
        response = requester.get(url, headers=headers, params=params or {}, timeout=timeout)
        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, (dict, list)):
            raise ValueError("Alpaca response was not a JSON object or list")
        return payload

    return read_with_retry(
        fetch,
        component=component,
        operation=operation,
        attempts=attempts,
        health_path=health_path,
    )


def configure_sdk_client(
    client: Any,
    *,
    connect_timeout: float = 3.05,
    read_timeout: float = 12.0,
    transport_retries: int = 2,
) -> Any:
    """Apply GET-only transport retries and explicit timeouts to alpaca-py."""
    session = getattr(client, "_session", None)
    if session is None or getattr(session, "_alpaca_resilience_configured", False):
        return client

    retry = Retry(
        total=max(0, transport_retries),
        connect=max(0, transport_retries),
        read=max(0, transport_retries),
        status=max(0, transport_retries),
        backoff_factor=0.25,
        status_forcelist=sorted(RETRYABLE_STATUS_CODES),
        allowed_methods=frozenset({"GET", "HEAD", "OPTIONS"}),
        respect_retry_after_header=True,
        raise_on_status=False,
    )
    adapter = HTTPAdapter(max_retries=retry)
    session.mount("https://", adapter)
    session.mount("http://", adapter)

    original_request = session.request

    def request_with_timeout(method: str, url: str, **kwargs: Any):
        kwargs.setdefault("timeout", (connect_timeout, read_timeout))
        return original_request(method, url, **kwargs)

    session.request = request_with_timeout
    session._alpaca_resilience_configured = True
    return client

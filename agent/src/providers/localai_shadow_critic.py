"""Loopback-only LocalAI adapter for the existing veto-only critic contract."""
from __future__ import annotations

import ipaddress
import json
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlsplit

from agent.src.providers.ollama_shadow_critic import (
    _hash, build_critic_input, validate_model_output,
)


def validate_localai_base_url(value: str) -> str:
    parsed = urlsplit(value.strip().rstrip("/"))
    if parsed.scheme != "http" or parsed.username or parsed.password or parsed.query or parsed.fragment or parsed.path not in {"", "/"}:
        raise ValueError("LocalAI requires a plain HTTP loopback base URL")
    try:
        host = ipaddress.ip_address(parsed.hostname or "")
    except ValueError as exc:
        raise ValueError("LocalAI requires a literal loopback IP") from exc
    if not host.is_loopback or (parsed.port or 8080) != 8080:
        raise ValueError("LocalAI shadow critic is restricted to loopback port 8080")
    rendered = f"[{host.compressed}]" if host.version == 6 else host.compressed
    return f"http://{rendered}:8080"


def _request(url: str, *, timeout: float, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    request = urllib.request.Request(
        url, method="POST" if payload is not None else "GET",
        data=json.dumps(payload).encode() if payload is not None else None,
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        value = json.loads(response.read().decode())
    if not isinstance(value, dict):
        raise ValueError("non_object_response")
    return value


def evaluate(candidate: dict[str, Any], evidence_cards: list[dict[str, Any]], *, model: str, base_url: str = "http://127.0.0.1:8080", timeout_seconds: float = 30) -> dict[str, Any]:
    started = time.perf_counter(); critic_input, refs = build_critic_input(candidate, evidence_cards)
    result = {
        "provider": "localai_openai_compatible_shadow_critic", "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "status": "unavailable", "model": model, "input_hash": _hash(critic_input), "response_hash": None,
        "stance": None, "veto_reasons": [], "evidence_refs": [], "summary": None,
        "authority": "shadow_veto_only", "execution_enabled": False, "can_submit_orders": False, "error": None,
    }
    try:
        base = validate_localai_base_url(base_url)
        models = _request(f"{base}/v1/models", timeout=min(3, timeout_seconds)).get("data") or []
        if not any(isinstance(row, dict) and row.get("id") == model for row in models):
            result.update(status="not_configured", error="model_not_installed"); return result
        response = _request(f"{base}/v1/chat/completions", timeout=timeout_seconds, payload={
            "model": model, "temperature": 0, "response_format": {"type": "json_object"},
            "messages": [
                {"role": "system", "content": "You are a veto-only risk critic. Cite only supplied evidence hashes. Never approve, size, route, alert, or execute. Return JSON with veto_reasons, evidence_refs, summary."},
                {"role": "user", "content": json.dumps(critic_input, sort_keys=True)},
            ],
        })
        content = response["choices"][0]["message"]["content"]
        validated = validate_model_output(json.loads(content), refs)
        result.update(status="ok", response_hash=_hash(validated), **validated)
    except urllib.error.HTTPError as exc:
        result["error"] = f"http_{exc.code}"
    except (urllib.error.URLError, TimeoutError):
        result["error"] = "connection_failed_or_timeout"
    except (KeyError, IndexError, TypeError, ValueError, json.JSONDecodeError):
        result.update(status="invalid_response", error="schema_validation_failed")
    finally:
        result["latency_ms"] = round((time.perf_counter() - started) * 1000, 2)
    return result

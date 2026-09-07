"""Local-only Ollama client for a schema-constrained shadow trade critic.

The critic has no broker, Discord, or order authority.  A valid ``veto`` may
only add a blocker to the deterministic shadow gate; every other result is
informational.
"""
from __future__ import annotations

import hashlib
import ipaddress
import json
import math
import re
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlsplit

ALLOWED_VETO_REASONS = {
    "direction_conflicts_with_evidence",
    "risk_reward_not_supported",
    "market_regime_conflict",
    "evidence_internally_inconsistent",
}
OUTPUT_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["veto_reasons", "evidence_refs", "summary"],
    "properties": {
        "veto_reasons": {
            "type": "array",
            "items": {"type": "string", "enum": sorted(ALLOWED_VETO_REASONS)},
            "maxItems": 4,
        },
        "evidence_refs": {"type": "array", "items": {"type": "string"}, "maxItems": 8},
        "summary": {"type": "string", "maxLength": 240},
    },
}


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _hash(value: Any) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def validate_local_base_url(value: str) -> str:
    """Return a canonical loopback Ollama URL or raise ``ValueError``."""
    parsed = urlsplit(value.strip().rstrip("/"))
    if parsed.scheme != "http" or parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ValueError("Ollama shadow critic requires a plain HTTP loopback URL without credentials")
    if parsed.path not in {"", "/"}:
        raise ValueError("Ollama base URL must not include a path")
    try:
        host = ipaddress.ip_address(parsed.hostname or "")
    except ValueError as exc:
        raise ValueError("Ollama shadow critic requires a literal loopback IP") from exc
    if not host.is_loopback:
        raise ValueError("Ollama shadow critic refuses non-loopback endpoints")
    port = parsed.port or 11434
    if port != 11434:
        raise ValueError("Ollama shadow critic requires local port 11434")
    rendered_host = f"[{host.compressed}]" if host.version == 6 else host.compressed
    return f"http://{rendered_host}:11434"


def _post_json(url: str, payload: dict[str, Any], timeout_seconds: float) -> dict[str, Any]:
    request = urllib.request.Request(
        url,
        data=json.dumps(payload, separators=(",", ":")).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=timeout_seconds) as response:  # noqa: S310 - URL is loopback validated
        value = json.loads(response.read().decode("utf-8"))
    if not isinstance(value, dict):
        raise ValueError("Ollama returned a non-object response")
    return value


def _get_json(url: str, timeout_seconds: float) -> dict[str, Any]:
    request = urllib.request.Request(url, method="GET")
    with urllib.request.urlopen(request, timeout=timeout_seconds) as response:  # noqa: S310 - URL is loopback validated
        value = json.loads(response.read().decode("utf-8"))
    if not isinstance(value, dict):
        raise ValueError("Ollama returned a non-object response")
    return value


def sanitize_candidate(candidate: dict[str, Any]) -> dict[str, Any]:
    """Allow only decision facts; discard notes/headlines/free-form instructions."""
    def token(value: Any, limit: int = 64) -> str | None:
        rendered = str(value or "").strip()
        return rendered if rendered and len(rendered) <= limit and re.fullmatch(r"[A-Za-z0-9_.:+-]+", rendered) else None

    def number(value: Any) -> float | None:
        try:
            parsed = float(value)
        except (TypeError, ValueError):
            return None
        return parsed if math.isfinite(parsed) else None

    return {
        "symbol": token(candidate.get("symbol"), 12),
        "direction": token(candidate.get("direction"), 12),
        "setup": token(candidate.get("setup")),
        "state": token(candidate.get("state"), 16),
        "grade": token(candidate.get("grade"), 8),
        "score": number(candidate.get("score")),
        "trigger": number(candidate.get("trigger")),
        "stop": number(candidate.get("stop")),
        "target": number(candidate.get("target")),
        "bar_completed_at": token(candidate.get("bar_completed_at"), 40),
        "lane": token(candidate.get("lane")),
    }


def validate_model_output(value: Any, allowed_refs: set[str]) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != {"veto_reasons", "evidence_refs", "summary"}:
        raise ValueError("response does not match the exact critic schema")
    reasons = value.get("veto_reasons")
    refs = value.get("evidence_refs")
    summary = value.get("summary")
    if not isinstance(reasons, list) or not isinstance(refs, list) or not isinstance(summary, str):
        raise ValueError("response contains invalid field types")
    if len(reasons) > 4 or any(item not in ALLOWED_VETO_REASONS for item in reasons):
        raise ValueError("response contains invalid veto reasons")
    if len(refs) > 8 or any(not isinstance(item, str) or item not in allowed_refs for item in refs):
        raise ValueError("response cites evidence not present in the input")
    if reasons and not refs:
        raise ValueError("veto has no cited input evidence")
    if len(summary) > 240:
        raise ValueError("summary exceeds the bounded schema")
    # Authority is derived deterministically from the presence of an allowed
    # veto reason; the model cannot emit a contradictory approval label.
    return {"stance": "veto" if reasons else "neutral", "veto_reasons": reasons, "evidence_refs": refs, "summary": summary}


def build_critic_input(candidate: dict[str, Any], evidence_cards: list[dict[str, Any]]) -> tuple[dict[str, Any], set[str]]:
    """Return the complete sanitized model input and its valid citation set."""
    safe_cards = [
        {
            "role": re.sub(r"[^A-Za-z0-9_.:+-]", "_", str(card.get("role") or "unknown"))[:64],
            "claim": re.sub(r"[^A-Za-z0-9_.:+-]", "_", str(card.get("claim") or "missing"))[:64],
            "evidence_hash": card.get("evidence_hash"),
        }
        for card in evidence_cards if isinstance(card, dict) and card.get("evidence_hash")
    ]
    return {"candidate": sanitize_candidate(candidate), "evidence": safe_cards}, {str(card["evidence_hash"]) for card in safe_cards}


def input_digest(candidate: dict[str, Any], evidence_cards: list[dict[str, Any]]) -> str:
    return _hash(build_critic_input(candidate, evidence_cards)[0])


def evaluate(
    candidate: dict[str, Any], evidence_cards: list[dict[str, Any]], *, model: str = "qwen3:4b-instruct",
    base_url: str = "http://127.0.0.1:11434", timeout_seconds: float = 30.0,
) -> dict[str, Any]:
    """Evaluate one candidate and return a fail-honest, authority-free card."""
    started = time.perf_counter()
    base = validate_local_base_url(base_url)
    critic_input, refs = build_critic_input(candidate, evidence_cards)
    base_result: dict[str, Any] = {
        "provider": "ollama_local_shadow_critic", "generated_at": _utc_now(), "status": "unavailable",
        "model": model, "model_digest": None, "prompt_version": "ollama-shadow-critic-v1",
        "input_hash": _hash(critic_input), "prompt_hash": _hash({"schema": OUTPUT_SCHEMA, "version": "v1"}),
        "response_hash": None, "latency_ms": None, "stance": None, "veto_reasons": [], "evidence_refs": [],
        "summary": None, "execution_enabled": False, "can_submit_orders": False,
        "authority": "shadow_veto_only", "error": None,
    }
    try:
        tags = _get_json(f"{base}/api/tags", min(timeout_seconds, 3.0))
        models = [row for row in tags.get("models", []) if isinstance(row, dict)]
        selected = next((row for row in models if row.get("name") == model or row.get("model") == model), None)
        if selected is None:
            base_result.update(status="not_configured", error="model_not_installed")
            return base_result
        base_result["model_digest"] = selected.get("digest")
        response = _post_json(f"{base}/api/chat", {
            "model": model, "stream": False, "think": False, "format": OUTPUT_SCHEMA,
            "options": {"temperature": 0, "seed": 7, "num_ctx": 4096},
            "messages": [
                {"role": "system", "content": "You are a risk critic, not a trader. Use only supplied facts. List only allowed veto reasons that are directly supported by cited evidence. An empty veto_reasons list means no veto. Never approve, size, route, message, or execute a trade. Return the required JSON only."},
                {"role": "user", "content": json.dumps(critic_input, sort_keys=True, separators=(",", ":"))},
            ],
        }, timeout_seconds)
        content = ((response.get("message") or {}).get("content"))
        raw = json.loads(content) if isinstance(content, str) else content
        validated = validate_model_output(raw, refs)
        base_result.update(status="ok", response_hash=_hash(validated), **validated)
    except urllib.error.HTTPError as exc:
        base_result.update(status="unavailable", error="overloaded" if exc.code == 503 else f"http_{exc.code}")
    except (TimeoutError, urllib.error.URLError) as exc:
        base_result["error"] = "timeout" if isinstance(getattr(exc, "reason", None), TimeoutError) or isinstance(exc, TimeoutError) else "connection_failed"
    except (json.JSONDecodeError, ValueError, TypeError, KeyError):
        base_result.update(status="invalid_response", error="schema_validation_failed")
    finally:
        base_result["latency_ms"] = round((time.perf_counter() - started) * 1000, 2)
    return base_result

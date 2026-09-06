#!/usr/bin/env python3
"""Small, secret-safe Discord notifier for trading operations.

The webhook is read from the process environment first and then `agent/.env`.
It is never included in return values, logs, exceptions, or test output.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Callable, Mapping
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit


ROOT = Path(__file__).resolve().parents[1]
ENV_PATH = ROOT / "agent" / ".env"
WEBHOOK_KEY = "DISCORD_WEBHOOK_URL"
DISCORD_HOSTS = frozenset({"discord.com", "www.discord.com", "discordapp.com"})
MAX_CONTENT = 1850


def _env_value(
    key: str,
    *,
    environ: Mapping[str, str] | None = None,
    env_path: Path = ENV_PATH,
) -> str | None:
    source = os.environ if environ is None else environ
    value = str(source.get(key, "")).strip()
    if value:
        return value
    try:
        lines = env_path.read_text(encoding="utf-8-sig", errors="ignore").splitlines()
    except OSError:
        return None
    for raw in lines:
        stripped = raw.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        name, candidate = stripped.split("=", 1)
        if name.strip() == key and candidate.strip():
            return candidate.strip().strip('"').strip("'")
    return None


def _validate_webhook(url: str) -> None:
    parsed = urlsplit(url)
    if parsed.scheme != "https" or parsed.hostname not in DISCORD_HOSTS:
        raise ValueError("discord_webhook_must_use_official_https_host")
    if not parsed.path.startswith("/api/webhooks/"):
        raise ValueError("discord_webhook_path_invalid")


def redact(text: str) -> str:
    value = str(text)
    value = re.sub(
        r"https://(?:www\.)?(?:discord(?:app)?\.com)/api/webhooks/[^\s\]\)\"']+",
        "[REDACTED_DISCORD_WEBHOOK]",
        value,
        flags=re.IGNORECASE,
    )
    value = re.sub(
        r"(?i)\b(?:DISCORD_WEBHOOK_URL|DATABENTO_API_KEY|APCA_API_SECRET_KEY|ALPACA_SECRET_KEY)\s*=\s*\S+",
        "[REDACTED_SECRET]",
        value,
    )
    value = re.sub(r"\bdb-[A-Za-z0-9_-]{8,}\b", "[REDACTED_DATABENTO_KEY]", value)
    return value


def _chunks(message: str) -> list[str]:
    clean = redact(message).strip() or "(empty notification)"
    chunks: list[str] = []
    while len(clean) > MAX_CONTENT:
        split = clean.rfind("\n", 0, MAX_CONTENT)
        if split < MAX_CONTENT // 2:
            split = MAX_CONTENT
        chunks.append(clean[:split].rstrip())
        clean = clean[split:].lstrip()
    chunks.append(clean)
    return chunks


def _wait_url(url: str) -> str:
    parts = urlsplit(url)
    query = dict(parse_qsl(parts.query, keep_blank_values=True))
    query["wait"] = "true"
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), parts.fragment))


def _message_receipt(value: Any) -> dict[str, str | None]:
    payload = value if isinstance(value, Mapping) else {}
    return {
        "discord_message_id": str(payload.get("id") or "").strip() or None,
        "discord_delivered_ts": str(payload.get("timestamp") or "").strip() or None,
    }


def _post_json(url: str, payload: dict[str, Any], timeout: float) -> dict[str, Any] | None:
    request = urllib.request.Request(
        _wait_url(url),
        data=json.dumps(payload, separators=(",", ":")).encode("utf-8"),
        headers={"Content-Type": "application/json", "User-Agent": "VibeTradingOps/1.0"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        if int(getattr(response, "status", 200)) not in {200, 204}:
            raise RuntimeError(f"discord_http_{getattr(response, 'status', 'unknown')}")
        raw = response.read()
        return json.loads(raw.decode("utf-8")) if raw else None


def send_discord(
    message: str,
    *,
    webhook_url: str | None = None,
    transport: Callable[[str, dict[str, Any], float], None] = _post_json,
    timeout: float = 10.0,
    attempts: int = 2,
) -> dict[str, Any]:
    webhook = webhook_url or _env_value(WEBHOOK_KEY)
    if not webhook:
        return {"status": "not_configured", "sent": False, "chunks": 0}
    _validate_webhook(webhook)
    chunks = _chunks(message)
    sent = 0
    receipts: list[dict[str, str | None]] = []
    try:
        for content in chunks:
            payload = {"content": content, "allowed_mentions": {"parse": []}}
            for attempt in range(max(1, attempts)):
                try:
                    response = transport(_wait_url(webhook), payload, timeout)
                    receipts.append(_message_receipt(response))
                    sent += 1
                    break
                except (urllib.error.URLError, TimeoutError, RuntimeError):
                    if attempt + 1 >= max(1, attempts):
                        raise
                    time.sleep(0.5)
    except Exception as exc:
        return {
            "status": "send_failed",
            "sent": False,
            "chunks": sent,
            "error_type": type(exc).__name__,
        }
    return {"status": "sent", "sent": True, "chunks": sent, "receipts": receipts}


def send_discord_embed(
    *,
    title: str,
    description: str,
    color: int = 0xE53935,
    fields: list[dict[str, Any]] | None = None,
    content: str = "",
    webhook_url: str | None = None,
    transport: Callable[[str, dict[str, Any], float], None] = _post_json,
    timeout: float = 10.0,
    attempts: int = 2,
    allow_mentions: bool = True,
) -> dict[str, Any]:
    """Send a Discord embed (colored side-bar, rich fields). Optional @here mention via content."""
    webhook = webhook_url or _env_value(WEBHOOK_KEY)
    if not webhook:
        return {"status": "not_configured", "sent": False, "chunks": 0}
    _validate_webhook(webhook)
    embed: dict[str, Any] = {
        "title": redact(title)[:256],
        "description": redact(description)[:4096],
        "color": int(color) & 0xFFFFFF,
    }
    if fields:
        embed["fields"] = [
            {"name": redact(str(f.get("name", "")))[:256],
             "value": redact(str(f.get("value", "")))[:1024],
             "inline": bool(f.get("inline", False))}
            for f in fields[:25]
        ]
    payload: dict[str, Any] = {
        "content": redact(content)[:MAX_CONTENT],
        "embeds": [embed],
        "allowed_mentions": {"parse": ["everyone"] if allow_mentions else []},
    }
    try:
        for attempt in range(max(1, attempts)):
            try:
                response = transport(_wait_url(webhook), payload, timeout)
                return {"status": "sent", "sent": True, "chunks": 1,
                        "receipts": [_message_receipt(response)]}
            except (urllib.error.URLError, TimeoutError, RuntimeError):
                if attempt + 1 >= max(1, attempts):
                    raise
                time.sleep(0.5)
    except Exception as exc:
        return {"status": "send_failed", "sent": False, "chunks": 0, "error_type": type(exc).__name__}
    return {"status": "send_failed", "sent": False, "chunks": 0}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--message", required=True)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    if args.dry_run:
        print(json.dumps({"status": "dry_run", "chunks": len(_chunks(args.message)), "sent": False}))
        return 0
    result = send_discord(args.message)
    print(json.dumps(result, sort_keys=True))
    return 0 if result["status"] in {"sent", "not_configured"} else 1


if __name__ == "__main__":
    raise SystemExit(main())

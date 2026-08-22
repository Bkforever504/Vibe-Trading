#!/usr/bin/env python3
"""Read-only ProjectX SignalR market-event recorder for the active MES contract."""
from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import quote


RECORD_SEPARATOR = "\x1e"
MARKET_HUB = "wss://rtc.topstepx.com/hubs/market"
MARKET_TARGETS = {
    "GatewayQuote": "quote",
    "GatewayTrade": "trade",
    "GatewayDepth": "depth",
}
SUBSCRIPTIONS = (
    "SubscribeContractQuotes",
    "SubscribeContractTrades",
    "SubscribeContractMarketDepth",
)


def signalr_frame(payload: dict[str, Any]) -> str:
    return json.dumps(payload, separators=(",", ":")) + RECORD_SEPARATOR


def decode_signalr_frames(raw: str | bytes) -> list[dict[str, Any]]:
    text = raw.decode("utf-8") if isinstance(raw, bytes) else raw
    messages: list[dict[str, Any]] = []
    for chunk in text.split(RECORD_SEPARATOR):
        if not chunk.strip():
            continue
        value = json.loads(chunk)
        if not isinstance(value, dict):
            raise ValueError("SignalR frame must contain a JSON object")
        messages.append(value)
    return messages


def normalize_market_event(message: dict[str, Any], *, received_at: datetime | None = None) -> dict[str, Any] | None:
    if message.get("type") != 1:
        return None
    target = str(message.get("target") or "")
    event_type = MARKET_TARGETS.get(target)
    arguments = message.get("arguments")
    if event_type is None or not isinstance(arguments, list) or len(arguments) < 2:
        return None
    contract_id, payload = arguments[0], arguments[1]
    if not isinstance(payload, dict):
        return None
    received = received_at or datetime.now(timezone.utc)
    source_timestamp = payload.get("timestamp") or payload.get("lastUpdated")
    return {
        "schema_version": 1,
        "provider": "topstepx_projectx_signalr",
        "event_type": event_type,
        "contract_id": str(contract_id),
        "source_timestamp": str(source_timestamp) if source_timestamp is not None else None,
        "received_at_utc": received.astimezone(timezone.utc).isoformat().replace("+00:00", "Z"),
        "payload": payload,
    }


@dataclass
class RotatingJsonlWriter:
    path: Path
    max_bytes: int = 50 * 1024 * 1024
    backup_count: int = 3

    def __post_init__(self) -> None:
        if self.max_bytes <= 0 or self.backup_count < 0:
            raise ValueError("rotation limits must be non-negative and max_bytes must be positive")

    def _rotate(self) -> None:
        if self.backup_count == 0:
            self.path.unlink(missing_ok=True)
            return
        oldest = self.path.with_name(f"{self.path.name}.{self.backup_count}")
        oldest.unlink(missing_ok=True)
        for index in range(self.backup_count - 1, 0, -1):
            source = self.path.with_name(f"{self.path.name}.{index}")
            if source.exists():
                source.replace(self.path.with_name(f"{self.path.name}.{index + 1}"))
        if self.path.exists():
            self.path.replace(self.path.with_name(f"{self.path.name}.1"))

    def append(self, row: dict[str, Any]) -> None:
        encoded = (json.dumps(row, separators=(",", ":"), sort_keys=True) + "\n").encode("utf-8")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        current_size = self.path.stat().st_size if self.path.exists() else 0
        if current_size and current_size + len(encoded) > self.max_bytes:
            self._rotate()
        with self.path.open("ab") as handle:
            handle.write(encoded)


class TopstepXMarketRecorder:
    """SignalR client that has no account, position, or order operations."""

    def __init__(self, *, access_token: str, contract_id: str, writer: RotatingJsonlWriter) -> None:
        self.access_token = access_token.strip()
        self.contract_id = contract_id.strip()
        self.writer = writer
        if not self.access_token or not self.contract_id.startswith("CON.F.US.MES."):
            raise ValueError("A token and active MES contract ID are required")

    @property
    def url(self) -> str:
        return f"{MARKET_HUB}?access_token={quote(self.access_token, safe='')}"

    def subscription_frames(self) -> list[str]:
        return [
            signalr_frame({
                "type": 1,
                "target": target,
                "arguments": [self.contract_id],
                "invocationId": str(index),
            })
            for index, target in enumerate(SUBSCRIPTIONS, start=1)
        ]

    def record_message(self, raw: str | bytes, *, received_at: datetime | None = None) -> int:
        count = 0
        for message in decode_signalr_frames(raw):
            event = normalize_market_event(message, received_at=received_at)
            if event is None or event["contract_id"] != self.contract_id:
                continue
            self.writer.append(event)
            count += 1
        return count

    def run(self, *, duration_seconds: int) -> dict[str, Any]:
        if duration_seconds <= 0:
            raise ValueError("duration_seconds must be positive")
        import time
        import websocket

        started = datetime.now(timezone.utc)
        deadline = time.monotonic() + duration_seconds
        event_count = 0
        ws = websocket.create_connection(self.url, timeout=15, enable_multithread=False)
        try:
            ws.send(signalr_frame({"protocol": "json", "version": 1}))
            handshake = decode_signalr_frames(ws.recv())
            if not handshake or handshake[0].get("error"):
                raise RuntimeError(f"SignalR handshake failed: {handshake!r}")
            for frame in self.subscription_frames():
                ws.send(frame)
            ws.settimeout(5)
            while time.monotonic() < deadline:
                try:
                    raw = ws.recv()
                except websocket.WebSocketTimeoutException:
                    continue
                if raw in (None, ""):
                    break
                event_count += self.record_message(raw)
        finally:
            ws.close()
        ended = datetime.now(timezone.utc)
        return {
            "provider": "topstepx_market_recorder",
            "mode": "read_only",
            "execution_enabled": False,
            "can_submit_orders": False,
            "contract_id": self.contract_id,
            "started_at_utc": started.isoformat().replace("+00:00", "Z"),
            "ended_at_utc": ended.isoformat().replace("+00:00", "Z"),
            "event_count": event_count,
            "output": str(self.writer.path),
        }


def default_output() -> Path:
    configured = os.environ.get("TOPSTEPX_MARKET_LOG", "").strip()
    return Path(configured) if configured else Path.home() / ".vibe-trading" / "topstepx" / "mes-market-events.jsonl"

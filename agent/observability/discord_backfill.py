"""Recover Discord message timestamps only when an original message ID exists.

This writes a sidecar audit ledger and never mutates historical alert records.
Rows without stored message IDs are permanently marked unrecoverable; timestamps
are never inferred from local HTTP completion times.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from agent.notifier import _env_value, _validate_webhook

HOME = Path.home() / ".vibe-trading"
DEFAULT_INPUTS = {
    "governed_shadow": HOME / "data" / "governed_shadow_alert_events.jsonl",
    "core_index_tape_watcher": HOME / "data" / "core_index_tape_delivery_events.jsonl",
}
DEFAULT_LEDGER = HOME / "data" / "discord_delivery_backfill.jsonl"
DEFAULT_REPORT = HOME / "reports" / "discord-delivery-backfill.json"
SNOWFLAKE = re.compile(r"^[0-9]{5,25}$")


def _rows(path: Path) -> list[dict[str, Any]]:
    try:
        return [value for line in path.read_text(encoding="utf-8-sig").splitlines()
                if line.strip() and isinstance((value := json.loads(line)), dict)]
    except (OSError, json.JSONDecodeError):
        return []


def _get_message(webhook: str, message_id: str, timeout: float = 10.0) -> Mapping[str, Any]:
    _validate_webhook(webhook)
    if not SNOWFLAKE.fullmatch(message_id):
        raise ValueError("invalid_discord_message_id")
    url = f"{webhook.rstrip('/')}/messages/{message_id}"
    request = urllib.request.Request(url, headers={"User-Agent": "VibeTrading-TraceBackfill/1.0"})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        raw = response.read()
    value = json.loads(raw.decode("utf-8"))
    return value if isinstance(value, Mapping) else {}


def recover_rows(rows: Iterable[Mapping[str, Any]], *, source: str,
                 fetcher: Callable[[str], Mapping[str, Any]] | None) -> list[dict[str, Any]]:
    recovered: list[dict[str, Any]] = []
    for row in rows:
        event_id = str(row.get("event_id") or row.get("transition_id") or "").strip() or None
        message_id = str(row.get("discord_message_id") or "").strip() or None
        exact = row.get("delivery_timestamp_semantics") == "discord_message_timestamp" and row.get("discord_delivered_ts")
        base = {"source": source, "event_id": event_id, "trace_id": row.get("trace_id"),
                "discord_message_id": message_id, "execution_enabled": False, "can_submit_orders": False}
        if exact:
            recovered.append({**base, "status": "already_exact", "recoverable": True,
                              "discord_delivered_ts": row.get("discord_delivered_ts"), "response_hash": None})
            continue
        if not message_id:
            recovered.append({**base, "status": "unrecoverable", "recoverable": False,
                              "reason": "message_id_not_recorded", "discord_delivered_ts": None,
                              "response_hash": None})
            continue
        if fetcher is None:
            recovered.append({**base, "status": "not_configured", "recoverable": True,
                              "reason": "discord_webhook_not_configured", "discord_delivered_ts": None,
                              "response_hash": None})
            continue
        try:
            message = fetcher(message_id)
            returned_id = str(message.get("id") or "")
            timestamp = str(message.get("timestamp") or "").strip()
            parsed = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
            if returned_id != message_id or parsed.tzinfo is None:
                raise ValueError("discord_message_identity_or_timestamp_invalid")
            normalized = parsed.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
            digest = hashlib.sha256(json.dumps({"id": returned_id, "timestamp": normalized}, sort_keys=True).encode()).hexdigest()
            recovered.append({**base, "status": "recovered", "recoverable": True,
                              "discord_delivered_ts": normalized, "response_hash": digest})
        except urllib.error.HTTPError as exc:
            recovered.append({**base, "status": f"http_{exc.code}", "recoverable": True,
                              "discord_delivered_ts": None, "response_hash": None})
        except Exception as exc:
            recovered.append({**base, "status": "timeout" if "timeout" in type(exc).__name__.lower() else "missing",
                              "recoverable": True, "reason": type(exc).__name__,
                              "discord_delivered_ts": None, "response_hash": None})
    return recovered


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ledger", type=Path, default=DEFAULT_LEDGER)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    args = parser.parse_args()
    webhook = _env_value("SHADOW_ALERT_WEBHOOK_URL") or _env_value("DISCORD_WEBHOOK_URL")
    fetcher = (lambda message_id: _get_message(webhook, message_id)) if webhook else None
    output = [result for source, path in DEFAULT_INPUTS.items()
              for result in recover_rows(_rows(path), source=source, fetcher=fetcher)]
    args.ledger.parent.mkdir(parents=True, exist_ok=True)
    args.ledger.write_text("".join(json.dumps(row, sort_keys=True) + "\n" for row in output), encoding="utf-8")
    counts = {status: sum(row["status"] == status for row in output) for status in sorted({row["status"] for row in output})}
    report = {"provider": "discord_delivery_backfill", "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
              "records_reviewed": len(output), "counts": counts,
              "historical_gap_permanent": all(not row["recoverable"] for row in output) if output else None,
              "policy": "message_id_required_no_timestamp_inference", "execution_enabled": False, "can_submit_orders": False}
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(report, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


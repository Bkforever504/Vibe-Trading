from __future__ import annotations

import hashlib
import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


REQUIRED_OOS_METRICS = {
    "oos_trade_count",
    "oos_expectancy",
    "oos_profit_factor",
    "oos_max_drawdown",
}


def _identity_payload(card: dict[str, Any]) -> dict[str, Any]:
    return {
        "packet_id": card.get("packet_id"),
        "packet": card.get("packet"),
        "validation": card.get("validation"),
        "metrics": card.get("metrics"),
        "code_version": card.get("code_version"),
        "dataset_provenance": card.get("dataset_provenance"),
    }


def run_id(card: dict[str, Any]) -> str:
    encoded = json.dumps(_identity_payload(card), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()[:20]


def build_run_card(
    packet_id: str,
    packet: dict[str, Any],
    validation: dict[str, Any],
    metrics: dict[str, Any] | None,
    *,
    code_version: str,
    dataset_provenance: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if not validation.get("valid"):
        status = "validation_failed"
    elif metrics is None:
        status = "validated_not_backtested"
    elif not REQUIRED_OOS_METRICS.issubset(metrics):
        status = "incomplete_metrics"
    else:
        status = "research_complete"
    card: dict[str, Any] = {
        "schema_version": 1,
        "packet_id": packet_id,
        "packet": packet,
        "validation": validation,
        "metrics": metrics,
        "code_version": code_version,
        "dataset_provenance": dataset_provenance or {},
        "status": status,
        "execution_enabled": False,
        "can_submit_orders": False,
    }
    card["run_id"] = run_id(card)
    card["generated_at"] = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    return card


def write_run_card(card: dict[str, Any], directory: Path) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    identifier = str(card.get("run_id") or run_id(card))
    path = directory / f"{identifier}.json"
    encoded = (json.dumps(card, indent=2, sort_keys=True) + "\n").encode("utf-8")
    if path.exists():
        if path.read_bytes() != encoded:
            raise FileExistsError(f"run card already exists with different content: {path}")
        return path
    descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=directory)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(encoded)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass
    return path

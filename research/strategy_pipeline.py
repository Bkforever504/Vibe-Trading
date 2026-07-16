from __future__ import annotations

import hashlib
import json
import os
import tempfile
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any


RUNTIME_FIELDS = {"created_at", "updated_at", "status", "last_run_id", "packet_id"}
REQUIRED_SECTIONS = ("market", "rules", "data", "research", "provenance", "authority")
REQUIRED_RULES = ("setup", "entry", "stop", "targets", "exit", "sizing", "session")
REQUIRED_RESEARCH = (
    "dataset_start",
    "dataset_end",
    "oos_start",
    "oos_end",
    "benchmark",
    "cost_model",
)


@dataclass(frozen=True)
class ValidationResult:
    valid: bool
    errors: tuple[str, ...]
    warnings: tuple[str, ...] = ()


def canonical_packet(packet: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in packet.items() if key not in RUNTIME_FIELDS}


def packet_id(packet: dict[str, Any]) -> str:
    payload = json.dumps(canonical_packet(packet), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:20]


def _missing(value: Any) -> bool:
    return value is None or value == "" or value == [] or value == {}


def _date(value: Any) -> date | None:
    try:
        return date.fromisoformat(str(value))
    except (TypeError, ValueError):
        return None


def validate_packet(packet: dict[str, Any]) -> ValidationResult:
    errors: list[str] = []
    if packet.get("schema_version") != 1:
        errors.append("unsupported_schema_version")
    for field in ("name", "thesis"):
        if _missing(packet.get(field)):
            errors.append(f"missing_{field}")
    for section in REQUIRED_SECTIONS:
        if not isinstance(packet.get(section), dict) or not packet.get(section):
            errors.append(f"missing_{section}")

    market = packet.get("market") if isinstance(packet.get("market"), dict) else {}
    for field in ("asset_class", "symbols", "timeframe", "timezone"):
        if _missing(market.get(field)):
            errors.append(f"missing_market.{field}")

    rules = packet.get("rules") if isinstance(packet.get("rules"), dict) else {}
    for field in REQUIRED_RULES:
        if _missing(rules.get(field)):
            errors.append(f"missing_rules.{field}")

    research = packet.get("research") if isinstance(packet.get("research"), dict) else {}
    for field in REQUIRED_RESEARCH:
        if _missing(research.get(field)):
            errors.append(f"missing_research.{field}")
    parsed_dates = {field: _date(research.get(field)) for field in ("dataset_start", "dataset_end", "oos_start", "oos_end")}
    for field, parsed in parsed_dates.items():
        if research.get(field) not in (None, "") and parsed is None:
            errors.append(f"invalid_research.{field}")
    if parsed_dates["dataset_start"] and parsed_dates["dataset_end"]:
        if parsed_dates["dataset_start"] > parsed_dates["dataset_end"]:
            errors.append("research.dataset_window_reversed")
    if parsed_dates["oos_start"] and parsed_dates["oos_end"]:
        if parsed_dates["oos_start"] > parsed_dates["oos_end"]:
            errors.append("research.oos_window_reversed")

    authority = packet.get("authority") if isinstance(packet.get("authority"), dict) else {}
    expected = {
        "mode": "research_only",
        "execution_enabled": False,
        "can_submit_orders": False,
        "promotion_requires_human_approval": True,
    }
    for field, value in expected.items():
        if authority.get(field) != value:
            suffix = "must_be_false" if value is False else "must_be_true" if value is True else f"must_be_{value}"
            errors.append(f"authority.{field}_{suffix}")

    return ValidationResult(valid=not errors, errors=tuple(sorted(set(errors))))


def write_packet_atomic(packet: dict[str, Any], path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = dict(packet)
    payload["packet_id"] = packet_id(payload)
    encoded = (json.dumps(payload, indent=2, sort_keys=True) + "\n").encode("utf-8")
    if path.exists():
        if path.read_bytes() != encoded:
            raise FileExistsError(f"packet path already contains different content: {path}")
        return path
    descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
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

#!/usr/bin/env python3
"""Append-only hypothesis and experiment-family ledgers.

This module has no execution authority. It records immutable research state
transitions; callers derive current state from the latest event per candidate.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator


ROOT = Path(__file__).resolve().parent.parent
HYPOTHESIS_LEDGER_PATH = ROOT / "data" / "hypothesis_ledger.jsonl"
EXPERIMENT_FAMILY_PATH = ROOT / "data" / "experiment_family.jsonl"

SCHEMA_VERSION = 1
STATUSES = {
    "proposed",
    "development",
    "shadow",
    "paper_review",
    "approved",
    "rejected",
}
ORIGINS = {"research", "social", "external"}
STATUS_TRANSITIONS = {
    "proposed": {"development", "rejected"},
    "development": {"shadow", "rejected"},
    "shadow": {"paper_review", "rejected"},
    "paper_review": {"approved", "shadow", "rejected"},
    "approved": {"paper_review", "rejected"},
    "rejected": set(),
}
IMMUTABLE_FIELDS = ("id", "spec_hash", "spec_path", "family_id", "origin")


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    for line_number, raw in enumerate(path.read_text(encoding="utf-8-sig").splitlines(), 1):
        if not raw.strip():
            continue
        try:
            value = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ValueError(f"invalid_jsonl:{path}:{line_number}:{exc.msg}") from exc
        if not isinstance(value, dict):
            raise ValueError(f"jsonl_row_must_be_object:{path}:{line_number}")
        rows.append(value)
    return rows


@contextmanager
def ledger_lock(path: Path, timeout_seconds: float = 5.0) -> Iterator[None]:
    path.parent.mkdir(parents=True, exist_ok=True)
    lock_path = path.with_suffix(path.suffix + ".lock")
    deadline = time.monotonic() + timeout_seconds
    while True:
        try:
            descriptor = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            os.close(descriptor)
            break
        except FileExistsError:
            if time.monotonic() >= deadline:
                raise TimeoutError(f"ledger_lock_timeout:{lock_path}")
            time.sleep(0.05)
    try:
        yield
    finally:
        try:
            lock_path.unlink()
        except FileNotFoundError:
            pass


def _append_row(path: Path, row: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(row, separators=(",", ":"), sort_keys=True) + "\n")


def latest_hypotheses(path: Path = HYPOTHESIS_LEDGER_PATH) -> dict[str, dict[str, Any]]:
    latest: dict[str, dict[str, Any]] = {}
    for row in read_jsonl(path):
        candidate_id = str(row.get("id") or "")
        if candidate_id:
            latest[candidate_id] = row
    return latest


def validate_hypothesis(record: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    for field in IMMUTABLE_FIELDS:
        if not str(record.get(field) or "").strip():
            errors.append(f"missing_{field}")
    if record.get("status") not in STATUSES:
        errors.append("invalid_status")
    if record.get("origin") not in ORIGINS:
        errors.append("invalid_origin")
    spec_hash = str(record.get("spec_hash") or "")
    if not re.fullmatch(r"sha256:[0-9a-f]{64}", spec_hash):
        errors.append("invalid_spec_hash")
    if not str(record.get("proposed_at") or "").strip():
        errors.append("missing_proposed_at")
    for field in ("n_resolved", "distinct_sessions"):
        value = record.get(field)
        if not isinstance(value, int) or isinstance(value, bool) or value < 0:
            errors.append(f"invalid_{field}")
    if record.get("execution_enabled") is not False:
        errors.append("execution_enabled_must_be_false")
    if record.get("can_submit_orders") is not False:
        errors.append("can_submit_orders_must_be_false")
    return sorted(set(errors))


def append_hypothesis_event(
    candidate: dict[str, Any],
    path: Path = HYPOTHESIS_LEDGER_PATH,
    *,
    event_type: str = "state_transition",
) -> dict[str, Any]:
    current = latest_hypotheses(path).get(str(candidate.get("id") or ""))
    proposed_at = candidate.get("proposed_at") or (current or {}).get("proposed_at") or utc_now()
    row = {
        "schema_version": SCHEMA_VERSION,
        "event_type": event_type,
        "event_at": utc_now(),
        "id": candidate.get("id"),
        "proposed_at": proposed_at,
        "spec_hash": candidate.get("spec_hash"),
        "spec_path": candidate.get("spec_path"),
        "family_id": candidate.get("family_id"),
        "origin": candidate.get("origin"),
        "status": candidate.get("status"),
        "first_resolved_at": candidate.get("first_resolved_at"),
        "last_evaluated_at": candidate.get("last_evaluated_at"),
        "n_resolved": candidate.get("n_resolved", 0),
        "distinct_sessions": candidate.get("distinct_sessions", 0),
        "dsr": candidate.get("dsr"),
        "dsr_lower_bound": candidate.get("dsr_lower_bound"),
        "pbo": candidate.get("pbo"),
        "expectancy_lb": candidate.get("expectancy_lb"),
        "verdict_reason": candidate.get("verdict_reason"),
        "execution_enabled": False,
        "can_submit_orders": False,
    }
    errors = validate_hypothesis(row)
    if errors:
        raise ValueError(";".join(errors))
    if current:
        changed = [field for field in IMMUTABLE_FIELDS if row[field] != current.get(field)]
        if changed:
            raise ValueError("immutable_candidate_fields_changed:" + ",".join(changed))
        old_status = str(current.get("status"))
        new_status = str(row.get("status"))
        if new_status != old_status and new_status not in STATUS_TRANSITIONS.get(old_status, set()):
            raise ValueError(f"invalid_status_transition:{old_status}->{new_status}")
        comparable = {key: value for key, value in row.items() if key not in {"event_at"}}
        prior = {key: current.get(key) for key in comparable}
        if comparable == prior:
            return {"recorded": False, "duplicate": True, "id": row["id"], "status": row["status"]}
    identity = json.dumps(row, separators=(",", ":"), sort_keys=True)
    row["ledger_event_id"] = hashlib.sha256(identity.encode("utf-8")).hexdigest()[:24]
    with ledger_lock(path):
        # Re-read under lock so concurrent writers cannot fork the state history.
        locked_current = latest_hypotheses(path).get(str(row["id"]))
        if locked_current:
            if current is None or locked_current.get("ledger_event_id") != current.get("ledger_event_id"):
                raise RuntimeError(f"concurrent_hypothesis_update:{row['id']}")
        _append_row(path, row)
    return {"recorded": True, "duplicate": False, "id": row["id"], "status": row["status"]}


def record_frozen_spec(
    *,
    candidate_id: str,
    family_id: str,
    spec_hash: str,
    spec_path: str,
    origin: str,
    path: Path = EXPERIMENT_FAMILY_PATH,
) -> dict[str, Any]:
    if origin not in ORIGINS:
        raise ValueError("invalid_origin")
    if not re.fullmatch(r"sha256:[0-9a-f]{64}", spec_hash):
        raise ValueError("invalid_spec_hash")
    row = {
        "schema_version": SCHEMA_VERSION,
        "recorded_at": utc_now(),
        "candidate_id": candidate_id,
        "family_id": family_id,
        "spec_hash": spec_hash,
        "spec_path": spec_path,
        "origin": origin,
        "execution_enabled": False,
        "can_submit_orders": False,
    }
    with ledger_lock(path):
        rows = read_jsonl(path)
        existing = next((item for item in rows if item.get("spec_hash") == spec_hash), None)
        if existing:
            immutable = ("candidate_id", "family_id", "spec_path", "origin")
            if any(existing.get(field) != row.get(field) for field in immutable):
                raise ValueError("spec_hash_identity_conflict")
            return {"recorded": False, "duplicate": True, "family_size": len(rows)}
        _append_row(path, row)
        return {"recorded": True, "duplicate": False, "family_size": len(rows) + 1}


def experiment_family_size(path: Path = EXPERIMENT_FAMILY_PATH, family_id: str | None = None) -> int:
    rows = read_jsonl(path)
    hashes = {
        str(row.get("spec_hash"))
        for row in rows
        if row.get("spec_hash") and (family_id is None or row.get("family_id") == family_id)
    }
    return len(hashes)

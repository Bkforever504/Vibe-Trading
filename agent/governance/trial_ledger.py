"""Append-only lifetime trial ledger used by the DSR denominator."""
from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_LEDGER = ROOT / "data" / "governance" / "trial_ledger.jsonl"
DEFAULT_FAMILIES = ROOT / "config" / "signal_families.json"


def _rows(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        raise FileNotFoundError(path)
    rows = []
    for line in path.read_text(encoding="utf-8-sig").splitlines():
        if not line.strip():
            continue
        value = json.loads(line)
        if isinstance(value, dict):
            rows.append(value)
    return rows


def family_for(signal_id: str, *, descriptor: str = "", families_path: Path = DEFAULT_FAMILIES) -> str:
    config = json.loads(families_path.read_text(encoding="utf-8"))
    explicit = config.get("assignments") if isinstance(config.get("assignments"), Mapping) else {}
    if signal_id in explicit:
        return str(explicit[signal_id])
    haystack = f"{signal_id} {descriptor}".lower()
    for family, specification in (config.get("families") or {}).items():
        if isinstance(specification, Mapping):
            keywords = [
                *(specification.get("keywords") or []),
                *(specification.get("example_signals") or []),
            ]
        elif isinstance(specification, (list, tuple, set)):
            # Backward compatibility with the v1 ``family: [keywords]`` schema.
            keywords = specification
        else:
            keywords = []
        if any(str(keyword).lower() in haystack for keyword in keywords):
            return str(family)
    return str(config.get("default_family") or "unassigned")


def record_trial(signal_id: str, hypothesis_hash: str, timestamp: str | None = None, *,
                 family_key: str | None = None, legacy_backfill: bool = False,
                 path: Path = DEFAULT_LEDGER) -> bool:
    if not signal_id or not hypothesis_hash:
        raise ValueError("signal_id and hypothesis_hash are required")
    existing = _rows(path) if path.exists() else []
    if any(row.get("record_type") == "trial" and row.get("signal_id") == signal_id and
           row.get("hypothesis_hash") == hypothesis_hash for row in existing):
        return False
    family = family_key or family_for(signal_id)
    row = {"record_type": "trial", "signal_id": signal_id, "family_key": family,
           "hypothesis_hash": hypothesis_hash,
           "timestamp": timestamp or datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
           "legacy_backfill": bool(legacy_backfill),
           "denominator_note": "legacy trials are under-counted" if legacy_backfill else None,
           "execution_enabled": False, "can_submit_orders": False}
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(row, sort_keys=True, separators=(",", ":")) + "\n")
        handle.flush()
        os.fsync(handle.fileno())
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass
    return True


def count_trials(family_key: str, *, path: Path = DEFAULT_LEDGER) -> int:
    return len({(row.get("signal_id"), row.get("hypothesis_hash")) for row in _rows(path)
                if row.get("record_type") == "trial" and row.get("family_key") == family_key})


def hypothesis_hash(signal: Mapping[str, Any]) -> str:
    selected = {key: signal.get(key) for key in ("id", "script", "evidence_gate", "status", "promotion_gate")}
    return hashlib.sha256(json.dumps(selected, sort_keys=True, default=str).encode()).hexdigest()

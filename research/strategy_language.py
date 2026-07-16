from __future__ import annotations

from dataclasses import dataclass
from typing import Any


MATERIAL_FIELDS = ("symbols", "timeframe", "setup", "entry", "stop", "target", "exit", "sizing", "session")
SUPPORTED_KEYS = {
    "symbol",
    "symbols",
    "timeframe",
    "setup",
    "entry",
    "stop",
    "target",
    "targets",
    "exit",
    "sizing",
    "session",
    "benchmark",
    "dataset",
    "oos",
    "cost_model",
}


@dataclass(frozen=True)
class Interpretation:
    status: str
    fields: dict[str, Any]
    missing_fields: tuple[str, ...]
    ambiguities: tuple[str, ...]


def _symbols(value: str) -> list[str]:
    return [part.strip().lstrip("$").upper() for part in value.replace(",", " ").split() if part.strip()]


def interpret_description(description: str) -> Interpretation:
    parsed: dict[str, str] = {}
    ambiguities: list[str] = []
    for clause in description.split(";"):
        if ":" not in clause:
            if clause.strip():
                ambiguities.append("unstructured_description")
            continue
        key, value = clause.split(":", 1)
        key = key.strip().lower()
        value = value.strip()
        if key not in SUPPORTED_KEYS:
            ambiguities.append(f"unsupported_clause.{key or 'empty'}")
            continue
        if not value:
            ambiguities.append(f"empty_clause.{key}")
            continue
        parsed[key] = value

    symbol_text = parsed.get("symbols") or parsed.get("symbol") or ""
    target_text = parsed.get("targets") or parsed.get("target") or ""
    fields: dict[str, Any] = {
        "symbols": _symbols(symbol_text),
        "timeframe": parsed.get("timeframe"),
        "rules": {
            "setup": parsed.get("setup"),
            "entry": parsed.get("entry"),
            "stop": parsed.get("stop"),
            "targets": [part.strip() for part in target_text.split(",") if part.strip()],
            "exit": parsed.get("exit"),
            "sizing": parsed.get("sizing"),
            "session": parsed.get("session"),
        },
        "benchmark": parsed.get("benchmark"),
        "dataset": parsed.get("dataset"),
        "oos": parsed.get("oos"),
        "cost_model": parsed.get("cost_model"),
    }
    presence = {
        "symbols": fields["symbols"],
        "timeframe": fields["timeframe"],
        "setup": fields["rules"]["setup"],
        "entry": fields["rules"]["entry"],
        "stop": fields["rules"]["stop"],
        "target": fields["rules"]["targets"],
        "exit": fields["rules"]["exit"],
        "sizing": fields["rules"]["sizing"],
        "session": fields["rules"]["session"],
    }
    missing = tuple(field for field in MATERIAL_FIELDS if not presence[field])
    unique_ambiguities = tuple(sorted(set(ambiguities)))
    status = "ready_for_validation" if not missing and not unique_ambiguities else "needs_rules"
    return Interpretation(status=status, fields=fields, missing_fields=missing, ambiguities=unique_ambiguities)

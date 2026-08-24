#!/usr/bin/env python3
"""Validate frozen trading-hypothesis preregistrations without promoting them."""
from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parent.parent
SCHEMA_MARKER = "hypothesis-v2"
SUPPORTED_SCHEMAS = ("hypothesis-v1", "hypothesis-v2")
HASH_PLACEHOLDER = "sha256:<SPEC_HASH>"
REQUIRED_METADATA = (
    "Preregistration Schema",
    "Spec ID",
    "Family ID",
    "Origin",
    "Status",
    "Spec Hash",
)
V2_REQUIRED_METADATA = (
    "Universe ID",
    "Universe Version",
    "Universe Hash",
    "Membership As Of",
)
REQUIRED_SECTIONS = (
    "Entry Rule",
    "Exit Rule",
    "Universe",
    "Timestamp Basis",
    "Execution Policy",
    "Cost Stress",
)
V2_REQUIRED_SECTIONS = (
    "Experiment Family & Multiple Testing",
    "Regime Coverage",
    "Latency Budget",
    "Blocker EV Review",
    "Data Repair & Backfill",
    "Decay & Revalidation",
    "Universe Version",
)
METADATA_RE = re.compile(r"^([A-Za-z][A-Za-z ]+):\s*(.*?)\s*$", re.MULTILINE)
SECTION_RE = re.compile(r"^##\s+(.+?)\s*$", re.MULTILINE)
HASH_LINE_RE = re.compile(r"^Spec Hash:\s*.*$", re.MULTILINE)


def _normalize_text(text: str) -> str:
    return text.replace("\r\n", "\n").replace("\r", "\n").rstrip() + "\n"


def canonical_spec_text(text: str) -> str:
    normalized = _normalize_text(text)
    if HASH_LINE_RE.search(normalized):
        return HASH_LINE_RE.sub(f"Spec Hash: {HASH_PLACEHOLDER}", normalized, count=1)
    return normalized


def compute_spec_hash_text(text: str) -> str:
    digest = hashlib.sha256(canonical_spec_text(text).encode("utf-8")).hexdigest()
    return f"sha256:{digest}"


def compute_spec_hash(path: Path) -> str:
    return compute_spec_hash_text(path.read_text(encoding="utf-8-sig"))


def parse_spec(text: str) -> dict[str, Any]:
    metadata = {key.strip(): value.strip() for key, value in METADATA_RE.findall(text)}
    matches = list(SECTION_RE.finditer(text))
    sections: dict[str, str] = {}
    for index, match in enumerate(matches):
        start = match.end()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        sections[match.group(1).strip()] = text[start:end].strip()
    return {"metadata": metadata, "sections": sections}


def validate_spec(path: Path) -> dict[str, Any]:
    try:
        text = path.read_text(encoding="utf-8-sig")
    except OSError as exc:
        return {"path": str(path), "valid": False, "errors": [f"read_error:{exc}"]}
    parsed = parse_spec(text)
    metadata = parsed["metadata"]
    sections = parsed["sections"]
    errors: list[str] = []
    schema = metadata.get("Preregistration Schema")
    required_metadata = REQUIRED_METADATA + (V2_REQUIRED_METADATA if schema == "hypothesis-v2" else ())
    for field in required_metadata:
        if not metadata.get(field):
            errors.append(f"missing_metadata:{field}")
    required_sections = REQUIRED_SECTIONS + (V2_REQUIRED_SECTIONS if schema == "hypothesis-v2" else ())
    for section in required_sections:
        if len(sections.get(section, "").strip()) < 10:
            errors.append(f"missing_or_empty_section:{section}")
    if schema not in SUPPORTED_SCHEMAS:
        errors.append("unsupported_preregistration_schema")
    if metadata.get("Origin") not in {"research", "social", "external"}:
        errors.append("invalid_origin")
    if schema == "hypothesis-v2" and not re.fullmatch(r"sha256:[0-9a-f]{64}", str(metadata.get("Universe Hash") or "")):
        errors.append("invalid_universe_hash")
    if str(metadata.get("Status", "")).lower() != "frozen":
        errors.append("status_must_be_frozen")
    declared_hash = metadata.get("Spec Hash")
    computed_hash = compute_spec_hash_text(text)
    if declared_hash != computed_hash:
        errors.append("spec_hash_mismatch")
    execution_policy = sections.get("Execution Policy", "").lower().replace(" ", "")
    if "execution_enabled=false" not in execution_policy:
        errors.append("execution_policy_missing_execution_disabled")
    if "can_submit_orders=false" not in execution_policy:
        errors.append("execution_policy_missing_order_authority_disabled")
    return {
        "path": str(path),
        "valid": not errors,
        "errors": sorted(set(errors)),
        "metadata": metadata,
        "computed_spec_hash": computed_hash,
        "preregistration_schema": schema,
        "required_metadata": list(required_metadata),
        "required_sections": list(required_sections),
        "execution_enabled": False,
        "can_submit_orders": False,
    }


def discover_specs(root: Path) -> list[Path]:
    candidates: list[Path] = []
    for path in root.rglob("*.md"):
        if "TEMPLATE" in path.stem.upper():
            continue
        try:
            head = path.read_text(encoding="utf-8-sig")[:4096]
        except OSError:
            continue
        if any(f"Preregistration Schema: {schema}" in head for schema in SUPPORTED_SCHEMAS):
            candidates.append(path)
    return sorted(candidates)


def write_hash(path: Path) -> str:
    text = path.read_text(encoding="utf-8-sig")
    if not HASH_LINE_RE.search(text):
        raise ValueError("missing_metadata:Spec Hash")
    hashed = compute_spec_hash_text(text)
    updated = HASH_LINE_RE.sub(f"Spec Hash: {hashed}", _normalize_text(text), count=1)
    path.write_text(updated, encoding="utf-8", newline="\n")
    return hashed


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("paths", nargs="*", type=Path)
    parser.add_argument("--scan-root", type=Path, default=ROOT / "research")
    parser.add_argument("--write-hash", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    paths = args.paths or discover_specs(args.scan_root)
    if args.write_hash:
        for path in paths:
            write_hash(path)
    results = [validate_spec(path) for path in paths]
    report = {
        "provider": "preregistration_validator",
        "schema_version": 1,
        "validated": len(results),
        "valid": sum(1 for row in results if row["valid"]),
        "invalid": sum(1 for row in results if not row["valid"]),
        "results": results,
        "execution_enabled": False,
        "can_submit_orders": False,
    }
    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        for result in results:
            label = "PASS" if result["valid"] else "FAIL"
            print(f"{label} {result['path']}")
            for error in result["errors"]:
                print(f"  - {error}")
        print(f"validated={report['validated']} valid={report['valid']} invalid={report['invalid']}")
    return 1 if report["invalid"] else 0


if __name__ == "__main__":
    raise SystemExit(main())

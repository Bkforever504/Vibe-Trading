#!/usr/bin/env python3
"""Fail closed on invalid preregistrations and unauditable research rejects."""
from __future__ import annotations

import argparse
import re
from pathlib import Path

try:
    from scripts.hypothesis_ledger import read_jsonl, validate_hypothesis
    from scripts.preregistration_validator import SCHEMA_MARKER, validate_spec
except ModuleNotFoundError:  # Direct ``python scripts/...`` execution.
    from hypothesis_ledger import read_jsonl, validate_hypothesis
    from preregistration_validator import SCHEMA_MARKER, validate_spec


ROOT = Path(__file__).resolve().parents[1]


def validate_paths(paths: list[Path]) -> list[str]:
    errors: list[str] = []
    for raw in paths:
        path = raw if raw.is_absolute() else ROOT / raw
        if path.suffix.lower() == ".md" and "research" in {part.lower() for part in path.parts}:
            try:
                content = path.read_text(encoding="utf-8-sig")
            except OSError as exc:
                errors.append(f"{path}:read_error:{exc}")
                continue
            if f"Preregistration Schema: {SCHEMA_MARKER}" in content and "TEMPLATE" not in path.name.upper():
                errors.extend(f"{path}:{item}" for item in validate_spec(path)["errors"])
        if path.name == "hypothesis_ledger.jsonl" and path.exists():
            for line, row in enumerate(read_jsonl(path), 1):
                errors.extend(f"{path}:{line}:{item}" for item in validate_hypothesis(row))
                if row.get("status") == "rejected":
                    reason = str(row.get("verdict_reason") or "")
                    if not re.search(r"\bPROMO_[A-Z0-9_]+_V\d+\b", reason):
                        errors.append(f"{path}:{line}:rejection_missing_rule_id")
                    if "result=" not in reason:
                        errors.append(f"{path}:{line}:rejection_missing_result_path")
    return sorted(set(errors))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("paths", nargs="*", type=Path)
    args = parser.parse_args()
    targets = args.paths or list((ROOT / "research").glob("*.md"))
    errors = validate_paths(targets)
    for error in errors:
        print(error)
    print(f"research_guard files={len(targets)} errors={len(errors)} execution_enabled=false can_submit_orders=false")
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Append only known-safe local-artifact patterns to .gitignore."""
from __future__ import annotations

import argparse
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TARGET = ROOT / ".gitignore"
PATTERNS = (".pytest_cache/", ".pytest-*/", "__pycache__/", "~*", ".hold/", "data/scratch/", "data/hygiene/")


def updated(text: str) -> tuple[str, list[str]]:
    existing = {line.strip() for line in text.splitlines()}
    missing = [item for item in PATTERNS if item not in existing]
    if not missing:
        return text, []
    suffix = "" if not text or text.endswith("\n") else "\n"
    return text + suffix + "\n# Local hygiene and test scratch\n" + "\n".join(missing) + "\n", missing


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    before = TARGET.read_text(encoding="utf-8") if TARGET.exists() else ""
    after, missing = updated(before)
    print("missing=" + ",".join(missing))
    if not args.dry_run and missing:
        TARGET.write_text(after, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

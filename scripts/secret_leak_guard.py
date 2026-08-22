#!/usr/bin/env python3
"""Scan tracked or staged text without printing any suspected secret value."""
from __future__ import annotations

import argparse
import re
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TEXT_SUFFIXES = {".py", ".ts", ".tsx", ".js", ".json", ".jsonl", ".md", ".txt", ".log", ".yml", ".yaml", ".ps1", ".sh"}
KEY_NAME = r"(?:api(?:[_-][a-z0-9]+)*[_-]key|secret[_-]key|client[_-]secret|access[_-]token|password)"
ASSIGNMENT = re.compile(rf"(?i)[\"']?\b({KEY_NAME})\b[\"']?\s*[:=]\s*[\"']([^\"']{{16,}})[\"']")
ENV_ASSIGNMENT = re.compile(rf"(?i)^\s*(?:export\s+)?({KEY_NAME})\s*=\s*([^\s#]{{16,}})\s*$")
HIGH_RISK = re.compile(r"(?:AKIA[0-9A-Z]{16}|gh[pousr]_[A-Za-z0-9]{30,}|(?<![A-Za-z0-9])sk-[A-Za-z0-9_-]{32,})")
PLACEHOLDERS = ("placeholder", "replace", "example", "dummy", "redacted", "test", "your_")


def _git_paths(staged: bool) -> list[Path]:
    command = ["git", "diff", "--cached", "--name-only", "--diff-filter=ACMR"] if staged else ["git", "ls-files"]
    completed = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, check=False)
    return [ROOT / line for line in completed.stdout.splitlines() if line.strip()]


def scan_paths(paths: list[Path]) -> list[str]:
    findings: list[str] = []
    for path in paths:
        if path.name == Path(__file__).name or not path.exists() or path.suffix.lower() not in TEXT_SUFFIXES:
            continue
        lower_name = path.name.lower()
        if (lower_name == ".env" or (("api-key" in lower_name or "token" in lower_name) and path.suffix.lower() in {".txt", ".env", ".log"})) and not any(word in lower_name for word in ("example", "template", "schema")):
            findings.append(f"{path}:sensitive_filename")
        try:
            lines = path.read_text(encoding="utf-8-sig", errors="ignore").splitlines()
        except OSError:
            continue
        for line_number, line in enumerate(lines, 1):
            assigned = [match.group(2) for match in ASSIGNMENT.finditer(line)]
            env_match = ENV_ASSIGNMENT.match(line) if path.suffix.lower() in {".env", ".txt", ".log"} or path.name == ".env" else None
            if env_match:
                assigned.append(env_match.group(2).strip("\"'"))
            high_risk = HIGH_RISK.findall(line)
            for candidate in [*assigned, *high_risk]:
                fixture_only = "tests" in {part.lower() for part in path.parts} and candidate not in high_risk
                if not fixture_only and not any(marker in candidate.lower() for marker in PLACEHOLDERS):
                    findings.append(f"{path}:{line_number}:suspected_secret")
                    break
            if "BEGIN " + "PRIVATE KEY" in line:
                findings.append(f"{path}:{line_number}:private_key_material")
    return sorted(set(findings))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--staged", action="store_true")
    parser.add_argument("paths", nargs="*", type=Path)
    args = parser.parse_args()
    paths = [path if path.is_absolute() else ROOT / path for path in args.paths] or _git_paths(args.staged)
    findings = scan_paths(paths)
    for finding in findings:
        print(finding)
    print(f"secret_leak_guard files={len(paths)} findings={len(findings)}")
    return 1 if findings else 0


if __name__ == "__main__":
    raise SystemExit(main())

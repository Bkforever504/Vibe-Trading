#!/usr/bin/env python3
"""Read-only working-tree inventory for safe workstream isolation."""
from __future__ import annotations

import argparse
import re
import subprocess
from collections import defaultdict
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
REPORT_DIR = ROOT / "data" / "hygiene"
SECRET_NAME = re.compile(r"(?i)(^|/)(\.env[^/]*|[^/]*(credential|token|secret)[^/]*|[^/]+\.(key|pem))$")
PYTEST = re.compile(r"(^|/)(\.pytest_cache/|\.pytest-[^/]+/|__pycache__/)")
CV_PREFIXES = ("agent/governance/", "agent/analytics/", "data/governance/")
CV_EXACT = {
    "agent/tests/test_statistical_gate.py", "agent/tests/test_trial_ledger.py",
    "agent/tests/test_outcome_bootstrap.py", "agent/tests/test_paired_bootstrap.py",
    "agent/tests/test_statistical_governance_report.py", "config/signal_families.json",
    "scripts/statistical_governance_report.py", "scripts/reevaluate_existing_promoted_signals.py",
    "docs/STATISTICAL_PROMOTION_GATE.md", "docs/BOOTSTRAP_CI.md", "data/latency_pairs.jsonl",
}


def status_entries(text: str) -> list[tuple[str, str]]:
    result = []
    for line in text.splitlines():
        if len(line) < 4:
            continue
        raw = line[3:].strip().replace("\\", "/")
        path = raw.split(" -> ")[-1].strip('"')
        result.append((line[:2], path))
    return result


def classify(path: str, *, tracked: bool = False) -> str:
    if SECRET_NAME.search(path):
        return "secret_candidate"
    if PYTEST.search(path):
        return "pytest_cache"
    if path.startswith(".hold/") or path.startswith("data/scratch/") or path.startswith("output/") or Path(path).name.startswith("~"):
        return "local_scratch"
    if path in CV_EXACT or path.startswith(CV_PREFIXES):
        return "workstream_ws_cv_bootstrap"
    if path.startswith("agent/observability/") or path == "docs/END_TO_END_TRACING.md":
        return "workstream_ws_trace"
    if any(token in path.lower() for token in ("databento", "nbbo", "edgar", "institutional_confluence", "premarket_thesis")):
        return "workstream_ws_edgar"
    return "workstream_unknown_but_meaningful" if tracked or Path(path).suffix else "deletion_candidate_unknown"


def git(*args: str) -> str:
    return subprocess.run(["git", *args], cwd=ROOT, check=True, capture_output=True,
                          text=True, encoding="utf-8", errors="replace").stdout


def build_report(status: str) -> tuple[str, dict[str, list[str]]]:
    tracked_paths = set(git("ls-files").replace("\\", "/").splitlines())
    groups: dict[str, list[str]] = defaultdict(list)
    for _code, path in status_entries(status):
        groups[classify(path, tracked=path in tracked_paths)].append(path)
    order = ["secret_candidate", "pytest_cache", "local_scratch", "workstream_ws_cv_bootstrap",
             "workstream_ws_trace", "workstream_ws_edgar", "workstream_unknown_but_meaningful",
             "deletion_candidate_unknown"]
    lines = [f"# Working-tree categorization — {date.today().isoformat()}", "",
             "Read-only inventory. No path was staged, moved, or deleted.", "", "## Counts", ""]
    lines += [f"- `{name}`: {len(groups.get(name, []))}" for name in order]
    for name in order:
        lines += ["", f"## {name}", ""]
        lines += [f"- `{path}`" for path in sorted(groups.get(name, []))] or ["- None"]
    return "\n".join(lines) + "\n", dict(groups)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report-dir", type=Path, default=REPORT_DIR)
    args = parser.parse_args()
    status = git("status", "--porcelain=v1", "--untracked-files=all")
    report, groups = build_report(status)
    args.report_dir.mkdir(parents=True, exist_ok=True)
    target = args.report_dir / f"categorization_report_{date.today().isoformat()}.md"
    target.write_text(report, encoding="utf-8")
    (args.report_dir / "pre_hygiene_status.txt").write_text(status, encoding="utf-8")
    (args.report_dir / "pre_hygiene_stash_list.txt").write_text(git("stash", "list"), encoding="utf-8")
    (args.report_dir / "pre_hygiene_branch.txt").write_text(git("branch", "-vv"), encoding="utf-8")
    print(f"report={target} entries={sum(map(len, groups.values()))} secrets={len(groups.get('secret_candidate', []))}")
    return 2 if groups.get("secret_candidate") else 0


if __name__ == "__main__":
    raise SystemExit(main())

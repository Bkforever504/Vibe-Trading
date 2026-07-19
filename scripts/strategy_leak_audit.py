#!/usr/bin/env python3
"""Read-only strategy leak/look-ahead audit.

Scans strategy source files for common backtest contamination patterns:
future bars, centered rolling windows, full-dataset normalization, same-bar
high/low assumptions, and unshifted signals. This is an intake/gov tool only.
It never places orders.
"""
from __future__ import annotations

import argparse
import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
LOG_PATH = ROOT / "data" / "strategy_leak_audit_log.jsonl"
REPORT_PATH = Path.home() / ".vibe-trading" / "reports" / "strategy-leak-audit.json"


@dataclass(frozen=True)
class LeakRule:
    rule_id: str
    severity: str
    description: str
    pattern: re.Pattern[str]


RULES = [
    LeakRule("future_shift", "critical", "Negative shift can use future bars.", re.compile(r"\.shift\s*\(\s*-\d+")),
    LeakRule("future_index", "critical", "Forward indexing can use future candles.", re.compile(r"\[[^\]\n]*i\s*\+\s*\d+")),
    LeakRule("pine_lookahead", "critical", "Pine lookahead_on leaks future higher-timeframe data.", re.compile(r"barmerge\.lookahead_on|lookahead\s*=\s*true", re.I)),
    LeakRule("centered_rolling", "warning", "Centered rolling windows use future observations.", re.compile(r"rolling\s*\([^)]*center\s*=\s*True", re.I)),
    LeakRule("global_minmax", "warning", "Full-dataset min/max normalization can leak future ranges.", re.compile(r"\.(min|max)\s*\(\s*\).*?(\-|/)|MinMaxScaler\s*\(", re.I)),
    LeakRule("same_day_extreme", "warning", "Same-bar high/low can be unavailable at decision time.", re.compile(r"\b(high|low)\b.*\b(entry|signal|buy|sell)|\b(entry|signal|buy|sell)\b.*\b(high|low)\b", re.I)),
    LeakRule("unshifted_signal", "info", "Signal may need one-bar shift before fills.", re.compile(r"signal\s*=|entry_signal\s*=|entries\s*=", re.I)),
]


def scan_text(source: str, *, path: str = "<memory>") -> dict[str, Any]:
    findings: list[dict[str, Any]] = []
    lines = source.splitlines()
    for idx, line in enumerate(lines, start=1):
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or stripped.startswith("//"):
            continue
        for rule in RULES:
            if rule.pattern.search(line):
                findings.append({
                    "rule_id": rule.rule_id,
                    "severity": rule.severity,
                    "line": idx,
                    "snippet": stripped[:180],
                    "description": rule.description,
                })
    severity_order = {"critical": 3, "warning": 2, "info": 1}
    max_severity = max((severity_order.get(f["severity"], 0) for f in findings), default=0)
    if max_severity >= 3:
        verdict = "reject_until_fixed"
    elif max_severity == 2:
        verdict = "needs_review"
    elif max_severity == 1:
        verdict = "review_shift_assumption"
    else:
        verdict = "clean"
    return {
        "path": path,
        "finding_count": len(findings),
        "critical_count": sum(1 for f in findings if f["severity"] == "critical"),
        "warning_count": sum(1 for f in findings if f["severity"] == "warning"),
        "info_count": sum(1 for f in findings if f["severity"] == "info"),
        "verdict": verdict,
        "findings": findings,
    }


def scan_file(path: Path) -> dict[str, Any]:
    try:
        source = path.read_text(encoding="utf-8", errors="replace")
    except Exception as exc:
        return {
            "path": str(path),
            "finding_count": 0,
            "critical_count": 0,
            "warning_count": 0,
            "info_count": 0,
            "verdict": "error",
            "error": str(exc)[:180],
            "findings": [],
        }
    return scan_text(source, path=str(path))


def build_report(paths: list[Path]) -> dict[str, Any]:
    audits = [scan_file(path) for path in paths]
    return {
        "date": datetime.now(timezone.utc).date().isoformat(),
        "timestamp": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "provider": "strategy_leak_audit",
        "mode": "read_only",
        "execution_enabled": False,
        "can_submit_orders": False,
        "files_scanned": len(audits),
        "critical_files": sum(1 for item in audits if item.get("critical_count", 0) > 0),
        "needs_review_files": sum(1 for item in audits if item.get("verdict") in {"needs_review", "review_shift_assumption"}),
        "audits": audits,
        "warnings": [
            "Read-only intake audit. No orders are placed.",
            "A clean scan does not prove a strategy is valid; it only removes obvious leak patterns.",
        ],
    }


def append_log(report: dict[str, Any], path: Path = LOG_PATH) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(report, separators=(",", ":"), default=str) + "\n")


def write_report(report: dict[str, Any], path: Path = REPORT_PATH) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    return path


def print_report(report: dict[str, Any]) -> None:
    print("\nStrategy Leak Audit | read-only")
    print("=" * 72)
    print(
        f"files={report['files_scanned']} critical_files={report['critical_files']} "
        f"needs_review={report['needs_review_files']} execution_enabled={report['execution_enabled']}"
    )
    for item in report["audits"]:
        print(f"{item['verdict']:<20} {item['finding_count']:>2} findings | {item['path']}")
    print("No orders placed.\n")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("paths", nargs="+", type=Path)
    parser.add_argument("--log-path", type=Path, default=LOG_PATH)
    parser.add_argument("--report-path", type=Path, default=REPORT_PATH)
    parser.add_argument("--print", action="store_true", dest="print_output")
    args = parser.parse_args()
    report = build_report(args.paths)
    append_log(report, args.log_path)
    write_report(report, args.report_path)
    if args.print_output:
        print_report(report)
    else:
        print(f"Strategy leak audit written to {args.report_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

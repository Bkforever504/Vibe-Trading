"""Read-only report for Flip Bot 0DTE shadow candidate logs."""
from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
LOG_PATH = ROOT / "data" / "flip_shadow_candidates_log.jsonl"
REPORT_PATH = Path.home() / ".vibe-trading" / "reports" / "flip-shadow-candidates.json"


def read_rows(path: Path = LOG_PATH) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(row, dict):
            rows.append(row)
    return rows


def build_report(path: Path = LOG_PATH) -> dict[str, Any]:
    rows = read_rows(path)
    by_symbol = Counter(str(row.get("symbol", "")) for row in rows if row.get("symbol"))
    by_right = Counter(str(row.get("right", "")) for row in rows if row.get("right"))
    latest = rows[-1] if rows else None
    return {
        "provider": "flip_shadow_candidates_report",
        "mode": "read_only",
        "execution_enabled": False,
        "source_path": str(path),
        "sample_count": len(rows),
        "by_symbol": dict(by_symbol),
        "by_right": dict(by_right),
        "latest": latest,
        "warnings": [
            "Shadow-only report. No broker calls are made.",
            "QQQ/NVDA/TSLA require 30-day review before promotion.",
        ],
    }


def write_report(report: dict[str, Any], path: Path = REPORT_PATH) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def print_report(report: dict[str, Any]) -> None:
    print("\nFlip Shadow Candidates | read-only")
    print("=" * 58)
    print(f"Rows: {report['sample_count']}")
    print(f"By symbol: {report['by_symbol']}")
    print(f"By right: {report['by_right']}")
    print(f"Report: {REPORT_PATH}\n")


def main() -> int:
    parser = argparse.ArgumentParser(description="Report Flip Bot shadow candidate logs.")
    parser.add_argument("--log-path", type=Path, default=LOG_PATH)
    parser.add_argument("--report-path", type=Path, default=REPORT_PATH)
    parser.add_argument("--print", action="store_true", dest="do_print")
    args = parser.parse_args()
    report = build_report(args.log_path)
    write_report(report, args.report_path)
    if args.do_print:
        print_report(report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

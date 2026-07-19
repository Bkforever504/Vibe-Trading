#!/usr/bin/env python3
"""Read-only coverage report for point-in-time option quote samples."""
from __future__ import annotations

import argparse
import json
import os
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


VIBE_HOME = Path.home() / ".vibe-trading"
SAMPLES_PATH = VIBE_HOME / "logs" / "option-quote-samples.jsonl"
REPORT_PATH = VIBE_HOME / "reports" / "option-quote-sample-coverage.json"
ROOT = Path(__file__).resolve().parent.parent
LOG_PATH = ROOT / "data" / "option_quote_sample_coverage_log.jsonl"
REQUIRED_EVENTS = ("fill", "monitor", "exit")


def _read_jsonl(path: Path) -> tuple[list[dict[str, Any]], int]:
    try:
        lines = path.read_text(encoding="utf-8-sig").splitlines()
    except OSError:
        return [], 0
    rows: list[dict[str, Any]] = []
    bad = 0
    for line in lines:
        if not line.strip():
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            bad += 1
            continue
        if isinstance(payload, dict):
            rows.append(payload)
    return rows, bad


def _key(row: dict[str, Any]) -> str:
    return str(row.get("trade_id") or row.get("order_id") or row.get("contract") or "unknown")


def build_report(samples_path: Path = SAMPLES_PATH) -> dict[str, Any]:
    rows, bad_json_count = _read_jsonl(samples_path)
    event_counts = Counter(str(row.get("event") or "unknown") for row in rows)
    status_counts = Counter(
        str((row.get("provenance") if isinstance(row.get("provenance"), dict) else {}).get("status") or "unknown")
        for row in rows
    )
    by_key: dict[str, Counter[str]] = defaultdict(Counter)
    for row in rows:
        by_key[_key(row)][str(row.get("event") or "unknown")] += 1
    complete_keys = [
        key for key, counts in by_key.items()
        if all(counts[event] > 0 for event in REQUIRED_EVENTS)
    ]
    latest_samples = sorted(rows, key=lambda row: str(row.get("captured_at") or ""))[-10:]
    return {
        "provider": "option_quote_sample_coverage",
        "mode": "read_only",
        "execution_enabled": False,
        "can_submit_orders": False,
        "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "samples_path": str(samples_path),
        "samples_file_exists": samples_path.exists(),
        "sample_count": len(rows),
        "bad_json_count": bad_json_count,
        "event_counts": dict(sorted(event_counts.items())),
        "provenance_status_counts": dict(sorted(status_counts.items())),
        "tracked_key_count": len(by_key),
        "complete_fill_monitor_exit_key_count": len(complete_keys),
        "required_events": list(REQUIRED_EVENTS),
        "latest_samples": [
            {
                "captured_at": row.get("captured_at"),
                "event": row.get("event"),
                "trade_id": row.get("trade_id"),
                "order_id": row.get("order_id"),
                "contract": row.get("contract"),
                "provenance_status": (row.get("provenance") if isinstance(row.get("provenance"), dict) else {}).get("status"),
            }
            for row in latest_samples
        ],
        "warnings": [
            "Read-only coverage report. This report cannot submit orders or fetch quotes.",
            "A missing file usually means no point-in-time quote capture has run yet.",
            "Complete path telemetry requires fill, monitor, and exit samples for the same trade/order/contract key.",
        ],
    }


def write_report(report: dict[str, Any], path: Path = REPORT_PATH) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(temp, path)


def append_log(report: dict[str, Any], path: Path = LOG_PATH) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(report, separators=(",", ":"), sort_keys=True) + "\n")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--samples-path", type=Path, default=SAMPLES_PATH)
    parser.add_argument("--report-path", type=Path, default=REPORT_PATH)
    parser.add_argument("--log-path", type=Path, default=LOG_PATH)
    parser.add_argument("--print", action="store_true", dest="do_print")
    args = parser.parse_args()
    report = build_report(args.samples_path)
    write_report(report, args.report_path)
    append_log(report, args.log_path)
    if args.do_print:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        print(f"Option quote sample coverage report written to {args.report_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

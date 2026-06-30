#!/usr/bin/env python3
"""Read-only health report for the new signal stack.

Checks:
- Windows Task Scheduler status for each signal task.
- Latest JSONL row for each expected log.
- Missing/stale/error rows.

No trading. No broker calls. Safe to run any time.
"""
from __future__ import annotations

import argparse
import json
import subprocess
from datetime import date, datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
REPORT_DIR = Path.home() / ".vibe-trading" / "reports"
REPORT_PATH = REPORT_DIR / "signal-stack-health.json"


SIGNALS = [
    {
        "name": "GEX Scanner",
        "task": r"\VibeTrade\GEXScanner",
        "log": ROOT / "data" / "gex_scan_log.jsonl",
        "kind": "morning",
    },
    {
        "name": "IVR Scanner",
        "task": r"\VibeTrade\IVRScanner",
        "log": ROOT / "data" / "iv_history_log.jsonl",
        "kind": "morning",
    },
    {
        "name": "TTM Squeeze",
        "task": r"\VibeTrade\TTMSqueezeShadowLogger",
        "log": ROOT / "data" / "ttm_squeeze_shadow_log.jsonl",
        "kind": "close",
    },
    {
        "name": "WaveTrend",
        "task": r"\VibeTrade\WaveTrendShadowLogger",
        "log": ROOT / "data" / "wavetrend_shadow_log.jsonl",
        "kind": "close",
    },
    {
        "name": "SMC",
        "task": r"\VibeTrade\SMCShadowLogger",
        "log": ROOT / "data" / "smc_shadow_log.jsonl",
        "kind": "close",
    },
]


def _latest_jsonl(path: Path) -> tuple[dict | None, int, str | None]:
    if not path.exists():
        return None, 0, "missing"
    rows = []
    bad_lines = 0
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            bad_lines += 1
            continue
        if isinstance(row, dict):
            rows.append(row)
    if not rows:
        return None, 0, "empty" if bad_lines == 0 else f"invalid_json_lines={bad_lines}"
    warning = f"invalid_json_lines={bad_lines}" if bad_lines else None
    return rows[-1], len(rows), warning


def _task_status(task_name: str) -> dict:
    try:
        proc = subprocess.run(
            ["schtasks", "/Query", "/TN", task_name, "/FO", "LIST"],
            check=False,
            capture_output=True,
            text=True,
            timeout=15,
        )
    except Exception as exc:
        return {"available": False, "status": "unknown", "error": str(exc)[:160]}
    if proc.returncode != 0:
        return {
            "available": False,
            "status": "missing",
            "error": (proc.stderr or proc.stdout).strip()[:160],
        }
    parsed = {}
    for raw in proc.stdout.splitlines():
        if ":" not in raw:
            continue
        key, value = raw.split(":", 1)
        parsed[key.strip().lower().replace(" ", "_")] = value.strip()
    return {
        "available": True,
        "status": parsed.get("status", "unknown"),
        "next_run_time": parsed.get("next_run_time", ""),
        "last_run_time": parsed.get("last_run_time", ""),
    }


def _row_has_errors(row: dict | None) -> list[str]:
    if not row:
        return []
    errors: list[str] = []
    scans = row.get("scans")
    if isinstance(scans, list):
        for scan in scans:
            if isinstance(scan, dict) and scan.get("status") == "error":
                errors.append(f"{scan.get('symbol', '?')}: {scan.get('error', 'error')}")
    for key in ("primary", "comparison"):
        section = row.get(key)
        if isinstance(section, dict) and section.get("error"):
            errors.append(f"{key}: {section.get('error')}")
    return errors


def build_report(today: date | None = None) -> dict:
    today = today or date.today()
    today_str = today.isoformat()
    items = []
    for signal in SIGNALS:
        latest, row_count, parse_warning = _latest_jsonl(signal["log"])
        task = _task_status(signal["task"])
        latest_date = str((latest or {}).get("date", ""))
        errors = _row_has_errors(latest)
        if latest is None:
            health = "missing"
        elif latest_date != today_str:
            health = "stale"
        elif errors:
            health = "error"
        else:
            health = "ok"
        warnings = []
        if parse_warning:
            warnings.append(parse_warning)
        if task.get("status") != "Ready":
            warnings.append(f"task_status={task.get('status')}")
        if latest_date and latest_date != today_str:
            warnings.append(f"latest_date={latest_date}")
        warnings.extend(errors)
        items.append({
            "name": signal["name"],
            "kind": signal["kind"],
            "task": signal["task"],
            "task_status": task,
            "log_path": str(signal["log"]),
            "row_count": row_count,
            "latest_date": latest_date,
            "health": health,
            "warnings": warnings,
        })
    summary = {
        "ok": sum(1 for item in items if item["health"] == "ok"),
        "stale": sum(1 for item in items if item["health"] == "stale"),
        "missing": sum(1 for item in items if item["health"] == "missing"),
        "error": sum(1 for item in items if item["health"] == "error"),
    }
    return {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "date": today_str,
        "summary": summary,
        "items": items,
    }


def write_report(report: dict, path: Path = REPORT_PATH) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def print_report(report: dict) -> None:
    print("\nSignal Stack Health | " + report["date"])
    print("=" * 72)
    print(
        f"OK={report['summary']['ok']}  "
        f"STALE={report['summary']['stale']}  "
        f"MISSING={report['summary']['missing']}  "
        f"ERROR={report['summary']['error']}"
    )
    print()
    for item in report["items"]:
        task = item["task_status"]
        warn = "; ".join(item["warnings"]) if item["warnings"] else "-"
        print(
            f"{item['name']:<16} health={item['health']:<7} "
            f"task={task.get('status', '?'):<8} rows={item['row_count']:<3} "
            f"latest={item['latest_date'] or '-':<10} next={task.get('next_run_time', '-')}"
        )
        if warn != "-":
            print(f"  warnings: {warn}")
    print(f"\nJSON: {REPORT_PATH}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Check new signal stack task/log health.")
    parser.add_argument("--no-write", action="store_true", help="Do not write JSON report.")
    args = parser.parse_args()
    report = build_report()
    print_report(report)
    if not args.no_write:
        write_report(report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

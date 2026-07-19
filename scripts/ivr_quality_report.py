#!/usr/bin/env python3
"""Read-only quality report for the Alpaca IVR scanner.

The IVR scanner is useful only if it keeps producing real ATM IV readings and
eventually has enough history for true IVR. This report grades that data feed
without changing any bot behavior.
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.ivr_scanner import LOG_PATH as IVR_LOG_PATH, SYMBOLS

REPORT_PATH = Path.home() / ".vibe-trading" / "reports" / "ivr-quality-report.json"
LOG_PATH = ROOT / "data" / "ivr_quality_report_log.jsonl"
MIN_HISTORY_DAYS = 30


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        raw = raw.strip()
        if not raw:
            continue
        try:
            row = json.loads(raw)
        except json.JSONDecodeError:
            continue
        if isinstance(row, dict):
            rows.append(row)
    return rows


def _flatten_scans(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    scans: list[dict[str, Any]] = []
    for row in rows:
        for scan in row.get("scans", []):
            if not isinstance(scan, dict):
                continue
            scans.append({
                "date": row.get("date"),
                "timestamp": row.get("timestamp"),
                **scan,
            })
    return scans


def _status_for(symbol_rows: list[dict[str, Any]]) -> str:
    if not symbol_rows:
        return "missing"
    ok = [row for row in symbol_rows if row.get("status") in {"ok", "accumulating"} and row.get("atm_iv") is not None]
    true_ivr = [row for row in symbol_rows if row.get("status") == "ok" and row.get("ivr") is not None]
    latest_history = max(int(row.get("history_days") or 0) for row in symbol_rows)
    ok_rate = len(ok) / len(symbol_rows)
    if latest_history < MIN_HISTORY_DAYS:
        return "building" if ok_rate >= 0.8 else "needs_attention"
    if len(true_ivr) / len(symbol_rows) >= 0.8:
        return "good"
    return "needs_attention"


def build_report(
    *,
    ivr_log_path: Path = IVR_LOG_PATH,
    symbols: list[str] | None = None,
) -> dict[str, Any]:
    symbols = symbols or SYMBOLS
    rows = _read_jsonl(ivr_log_path)
    scans = _flatten_scans(rows)
    by_symbol: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for scan in scans:
        sym = str(scan.get("symbol") or "")
        if sym:
            by_symbol[sym].append(scan)

    symbol_reports: list[dict[str, Any]] = []
    totals = Counter()
    for sym in symbols:
        sym_rows = by_symbol.get(sym, [])
        status_counts = Counter(str(row.get("status") or "unknown") for row in sym_rows)
        atm_iv_count = sum(1 for row in sym_rows if row.get("atm_iv") is not None)
        true_ivr_count = sum(1 for row in sym_rows if row.get("ivr") is not None)
        latest = sym_rows[-1] if sym_rows else {}
        latest_history = int(latest.get("history_days") or 0)
        report = {
            "symbol": sym,
            "status": _status_for(sym_rows),
            "readings": len(sym_rows),
            "atm_iv_readings": atm_iv_count,
            "true_ivr_readings": true_ivr_count,
            "latest_date": latest.get("date"),
            "latest_status": latest.get("status"),
            "latest_history_days": latest_history,
            "latest_atm_iv": latest.get("atm_iv"),
            "latest_ivr": latest.get("ivr"),
            "status_counts": dict(status_counts),
            "coverage_rate": round(atm_iv_count / len(sym_rows), 3) if sym_rows else 0.0,
            "true_ivr_rate": round(true_ivr_count / len(sym_rows), 3) if sym_rows else 0.0,
        }
        symbol_reports.append(report)
        totals["readings"] += len(sym_rows)
        totals["atm_iv_readings"] += atm_iv_count
        totals["true_ivr_readings"] += true_ivr_count
        totals[report["status"]] += 1

    if totals["readings"] == 0:
        overall_status = "missing"
    elif totals["needs_attention"] > 0 or totals["missing"] > 0:
        overall_status = "needs_attention"
    elif totals["building"] > 0:
        overall_status = "building"
    else:
        overall_status = "good"

    return {
        "date": date.today().isoformat(),
        "timestamp": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "provider": "ivr_quality_report",
        "mode": "read_only",
        "execution_enabled": False,
        "ivr_log_path": str(ivr_log_path),
        "overall_status": overall_status,
        "min_history_days_for_true_ivr": MIN_HISTORY_DAYS,
        "summary": {
            "symbols": len(symbols),
            "total_readings": totals["readings"],
            "atm_iv_readings": totals["atm_iv_readings"],
            "true_ivr_readings": totals["true_ivr_readings"],
            "coverage_rate": round(totals["atm_iv_readings"] / totals["readings"], 3) if totals["readings"] else 0.0,
            "true_ivr_rate": round(totals["true_ivr_readings"] / totals["readings"], 3) if totals["readings"] else 0.0,
            "status_counts": {key: totals[key] for key in ("good", "building", "needs_attention", "missing")},
        },
        "symbols_detail": symbol_reports,
        "warnings": [
            "Read-only IVR data-quality report. No IVR gates are changed.",
            "Accumulating status is expected until roughly 30 market readings exist.",
        ],
    }


def write_report(report: dict[str, Any], path: Path = REPORT_PATH) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, indent=2, default=str) + "\n", encoding="utf-8")
    return path


def append_log(report: dict[str, Any], path: Path = LOG_PATH) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(report, separators=(",", ":"), default=str) + "\n")


def print_report(report: dict[str, Any]) -> None:
    print("\nIVR Quality Report | read-only")
    print("=" * 72)
    summary = report["summary"]
    print(
        f"status={report['overall_status']} readings={summary['total_readings']} "
        f"coverage={summary['coverage_rate']:.1%} true_ivr={summary['true_ivr_rate']:.1%}"
    )
    for row in report["symbols_detail"]:
        print(
            f"{row['symbol']:<4} {row['status']:<16} readings={row['readings']:<3} "
            f"history={row['latest_history_days']:<3} latest={row['latest_status']}"
        )
    print(f"JSON: {REPORT_PATH}\n")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ivr-log-path", type=Path, default=IVR_LOG_PATH)
    parser.add_argument("--log-path", type=Path, default=LOG_PATH)
    parser.add_argument("--report-path", type=Path, default=REPORT_PATH)
    parser.add_argument("--print", action="store_true", dest="print_output")
    args = parser.parse_args()

    report = build_report(ivr_log_path=args.ivr_log_path)
    append_log(report, args.log_path)
    write_report(report, args.report_path)
    if args.print_output:
        print_report(report)
    else:
        print(f"IVR quality report logged to {args.log_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Summarize intraday persistence from social_trending_symbols_log.jsonl."""
from __future__ import annotations

import argparse
import json
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
LOG_PATH = ROOT / "data" / "social_trending_symbols_log.jsonl"
REPORT_PATH = Path.home() / ".vibe-trading" / "reports" / "social-trending-persistence.json"


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
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


def _cutoff_date(days: int) -> str:
    return (datetime.now(timezone.utc).date() - timedelta(days=max(days - 1, 0))).isoformat()


def build_persistence_report(log_path: Path = LOG_PATH, *, days: int = 30, min_slots: int = 2) -> dict[str, Any]:
    cutoff = _cutoff_date(days)
    rows = [row for row in _read_jsonl(log_path) if str(row.get("date") or "") >= cutoff]

    grouped: dict[tuple[str, str], dict[str, Any]] = defaultdict(lambda: {
        "date": "",
        "symbol": "",
        "slots": set(),
        "first_rank": None,
        "best_rank": None,
        "last_rank": None,
        "max_trending_score": 0.0,
        "bucket": "",
        "action": "",
        "noise_flags": set(),
        "summaries": [],
    })

    for row in rows:
        date = str(row.get("date") or "")
        slot = int(row.get("intraday_scan_index") or 0)
        for symbol_row in row.get("symbols") or []:
            if not isinstance(symbol_row, dict):
                continue
            symbol = str(symbol_row.get("symbol") or "").upper()
            if not symbol:
                continue
            item = grouped[(date, symbol)]
            item["date"] = date
            item["symbol"] = symbol
            item["slots"].add(slot)
            rank = int(symbol_row.get("rank") or 999)
            item["first_rank"] = rank if item["first_rank"] is None else item["first_rank"]
            item["best_rank"] = rank if item["best_rank"] is None else min(item["best_rank"], rank)
            item["last_rank"] = rank
            item["max_trending_score"] = max(float(item["max_trending_score"]), float(symbol_row.get("trending_score") or 0.0))
            item["bucket"] = item["bucket"] or str(symbol_row.get("bucket") or "")
            item["action"] = item["action"] or str(symbol_row.get("action") or "")
            for flag in symbol_row.get("noise_flags") or []:
                item["noise_flags"].add(str(flag))
            summary = str(symbol_row.get("summary") or "")
            if summary and len(item["summaries"]) < 2:
                item["summaries"].append(summary)

    symbols = []
    for item in grouped.values():
        slots = sorted(item["slots"])
        symbols.append({
            "date": item["date"],
            "symbol": item["symbol"],
            "slot_count": len(slots),
            "slots": slots,
            "first_rank": item["first_rank"],
            "best_rank": item["best_rank"],
            "last_rank": item["last_rank"],
            "max_trending_score": round(float(item["max_trending_score"]), 4),
            "bucket": item["bucket"],
            "action": item["action"],
            "noise_flags": sorted(item["noise_flags"]),
            "summaries": item["summaries"],
        })

    persistent = [
        row for row in symbols
        if int(row["slot_count"]) >= min_slots
    ]
    persistent.sort(key=lambda row: (row["date"], row["slot_count"], -int(row["best_rank"] or 999)), reverse=True)
    symbols.sort(key=lambda row: (row["date"], row["slot_count"], -int(row["best_rank"] or 999)), reverse=True)

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "provider": "social_trending_persistence_report",
        "source_log": str(log_path),
        "mode": "context_only",
        "execution_enabled": False,
        "lookback_days": days,
        "min_slots": min_slots,
        "scan_rows": len(rows),
        "symbol_day_count": len(symbols),
        "persistent_count": len(persistent),
        "persistent_symbols": persistent[:100],
        "all_symbols": symbols[:200],
        "warnings": [
            "Persistence is context only. It does not imply trade edge without price/volume confirmation.",
            "More rows are needed before this becomes statistically useful.",
        ],
    }


def write_report(report: dict[str, Any], report_path: Path = REPORT_PATH) -> Path:
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    return report_path


def print_report(report: dict[str, Any]) -> None:
    print("\nSocial Trending Persistence | context only")
    print("=" * 68)
    print(
        f"rows={report['scan_rows']} symbol_days={report['symbol_day_count']} "
        f"persistent={report['persistent_count']} min_slots={report['min_slots']}"
    )
    for row in report["persistent_symbols"][:15]:
        flags = f" flags={'; '.join(row['noise_flags'])}" if row.get("noise_flags") else ""
        print(
            f"{row['date']} {row['symbol']:<6} slots={row['slot_count']} "
            f"best_rank={row['best_rank']} bucket={row['bucket']}{flags}"
        )
    print("No orders placed.\n")


def main() -> int:
    parser = argparse.ArgumentParser(description="Summarize social-trending intraday persistence.")
    parser.add_argument("--log-path", type=Path, default=LOG_PATH)
    parser.add_argument("--report-path", type=Path, default=REPORT_PATH)
    parser.add_argument("--days", type=int, default=30)
    parser.add_argument("--min-slots", type=int, default=2)
    parser.add_argument("--print", action="store_true", dest="print_output")
    args = parser.parse_args()

    report = build_persistence_report(args.log_path, days=args.days, min_slots=args.min_slots)
    write_report(report, args.report_path)
    if args.print_output:
        print_report(report)
    else:
        print(f"Social trending persistence report written to {args.report_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Read-only PMXT schema probe for prediction-market venue normalization."""
from __future__ import annotations

import argparse
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
TOOL_DIR = ROOT / "tools" / "pmxt-probe"
NODE_SCRIPT = TOOL_DIR / "pmxt_schema_probe.mjs"
LOG_PATH = ROOT / "data" / "pmxt_market_schema_probe_log.jsonl"
REPORT_PATH = Path.home() / ".vibe-trading" / "reports" / "pmxt-market-schema-probe.json"


def _json_loads(text: str) -> dict[str, Any]:
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as exc:
        return {"status": "error", "error": f"invalid_json_from_node: {exc}", "raw_stdout": text[:2000]}
    return payload if isinstance(payload, dict) else {"status": "error", "error": "node_output_not_object"}


def run_node_probe(query: str, venues: list[str], timeout_ms: int = 12000, max_markets: int = 8) -> dict[str, Any]:
    if not NODE_SCRIPT.exists():
        return {"status": "missing_script", "error": f"Missing {NODE_SCRIPT}"}
    if not (TOOL_DIR / "node_modules" / "pmxtjs").exists():
        return {
            "status": "missing_dependency",
            "error": "pmxtjs is not installed in tools/pmxt-probe",
            "install_command": "cd tools\\pmxt-probe && npm install",
        }
    cmd = [
        "node",
        str(NODE_SCRIPT),
        "--query",
        query,
        "--venues",
        ",".join(venues),
        "--timeout-ms",
        str(timeout_ms),
        "--max-markets",
        str(max_markets),
    ]
    proc = subprocess.run(
        cmd,
        cwd=str(TOOL_DIR),
        check=False,
        capture_output=True,
        text=True,
        timeout=max(10, int(timeout_ms / 1000) * max(1, len(venues)) + 10),
    )
    if proc.returncode != 0:
        return {
            "status": "error",
            "error": "node_probe_failed",
            "returncode": proc.returncode,
            "stderr": proc.stderr[-2000:],
            "stdout": proc.stdout[-2000:],
        }
    payload = _json_loads(proc.stdout)
    payload["status"] = payload.get("status") or "ok"
    if proc.stderr.strip():
        payload["stderr"] = proc.stderr[-2000:]
    return payload


def _schema_score(result: dict[str, Any]) -> float:
    if result.get("status") != "ok":
        return 0.0
    markets = result.get("markets") if isinstance(result.get("markets"), list) else []
    if not markets:
        return 0.0
    useful_fields = ("id", "title", "ticker", "slug", "volume", "liquidity", "best_bid", "best_ask", "yes_price", "end_date")
    filled = 0
    total = len(markets) * len(useful_fields)
    for market in markets:
        if not isinstance(market, dict):
            continue
        filled += sum(1 for field in useful_fields if market.get(field) not in (None, ""))
    return round(filled / total * 10.0, 2) if total else 0.0


def build_report(raw: dict[str, Any], query: str, venues: list[str]) -> dict[str, Any]:
    results = raw.get("results") if isinstance(raw.get("results"), list) else []
    venue_rows = []
    for result in results:
        if not isinstance(result, dict):
            continue
        venue_rows.append({
            "venue": result.get("venue"),
            "status": result.get("status"),
            "market_count": result.get("market_count", 0),
            "sample_count": len(result.get("markets") or []),
            "schema_score": _schema_score(result),
            "error": result.get("error"),
            "sample_markets": result.get("markets", [])[:3],
        })
    ok_count = sum(1 for row in venue_rows if row["status"] == "ok" and row["sample_count"] > 0)
    avg_schema = round(sum(row["schema_score"] for row in venue_rows) / len(venue_rows), 2) if venue_rows else 0.0
    if raw.get("status") == "missing_dependency":
        recommendation = "install_pmxt_sandbox"
    elif ok_count >= 2 and avg_schema >= 4:
        recommendation = "candidate_for_read_only_integration"
    elif ok_count >= 1:
        recommendation = "partial_candidate_review_manually"
    else:
        recommendation = "not_ready"
    return {
        "date": datetime.now(timezone.utc).date().isoformat(),
        "timestamp": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "provider": "pmxt_market_schema_probe",
        "mode": "read_only",
        "execution_enabled": False,
        "query": query,
        "venues": venues,
        "status": raw.get("status", "unknown"),
        "recommendation": recommendation,
        "ok_venue_count": ok_count,
        "avg_schema_score": avg_schema,
        "venues_report": venue_rows,
        "raw_error": raw.get("error"),
        "install_command": raw.get("install_command"),
        "warnings": [
            "PMXT probe is read-only and sandboxed under tools/pmxt-probe.",
            "Do not enable PMXT hosted trading or credentials from this probe.",
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
    print("\nPMXT Market Schema Probe | read-only")
    print("=" * 72)
    print(
        f"query={report['query']} status={report['status']} "
        f"recommendation={report['recommendation']} ok={report['ok_venue_count']} "
        f"schema={report['avg_schema_score']}"
    )
    if report.get("install_command"):
        print(f"install: {report['install_command']}")
    for row in report["venues_report"]:
        print(
            f"{str(row['venue']):<12} status={str(row['status']):<7} "
            f"markets={row['market_count']:<5} samples={row['sample_count']:<3} "
            f"schema={row['schema_score']:<4} error={row.get('error') or '-'}"
        )
    print(f"JSON: {REPORT_PATH}\n")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--query", default="Fed", help="Market search query.")
    parser.add_argument("--venues", default="polymarket,kalshi,limitless", help="Comma-separated PMXT venues.")
    parser.add_argument("--timeout-ms", type=int, default=12000)
    parser.add_argument("--max-markets", type=int, default=8)
    parser.add_argument("--log-path", type=Path, default=LOG_PATH)
    parser.add_argument("--report-path", type=Path, default=REPORT_PATH)
    parser.add_argument("--print", action="store_true", dest="print_output")
    args = parser.parse_args()
    venues = [venue.strip().lower() for venue in args.venues.split(",") if venue.strip()]
    raw = run_node_probe(args.query, venues, timeout_ms=args.timeout_ms, max_markets=args.max_markets)
    report = build_report(raw, args.query, venues)
    append_log(report, args.log_path)
    write_report(report, args.report_path)
    if args.print_output:
        print_report(report)
    else:
        print(f"PMXT schema probe logged to {args.log_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Read-only slow-news prediction market watch.

Finds public Limitless markets whose titles look tied to macro, CPI/FOMC/jobs,
earnings, or other event-resolution windows. The thesis: avoid speed wars and
observe slower event markets where mispricing may persist long enough to study.
No keys, no wallets, no orders.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.limitless_market_scanner import fetch_active_markets, normalize_market

LOG_PATH = ROOT / "data" / "prediction_market_slow_news_log.jsonl"
REPORT_PATH = Path.home() / ".vibe-trading" / "reports" / "prediction-market-slow-news.json"

THEMES = {
    "inflation_cpi": re.compile(r"\b(cpi|inflation|pce|prices?)\b", re.I),
    "fed_rates": re.compile(r"\b(fed|fomc|rate cut|rate hike|interest rate|powell)\b", re.I),
    "jobs_macro": re.compile(r"\b(jobs?|payroll|unemployment|nfp|claims)\b", re.I),
    "earnings": re.compile(r"\b(earnings|eps|revenue|guidance)\b", re.I),
    "politics_policy": re.compile(r"\b(election|bill|tariff|court|senate|congress|white house)\b", re.I),
    "sports_event": re.compile(r"\b(win|championship|final|game|match|score)\b", re.I),
}


def classify_title(title: str) -> list[str]:
    return [theme for theme, pattern in THEMES.items() if pattern.search(title)]


def event_score(market: dict[str, Any]) -> int:
    title = str(market.get("title") or "")
    themes = classify_title(title)
    score = 0
    score += 3 if any(theme in themes for theme in ("inflation_cpi", "fed_rates", "jobs_macro", "earnings")) else 0
    score += 1 if market.get("volume", 0.0) and float(market["volume"]) >= 1000 else 0
    yes_spread = market.get("yes_spread")
    no_spread = market.get("no_spread")
    spreads = [float(s) for s in (yes_spread, no_spread) if s is not None]
    if spreads and max(spreads) <= 0.10:
        score += 1
    if market.get("is_poly_arbitrage"):
        score += 1
    return score


def build_report(top: int = 50) -> dict[str, Any]:
    try:
        rows = [normalize_market(row) for row in fetch_active_markets(pages=max(1, (top + 24) // 25), page_limit=25)]
        status = "ok"
        error = None
    except Exception as exc:
        rows = []
        status = "error"
        error = str(exc)[:180]
    candidates = []
    for market in rows[:top]:
        title = str(market.get("title") or "")
        themes = classify_title(title)
        score = event_score(market)
        if themes or score >= 2:
            candidates.append({
                "slug": market.get("slug"),
                "title": title,
                "url": market.get("url"),
                "themes": themes,
                "volume": market.get("volume"),
                "yes_price": market.get("yes_price"),
                "no_price": market.get("no_price"),
                "yes_spread": market.get("yes_spread"),
                "no_spread": market.get("no_spread"),
                "is_poly_arbitrage": market.get("is_poly_arbitrage"),
                "slow_news_score": score,
                "watch_reason": "macro_or_earnings_resolution_window" if score >= 3 else "context_only",
            })
    candidates.sort(key=lambda row: (row["slow_news_score"], float(row.get("volume") or 0.0)), reverse=True)
    return {
        "date": datetime.now(timezone.utc).date().isoformat(),
        "timestamp": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "provider": "prediction_market_slow_news_watch",
        "mode": "read_only",
        "execution_enabled": False,
        "can_submit_orders": False,
        "status": status,
        "error": error,
        "markets_scanned": len(rows[:top]),
        "candidate_count": len(candidates),
        "top_candidates": candidates[:15],
        "warnings": [
            "Read-only scanner. No keys, wallets, signatures, or orders.",
            "Slow-news candidates require observed post-resolution mispricing before any trading discussion.",
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
    print("\nPrediction Market Slow-News Watch | read-only")
    print("=" * 72)
    print(f"status={report['status']} scanned={report['markets_scanned']} candidates={report['candidate_count']}")
    for row in report["top_candidates"][:5]:
        print(f"score={row['slow_news_score']} themes={','.join(row['themes']) or '-'} | {row['title']}")
    print("No orders placed.\n")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--top", type=int, default=50)
    parser.add_argument("--log-path", type=Path, default=LOG_PATH)
    parser.add_argument("--report-path", type=Path, default=REPORT_PATH)
    parser.add_argument("--print", action="store_true", dest="print_output")
    args = parser.parse_args()
    report = build_report(top=args.top)
    append_log(report, args.log_path)
    write_report(report, args.report_path)
    if args.print_output:
        print_report(report)
    else:
        print(f"Prediction-market slow-news watch logged to {args.log_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

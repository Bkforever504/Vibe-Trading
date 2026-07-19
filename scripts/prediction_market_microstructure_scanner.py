"""Read-only prediction-market microstructure scanner.

Looks for account-flip style claims we can actually test: short-horizon Up/Down
markets with large two-sided flow, tight spreads, and directional imbalance.
No API keys, no wallet connection, no orders.
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.limitless_market_scanner import scan_limitless

LOG_PATH = ROOT / "data" / "prediction_market_microstructure_log.jsonl"
REPORT_PATH = Path.home() / ".vibe-trading" / "reports" / "prediction-market-microstructure.json"


def classify_market(market: dict[str, Any]) -> str:
    title = str(market.get("title") or "").lower()
    slug = str(market.get("slug") or "").lower()
    text = f"{title} {slug}"
    if "up or down" in text or "15 min" in text or "hourly" in text:
        return "short_horizon_up_down"
    if "fed" in text or "rate" in text or "fomc" in text:
        return "macro_event"
    return "other"


def summarize_events(events: list[dict[str, Any]]) -> dict[str, Any]:
    by_market: dict[str, dict[str, Any]] = defaultdict(lambda: {"yes_usd": 0.0, "no_usd": 0.0, "trades": 0, "wallets": set()})
    for event in events:
        slug = str(event.get("market_slug") or "unknown")
        outcome = str(event.get("outcome") or event.get("side") or "").upper()
        usd = float(event.get("usd") or 0.0)
        row = by_market[slug]
        row["trades"] += 1
        if event.get("wallet"):
            row["wallets"].add(event["wallet"])
        if "YES" in outcome or outcome in {"UP", "LONG"}:
            row["yes_usd"] += usd
        elif "NO" in outcome or outcome in {"DOWN", "SHORT"}:
            row["no_usd"] += usd
    out = {}
    for slug, row in by_market.items():
        total = row["yes_usd"] + row["no_usd"]
        imbalance = (row["yes_usd"] - row["no_usd"]) / total if total else 0.0
        out[slug] = {
            "yes_usd": round(row["yes_usd"], 2),
            "no_usd": round(row["no_usd"], 2),
            "total_usd": round(total, 2),
            "imbalance": round(imbalance, 3),
            "trades": row["trades"],
            "unique_wallets": len(row["wallets"]),
        }
    return out


def build_microstructure_report(top: int = 10, min_usd: float = 100.0) -> dict[str, Any]:
    base = scan_limitless(top=top, min_usd=min_usd)
    events_by_market = summarize_events(base.get("whale_events", []))
    candidates = []
    for market in base.get("top_markets", []):
        slug = market.get("slug")
        event_stats = events_by_market.get(slug, {})
        yes_spread = market.get("yes_spread")
        no_spread = market.get("no_spread")
        max_spread = max([s for s in [yes_spread, no_spread] if s is not None], default=None)
        market_type = classify_market(market)
        tight = max_spread is not None and max_spread <= 0.08
        flow = float(event_stats.get("total_usd", 0.0) or 0.0)
        imbalance = abs(float(event_stats.get("imbalance", 0.0) or 0.0))
        score = 0
        score += 3 if market_type == "short_horizon_up_down" else 0
        score += 2 if tight else 0
        score += 2 if flow >= 500 else 1 if flow >= min_usd else 0
        score += 1 if imbalance >= 0.35 else 0
        candidates.append({
            "slug": slug,
            "title": market.get("title"),
            "url": market.get("url"),
            "market_type": market_type,
            "volume": market.get("volume"),
            "yes_price": market.get("yes_price"),
            "no_price": market.get("no_price"),
            "max_spread": max_spread,
            "tight_spread": tight,
            "flow": event_stats,
            "microstructure_score": score,
            "directional_hint": "yes_flow" if float(event_stats.get("imbalance", 0.0) or 0.0) > 0.35 else "no_flow" if float(event_stats.get("imbalance", 0.0) or 0.0) < -0.35 else "balanced",
        })
    candidates.sort(key=lambda row: (row["microstructure_score"], float(row.get("volume") or 0.0)), reverse=True)
    return {
        "date": datetime.now(timezone.utc).date().isoformat(),
        "timestamp": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "provider": "prediction_market_microstructure_scanner",
        "source": "limitless_public_api",
        "mode": "read_only",
        "execution_enabled": False,
        "markets_scanned": base.get("markets_scanned", 0),
        "candidate_count": len([c for c in candidates if c["microstructure_score"] >= 5]),
        "top_candidates": candidates[:10],
        "warnings": [
            "Read-only scanner. No keys, wallet signatures, approvals, or orders are used.",
            "Short-horizon prediction markets can be noisy and illiquid; require 30 days of observations before action.",
        ],
    }


def append_log(report: dict[str, Any], log_path: Path = LOG_PATH) -> None:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(report, separators=(",", ":")) + "\n")


def write_report(report: dict[str, Any], report_path: Path = REPORT_PATH) -> Path:
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    return report_path


def print_report(report: dict[str, Any]) -> None:
    print("\nPrediction Market Microstructure | read-only")
    print("=" * 72)
    print(f"markets={report['markets_scanned']} candidates={report['candidate_count']} execution_enabled={report['execution_enabled']}")
    for row in report["top_candidates"][:5]:
        flow = row.get("flow") or {}
        print(f"score={row['microstructure_score']} {row['title']} flow=${flow.get('total_usd', 0)} hint={row['directional_hint']}")
    print("No orders placed.\n")


def main() -> int:
    parser = argparse.ArgumentParser(description="Read-only prediction market microstructure scanner.")
    parser.add_argument("--top", type=int, default=10)
    parser.add_argument("--min-usd", type=float, default=100.0)
    parser.add_argument("--log-path", type=Path, default=LOG_PATH)
    parser.add_argument("--report-path", type=Path, default=REPORT_PATH)
    parser.add_argument("--print", action="store_true", dest="print_output")
    args = parser.parse_args()
    report = build_microstructure_report(top=args.top, min_usd=args.min_usd)
    append_log(report, args.log_path)
    write_report(report, args.report_path)
    if args.print_output:
        print_report(report)
    else:
        print(f"Prediction-market microstructure logged to {args.log_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

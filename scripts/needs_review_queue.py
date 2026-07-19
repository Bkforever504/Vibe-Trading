#!/usr/bin/env python3
"""Build a focused queue of guard-blocked trades that deserve manual review.

This is deliberately read-only. It turns rejected_trade_intelligence output into
a short action list so strict guards can be studied without loosening them.
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts import rejected_trade_intelligence as rejected

VIBE_HOME = Path.home() / ".vibe-trading"
LOG_PATH = ROOT / "data" / "needs_review_queue_log.jsonl"
REPORT_PATH = VIBE_HOME / "reports" / "needs-review-queue.json"

REVIEW_VERDICTS = {"possibly_too_strict", "needs_review"}
KALSHI_REVIEW_REASONS = {"contracts_above_limit", "notional_above_limit"}


def _priority_for(review: dict[str, Any]) -> str:
    verdict = str(review.get("verdict") or "")
    reason = str(review.get("reason") or "")
    guard_source = str(review.get("guard_source") or "")
    score = float(review.get("review_score") or 0.0)
    if guard_source == "kalshi" and reason in {"contracts_above_limit", "notional_above_limit"}:
        return "medium"
    if verdict == "possibly_too_strict":
        return "high"
    if reason in {"confidence_below_minimum", "notional_above_limit"} and score <= 5.5:
        return "medium"
    return "low"


def _next_action(review: dict[str, Any]) -> str:
    verdict = str(review.get("verdict") or "")
    reason = str(review.get("reason") or "")
    guard_source = str(review.get("guard_source") or "")
    symbol = str(review.get("symbol") or "symbol")
    if guard_source == "kalshi":
        market = str(review.get("market_ticker") or symbol or "market")
        if reason in {"dry_run_active", "live_execution_not_enabled"}:
            return f"Expected Kalshi safety lock for {market}; no action unless explicitly promoting from dry-run."
        if reason == "contracts_above_limit":
            return f"Review {market} sizing model; keep contract cap unchanged until 30-day Kalshi edge evidence exists."
        if reason == "notional_above_limit":
            return f"Review {market} price/contracts math; prefer smaller notional, not a higher Kalshi cap."
        if reason == "daily_loss_limit":
            return "Leave Kalshi daily-loss lock intact; review only after full day outcome report."
    if verdict == "possibly_too_strict":
        return f"Inspect {symbol} chart/outcome after the block; do not loosen guard unless 30-day evidence supports it."
    if reason == "confidence_below_minimum":
        return "Check whether the signal was near threshold and whether market-force context agreed."
    if reason == "notional_above_limit":
        return "Check whether a smaller defined-risk structure would have fit without raising risk."
    return "Review context, then close as protective or keep open for more samples."


def _queue_item(review: dict[str, Any]) -> dict[str, Any]:
    return {
        "date": review.get("date"),
        "priority": _priority_for(review),
        "bot": review.get("bot"),
        "symbol": review.get("symbol"),
        "action": review.get("action"),
        "reason": review.get("reason"),
        "verdict": review.get("verdict"),
        "guard_source": review.get("guard_source"),
        "market_ticker": review.get("market_ticker"),
        "side": review.get("side"),
        "price_cents": review.get("price_cents"),
        "contracts": review.get("contracts"),
        "edge": review.get("edge"),
        "spread_cents": review.get("spread_cents"),
        "review_score": review.get("review_score"),
        "confidence": review.get("confidence"),
        "min_confidence": review.get("min_confidence"),
        "estimated_notional": review.get("estimated_notional"),
        "max_notional": review.get("max_notional"),
        "market_force": review.get("market_force"),
        "daily_realized_pnl": review.get("daily_realized_pnl"),
        "notes": review.get("notes") if isinstance(review.get("notes"), list) else [],
        "next_action": _next_action(review),
    }


def build_queue(
    *,
    lookback_days: int = 30,
    max_items: int = 25,
    guard_paths: list[Path] | None = None,
    outcome_path: Path = rejected.OUTCOME_PATH,
    market_force_path: Path = rejected.MARKET_FORCE_PATH,
) -> dict[str, Any]:
    intelligence = rejected.build_report(
        guard_paths=guard_paths,
        outcome_path=outcome_path,
        market_force_path=market_force_path,
        lookback_days=lookback_days,
    )
    candidates = []
    for row in intelligence.get("recent_reviews", []):
        is_review_verdict = row.get("verdict") in REVIEW_VERDICTS
        is_kalshi_sizing_review = (
            row.get("guard_source") == "kalshi"
            and row.get("reason") in KALSHI_REVIEW_REASONS
        )
        if is_review_verdict or is_kalshi_sizing_review:
            candidates.append(_queue_item(row))
    priority_order = {"high": 0, "medium": 1, "low": 2}
    candidates.sort(
        key=lambda row: (
            priority_order.get(str(row.get("priority")), 9),
            str(row.get("date") or ""),
            str(row.get("symbol") or ""),
        )
    )
    queue = candidates[:max_items]
    return {
        "date": date.today().isoformat(),
        "timestamp": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "provider": "needs_review_queue",
        "mode": "read_only",
        "execution_enabled": False,
        "lookback_days": lookback_days,
        "source_block_count": intelligence.get("block_count", 0),
        "queue_count": len(queue),
        "by_priority": dict(Counter(str(row.get("priority")) for row in queue)),
        "by_reason": dict(Counter(str(row.get("reason")) for row in queue)),
        "items": queue,
        "warnings": [
            "This queue is for manual review only.",
            "A queued item is not permission to loosen execution guards.",
            "Promotions still require the signal promotion rules in rules/signal_promotion_rules.md.",
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
    print("\nNeeds Review Queue | read-only")
    print("=" * 72)
    print(
        f"queue={report['queue_count']} source_blocks={report['source_block_count']} "
        f"priorities={report['by_priority']}"
    )
    for item in report["items"][:12]:
        print(
            f"{item.get('priority', '-'):<6} {item.get('date', '-'):<10} "
            f"{item.get('bot', '-'):<10} {item.get('symbol', '-'):<6} "
            f"{item.get('reason', '-'):<24} {item.get('verdict', '-')}"
        )
    for warning in report["warnings"]:
        print(f"- {warning}")
    print(f"JSON: {REPORT_PATH}\n")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--lookback-days", type=int, default=30)
    parser.add_argument("--max-items", type=int, default=25)
    parser.add_argument("--log-path", type=Path, default=LOG_PATH)
    parser.add_argument("--report-path", type=Path, default=REPORT_PATH)
    parser.add_argument("--print", action="store_true", dest="print_output")
    args = parser.parse_args()
    report = build_queue(lookback_days=args.lookback_days, max_items=args.max_items)
    append_log(report, args.log_path)
    write_report(report, args.report_path)
    if args.print_output:
        print_report(report)
    else:
        print(f"Needs review queue logged to {args.log_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

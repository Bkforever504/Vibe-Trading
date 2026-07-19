#!/usr/bin/env python3
"""Read-only intelligence report for guard-blocked trades.

The goal is not to loosen guards. It is to learn whether rejected trades were
probably protective, overly strict, or simply unreviewable with current data.
"""
from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
VIBE_HOME = Path.home() / ".vibe-trading"
LOG_PATH = ROOT / "data" / "rejected_trade_intelligence_log.jsonl"
REPORT_PATH = VIBE_HOME / "reports" / "rejected-trade-intelligence.json"
GUARD_PATHS = [VIBE_HOME / "guard-blocks.jsonl", VIBE_HOME / "kalshi-guard-blocks.jsonl"]
OUTCOME_PATH = ROOT / "data" / "daily_outcome_review_log.jsonl"
MARKET_FORCE_PATH = ROOT / "data" / "market_force_score_log.jsonl"


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


def _safe_float(value: Any, default: float | None = None) -> float | None:
    try:
        if value in (None, ""):
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def _event_date(row: dict[str, Any]) -> str:
    details = row.get("details") if isinstance(row.get("details"), dict) else {}
    for source in (row, details):
        for key in ("date", "checked_at", "timestamp", "created_at", "ts"):
            value = source.get(key)
            if value:
                return str(value)[:10]
    return ""


def _latest_by_day(path: Path) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for row in _read_jsonl(path):
        day = _event_date(row)
        if day:
            out[day] = row
    return out


def _load_blocks(paths: list[Path]) -> list[dict[str, Any]]:
    blocks: list[dict[str, Any]] = []
    for path in paths:
        source = "kalshi" if "kalshi" in path.name else "alpaca"
        for row in _read_jsonl(path):
            details = row.get("details") if isinstance(row.get("details"), dict) else {}
            merged = {**details, **{k: v for k, v in row.items() if k != "details"}}
            merged["source_file"] = str(path)
            merged["guard_source"] = source
            merged["date"] = _event_date(row)
            blocks.append(merged)
    return [block for block in blocks if block.get("date")]


def classify_block(block: dict[str, Any], outcome: dict[str, Any] | None, market_force: dict[str, Any] | None) -> dict[str, Any]:
    reason = str(block.get("reason") or "")
    confidence = _safe_float(block.get("confidence"))
    min_conf = _safe_float(block.get("min_confidence"), 8.5) or 8.5
    notional = _safe_float(block.get("estimated_notional") or block.get("estimated_notional_dollars"), 0.0) or 0.0
    max_notional = _safe_float(block.get("max_notional") or block.get("max_notional_dollars"), 0.0) or 0.0
    daily_pnl = _safe_float(((outcome or {}).get("event_summary") or {}).get("realized_pnl"), 0.0) or 0.0
    mf_class = str((market_force or {}).get("classification") or "")
    verdict = "needs_review"
    score = 5.0
    notes: list[str] = []

    if reason in {"duplicate_symbol_exposure", "portfolio_kill_switch", "manual_reset_required", "daily_loss_limit"}:
        verdict = "likely_good_rejection"
        score += 2.0
        notes.append(f"{reason} protects capital or prevents crowding")
    elif reason in {"dry_run_active", "live_execution_not_enabled"}:
        verdict = "safety_lock"
        score += 2.0
        notes.append(f"{reason} correctly prevented live prediction-market execution")
    elif reason == "contracts_above_limit":
        verdict = "likely_good_rejection"
        score += 1.5
        notes.append("contract count exceeded configured prediction-market cap")
    elif reason == "spread_too_wide":
        verdict = "likely_good_rejection"
        score += 1.5
        notes.append("wide spread would likely hurt fill quality")
    elif reason == "notional_above_limit":
        verdict = "likely_good_rejection"
        score += 1.0
        notes.append("notional exceeded configured budget")
    elif reason == "confidence_below_minimum":
        gap = min_conf - (confidence or 0.0)
        if gap <= 0.5 and daily_pnl > 0 and "bullish" in mf_class:
            verdict = "possibly_too_strict"
            score -= 1.5
            notes.append("near-threshold confidence was blocked on profitable/bullish day")
        else:
            verdict = "reasonable_rejection"
            score += 0.5
            notes.append("confidence did not meet hard minimum")
    elif reason in {"edge_below_threshold", "market_edge_below_threshold"}:
        verdict = "reasonable_rejection"
        score += 0.5
        notes.append("market edge did not meet the configured prediction-market threshold")

    if max_notional and notional > max_notional:
        notes.append(f"notional {notional:.2f} > max {max_notional:.2f}")
    if daily_pnl < 0 and verdict == "possibly_too_strict":
        verdict = "needs_review"
        notes.append("same-day P&L was negative, so strictness may have helped")

    return {
        "date": block.get("date"),
        "bot": block.get("bot") or block.get("guard_source"),
        "symbol": block.get("symbol") or block.get("market_ticker") or "",
        "action": block.get("action") or "",
        "guard_source": block.get("guard_source"),
        "market_ticker": block.get("market_ticker"),
        "side": block.get("side"),
        "price_cents": _safe_float(block.get("price_cents")),
        "contracts": _safe_float(block.get("contracts")),
        "edge": _safe_float(block.get("edge")),
        "spread_cents": _safe_float(block.get("spread_cents")),
        "reason": reason,
        "confidence": confidence,
        "min_confidence": min_conf,
        "estimated_notional": notional,
        "max_notional": max_notional,
        "market_force": mf_class,
        "daily_realized_pnl": daily_pnl,
        "verdict": verdict,
        "review_score": round(max(0.0, min(10.0, score)), 2),
        "notes": notes,
    }


def build_report(
    *,
    guard_paths: list[Path] | None = None,
    outcome_path: Path = OUTCOME_PATH,
    market_force_path: Path = MARKET_FORCE_PATH,
    lookback_days: int = 30,
) -> dict[str, Any]:
    guard_paths = guard_paths or GUARD_PATHS
    outcomes = _latest_by_day(outcome_path)
    market_forces = _latest_by_day(market_force_path)
    blocks = _load_blocks(guard_paths)
    if lookback_days > 0:
        days = sorted({block["date"] for block in blocks})[-lookback_days:]
        blocks = [block for block in blocks if block["date"] in set(days)]
    reviews = [classify_block(block, outcomes.get(block["date"]), market_forces.get(block["date"])) for block in blocks]
    by_reason = Counter(row["reason"] for row in reviews)
    by_verdict = Counter(row["verdict"] for row in reviews)
    reason_rows = []
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in reviews:
        grouped[row["reason"]].append(row)
    for reason, rows in grouped.items():
        reason_rows.append({
            "reason": reason,
            "count": len(rows),
            "avg_review_score": round(sum(float(row["review_score"]) for row in rows) / len(rows), 2),
            "verdicts": dict(Counter(row["verdict"] for row in rows)),
            "sample_symbols": sorted({row["symbol"] for row in rows if row["symbol"]})[:8],
        })
    reason_rows.sort(key=lambda row: row["count"], reverse=True)
    return {
        "date": date.today().isoformat(),
        "timestamp": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "provider": "rejected_trade_intelligence",
        "mode": "read_only",
        "execution_enabled": False,
        "lookback_days": lookback_days,
        "block_count": len(reviews),
        "by_reason": dict(by_reason),
        "by_verdict": dict(by_verdict),
        "reason_quality": reason_rows,
        "recent_reviews": reviews[-50:],
        "warnings": [
            "Read-only rejected-trade review. No guard settings are changed.",
            "A possibly_too_strict label is a research prompt, not permission to loosen gates.",
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
    print("\nRejected Trade Intelligence | read-only")
    print("=" * 72)
    print(f"blocks={report['block_count']} verdicts={report['by_verdict']}")
    for row in report["reason_quality"][:8]:
        print(
            f"{row['reason']:<28} count={row['count']:<3} "
            f"score={row['avg_review_score']:<4} verdicts={row['verdicts']}"
        )
    for warning in report["warnings"]:
        print(f"- {warning}")
    print(f"JSON: {REPORT_PATH}\n")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--lookback-days", type=int, default=30)
    parser.add_argument("--log-path", type=Path, default=LOG_PATH)
    parser.add_argument("--report-path", type=Path, default=REPORT_PATH)
    parser.add_argument("--print", action="store_true", dest="print_output")
    args = parser.parse_args()
    report = build_report(lookback_days=args.lookback_days)
    append_log(report, args.log_path)
    write_report(report, args.report_path)
    if args.print_output:
        print_report(report)
    else:
        print(f"Rejected trade intelligence logged to {args.log_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

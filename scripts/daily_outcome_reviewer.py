"""Review whether the daily posture matched actual bot outcomes.

This closes the loop on the new intelligence stack:
- Exposure Coach says how aggressive/cautious the day should be.
- Market Force explains the tape.
- Actual bot/guard/shadow events show what happened.

Read-only. No bot settings are changed.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.export_daily_bot_activity_csv import collect_events

VIBE_HOME = Path.home() / ".vibe-trading"
LOG_PATH = ROOT / "data" / "daily_outcome_review_log.jsonl"
REPORT_PATH = VIBE_HOME / "reports" / "daily-outcome-review.json"

SOURCE_PATHS = {
    "exposure": ROOT / "data" / "exposure_coach_log.jsonl",
    "market_force": ROOT / "data" / "market_force_score_log.jsonl",
    "breadth": ROOT / "data" / "market_breadth_uptrend_log.jsonl",
    "distribution": ROOT / "data" / "distribution_day_log.jsonl",
}


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


def latest_for_day(path: Path, day: str) -> dict[str, Any] | None:
    rows = [row for row in _read_jsonl(path) if str(row.get("date", ""))[:10] == day]
    return rows[-1] if rows else None


def _safe_float(value: Any) -> float | None:
    try:
        if value in (None, ""):
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def summarize_events(events: list[dict[str, Any]]) -> dict[str, Any]:
    trades = [event for event in events if event.get("event_type") == "trade"]
    guard_blocks = [event for event in events if event.get("event_type") == "guard_block"]
    shadow_signals = [event for event in events if event.get("event_type") == "shadow_signal"]
    context_events = [
        event for event in events
        if str(event.get("event_type", "")).endswith("_context") or event.get("event_type") in {"exposure_review", "trade_review"}
    ]
    pnls = [_safe_float(event.get("pnl")) for event in trades]
    pnls = [pnl for pnl in pnls if pnl is not None]
    entry_like = [
        event for event in shadow_signals
        if any(token in str(event.get("action", "")).lower() for token in ("enter", "hold", "selected", "long", "short"))
        and "flat" not in str(event.get("action", "")).lower()
    ]
    return {
        "trade_count": len(trades),
        "guard_block_count": len(guard_blocks),
        "shadow_signal_count": len(shadow_signals),
        "entry_like_shadow_count": len(entry_like),
        "context_event_count": len(context_events),
        "realized_pnl": round(sum(pnls), 2) if pnls else 0.0,
        "winning_trade_count": sum(1 for pnl in pnls if pnl > 0),
        "losing_trade_count": sum(1 for pnl in pnls if pnl < 0),
        "trade_sources": sorted({str(event.get("source")) for event in trades if event.get("source")}),
        "blocked_reasons": sorted({str(event.get("reason")) for event in guard_blocks if event.get("reason")}),
    }


def evaluate_posture(posture: str, score: float, event_summary: dict[str, Any], market_force: dict[str, Any] | None) -> dict[str, Any]:
    pnl = float(event_summary.get("realized_pnl") or 0.0)
    blocks = int(event_summary.get("guard_block_count") or 0)
    trades = int(event_summary.get("trade_count") or 0)
    mf_class = str((market_force or {}).get("classification") or "missing")
    verdict = "needs_more_data"
    review_score = 5.0
    reasons: list[str] = []

    if posture in {"cautious", "cash_priority"}:
        review_score += 1.0
        reasons.append(f"posture was defensive ({posture})")
        if pnl < 0 or blocks > 0 or "bearish" in mf_class or mf_class == "mixed":
            review_score += 1.5
            verdict = "posture_helpful"
            reasons.append("defensive posture matched risk evidence or blocked activity")
        elif pnl > 250 and trades > 0:
            review_score -= 1.0
            verdict = "possibly_too_cautious"
            reasons.append("bot produced profit despite defensive posture")
    elif posture in {"normal", "aggressive"}:
        reasons.append(f"posture allowed risk ({posture})")
        if pnl > 0:
            review_score += 2.0
            verdict = "posture_helpful"
            reasons.append("risk-on posture matched positive realized P&L")
        elif pnl < 0:
            review_score -= 2.0
            verdict = "possibly_too_loose"
            reasons.append("risk-on posture conflicted with realized loss")
        elif blocks > 0:
            review_score -= 0.75
            verdict = "guard_disagreed"
            reasons.append("execution guard blocked trades despite risk-on posture")

    if trades == 0 and blocks == 0:
        verdict = "no_execution_sample"
        reasons.append("no executed or blocked trade sample")
    if event_summary.get("entry_like_shadow_count", 0) and trades == 0:
        reasons.append("shadow entries appeared without execution sample")

    return {
        "verdict": verdict,
        "review_score": round(max(0.0, min(10.0, review_score)), 2),
        "reasons": reasons,
    }


def build_report(day: str | None = None, paths: dict[str, Path] | None = None) -> dict[str, Any]:
    day = day or date.today().isoformat()
    paths = paths or SOURCE_PATHS
    exposure = latest_for_day(paths["exposure"], day)
    market_force = latest_for_day(paths["market_force"], day)
    breadth = latest_for_day(paths["breadth"], day)
    distribution = latest_for_day(paths["distribution"], day)
    events = collect_events(day)
    event_summary = summarize_events(events)
    posture = str((exposure or {}).get("posture") or "missing")
    posture_score = float((exposure or {}).get("score") or 0.0)
    evaluation = evaluate_posture(posture, posture_score, event_summary, market_force)
    return {
        "date": day,
        "timestamp": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "provider": "daily_outcome_reviewer",
        "mode": "read_only",
        "execution_enabled": False,
        "posture": posture,
        "posture_score": posture_score,
        "market_force_classification": (market_force or {}).get("classification"),
        "market_force_score": (market_force or {}).get("total_score"),
        "breadth_status": ((breadth or {}).get("breadth") or {}).get("uptrend_status") if isinstance((breadth or {}).get("breadth"), dict) else None,
        "distribution_regime": ((distribution or {}).get("aggregate") or {}).get("regime") if isinstance((distribution or {}).get("aggregate"), dict) else None,
        "event_summary": event_summary,
        **evaluation,
        "warnings": [
            "Read-only review. No bot settings are changed.",
            "Use at least 30 trading days before turning posture into an execution gate.",
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
    summary = report["event_summary"]
    print("\nDaily Outcome Reviewer | read-only")
    print("=" * 72)
    print(
        f"date={report['date']} posture={report['posture']} verdict={report['verdict']} "
        f"score={report['review_score']}"
    )
    print(
        f"trades={summary['trade_count']} pnl={summary['realized_pnl']} "
        f"blocks={summary['guard_block_count']} shadow_entries={summary['entry_like_shadow_count']}"
    )
    for reason in report["reasons"]:
        print(f"- {reason}")
    print("No settings changed. No orders placed.\n")


def main() -> int:
    parser = argparse.ArgumentParser(description="Review daily posture vs actual bot outcomes.")
    parser.add_argument("--date", default=date.today().isoformat())
    parser.add_argument("--log-path", type=Path, default=LOG_PATH)
    parser.add_argument("--report-path", type=Path, default=REPORT_PATH)
    parser.add_argument("--print", action="store_true", dest="print_output")
    args = parser.parse_args()
    report = build_report(day=args.date)
    append_log(report, args.log_path)
    write_report(report, args.report_path)
    if args.print_output:
        print_report(report)
    else:
        print(f"Daily outcome review logged to {args.log_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

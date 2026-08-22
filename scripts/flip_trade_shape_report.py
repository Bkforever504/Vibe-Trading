#!/usr/bin/env python3
"""Summarize executable Flip trade paths without changing execution.

Winning and losing trades are defined from filled entry/exit prices. Intraday
shape statistics use executable bids captured by the monitor, never midpoint
highs. The report is descriptive and has no order or promotion authority.
"""
from __future__ import annotations

import argparse
import json
import math
import os
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
STATE_PATH = Path.home() / ".vibe-trading" / "flip-trades.json"
REPORT_PATH = Path.home() / ".vibe-trading" / "reports" / "flip-trade-shapes.json"
LOG_PATH = ROOT / "data" / "flip_trade_shape_report_log.jsonl"
MIN_REVIEW_TRADES = 30
MIN_REVIEW_DATES = 10


def _number(value: Any) -> float | None:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def _read_trades(path: Path) -> list[dict[str, Any]]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        return []
    return [row for row in payload if isinstance(row, dict)] if isinstance(payload, list) else []


def _return_pct(trade: dict[str, Any]) -> float | None:
    entry = _number(trade.get("entry_price"))
    exit_price = _number(trade.get("exit_price"))
    if entry is None or entry <= 0 or exit_price is None:
        return None
    return (exit_price - entry) / entry * 100.0


def _broker_fill_verified(trade: dict[str, Any]) -> bool:
    entry_verified = bool(trade.get("entry_fill_confirmed")) or str(
        trade.get("entry_price_source") or ""
    ) == "broker_fill"
    exit_verified = str(trade.get("exit_price_source") or "") == "broker_filled_avg_price"
    return entry_verified and exit_verified


def _summarize(rows: list[dict[str, Any]]) -> dict[str, Any]:
    returns = [value for row in rows if (value := _return_pct(row)) is not None]
    dates = {str(row.get("entry_date") or "")[:10] for row in rows if row.get("entry_date")}
    captures: list[float] = []
    givebacks: list[float] = []
    frictions: list[float] = []
    for row in rows:
        realized = _return_pct(row)
        best = _number(row.get("best_pnl_pct"))
        if realized is not None and best is not None and best > 0:
            captures.append(realized / best)
            givebacks.append(max(0.0, best - realized))
        shape = row.get("last_trade_shape") if isinstance(row.get("last_trade_shape"), dict) else {}
        friction = _number(shape.get("mid_to_executable_friction_pct_of_entry"))
        if friction is not None:
            frictions.append(friction)
    wins = sum(value > 0 for value in returns)
    return {
        "completed_count": len(returns),
        "distinct_entry_dates": len(dates),
        "win_rate": round(wins / len(returns), 4) if returns else None,
        "average_realized_return_pct": round(sum(returns) / len(returns), 3) if returns else None,
        "average_capture_ratio_of_positive_mfe": round(sum(captures) / len(captures), 4) if captures else None,
        "average_giveback_from_positive_mfe_pct_points": round(sum(givebacks) / len(givebacks), 3) if givebacks else None,
        "average_last_mark_mid_to_bid_friction_pct_of_entry": round(sum(frictions) / len(frictions), 3) if frictions else None,
        "review_ready": len(returns) >= MIN_REVIEW_TRADES and len(dates) >= MIN_REVIEW_DATES,
    }


def build_report(state_path: Path = STATE_PATH) -> dict[str, Any]:
    trades = _read_trades(state_path)
    priced_closed = [
        row for row in trades if row.get("status") == "closed" and _return_pct(row) is not None
    ]
    closed = [row for row in priced_closed if _broker_fill_verified(row)]
    legacy_closed = [row for row in priced_closed if not _broker_fill_verified(row)]
    by_first_mark: dict[str, list[dict[str, Any]]] = defaultdict(list)
    by_symbol: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in closed:
        by_first_mark[str(row.get("first_executable_mark_confirmation") or "missing")].append(row)
        by_symbol[str(row.get("symbol") or "unknown").upper()].append(row)
    exit_reasons = Counter(str(row.get("exit_reason") or "unknown").split(" (")[0] for row in closed)
    final_states = Counter(
        str((row.get("last_trade_shape") or {}).get("state") or "missing")
        for row in closed
    )
    overall = _summarize(closed)
    return {
        "provider": "flip_trade_shape_report",
        "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "source_path": str(state_path),
        "mode": "read_only_executable_path_accounting",
        "execution_enabled": False,
        "can_submit_orders": False,
        "can_change_exit_policy": False,
        "definitions": {
            "winner": "verified broker exit fill is above verified broker entry fill",
            "loser": "verified broker exit fill is at or below verified broker entry fill",
            "path_marks": "monitor-observed executable bid; midpoint is benchmark only",
            "review_gate": f"at least {MIN_REVIEW_TRADES} completed trades across {MIN_REVIEW_DATES} entry dates",
        },
        "overall": overall,
        "legacy_or_unverified_closed": {
            **_summarize(legacy_closed),
            "excluded_from_review": True,
            "reason": "entry_and_exit_broker_fill_provenance_not_both_verified",
        },
        "by_first_executable_mark": {
            key: _summarize(rows) for key, rows in sorted(by_first_mark.items())
        },
        "by_symbol": {key: _summarize(rows) for key, rows in sorted(by_symbol.items())},
        "exit_reason_counts": dict(exit_reasons.most_common()),
        "last_observed_shape_counts": dict(final_states.most_common()),
        "warnings": [
            "This report is descriptive and cannot alter an entry, exit, size, or promotion gate.",
            "No shape is considered predictive until its review gate and a chronological holdout pass.",
            "Missing executable bids remain missing; midpoint marks are never substituted.",
        ],
    }


def _write(path: Path, report: dict[str, Any], *, append: bool = False) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if append:
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(report, sort_keys=True, separators=(",", ":")) + "\n")
        return
    temp = path.with_suffix(
        path.suffix + f".tmp-{os.getpid()}-{datetime.now(timezone.utc).timestamp()}"
    )
    try:
        temp.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        os.replace(temp, path)
    finally:
        temp.unlink(missing_ok=True)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--state", type=Path, default=STATE_PATH)
    parser.add_argument("--output", type=Path, default=REPORT_PATH)
    parser.add_argument("--log", type=Path, default=LOG_PATH)
    parser.add_argument("--print", action="store_true", dest="print_report")
    args = parser.parse_args()
    report = build_report(args.state)
    _write(args.output, report)
    _write(args.log, report, append=True)
    if args.print_report:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        print(f"Flip trade-shape report written to {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

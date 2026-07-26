#!/usr/bin/env python3
"""Blocked-versus-taken outcome tracker for the options multi-warning
stand_aside gate (read-only).

Compares decision rows blocked by `shadow_consensus_multi_warning_stand_aside`
against entries actually submitted, using forward underlying moves from the
local daily caches. Underlying moves are a risk proxy for short-premium
positions, not option P&L; the report says so explicitly. Promotion review of
the gate requires at least 30 independent blocked candidates with resolved
horizons.
"""
from __future__ import annotations

import argparse
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
VIBE_HOME = Path.home() / ".vibe-trading"
DECISIONS_PATH = VIBE_HOME / "logs" / "options-decisions.jsonl"
DAILY_DIR = ROOT / "data" / "htf_volume_screen_lab"
REPORT_PATH = VIBE_HOME / "reports" / "options-caution-gate-outcomes.json"

BLOCK_REASON = "shadow_consensus_multi_warning_stand_aside"
HORIZON_TRADING_DAYS = 5
MIN_CANDIDATES_FOR_REVIEW = 30


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(row, dict):
            rows.append(row)
    return rows


def _daily_closes(symbol: str) -> list[tuple[str, float]]:
    """(iso_date, close) ascending from the newest local daily cache."""
    matches = sorted(DAILY_DIR.glob(f"{symbol.lower()}_*.parquet"))
    if not matches:
        return []
    import pandas as pd

    frame = pd.read_parquet(matches[-1])
    frame.columns = [str(column).lower() for column in frame.columns]
    index = pd.to_datetime(frame.index).tz_localize(None).normalize()
    closes = frame["close"].astype(float)
    return [(day.date().isoformat(), float(value)) for day, value in zip(index, closes)]


def forward_move(closes: list[tuple[str, float]], day: str, horizon: int) -> dict[str, Any] | None:
    """Signed and absolute pct move from the first close on/after `day` to
    `horizon` trading days later. None while unresolved."""
    dates = [d for d, _ in closes]
    start_index = next((i for i, d in enumerate(dates) if d >= day), None)
    if start_index is None or start_index + horizon >= len(closes):
        return None
    start = closes[start_index][1]
    end = closes[start_index + horizon][1]
    if start <= 0:
        return None
    move = (end / start - 1.0) * 100
    return {
        "start_date": closes[start_index][0],
        "end_date": closes[start_index + horizon][0],
        "move_pct": round(move, 3),
        "abs_move_pct": round(abs(move), 3),
    }


def _cohort_rows(decisions: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    blocked = [row for row in decisions if row.get("reason") == BLOCK_REASON]
    taken = [row for row in decisions if row.get("action") == "submitted"]
    return blocked, taken


def _summarize(rows: list[dict[str, Any]]) -> dict[str, Any]:
    resolved = [row for row in rows if row.get("outcome")]
    moves = [row["outcome"]["move_pct"] for row in resolved]
    abs_moves = [row["outcome"]["abs_move_pct"] for row in resolved]
    return {
        "candidates": len(rows),
        "resolved": len(resolved),
        "unresolved": len(rows) - len(resolved),
        "mean_move_pct": round(sum(moves) / len(moves), 3) if moves else None,
        "mean_abs_move_pct": round(sum(abs_moves) / len(abs_moves), 3) if abs_moves else None,
        "large_adverse_share_gt_2pct": (
            round(sum(1 for value in abs_moves if value > 2.0) / len(abs_moves), 3)
            if abs_moves else None
        ),
    }


def build_report(
    decisions_path: Path = DECISIONS_PATH,
    horizon: int = HORIZON_TRADING_DAYS,
    closes_fn=None,
) -> dict[str, Any]:
    closes_fn = closes_fn or _daily_closes
    decisions = _read_jsonl(decisions_path)
    blocked_raw, taken_raw = _cohort_rows(decisions)
    closes_cache: dict[str, list[tuple[str, float]]] = {}

    def resolve(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        out = []
        for row in rows:
            symbol = str(row.get("symbol") or "")
            day = str(row.get("ts") or "")[:10]
            if not symbol or not day:
                continue
            if symbol not in closes_cache:
                closes_cache[symbol] = closes_fn(symbol)
            outcome = forward_move(closes_cache[symbol], day, horizon)
            out.append({
                "symbol": symbol,
                "date": day,
                "strategy": row.get("strategy"),
                "outcome": outcome,
            })
        return out

    blocked = resolve(blocked_raw)
    taken = resolve(taken_raw)
    blocked_summary = _summarize(blocked)
    independent_blocked_dates = len({row["date"] for row in blocked})
    return {
        "provider": "options_caution_gate_outcomes",
        "mode": "read_only",
        "execution_enabled": False,
        "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "block_reason": BLOCK_REASON,
        "horizon_trading_days": horizon,
        "metric_basis": "underlying_forward_move_proxy_not_option_pnl",
        "blocked": blocked_summary,
        "independent_blocked_dates": independent_blocked_dates,
        "taken": _summarize(taken),
        "review_gate": {
            "minimum_independent_blocked_candidates": MIN_CANDIDATES_FOR_REVIEW,
            "review_eligible": independent_blocked_dates >= MIN_CANDIDATES_FOR_REVIEW,
        },
        "rows": {"blocked": blocked, "taken": taken},
        "authority": "observational_only_cannot_change_gate",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--print", action="store_true", dest="do_print")
    args = parser.parse_args()
    report = build_report()
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    temp = REPORT_PATH.with_suffix(REPORT_PATH.suffix + ".tmp")
    temp.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(temp, REPORT_PATH)
    summary = {key: report[key] for key in ("blocked", "taken", "independent_blocked_dates", "review_gate")}
    print(json.dumps(summary, indent=2, sort_keys=True))
    if args.do_print:
        print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

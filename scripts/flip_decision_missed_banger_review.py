#!/usr/bin/env python3
"""Review skipped Flip decisions against subsequent SPY price paths.

Read-only research. Underlying 5-minute moves are a proxy for missed option
opportunity, not reconstructed option fills or proof that a gate should change.
"""
from __future__ import annotations

import argparse
import json
import os
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable


ROOT = Path(__file__).resolve().parent.parent
VIBE_HOME = Path.home() / ".vibe-trading"
DECISION_LOG_PATH = VIBE_HOME / "logs" / "flip-decisions.jsonl"
REPORT_PATH = VIBE_HOME / "reports" / "flip-decision-missed-banger-review.json"
LOG_PATH = ROOT / "data" / "flip_decision_missed_banger_review_log.jsonl"
LOOKBACK_DAYS = 30
HORIZON_MINUTES = 60
MISSED_BANGER_UNDERLYING_MOVE_PCT = 0.50
MAX_BAR_DELAY_MINUTES = 10


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    try:
        raw_lines = path.read_text(encoding="utf-8-sig").splitlines()
    except OSError:
        return []
    rows: list[dict[str, Any]] = []
    for raw in raw_lines:
        try:
            row = json.loads(raw)
        except json.JSONDecodeError:
            continue
        if isinstance(row, dict):
            rows.append(row)
    return rows


def _timestamp(value: Any) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _direction(row: dict[str, Any]) -> str | None:
    details = row.get("details") if isinstance(row.get("details"), dict) else {}
    orb = str(details.get("orb_direction") or "").lower()
    if orb in {"bull", "bear"}:
        return orb
    right = str(details.get("right") or "").upper()
    if right == "CALL":
        return "bull"
    if right == "PUT":
        return "bear"
    strategy = str(row.get("strategy") or "").lower()
    if strategy == "bull_trend":
        return "bull"
    if strategy == "bear_trend":
        return "bear"
    return None


def _fetch_bars(symbol: str, start: datetime, end: datetime) -> list[dict[str, Any]]:
    import pandas as pd
    import yfinance as yf

    frame = yf.download(
        symbol,
        start=start.date().isoformat(),
        end=(end.date() + timedelta(days=1)).isoformat(),
        interval="5m",
        auto_adjust=False,
        prepost=False,
        progress=False,
        threads=False,
    )
    if frame.empty:
        return []
    if isinstance(frame.columns, pd.MultiIndex):
        frame = frame.xs(symbol, axis=1, level=-1)
    rows: list[dict[str, Any]] = []
    for stamp, values in frame.iterrows():
        if stamp.tzinfo is None:
            stamp = stamp.tz_localize("America/New_York")
        stamp = stamp.tz_convert("UTC")
        rows.append({
            "ts": stamp.to_pydatetime(),
            "open": float(values["Open"]),
            "high": float(values["High"]),
            "low": float(values["Low"]),
            "close": float(values["Close"]),
        })
    return rows


def evaluate_decision(
    row: dict[str, Any],
    bars: list[dict[str, Any]],
    *,
    horizon_minutes: int = HORIZON_MINUTES,
) -> dict[str, Any]:
    ts = _timestamp(row.get("ts"))
    direction = _direction(row)
    base = {
        "decision_id": f"{row.get('symbol')}:{row.get('ts')}:{row.get('strategy')}:{row.get('reason')}",
        "ts": row.get("ts"),
        "symbol": str(row.get("symbol") or "").upper(),
        "strategy": row.get("strategy"),
        "action": row.get("action"),
        "reason": row.get("reason"),
        "direction": direction,
        "blockers": (row.get("details") or {}).get("blockers", []) if isinstance(row.get("details"), dict) else [],
        "evidence_kind": "underlying_5m_proxy_not_option_fill",
    }
    if ts is None:
        return {**base, "outcome_status": "invalid_timestamp"}
    if direction is None:
        return {**base, "outcome_status": "direction_unavailable"}
    eligible_bars = [bar for bar in bars if ts <= bar["ts"] <= ts + timedelta(minutes=horizon_minutes)]
    if not eligible_bars or (eligible_bars[0]["ts"] - ts).total_seconds() > MAX_BAR_DELAY_MINUTES * 60:
        return {**base, "outcome_status": "price_path_unavailable"}
    entry = float(eligible_bars[0]["open"])
    path_max = max(float(bar["high"]) for bar in eligible_bars)
    path_min = min(float(bar["low"]) for bar in eligible_bars)
    end = float(eligible_bars[-1]["close"])
    if direction == "bull":
        favorable = (path_max - entry) / entry * 100
        adverse = (entry - path_min) / entry * 100
        end_move = (end - entry) / entry * 100
    else:
        favorable = (entry - path_min) / entry * 100
        adverse = (path_max - entry) / entry * 100
        end_move = (entry - end) / entry * 100
    return {
        **base,
        "outcome_status": "observed",
        "entry_bar_at": eligible_bars[0]["ts"].isoformat().replace("+00:00", "Z"),
        "entry_underlying": round(entry, 4),
        "horizon_minutes": horizon_minutes,
        "bars_observed": len(eligible_bars),
        "max_favorable_underlying_pct": round(favorable, 4),
        "max_adverse_underlying_pct": round(adverse, 4),
        "directional_end_move_pct": round(end_move, 4),
        "is_missed_banger_proxy": favorable >= MISSED_BANGER_UNDERLYING_MOVE_PCT,
    }


def _group_stats(rows: list[dict[str, Any]], key: str) -> dict[str, dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        values = row.get(key) if key == "blockers" else [row.get(key)]
        if not isinstance(values, list):
            values = [values]
        for value in values or ["none"]:
            grouped[str(value or "unknown")].append(row)
    return {
        name: {
            "observed_count": len(items),
            "missed_banger_proxy_count": sum(bool(item.get("is_missed_banger_proxy")) for item in items),
            "missed_banger_proxy_rate": round(sum(bool(item.get("is_missed_banger_proxy")) for item in items) / len(items), 4),
            "avg_max_favorable_underlying_pct": round(sum(float(item.get("max_favorable_underlying_pct") or 0.0) for item in items) / len(items), 4),
            "trading_days": len({str(item.get("ts") or "")[:10] for item in items}),
        }
        for name, items in sorted(grouped.items())
    }


def build_report(
    *,
    decision_log: Path = DECISION_LOG_PATH,
    now: datetime | None = None,
    fetcher: Callable[[str, datetime, datetime], list[dict[str, Any]]] = _fetch_bars,
) -> dict[str, Any]:
    current = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    cutoff = current - timedelta(days=LOOKBACK_DAYS)
    candidates = []
    for row in _read_jsonl(decision_log):
        ts = _timestamp(row.get("ts"))
        if ts is None or ts < cutoff or str(row.get("symbol") or "").upper() != "SPY":
            continue
        if row.get("action") not in {"skip", "blocked"}:
            continue
        candidates.append(row)
    bars = fetcher("SPY", cutoff, current) if candidates else []
    evaluations = [evaluate_decision(row, bars) for row in candidates]
    observed = [row for row in evaluations if row.get("outcome_status") == "observed"]
    statuses = Counter(str(row.get("outcome_status")) for row in evaluations)
    return {
        "provider": "flip_decision_missed_banger_review",
        "generated_at": current.isoformat().replace("+00:00", "Z"),
        "mode": "read_only_research",
        "execution_enabled": False,
        "can_submit_orders": False,
        "lookback_days": LOOKBACK_DAYS,
        "horizon_minutes": HORIZON_MINUTES,
        "preregistered_missed_banger_underlying_move_pct": MISSED_BANGER_UNDERLYING_MOVE_PCT,
        "decision_count": len(evaluations),
        "observed_count": len(observed),
        "outcome_status_counts": dict(sorted(statuses.items())),
        "missed_banger_proxy_count": sum(bool(row.get("is_missed_banger_proxy")) for row in observed),
        "by_reason": _group_stats(observed, "reason"),
        "by_blocker": _group_stats([row for row in observed if row.get("blockers")], "blockers"),
        "evaluations": evaluations,
        "interpretation": [
            "A favorable SPY move is only an underlying proxy; it is not an option fill or realizable option P&L.",
            "Repeated intraday decisions are correlated observations, so trading-day counts matter more than raw rows.",
            "This report cannot change execution gates or promote a rule automatically.",
            "Direction-unavailable historical rows remain unscored rather than inferred after the fact.",
        ],
    }


def _atomic_write(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(temp, path)


def write_outputs(report: dict[str, Any], report_path: Path = REPORT_PATH, log_path: Path = LOG_PATH) -> None:
    _atomic_write(report_path, report)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(report, separators=(",", ":"), sort_keys=True) + "\n")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--decision-log", type=Path, default=DECISION_LOG_PATH)
    parser.add_argument("--report-path", type=Path, default=REPORT_PATH)
    parser.add_argument("--log-path", type=Path, default=LOG_PATH)
    parser.add_argument("--print", action="store_true", dest="do_print")
    args = parser.parse_args()
    report = build_report(decision_log=args.decision_log)
    write_outputs(report, args.report_path, args.log_path)
    if args.do_print:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        print(f"Flip decision missed-banger review written to {args.report_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Audit liquid radar signals against their actual completed 5-minute chart path.

Signals are frozen from the first same-session radar snapshot that reported a
completed 5m confirmation.  Outcomes are underlying-price observations only;
they do not assume a fill, options contract, or live execution.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, time, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.intraday_opportunity_radar import MARKET_TZ, _finite, _read_json, fetch_intraday_bars
from scripts.premarket_opportunity_radar import _atomic_json

VIBE_HOME = Path.home() / ".vibe-trading"
LOG_PATH = ROOT / "data" / "intraday_opportunity_radar_log.jsonl"
REPORT_PATH = VIBE_HOME / "reports" / "liquid-signal-chart-audit.json"
LEDGER_PATH = ROOT / "data" / "liquid_signal_chart_audit.jsonl"
MIN_AVG_DOLLAR_VOLUME = 100_000_000
MAX_SPREAD_PCT = 0.005
MIN_PRICE = 10.0
HORIZONS = (5, 15, 30, 60)


def _history(path: Path, session: str) -> list[dict[str, Any]]:
    try:
        rows = [json.loads(line) for line in path.read_text(encoding="utf-8-sig").splitlines() if line.strip()]
    except (OSError, json.JSONDecodeError):
        return []
    return [row for row in rows if isinstance(row, dict) and str(row.get("date") or "")[:10] == session]


def first_liquid_confirmations(history: list[dict[str, Any]]) -> list[dict[str, Any]]:
    found: dict[str, dict[str, Any]] = {}
    for snapshot in sorted(history, key=lambda row: str(row.get("as_of_et") or "")):
        captured_at = str(snapshot.get("as_of_et") or snapshot.get("generated_at") or "")
        for candidate in snapshot.get("ranked_candidates") or []:
            if not isinstance(candidate, dict):
                continue
            symbol = str(candidate.get("symbol") or "").upper()
            confirmation = candidate.get("price_action_confirmation") if isinstance(candidate.get("price_action_confirmation"), dict) else {}
            if not symbol or symbol in found or str(candidate.get("confirmation_stage") or "") != "completed_5m_confirmed":
                continue
            if not (
                (_finite(candidate.get("avg_dollar_volume_20d")) or 0) >= MIN_AVG_DOLLAR_VOLUME
                and (_finite(candidate.get("price")) or 0) >= MIN_PRICE
                and (_finite(candidate.get("spread_pct")) is not None and (_finite(candidate.get("spread_pct")) or 1) <= MAX_SPREAD_PCT)
            ):
                continue
            signal_time = str(confirmation.get("bar_completed_at") or "")
            entry = _finite(candidate.get("entry"))
            direction = str(candidate.get("direction") or "")
            if not signal_time or entry is None or direction not in {"bullish", "bearish"}:
                continue
            found[symbol] = {"symbol": symbol, "direction": direction, "setup": candidate.get("setup"), "signal_bar_completed_at": signal_time, "first_seen_at": captured_at, "entry_reference": entry, "invalidation": _finite(candidate.get("invalidation")), "target_2r": _finite(candidate.get("target")), "scanner_score": _finite(candidate.get("score")), "scanner_grade": candidate.get("grade")}
    return list(found.values())


def _time(value: str) -> datetime | None:
    try:
        result = pd.Timestamp(value).to_pydatetime()
    except (TypeError, ValueError):
        return None
    return result.replace(tzinfo=timezone.utc) if result.tzinfo is None else result


def chart_outcome(signal: dict[str, Any], rows: list[dict[str, Any]]) -> dict[str, Any]:
    stamp = _time(str(signal.get("signal_bar_completed_at") or ""))
    entry = _finite(signal.get("entry_reference"))
    if stamp is None or entry is None:
        return {**signal, "outcome_status": "unavailable", "reason": "signal_time_or_entry_missing"}
    bars = []
    for row in rows:
        bar_time = _time(str(row.get("t") or ""))
        close = _finite(row.get("c")); high = _finite(row.get("h")); low = _finite(row.get("l"))
        if bar_time and close is not None and high is not None and low is not None:
            bars.append((bar_time, close, high, low))
    bars.sort(key=lambda row: row[0])
    after = [row for row in bars if row[0] >= stamp]
    if not after:
        return {**signal, "outcome_status": "unavailable", "reason": "actual_chart_bar_missing"}
    side = 1 if signal["direction"] == "bullish" else -1
    outcome: dict[str, Any] = {**signal, "outcome_status": "resolved_underlying_path", "chart_source": "alpaca_iex_completed_5m", "fill_assumed": False, "execution_enabled": False, "can_submit_orders": False}
    for horizon in HORIZONS:
        window = after[: max(1, horizon // 5)]
        if len(window) < horizon // 5:
            outcome[f"forward_{horizon}m_status"] = "pending_insufficient_completed_bars"
            continue
        close = window[-1][1]
        outcome[f"forward_{horizon}m_return_pct"] = round(side * (close / entry - 1) * 100, 4)
        outcome[f"forward_{horizon}m_status"] = "resolved"
    available = after[:12]
    outcome["mfe_pct_60m_or_available"] = round(side * ((max(row[2] for row in available) if side > 0 else min(row[3] for row in available)) / entry - 1) * 100, 4)
    outcome["mae_pct_60m_or_available"] = round(side * ((min(row[3] for row in available) if side > 0 else max(row[2] for row in available)) / entry - 1) * 100, 4)
    outcome["completed_bars_after_signal"] = len(after)
    return outcome


def build_report(now_et: datetime | None = None, log_path: Path = LOG_PATH) -> dict[str, Any]:
    now_et = (now_et or datetime.now(timezone.utc).astimezone(MARKET_TZ)).astimezone(MARKET_TZ)
    history = _history(log_path, now_et.date().isoformat())
    signals = first_liquid_confirmations(history)
    bars, errors = fetch_intraday_bars([row["symbol"] for row in signals], now_et)
    outcomes = [chart_outcome(signal, bars.get(signal["symbol"], [])) for signal in signals]
    resolved_30 = [row["forward_30m_return_pct"] for row in outcomes if row.get("forward_30m_status") == "resolved"]
    return {"schema_version": 1, "date": now_et.date().isoformat(), "as_of_et": now_et.isoformat(), "mode": "chart_based_shadow_audit", "execution_enabled": False, "can_submit_orders": False, "signal_definition": "first same-session liquid completed-5m radar confirmation", "liquidity_definition": {"min_avg_dollar_volume_20d": MIN_AVG_DOLLAR_VOLUME, "max_underlying_spread_pct": MAX_SPREAD_PCT * 100, "min_price": MIN_PRICE}, "summary": {"radar_snapshots": len(history), "liquid_confirmed_signals": len(signals), "chart_resolved_signals": sum(row.get("outcome_status") == "resolved_underlying_path" for row in outcomes), "resolved_30m_mean_return_pct": round(sum(resolved_30) / len(resolved_30), 4) if resolved_30 else None}, "signals": outcomes, "errors": errors, "warnings": ["Uses actual completed underlying 5-minute chart bars after the point-in-time signal.", "No fill, options premium, slippage, or profitability is inferred.", "This is an outcome audit and cannot change current ranks or execution."]}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report-path", type=Path, default=REPORT_PATH)
    parser.add_argument("--ledger-path", type=Path, default=LEDGER_PATH)
    parser.add_argument("--print", action="store_true", dest="show")
    args = parser.parse_args(); report = build_report(); _atomic_json(args.report_path, report)
    # Persist point-in-time chart outcomes for later cohort analysis. This is
    # append-only evidence, not a trading journal or execution record.
    args.ledger_path.parent.mkdir(parents=True, exist_ok=True)
    with args.ledger_path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(report, separators=(",", ":"), sort_keys=True) + "\n")
    if args.show: print(json.dumps(report, indent=2))
    else: print(f"Liquid chart audit: signals={report['summary']['liquid_confirmed_signals']} resolved={report['summary']['chart_resolved_signals']} errors={len(report['errors'])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

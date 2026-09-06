#!/usr/bin/env python3
"""Frozen, cost-aware forward evaluation for Donchian expansion observations.

Shadow-only. It records next-bar-open hypothetical underlying outcomes and
cannot produce alerts, broker calls, recommendations, or execution authority.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Mapping

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.intraday_opportunity_radar import MARKET_TZ, _finite, _read_json, fetch_intraday_bars
from scripts.premarket_opportunity_radar import _atomic_json

VIBE_HOME = Path.home() / ".vibe-trading"
SIGNAL_REPORT_PATH = VIBE_HOME / "reports" / "donchian-expansion-shadow.json"
REPORT_PATH = VIBE_HOME / "reports" / "donchian-expansion-forward-shadow.json"
LEDGER_PATH = ROOT / "data" / "donchian_expansion_forward_shadow.jsonl"
SLIPPAGE_PER_SIDE_BPS = 5.0
MAX_ENTRY_DELAY_MINUTES = 30
TIME_EXIT_MINUTES = 60
TARGET_R = 2.0


def _time(value: Any) -> datetime | None:
    try:
        stamp = pd.Timestamp(value).to_pydatetime()
    except (TypeError, ValueError):
        return None
    return stamp.replace(tzinfo=timezone.utc) if stamp.tzinfo is None else stamp


def freeze_signal(hit: Mapping[str, Any]) -> dict[str, Any] | None:
    symbol, direction = str(hit.get("symbol") or "").upper(), str(hit.get("direction") or "")
    stamp, bar = _time(hit.get("last_completed_bar_at")), hit.get("signal_bar")
    if not symbol or direction not in {"bullish", "bearish"} or stamp is None or not isinstance(bar, Mapping):
        return None
    stop = _finite(bar.get("low")) if direction == "bullish" else _finite(bar.get("high"))
    signal_close = _finite(bar.get("close"))
    if stop is None or signal_close is None:
        return None
    return {
        "signal_id": f"{symbol}:{direction}:{stamp.isoformat()}", "symbol": symbol, "direction": direction,
        "signal_bar_completed_at": stamp.isoformat(), "signal_close_reference": signal_close,
        "initial_stop_reference": stop, "entry_rule": "next_completed_5m_bar_open_within_30_minutes",
        "stop_rule": "signal_bar_low_for_long_signal_bar_high_for_short", "target_r": TARGET_R,
        "time_exit_minutes": TIME_EXIT_MINUTES, "slippage_per_side_bps": SLIPPAGE_PER_SIDE_BPS,
        "authority": "forward_shadow_only_no_alert_rank_sizing_or_execution", "execution_enabled": False, "can_submit_orders": False,
    }


def _existing_ids(path: Path) -> set[str]:
    try:
        return {str(json.loads(line).get("signal_id") or "") for line in path.read_text(encoding="utf-8").splitlines() if line.strip()}
    except (OSError, json.JSONDecodeError):
        return set()


def append_new_signals(hits: list[Mapping[str, Any]], path: Path) -> int:
    existing = _existing_ids(path)
    rows = [frozen for hit in hits if (frozen := freeze_signal(hit)) and frozen["signal_id"] not in existing]
    if not rows:
        return 0
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, sort_keys=True, separators=(",", ":")) + "\n")
    return len(rows)


def read_today(path: Path, session: str) -> list[dict[str, Any]]:
    try:
        rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    except (OSError, json.JSONDecodeError):
        return []
    return [row for row in rows if isinstance(row, dict) and str(row.get("signal_bar_completed_at") or "")[:10] == session]


def resolve_signal(signal: Mapping[str, Any], rows: list[dict[str, Any]]) -> dict[str, Any]:
    stamp, direction = _time(signal.get("signal_bar_completed_at")), str(signal.get("direction") or "")
    stop = _finite(signal.get("initial_stop_reference"))
    if stamp is None or direction not in {"bullish", "bearish"} or stop is None:
        return {**signal, "status": "unavailable", "reason": "signal_geometry_missing"}
    bars = []
    for row in rows:
        at = _time(row.get("t")); opened, high, low, closed = (_finite(row.get(key)) for key in ("o", "h", "l", "c"))
        if at and all(value is not None for value in (opened, high, low, closed)):
            bars.append((at, float(opened), float(high), float(low), float(closed)))
    bars.sort(key=lambda value: value[0])
    entry_bar = next((bar for bar in bars if stamp < bar[0] <= stamp + timedelta(minutes=MAX_ENTRY_DELAY_MINUTES)), None)
    if entry_bar is None:
        return {**signal, "status": "pending_entry_bar" if not bars or bars[-1][0] <= stamp + timedelta(minutes=MAX_ENTRY_DELAY_MINUTES) else "missed_entry_window"}
    side = 1.0 if direction == "bullish" else -1.0
    entry_raw = entry_bar[1]
    entry = entry_raw * (1 + side * SLIPPAGE_PER_SIDE_BPS / 10_000)
    risk = side * (entry - stop)
    if risk <= 0:
        return {**signal, "status": "invalid_geometry", "reason": "entry_not_beyond_stop", "entry_raw": entry_raw}
    target = entry + side * TARGET_R * risk
    exit_bar = None; exit_raw = None; reason = "pending_time_exit"
    horizon = entry_bar[0] + timedelta(minutes=TIME_EXIT_MINUTES)
    for bar in (row for row in bars if row[0] >= entry_bar[0]):
        stop_hit = bar[3] <= stop if side > 0 else bar[2] >= stop
        target_hit = bar[2] >= target if side > 0 else bar[3] <= target
        if stop_hit:  # Conservative if both boundaries occur inside one bar.
            exit_bar, exit_raw, reason = bar, stop, "stop"
            break
        if target_hit:
            exit_bar, exit_raw, reason = bar, target, "target_2r"
            break
        if bar[0] >= horizon:
            exit_bar, exit_raw, reason = bar, bar[4], "time_exit_60m"
            break
    if exit_bar is None:
        return {**signal, "status": "open_pending_resolution", "entry_raw": round(entry_raw, 4), "entry_at": entry_bar[0].isoformat(), "entry_after_slippage": round(entry, 4), "stop": round(stop, 4), "target_2r": round(target, 4), "risk_per_share": round(risk, 4)}
    exit_after_slippage = float(exit_raw) * (1 - side * SLIPPAGE_PER_SIDE_BPS / 10_000)
    net_r = side * (exit_after_slippage - entry) / risk
    return {**signal, "status": "resolved", "entry_raw": round(entry_raw, 4), "entry_at": entry_bar[0].isoformat(), "entry_after_slippage": round(entry, 4), "stop": round(stop, 4), "target_2r": round(target, 4), "risk_per_share": round(risk, 4), "exit_at": exit_bar[0].isoformat(), "exit_after_slippage": round(exit_after_slippage, 4), "exit_reason": reason, "net_r_after_costs": round(net_r, 4), "execution_enabled": False, "can_submit_orders": False}


def build_report(now_et: datetime | None = None, signal_path: Path = SIGNAL_REPORT_PATH, ledger_path: Path = LEDGER_PATH) -> dict[str, Any]:
    now_et = (now_et or datetime.now(timezone.utc).astimezone(MARKET_TZ)).astimezone(MARKET_TZ)
    signal_report = _read_json(signal_path)
    hits = [row for row in signal_report.get("rankings") or [] if isinstance(row, Mapping)]
    appended = append_new_signals(hits, ledger_path)
    signals = read_today(ledger_path, now_et.date().isoformat())
    bars, errors = fetch_intraday_bars([str(row.get("symbol") or "") for row in signals], now_et)
    outcomes = [resolve_signal(signal, bars.get(str(signal.get("symbol") or ""), [])) for signal in signals]
    resolved = [row.get("net_r_after_costs") for row in outcomes if row.get("status") == "resolved"]
    return {"schema_version": 1, "date": now_et.date().isoformat(), "as_of_et": now_et.isoformat(), "mode": "forward_shadow_cost_aware_underlying", "execution_enabled": False, "can_submit_orders": False, "frozen_policy": {"entry": "next_completed_5m_open_within_30m", "stop": "signal_bar_extreme", "target_r": TARGET_R, "time_exit_minutes": TIME_EXIT_MINUTES, "slippage_per_side_bps": SLIPPAGE_PER_SIDE_BPS, "same_bar_priority": "stop_before_target"}, "summary": {"new_signals_logged": appended, "signals_today": len(signals), "resolved": len(resolved), "mean_net_r_after_costs": round(sum(resolved) / len(resolved), 4) if resolved else None}, "outcomes": outcomes, "errors": errors, "warning": "Underlying-price forward shadow only. The fixed slippage stress is an assumption, not NBBO fill evidence. No promotion or execution authority is implied."}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report-path", type=Path, default=REPORT_PATH)
    parser.add_argument("--ledger-path", type=Path, default=LEDGER_PATH)
    args = parser.parse_args()
    report = build_report(ledger_path=args.ledger_path)
    _atomic_json(args.report_path, report)
    print(f"Donchian forward shadow: signals={report['summary']['signals_today']} resolved={report['summary']['resolved']} errors={len(report['errors'])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

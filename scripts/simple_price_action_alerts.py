#!/usr/bin/env python3
"""Compact, causal price-action alerts derived from the intraday radar.

This module has no broker imports or order authority. GREEN means the latest
completed 5-minute bar confirmed a mechanical setup and all quality gates
passed. It does not mean the trade is guaranteed to win.
"""
from __future__ import annotations

import argparse
import json
import sys
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.premarket_opportunity_radar import _atomic_json, _read_json
from scripts.shadow_alerts import webhook_url


VIBE_HOME = Path.home() / ".vibe-trading"
RADAR_PATH = VIBE_HOME / "reports" / "intraday-opportunity-radar.json"
REPORT_PATH = VIBE_HOME / "reports" / "simple-price-action-alerts.json"
STATE_PATH = VIBE_HOME / "state" / "simple-price-action-alerts.json"

QUALITY_GATES = (
    "price_floor",
    "completed_5m_structure",
    "underlying_spread",
    "dollar_liquidity",
    "meaningful_move_or_activity",
)


def _number(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if number == number and abs(number) != float("inf") else None


def _level(value: Any) -> float | None:
    number = _number(value)
    return round(number, 4) if number is not None else None


def _decisive_reason(
    row: dict[str, Any],
    state: str,
    failed: list[str],
    *,
    score: float,
    confirmation_state: str,
    expected_confirmation: str,
) -> str:
    confirmation = row.get("price_action_confirmation") or {}
    if state == "CONFIRMED":
        return str(confirmation.get("pattern") or row.get("setup") or "closed_bar_confirmation")
    if state == "INVALID":
        return failed[0] if failed else "invalidation_level_breached"
    if confirmation_state == expected_confirmation and score < 73.0:
        return "setup_quality_below_B_plus"
    if confirmation_state == expected_confirmation and row.get("state") != "precision_watch":
        return "radar_quality_not_precision_watch"
    return str(confirmation.get("pattern") or "waiting_for_closed_bar_confirmation")


def compact_signal(row: dict[str, Any]) -> dict[str, Any]:
    symbol = str(row.get("symbol") or "UNKNOWN").upper()
    direction = str(row.get("direction") or "neutral").lower()
    gates = row.get("hard_gates") if isinstance(row.get("hard_gates"), dict) else {}
    failed = [name for name in QUALITY_GATES if gates.get(name) is not True]
    confirmation = row.get("price_action_confirmation") if isinstance(row.get("price_action_confirmation"), dict) else {}
    confirmation_state = str(confirmation.get("state") or "waiting")
    expected_confirmation = "bullish_confirmed" if direction == "bullish" else "bearish_confirmed"
    score = _number(row.get("score")) or 0.0
    quality_passed = not failed and score >= 73.0 and row.get("state") == "precision_watch"

    levels = row.get("trade_levels") if isinstance(row.get("trade_levels"), dict) else {}
    entry = _level(levels.get("confirmation_trigger"))
    stop = _level(levels.get("invalidation"))
    target = _level(levels.get("target_2r"))
    price = _level(row.get("price"))
    invalidated = bool(
        price is not None
        and stop is not None
        and ((direction == "bullish" and price <= stop) or (direction == "bearish" and price >= stop))
    )

    if failed or invalidated or row.get("state") == "filtered":
        state, color = "INVALID", "RED"
    elif quality_passed and confirmation_state == expected_confirmation:
        state, color = "CONFIRMED", "GREEN"
    else:
        state, color = "WAIT", "YELLOW"

    side = "LONG" if direction == "bullish" else "SHORT" if direction == "bearish" else "NEUTRAL"
    reason = _decisive_reason(
        row,
        state,
        failed,
        score=score,
        confirmation_state=confirmation_state,
        expected_confirmation=expected_confirmation,
    )
    action = (
        f"{side} confirmed on a completed 5-minute bar; revalidate the quote before any paper entry."
        if state == "CONFIRMED"
        else "Stand aside; a quality gate or invalidation failed."
        if state == "INVALID"
        else f"Wait for a completed 5-minute {side.lower()} trigger and hold/retest."
    )
    return {
        "symbol": symbol,
        "state": state,
        "color": color,
        "direction": side,
        "grade": row.get("grade") or "--",
        "score": round(score, 1),
        "setup": row.get("setup") or "unconfirmed",
        "trigger": entry,
        "stop": stop,
        "target": target,
        "last_price": price,
        "decisive_reason": reason,
        "action": action,
        "failed_quality_gates": failed,
        "bar_completed_at": confirmation.get("bar_completed_at"),
        "score_definition": "setup_quality_not_probability",
        "execution_enabled": False,
        "can_submit_orders": False,
    }


def format_notification(signal: dict[str, Any]) -> str:
    return (
        f"**{signal['color']} {signal['state']} | {signal['symbol']} {signal['direction']} | "
        f"{signal['grade']} {signal['score']}/100**\n"
        f"Trigger `{signal['trigger']}` | Stop `{signal['stop']}` | Target `{signal['target']}`\n"
        f"Why: `{signal['decisive_reason']}`\n"
        f"{signal['action']}\n"
        "Signal only. Setup score is not win probability. No order placed."
    )


def _post_discord(message: str) -> bool:
    url = webhook_url()
    if not url:
        return False
    request = urllib.request.Request(
        url,
        data=json.dumps({"content": message}).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=10):
            return True
    except Exception:
        return False


def send_state_change_alerts(
    report: dict[str, Any],
    *,
    state_path: Path = STATE_PATH,
    sender: Callable[[str], bool] = _post_discord,
) -> int:
    previous = _read_json(state_path)
    previous_states = previous.get("states") if isinstance(previous.get("states"), dict) else {}
    current_states: dict[str, str] = {}
    sent = 0
    for signal in report.get("signals") or []:
        symbol = str(signal.get("symbol") or "")
        state = str(signal.get("state") or "WAIT")
        current_states[symbol] = state
        prior = previous_states.get(symbol)
        should_send = state == "CONFIRMED" and prior != "CONFIRMED"
        should_send = should_send or (state == "INVALID" and prior == "CONFIRMED")
        if should_send and sender(format_notification(signal)):
            sent += 1
    _atomic_json(
        state_path,
        {"schema_version": 1, "updated_at": report.get("generated_at"), "states": current_states},
    )
    return sent


def build_report(radar: dict[str, Any]) -> dict[str, Any]:
    rows = radar.get("ranked_candidates") if isinstance(radar.get("ranked_candidates"), list) else []
    signals = [compact_signal(row) for row in rows if isinstance(row, dict)]
    rank = {"CONFIRMED": 0, "WAIT": 1, "INVALID": 2}
    signals.sort(key=lambda row: (rank[row["state"]], -float(row["score"]), row["symbol"]))
    counts = {state: sum(row["state"] == state for row in signals) for state in rank}
    return {
        "schema_version": 1,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source_generated_at": radar.get("generated_at"),
        "source_session_status": radar.get("session_status"),
        "definitions": {
            "GREEN": "completed_5m_confirmation_plus_all_quality_gates_not_a_guarantee",
            "YELLOW": "watch_only_wait_for_closed_bar_confirmation",
            "RED": "failed_quality_gate_or_invalidation_stand_aside",
        },
        "counts": counts,
        "signals": signals[:24],
        "execution_enabled": False,
        "can_submit_orders": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--radar-path", type=Path, default=RADAR_PATH)
    parser.add_argument("--report-path", type=Path, default=REPORT_PATH)
    parser.add_argument("--state-path", type=Path, default=STATE_PATH)
    parser.add_argument("--alert", action="store_true")
    parser.add_argument("--print", action="store_true", dest="print_report")
    args = parser.parse_args()

    report = build_report(_read_json(args.radar_path))
    report["alerts_sent"] = send_state_change_alerts(report, state_path=args.state_path) if args.alert else 0
    _atomic_json(args.report_path, report)
    if args.print_report:
        print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

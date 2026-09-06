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
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Mapping

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.premarket_opportunity_radar import _atomic_json, _read_json
from scripts.priority_focus_universe import PRIORITY_FOCUS_UNIVERSE
from scripts.shadow_alerts import webhook_url
from scripts.alert_delivery_timing import first_complete_bar_after_delivery


VIBE_HOME = Path.home() / ".vibe-trading"
RADAR_PATH = VIBE_HOME / "reports" / "intraday-opportunity-radar.json"
REPORT_PATH = VIBE_HOME / "reports" / "simple-price-action-alerts.json"
STATE_PATH = VIBE_HOME / "state" / "simple-price-action-alerts.json"
LIFECYCLE_PATH = VIBE_HOME / "reports" / "intraday-trade-lifecycle-shadow.json"
DAILY_MAP_PATH = VIBE_HOME / "reports" / "daily-level-map-shadow.json"
EVENT_LOG_PATH = VIBE_HOME / "data" / "simple_price_action_alert_events.jsonl"

QUALITY_GATES = (
    "price_floor",
    "completed_5m_structure",
    "underlying_spread",
    "dollar_liquidity",
    "meaningful_move_or_activity",
)

# Core index products are the user's primary observation universe.  They stay
# shadow-only, but their visibility must not depend on the A+/B+ promotion
# policy used for individual-stock execution review.
CORE_INDEX_SYMBOLS = frozenset({"SPY", "QQQ", "IWM"})
PRIORITY_FOCUS_SYMBOLS = frozenset(PRIORITY_FOCUS_UNIVERSE)
INDEX_PROXY_MAP = {"SPY": ["SPX", "SPXW"]}


def _number(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if number == number and abs(number) != float("inf") else None


def _level(value: Any) -> float | None:
    number = _number(value)
    return round(number, 4) if number is not None else None


def _decision_available_at(value: Any) -> str | None:
    """Alpaca labels a 5m bar by its start; alerts need its close time."""
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return str(value)
    return (parsed + timedelta(minutes=5)).isoformat().replace("+00:00", "Z")


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


def compact_signal(row: dict[str, Any], *, execution_review: dict[str, Any] | None = None) -> dict[str, Any]:
    symbol = str(row.get("symbol") or "UNKNOWN").upper()
    core_index_shadow = symbol in CORE_INDEX_SYMBOLS
    priority_focus_shadow = symbol in PRIORITY_FOCUS_SYMBOLS
    direction = str(row.get("direction") or "neutral").lower()
    gates = row.get("hard_gates") if isinstance(row.get("hard_gates"), dict) else {}
    failed = [name for name in QUALITY_GATES if gates.get(name) is not True]
    confirmation = row.get("price_action_confirmation") if isinstance(row.get("price_action_confirmation"), dict) else {}
    confirmation_state = str(confirmation.get("state") or "waiting")
    expected_confirmation = "bullish_confirmed" if direction == "bullish" else "bearish_confirmed"
    score = _number(row.get("score")) or 0.0
    quality_passed = not failed and score >= 73.0 and row.get("state") == "precision_watch"
    core_visibility_passed = core_index_shadow and not failed

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

    review_outcome = str((execution_review or {}).get("outcome") or "")
    review_eligible = review_outcome in {"a_plus_manual_review_eligible", "b_plus_manual_review_eligible"}
    if failed or invalidated or row.get("state") == "filtered":
        state, color = "INVALID", "RED"
    elif (
        confirmation_state == expected_confirmation
        and (
            (quality_passed and (execution_review is None or review_eligible))
            or core_visibility_passed
        )
    ):
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
    if state == "WAIT" and execution_review is not None and not review_eligible and not core_index_shadow:
        reason = "manual_execution_review_not_eligible"
    action = (
        f"{side} confirmed on a completed 5-minute bar; revalidate the quote before any paper entry."
        if state == "CONFIRMED"
        else "Stand aside; a quality gate or invalidation failed."
        if state == "INVALID"
        else f"Core-index shadow watch active; wait for a completed 5-minute {side.lower()} trigger and hold/retest."
        if core_index_shadow
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
        "market_context": row.get('market_context') or {},
        "regime": (row.get('market_context') or {}).get('qqq_spy_regime') or 'unknown',
        "regime_observed_at": row.get('context_observed_at') or row.get('data_freshness', {}).get('latest_quote_at'),
        "trigger": entry,
        "stop": stop,
        "target": target,
        "last_price": price,
        "decisive_reason": reason,
        "action": action,
        "failed_quality_gates": failed,
        "bar_completed_at": _decision_available_at(confirmation.get("bar_completed_at")),
        "score_definition": "setup_quality_not_probability",
        "execution_review_outcome": review_outcome or "not_available",
        "execution_review_eligible": review_eligible,
        "observation_visible": priority_focus_shadow,
        "lane": "CORE_INDEX_SHADOW" if core_index_shadow else "PRIORITY_FOCUS_SHADOW" if priority_focus_shadow else "STANDARD_SHADOW",
        "always_visible": priority_focus_shadow,
        "index_proxy_for": INDEX_PROXY_MAP.get(symbol, []),
        "execution_enabled": False,
        "can_submit_orders": False,
    }


def compact_daily_map_signal(row: Mapping[str, Any]) -> dict[str, Any] | None:
    """Adapt one typed daily-map row into the governed candidate contract."""
    symbol = str(row.get("symbol") or "").upper()
    level = row.get("nearest_level") if isinstance(row.get("nearest_level"), Mapping) else {}
    confirmation = row.get("confirmation_3m") if isinstance(row.get("confirmation_3m"), Mapping) else {}
    map_state = str(confirmation.get("state") or "UNAVAILABLE").upper()
    direction = str(confirmation.get("direction") or "NONE").upper()
    if not symbol or map_state == "UNAVAILABLE":
        return None
    state = "CONFIRMED" if map_state == "CONFIRMED" else "INVALID" if map_state == "INVALIDATED" else "WAIT"
    color = "GREEN" if state == "CONFIRMED" else "RED" if state == "INVALID" else "YELLOW"
    trigger = _level(confirmation.get("trigger"))
    stop = _level(confirmation.get("invalidation"))
    target = _level(confirmation.get("next_target"))
    distance = _number(level.get("distance_points"))
    return {
        "symbol": symbol,
        "state": state,
        "color": color,
        "direction": direction,
        "grade": "SHADOW-3M",
        "score": 0.0,
        "setup": "daily_map_3m_level_reaction",
        "trigger": trigger,
        "stop": stop,
        "target": target,
        "last_price": round(trigger + distance, 4) if trigger is not None and distance is not None else None,
        "decisive_reason": str(confirmation.get("reason") or map_state.lower()),
        "action": "Completed 3-minute mapped-level confirmation; shadow lifecycle only." if state == "CONFIRMED" else "Observe the mapped level; do not chase or place an order.",
        "failed_quality_gates": [],
        "bar_completed_at": confirmation.get("bar_completed_at"),
        "score_definition": "not_scored_unvalidated_daily_map_shadow",
        "execution_review_outcome": "shadow_research_only",
        "lane": "DAILY_MAP_3M_SHADOW",
        "always_visible": symbol in CORE_INDEX_SYMBOLS,
        "index_proxy_for": INDEX_PROXY_MAP.get(symbol, []),
        "level_type": level.get("type"),
        "level_source": level.get("source"),
        "level_provenance": level.get("provenance"),
        "external_unverified": bool(level.get("external_unverified")),
        "execution_enabled": False,
        "can_submit_orders": False,
    }


def format_notification(signal: dict[str, Any]) -> str:
    proxy_for = signal.get("index_proxy_for") or []
    proxy_note = f" | proxy for {','.join(proxy_for)}" if proxy_for else ""
    return (
        f"**{signal['color']} {signal['state']} | {signal['symbol']} {signal['direction']} | "
        f"{signal['grade']} {signal['score']}/100{proxy_note}**\n"
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


def _append_event(path: Path, event: dict[str, Any]) -> bool:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(event, sort_keys=True) + "\n")
        return True
    except OSError:
        # Delivery must not be rolled back or duplicated merely because the
        # audit ledger is temporarily unavailable. Surface this separately.
        return False


def _recent_events(path: Path, *, limit: int = 50) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    events: list[dict[str, Any]] = []
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    for line in lines[-limit:]:
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(event, dict):
            events.append(event)
    return events


def send_state_change_alerts(
    report: dict[str, Any],
    *,
    state_path: Path = STATE_PATH,
    sender: Callable[[str], bool] = _post_discord,
    event_path: Path | None = None,
) -> int:
    previous = _read_json(state_path)
    previous_states = previous.get("states") if isinstance(previous.get("states"), dict) else {}
    previous_signatures = previous.get("signatures") if isinstance(previous.get("signatures"), dict) else {}
    current_states: dict[str, str] = {}
    current_signatures: dict[str, str] = {}
    sent = 0
    attempted = 0
    failed_deliveries = 0
    event_log_failures = 0
    for signal in report.get("signals") or []:
        symbol = str(signal.get("symbol") or "")
        state = str(signal.get("state") or "WAIT")
        current_states[symbol] = state
        prior = previous_states.get(symbol)
        core_index_shadow = bool(signal.get("always_visible"))
        session_day = str(signal.get("bar_completed_at") or report.get("generated_at") or "")[:10]
        watch_signature = "|".join(
            [session_day, str(signal.get("direction") or ""), str(signal.get("setup") or "")]
        )
        event_signature = "|".join([state, watch_signature])
        signature = event_signature if state == "CONFIRMED" else watch_signature
        current_signatures[symbol] = signature
        prior_signature = previous_signatures.get(symbol)
        should_send = state == "CONFIRMED" and (
            prior != "CONFIRMED" or (core_index_shadow and signature != prior_signature)
        )
        should_send = should_send or (state == "INVALID" and prior == "CONFIRMED")
        should_send = should_send or (
            core_index_shadow
            and state == "WAIT"
            and (prior != "WAIT" or signature != prior_signature)
        )
        if should_send:
            attempted += 1
            attempted_at = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
            delivered = sender(format_notification(signal))
            delivered_at = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z") if delivered else None
            if delivered:
                sent += 1
            else:
                failed_deliveries += 1
                # Never acknowledge an undelivered transition.  Preserve the
                # last successful state so the next scheduled cycle retries.
                if prior is None:
                    current_states.pop(symbol, None)
                else:
                    current_states[symbol] = prior
                if prior_signature is None:
                    current_signatures.pop(symbol, None)
                else:
                    current_signatures[symbol] = prior_signature
            if event_path is not None:
                event_logged = _append_event(
                    event_path,
                    {
                        "event_id": "|".join([symbol, signature, str(report.get("generated_at") or "")]),
                        "attempted_at": attempted_at,
                        "delivered_at": delivered_at,
                        "detected_at": report.get("generated_at"),
                        "source_generated_at": report.get("source_generated_at"),
                        "symbol": symbol,
                        "state": state,
                        "direction": signal.get("direction"),
                        "setup": signal.get("setup"),
                        "grade": signal.get("grade"),
                        "score": signal.get("score"),
                        "trigger": signal.get("trigger"),
                        "stop": signal.get("stop"),
                        "target": signal.get("target"),
                        "bar_completed_at": signal.get("bar_completed_at"),
                        "bar_timestamp_semantics": "decision_available_at",
                        "lane": signal.get("lane"),
                        "index_proxy_for": signal.get("index_proxy_for") or [],
                        "discord_delivered": delivered,
                        "execution_enabled": False,
                        "can_submit_orders": False,
                    },
                )
                if not event_logged:
                    event_log_failures += 1
    _atomic_json(
        state_path,
        {
            "schema_version": 2,
            "updated_at": report.get("generated_at"),
            "states": current_states,
            "signatures": current_signatures,
        },
    )
    report["notification_attempts"] = attempted
    report["notification_failures"] = failed_deliveries
    report["events_recorded"] = attempted
    report["event_log_failures"] = event_log_failures
    return sent


def _execution_reviews(lifecycle: dict[str, Any]) -> dict[str, dict[str, Any]]:
    reviews: dict[str, dict[str, Any]] = {}
    for plan in lifecycle.get("plans") or []:
        if not isinstance(plan, dict):
            continue
        symbol = str(plan.get("symbol") or "").upper()
        decision = plan.get("decision_contract")
        if symbol and isinstance(decision, dict):
            reviews[symbol] = decision
    return reviews


def build_report(
    radar: dict[str, Any],
    lifecycle: dict[str, Any] | None = None,
    daily_map: dict[str, Any] | None = None,
) -> dict[str, Any]:
    rows = radar.get("ranked_candidates") if isinstance(radar.get("ranked_candidates"), list) else []
    reviews = _execution_reviews(lifecycle or {})
    signals = [
        compact_signal(row, execution_review=reviews.get(str(row.get("symbol") or "").upper()) if lifecycle is not None else None)
        for row in rows if isinstance(row, dict)
    ]
    map_signals = [
        signal for signal in (
            compact_daily_map_signal(row)
            for row in (daily_map or {}).get("symbols") or []
            if isinstance(row, Mapping)
        ) if signal is not None
    ]
    signals.extend(map_signals)
    rank = {"CONFIRMED": 0, "WAIT": 1, "INVALID": 2}
    signals.sort(key=lambda row: (rank[row["state"]], -float(row["score"]), row["symbol"]))
    counts = {state: sum(row["state"] == state for row in signals) for state in rank}
    required_map = [row for row in signals if row.get("lane") == "DAILY_MAP_3M_SHADOW" and row.get("state") == "CONFIRMED"]
    core_signals = [row for row in signals if row.get("always_visible") and row not in required_map]
    standard_signals = [row for row in signals if not row.get("always_visible") and row not in required_map]
    reserved = required_map + core_signals
    visible_signals = reserved + standard_signals[: max(0, 24 - len(reserved))]
    visible_signals.sort(key=lambda row: (rank[row["state"]], -float(row["score"]), row["symbol"]))
    return {
        "schema_version": 1,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source_generated_at": radar.get("generated_at"),
        "source_session_status": radar.get("session_status"),
        "daily_map_source_generated_at": (daily_map or {}).get("generated_at"),
        "daily_map_source_status": (daily_map or {}).get("status", "not_loaded"),
        "execution_review_source": "intraday_trade_lifecycle_shadow" if lifecycle is not None else "not_loaded",
        "definitions": {
            "GREEN": "completed_5m_confirmation_plus_all_quality_gates_not_a_guarantee",
            "YELLOW": "watch_only_wait_for_closed_bar_confirmation",
            "RED": "failed_quality_gate_or_invalidation_stand_aside",
            "CORE_INDEX_SHADOW": "SPY_QQQ_IWM_watch_and_confirmation_are_visible_without_execution_promotion",
        },
        "counts": counts,
        "signals": visible_signals,
        "execution_enabled": False,
        "can_submit_orders": False,
    }


def record_current_signals(report: dict[str, Any], path: Path = EVENT_LOG_PATH) -> int:
    """Persist every current candidate once, independent of notification delivery."""
    existing: set[str] = set()
    for event in _recent_events(path, limit=10000):
        existing.add(str(event.get("event_id") or ""))
    recorded = 0
    for signal in report.get("signals") or []:
        event_id = "|".join(
            str(value or "") for value in (
                signal.get("symbol"), signal.get("lane"), signal.get("state"),
                signal.get("bar_completed_at"), signal.get("trigger"), signal.get("direction"),
            )
        )
        if event_id in existing:
            continue
        event = {
            "event_id": event_id,
            "detected_at": report.get("generated_at"),
            "source_generated_at": report.get("source_generated_at"),
            **{key: signal.get(key) for key in (
                "symbol", "state", "direction", "setup", "grade", "score", "trigger", "stop", "target",
                "bar_completed_at", "lane", "index_proxy_for", "level_type", "level_source",
                "level_provenance", "external_unverified", "execution_enabled", "can_submit_orders",
                "regime", "regime_observed_at", "market_context",
            )},
            "discord_delivered": None,
            "record_kind": "candidate_observation",
        }
        if _append_event(path, event):
            recorded += 1
            existing.add(event_id)
    return recorded


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--radar-path", type=Path, default=RADAR_PATH)
    parser.add_argument("--report-path", type=Path, default=REPORT_PATH)
    parser.add_argument("--state-path", type=Path, default=STATE_PATH)
    parser.add_argument("--lifecycle-path", type=Path, default=LIFECYCLE_PATH)
    parser.add_argument("--daily-map-path", type=Path, default=DAILY_MAP_PATH)
    parser.add_argument("--event-log-path", type=Path, default=EVENT_LOG_PATH)
    parser.add_argument("--alert", action="store_true")
    parser.add_argument("--print", action="store_true", dest="print_report")
    args = parser.parse_args()

    report = build_report(
        _read_json(args.radar_path),
        _read_json(args.lifecycle_path),
        _read_json(args.daily_map_path),
    )
    report["alerts_sent"] = send_state_change_alerts(
        report,
        state_path=args.state_path,
        event_path=None,
    ) if args.alert else 0
    report["candidate_events_recorded"] = record_current_signals(report, args.event_log_path)
    report["recent_events"] = _recent_events(args.event_log_path)
    _atomic_json(args.report_path, report)
    if args.print_report:
        print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

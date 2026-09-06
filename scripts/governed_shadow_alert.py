#!/usr/bin/env python3
"""Deliver governed shadow decisions with retryable, auditable diagnostics."""
from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Mapping
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import requests

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.shadow_alerts import webhook_url
from scripts import discord_trade_quality as quality

VIBE_HOME = Path.home() / ".vibe-trading"
DECISION_PATH = VIBE_HOME / "reports" / "governed-shadow-decisions.json"
STATE_PATH = VIBE_HOME / "state" / "governed-shadow-alert.json"
REPORT_PATH = VIBE_HOME / "reports" / "governed-shadow-alert-delivery.json"
EVENT_PATH = VIBE_HOME / "data" / "governed_shadow_alert_events.jsonl"
LATENCY_PAIRS_PATH = ROOT / "data" / "latency_pairs.jsonl"
MAX_LIVE_ALERT_AGE = timedelta(minutes=15)
DIRECT_REJECTED_LANES = frozenset()
SETUP_COOLDOWN = timedelta(minutes=15)


def _wait_url(url: str) -> str:
    parts = urlsplit(url)
    query = dict(parse_qsl(parts.query, keep_blank_values=True))
    query["wait"] = "true"
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), parts.fragment))


def _message_metadata(payload: Any) -> tuple[str | None, str | None]:
    if not isinstance(payload, Mapping):
        return None, None
    message_id = str(payload.get("id") or "").strip() or None
    timestamp = str(payload.get("timestamp") or "").strip() or None
    try:
        if timestamp:
            parsed = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
            timestamp = parsed.astimezone(timezone.utc).isoformat().replace("+00:00", "Z") if parsed.tzinfo else None
    except ValueError:
        timestamp = None
    return message_id, timestamp


def _response_json(response: Any) -> Any:
    try:
        if hasattr(response, "json"):
            return response.json()
        raw = response.read()
        return json.loads(raw.decode("utf-8")) if raw else None
    except (AttributeError, UnicodeDecodeError, json.JSONDecodeError, ValueError):
        return None


def _read(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        return default


def _atomic(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(path)


def _append(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(value, sort_keys=True) + "\n")


def format_message(row: Mapping[str, Any]) -> str:
    candidate = row.get("candidate") if isinstance(row.get("candidate"), Mapping) else {}
    blockers = ", ".join(str(item) for item in row.get("blockers") or []) or "none"
    decision = str(row.get("decision") or "shadow_rejected")
    label = "SIMULATE" if decision == "shadow_accepted" else "OBSERVE / VETOED"
    check = row.get('delivery_quality') or {}
    boundary = check.get('entry_boundary')
    boundary_text = f"{boundary:.4f}" if isinstance(boundary, (int, float)) else 'unavailable'
    entry_range = f"{candidate.get('trigger')} to {boundary_text}" if candidate.get('direction') == 'LONG' else f"{boundary_text} to {candidate.get('trigger')}"
    return (
        f"**SHADOW {label} | {candidate.get('symbol')} {candidate.get('direction')} | {candidate.get('grade', 'ungraded')}**\n"
        f"Setup `{candidate.get('setup')}` | completed `{candidate.get('bar_completed_at')}`\n"
        f"Entry `{candidate.get('trigger')}` | Stop `{candidate.get('stop')}` | Target `{candidate.get('target')}`\n"
        f"Current quote `{check.get('quote_price')}` | remaining R:R `{check.get('remaining_rr')}` | feed `{check.get('feed')}`\n"
        f"Permitted underlying entry range `{entry_range}`; skip outside range.\n"
        f"Quote time `{check.get('quote_at')}` | signal expires `{check.get('signal_expires_at')}`\n"
        f"Data scope `{check.get('quote_scope', 'unknown')}`. Recheck price and stop before any action; this quote is a snapshot.\n"
        f"Decision `{decision}` | blockers `{blockers}`\n"
        "Underlying-price plan, not an option-contract fill quote. Alert and simulation only. No broker order placed."
    )


def _is_fresh(row: Mapping[str, Any], *, now: datetime) -> bool:
    candidate = row.get("candidate") if isinstance(row.get("candidate"), Mapping) else {}
    try:
        completed = datetime.fromisoformat(str(candidate.get("bar_completed_at") or "").replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return False
    if completed.tzinfo is None:
        completed = completed.replace(tzinfo=timezone.utc)
    completed = completed.astimezone(timezone.utc)
    age = now - completed
    return timedelta(0) <= age <= MAX_LIVE_ALERT_AGE


def _discord_route(row: Mapping[str, Any]) -> tuple[bool, str]:
    """Keep rejected research visible without presenting every row as a trade alert."""
    if str(row.get("decision") or "shadow_rejected") == "shadow_accepted":
        return True, "shadow_accepted"
    candidate = row.get("candidate") if isinstance(row.get("candidate"), Mapping) else {}
    lane = str(candidate.get("lane") or "STANDARD_SHADOW")
    if lane in DIRECT_REJECTED_LANES:
        return True, "priority_shadow_review"
    if lane == "DAILY_MAP_3M_SHADOW":
        return False, "daily_map_has_dedicated_transition_alert"
    return False, "rejected_research_dashboard_only"


def deliver(message: str, *, opener: Callable[..., Any] | None = None, attempts: int = 3) -> dict[str, Any]:
    url = webhook_url()
    if not url:
        return {"delivered": False, "attempts": 0, "error_class": "webhook_not_configured"}
    wait_url = _wait_url(url)
    request = urllib.request.Request(
        wait_url,
        data=json.dumps({"content": message}).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    last_error = "unknown"
    for attempt in range(1, attempts + 1):
        try:
            if opener is not None:  # dependency-injection seam for deterministic tests
                with opener(request, timeout=10) as response:
                    message_id, discord_ts = _message_metadata(_response_json(response))
                    return {"delivered": True, "attempts": attempt, "error_class": None,
                            "discord_message_id": message_id, "discord_delivered_ts": discord_ts,
                            "ack_receipt_ts": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")}
            response = requests.post(
                wait_url,
                json={"content": message},
                headers={"User-Agent": "VibeTrading-ShadowAlerts/1.0"},
                timeout=10,
            )
            if 200 <= response.status_code < 300:
                message_id, discord_ts = _message_metadata(_response_json(response))
                return {"delivered": True, "attempts": attempt, "error_class": None,
                        "discord_message_id": message_id, "discord_delivered_ts": discord_ts,
                        "ack_receipt_ts": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")}
            last_error = f"http_{response.status_code}"
            if 400 <= response.status_code < 500 and response.status_code != 429:
                break
        except urllib.error.HTTPError as exc:
            last_error = f"http_{exc.code}"
            if 400 <= exc.code < 500 and exc.code != 429:
                break
        except Exception as exc:  # network details and webhook URL are never persisted
            last_error = type(exc).__name__
        if attempt < attempts:
            time.sleep(0.25 * attempt)
    return {"delivered": False, "attempts": attempt, "error_class": last_error,
            "discord_message_id": None, "discord_delivered_ts": None,
            "ack_receipt_ts": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")}


def run(
    decision_report: Mapping[str, Any], *, send: bool, state_path: Path = STATE_PATH,
    report_path: Path = REPORT_PATH, event_path: Path = EVENT_PATH,
    latency_pairs_path: Path | None = None,
    sender: Callable[[str], Mapping[str, Any]] = deliver,
    market_fetcher: Callable[..., dict[str, Any]] = quality.fetch_market,
) -> dict[str, Any]:
    state = _read(state_path, {})
    delivered_ids = {str(item) for item in state.get("delivered_event_ids") or []}
    dashboard_only_ids = {str(item) for item in state.get("dashboard_only_event_ids") or []}
    acknowledged_ids = delivered_ids | dashboard_only_ids | {str(item) for item in state.get("stale_event_ids") or []}
    stale_ids = {str(item) for item in state.get("stale_event_ids") or []}
    recent_setups = dict(state.get('recent_setups') or {})
    rows = [row for row in decision_report.get("decisions") or [] if isinstance(row, Mapping)]
    attempts = failures = sent = stale_skipped = dashboard_only = 0
    dashboard_only_reasons: dict[str, int] = {}
    events: list[dict[str, Any]] = []
    quality_checks: list[dict[str, Any]] = []
    now = datetime.now(timezone.utc)
    pending_rows = [row for row in rows if str(row.get('event_id') or '') not in acknowledged_ids and _discord_route(row)[0] and _is_fresh(row, now=now)]
    market = market_fetcher([row.get('candidate') or {} for row in pending_rows], now=now) if send and pending_rows else {}
    for row in rows:
        # Quotes can arrive after fetch began; evaluate age at dispatch, not
        # against the pre-request clock (also accounts for earlier sends).
        now = datetime.now(timezone.utc)
        event_id = str(row.get("event_id") or "")
        if not event_id or event_id in acknowledged_ids:
            continue
        direct, route_reason = _discord_route(row)
        if not direct:
            dashboard_only_ids.add(event_id)
            acknowledged_ids.add(event_id)
            dashboard_only += 1
            dashboard_only_reasons[route_reason] = dashboard_only_reasons.get(route_reason, 0) + 1
            continue
        now = datetime.now(timezone.utc)
        if not _is_fresh(row, now=now):
            stale_ids.add(event_id)
            acknowledged_ids.add(event_id)
            stale_skipped += 1
            continue
        candidate = row.get('candidate') or {}
        key = quality.setup_key(candidate)
        prior_delivery = quality.stamp(recent_setups.get(key))
        duplicate = prior_delivery is not None and timedelta(0) <= now - prior_delivery < SETUP_COOLDOWN
        check = quality.evaluate(candidate, market.get(str(candidate.get('symbol') or '').upper(), {}), now=now) if send else {'eligible': False, 'reasons': ['send_disabled']}
        if duplicate:
            check['eligible'] = False
            check['reasons'] = sorted(set(check['reasons'] + ['duplicate_setup_cooldown']))
        quality_checks.append({'event_id': event_id, 'symbol': candidate.get('symbol'), **check})
        if send and not check['eligible']:
            retryable = {'market_data_unavailable', 'quote_stale_or_future', 'invalid_bid_ask', 'post_signal_bar_coverage_missing', 'trigger_not_currently_held', 'spread_too_wide'}
            if not set(check['reasons']).issubset(retryable):
                dashboard_only_ids.add(event_id)
                acknowledged_ids.add(event_id)
            dashboard_only += 1
            for reason in check['reasons']:
                dashboard_only_reasons[reason] = dashboard_only_reasons.get(reason, 0) + 1
            continue
        attempted_at = datetime.now(timezone.utc)
        result = dict(sender(format_message({**row, 'delivery_quality': check}))) if send else {
            "delivered": False, "attempts": 0, "error_class": "send_disabled",
            "discord_message_id": None, "discord_delivered_ts": None, "ack_receipt_ts": None,
        }
        finished_at = datetime.now(timezone.utc)
        attempts += int(result.get("attempts") or 0)
        delivered = result.get("delivered") is True
        discord_delivered_ts = result.get("discord_delivered_ts")
        discord_message_id = result.get("discord_message_id")
        exact_receipt = bool(delivered and discord_message_id and discord_delivered_ts)
        sent += int(delivered)
        failures += int(send and not delivered)
        event = {
            "event_id": event_id,
            "trace_id": row.get("trace_id"),
            "bar_close_ts": candidate.get("bar_completed_at"),
            "scanner_emit_ts": row.get("scanner_emit_ts"),
            "decision_ts": row.get("recorded_at"),
            "dispatch_send_ts": attempted_at.isoformat().replace("+00:00", "Z"),
            "attempted_at": attempted_at.isoformat().replace("+00:00", "Z"),
            "discord_message_id": discord_message_id,
            "discord_delivered_ts": discord_delivered_ts,
            "ack_receipt_ts": result.get("ack_receipt_ts") or finished_at.isoformat().replace("+00:00", "Z"),
            "delivery_timestamp_semantics": "discord_message_timestamp" if exact_receipt else "http_ack_only" if delivered else "missing",
            "delivered_at": discord_delivered_ts if exact_receipt else None,
            "transport_seconds": (finished_at - attempted_at).total_seconds(),
            "decision_at": row.get('recorded_at'),
            "signal_available_at": candidate.get('bar_completed_at'),
            "candidate": candidate,
            "delivery_quality": check,
            "delivered": delivered,
            "attempts": result.get("attempts"),
            "error_class": result.get("error_class"),
            "decision": row.get("decision"),
            "symbol": ((row.get("candidate") or {}).get("symbol") if isinstance(row.get("candidate"), Mapping) else None),
            "execution_enabled": False,
            "can_submit_orders": False,
        }
        _append(event_path, event)
        pair_path = latency_pairs_path or (LATENCY_PAIRS_PATH if event_path == EVENT_PATH
                                           else event_path.with_name("latency_pairs.jsonl"))
        signal_at, delivered_at = quality.stamp(event.get("signal_available_at")), quality.stamp(event.get("delivered_at"))
        if event.get("trace_id") and exact_receipt and signal_at and delivered_at and delivered_at >= signal_at:
            _append(pair_path, {
                "trace_id": event["trace_id"], "event_id": event_id,
                "observed_at": event["ack_receipt_ts"],
                "baseline_latency_ms": None,
                "new_latency_ms": round((delivered_at - signal_at).total_seconds() * 1000, 3),
                "baseline_status": "no_defensible_parallel_baseline",
                "timestamps_synthesized": 0, "execution_enabled": False,
                "can_submit_orders": False,
            })
        events.append(event)
        if delivered:
            recent_setups[key] = finished_at.isoformat()
            delivered_ids.add(event_id)
            acknowledged_ids.add(event_id)
    if sent or stale_skipped or dashboard_only:
        _atomic(state_path, {
            "updated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "delivered_event_ids": sorted(delivered_ids)[-5000:],
            "stale_event_ids": sorted(stale_ids)[-5000:],
            "dashboard_only_event_ids": sorted(dashboard_only_ids)[-5000:],
            "recent_setups": {key: value for key, value in recent_setups.items() if quality.stamp(value) and now - quality.stamp(value) < SETUP_COOLDOWN},
        })
    report = {
        "provider": "governed_shadow_alert",
        "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "send_enabled": send,
        "candidate_decisions": len(rows),
        "delivery_attempts": attempts,
        "alerts_sent": sent,
        "delivery_failures": failures,
        "stale_skipped": stale_skipped,
        "dashboard_only": dashboard_only,
        "dashboard_only_reasons": dict(sorted(dashboard_only_reasons.items())),
        "pending_delivery": len([row for row in rows if str(row.get("event_id") or "") not in acknowledged_ids]),
        "events": events,
        "quality_checks": quality_checks,
        "selection_policy": "accepted_fresh_quote_revalidated_no_chase",
        "execution_enabled": False,
        "can_submit_orders": False,
    }
    _atomic(report_path, report)
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--send", action="store_true")
    args = parser.parse_args()
    report = run(_read(DECISION_PATH, {}), send=args.send)
    print(json.dumps({key: report[key] for key in ("candidate_decisions", "alerts_sent", "delivery_failures", "stale_skipped", "pending_delivery")}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Point-in-time catalyst-to-fast-tape correlation (shadow/manual review only).

This module is deliberately isolated from schedulers, Discord, brokers, and order
authority.  It joins verified primary-source events to completed fast-tape
transitions only when the source was observable before the completed bar.  Social
posts remain unverified nominations and can never become manual-review candidates.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence


SCHEMA_VERSION = 1
LIFECYCLE_STATES = frozenset({"WATCH", "ARMED", "CONFIRMED", "INVALIDATED"})
TAPE_TRANSITION_STATES = frozenset({"ARMED", "CONFIRMED", "INVALIDATED"})
PRIMARY_SOURCES = frozenset({
    "sec_edgar_latest_atom",
    "company_investor_relations",
    "company_ir",
    "company_press_release",
    "exchange_notice",
    "official_regulator",
})
SOCIAL_SOURCES = frozenset({"x", "twitter", "social", "social_media", "reddit", "stocktwits"})
DEFAULT_CORRELATION_WINDOW_SECONDS = 90 * 60
DEFAULT_TAPE_FRESHNESS_SECONDS = 180


def _authority() -> dict[str, bool]:
    return {"execution_enabled": False, "can_submit_orders": False}


def _utc(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        parsed = value
    else:
        text = str(value or "").strip()
        if not text or (len(text) == 10 and text[4:5] == "-" and text[7:8] == "-"):
            return None
        try:
            parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        except (TypeError, ValueError):
            return None
    if parsed.tzinfo is None:
        return None
    return parsed.astimezone(timezone.utc)


def _iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _finite(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _canonical_hash(value: Any) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _event_time(row: Mapping[str, Any]) -> datetime | None:
    for key in ("event_at", "event_ts", "accepted_at", "published_at", "released_at", "filed_at"):
        if parsed := _utc(row.get(key)):
            return parsed
    return None


def _observed_time(row: Mapping[str, Any]) -> datetime | None:
    for key in (
        "source_observed_at", "collector_first_seen_at", "collector_received_at",
        "observed_at", "ingested_at", "received_at", "_source_observed_at",
    ):
        if parsed := _utc(row.get(key)):
            return parsed
    return None


def _source_name(row: Mapping[str, Any]) -> str:
    return str(row.get("source") or row.get("source_type") or row.get("provider") or "").strip().lower()


def _is_social(row: Mapping[str, Any]) -> bool:
    source = _source_name(row)
    return source in SOCIAL_SOURCES or bool(row.get("social_input"))


def _verified_primary(row: Mapping[str, Any]) -> bool:
    source = _source_name(row)
    if source not in PRIMARY_SOURCES or not str(row.get("source_url") or "").strip():
        return False
    verification = str(row.get("verification_status") or "").strip().lower()
    explicitly_verified = row.get("verified") is True or verification in {
        "verified", "primary_verified", "primary_index_verified",
    }
    return explicitly_verified


def _catalyst_id(row: Mapping[str, Any], event_at: datetime | None) -> str:
    supplied = str(row.get("event_id") or row.get("catalyst_id") or "").strip()
    if supplied:
        return supplied
    identity = {
        "symbol": str(row.get("symbol") or "").upper(),
        "source": _source_name(row),
        "source_url": str(row.get("source_url") or ""),
        "event_at": _iso(event_at) if event_at else None,
        "event_type": row.get("event_type"),
    }
    return "cat_" + _canonical_hash(identity)[:20]


def normalize_catalyst(row: Mapping[str, Any]) -> dict[str, Any]:
    event_at = _event_time(row)
    observed_at = _observed_time(row)
    social = _is_social(row)
    verified = _verified_primary(row) and event_at is not None and observed_at is not None
    blockers: list[str] = []
    if social:
        blockers.append("unverified_social_nomination_only")
    elif _source_name(row) not in PRIMARY_SOURCES:
        blockers.append("source_is_not_an_approved_primary_source")
    elif not str(row.get("source_url") or "").strip():
        blockers.append("primary_source_url_missing")
    elif not _verified_primary(row):
        blockers.append("primary_source_not_verified")
    if event_at is None:
        blockers.append("event_timestamp_missing_or_not_timezone_aware")
    if observed_at is None:
        blockers.append("source_observed_timestamp_missing_or_not_timezone_aware")
    if event_at and observed_at and observed_at < event_at:
        blockers.append("source_observed_before_event_timestamp")
        verified = False
    return {
        "catalyst_id": _catalyst_id(row, event_at),
        "symbol": str(row.get("symbol") or "").strip().upper(),
        "event_type": row.get("event_type"),
        "headline": row.get("headline") or row.get("title"),
        "source": _source_name(row) or None,
        "source_url": row.get("source_url"),
        "event_at": _iso(event_at) if event_at else None,
        "source_observed_at": _iso(observed_at) if observed_at else None,
        "source_latency_seconds": round((observed_at - event_at).total_seconds(), 3) if event_at and observed_at else None,
        "verified_primary": verified,
        "nomination_only": social or not verified,
        "blockers": blockers,
        **_authority(),
    }


def normalize_tape_transition(row: Mapping[str, Any]) -> dict[str, Any] | None:
    state = str(row.get("state") or "").upper()
    bar_at = _utc(row.get("bar_completed_at"))
    detected_at = _utc(row.get("detected_at"))
    completed = row.get("completed_bar") is True or bool(bar_at)
    if (
        state not in TAPE_TRANSITION_STATES
        or row.get("transition") is not True
        or str(row.get("data_status") or "").lower() not in {"ok", "complete", "completed"}
        or not completed
        or bar_at is None
        or detected_at is None
        or detected_at < bar_at
    ):
        return None
    supplied = str(row.get("transition_id") or "").strip()
    identity = {
        "symbol": str(row.get("symbol") or "").upper(),
        "state": state,
        "direction": str(row.get("direction") or "NONE").upper(),
        "bar_completed_at": _iso(bar_at),
        "reason": row.get("reason"),
    }
    return {
        "tape_transition_id": supplied or "tape_" + _canonical_hash(identity)[:20],
        "symbol": identity["symbol"],
        "state": state,
        "direction": identity["direction"],
        "reason": row.get("reason"),
        "bar_completed_at": identity["bar_completed_at"],
        "detected_at": _iso(detected_at),
        "tape_detection_latency_seconds": round((detected_at - bar_at).total_seconds(), 3),
        "data_status": "ok",
        **_authority(),
    }


def _plan_time(row: Mapping[str, Any]) -> datetime | None:
    for key in ("as_of", "generated_at", "created_at", "bar_completed_at", "_source_observed_at"):
        if parsed := _utc(row.get(key)):
            return parsed
    return None


def _plan_for(
    plans: Sequence[Mapping[str, Any]], symbol: str, direction: str, *, available_at: datetime
) -> tuple[dict[str, Any] | None, str | None]:
    eligible: list[tuple[datetime, Mapping[str, Any]]] = []
    for row in plans:
        if str(row.get("symbol") or "").upper() != symbol:
            continue
        normalized_direction = str(row.get("direction") or "").upper()
        if normalized_direction not in {direction, "BULLISH" if direction == "LONG" else "BEARISH"}:
            continue
        as_of = _plan_time(row)
        if as_of is None or as_of > available_at:
            continue
        if row.get("execution_enabled") is True or row.get("can_submit_orders") is True:
            continue
        eligible.append((as_of, row))
    if not eligible:
        return None, "deterministic_plan_missing_or_not_point_in_time"
    as_of, source = max(eligible, key=lambda item: item[0])
    raw_plan = source.get("plan") if isinstance(source.get("plan"), Mapping) else source
    assert isinstance(raw_plan, Mapping)
    if raw_plan.get("execution_enabled") is True or raw_plan.get("can_submit_orders") is True:
        return None, "deterministic_plan_has_order_authority"
    copied = {
        "plan_id": source.get("plan_id") or source.get("candidate_id"),
        "plan_as_of": _iso(as_of),
        "entry_zone": raw_plan.get("entry_zone"),
        "max_chase_price": raw_plan.get("max_chase_price", raw_plan.get("max_chase")),
        "stop": raw_plan.get("stop"),
        "targets": raw_plan.get("targets"),
        "expires_at": raw_plan.get("expires_at"),
        "copied_from_existing_deterministic_plan": True,
    }
    expiry = _utc(copied["expires_at"]) if copied["expires_at"] else None
    zone = copied["entry_zone"] if isinstance(copied["entry_zone"], Mapping) else {}
    targets = copied["targets"] if isinstance(copied["targets"], Sequence) and not isinstance(copied["targets"], (str, bytes)) else []
    valid_targets = bool(targets) and all(
        _finite(value.get("price")) is not None if isinstance(value, Mapping) else _finite(value) is not None
        for value in targets
    )
    complete_levels = bool(
        _finite(zone.get("low")) is not None
        and _finite(zone.get("high")) is not None
        and _finite(copied["max_chase_price"]) is not None
        and _finite(copied["stop"]) is not None
        and valid_targets
    )
    if not complete_levels:
        return copied, "deterministic_plan_levels_incomplete"
    if copied["expires_at"] and (expiry is None or expiry <= available_at):
        return copied, "deterministic_plan_expired_or_expiry_invalid"
    return copied, None


def _transition_id(catalyst_id: str, tape_id: str | None, state: str) -> str:
    return "ct_" + _canonical_hash({"catalyst_id": catalyst_id, "tape_transition_id": tape_id, "state": state})[:24]


def _watch_row(catalyst: Mapping[str, Any], *, reason: str, existing_ids: set[str]) -> dict[str, Any]:
    transition_id = _transition_id(str(catalyst["catalyst_id"]), None, "WATCH")
    return {
        "transition_id": transition_id,
        "is_new": transition_id not in existing_ids,
        "state": "WATCH",
        "direction": "NONE",
        "symbol": catalyst.get("symbol"),
        "reason": reason,
        "catalyst": dict(catalyst),
        "tape": None,
        "deterministic_plan": None,
        "event_to_bar_seconds": None,
        "source_to_bar_seconds": None,
        "source_to_decision_seconds": None,
        "actionability": "nomination_only" if catalyst.get("nomination_only") else "watch_only",
        "actionable_for_manual_review": False,
        "data_status": "unverified" if catalyst.get("nomination_only") else "unavailable",
        "blockers": list(catalyst.get("blockers") or []) + [reason],
        "review_instruction": "SHADOW ONLY — manual review required; no order may be submitted.",
        **_authority(),
    }


def build_report(
    catalysts: Iterable[Mapping[str, Any]],
    tape_transitions: Iterable[Mapping[str, Any]],
    plans: Iterable[Mapping[str, Any]],
    *,
    now: datetime | None = None,
    existing_transition_ids: Iterable[str] = (),
    correlation_window_seconds: int = DEFAULT_CORRELATION_WINDOW_SECONDS,
    tape_freshness_seconds: int = DEFAULT_TAPE_FRESHNESS_SECONDS,
) -> dict[str, Any]:
    """Build a causal correlation report without sending alerts or placing orders."""
    clock = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    existing_ids = {str(value) for value in existing_transition_ids}
    catalyst_rows = [normalize_catalyst(row) for row in catalysts if isinstance(row, Mapping)]
    tape_rows = [value for row in tape_transitions if isinstance(row, Mapping) and (value := normalize_tape_transition(row))]
    plan_rows = [row for row in plans if isinstance(row, Mapping)]
    output: list[dict[str, Any]] = []
    rejected_tape = 0

    for catalyst in catalyst_rows:
        event_at = _utc(catalyst.get("event_at"))
        observed_at = _utc(catalyst.get("source_observed_at"))
        if not catalyst["verified_primary"]:
            output.append(_watch_row(catalyst, reason="unverified_nomination_cannot_join_actionable_tape", existing_ids=existing_ids))
            continue
        assert event_at is not None and observed_at is not None
        matches: list[dict[str, Any]] = []
        for tape in tape_rows:
            if tape["symbol"] != catalyst["symbol"]:
                continue
            bar_at = _utc(tape["bar_completed_at"])
            detected_at = _utc(tape["detected_at"])
            assert bar_at is not None and detected_at is not None
            if observed_at > bar_at or event_at > bar_at:
                rejected_tape += 1
                continue
            if (bar_at - observed_at).total_seconds() > correlation_window_seconds:
                continue
            if (clock - detected_at).total_seconds() > tape_freshness_seconds or detected_at > clock:
                rejected_tape += 1
                continue
            matches.append(tape)
        if not matches:
            output.append(_watch_row(catalyst, reason="no_fresh_completed_tape_transition_after_source_observation", existing_ids=existing_ids))
            continue
        for tape in sorted(matches, key=lambda row: (str(row["bar_completed_at"]), str(row["tape_transition_id"]))):
            bar_at = _utc(tape["bar_completed_at"])
            detected_at = _utc(tape["detected_at"])
            assert bar_at is not None and detected_at is not None
            state = str(tape["state"])
            transition_id = _transition_id(str(catalyst["catalyst_id"]), str(tape["tape_transition_id"]), state)
            plan, plan_blocker = _plan_for(plan_rows, str(catalyst["symbol"]), str(tape["direction"]), available_at=bar_at)
            blockers = [plan_blocker] if plan_blocker else []
            actionability = "stand_aside"
            manual_candidate = False
            if state == "ARMED":
                actionability = "prepare_only"
            elif state == "CONFIRMED" and not plan_blocker:
                actionability = "manual_review_candidate"
                manual_candidate = True
            elif state == "WATCH":
                actionability = "watch_only"
            output.append({
                "transition_id": transition_id,
                "is_new": transition_id not in existing_ids,
                "state": state,
                "direction": tape["direction"],
                "symbol": catalyst["symbol"],
                "reason": "verified_primary_catalyst_correlated_to_completed_fast_tape_transition",
                "catalyst": catalyst,
                "tape": tape,
                "deterministic_plan": plan,
                "event_to_bar_seconds": round((bar_at - event_at).total_seconds(), 3),
                "source_to_bar_seconds": round((bar_at - observed_at).total_seconds(), 3),
                "source_to_decision_seconds": round((detected_at - observed_at).total_seconds(), 3),
                "actionability": actionability,
                "actionable_for_manual_review": manual_candidate,
                "data_status": "ok",
                "blockers": blockers,
                "review_instruction": "SHADOW ONLY — manual review required; no order may be submitted.",
                **_authority(),
            })

    invalid_inputs = sum(bool(row["catalyst"].get("blockers")) for row in output)
    status = "ok"
    if not catalyst_rows:
        status = "missing_catalyst_input"
    elif not tape_rows:
        status = "missing_or_invalid_tape_input"
    elif invalid_inputs or rejected_tape:
        status = "degraded"
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at": _iso(clock),
        "status": status,
        "mode": "shadow_manual_review_only",
        "transitions": output,
        "new_transition_count": sum(row["is_new"] for row in output),
        "state_counts": {state: sum(row["state"] == state for row in output) for state in sorted(LIFECYCLE_STATES)},
        "input_counts": {"catalysts": len(catalyst_rows), "valid_completed_tape_transitions": len(tape_rows), "plans": len(plan_rows)},
        "point_in_time_rejections": rejected_tape,
        "warnings": [
            "Social/X inputs are unverified nomination-only and never actionable.",
            "Entry, chase, stop, and target levels are copied only from an existing point-in-time deterministic plan.",
            "No scheduler, Discord sender, broker import, or order path is present in this module.",
        ],
        **_authority(),
    }


def format_shadow_card(row: Mapping[str, Any]) -> str:
    """Format a human review card; this function never sends it anywhere."""
    symbol = str(row.get("symbol") or "UNKNOWN")
    state = str(row.get("state") or "WATCH")
    direction = str(row.get("direction") or "NONE")
    plan = row.get("deterministic_plan") if isinstance(row.get("deterministic_plan"), Mapping) else {}
    return "\n".join([
        f"SHADOW / MANUAL REVIEW — CATALYST {state} | {symbol} | {direction}",
        f"Actionability: {row.get('actionability', 'stand_aside')}",
        f"Entry zone: {plan.get('entry_zone')}",
        f"Max chase: {plan.get('max_chase_price')}",
        f"Stop: {plan.get('stop')}",
        f"Targets: {plan.get('targets')}",
        "No order will be placed. Verify the primary source and chart manually.",
    ])


def _read_json(path: Path | None) -> dict[str, Any]:
    if path is None:
        return {}
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def _rows(payload: Mapping[str, Any], keys: Sequence[str]) -> list[dict[str, Any]]:
    for key in keys:
        values = payload.get(key)
        if isinstance(values, list):
            observed = payload.get("generated_at")
            return [
                {**dict(row), "_source_observed_at": row.get("source_observed_at") or observed}
                for row in values if isinstance(row, Mapping)
            ]
    return []


def _atomic_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(dict(payload), indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(path)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--catalysts", type=Path, required=True)
    parser.add_argument("--tape", type=Path, required=True)
    parser.add_argument("--plans", type=Path, required=True)
    parser.add_argument("--prior-report", type=Path)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--print", action="store_true", dest="print_report")
    args = parser.parse_args()
    catalyst_payload = _read_json(args.catalysts)
    tape_payload = _read_json(args.tape)
    plan_payload = _read_json(args.plans)
    prior_payload = _read_json(args.prior_report)
    report = build_report(
        _rows(catalyst_payload, ("catalysts", "events", "nominations")),
        _rows(tape_payload, ("observations", "transitions", "events")),
        _rows(plan_payload, ("plans", "candidates", "ranked_candidates", "signals")),
        existing_transition_ids=[str(row.get("transition_id")) for row in prior_payload.get("transitions") or [] if isinstance(row, Mapping)],
    )
    _atomic_json(args.out, report)
    if args.print_report:
        print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

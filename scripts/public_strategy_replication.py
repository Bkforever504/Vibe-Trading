#!/usr/bin/env python3
"""Build a tamper-evident, research-only public strategy replication league.

The pipeline snapshots already-normalized verified-trader signals, freezes the
rules attributed to each public strategy, and joins independent executable
OPRA reconstructions. It cannot place orders or promote a strategy into paper
or production trading.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from strategies.spy_spx_execution_policy import executable_ev_lower_bound

VIBE_HOME = Path.home() / ".vibe-trading"
DEFAULT_LEDGER = ROOT / "data" / "public_strategy_replication_log.jsonl"
DEFAULT_REPORT = VIBE_HOME / "reports" / "public-strategy-replication-league.json"

SCHEMA_VERSION = "1.0.0"
GENESIS_HASH = "GENESIS"
ALLOWED_INSTRUMENTS = {"SPY", "SPX", "XSP"}
ALLOWED_OPERATORS = {"eq", "ne", "gt", "gte", "lt", "lte", "crosses_above", "crosses_below"}
REQUIRED_RULE_FIELDS = (
    "rule_id",
    "version",
    "frozen_at",
    "setup_family",
    "source_traders",
    "instruments",
    "session_windows_et",
    "entry_predicates",
    "contract_selection",
    "entry_order",
    "stop_policy",
    "target_policy",
    "time_exit",
    "no_trade_conditions",
    "regime_filters",
    "regime_definition",
    "position_sizing",
)


class ReplicationError(RuntimeError):
    """A fail-closed replication input or integrity error."""


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _parse_timestamp(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return None
    return parsed.astimezone(timezone.utc)


def _number(value: Any) -> float | None:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def _canonical_bytes(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")


def _sha256(value: Any) -> str:
    return hashlib.sha256(_canonical_bytes(value)).hexdigest()


def _without_integrity(event: Mapping[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in event.items() if key != "integrity"}


def _stable_event_content(event: Mapping[str, Any]) -> dict[str, Any]:
    return {
        key: value
        for key, value in event.items()
        if key not in {"integrity", "ingested_at"}
    }


def _load_json_rows(path: Path) -> list[dict[str, Any]]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ReplicationError(f"unable to read JSON input {path}: {exc}") from exc
    if isinstance(payload, dict):
        for key in ("rules", "records", "outcomes", "manifests"):
            if isinstance(payload.get(key), list):
                payload = payload[key]
                break
        else:
            payload = [payload]
    if not isinstance(payload, list) or any(not isinstance(row, dict) for row in payload):
        raise ReplicationError("input must be a JSON object or list of objects")
    return [dict(row) for row in payload]


def load_jsonl(path: Path, *, tolerate_invalid: bool = False) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    records: list[dict[str, Any]] = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8-sig").splitlines(), 1):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError as exc:
            if tolerate_invalid:
                continue
            raise ReplicationError(f"invalid JSONL at {path}:{line_number}: {exc}") from exc
        if not isinstance(row, dict):
            if tolerate_invalid:
                continue
            raise ReplicationError(f"non-object JSONL record at {path}:{line_number}")
        records.append(row)
    return records


def verify_ledger(events: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    previous_hash = GENESIS_HASH
    count = 0
    for expected_sequence, event in enumerate(events, 1):
        count += 1
        integrity = event.get("integrity")
        if not isinstance(integrity, Mapping):
            raise ReplicationError(f"ledger event {expected_sequence} has no integrity envelope")
        sequence = integrity.get("sequence")
        prior = integrity.get("previous_event_hash")
        claimed = integrity.get("event_hash")
        if sequence != expected_sequence:
            raise ReplicationError(
                f"ledger sequence mismatch at {expected_sequence}: found {sequence}"
            )
        if prior != previous_hash:
            raise ReplicationError(f"ledger chain break at sequence {expected_sequence}")
        expected_hash = _sha256(
            {
                "sequence": expected_sequence,
                "previous_event_hash": previous_hash,
                "event": _without_integrity(event),
            }
        )
        if claimed != expected_hash:
            raise ReplicationError(f"ledger tamper detected at sequence {expected_sequence}")
        previous_hash = expected_hash
    return {
        "valid": True,
        "event_count": count,
        "head_hash": previous_hash,
        "execution_enabled": False,
    }


def load_ledger(path: Path = DEFAULT_LEDGER) -> list[dict[str, Any]]:
    events = load_jsonl(path)
    verify_ledger(events)
    return events


def append_events(
    events: Iterable[Mapping[str, Any]], *, path: Path = DEFAULT_LEDGER
) -> dict[str, Any]:
    existing = load_ledger(path)
    by_id = {str(row.get("event_id")): row for row in existing if row.get("event_id")}
    previous_hash = (
        str(existing[-1]["integrity"]["event_hash"]) if existing else GENESIS_HASH
    )
    accepted: list[dict[str, Any]] = []
    duplicates = 0
    for incoming in events:
        event = dict(incoming)
        event.setdefault("schema_version", SCHEMA_VERSION)
        event.setdefault("ingested_at", _now_iso())
        event.setdefault("execution_enabled", False)
        event.setdefault("can_submit_orders", False)
        event.setdefault("promotion_eligible", False)
        event_id = str(event.get("event_id") or _sha256(event)[:24])
        event["event_id"] = event_id
        prior_event = by_id.get(event_id)
        if prior_event:
            if _stable_event_content(prior_event) != _stable_event_content(event):
                raise ReplicationError(f"event_id collision with different payload: {event_id}")
            duplicates += 1
            continue
        sequence = len(existing) + len(accepted) + 1
        event_hash = _sha256(
            {
                "sequence": sequence,
                "previous_event_hash": previous_hash,
                "event": event,
            }
        )
        event["integrity"] = {
            "sequence": sequence,
            "previous_event_hash": previous_hash,
            "event_hash": event_hash,
        }
        previous_hash = event_hash
        by_id[event_id] = event
        accepted.append(event)
    if accepted:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            for event in accepted:
                handle.write(json.dumps(event, sort_keys=True, separators=(",", ":")) + "\n")
    return {
        "accepted": len(accepted),
        "duplicates": duplicates,
        "head_hash": previous_hash,
        "execution_enabled": False,
        "can_submit_orders": False,
    }


def _validate_predicates(name: str, predicates: Any, *, allow_empty: bool) -> list[dict[str, Any]]:
    if not isinstance(predicates, list) or (not allow_empty and not predicates):
        raise ReplicationError(f"{name} must be {'a' if allow_empty else 'a non-empty'} list")
    normalized: list[dict[str, Any]] = []
    for index, predicate in enumerate(predicates):
        if not isinstance(predicate, Mapping):
            raise ReplicationError(f"{name}[{index}] must be an object")
        left = str(predicate.get("left") or "").strip()
        operator = str(predicate.get("operator") or "").strip()
        has_right = predicate.get("right") not in (None, "")
        if not left or operator not in ALLOWED_OPERATORS or not has_right:
            raise ReplicationError(f"{name}[{index}] is not deterministic")
        normalized.append(dict(predicate))
    return normalized


def normalize_rule(raw: Mapping[str, Any]) -> dict[str, Any]:
    missing = [field for field in REQUIRED_RULE_FIELDS if raw.get(field) in (None, "")]
    if missing:
        raise ReplicationError(f"rule missing required fields: {', '.join(missing)}")
    rule_id = str(raw["rule_id"]).strip().lower()
    if not re.fullmatch(r"[a-z0-9][a-z0-9_.-]{2,63}", rule_id):
        raise ReplicationError("rule_id must be a stable lowercase identifier")
    version = str(raw["version"]).strip()
    if not version or len(version) > 32:
        raise ReplicationError("rule version is invalid")
    frozen_at = _parse_timestamp(raw["frozen_at"])
    if frozen_at is None:
        raise ReplicationError("frozen_at must be timezone-aware")
    if not isinstance(raw["source_traders"], list):
        raise ReplicationError("source_traders must be a list")
    source_traders = sorted({str(value).strip() for value in raw["source_traders"] if str(value).strip()})
    if not source_traders:
        raise ReplicationError("source_traders cannot be empty")
    if not isinstance(raw["instruments"], list):
        raise ReplicationError("instruments must be a list")
    instruments = sorted({str(value).upper() for value in raw["instruments"]})
    if not instruments or not set(instruments).issubset(ALLOWED_INSTRUMENTS):
        raise ReplicationError("instruments must be limited to SPY, SPX, or XSP")
    windows = raw["session_windows_et"]
    if not isinstance(windows, list) or not windows:
        raise ReplicationError("session_windows_et must be a non-empty list")
    for window in windows:
        if not isinstance(window, Mapping) or not re.fullmatch(r"\d{2}:\d{2}", str(window.get("start") or "")) or not re.fullmatch(r"\d{2}:\d{2}", str(window.get("end") or "")):
            raise ReplicationError("each session window requires HH:MM start and end")
    contract = dict(raw["contract_selection"])
    if contract.get("quote_authority") != "opra":
        raise ReplicationError("contract_selection.quote_authority must be opra")
    for field in ("dte_min", "dte_max", "max_quote_age_seconds", "max_spread_pct"):
        if _number(contract.get(field)) is None:
            raise ReplicationError(f"contract_selection.{field} is required")
    entry_order = dict(raw["entry_order"])
    if entry_order.get("type") != "limit" or entry_order.get("market_fallback") is not False:
        raise ReplicationError("entry_order must be limit-only with market_fallback false")
    sizing = dict(raw["position_sizing"])
    risk_pct = _number(sizing.get("max_account_risk_pct"))
    if risk_pct is None or risk_pct <= 0 or risk_pct > 1.0:
        raise ReplicationError("position_sizing.max_account_risk_pct must be in (0, 1]")
    for field in ("stop_policy", "target_policy", "time_exit"):
        if not isinstance(raw[field], Mapping) or not raw[field]:
            raise ReplicationError(f"{field} must be a non-empty deterministic object")
    if not isinstance(raw["regime_definition"], Mapping) or not raw["regime_definition"]:
        raise ReplicationError("regime_definition must be a non-empty deterministic object")
    regime_definition = dict(raw["regime_definition"])
    regime_definition.pop("definition_hash", None)
    regime_definition["definition_hash"] = _sha256(regime_definition)
    normalized = {
        **dict(raw),
        "rule_id": rule_id,
        "version": version,
        "frozen_at": frozen_at.isoformat().replace("+00:00", "Z"),
        "source_traders": source_traders,
        "instruments": instruments,
        "entry_predicates": _validate_predicates(
            "entry_predicates", raw["entry_predicates"], allow_empty=False
        ),
        "no_trade_conditions": _validate_predicates(
            "no_trade_conditions", raw["no_trade_conditions"], allow_empty=True
        ),
        "regime_filters": _validate_predicates(
            "regime_filters", raw["regime_filters"], allow_empty=True
        ),
        "contract_selection": contract,
        "entry_order": entry_order,
        "regime_definition": regime_definition,
        "position_sizing": sizing,
        "mode": "research_only",
        "execution_enabled": False,
        "can_submit_orders": False,
        "automatic_promotion": False,
    }
    normalized.pop("rule_hash", None)
    normalized["rule_hash"] = _sha256(normalized)
    return normalized


def register_rules(
    rules: Iterable[Mapping[str, Any]], *, ledger_path: Path = DEFAULT_LEDGER
) -> dict[str, Any]:
    existing = load_ledger(ledger_path)
    registered = {
        (row["rule"]["rule_id"], row["rule"]["version"]): row["rule"]
        for row in existing
        if row.get("event_type") == "rule_registered"
    }
    events: list[dict[str, Any]] = []
    for raw in rules:
        rule = normalize_rule(raw)
        key = (rule["rule_id"], rule["version"])
        prior = registered.get(key)
        if prior and prior.get("rule_hash") != rule["rule_hash"]:
            raise ReplicationError(f"frozen rule mutation rejected: {key[0]}@{key[1]}")
        events.append(
            {
                "event_id": f"rule:{rule['rule_id']}:{rule['version']}:{rule['rule_hash'][:16]}",
                "event_type": "rule_registered",
                "rule": rule,
            }
        )
    return append_events(events, path=ledger_path)


def _registered_rule(
    events: Iterable[Mapping[str, Any]], rule_id: str, version: str
) -> dict[str, Any]:
    matches = [
        dict(row["rule"])
        for row in events
        if row.get("event_type") == "rule_registered"
        and row.get("rule", {}).get("rule_id") == rule_id
        and row.get("rule", {}).get("version") == version
    ]
    if len(matches) != 1:
        raise ReplicationError(f"exactly one frozen rule required for {rule_id}@{version}")
    return matches[0]


def snapshot_verified_signals(
    records: Iterable[Mapping[str, Any]],
    *,
    rule_id: str,
    version: str,
    ledger_path: Path = DEFAULT_LEDGER,
) -> dict[str, Any]:
    ledger = load_ledger(ledger_path)
    rule = _registered_rule(ledger, rule_id, version)
    events: list[dict[str, Any]] = []
    rejected = 0
    for record in records:
        safety = record.get("safety") or {}
        if (
            record.get("event", {}).get("type") != "signal"
            or safety.get("quarantined")
            or not safety.get("replay_eligible")
        ):
            rejected += 1
            continue
        source_timestamp = _parse_timestamp(record.get("event", {}).get("source_timestamp"))
        observed_at = _parse_timestamp(record.get("event", {}).get("observed_at"))
        if source_timestamp is None or observed_at is None or source_timestamp > observed_at:
            rejected += 1
            continue
        trader = str(record.get("trader", {}).get("id") or record.get("trader", {}).get("handle") or "")
        if trader not in rule["source_traders"]:
            rejected += 1
            continue
        instrument = dict(record.get("instrument") or {})
        symbol = str(instrument.get("underlying") or "").upper()
        if not symbol:
            raw_symbol = str(instrument.get("symbol") or instrument.get("option_symbol") or "").upper()
            option_match = re.match(r"^(SPY|SPX|XSP)\d", raw_symbol)
            symbol = option_match.group(1) if option_match else raw_symbol
        if symbol not in rule["instruments"]:
            rejected += 1
            continue
        market_join = record.get("evidence", {}).get("market_join") or {}
        market_timestamp = _parse_timestamp(market_join.get("timestamp"))
        join_delay = (
            (market_timestamp - observed_at).total_seconds()
            if market_timestamp is not None and market_timestamp >= observed_at
            else None
        )
        market_join_valid = bool(
            market_join.get("available")
            and market_join.get("price") is not None
            and join_delay is not None
            and join_delay <= float(rule["contract_selection"]["max_quote_age_seconds"])
        )
        rule_frozen_at = _parse_timestamp(rule["frozen_at"])
        forward_eligible = bool(rule_frozen_at and source_timestamp >= rule_frozen_at)
        source_fingerprint = str(record.get("fingerprint") or record.get("event_id") or "")
        if not source_fingerprint:
            rejected += 1
            continue
        events.append(
            {
                "event_id": f"signal:{_sha256({'source': source_fingerprint, 'rule': rule['rule_hash']})[:24]}",
                "event_type": "signal_snapshot",
                "rule_ref": {
                    "rule_id": rule["rule_id"],
                    "version": rule["version"],
                    "rule_hash": rule["rule_hash"],
                },
                "source": {
                    "type": record.get("source", {}).get("type"),
                    "id": record.get("source", {}).get("id"),
                    "external_id": record.get("source", {}).get("external_id"),
                    "fingerprint": source_fingerprint,
                    "url": record.get("source", {}).get("url"),
                },
                "trader": trader,
                "source_timestamp": source_timestamp.isoformat().replace("+00:00", "Z"),
                "observed_at": observed_at.isoformat().replace("+00:00", "Z"),
                "observation_latency_seconds": (observed_at - source_timestamp).total_seconds(),
                "instrument": instrument,
                "signal": {
                    "action": record.get("trade", {}).get("action"),
                    "direction": record.get("trade", {}).get("direction"),
                    "leader_price": record.get("trade", {}).get("price"),
                    "stop_price": record.get("trade", {}).get("stop_price"),
                    "target_price": record.get("trade", {}).get("target_price"),
                },
                "point_in_time_market_join": {
                    "price": market_join.get("price"),
                    "timestamp": market_join.get("timestamp"),
                    "source": market_join.get("source"),
                    "delay_seconds": join_delay,
                    "valid": market_join_valid,
                },
                "pre_entry_captured": True,
                "forward_eligible": forward_eligible,
                "reconstruction_ready": market_join_valid and forward_eligible,
            }
        )
    result = append_events(events, path=ledger_path)
    result["source_records_rejected"] = rejected
    return result


def normalize_coverage_manifest(raw: Mapping[str, Any]) -> dict[str, Any]:
    required = (
        "source_type",
        "source_id",
        "trader",
        "coverage_start",
        "coverage_end",
        "capture_method",
        "poll_interval_seconds",
        "captured_record_count",
        "capture_complete",
        "deletions_tracked",
        "archive_sha256",
    )
    missing = [field for field in required if raw.get(field) in (None, "")]
    if missing:
        raise ReplicationError(f"coverage manifest missing fields: {', '.join(missing)}")
    start = _parse_timestamp(raw["coverage_start"])
    end = _parse_timestamp(raw["coverage_end"])
    archive_hash = str(raw["archive_sha256"]).lower()
    if start is None or end is None or start >= end:
        raise ReplicationError("coverage manifest range is invalid")
    if not re.fullmatch(r"[0-9a-f]{64}", archive_hash):
        raise ReplicationError("coverage archive_sha256 is invalid")
    complete = raw["capture_complete"] is True and raw["deletions_tracked"] is True
    if not complete:
        raise ReplicationError("coverage must attest complete capture and deletion tracking")
    poll = _number(raw["poll_interval_seconds"])
    count = _number(raw["captured_record_count"])
    if poll is None or poll <= 0 or poll > 300 or count is None or count < 0 or not count.is_integer():
        raise ReplicationError("coverage poll interval or record count is invalid")
    manifest = {
        **dict(raw),
        "coverage_start": start.isoformat().replace("+00:00", "Z"),
        "coverage_end": end.isoformat().replace("+00:00", "Z"),
        "archive_sha256": archive_hash,
        "poll_interval_seconds": poll,
        "captured_record_count": int(count),
        "verified_for_research": True,
    }
    return manifest


def import_coverage_manifests(
    manifests: Iterable[Mapping[str, Any]], *, ledger_path: Path = DEFAULT_LEDGER
) -> dict[str, Any]:
    events = []
    for raw in manifests:
        manifest = normalize_coverage_manifest(raw)
        identity = {
            key: manifest[key]
            for key in ("source_type", "source_id", "trader", "coverage_start", "coverage_end", "archive_sha256")
        }
        events.append(
            {
                "event_id": f"coverage:{_sha256(identity)[:24]}",
                "event_type": "source_coverage_manifest",
                "manifest": manifest,
            }
        )
    return append_events(events, path=ledger_path)


def _signal_events(events: Iterable[Mapping[str, Any]]) -> dict[str, dict[str, Any]]:
    return {
        str(row["event_id"]): dict(row)
        for row in events
        if row.get("event_type") == "signal_snapshot"
    }


def normalize_replay_outcome(
    raw: Mapping[str, Any], *, signal: Mapping[str, Any], rule: Mapping[str, Any]
) -> dict[str, Any]:
    if not signal.get("reconstruction_ready") or not signal.get("forward_eligible"):
        raise ReplicationError("signal is not eligible for forward executable reconstruction")
    if str(raw.get("quote_authority") or "").lower() != "opra":
        raise ReplicationError("OPRA quote authority is required")
    if str(raw.get("quote_method") or "") not in {
        "opra_aggregate_executable_nbbo",
        "opra_leg_nbbo_executable",
    }:
        raise ReplicationError("an executable OPRA quote method is required")
    if raw.get("rule_hash") != rule["rule_hash"]:
        raise ReplicationError("outcome rule_hash does not match the frozen rule")
    if raw.get("regime_definition_hash") != rule["regime_definition"]["definition_hash"]:
        raise ReplicationError("outcome regime definition does not match the frozen rule")
    position_side = str(raw.get("position_side") or "")
    if position_side not in {"long_premium", "short_premium"}:
        raise ReplicationError("position_side must be long_premium or short_premium")
    observed_at = _parse_timestamp(signal.get("observed_at"))
    entry_at = _parse_timestamp(raw.get("entry_quote_timestamp"))
    exit_at = _parse_timestamp(raw.get("exit_quote_timestamp"))
    if observed_at is None or entry_at is None or exit_at is None:
        raise ReplicationError("signal, entry, and exit timestamps must be timezone-aware")
    join_delay = (entry_at - observed_at).total_seconds()
    if join_delay < 0 or join_delay > float(rule["contract_selection"]["max_quote_age_seconds"]):
        raise ReplicationError("entry quote is not a valid point-in-time post-observation join")
    if exit_at <= entry_at:
        raise ReplicationError("exit quote must follow entry quote")
    entry_value = _number(raw.get("entry_executable_value"))
    exit_value = _number(raw.get("exit_executable_value"))
    entry_mid = _number(raw.get("entry_mid_value"))
    exit_mid = _number(raw.get("exit_mid_value"))
    quantity = _number(raw.get("quantity"))
    multiplier = _number(raw.get("multiplier"))
    capital_at_risk = _number(raw.get("capital_at_risk_dollars"))
    fees = _number(raw.get("fees_dollars"))
    slippage = _number(raw.get("additional_slippage_dollars"))
    numeric = (entry_value, exit_value, entry_mid, exit_mid, quantity, multiplier, capital_at_risk, fees, slippage)
    if any(value is None for value in numeric):
        raise ReplicationError("outcome executable values, mids, size, risk, fees, and slippage are required")
    if min(entry_value, quantity, multiplier, capital_at_risk) <= 0 or min(exit_value, entry_mid, exit_mid) < 0:
        raise ReplicationError("entry, size, multiplier, and risk must be positive; exit values cannot be negative")
    if fees < 0 or slippage < 0:
        raise ReplicationError("fees and slippage cannot be negative")
    if position_side == "long_premium" and (
        entry_value < entry_mid or exit_value > exit_mid
    ):
        raise ReplicationError("long-premium executable values are on the wrong NBBO side")
    if position_side == "short_premium" and (
        entry_value > entry_mid or exit_value < exit_mid
    ):
        raise ReplicationError("short-premium executable values are on the wrong NBBO side")
    entry_full_spread_pct = 200.0 * abs(entry_value - entry_mid) / entry_mid
    if entry_full_spread_pct > float(rule["contract_selection"]["max_spread_pct"]) + 1e-9:
        raise ReplicationError("entry executable spread exceeds the frozen liquidity cap")
    direction = 1.0 if position_side == "long_premium" else -1.0
    gross_pnl = (exit_value - entry_value) * direction * quantity * multiplier
    spread_friction = (
        abs(entry_value - entry_mid) + abs(exit_value - exit_mid)
    ) * quantity * multiplier
    net_pnl = gross_pnl - fees - slippage
    doubled_cost_pnl = net_pnl - fees - slippage - spread_friction
    instrument = str(raw.get("instrument") or "").strip().upper()
    if not instrument:
        raise ReplicationError("exact reconstructed option instrument is required")
    regime = str(raw.get("regime") or "unknown").strip().lower()
    if not regime or regime == "unknown":
        raise ReplicationError("a frozen-method regime label is required")
    trading_date = entry_at.astimezone(ZoneInfo("America/New_York")).date().isoformat()
    return {
        "signal_event_id": signal["event_id"],
        "rule_ref": dict(signal["rule_ref"]),
        "trader": signal["trader"],
        "instrument": instrument,
        "position_side": position_side,
        "quote_authority": "opra",
        "quote_method": str(raw["quote_method"]),
        "entry_quote_timestamp": entry_at.isoformat().replace("+00:00", "Z"),
        "exit_quote_timestamp": exit_at.isoformat().replace("+00:00", "Z"),
        "entry_join_delay_seconds": join_delay,
        "entry_executable_value": entry_value,
        "exit_executable_value": exit_value,
        "entry_mid_value": entry_mid,
        "exit_mid_value": exit_mid,
        "quantity": quantity,
        "multiplier": multiplier,
        "capital_at_risk_dollars": capital_at_risk,
        "gross_pnl_dollars": round(gross_pnl, 6),
        "spread_friction_dollars": round(spread_friction, 6),
        "fees_dollars": fees,
        "additional_slippage_dollars": slippage,
        "net_pnl_dollars": round(net_pnl, 6),
        "doubled_cost_pnl_dollars": round(doubled_cost_pnl, 6),
        "net_r": round(net_pnl / capital_at_risk, 8),
        "doubled_cost_r": round(doubled_cost_pnl / capital_at_risk, 8),
        "regime": regime,
        "regime_definition_hash": rule["regime_definition"]["definition_hash"],
        "trading_date": trading_date,
        "resolution": str(raw.get("resolution") or "unknown"),
        "calculation_authority": "pipeline_computed_not_source_claimed",
    }


def import_replay_outcomes(
    outcomes: Iterable[Mapping[str, Any]], *, ledger_path: Path = DEFAULT_LEDGER
) -> dict[str, Any]:
    ledger = load_ledger(ledger_path)
    signals = _signal_events(ledger)
    existing_by_signal = {
        str(row.get("outcome", {}).get("signal_event_id")): row.get("outcome")
        for row in ledger
        if row.get("event_type") == "replay_outcome"
    }
    batch_by_signal: dict[str, dict[str, Any]] = {}
    events = []
    for raw in outcomes:
        signal_id = str(raw.get("signal_event_id") or "")
        signal = signals.get(signal_id)
        if signal is None:
            raise ReplicationError(f"unknown signal_event_id: {signal_id}")
        rule_ref = signal["rule_ref"]
        rule = _registered_rule(ledger, rule_ref["rule_id"], rule_ref["version"])
        outcome = normalize_replay_outcome(raw, signal=signal, rule=rule)
        prior = existing_by_signal.get(signal_id) or batch_by_signal.get(signal_id)
        if prior is not None and prior != outcome:
            raise ReplicationError(f"conflicting second outcome for signal: {signal_id}")
        batch_by_signal[signal_id] = outcome
        events.append(
            {
                "event_id": f"outcome:{_sha256(outcome)[:24]}",
                "event_type": "replay_outcome",
                "outcome": outcome,
            }
        )
    return append_events(events, path=ledger_path)


def _mean(values: list[float]) -> float | None:
    return sum(values) / len(values) if values else None


def _profit_factor(values: list[float]) -> float | None:
    wins = sum(value for value in values if value > 0)
    losses = abs(sum(value for value in values if value < 0))
    if losses == 0:
        return None if wins == 0 else float("inf")
    return wins / losses


def _drawdown(values: list[float]) -> tuple[float, int]:
    equity = 0.0
    peak = 0.0
    max_drawdown = 0.0
    current_losses = 0
    max_losses = 0
    for value in values:
        equity += value
        peak = max(peak, equity)
        max_drawdown = max(max_drawdown, peak - equity)
        current_losses = current_losses + 1 if value < 0 else 0
        max_losses = max(max_losses, current_losses)
    return max_drawdown, max_losses


def _trim_best(values: list[float], fraction: float) -> list[float]:
    if not values:
        return []
    remove_count = max(1, math.ceil(len(values) * fraction))
    return sorted(values)[:-remove_count]


def _covered(signal: Mapping[str, Any], manifests: Iterable[Mapping[str, Any]]) -> bool:
    timestamp = _parse_timestamp(signal.get("source_timestamp"))
    if timestamp is None:
        return False
    source = signal.get("source") or {}
    for row in manifests:
        manifest = row.get("manifest") or {}
        start = _parse_timestamp(manifest.get("coverage_start"))
        end = _parse_timestamp(manifest.get("coverage_end"))
        if (
            manifest.get("source_type") == source.get("type")
            and manifest.get("source_id") == source.get("id")
            and manifest.get("trader") == signal.get("trader")
            and start is not None
            and end is not None
            and start <= timestamp <= end
        ):
            return True
    return False


def _cohort_report(
    rule: Mapping[str, Any],
    signals: list[dict[str, Any]],
    outcomes: list[dict[str, Any]],
    manifests: list[dict[str, Any]],
) -> dict[str, Any]:
    observed_signal_count = len(signals)
    signals = [row for row in signals if row.get("forward_eligible")]
    eligible_signal_ids = {row["event_id"] for row in signals}
    outcomes = [row for row in outcomes if row.get("signal_event_id") in eligible_signal_ids]
    outcomes.sort(key=lambda row: (row["trading_date"], row["entry_quote_timestamp"]))
    values = [float(row["net_r"]) for row in outcomes]
    doubled = [float(row["doubled_cost_r"]) for row in outcomes]
    holdout_count = max(1, math.ceil(len(values) * 0.25)) if values else 0
    holdout = values[-holdout_count:] if holdout_count else []
    full_lcb = executable_ev_lower_bound([value * 100.0 for value in values])
    holdout_lcb = executable_ev_lower_bound([value * 100.0 for value in holdout])
    max_drawdown, max_loss_streak = _drawdown(values)
    by_regime: dict[str, list[float]] = defaultdict(list)
    for row in outcomes:
        by_regime[str(row["regime"])].append(float(row["net_r"]))
    regimes = {
        name: {"count": len(rows), "mean_r": round(_mean(rows) or 0.0, 6)}
        for name, rows in sorted(by_regime.items())
    }
    signal_ids = {row["event_id"] for row in signals}
    resolved_signal_ids = {row["signal_event_id"] for row in outcomes}
    covered_count = sum(_covered(row, manifests) for row in signals)
    reconstruction_ready = sum(bool(row.get("reconstruction_ready")) for row in signals)
    distinct_days = len({row["trading_date"] for row in outcomes})
    pf = _profit_factor(values)
    top_one = _trim_best(values, 0.01)
    top_five = _trim_best(values, 0.05)
    blockers: list[str] = []
    checks = (
        (len(signals) < 30, "fewer_than_30_pretrade_signals"),
        (len(outcomes) < 30, "fewer_than_30_resolved_reconstructions"),
        (distinct_days < 20, "fewer_than_20_independent_dates"),
        (len(signals) == 0 or covered_count / len(signals) < 0.95, "source_coverage_below_95pct"),
        (len(signals) == 0 or reconstruction_ready / len(signals) < 0.80, "point_in_time_join_below_80pct"),
        (len(signals) == 0 or len(resolved_signal_ids & signal_ids) / len(signals) < 0.80, "reconstruction_rate_below_80pct"),
        (full_lcb.get("status") != "positive", "full_executable_lcb_not_positive"),
        (len(holdout) < 10, "chronological_holdout_fewer_than_10"),
        (holdout_lcb.get("status") != "positive", "holdout_executable_lcb_not_positive"),
        (pf is None or pf < 1.20, "profit_factor_below_1_20"),
        (_mean(doubled) is None or (_mean(doubled) or 0.0) <= 0, "doubled_cost_expectancy_not_positive"),
        (_mean(top_one) is None or (_mean(top_one) or 0.0) <= 0, "best_1pct_removed_expectancy_not_positive"),
        (_mean(top_five) is None or (_mean(top_five) or 0.0) <= 0, "best_5pct_removed_expectancy_not_positive"),
        (max_drawdown > 10.0, "max_drawdown_exceeds_10r"),
        (
            len([rows for rows in by_regime.values() if len(rows) >= 5 and (_mean(rows) or 0.0) > 0]) < 2,
            "fewer_than_two_positive_regimes_with_5_outcomes",
        ),
    )
    blockers.extend(reason for failed, reason in checks if failed)
    return {
        "rule_id": rule["rule_id"],
        "version": rule["version"],
        "rule_hash": rule["rule_hash"],
        "setup_family": rule["setup_family"],
        "source_traders": rule["source_traders"],
        "observed_signal_count": observed_signal_count,
        "signal_count": len(signals),
        "covered_signal_count": covered_count,
        "source_coverage_rate": round(covered_count / len(signals), 4) if signals else 0.0,
        "point_in_time_join_rate": round(reconstruction_ready / len(signals), 4) if signals else 0.0,
        "resolved_count": len(outcomes),
        "reconstruction_rate": round(len(resolved_signal_ids & signal_ids) / len(signals), 4) if signals else 0.0,
        "distinct_resolved_days": distinct_days,
        "mean_net_r": round(_mean(values), 6) if values else None,
        "mean_doubled_cost_r": round(_mean(doubled), 6) if doubled else None,
        "profit_factor": round(pf, 4) if isinstance(pf, float) and math.isfinite(pf) else pf,
        "max_drawdown_r": round(max_drawdown, 6),
        "max_consecutive_losses": max_loss_streak,
        "best_1pct_removed_mean_r": round(_mean(top_one), 6) if top_one else None,
        "best_5pct_removed_mean_r": round(_mean(top_five), 6) if top_five else None,
        "full_executable_lcb": full_lcb,
        "chronological_holdout": {"count": len(holdout), **holdout_lcb},
        "regimes": regimes,
        "status": "forward_shadow_nominee" if not blockers else "collecting_or_rejected",
        "promotion_blockers": blockers,
        "paper_gate_ready": False,
        "production_change_allowed": False,
    }


def build_report(events: list[dict[str, Any]]) -> dict[str, Any]:
    integrity = verify_ledger(events)
    rules = [row["rule"] for row in events if row.get("event_type") == "rule_registered"]
    signals = [row for row in events if row.get("event_type") == "signal_snapshot"]
    outcomes = [row["outcome"] for row in events if row.get("event_type") == "replay_outcome"]
    manifests = [row for row in events if row.get("event_type") == "source_coverage_manifest"]
    cohorts = []
    for rule in rules:
        rule_signals = [
            row for row in signals if row.get("rule_ref", {}).get("rule_hash") == rule["rule_hash"]
        ]
        signal_ids = {row["event_id"] for row in rule_signals}
        rule_outcomes = [row for row in outcomes if row.get("signal_event_id") in signal_ids]
        cohorts.append(_cohort_report(rule, rule_signals, rule_outcomes, manifests))
    cohorts.sort(
        key=lambda row: (
            row["status"] == "forward_shadow_nominee",
            row["full_executable_lcb"].get("executable_ev_lower_bound_pct") or -math.inf,
            row["resolved_count"],
        ),
        reverse=True,
    )
    return {
        "schema_version": SCHEMA_VERSION,
        "provider": "public_strategy_replication_league",
        "generated_at": _now_iso(),
        "mode": "research_and_forward_shadow_only",
        "execution_enabled": False,
        "can_submit_orders": False,
        "automatic_promotion": False,
        "paper_gate_ready": False,
        "integrity": integrity,
        "rule_count": len(rules),
        "signal_count": len(signals),
        "outcome_count": len(outcomes),
        "coverage_manifest_count": len(manifests),
        "forward_shadow_nominee_count": sum(
            row["status"] == "forward_shadow_nominee" for row in cohorts
        ),
        "cohorts": cohorts,
        "warnings": [
            "Public strategies are hypotheses until independently reconstructed.",
            "Screenshots, self-reported PnL, and post-entry calls are excluded.",
            "A forward-shadow nominee still requires independent adversarial review and human approval.",
            "This report has no paper or production execution authority.",
        ],
    }


def write_report(report: Mapping[str, Any], path: Path = DEFAULT_REPORT) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    register = subparsers.add_parser("register-rules")
    register.add_argument("--input", type=Path, required=True)
    register.add_argument("--ledger", type=Path, default=DEFAULT_LEDGER)

    snapshot = subparsers.add_parser("snapshot-signals")
    snapshot.add_argument("--verified-journal", type=Path, required=True)
    snapshot.add_argument("--rule-id", required=True)
    snapshot.add_argument("--version", required=True)
    snapshot.add_argument("--ledger", type=Path, default=DEFAULT_LEDGER)

    coverage = subparsers.add_parser("import-coverage")
    coverage.add_argument("--input", type=Path, required=True)
    coverage.add_argument("--ledger", type=Path, default=DEFAULT_LEDGER)

    outcomes = subparsers.add_parser("import-outcomes")
    outcomes.add_argument("--input", type=Path, required=True)
    outcomes.add_argument("--ledger", type=Path, default=DEFAULT_LEDGER)

    verify = subparsers.add_parser("verify")
    verify.add_argument("--ledger", type=Path, default=DEFAULT_LEDGER)

    report_parser = subparsers.add_parser("report")
    report_parser.add_argument("--ledger", type=Path, default=DEFAULT_LEDGER)
    report_parser.add_argument("--out", type=Path, default=DEFAULT_REPORT)
    report_parser.add_argument("--print", action="store_true", dest="print_output")

    args = parser.parse_args()
    try:
        if args.command == "register-rules":
            result = register_rules(_load_json_rows(args.input), ledger_path=args.ledger)
        elif args.command == "snapshot-signals":
            result = snapshot_verified_signals(
                load_jsonl(args.verified_journal, tolerate_invalid=False),
                rule_id=args.rule_id,
                version=args.version,
                ledger_path=args.ledger,
            )
        elif args.command == "import-coverage":
            result = import_coverage_manifests(
                _load_json_rows(args.input), ledger_path=args.ledger
            )
        elif args.command == "import-outcomes":
            result = import_replay_outcomes(
                _load_json_rows(args.input), ledger_path=args.ledger
            )
        elif args.command == "verify":
            result = verify_ledger(load_ledger(args.ledger))
        else:
            report = build_report(load_ledger(args.ledger))
            write_report(report, args.out)
            result = report
        if args.command != "report" or args.print_output:
            print(json.dumps(result, indent=2, sort_keys=True))
        else:
            print(
                f"Replication league: {result['rule_count']} rules, "
                f"{result['signal_count']} signals, {result['outcome_count']} outcomes, "
                f"{result['forward_shadow_nominee_count']} nominees."
            )
        return 0
    except ReplicationError as exc:
        print(f"Public strategy replication blocked: {exc}")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

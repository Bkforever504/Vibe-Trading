#!/usr/bin/env python3
"""Normalize external trader evidence into an append-only shadow journal.

This module is deliberately unable to place orders. Public social claims,
cooperating-trader alerts, and consented broker histories receive different
evidence treatment and can never grant themselves production authority.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import os
import re
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping

ROOT = Path(__file__).resolve().parents[1]
VIBE_HOME = Path.home() / ".vibe-trading"
DEFAULT_JOURNAL = ROOT / "data" / "verified_trader_evidence_log.jsonl"
DEFAULT_REPORT = VIBE_HOME / "reports" / "verified-trader-evidence.json"
DEFAULT_PROFILES_EXPORT = VIBE_HOME / "verified-trader-profiles.json"
DEFAULT_SIGNALS_EXPORT = VIBE_HOME / "verified-trader-signals.json"

SCHEMA_VERSION = "1.1.0"
TRADE_EVENT_TYPES = {"signal", "fill", "outcome"}
COVERAGE_EVENT_TYPE = "coverage_manifest"
CONTEXT_SOURCE_TYPES = {"x_api", "sec_form4", "cftc_cot"}
SECRET_KEY_FRAGMENTS = (
    "authorization",
    "password",
    "passwd",
    "secret",
    "token",
    "api_key",
    "apikey",
    "api-key",
    "private_key",
    "client_secret",
    "x-auth",
)

SOURCE_POLICIES: dict[str, dict[str, Any]] = {
    "broker_csv": {
        "base_evidence_score": 9,
        "consent_required": True,
        "default_event_type": "fill",
        "context_only": False,
        "broker_linked": True,
    },
    "snaptrade_activity": {
        "base_evidence_score": 9,
        "consent_required": True,
        "default_event_type": "fill",
        "context_only": False,
        "broker_linked": True,
    },
    "collective2_signal": {
        "base_evidence_score": 4,
        "consent_required": False,
        "default_event_type": "signal",
        "context_only": False,
        "broker_linked": False,
        "results_hypothetical": True,
    },
    "robinhood_social_signal": {
        "base_evidence_score": 8,
        "consent_required": False,
        "default_event_type": "signal",
        "context_only": False,
        "broker_linked": False,
        "trade_verified_by_platform": True,
    },
    "kinfo_public_profile": {
        "base_evidence_score": 7,
        "consent_required": False,
        "default_event_type": "claim",
        "context_only": True,
        "broker_linked": False,
        "performance_verified_by_broker_import": True,
    },
    "tradingview_webhook": {
        "base_evidence_score": 6,
        "consent_required": True,
        "default_event_type": "signal",
        "context_only": False,
        "broker_linked": False,
    },
    "manual_export": {
        "base_evidence_score": 4,
        "consent_required": True,
        "default_event_type": "signal",
        "context_only": False,
        "broker_linked": False,
    },
    "x_api": {
        "base_evidence_score": 2,
        "consent_required": False,
        "default_event_type": "claim",
        "context_only": True,
        "broker_linked": False,
    },
    "sec_form4": {
        "base_evidence_score": 8,
        "consent_required": False,
        "default_event_type": "context",
        "context_only": True,
        "broker_linked": False,
    },
    "cftc_cot": {
        "base_evidence_score": 8,
        "consent_required": False,
        "default_event_type": "context",
        "context_only": True,
        "broker_linked": False,
    },
}


class EvidenceIntakeError(RuntimeError):
    """A safe, user-facing intake error."""


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def parse_timestamp(value: Any) -> datetime | None:
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        parsed = value
    else:
        text = str(value).strip()
        if not text:
            return None
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        try:
            parsed = datetime.fromisoformat(text)
        except ValueError:
            for pattern in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d", "%m/%d/%Y %H:%M:%S", "%m/%d/%Y"):
                try:
                    parsed = datetime.strptime(text, pattern)
                    break
                except ValueError:
                    continue
            else:
                return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _safe_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def _safe_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _safe_bool(value: Any) -> bool | None:
    if isinstance(value, bool):
        return value
    text = str(value or "").strip().lower()
    if text in {"true", "1", "yes"}:
        return True
    if text in {"false", "0", "no"}:
        return False
    return None


def _first(raw: Mapping[str, Any], *keys: str) -> Any:
    for key in keys:
        if key in raw and raw[key] not in (None, ""):
            return raw[key]
    return None


def _nested_symbol(value: Any) -> str | None:
    if isinstance(value, Mapping):
        return _safe_text(
            _first(value, "symbol", "ticker", "raw_symbol", "description", "id")
        )
    return _safe_text(value)


def _canonical_action(value: Any) -> str | None:
    text = str(value or "").strip().upper().replace("-", "_").replace(" ", "_")
    aliases = {
        "B": "BUY",
        "BOT": "BUY",
        "BTO": "BUY",
        "BUY_TO_OPEN": "BUY",
        "BUY_TO_CLOSE": "BUY",
        "S": "SELL",
        "SLD": "SELL",
        "STO": "SELL",
        "SELL_TO_OPEN": "SELL",
        "SELL_TO_CLOSE": "SELL",
    }
    if text in aliases:
        return aliases[text]
    return text if text in {"BUY", "SELL"} else None


def _canonical_direction(value: Any) -> str | None:
    text = str(value or "").strip().upper().replace("-", "_").replace(" ", "_")
    aliases = {
        "BULL": "LONG",
        "BULLISH": "LONG",
        "UP": "LONG",
        "BEAR": "SHORT",
        "BEARISH": "SHORT",
        "DOWN": "SHORT",
    }
    if text in aliases:
        return aliases[text]
    return text if text in {"LONG", "SHORT"} else None


def sanitize_payload(value: Any) -> Any:
    """Remove credential-like values while preserving research fields."""
    if isinstance(value, Mapping):
        sanitized: dict[str, Any] = {}
        for key, child in value.items():
            lowered = str(key).lower()
            if any(fragment in lowered for fragment in SECRET_KEY_FRAGMENTS):
                sanitized[str(key)] = "[REDACTED]"
            else:
                sanitized[str(key)] = sanitize_payload(child)
        return sanitized
    if isinstance(value, list):
        return [sanitize_payload(item) for item in value]
    if isinstance(value, tuple):
        return [sanitize_payload(item) for item in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


def timeliness_score(latency_seconds: float | None) -> int:
    if latency_seconds is None or latency_seconds < 0:
        return 0
    if latency_seconds <= 5:
        return 10
    if latency_seconds <= 60:
        return 9
    if latency_seconds <= 300:
        return 7
    if latency_seconds <= 900:
        return 5
    if latency_seconds <= 3600:
        return 3
    return 1


def _extract_cashtags(text: str) -> list[str]:
    return sorted({match.upper() for match in re.findall(r"\$([A-Za-z]{1,6})\b", text)})


def _canonicalize_raw(
    raw: Mapping[str, Any],
    *,
    source_type: str,
    policy: Mapping[str, Any],
) -> dict[str, Any]:
    event_type = str(
        _first(raw, "event_type", "record_type", "kind") or policy["default_event_type"]
    ).strip().lower()
    if source_type == "snaptrade_activity":
        transaction_type = str(_first(raw, "type", "transaction_type") or "").upper()
        if transaction_type in {"BUY", "SELL"}:
            event_type = "fill"
        elif event_type == "fill":
            event_type = "activity"

    universal_symbol = raw.get("universal_symbol")
    option_symbol = raw.get("option_symbol")
    symbol = _nested_symbol(
        _first(raw, "symbol", "ticker", "market", "instrument", "underlying")
    )
    if not symbol:
        symbol = _nested_symbol(option_symbol) or _nested_symbol(universal_symbol)

    text = str(_first(raw, "text", "message", "claim_text", "notes") or "")
    cashtags = _extract_cashtags(text)
    if not symbol and cashtags:
        symbol = cashtags[0]

    raw_side = _first(raw, "action", "order_action", "transaction_type", "side")
    if source_type == "snaptrade_activity" and not raw_side:
        raw_side = _first(raw, "type")
    action = _canonical_action(raw_side)
    explicit_direction = _first(raw, "direction", "bias", "position_direction")
    direction = _canonical_direction(explicit_direction)
    if not direction and not action:
        direction = _canonical_direction(raw_side)

    timestamp = _first(
        raw,
        "source_timestamp",
        "filled_at",
        "executed_at",
        "created_at",
        "trade_date",
        "observed_at",
        "timestamp",
        "date",
    )
    external_id = _safe_text(
        _first(
            raw,
            "external_id",
            "id",
            "post_id",
            "signal_id",
            "order_id",
            "brokerage_order_id",
            "trade_id",
        )
    )
    trader_id = _safe_text(
        _first(
            raw,
            "trader_id",
            "trader",
            "handle",
            "author_username",
            "system_id",
            "strategy_owner",
            "account_owner_id",
        )
    )
    platform = _safe_text(_first(raw, "platform", "brokerage", "provider")) or source_type

    nested_fee = raw.get("fee")
    if isinstance(nested_fee, Mapping):
        nested_fee = _first(nested_fee, "amount", "value")
    return {
        "external_id": external_id,
        "event_type": event_type,
        "trader_id": trader_id,
        "trader_handle": _safe_text(_first(raw, "handle", "author_username", "trader")) or trader_id,
        "platform": platform,
        "source_timestamp": timestamp,
        "symbol": symbol.upper() if symbol else None,
        "underlying": _safe_text(_first(raw, "underlying", "underlying_symbol")),
        "asset_class": _safe_text(_first(raw, "asset_class", "security_type", "category")),
        "option_symbol": _nested_symbol(option_symbol),
        "option_right": _safe_text(_first(raw, "option_right", "right")),
        "strike": _safe_float(_first(raw, "strike", "strike_price")),
        "expiration": _safe_text(_first(raw, "expiration", "expiry", "expiration_date")),
        "action": action,
        "direction": direction,
        "quantity": _safe_float(_first(raw, "quantity", "qty", "units", "size", "contracts")),
        "price": _safe_float(
            _first(
                raw,
                "price",
                "fill_price",
                "filled_avg_price",
                "entry_price",
                "leader_price",
                "limit_price",
            )
        ),
        "observed_market_price": _safe_float(
            _first(raw, "observed_market_price", "current_price", "mark_price")
        ),
        "observed_market_timestamp": _safe_text(
            _first(raw, "observed_market_timestamp", "current_price_timestamp", "mark_timestamp")
        ),
        "observed_market_source": _safe_text(
            _first(raw, "observed_market_source", "current_price_source", "mark_source")
        ),
        "stop_price": _safe_float(_first(raw, "stop_price", "stop", "stop_loss")),
        "target_price": _safe_float(_first(raw, "target_price", "target", "take_profit")),
        "fees": _safe_float(_first(raw, "fees", "commission") or nested_fee),
        "realized_pnl": _safe_float(
            _first(raw, "realized_pnl", "realized_pnl_dollars", "pnl", "profit_loss")
        ),
        "strategy": _safe_text(_first(raw, "strategy", "strategy_name", "setup", "alert_name")),
        "position_id": _safe_text(
            _first(raw, "position_id", "trade_group_id", "brokerage_group_order_id")
        ),
        "coverage_manifest": {
            "account_id_hash": _safe_text(_first(raw, "account_id_hash", "account_hash")),
            "requested_start": _safe_text(_first(raw, "requested_start", "request_start")),
            "requested_end": _safe_text(_first(raw, "requested_end", "request_end")),
            "coverage_start": _safe_text(_first(raw, "coverage_start", "export_start")),
            "coverage_end": _safe_text(_first(raw, "coverage_end", "export_end")),
            "record_count": _safe_float(_first(raw, "record_count", "export_record_count")),
            "complete": _safe_bool(_first(raw, "complete", "coverage_complete")),
            "losses_included": _safe_bool(_first(raw, "losses_included", "includes_losses")),
            "export_sha256": _safe_text(_first(raw, "export_sha256", "sha256")),
        },
        "source_url": _safe_text(_first(raw, "source_url", "url", "permalink")),
        "text": text[:2000] or None,
    }


def _fingerprint_payload(
    canonical: Mapping[str, Any],
    *,
    source_type: str,
    source_id: str,
) -> str:
    external_id = canonical.get("external_id")
    if external_id:
        identity: dict[str, Any] = {
            "source_type": source_type,
            "source_id": source_id,
            "external_id": external_id,
        }
    else:
        identity = {
            "source_type": source_type,
            "source_id": source_id,
            "trader_id": canonical.get("trader_id"),
            "symbol": canonical.get("symbol"),
            "event_type": canonical.get("event_type"),
            "source_timestamp": canonical.get("source_timestamp"),
            "action": canonical.get("action"),
            "direction": canonical.get("direction"),
            "price": canonical.get("price"),
            "quantity": canonical.get("quantity"),
        }
    encoded = json.dumps(identity, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _completeness(canonical: Mapping[str, Any]) -> tuple[float, list[str]]:
    required: list[tuple[str, bool]] = [
        ("trader_id", bool(canonical.get("trader_id"))),
        ("event_type", bool(canonical.get("event_type"))),
        ("source_timestamp", bool(canonical.get("source_timestamp"))),
    ]
    event_type = canonical.get("event_type")
    if event_type in TRADE_EVENT_TYPES:
        required.extend(
            [
                ("symbol", bool(canonical.get("symbol"))),
                (
                    "action_or_direction",
                    bool(canonical.get("action") or canonical.get("direction")),
                ),
            ]
        )
    if event_type in {"signal", "fill"}:
        required.append(("price", canonical.get("price") is not None))
    if event_type == "fill":
        required.append(("quantity", canonical.get("quantity") is not None))
    if event_type == "outcome":
        required.append(("realized_pnl", canonical.get("realized_pnl") is not None))
    if event_type == COVERAGE_EVENT_TYPE:
        manifest = canonical.get("coverage_manifest") or {}
        required.extend(
            [
                ("external_id", bool(canonical.get("external_id"))),
                ("account_id_hash", bool(manifest.get("account_id_hash"))),
                ("requested_start", bool(manifest.get("requested_start"))),
                ("requested_end", bool(manifest.get("requested_end"))),
                ("coverage_start", bool(manifest.get("coverage_start"))),
                ("coverage_end", bool(manifest.get("coverage_end"))),
                ("record_count", bool(manifest.get("record_count"))),
                ("complete", manifest.get("complete") is True),
                ("losses_included", manifest.get("losses_included") is True),
                ("export_sha256", bool(manifest.get("export_sha256"))),
            ]
        )
    missing = [name for name, present in required if not present]
    score = (len(required) - len(missing)) / len(required) if required else 0.0
    return round(score, 4), missing


def normalize_record(
    raw: Mapping[str, Any],
    *,
    source_type: str,
    source_id: str,
    consent_ref: str | None = None,
    observed_at: datetime | str | None = None,
    ingested_at: datetime | None = None,
) -> dict[str, Any]:
    if source_type not in SOURCE_POLICIES:
        raise EvidenceIntakeError(f"unsupported source type: {source_type}")
    if not source_id.strip():
        raise EvidenceIntakeError("source_id is required")

    policy = SOURCE_POLICIES[source_type]
    ingested = ingested_at or _now_utc()
    observed = parse_timestamp(observed_at) or ingested
    canonical = _canonicalize_raw(raw, source_type=source_type, policy=policy)
    source_dt = parse_timestamp(canonical["source_timestamp"])
    canonical["source_timestamp"] = _iso(source_dt) if source_dt else None
    latency = (observed - source_dt).total_seconds() if source_dt else None
    latency_score = timeliness_score(latency)
    completeness_score, missing = _completeness(canonical)

    quarantine_reasons: list[str] = []
    if policy["consent_required"] and not _safe_text(consent_ref):
        quarantine_reasons.append("consent_reference_required")
    if not canonical["trader_id"]:
        quarantine_reasons.append("trader_id_missing")
    if not canonical["source_timestamp"]:
        quarantine_reasons.append("source_timestamp_missing")
    if canonical["event_type"] in TRADE_EVENT_TYPES and not canonical["symbol"]:
        quarantine_reasons.append("symbol_missing")
    if (
        canonical["event_type"] in TRADE_EVENT_TYPES
        and not canonical["action"]
        and not canonical["direction"]
    ):
        quarantine_reasons.append("side_missing")
    if latency is not None and latency < 0:
        quarantine_reasons.append("timestamp_paradox")
    if completeness_score < 0.70 and not policy["context_only"]:
        quarantine_reasons.append("completeness_below_0_70")
    if canonical["event_type"] == "outcome" and not policy.get("broker_linked"):
        quarantine_reasons.append("outcome_claimed_by_non_broker_source")
    if canonical["event_type"] == COVERAGE_EVENT_TYPE:
        manifest = canonical["coverage_manifest"]
        requested_start = parse_timestamp(manifest.get("requested_start"))
        requested_end = parse_timestamp(manifest.get("requested_end"))
        coverage_start = parse_timestamp(manifest.get("coverage_start"))
        coverage_end = parse_timestamp(manifest.get("coverage_end"))
        record_count = manifest.get("record_count")
        hashes_valid = all(
            re.fullmatch(r"[0-9a-fA-F]{64}", str(value or ""))
            for value in (manifest.get("account_id_hash"), manifest.get("export_sha256"))
        )
        dates_valid = all((requested_start, requested_end, coverage_start, coverage_end))
        range_valid = bool(
            dates_valid
            and requested_start <= requested_end
            and coverage_start <= requested_start
            and coverage_end >= requested_end
        )
        count_valid = bool(record_count and float(record_count).is_integer() and record_count > 0)
        if not policy.get("broker_linked"):
            quarantine_reasons.append("coverage_manifest_requires_broker_source")
        if manifest.get("complete") is not True or manifest.get("losses_included") is not True:
            quarantine_reasons.append("coverage_manifest_does_not_attest_complete_losses")
        if not hashes_valid:
            quarantine_reasons.append("coverage_manifest_hash_invalid")
        if not range_valid:
            quarantine_reasons.append("coverage_manifest_range_invalid")
        if not count_valid:
            quarantine_reasons.append("coverage_manifest_record_count_invalid")

    fingerprint = _fingerprint_payload(
        canonical,
        source_type=source_type,
        source_id=source_id,
    )
    replay_eligible = False
    live_shadow_eligible = False
    if not quarantine_reasons and completeness_score >= 0.70:
        if source_type in {"broker_csv", "snaptrade_activity"}:
            replay_eligible = canonical["event_type"] in {"fill", "outcome"}
        elif (
            source_type in {
                "collective2_signal",
                "robinhood_social_signal",
                "tradingview_webhook",
            }
            and canonical["event_type"] == "signal"
            and canonical["price"] is not None
            and int(policy["base_evidence_score"]) >= 5
            and latency_score >= 5
        ):
            replay_eligible = True
            live_shadow_eligible = canonical["observed_market_price"] is not None

    return {
        "schema_version": SCHEMA_VERSION,
        "event_id": canonical["external_id"] or fingerprint[:24],
        "fingerprint": fingerprint,
        "ingested_at": _iso(ingested),
        "source": {
            "type": source_type,
            "id": source_id,
            "external_id": canonical["external_id"],
            "url": canonical["source_url"],
            "consent_ref": _safe_text(consent_ref),
            "consent_required": bool(policy["consent_required"]),
            "broker_linked": bool(policy["broker_linked"]),
            "context_only": bool(policy["context_only"]),
            "results_hypothetical": bool(policy.get("results_hypothetical", False)),
            "trade_verified_by_platform": bool(
                policy.get("trade_verified_by_platform", False)
            ),
            "performance_verified_by_broker_import": bool(
                policy.get("performance_verified_by_broker_import", False)
            ),
        },
        "trader": {
            "id": canonical["trader_id"],
            "handle": canonical["trader_handle"],
            "platform": canonical["platform"],
        },
        "event": {
            "type": canonical["event_type"],
            "source_timestamp": canonical["source_timestamp"],
            "observed_at": _iso(observed),
            "position_id": canonical["position_id"],
            "strategy": canonical["strategy"],
            "text": canonical["text"],
        },
        "coverage_manifest": canonical["coverage_manifest"],
        "instrument": {
            "symbol": canonical["symbol"],
            "underlying": canonical["underlying"],
            "asset_class": canonical["asset_class"],
            "option_symbol": canonical["option_symbol"],
            "option_right": canonical["option_right"],
            "strike": canonical["strike"],
            "expiration": canonical["expiration"],
        },
        "trade": {
            "action": canonical["action"],
            "direction": canonical["direction"],
            "quantity": canonical["quantity"],
            "price": canonical["price"],
            "observed_market_price": canonical["observed_market_price"],
            "price_drift": (
                round(
                    abs(canonical["observed_market_price"] - canonical["price"])
                    / canonical["price"],
                    6,
                )
                if canonical["price"]
                and canonical["observed_market_price"] is not None
                else None
            ),
            "stop_price": canonical["stop_price"],
            "target_price": canonical["target_price"],
            "fees": canonical["fees"],
            "realized_pnl": canonical["realized_pnl"],
        },
        "evidence": {
            "base_score": int(policy["base_evidence_score"]),
            "completeness_score": completeness_score,
            "missing_fields": missing,
            "latency_seconds": round(latency, 3) if latency is not None else None,
            "timeliness_score": latency_score,
            "source_claim_unverified": source_type == "x_api",
            "market_join": {
                "price": canonical["observed_market_price"],
                "timestamp": canonical["observed_market_timestamp"],
                "source": canonical["observed_market_source"],
                "available": canonical["observed_market_price"] is not None,
            },
            "outcome_verified": bool(
                policy["broker_linked"]
                and canonical["event_type"] == "outcome"
                and canonical["realized_pnl"] is not None
            ),
        },
        "safety": {
            "mode": "shadow_only",
            "quarantined": bool(quarantine_reasons),
            "quarantine_reasons": quarantine_reasons,
            "replay_eligible": replay_eligible,
            "live_shadow_eligible": live_shadow_eligible,
            "execution_eligible": False,
            "promotion_eligible": False,
            "human_review_required": True,
        },
        "raw_payload": sanitize_payload(dict(raw)),
    }


def x_report_rows(payload: Mapping[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for post in payload.get("posts") or []:
        if not isinstance(post, Mapping):
            continue
        rows.append(
            {
                "event_type": "claim",
                "external_id": post.get("post_id"),
                "trader_id": post.get("author_id") or post.get("author_username"),
                "handle": post.get("author_username"),
                "platform": "x",
                "source_timestamp": post.get("created_at"),
                "text": post.get("text"),
                "url": post.get("url"),
            }
        )
    return rows


def payload_rows(payload: Any, source_type: str) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [dict(row) for row in payload if isinstance(row, Mapping)]
    if not isinstance(payload, Mapping):
        raise EvidenceIntakeError("input JSON must contain an object or list")
    if source_type == "x_api" and isinstance(payload.get("posts"), list):
        return x_report_rows(payload)
    for key in ("data", "signals", "activities", "events", "trades", "records"):
        value = payload.get(key)
        if isinstance(value, list):
            return [dict(row) for row in value if isinstance(row, Mapping)]
    return [dict(payload)]


def load_input_rows(path: Path, source_type: str) -> list[dict[str, Any]]:
    if not path.exists():
        raise EvidenceIntakeError(f"input file not found: {path}")
    if path.suffix.lower() == ".csv":
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            return [dict(row) for row in csv.DictReader(handle)]
    if path.suffix.lower() == ".jsonl":
        rows: list[dict[str, Any]] = []
        for number, line in enumerate(path.read_text(encoding="utf-8-sig").splitlines(), 1):
            if not line.strip():
                continue
            try:
                payload = json.loads(line)
            except json.JSONDecodeError as exc:
                raise EvidenceIntakeError(f"invalid JSONL at line {number}: {exc.msg}") from None
            rows.extend(payload_rows(payload, source_type))
        return rows
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except json.JSONDecodeError as exc:
        raise EvidenceIntakeError(f"invalid JSON: {exc.msg}") from None
    return payload_rows(payload, source_type)


def build_coverage_manifest_row(
    path: Path,
    *,
    source_type: str,
    trader_id: str,
    account_alias: str,
    requested_start: str,
    requested_end: str,
    coverage_start: str,
    coverage_end: str,
    attest_complete_losses: bool,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Build a file-bound completeness manifest for a consented broker export."""
    if source_type not in {"broker_csv", "snaptrade_activity"}:
        raise EvidenceIntakeError("coverage manifests require a broker-linked source")
    if not trader_id.strip() or not account_alias.strip():
        raise EvidenceIntakeError("trader ID and non-sensitive account alias are required")
    if not attest_complete_losses:
        raise EvidenceIntakeError(
            "complete, loss-inclusive export attestation is required"
        )
    requested_start_dt = parse_timestamp(requested_start)
    requested_end_dt = parse_timestamp(requested_end)
    coverage_start_dt = parse_timestamp(coverage_start)
    coverage_end_dt = parse_timestamp(coverage_end)
    if not all((requested_start_dt, requested_end_dt, coverage_start_dt, coverage_end_dt)):
        raise EvidenceIntakeError("coverage manifest dates are invalid")
    if not (
        requested_start_dt <= requested_end_dt
        and coverage_start_dt <= requested_start_dt
        and coverage_end_dt >= requested_end_dt
    ):
        raise EvidenceIntakeError("coverage range must contain the requested range")

    rows = load_input_rows(path, source_type)
    policy = SOURCE_POLICIES[source_type]
    trade_record_count = sum(
        _canonicalize_raw(row, source_type=source_type, policy=policy)["event_type"]
        in {"fill", "outcome"}
        for row in rows
    )
    if trade_record_count <= 0:
        raise EvidenceIntakeError("broker export contains no fill or outcome records")
    export_sha256 = hashlib.sha256(path.read_bytes()).hexdigest()
    account_id_hash = hashlib.sha256(account_alias.strip().encode("utf-8")).hexdigest()
    manifest = {
        "external_id": f"coverage-{export_sha256[:24]}",
        "event_type": COVERAGE_EVENT_TYPE,
        "trader_id": trader_id.strip(),
        "source_timestamp": coverage_end,
        "account_id_hash": account_id_hash,
        "requested_start": requested_start,
        "requested_end": requested_end,
        "coverage_start": coverage_start,
        "coverage_end": coverage_end,
        # This is the number the report reconciles against canonical fills/outcomes.
        # The full source file, including non-trade activities, is bound by its hash.
        "record_count": trade_record_count,
        "complete": True,
        "losses_included": True,
        "export_sha256": export_sha256,
    }
    return rows, manifest


def ingest_covered_export(
    path: Path,
    *,
    source_type: str,
    source_id: str,
    consent_ref: str,
    trader_id: str,
    account_alias: str,
    requested_start: str,
    requested_end: str,
    coverage_start: str,
    coverage_end: str,
    attest_complete_losses: bool,
    observed_at: datetime | str | None = None,
    journal_path: Path = DEFAULT_JOURNAL,
    write: bool = True,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    rows, manifest = build_coverage_manifest_row(
        path,
        source_type=source_type,
        trader_id=trader_id,
        account_alias=account_alias,
        requested_start=requested_start,
        requested_end=requested_end,
        coverage_start=coverage_start,
        coverage_end=coverage_end,
        attest_complete_losses=attest_complete_losses,
    )
    records, result = ingest_rows(
        [*rows, manifest],
        source_type=source_type,
        source_id=source_id,
        consent_ref=consent_ref,
        trader_id=trader_id,
        observed_at=observed_at,
        journal_path=journal_path,
        write=write,
    )
    result.update({
        "source_row_count": len(rows),
        "source_trade_record_count": manifest["record_count"],
        "coverage_manifest_added": True,
    })
    return records, result


def load_journal(path: Path = DEFAULT_JOURNAL) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    records: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8-sig").splitlines():
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(row, dict):
            records.append(row)
    return records


def append_records(
    records: Iterable[dict[str, Any]],
    *,
    path: Path = DEFAULT_JOURNAL,
) -> dict[str, Any]:
    incoming = list(records)
    existing = {
        str(record.get("fingerprint"))
        for record in load_journal(path)
        if record.get("fingerprint")
    }
    accepted: list[dict[str, Any]] = []
    duplicate_count = 0
    broker_duplicate_count = 0
    for record in incoming:
        fingerprint = str(record.get("fingerprint") or "")
        if not fingerprint:
            raise EvidenceIntakeError("normalized record missing fingerprint")
        if fingerprint in existing:
            duplicate_count += 1
            if record.get("source", {}).get("broker_linked"):
                broker_duplicate_count += 1
            continue
        existing.add(fingerprint)
        accepted.append(record)
    if accepted:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            for record in accepted:
                handle.write(json.dumps(record, sort_keys=True, separators=(",", ":")) + "\n")
    if broker_duplicate_count:
        print(
            f"WARNING: {broker_duplicate_count} broker-linked record(s) were deduplicated "
            "(fingerprint already present). Verify no losing records are suppressed.",
            file=sys.stderr,
        )
    return {
        "accepted": len(accepted),
        "duplicates": duplicate_count,
        "broker_duplicates": broker_duplicate_count,
        "quarantined": sum(record["safety"]["quarantined"] for record in accepted),
        "replay_eligible": sum(record["safety"]["replay_eligible"] for record in accepted),
        "execution_enabled": False,
    }


def ingest_rows(
    rows: Iterable[Mapping[str, Any]],
    *,
    source_type: str,
    source_id: str,
    consent_ref: str | None = None,
    trader_id: str | None = None,
    observed_at: datetime | str | None = None,
    journal_path: Path = DEFAULT_JOURNAL,
    write: bool = True,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    records = []
    for row in rows:
        prepared = dict(row)
        if trader_id and not _first(
            prepared,
            "trader_id",
            "trader",
            "handle",
            "author_username",
            "system_id",
            "strategy_owner",
            "account_owner_id",
        ):
            prepared["trader_id"] = trader_id
        records.append(
            normalize_record(
                prepared,
                source_type=source_type,
                source_id=source_id,
                consent_ref=consent_ref,
                observed_at=observed_at,
            )
        )
    if write:
        result = append_records(records, path=journal_path)
    else:
        result = {
            "accepted": len(records),
            "duplicates": 0,
            "broker_duplicates": 0,
            "quarantined": sum(record["safety"]["quarantined"] for record in records),
            "replay_eligible": sum(record["safety"]["replay_eligible"] for record in records),
            "execution_enabled": False,
        }
    return records, result


def _max_drawdown(pnls: list[float]) -> float:
    equity = 0.0
    peak = 0.0
    drawdown = 0.0
    for pnl in pnls:
        equity += pnl
        peak = max(peak, equity)
        drawdown = max(drawdown, peak - equity)
    return round(drawdown, 4)


def _profit_factor(pnls: list[float]) -> float:
    gross_profit = sum(value for value in pnls if value > 0)
    gross_loss = abs(sum(value for value in pnls if value < 0))
    if gross_loss == 0:
        return float("inf") if gross_profit > 0 else 0.0
    return round(gross_profit / gross_loss, 4)


def _instrument_key(record: Mapping[str, Any]) -> str:
    instrument = record.get("instrument") or {}
    return str(instrument.get("option_symbol") or instrument.get("symbol") or "")


def _fill_derived_outcomes(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Reconstruct realized FIFO round trips from consented broker fills."""
    fills = [
        row for row in records
        if not row["safety"]["quarantined"]
        and row["source"]["broker_linked"]
        and row["source"]["consent_ref"]
        and row["event"]["type"] == "fill"
        and row["trade"]["action"] in {"BUY", "SELL"}
        and row["trade"]["quantity"]
        and row["trade"]["price"] is not None
        and _instrument_key(row)
    ]
    fills.sort(key=lambda row: row["event"]["source_timestamp"] or "")
    lots: dict[str, list[dict[str, Any]]] = defaultdict(list)
    outcomes: list[dict[str, Any]] = []
    for row in fills:
        key = _instrument_key(row)
        action_sign = 1 if row["trade"]["action"] == "BUY" else -1
        remaining = float(row["trade"]["quantity"])
        price = float(row["trade"]["price"])
        fee_per_unit = float(row["trade"].get("fees") or 0.0) / remaining
        is_option = bool((row.get("instrument") or {}).get("option_symbol")) or str(
            (row.get("instrument") or {}).get("asset_class") or ""
        ).lower() in {"option", "options", "us_option"}
        multiplier = 100.0 if is_option else 1.0
        while remaining > 1e-9 and lots[key] and lots[key][0]["sign"] != action_sign:
            lot = lots[key][0]
            matched = min(remaining, float(lot["quantity"]))
            gross = (
                (price - float(lot["price"])) * matched * multiplier
                if lot["sign"] > 0
                else (float(lot["price"]) - price) * matched * multiplier
            )
            fees = matched * (float(lot["fee_per_unit"]) + fee_per_unit)
            outcomes.append({
                "source_timestamp": row["event"]["source_timestamp"],
                "instrument": key,
                "quantity": matched,
                "realized_pnl": round(gross - fees, 4),
            })
            remaining -= matched
            lot["quantity"] = float(lot["quantity"]) - matched
            if lot["quantity"] <= 1e-9:
                lots[key].pop(0)
        if remaining > 1e-9:
            lots[key].append({
                "sign": action_sign,
                "quantity": remaining,
                "price": price,
                "fee_per_unit": fee_per_unit,
            })
    return outcomes


def _coverage_status(records: list[dict[str, Any]]) -> tuple[bool, list[str]]:
    manifests = [
        row for row in records
        if not row["safety"]["quarantined"]
        and row["event"]["type"] == COVERAGE_EVENT_TYPE
        and row["source"]["broker_linked"]
        and row["source"]["consent_ref"]
    ]
    if not manifests:
        return False, ["coverage_manifest_missing"]
    reasons: list[str] = []
    for manifest_row in manifests:
        manifest = manifest_row["coverage_manifest"]
        source_id = manifest_row["source"]["id"]
        observed = [
            row for row in records
            if row is not manifest_row
            and not row["safety"]["quarantined"]
            and row["source"]["broker_linked"]
            and row["source"]["id"] == source_id
            and row["event"]["type"] in {"fill", "outcome"}
        ]
        if len(observed) != int(manifest["record_count"]):
            reasons.append("coverage_manifest_record_count_mismatch")
            continue
        start = parse_timestamp(manifest["coverage_start"])
        end = parse_timestamp(manifest["coverage_end"])
        event_times = [parse_timestamp(row["event"]["source_timestamp"]) for row in observed]
        if not event_times or any(value is None or value < start or value > end for value in event_times):
            reasons.append("coverage_manifest_event_range_mismatch")
            continue
        return True, []
    return False, sorted(set(reasons)) or ["coverage_manifest_invalid"]


def _profile_summary(trader_id: str, records: list[dict[str, Any]]) -> dict[str, Any]:
    valid = [row for row in records if not row["safety"]["quarantined"]]
    outcomes = [
        row
        for row in valid
        if row["event"]["type"] == "outcome"
        and row["trade"]["realized_pnl"] is not None
    ]
    outcomes.sort(key=lambda row: row["event"]["source_timestamp"] or "")
    fill_outcomes = _fill_derived_outcomes(valid)
    if outcomes:
        pnls = [float(row["trade"]["realized_pnl"]) for row in outcomes]
        outcome_dates = [row["event"]["source_timestamp"] for row in outcomes]
        performance_source = "broker_outcome_events"
    else:
        pnls = [float(row["realized_pnl"]) for row in fill_outcomes]
        outcome_dates = [row["source_timestamp"] for row in fill_outcomes]
        performance_source = "fifo_broker_fill_reconstruction" if fill_outcomes else "none"
    wins = sum(value > 0 for value in pnls)
    source_types = sorted({str(row["source"]["type"]) for row in records})
    broker_connected_evidence = any(
        row["source"]["broker_linked"] and row["source"]["consent_ref"] for row in valid
    )
    clean_broker_outcomes = [
        row
        for row in outcomes
        if row["source"]["broker_linked"] and row["source"]["consent_ref"]
    ]
    resolved_count = len(pnls)
    broker_outcome_count_sufficient = resolved_count >= 30
    coverage_verified, coverage_blockers = _coverage_status(valid)
    replay_count = sum(row["safety"]["replay_eligible"] for row in valid)
    live_count = sum(row["safety"]["live_shadow_eligible"] for row in valid)
    status = "collecting"
    if not valid:
        status = "quarantined"
    elif replay_count == 0:
        status = "context_only"
    elif resolved_count >= 30:
        status = "adversarial_review_required"
    return {
        "trader_id": trader_id,
        "handle": next(
            (row["trader"]["handle"] for row in records if row["trader"]["handle"]),
            trader_id,
        ),
        "platforms": sorted(
            {str(row["trader"]["platform"]) for row in records if row["trader"]["platform"]}
        ),
        "source_types": source_types,
        "record_count": len(records),
        "quarantined_count": len(records) - len(valid),
        "replay_eligible_count": replay_count,
        "live_shadow_signal_count": live_count,
        "resolved_outcome_count": resolved_count,
        "explicit_broker_outcome_count": len(clean_broker_outcomes),
        "fill_derived_outcome_count": len(fill_outcomes),
        "performance_source": performance_source,
        "distinct_resolved_days": len({str(value)[:10] for value in outcome_dates if value}),
        "win_rate": round(wins / len(pnls), 4) if pnls else None,
        "realized_pnl": round(sum(pnls), 4) if pnls else None,
        "profit_factor": _profit_factor(pnls) if pnls else None,
        "max_drawdown_dollars": _max_drawdown(pnls) if pnls else None,
        "broker_connected_evidence": broker_connected_evidence,
        "broker_outcome_count_sufficient": broker_outcome_count_sufficient,
        "coverage_verified": coverage_verified,
        "coverage_blockers": coverage_blockers,
        "average_evidence_score": round(
            sum(row["evidence"]["base_score"] for row in records) / len(records), 3
        ),
        "status": status,
        "execution_eligible": False,
        "promotion_eligible": False,
        "remaining_promotion_gates": [
            "30+ independently resolved forward observations",
            "measured spread, fee, slippage, and source-delay stress",
            "positive expectancy under doubled costs",
            "best-1-percent outcome removal",
            "multi-regime stability",
            "independent adversarial review",
            "human approval",
        ],
    }


def build_report(records: list[dict[str, Any]]) -> dict[str, Any]:
    by_trader: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for record in records:
        trader_id = record.get("trader", {}).get("id")
        if trader_id:
            by_trader[str(trader_id)].append(record)
    profiles = [
        _profile_summary(trader_id, trader_records)
        for trader_id, trader_records in by_trader.items()
    ]
    profiles.sort(
        key=lambda row: (
            row["replay_eligible_count"],
            row["resolved_outcome_count"],
            row["average_evidence_score"],
        ),
        reverse=True,
    )
    source_counts = Counter(
        str(record.get("source", {}).get("type") or "unknown") for record in records
    )
    trade_records = [row for row in records if row.get("event", {}).get("type") in TRADE_EVENT_TYPES]
    broker_fills = [
        row for row in records
        if row.get("event", {}).get("type") == "fill" and row.get("source", {}).get("broker_linked")
    ]
    market_joined = [
        row for row in records
        if row.get("event", {}).get("type") == "signal"
        and row.get("evidence", {}).get("market_join", {}).get("available")
    ]
    manifests = [row for row in records if row.get("event", {}).get("type") == COVERAGE_EVENT_TYPE]
    if not trade_records:
        primary_bottleneck = "no_trade_records_only_claims"
    elif not broker_fills and not market_joined:
        primary_bottleneck = "no_broker_fills_or_point_in_time_signals"
    elif broker_fills and not manifests:
        primary_bottleneck = "broker_fills_present_but_coverage_manifest_missing"
    else:
        primary_bottleneck = "forward_outcomes_and_stress_testing"
    return {
        "schema_version": SCHEMA_VERSION,
        "provider": "verified_trader_evidence",
        "generated_at": _iso(_now_utc()),
        "mode": "shadow_only",
        "execution_enabled": False,
        "promotion_enabled": False,
        "record_count": len(records),
        "trader_count": len(profiles),
        "source_counts": dict(sorted(source_counts.items())),
        "quarantined_count": sum(
            bool(record.get("safety", {}).get("quarantined")) for record in records
        ),
        "replay_eligible_count": sum(
            bool(record.get("safety", {}).get("replay_eligible")) for record in records
        ),
        "live_shadow_eligible_count": sum(
            bool(record.get("safety", {}).get("live_shadow_eligible"))
            for record in records
        ),
        "acquisition_funnel": {
            "claim_count": sum(row.get("event", {}).get("type") == "claim" for row in records),
            "trade_event_count": len(trade_records),
            "broker_fill_count": len(broker_fills),
            "point_in_time_joined_signal_count": len(market_joined),
            "coverage_manifest_count": len(manifests),
            "primary_bottleneck": primary_bottleneck,
        },
        "profiles": profiles,
        "warnings": [
            "External observations are research evidence, not production authority.",
            "Public posts are selectively reported and cannot prove account profitability.",
            "No source, trader, or report can place an order or self-promote.",
        ],
        "live_shadow_signals": [
            {
                "trader": record["trader"]["handle"] or record["trader"]["id"],
                "platform": record["trader"]["platform"],
                "symbol": record["instrument"]["symbol"],
                "side": record["trade"]["direction"] or record["trade"]["action"],
                "leader_price": record["trade"]["price"],
                "current_price": record["trade"].get("observed_market_price"),
                "leader_notional": (
                    round(record["trade"]["price"] * record["trade"]["quantity"], 6)
                    if record["trade"]["price"] is not None
                    and record["trade"]["quantity"] is not None
                    else 0.0
                ),
                "observed_at": record["event"]["observed_at"],
                "category": record["event"]["strategy"] or "external_signal",
                "source_event_id": record["event_id"],
                "execution_eligible": False,
            }
            for record in records
            if record.get("safety", {}).get("live_shadow_eligible")
            and record.get("trade", {}).get("observed_market_price") is not None
        ],
    }


def _legacy_profile(profile: Mapping[str, Any]) -> dict[str, Any]:
    profit_factor = profile.get("profit_factor")
    return {
        "handle": profile.get("handle") or profile["trader_id"],
        "platform": ",".join(profile.get("platforms") or ["unknown"]),
        "source": (
            "exported_history"
            if profile.get("broker_outcome_count_sufficient")
            and profile.get("coverage_verified")
            else "external_evidence"
        ),
        "trades": profile["resolved_outcome_count"],
        "win_rate": profile.get("win_rate") or 0.0,
        "realized_pnl": profile.get("realized_pnl") or 0.0,
        "max_drawdown_pct": 0.0,
        "avg_leverage": 1.0,
        "profit_factor": (
            99.0 if profit_factor == float("inf") else profit_factor or 0.0
        ),
        "verified": bool(
            profile.get("broker_outcome_count_sufficient")
            and profile.get("coverage_verified")
        ),
        "category": "verified_trader_evidence",
        "trade_frequency": "unknown",
    }


def write_report_and_exports(
    report: Mapping[str, Any],
    *,
    report_path: Path = DEFAULT_REPORT,
    profiles_path: Path = DEFAULT_PROFILES_EXPORT,
    signals_path: Path = DEFAULT_SIGNALS_EXPORT,
) -> None:
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    profiles_path.parent.mkdir(parents=True, exist_ok=True)
    profiles_path.write_text(
        json.dumps([_legacy_profile(row) for row in report["profiles"]], indent=2) + "\n",
        encoding="utf-8",
    )
    # Only signals with a separately captured point-in-time market price can
    # enter this export. It remains separate from the existing dashboard input.
    signals_path.write_text(
        json.dumps(report["live_shadow_signals"], indent=2) + "\n",
        encoding="utf-8",
    )


def _source_choices() -> list[str]:
    return sorted(SOURCE_POLICIES)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    import_parser = subparsers.add_parser("import", help="Normalize and append a source file.")
    import_parser.add_argument("--source-type", required=True, choices=_source_choices())
    import_parser.add_argument("--source-id", required=True)
    import_parser.add_argument("--input", type=Path, required=True)
    import_parser.add_argument("--consent-ref")
    import_parser.add_argument("--trader-id")
    import_parser.add_argument("--observed-at")
    import_parser.add_argument("--journal", type=Path, default=DEFAULT_JOURNAL)
    import_parser.add_argument("--dry-run", action="store_true")

    covered_parser = subparsers.add_parser(
        "import-covered",
        help="Atomically import a consented broker export and its completeness manifest.",
    )
    covered_parser.add_argument(
        "--source-type", required=True, choices=("broker_csv", "snaptrade_activity")
    )
    covered_parser.add_argument("--source-id", required=True)
    covered_parser.add_argument("--input", type=Path, required=True)
    covered_parser.add_argument("--consent-ref", required=True)
    covered_parser.add_argument("--trader-id", required=True)
    covered_parser.add_argument("--account-alias", required=True)
    covered_parser.add_argument("--requested-start", required=True)
    covered_parser.add_argument("--requested-end", required=True)
    covered_parser.add_argument("--coverage-start", required=True)
    covered_parser.add_argument("--coverage-end", required=True)
    covered_parser.add_argument("--attest-complete-losses", action="store_true")
    covered_parser.add_argument("--observed-at")
    covered_parser.add_argument("--journal", type=Path, default=DEFAULT_JOURNAL)
    covered_parser.add_argument("--dry-run", action="store_true")

    report_parser = subparsers.add_parser("report", help="Build the evidence report and safe exports.")
    report_parser.add_argument("--journal", type=Path, default=DEFAULT_JOURNAL)
    report_parser.add_argument("--out", type=Path, default=DEFAULT_REPORT)
    report_parser.add_argument("--profiles-out", type=Path, default=DEFAULT_PROFILES_EXPORT)
    report_parser.add_argument("--signals-out", type=Path, default=DEFAULT_SIGNALS_EXPORT)
    report_parser.add_argument("--print", action="store_true", dest="print_output")

    args = parser.parse_args()
    try:
        if args.command == "import":
            rows = load_input_rows(args.input, args.source_type)
            _, result = ingest_rows(
                rows,
                source_type=args.source_type,
                source_id=args.source_id,
                consent_ref=args.consent_ref,
                trader_id=args.trader_id,
                observed_at=args.observed_at,
                journal_path=args.journal,
                write=not args.dry_run,
            )
            print(json.dumps(result, indent=2))
            return 0

        if args.command == "import-covered":
            _, result = ingest_covered_export(
                args.input,
                source_type=args.source_type,
                source_id=args.source_id,
                consent_ref=args.consent_ref,
                trader_id=args.trader_id,
                account_alias=args.account_alias,
                requested_start=args.requested_start,
                requested_end=args.requested_end,
                coverage_start=args.coverage_start,
                coverage_end=args.coverage_end,
                attest_complete_losses=args.attest_complete_losses,
                observed_at=args.observed_at,
                journal_path=args.journal,
                write=not args.dry_run,
            )
            print(json.dumps(result, indent=2))
            return 0

        records = load_journal(args.journal)
        report = build_report(records)
        write_report_and_exports(
            report,
            report_path=args.out,
            profiles_path=args.profiles_out,
            signals_path=args.signals_out,
        )
        if args.print_output:
            print(json.dumps(report, indent=2))
        else:
            print(
                "Verified trader report: "
                f"{report['record_count']} records, {report['trader_count']} traders, "
                f"{report['replay_eligible_count']} replay eligible."
            )
        return 0
    except EvidenceIntakeError as exc:
        print(f"Verified trader intake blocked: {exc}")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

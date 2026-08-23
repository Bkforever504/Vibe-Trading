#!/usr/bin/env python3
"""Qualify options quote evidence without granting order authority.

The module is deliberately provider-agnostic at its boundary: callers inject a
JSON snapshot and an evaluation time.  It performs no broker or network calls.
Indicative data may be retained as fresh context telemetry, but only a verified,
entitled OPRA quote can qualify for price discovery or a manual execution view.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence


SCHEMA_VERSION = 1
DEFAULT_MAX_AGE_SECONDS = 5.0
DEFAULT_CLOCK_SKEW_TOLERANCE_SECONDS = 1.0
DEFAULT_MAX_MANUAL_SPREAD_BPS = 500.0
VIBE_HOME = Path.home() / ".vibe-trading"
DEFAULT_INPUT = VIBE_HOME / "logs" / "option-quote-samples.jsonl"
DEFAULT_OUTPUT = VIBE_HOME / "reports" / "options-feed-qualification.json"


def _text(value: Any) -> str:
    return str(value or "").strip().lower()


def _finite(value: Any) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if math.isfinite(parsed) else None


def _truthy(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return _text(value) in {"1", "true", "yes", "verified", "entitled", "licensed", "active"}


def _parse_timestamp(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str) and value.strip():
        normalized = value.strip()
        if normalized.endswith("Z"):
            normalized = normalized[:-1] + "+00:00"
        try:
            parsed = datetime.fromisoformat(normalized)
        except ValueError:
            return None
    else:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _iso_utc(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _provider_class(record: Mapping[str, Any]) -> str:
    provenance = record.get("provenance")
    provenance = provenance if isinstance(provenance, Mapping) else {}
    raw = " ".join(
        filter(
            None,
            (
                _text(record.get("provider")),
                _text(record.get("vendor")),
                _text(provenance.get("provider")),
                _text(provenance.get("vendor")),
            ),
        )
    )
    if "alpaca" in raw:
        return "alpaca"
    if "databento" in raw:
        return "databento"
    if "cboe" in raw:
        return "cboe"
    if "opra" in raw:
        return "opra_direct"
    return "unknown"


def _feed_class(record: Mapping[str, Any]) -> str:
    provenance = record.get("provenance")
    provenance = provenance if isinstance(provenance, Mapping) else {}
    raw = " ".join(
        filter(
            None,
            (
                _text(record.get("feed")),
                _text(record.get("data_feed")),
                _text(record.get("quote_scope")),
                _text(provenance.get("feed")),
                _text(provenance.get("quote_scope")),
            ),
        )
    )
    # Several existing reports use "indicative_modified_not_opra_nbbo"; the
    # negative OPRA substring must never be mistaken for licensed OPRA data.
    if "indicative" in raw or "not_opra" in raw:
        return "indicative"
    if "opra" in raw:
        return "opra"
    return "unknown"


def _entitled(record: Mapping[str, Any]) -> bool:
    provenance = record.get("provenance")
    provenance = provenance if isinstance(provenance, Mapping) else {}
    values = (
        record.get("entitled"),
        record.get("entitlement_verified"),
        record.get("licensed"),
        provenance.get("entitled"),
        provenance.get("entitlement_verified"),
    )
    return any(_truthy(value) for value in values)


def _quote_timestamp(record: Mapping[str, Any]) -> tuple[Any, str]:
    for key in ("quote_timestamp", "timestamp", "as_of", "asof", "received_at"):
        if record.get(key) not in (None, ""):
            return record.get(key), key
    provenance = record.get("provenance")
    if isinstance(provenance, Mapping):
        for key in ("quote_timestamp", "timestamp", "as_of"):
            if provenance.get(key) not in (None, ""):
                return provenance.get(key), f"provenance.{key}"
    quote = record.get("quote")
    if isinstance(quote, Mapping):
        for key in ("quote_timestamp", "timestamp", "as_of"):
            if quote.get(key) not in (None, ""):
                return quote.get(key), f"quote.{key}"
    return None, "unavailable"


def _quote_value(record: Mapping[str, Any], *keys: str) -> Any:
    for key in keys:
        if record.get(key) not in (None, ""):
            return record.get(key)
    quote = record.get("quote")
    if isinstance(quote, Mapping):
        for key in keys:
            if quote.get(key) not in (None, ""):
                return quote.get(key)
    return None


def _trade_provenance(record: Mapping[str, Any], feed_class: str, entitled: bool) -> str:
    provenance = record.get("provenance")
    provenance = provenance if isinstance(provenance, Mapping) else {}
    raw = " ".join(
        filter(
            None,
            (
                _text(record.get("trade_provenance")),
                _text(record.get("trade_source")),
                _text(provenance.get("trade_provenance")),
                _text(provenance.get("trade_source")),
            ),
        )
    )
    if feed_class == "opra" and entitled and ("opra" in raw or "tape" in raw):
        return "opra_tape"
    if "indicative" in raw:
        return "indicative"
    return "unknown"


def qualify_options_feed(
    record: Mapping[str, Any],
    *,
    now: datetime | None = None,
    max_age_seconds: float = DEFAULT_MAX_AGE_SECONDS,
    clock_skew_tolerance_seconds: float = DEFAULT_CLOCK_SKEW_TOLERANCE_SECONDS,
    max_manual_spread_bps: float = DEFAULT_MAX_MANUAL_SPREAD_BPS,
) -> dict[str, Any]:
    """Return a fail-closed qualification envelope for one options quote."""

    evaluated_at = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    provider_class = _provider_class(record)
    feed_class = _feed_class(record)
    entitled = _entitled(record)
    raw_timestamp, timestamp_source = _quote_timestamp(record)
    quote_time = _parse_timestamp(raw_timestamp)

    blockers: list[str] = []
    warnings: list[str] = []

    if provider_class == "unknown":
        blockers.append("unknown_provider")
    if feed_class == "unknown":
        blockers.append("unknown_feed")
    elif feed_class == "indicative":
        blockers.append("indicative_not_opra_nbbo")
    if not entitled:
        blockers.append("opra_entitlement_unverified")

    delayed = _truthy(record.get("delayed")) or _text(record.get("freshness")) == "delayed"
    age_seconds: float | None = None
    clock_skew_seconds = 0.0
    if delayed:
        freshness = "delayed"
        blockers.append("delayed_feed")
    elif quote_time is None:
        freshness = "missing" if raw_timestamp in (None, "") else "invalid"
        blockers.append("missing_quote_timestamp" if freshness == "missing" else "invalid_quote_timestamp")
    else:
        signed_age = (evaluated_at - quote_time).total_seconds()
        if signed_age < -abs(clock_skew_tolerance_seconds):
            freshness = "clock_skew"
            clock_skew_seconds = round(abs(signed_age), 3)
            blockers.append("quote_timestamp_in_future")
        else:
            age_seconds = round(max(0.0, signed_age), 3)
            if age_seconds > max(0.0, max_age_seconds):
                freshness = "stale"
                blockers.append("stale_quote")
            else:
                freshness = "fresh"

    bid = _finite(_quote_value(record, "bid", "bid_price"))
    ask = _finite(_quote_value(record, "ask", "ask_price"))
    bid_size = _finite(_quote_value(record, "bid_size", "bidsize"))
    ask_size = _finite(_quote_value(record, "ask_size", "asksize"))

    quote_valid = True
    if bid is None or ask is None or bid <= 0 or ask <= 0:
        quote_valid = False
        blockers.append("missing_or_nonpositive_bid_ask")
    elif bid > ask:
        quote_valid = False
        blockers.append("crossed_quote")
    if bid_size is None or ask_size is None or bid_size <= 0 or ask_size <= 0:
        quote_valid = False
        blockers.append("zero_or_missing_quote_size")

    spread: float | None = None
    spread_pct: float | None = None
    spread_bps: float | None = None
    midpoint: float | None = None
    if quote_valid and bid is not None and ask is not None:
        midpoint = (bid + ask) / 2.0
        spread = max(0.0, ask - bid)
        if midpoint > 0:
            spread_pct = spread / midpoint * 100.0
            spread_bps = spread / midpoint * 10_000.0

    spread_usable = spread_bps is not None and spread_bps <= max(0.0, max_manual_spread_bps)
    if quote_valid and not spread_usable:
        blockers.append("spread_exceeds_manual_limit")

    structurally_usable = quote_valid and freshness == "fresh" and provider_class != "unknown"
    context_qualified = structurally_usable and feed_class in {"indicative", "opra"}
    feed_qualified = feed_class == "opra" and entitled and provider_class != "unknown"
    price_discovery_qualified = context_qualified and feed_qualified and spread_usable
    manual_execution_qualified = price_discovery_qualified
    trade_provenance = _trade_provenance(record, feed_class, entitled)

    if trade_provenance == "unknown":
        warnings.append("trade_provenance_unverified")
    if feed_class == "indicative" and context_qualified:
        warnings.append("indicative_context_telemetry_only")

    if manual_execution_qualified:
        qualification_label = "manual_execution_reference"
    elif context_qualified:
        qualification_label = "context_only"
    else:
        qualification_label = "blocked"

    source_label = {
        ("alpaca", "indicative"): "alpaca_indicative_modified_not_opra_nbbo",
        ("alpaca", "opra"): "alpaca_opra_nbbo",
    }.get((provider_class, feed_class), f"{provider_class}_{feed_class}")

    return {
        "schema_version": SCHEMA_VERSION,
        "symbol": str(record.get("symbol") or record.get("option_symbol") or record.get("contract") or "unknown"),
        "evaluated_at": _iso_utc(evaluated_at),
        "source_label": source_label,
        "provider_class": provider_class,
        "feed_class": feed_class,
        "entitlement_verified": entitled,
        "entitlement_status": "verified" if entitled else "unverified",
        "quote_provenance": (
            "opra_nbbo"
            if feed_class == "opra" and entitled and provider_class != "unknown"
            else "indicative_modified"
            if feed_class == "indicative"
            else "unknown"
        ),
        "trade_provenance": trade_provenance,
        "quote_timestamp": _iso_utc(quote_time) if quote_time is not None else None,
        "timestamp_source": timestamp_source,
        "freshness": freshness,
        "age_seconds": age_seconds,
        "clock_skew_seconds": clock_skew_seconds,
        "max_age_seconds": float(max_age_seconds),
        "max_manual_spread_bps": float(max_manual_spread_bps),
        "bid": bid,
        "ask": ask,
        "bid_size": bid_size,
        "ask_size": ask_size,
        "midpoint": round(midpoint, 6) if midpoint is not None else None,
        "spread": round(spread, 6) if spread is not None else None,
        "spread_pct": round(spread_pct, 3) if spread_pct is not None else None,
        "spread_bps": round(spread_bps, 2) if spread_bps is not None else None,
        "quote_valid": quote_valid,
        "feed_qualified": feed_qualified,
        "context_qualified": context_qualified,
        "price_discovery_qualified": price_discovery_qualified,
        "manual_execution_qualified": manual_execution_qualified,
        "support": {
            "context": context_qualified,
            "price_discovery": price_discovery_qualified,
            "manual_execution": manual_execution_qualified,
        },
        "qualification_label": qualification_label,
        "blockers": list(dict.fromkeys(blockers)),
        "warnings": list(dict.fromkeys(warnings)),
        "execution_enabled": False,
        "can_submit_orders": False,
    }


def build_report(
    records: Sequence[Mapping[str, Any]],
    *,
    now: datetime | None = None,
    max_age_seconds: float = DEFAULT_MAX_AGE_SECONDS,
    clock_skew_tolerance_seconds: float = DEFAULT_CLOCK_SKEW_TOLERANCE_SECONDS,
    max_manual_spread_bps: float = DEFAULT_MAX_MANUAL_SPREAD_BPS,
) -> dict[str, Any]:
    """Build a deterministic qualification report from injected records."""

    evaluated_at = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    qualified = [
        qualify_options_feed(
            record,
            now=evaluated_at,
            max_age_seconds=max_age_seconds,
            clock_skew_tolerance_seconds=clock_skew_tolerance_seconds,
            max_manual_spread_bps=max_manual_spread_bps,
        )
        for record in records
    ]
    status = (
        "manual_execution_reference_available"
        if any(row["manual_execution_qualified"] for row in qualified)
        else "context_only"
        if any(row["context_qualified"] for row in qualified)
        else "unavailable"
    )
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at": _iso_utc(evaluated_at),
        "mode": "read_only_evidence_qualification",
        "status": status,
        "source_label": "injected_options_quote_snapshot",
        "freshness_policy": {
            "max_age_seconds": float(max_age_seconds),
            "clock_skew_tolerance_seconds": float(clock_skew_tolerance_seconds),
            "max_manual_spread_bps": float(max_manual_spread_bps),
        },
        "summary": {
            "total": len(qualified),
            "feed_qualified": sum(bool(row["feed_qualified"]) for row in qualified),
            "context_qualified": sum(bool(row["context_qualified"]) for row in qualified),
            "price_discovery_qualified": sum(
                bool(row["price_discovery_qualified"]) for row in qualified
            ),
            "manual_execution_qualified": sum(
                bool(row["manual_execution_qualified"]) for row in qualified
            ),
            "blocked": sum(row["qualification_label"] == "blocked" for row in qualified),
        },
        "records": qualified,
        "execution_enabled": False,
        "can_submit_orders": False,
    }


def _load_records(path: Path) -> list[Mapping[str, Any]]:
    if not path.exists():
        return []
    if path.suffix.lower() == ".jsonl":
        rows: list[Any] = []
        for line in path.read_text(encoding="utf-8-sig").splitlines():
            try:
                value = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(value, Mapping):
                rows.append(value)
        return rows
    payload = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(payload, list):
        rows = payload
    elif isinstance(payload, Mapping):
        candidate = payload.get("quotes", payload.get("records", []))
        rows = candidate if isinstance(candidate, list) else []
    else:
        rows = []
    if not all(isinstance(row, Mapping) for row in rows):
        raise ValueError("input records must be JSON objects")
    return list(rows)


def _latest_by_symbol(records: Sequence[Mapping[str, Any]]) -> list[Mapping[str, Any]]:
    latest: dict[str, tuple[datetime, Mapping[str, Any]]] = {}
    for row in records:
        symbol = str(row.get("symbol") or row.get("option_symbol") or row.get("contract") or "").upper()
        raw_stamp, _source = _quote_timestamp(row)
        stamp = _parse_timestamp(raw_stamp) or _parse_timestamp(row.get("captured_at"))
        if not symbol or stamp is None:
            continue
        previous = latest.get(symbol)
        if previous is None or stamp > previous[0]:
            latest[symbol] = stamp, row
    return [latest[symbol][1] for symbol in sorted(latest)]


def _write_json_atomic(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    handle, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(handle, "w", encoding="utf-8") as stream:
            json.dump(payload, stream, indent=2, sort_keys=True)
            stream.write("\n")
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT, help="JSON or JSONL quote snapshot")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT, help="Qualification report path")
    parser.add_argument("--now", help="Injected ISO-8601 evaluation timestamp")
    parser.add_argument("--max-age-seconds", type=float, default=DEFAULT_MAX_AGE_SECONDS)
    parser.add_argument("--max-manual-spread-bps", type=float, default=DEFAULT_MAX_MANUAL_SPREAD_BPS)
    parser.add_argument(
        "--clock-skew-tolerance-seconds",
        type=float,
        default=DEFAULT_CLOCK_SKEW_TOLERANCE_SECONDS,
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    now = _parse_timestamp(args.now) if args.now else datetime.now(timezone.utc)
    if now is None:
        raise ValueError("--now must be a valid ISO-8601 timestamp")
    records = _latest_by_symbol(_load_records(args.input))
    report = build_report(
        records,
        now=now,
        max_age_seconds=args.max_age_seconds,
        clock_skew_tolerance_seconds=args.clock_skew_tolerance_seconds,
        max_manual_spread_bps=args.max_manual_spread_bps,
    )
    _write_json_atomic(args.output, report)
    print(
        "options_feed_qualification "
        f"total={report['summary']['total']} "
        f"manual_execution_qualified={report['summary']['manual_execution_qualified']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

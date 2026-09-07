#!/usr/bin/env python3
"""Fail-honest OPRA TCBBO flow intelligence for shadow evaluation.

OPRA does not provide aggressor side or opening/closing intent.  This module
only infers proximity to the immediately preceding consolidated quote and
keeps complex/package-like trades out of directional totals.
"""
from __future__ import annotations

import argparse
import json
import math
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping


AUTHORITY = {"execution_enabled": False, "can_submit_orders": False}
DEFAULT_INPUT = Path.home() / ".vibe-trading" / "data" / "opra-tcbbo-events.jsonl"
DEFAULT_REPORT = Path.home() / ".vibe-trading" / "reports" / "options-tape-intelligence-shadow.json"
COMPLEX_MARKERS = (
    "COMPLEX", "SPREAD", "SPRD", "STOCK_OPTION", "STOCK-OPTION", "PACKAGE",
    "CROSS", "AUCTION", "COMPRESSION", "MULTI_LEG", "MULTI-LEG",
)
SIMPLE_MARKERS = ("SIMPLE", "REGULAR", "ELECTRONIC", "AUTO_EXECUTION")


def _number(value: Any) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if math.isfinite(parsed) else None


def _timestamp(value: Any) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(str(value or "").replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def classify_tcbbo_trade(row: Mapping[str, Any], *, max_quote_age_seconds: float = 2.0) -> dict[str, Any]:
    price = _number(row.get("price"))
    bid = _number(row.get("bid_px_00") if row.get("bid_px_00") is not None else row.get("bid"))
    ask = _number(row.get("ask_px_00") if row.get("ask_px_00") is not None else row.get("ask"))
    size = _number(row.get("size"))
    event_at = _timestamp(row.get("ts_event") or row.get("timestamp"))
    # TCBBO's bid/ask fields are the consolidated BBO immediately preceding
    # this trade by schema. ts_recv is a capture timestamp after ts_event and
    # must never be misused as a quote timestamp.
    explicit_quote_at = _timestamp(row.get("quote_ts"))
    quote_at = explicit_quote_at or event_at
    condition = str(row.get("trade_condition") or row.get("condition") or "").upper()
    package_id = str(row.get("package_id") or row.get("complex_id") or "").strip() or None
    blockers: list[str] = []
    if None in {price, bid, ask, size} or min(value for value in (price, bid, ask, size) if value is not None) <= 0:
        blockers.append("missing_or_invalid_tcbbo_fields")
    if bid is not None and ask is not None and bid > ask:
        blockers.append("crossed_pre_trade_cbbo")
    age = (event_at - quote_at).total_seconds() if event_at and quote_at else None
    if age is None or age < 0 or age > max_quote_age_seconds:
        blockers.append("pre_trade_quote_stale_or_unordered")
    complex_like = bool(package_id) or any(marker in condition for marker in COMPLEX_MARKERS)
    complex_classification = "available" if condition or package_id else "unavailable_in_native_tcbbo"
    if complex_like:
        blockers.append("complex_or_packaged_trade")
    elif not condition:
        blockers.append("complex_classification_unavailable")
    elif not any(marker in condition for marker in SIMPLE_MARKERS):
        blockers.append("unrecognized_trade_condition")
    inference = "unknown"
    if not blockers and price is not None and bid is not None and ask is not None:
        tolerance = max(0.01, (ask - bid) * 0.10)
        if price >= ask - tolerance and price > bid + tolerance:
            inference = "near_ask"
        elif price <= bid + tolerance and price < ask - tolerance:
            inference = "near_bid"
        else:
            inference = "inside_or_ambiguous"
    premium = price * size * 100.0 if price is not None and size is not None else None
    return {
        "status": "classified" if not blockers else "excluded",
        "symbol": row.get("symbol") or row.get("raw_symbol"),
        "event_at": event_at.isoformat().replace("+00:00", "Z") if event_at else None,
        "sequence": row.get("sequence"),
        "inferred_trade_location": inference,
        "aggressor_side": "not_provided_by_opra",
        "opening_closing_intent": "unknown",
        "premium_usd": round(premium, 2) if premium is not None else None,
        "condition": condition or None,
        "package_id": package_id,
        "complex_or_packaged": complex_like,
        "complex_classification": complex_classification,
        "native_side": row.get("side"),
        "flags": row.get("flags"),
        "publisher_id": row.get("publisher_id"),
        "quote_provenance": "explicit_quote_timestamp" if explicit_quote_at else "tcbbo_immediately_preceding_cbbo_by_schema",
        "blockers": blockers,
        "source": "databento_opra_tcbbo",
        "authority": "shadow_critic_only_never_direction_or_execution_authority",
        **AUTHORITY,
    }


def aggregate_tcbbo_impulse(
    rows: Iterable[Mapping[str, Any]],
    *,
    minimum_classified_trades: int = 3,
) -> dict[str, Any]:
    classified = [classify_tcbbo_trade(row) for row in rows]
    valid = [row for row in classified if row["status"] == "classified"]
    excluded = defaultdict(int)
    for row in classified:
        for reason in row["blockers"]:
            excluded[reason] += 1
    near_ask = sum(float(row["premium_usd"] or 0.0) for row in valid if row["inferred_trade_location"] == "near_ask")
    near_bid = sum(float(row["premium_usd"] or 0.0) for row in valid if row["inferred_trade_location"] == "near_bid")
    ambiguous = sum(float(row["premium_usd"] or 0.0) for row in valid if row["inferred_trade_location"] == "inside_or_ambiguous")
    directional = near_ask + near_bid
    imbalance = (near_ask - near_bid) / directional if directional else None
    sufficient = len(valid) >= minimum_classified_trades and directional > 0
    return {
        "status": "observed" if sufficient else "insufficient_independent_evidence",
        "classified_trade_count": len(valid),
        "total_trade_count": len(classified),
        "near_ask_premium_usd": round(near_ask, 2),
        "near_bid_premium_usd": round(near_bid, 2),
        "ambiguous_premium_usd": round(ambiguous, 2),
        "signed_premium_imbalance": round(imbalance, 6) if imbalance is not None else None,
        "excluded_reasons": dict(sorted(excluded.items())),
        "limitations": [
            "Trade location is inferred from the preceding CBBO; OPRA does not provide aggressor side.",
            "Opening/closing intent is unknown; complex/package-like prints are excluded.",
            "This card cannot upgrade a candidate or override a deterministic veto.",
        ],
        "trades": classified,
        **AUTHORITY,
    }


def build_report(input_path: Path = DEFAULT_INPUT) -> dict[str, Any]:
    if not input_path.exists():
        return {
            "schema_version": 1,
            "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "status": "not_configured",
            "reason": "timestamped_opra_tcbbo_event_file_missing",
            "input_path": str(input_path),
            "warning": "No CBBO, trade conditions, or option flow was fabricated.",
            **AUTHORITY,
        }
    rows: list[dict[str, Any]] = []
    malformed = 0
    for line in input_path.read_text(encoding="utf-8-sig").splitlines():
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            malformed += 1
            continue
        if isinstance(row, dict):
            rows.append(row)
    result = aggregate_tcbbo_impulse(rows)
    return {
        "schema_version": 1,
        "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "input_path": str(input_path),
        "malformed_rows": malformed,
        **result,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    parser.add_argument("--print", action="store_true", dest="print_report")
    args = parser.parse_args()
    report = build_report(args.input)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    temporary = args.report.with_suffix(args.report.suffix + ".tmp")
    temporary.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(args.report)
    if args.print_report:
        print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

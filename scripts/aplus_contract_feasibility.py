#!/usr/bin/env python3
"""Exact-contract OPRA feasibility and shadow resting-limit evidence.

This module is deliberately offline and shadow-only.  It joins candidate
records that already contain a frozen OCC contract to an exact-contract quote
JSONL.  It never selects a contract from an option chain, fetches data, or
submits an order.

The accepted quote shapes are the normalized rows produced by
``fetch_databento_options_nbbo.py`` and the nested lifecycle rows produced by
``point_in_time_quotes.py``.  Indicative, future-looking, stale, malformed, or
unsynchronised arrival quotes are reported as unavailable rather than
estimated.  Resting-limit policies are supported only by a later OPRA ask at
or below the frozen buy limit; a quote event is not represented as a broker
fill and no midpoint fill is assumed.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CANDIDATES = ROOT / "data" / "options_shadow_twin_log.jsonl"
DEFAULT_QUOTES = ROOT / "data" / "databento" / "options_nbbo_candidate_quotes.jsonl"
DEFAULT_SIDECAR = Path.home() / ".vibe-trading" / "data" / "aplus_contract_feasibility.jsonl"
DEFAULT_SUMMARY = Path.home() / ".vibe-trading" / "reports" / "aplus-contract-feasibility.json"

UTC = timezone.utc
SCHEMA_VERSION = 1
OCC_PATTERN = re.compile(r"^[A-Z]{1,6}\d{6}[CP]\d{8}$")


def _parse_ts(value: Any) -> datetime | None:
    if value in (None, ""):
        return None
    raw = str(value).strip().replace("Z", "+00:00")
    # Provider timestamps can carry nanoseconds while fromisoformat accepts us.
    raw = re.sub(r"\.(\d{6})\d+(?=[+-])", r".\1", raw)
    try:
        parsed = datetime.fromisoformat(raw)
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _iso(value: datetime | None) -> str | None:
    if value is None:
        return None
    return value.astimezone(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _number(value: Any) -> float | None:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8-sig") as handle:
        for raw in handle:
            try:
                row = json.loads(raw)
            except json.JSONDecodeError:
                continue
            if isinstance(row, dict):
                rows.append(row)
    return rows


def _compact_occ(value: Any) -> str | None:
    compact = str(value or "").replace(" ", "").upper()
    return compact if OCC_PATTERN.fullmatch(compact) else None


def _occ_root(contract: str | None) -> str | None:
    if contract is None:
        return None
    match = re.match(r"^([A-Z]{1,6})\d{6}[CP]\d{8}$", contract)
    return match.group(1) if match else None


def _first_ts(row: dict[str, Any], names: Iterable[str]) -> datetime | None:
    for name in names:
        parsed = _parse_ts(row.get(name))
        if parsed is not None:
            return parsed
    return None


def _candidate_time(row: dict[str, Any]) -> datetime | None:
    return _first_ts(
        row,
        ("candidate_at", "created_at", "contract_selected_at", "observed_at", "generated_at", "as_of_et"),
    )


def _candidate_contracts(row: dict[str, Any]) -> list[str]:
    direct = [
        row.get("contract"), row.get("occ_symbol"), row.get("option_contract"),
        row.get("selected_contract"), row.get("symbol") if row.get("asset_class") == "option" else None,
    ]
    contracts = {_compact_occ(value) for value in direct}
    for leg in row.get("legs") or []:
        if isinstance(leg, dict):
            contracts.add(_compact_occ(leg.get("symbol") or leg.get("contract")))
    return sorted(contract for contract in contracts if contract)


def _nested_ts(row: dict[str, Any], section: str, names: Iterable[str]) -> datetime | None:
    payload = row.get(section)
    if not isinstance(payload, dict):
        return None
    return _first_ts(payload, names)


def _underlying_timestamp(candidate: dict[str, Any]) -> datetime | None:
    direct = _first_ts(
        candidate,
        ("underlying_quote_timestamp", "underlying_timestamp", "underlying_price_timestamp"),
    )
    if direct is not None:
        return direct
    underlying = candidate.get("underlying")
    if isinstance(underlying, dict):
        return _first_ts(underlying, ("quote_timestamp", "price_timestamp", "timestamp", "observed_at"))
    return None


def _normalise_quote(row: dict[str, Any]) -> dict[str, Any] | None:
    quote = row.get("quote") if isinstance(row.get("quote"), dict) else row
    contract = _compact_occ(row.get("symbol") or row.get("contract") or row.get("occ_symbol"))
    if contract is None:
        return None
    timestamp = _first_ts(quote, ("quote_timestamp", "observed_at", "timestamp"))
    if timestamp is None:
        timestamp = _first_ts(row, ("quote_timestamp", "observed_at", "captured_at"))
    provenance = row.get("provenance") if isinstance(row.get("provenance"), dict) else {}
    scope = str(row.get("quote_scope") or provenance.get("quote_scope") or "").strip().lower()
    if not scope:
        scope = str(provenance.get("dataset") or "").strip().lower()
    trade_ts = _nested_ts(row, "trade", ("trade_timestamp", "timestamp", "observed_at"))
    if trade_ts is None:
        trade_ts = _first_ts(row, ("trade_timestamp", "last_timestamp", "last_trade_timestamp"))
    greeks_ts = _nested_ts(row, "greeks", ("greeks_timestamp", "timestamp", "observed_at"))
    if greeks_ts is None:
        greeks_ts = _first_ts(row, ("greeks_timestamp",))
    underlying_ts = _underlying_timestamp(row)
    return {
        "contract": contract,
        "timestamp": timestamp,
        "bid": _number(quote.get("bid")),
        "ask": _number(quote.get("ask")),
        "bid_size": _number(quote.get("bid_size")),
        "ask_size": _number(quote.get("ask_size")),
        "quote_scope": scope,
        "provider_status": str(provenance.get("status") or row.get("status") or "").lower(),
        "licensed_consolidated_nbbo": provenance.get("licensed_consolidated_nbbo"),
        "trade_timestamp": trade_ts,
        "last_price": _number((row.get("trade") or {}).get("price")) if isinstance(row.get("trade"), dict) else _number(row.get("last")),
        "greeks_timestamp": greeks_ts,
        "underlying_timestamp": underlying_ts,
        "raw": row,
    }


def _is_opra_nbbo(quote: dict[str, Any]) -> bool:
    if quote.get("licensed_consolidated_nbbo") is True:
        return True
    scope = str(quote.get("quote_scope") or "").lower()
    if "indicative" in scope:
        return False
    return "opra" in scope and any(token in scope for token in ("nbbo", "cbbo", "consolidated"))


def _valid_market(quote: dict[str, Any]) -> bool:
    bid, ask = quote.get("bid"), quote.get("ask")
    return bool(bid is not None and ask is not None and bid > 0 and ask >= bid)


def _quote_metrics(quote: dict[str, Any], reference_at: datetime) -> dict[str, Any]:
    bid, ask = quote.get("bid"), quote.get("ask")
    valid = _valid_market(quote)
    midpoint = (bid + ask) / 2 if valid else None
    spread = ask - bid if valid else None
    quote_at = quote.get("timestamp")
    age = (reference_at - quote_at).total_seconds() if quote_at is not None else None
    trade_at = quote.get("trade_timestamp")
    greek_at = quote.get("greeks_timestamp")
    underlying_at = quote.get("underlying_timestamp")
    return {
        "quote_timestamp": _iso(quote_at),
        "quote_age_seconds": round(age, 3) if age is not None else None,
        "bid": bid,
        "ask": ask,
        "midpoint": round(midpoint, 4) if midpoint is not None else None,
        "spread_dollars": round(spread, 4) if spread is not None else None,
        "spread_pct_midpoint": round(100.0 * spread / midpoint, 4) if midpoint and midpoint > 0 else None,
        "bid_size": quote.get("bid_size"),
        "ask_size": quote.get("ask_size"),
        "last_price": quote.get("last_price"),
        "last_trade_timestamp": _iso(trade_at),
        "last_trade_age_seconds": round((reference_at - trade_at).total_seconds(), 3) if trade_at else None,
        "greeks_timestamp": _iso(greek_at),
        "greeks_age_seconds": round((reference_at - greek_at).total_seconds(), 3) if greek_at else None,
        "underlying_timestamp": _iso(underlying_at),
        "underlying_option_timestamp_skew_seconds": round(abs((quote_at - underlying_at).total_seconds()), 3)
        if quote_at and underlying_at else None,
        "quote_scope": quote.get("quote_scope") or None,
    }


def _find_arrival(quotes: list[dict[str, Any]], candidate_at: datetime) -> dict[str, Any] | None:
    eligible = [q for q in quotes if q.get("timestamp") is not None and q["timestamp"] <= candidate_at]
    return max(eligible, key=lambda q: q["timestamp"]) if eligible else None


def _find_exit(
    quotes: list[dict[str, Any]], candidate_at: datetime, exit_at: datetime, max_age_seconds: float
) -> dict[str, Any] | None:
    eligible = [
        q for q in quotes
        if q.get("timestamp") is not None and candidate_at < q["timestamp"] <= exit_at
        and (exit_at - q["timestamp"]).total_seconds() <= max_age_seconds
        and _valid_market(q) and _is_opra_nbbo(q)
    ]
    return max(eligible, key=lambda q: q["timestamp"]) if eligible else None


def _limit_evidence(
    policy: str,
    limit: float | None,
    quotes: list[dict[str, Any]],
    candidate_at: datetime,
    exit_at: datetime,
) -> dict[str, Any]:
    later = [
        q for q in quotes
        if q.get("timestamp") is not None and candidate_at < q["timestamp"] <= exit_at
        and _valid_market(q) and _is_opra_nbbo(q)
    ]
    event = next((q for q in sorted(later, key=lambda q: q["timestamp"]) if limit is not None and q["ask"] <= limit), None)
    return {
        "policy": policy,
        "side": "buy",
        "limit_price": round(limit, 4) if limit is not None else None,
        "quote_marketable_later": event is not None,
        "marketable_quote_timestamp": _iso(event.get("timestamp")) if event else None,
        "marketable_quote_ask": event.get("ask") if event else None,
        "seconds_to_marketable": round((event["timestamp"] - candidate_at).total_seconds(), 3) if event else None,
        "evidence": "subsequent_opra_ask_at_or_below_limit" if event else "no_subsequent_opra_ask_at_or_below_limit",
        "broker_fill_observed": False,
        "assumed_fill_price": None,
        "warning": "Quote marketability is shadow evidence, not a broker fill or queue-position claim.",
    }


def evaluate_contract(
    candidate: dict[str, Any],
    contract: str | None,
    quotes: list[dict[str, Any]],
    *,
    max_quote_age_seconds: float = 5.0,
    max_timestamp_skew_seconds: float = 5.0,
    max_spread_pct: float = 15.0,
    evaluation_minutes: int = 30,
    max_exit_quote_age_seconds: float = 5.0,
    option_tick: float = 0.01,
    stress_slippage_per_side: float = 0.02,
) -> dict[str, Any]:
    candidate_at = _candidate_time(candidate)
    candidate_id = str(candidate.get("candidate_id") or candidate.get("move_id") or candidate.get("id") or "")
    if not candidate_id:
        fingerprint = json.dumps(candidate, sort_keys=True, default=str, separators=(",", ":"))
        candidate_id = hashlib.sha256(fingerprint.encode("utf-8")).hexdigest()[:20]
    selected_at = _parse_ts(candidate.get("contract_selected_at")) or candidate_at
    deadline = _first_ts(candidate, ("evaluation_end_at", "exit_deadline", "exit_at", "resolved_at"))
    if deadline is None and candidate_at is not None:
        deadline = candidate_at + timedelta(minutes=evaluation_minutes)

    blockers: list[str] = []
    if candidate_at is None:
        blockers.append("missing_candidate_timestamp")
    if contract is None:
        blockers.append("missing_exact_occ_contract")
    if candidate_at and selected_at and selected_at > candidate_at:
        blockers.append("contract_selected_after_candidate")

    contract_quotes = quotes if contract is None else [q for q in quotes if q.get("contract") == contract]
    arrival = _find_arrival(contract_quotes, candidate_at) if candidate_at else None
    candidate_underlying_at = _underlying_timestamp(candidate)
    if arrival is not None and arrival.get("underlying_timestamp") is None:
        arrival = dict(arrival)
        arrival["underlying_timestamp"] = candidate_underlying_at
    arrival_metrics = _quote_metrics(arrival, candidate_at) if arrival is not None and candidate_at else None

    if arrival is None:
        blockers.append("missing_point_in_time_quote")
    else:
        if arrival.get("provider_status") == "unavailable":
            blockers.append("provider_unavailable")
        if not _is_opra_nbbo(arrival):
            blockers.append("quote_not_opra_nbbo")
        if not _valid_market(arrival):
            blockers.append("invalid_bid_ask")
        age = arrival_metrics.get("quote_age_seconds") if arrival_metrics else None
        if age is None or age < 0 or age > max_quote_age_seconds:
            blockers.append("stale_arrival_quote")
        if arrival.get("trade_timestamp") and arrival["trade_timestamp"] > candidate_at:
            blockers.append("future_last_trade_timestamp")
        if arrival.get("greeks_timestamp") and arrival["greeks_timestamp"] > candidate_at:
            blockers.append("future_greeks_timestamp")
        if arrival.get("underlying_timestamp") and arrival["underlying_timestamp"] > candidate_at:
            blockers.append("future_underlying_timestamp")
        skew = arrival_metrics.get("underlying_option_timestamp_skew_seconds") if arrival_metrics else None
        if skew is None:
            blockers.append("missing_underlying_timestamp")
        elif skew > max_timestamp_skew_seconds:
            blockers.append("underlying_option_timestamp_skew")
        spread_pct = arrival_metrics.get("spread_pct_midpoint") if arrival_metrics else None
        if spread_pct is None or spread_pct > max_spread_pct:
            blockers.append("spread_too_wide")

    entry_feasible = not blockers
    exit_quote = _find_exit(contract_quotes, candidate_at, deadline, max_exit_quote_age_seconds) if candidate_at and deadline else None
    exit_metrics = _quote_metrics(exit_quote, deadline) if exit_quote is not None and deadline else None
    entry_ask = arrival.get("ask") if entry_feasible and arrival else None
    exit_bid = exit_quote.get("bid") if exit_quote else None
    quoted_cost = None
    gross_return = None
    stressed_cost = None
    if entry_feasible and exit_metrics and entry_ask is not None and exit_bid is not None:
        entry_half = entry_ask - arrival_metrics["midpoint"]
        exit_half = exit_metrics["midpoint"] - exit_bid
        quoted_cost = entry_half + exit_half
        stressed_cost = quoted_cost + (2.0 * stress_slippage_per_side)
        gross_return = exit_bid - entry_ask

    midpoint = arrival_metrics.get("midpoint") if entry_feasible and arrival_metrics else None
    bid = arrival.get("bid") if entry_feasible and arrival else None
    # A midpoint ending between valid ticks is rounded down for a resting buy;
    # never emit a price that could not be submitted to a venue.
    if midpoint is not None and option_tick > 0:
        midpoint = math.floor((midpoint + 1e-12) / option_tick) * option_tick
    one_tick = min(bid + option_tick, entry_ask) if bid is not None and entry_ask is not None else None
    limits = []
    if entry_feasible and candidate_at and deadline:
        limits = [
            _limit_evidence("arrival_mid", midpoint, contract_quotes, candidate_at, deadline),
            _limit_evidence("arrival_bid_plus_one_tick", one_tick, contract_quotes, candidate_at, deadline),
        ]

    reason = blockers[0] if blockers else None
    record = {
        "schema_version": SCHEMA_VERSION,
        "record_type": "aplus_contract_feasibility",
        "candidate_id": candidate_id,
        "move_id": candidate.get("move_id"),
        "date": candidate.get("date") or (_iso(candidate_at) or "")[:10] or None,
        "symbol": candidate.get("underlying_symbol") or candidate.get("instrument")
        or (candidate.get("underlying") if isinstance(candidate.get("underlying"), str) else None)
        or _occ_root(contract),
        "contract": contract,
        "candidate_at": _iso(candidate_at),
        "contract_selected_at": _iso(selected_at),
        "contract_frozen_at_candidate": bool(contract and candidate_at and selected_at and selected_at <= candidate_at),
        "data_status": "available" if entry_feasible else "unavailable",
        "feasible": entry_feasible,
        "reason": reason,
        "blockers": blockers,
        "arrival_quote": arrival_metrics,
        "evaluation_end_at": _iso(deadline),
        "exit_quote": exit_metrics,
        "executable_round_trip": {
            "entry_side": "buy_at_ask",
            "entry_ask": entry_ask,
            "exit_side": "sell_at_bid",
            "exit_bid": exit_bid,
            "observed": gross_return is not None,
            "gross_return_dollars_per_share": round(gross_return, 4) if gross_return is not None else None,
            "gross_return_dollars_per_contract": round(gross_return * 100, 2) if gross_return is not None else None,
            "quoted_half_spread_cost_dollars_per_share": round(quoted_cost, 4) if quoted_cost is not None else None,
            "stressed_round_trip_cost_dollars_per_share": round(stressed_cost, 4) if stressed_cost is not None else None,
            "stressed_round_trip_cost_dollars_per_contract": round(stressed_cost * 100, 2) if stressed_cost is not None else None,
            "stress_slippage_per_side": stress_slippage_per_side,
        },
        "shadow_resting_limits": limits,
        "execution_enabled": False,
        "can_submit_orders": False,
        "authority": "shadow_evidence_only",
        "warnings": [
            "No order was submitted.",
            "Subsequent quote marketability does not prove a broker fill or queue priority.",
            "No midpoint execution is assumed.",
        ],
    }
    return record


def build_records(candidates: Iterable[dict[str, Any]], quotes: Iterable[dict[str, Any]], **kwargs: Any) -> list[dict[str, Any]]:
    normalised = [q for row in quotes if (q := _normalise_quote(row)) is not None]
    by_contract: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for quote in normalised:
        by_contract[quote["contract"]].append(quote)
    for rows in by_contract.values():
        rows.sort(key=lambda item: item.get("timestamp") or datetime.min.replace(tzinfo=UTC))

    output: list[dict[str, Any]] = []
    for candidate in candidates:
        if candidate.get("type") not in (None, "candidate", "aplus_candidate"):
            continue
        contracts = _candidate_contracts(candidate)
        if not contracts:
            output.append(evaluate_contract(candidate, None, [], **kwargs))
            continue
        for contract in contracts:
            output.append(evaluate_contract(candidate, contract, by_contract.get(contract, []), **kwargs))
    return output


def build_summary(records: list[dict[str, Any]], *, candidates_path: Path, quotes_path: Path) -> dict[str, Any]:
    blockers = Counter(blocker for record in records for blocker in record.get("blockers") or [])
    policies: dict[str, dict[str, int]] = defaultdict(lambda: {"evaluated": 0, "marketable_later": 0})
    for record in records:
        for policy in record.get("shadow_resting_limits") or []:
            name = str(policy.get("policy"))
            policies[name]["evaluated"] += 1
            if policy.get("quote_marketable_later") is True:
                policies[name]["marketable_later"] += 1
    available = sum(record.get("feasible") is True for record in records)
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at": _iso(datetime.now(UTC)),
        "provider": "aplus_contract_feasibility",
        "mode": "shadow_only",
        "execution_enabled": False,
        "can_submit_orders": False,
        "record_count": len(records),
        "available_count": available,
        "unavailable_count": len(records) - available,
        "availability_rate": round(available / len(records), 4) if records else None,
        "round_trip_observed_count": sum(bool(r["executable_round_trip"]["observed"]) for r in records),
        "blocker_counts": dict(sorted(blockers.items())),
        "shadow_limit_policy_counts": dict(policies),
        "inputs": {"candidates_path": str(candidates_path), "quotes_path": str(quotes_path)},
        "warning": "Quote crossings are shadow evidence, not broker fills. No midpoint fills are assumed.",
    }


def _write_jsonl(path: Path, records: Iterable[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8") as handle:
        for record in records:
            handle.write(json.dumps(record, sort_keys=True, allow_nan=False) + "\n")
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, sort_keys=True, allow_nan=False)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidates", type=Path, default=DEFAULT_CANDIDATES)
    parser.add_argument("--quotes", type=Path, default=DEFAULT_QUOTES)
    parser.add_argument("--sidecar", type=Path, default=DEFAULT_SIDECAR)
    parser.add_argument("--summary", type=Path, default=DEFAULT_SUMMARY)
    parser.add_argument("--max-quote-age-seconds", type=float, default=5.0)
    parser.add_argument("--max-timestamp-skew-seconds", type=float, default=5.0)
    parser.add_argument("--max-spread-pct", type=float, default=15.0)
    parser.add_argument("--evaluation-minutes", type=int, default=30)
    parser.add_argument("--max-exit-quote-age-seconds", type=float, default=5.0)
    parser.add_argument("--option-tick", type=float, default=0.01)
    parser.add_argument("--stress-slippage-per-side", type=float, default=0.02)
    parser.add_argument("--print", action="store_true", dest="do_print")
    args = parser.parse_args()
    records = build_records(
        _read_jsonl(args.candidates),
        _read_jsonl(args.quotes),
        max_quote_age_seconds=args.max_quote_age_seconds,
        max_timestamp_skew_seconds=args.max_timestamp_skew_seconds,
        max_spread_pct=args.max_spread_pct,
        evaluation_minutes=args.evaluation_minutes,
        max_exit_quote_age_seconds=args.max_exit_quote_age_seconds,
        option_tick=args.option_tick,
        stress_slippage_per_side=args.stress_slippage_per_side,
    )
    summary = build_summary(records, candidates_path=args.candidates, quotes_path=args.quotes)
    _write_jsonl(args.sidecar, records)
    _write_json(args.summary, summary)
    if args.do_print:
        print(json.dumps(summary, indent=2, sort_keys=True))
    else:
        print(
            f"A+ contract feasibility: records={summary['record_count']} "
            f"available={summary['available_count']} unavailable={summary['unavailable_count']}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

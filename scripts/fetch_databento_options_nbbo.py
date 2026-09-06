#!/usr/bin/env python3
"""Cost-guarded, candidate-scoped Databento OPRA CBBO acquisition."""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
import sys
import time as time_module
from copy import deepcopy
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

DATASET = "OPRA.PILLAR"
SCHEMA = "cbbo-1s"
SCOPE = "databento_opra_cbbo_1s"
FALLBACK_UNIT_PRICE_USD_PER_GIB = 2.0
DEFAULT_CANDIDATES = ROOT / "data" / "options_shadow_twin_log.jsonl"
DEFAULT_OUTPUT = ROOT / "data" / "databento" / "options_nbbo_candidate_quotes.jsonl"
DEFAULT_MANIFEST = ROOT / "data" / "databento_options_nbbo_manifest.json"
DEFAULT_RESULTS = ROOT / "data" / "options_nbbo_curriculum_results.json"
DEFAULT_LEDGER = Path.home() / ".vibe-trading" / "data" / "databento_call_ledger.jsonl"
DEFAULT_SESSION_CACHE = Path.home() / ".vibe-trading" / "cache" / "databento_options_nbbo"
DEFAULT_DAILY_USD_BUDGET = 5.0
CACHE_TTL_SECONDS = 60.0
OCC_PATTERN = re.compile(r"^([A-Z]{1,6})(\d{6}[CP]\d{8})$")
_SESSION_CACHE: dict[str, tuple[datetime, dict[str, Any]]] = {}


@dataclass(frozen=True)
class RequestSpec:
    symbols: tuple[str, ...]
    start: str
    end: str


@dataclass(frozen=True)
class CostEstimate:
    cost_usd: float
    billable_bytes: int
    unit_price_usd_per_gib: float
    unit_price_source: str


def _parse_ts(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _number(value: Any) -> float | None:
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    return out if math.isfinite(out) else None


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows = []
    for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(row, dict):
            rows.append(row)
    return rows


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def unresolved_candidate_rows(
    rows: Iterable[dict[str, Any]],
    results: dict[str, Any],
) -> list[dict[str, Any]]:
    resolved_ids = {
        str(row.get("candidate_id") or "")
        for row in (results.get("outcomes") or [])
        if isinstance(row, dict) and row.get("status") == "resolved"
    }
    return [
        row for row in rows
        if row.get("type") == "candidate"
        and str(row.get("candidate_id") or "") not in resolved_ids
    ]


def existing_symbol_coverage(path: Path) -> dict[str, datetime]:
    coverage: dict[str, datetime] = {}
    for row in _read_jsonl(path):
        symbol = compact_occ(str(row.get("symbol") or ""))
        observed = _parse_ts(row.get("observed_at"))
        if not symbol or observed is None:
            continue
        if symbol not in coverage or observed > coverage[symbol]:
            coverage[symbol] = observed
    return coverage


def _load_api_key() -> str:
    key = os.getenv("DATABENTO_API_KEY", "").strip()
    if key:
        return key
    env_path = ROOT / "agent" / ".env"
    if env_path.exists():
        for raw in env_path.read_text(encoding="utf-8", errors="ignore").splitlines():
            if raw.startswith("DATABENTO_API_KEY="):
                key = raw.split("=", 1)[1].strip()
                if key:
                    return key
    raise RuntimeError("DATABENTO_API_KEY is not configured")


def _configured_api_key() -> str | None:
    try:
        return _load_api_key()
    except RuntimeError:
        return None


def daily_budget_usd() -> float:
    raw = os.getenv("DATABENTO_DAILY_USD_BUDGET", str(DEFAULT_DAILY_USD_BUDGET)).strip()
    value = _number(raw)
    if value is None or value < 0:
        return DEFAULT_DAILY_USD_BUDGET
    return value


def _ledger_rows(path: Path) -> list[dict[str, Any]]:
    return _read_jsonl(path)


def daily_spend_usd(path: Path = DEFAULT_LEDGER, *, now: datetime | None = None) -> float:
    day = (now or datetime.now(timezone.utc)).astimezone(timezone.utc).date()
    total = 0.0
    for row in _ledger_rows(path):
        stamp = _parse_ts(row.get("timestamp"))
        cost = _number(row.get("cost_usd"))
        if stamp is not None and stamp.date() == day and cost is not None and row.get("billable") is True:
            total += max(0.0, cost)
    return round(total, 9)


def _append_ledger(path: Path, row: dict[str, Any]) -> None:
    """Append one sanitized audit row. Payloads and credentials are never written."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(row, sort_keys=True, separators=(",", ":"), allow_nan=False) + "\n")


def _error_class(exc: BaseException) -> str:
    name = type(exc).__name__ or "provider_error"
    return re.sub(r"[^A-Za-z0-9_.-]", "_", name)[:80]


def _failure_status(exc: BaseException) -> str:
    name = type(exc).__name__.lower()
    status_code = getattr(exc, "status_code", None) or getattr(exc, "status", None)
    if isinstance(status_code, int) and 100 <= status_code <= 599:
        return f"http_{status_code}"
    if "timeout" in name:
        return "timeout"
    return "missing"


def _canonical_hash(rows: list[dict[str, Any]]) -> str:
    body = json.dumps(rows, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    return hashlib.sha256(body).hexdigest()


def _cache_file(cache_dir: Path, fingerprint: str) -> Path:
    return cache_dir / f"{fingerprint}.json"


def _read_fresh_cache(
    fingerprint: str,
    *,
    cache_dir: Path,
    now: datetime,
    ttl_seconds: float,
) -> dict[str, Any] | None:
    memory_key = f"{cache_dir.resolve()}::{fingerprint}"
    memory = _SESSION_CACHE.get(memory_key)
    if memory and 0 <= (now - memory[0]).total_seconds() <= ttl_seconds:
        return deepcopy(memory[1])
    path = _cache_file(cache_dir, fingerprint)
    payload = _read_json(path)
    cached_at = _parse_ts(payload.get("cached_at"))
    response = payload.get("response")
    if cached_at is None or not isinstance(response, dict):
        return None
    if not 0 <= (now - cached_at).total_seconds() <= ttl_seconds:
        return None
    _SESSION_CACHE[memory_key] = (cached_at, response)
    return deepcopy(response)


def _write_session_cache(
    fingerprint: str,
    response: dict[str, Any],
    *,
    cache_dir: Path,
    now: datetime,
) -> None:
    # This is a local, expiring normalized quote cache, not a raw provider payload.
    memory_key = f"{cache_dir.resolve()}::{fingerprint}"
    _SESSION_CACHE[memory_key] = (now, deepcopy(response))
    _write_json(
        _cache_file(cache_dir, fingerprint),
        {"cached_at": _iso(now), "response": response},
    )


def _audit_base(spec: RequestSpec, *, now: datetime) -> dict[str, Any]:
    return {
        "timestamp": _iso(now),
        "dataset": DATASET,
        "schema": SCHEMA,
        "requested_dataset": DATASET,
        "requested_schema": SCHEMA,
        "returned_dataset": None,
        "returned_schema": None,
        "symbols": list(spec.symbols),
        "start": spec.start,
        "end": spec.end,
        "timeframe": {"start": spec.start, "end": spec.end},
        "request_fingerprint": request_fingerprint(spec),
        "execution_enabled": False,
        "can_submit_orders": False,
    }


def fetch_options_nbbo(
    spec: RequestSpec,
    *,
    client: Any | None = None,
    client_factory: Any | None = None,
    ledger_path: Path = DEFAULT_LEDGER,
    cache_dir: Path = DEFAULT_SESSION_CACHE,
    now: datetime | None = None,
    daily_budget: float | None = None,
    cache_ttl_seconds: float = CACHE_TTL_SECONDS,
) -> dict[str, Any]:
    """Fetch normalized OPRA CBBO data behind cache and a hard daily budget.

    The response deliberately contains only fields verified in the CBBO schema.
    IV, Greeks, OI, and inferred aggressor side must be supplied by independent
    sources and are never synthesized here.
    """
    called_at = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    base = _audit_base(spec, now=called_at)
    fingerprint = str(base["request_fingerprint"])
    cached = _read_fresh_cache(
        fingerprint,
        cache_dir=cache_dir,
        now=called_at,
        ttl_seconds=max(0.0, cache_ttl_seconds),
    )
    if cached is not None:
        cached.update({
            "status": "ok",
            "cache_hit": True,
            "cost_usd": 0.0,
            "projected_cost_usd": 0.0,
            "daily_cost_usd": daily_spend_usd(ledger_path, now=called_at),
            "latency_ms": 0.0,
        })
        return cached

    key = _configured_api_key()
    if client is None and key is None:
        return {
            **base,
            "status": "not_configured",
            "error_class": "missing_api_key",
            "rows": [],
            "cache_hit": False,
            "cost_usd": 0.0,
            "projected_cost_usd": None,
            "daily_cost_usd": daily_spend_usd(ledger_path, now=called_at),
            "latency_ms": 0.0,
            "response_hash": None,
            "bytes": 0,
        }

    started = time_module.perf_counter()
    estimate: CostEstimate | None = None
    fetch_attempted = False
    try:
        if client is None:
            if client_factory is None:
                import databento as db

                client_factory = db.Historical
            client = client_factory(key)
        estimate = estimate_cost(client, spec)
        spent = daily_spend_usd(ledger_path, now=called_at)
        budget = daily_budget_usd() if daily_budget is None else max(0.0, float(daily_budget))
        projected = spent + estimate.cost_usd
        if projected > budget:
            latency_ms = round((time_module.perf_counter() - started) * 1000, 3)
            ledger = {
                **base,
                "status": "budget_exceeded",
                "error_class": None,
                "billable": False,
                "cache_hit": False,
                "projected_cost_usd": round(estimate.cost_usd, 9),
                "daily_cost_usd": spent,
                "daily_budget_usd": budget,
                "cost_usd": 0.0,
                "bytes": estimate.billable_bytes,
                "credits_consumed": None,
                "latency_ms": latency_ms,
                "response_hash": None,
            }
            _append_ledger(ledger_path, ledger)
            return {**ledger, "rows": []}

        fetch_attempted = True
        store = client.timeseries.get_range(**request_kwargs(spec))
        normalized, audit = normalize_cbbo_frame(
            store.to_df(),
            fingerprint=fingerprint,
            cache=_cache_file(cache_dir, fingerprint),
        )
        response_hash = _canonical_hash(normalized)
        latency_ms = round((time_module.perf_counter() - started) * 1000, 3)
        status = "ok" if normalized else "missing"
        ledger = {
            **base,
            "returned_dataset": DATASET,
            "returned_schema": SCHEMA,
            "status": status,
            "error_class": None if normalized else "empty_normalized_response",
            "billable": True,
            "cache_hit": False,
            "projected_cost_usd": round(estimate.cost_usd, 9),
            "daily_cost_usd": round(spent + estimate.cost_usd, 9),
            "daily_budget_usd": budget,
            "cost_usd": round(estimate.cost_usd, 9),
            "bytes": estimate.billable_bytes,
            "credits_consumed": None,
            "latency_ms": latency_ms,
            "response_hash": response_hash,
            "response_hash_basis": "canonical_normalized_nbbo_rows",
            "returned_rows": len(normalized),
        }
        _append_ledger(ledger_path, ledger)
        response = {**ledger, "rows": normalized, "normalization_audit": audit}
        if status == "ok":
            _write_session_cache(fingerprint, response, cache_dir=cache_dir, now=called_at)
        return response
    except Exception as exc:  # provider exception hierarchy varies by SDK release
        latency_ms = round((time_module.perf_counter() - started) * 1000, 3)
        status = _failure_status(exc)
        spent = daily_spend_usd(ledger_path, now=called_at)
        conservative_cost = estimate.cost_usd if estimate is not None and fetch_attempted else 0.0
        ledger = {
            **base,
            "status": status,
            "error_class": _error_class(exc),
            # Once a data request was dispatched, reserve its projected cost even
            # when the response times out. This may overcount, but cannot breach
            # the user's hard daily cap through optimistic accounting.
            "billable": bool(fetch_attempted and estimate is not None),
            "cache_hit": False,
            "projected_cost_usd": round(estimate.cost_usd, 9) if estimate else None,
            "daily_cost_usd": round(spent + conservative_cost, 9),
            "daily_budget_usd": daily_budget_usd() if daily_budget is None else max(0.0, float(daily_budget)),
            "cost_usd": round(conservative_cost, 9),
            "bytes": estimate.billable_bytes if estimate else 0,
            "credits_consumed": None,
            "latency_ms": latency_ms,
            "response_hash": None,
        }
        _append_ledger(ledger_path, ledger)
        return {**ledger, "rows": []}


def compact_occ(symbol: str) -> str:
    return str(symbol or "").replace(" ", "").upper()


def padded_opra_symbol(symbol: str) -> str:
    compact = compact_occ(symbol)
    match = OCC_PATTERN.fullmatch(compact)
    if not match:
        raise ValueError(f"invalid OCC symbol: {symbol}")
    root, suffix = match.groups()
    return f"{root:<6}{suffix}"


def extract_candidate_spec(
    rows: Iterable[dict[str, Any]],
    *,
    end: datetime | None = None,
    now: datetime | None = None,
    availability_end: datetime | None = None,
) -> RequestSpec:
    candidates = [row for row in rows if row.get("type") == "candidate"]
    symbols = sorted({
        padded_opra_symbol(str(leg.get("symbol") or ""))
        for row in candidates
        for leg in (row.get("legs") or [])
        if isinstance(leg, dict) and leg.get("symbol")
    })
    starts = [
        stamp for stamp in (_parse_ts(row.get("created_at")) for row in candidates)
        if stamp is not None
    ]
    candidate_ends = [
        stamp for stamp in (
            _parse_ts(row.get("evaluation_end_at") or row.get("exit_deadline"))
            for row in candidates
        ) if stamp is not None
    ]
    expiries = []
    for row in candidates:
        try:
            expiry = datetime.fromisoformat(str(row.get("expiry"))).replace(
                hour=20, minute=0, tzinfo=timezone.utc
            )
        except ValueError:
            continue
        expiries.append(expiry)
    if not symbols or not starts:
        raise ValueError("no candidate OCC contracts with valid timestamps")
    now = now or datetime.now(timezone.utc)
    availability_cutoff = now - timedelta(minutes=30)
    requested_end = end or max(candidate_ends or expiries or [availability_cutoff])
    boundaries = [requested_end, availability_cutoff]
    if availability_end is not None:
        boundaries.append(availability_end)
    final_end = min(boundaries)
    start = min(starts) - timedelta(seconds=5)
    if final_end <= start:
        raise ValueError("historical availability cutoff does not extend beyond candidate start")
    return RequestSpec(tuple(symbols), _iso(start), _iso(final_end))


def incremental_candidate_spec(
    rows: Iterable[dict[str, Any]],
    coverage: dict[str, datetime],
    *,
    end: datetime | None = None,
    now: datetime | None = None,
    availability_end: datetime | None = None,
) -> RequestSpec:
    candidates = [row for row in rows if row.get("type") == "candidate"]
    base = extract_candidate_spec(
        candidates,
        end=end,
        now=now,
        availability_end=availability_end,
    )
    starts: list[datetime] = []
    for candidate in candidates:
        created = _parse_ts(candidate.get("created_at"))
        if created is None:
            continue
        for leg in candidate.get("legs") or []:
            if not isinstance(leg, dict) or not leg.get("symbol"):
                continue
            compact = compact_occ(str(leg["symbol"]))
            covered_through = coverage.get(compact)
            candidate_start = created - timedelta(seconds=5)
            starts.append(
                max(candidate_start, covered_through - timedelta(seconds=2))
                if covered_through is not None
                else candidate_start
            )
    if not starts:
        raise ValueError("no incremental candidate coverage starts")
    incremental_start = min(starts)
    final_end = _parse_ts(base.end)
    if final_end is None or final_end <= incremental_start:
        raise ValueError("no_new_provider_interval")
    return RequestSpec(base.symbols, _iso(incremental_start), base.end)


def request_kwargs(spec: RequestSpec) -> dict[str, Any]:
    return {
        "dataset": DATASET,
        "schema": SCHEMA,
        "symbols": list(spec.symbols),
        "stype_in": "raw_symbol",
        "start": spec.start,
        "end": spec.end,
    }


def request_fingerprint(spec: RequestSpec) -> str:
    payload = json.dumps(request_kwargs(spec), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


def cache_path_for(spec: RequestSpec, cache_dir: Path) -> Path:
    return cache_dir / f"opra_cbbo1s_candidates_{request_fingerprint(spec)}.dbn.zst"


def _with_retries(operation: Any, *, attempts: int = 3) -> Any:
    error: Exception | None = None
    for attempt in range(attempts):
        try:
            return operation()
        except Exception as exc:  # provider errors vary by client release
            error = exc
            if attempt + 1 < attempts:
                time_module.sleep(1.0 * (attempt + 1))
    assert error is not None
    raise error


def estimate_cost(client: Any, spec: RequestSpec) -> CostEstimate:
    billable = int(_with_retries(lambda: client.metadata.get_billable_size(**request_kwargs(spec))))
    if billable < 0:
        raise RuntimeError(f"invalid Databento billable size: {billable}")
    unit_price = FALLBACK_UNIT_PRICE_USD_PER_GIB
    source = "frozen_official_opra_unit_price_2026-08-03"
    cost = billable / (1024 ** 3) * unit_price
    return CostEstimate(cost, billable, unit_price, source)


def enforce_cost_guard(cost: float, max_cost: float) -> None:
    if not math.isfinite(cost) or cost < 0:
        raise RuntimeError(f"invalid Databento cost estimate: {cost}")
    if cost > max_cost:
        raise RuntimeError(f"Estimated cost ${cost:.2f} exceeds --max-cost ${max_cost:.2f}")


def cheapest_budget_candidate(
    rows: Iterable[dict[str, Any]],
    *,
    build_spec: Any,
    estimate: Any,
    max_cost: float,
) -> tuple[dict[str, Any] | None, RequestSpec | None, CostEstimate | None]:
    """Choose one unresolved candidate that fits a hard incremental budget."""
    choices = []
    for row in rows:
        try:
            spec = build_spec(row)
            cost = estimate(spec)
        except ValueError:
            continue
        if math.isfinite(cost.cost_usd):
            choices.append((cost.cost_usd, str(row.get("created_at") or ""), row, spec, cost))
    if not choices:
        return None, None, None
    _, _, row, spec, cost = min(choices, key=lambda item: (item[0], item[1]))
    if cost.cost_usd > max_cost:
        return None, spec, cost
    return row, spec, cost


def normalize_cbbo_frame(frame: Any, *, fingerprint: str, cache: Path) -> tuple[list[dict[str, Any]], dict[str, int]]:
    import pandas as pd

    required = {"symbol", "bid_px_00", "ask_px_00"}
    missing = required.difference(frame.columns)
    if missing:
        raise ValueError(f"Databento CBBO frame missing columns: {sorted(missing)}")
    data = frame.copy()
    observed = pd.to_datetime(data.index, utc=True, errors="coerce")
    output: list[dict[str, Any]] = []
    audit = {"input_rows": len(data), "invalid_timestamp": 0, "invalid_symbol": 0, "invalid_market": 0, "output_rows": 0}
    for position, (_, row) in enumerate(data.iterrows()):
        stamp = observed[position]
        if pd.isna(stamp):
            audit["invalid_timestamp"] += 1
            continue
        symbol = compact_occ(str(row.get("symbol") or ""))
        if not OCC_PATTERN.fullmatch(symbol):
            audit["invalid_symbol"] += 1
            continue
        bid = _number(row.get("bid_px_00"))
        ask = _number(row.get("ask_px_00"))
        if bid is None or ask is None or bid <= 0 or ask < bid:
            audit["invalid_market"] += 1
            continue
        output.append({
            "schema_version": 1,
            "symbol": symbol,
            "observed_at": stamp.isoformat().replace("+00:00", "Z"),
            "quote_timestamp": stamp.isoformat().replace("+00:00", "Z"),
            "bid": bid,
            "ask": ask,
            "bid_size": _number(row.get("bid_sz_00")),
            "ask_size": _number(row.get("ask_sz_00")),
            "quote_scope": SCOPE,
            "provenance": {
                "provider": "databento",
                "dataset": DATASET,
                "schema": SCHEMA,
                "request_fingerprint": fingerprint,
                "cache": str(cache),
                "licensed_consolidated_nbbo": True,
            },
            "execution_enabled": False,
            "can_submit_orders": False,
        })
    audit["output_rows"] = len(output)
    return output, audit


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _write_jsonl(path: Path, rows: Iterable[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    with temp.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, sort_keys=True, separators=(",", ":"), allow_nan=False) + "\n")
    os.replace(temp, path)


def merge_normalized_rows(path: Path, new_rows: Iterable[dict[str, Any]]) -> tuple[list[dict[str, Any]], int]:
    existing = _read_jsonl(path)
    combined: dict[tuple[str, str], dict[str, Any]] = {
        (str(row.get("symbol") or ""), str(row.get("observed_at") or "")): row
        for row in existing
        if row.get("symbol") and row.get("observed_at")
    }
    before = len(combined)
    for row in new_rows:
        key = (str(row.get("symbol") or ""), str(row.get("observed_at") or ""))
        if all(key):
            combined[key] = row
    merged = sorted(combined.values(), key=lambda row: (str(row["observed_at"]), str(row["symbol"])))
    return merged, len(combined) - before


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(payload, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")
    os.replace(temp, path)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidates", type=Path, default=DEFAULT_CANDIDATES)
    parser.add_argument("--end", help="Optional ISO end; still capped at the 30-minute historical cutoff")
    parser.add_argument("--download", action="store_true")
    parser.add_argument("--max-cost", type=float, default=2.0)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--cache-dir", type=Path, default=ROOT / "data" / "databento")
    parser.add_argument("--incremental", action="store_true")
    parser.add_argument("--results", type=Path, default=DEFAULT_RESULTS)
    args = parser.parse_args()

    import databento as db

    rows = _read_jsonl(args.candidates)
    if args.incremental:
        rows = unresolved_candidate_rows(rows, _read_json(args.results))
        if not rows:
            print(json.dumps({
                "mode": "no_op",
                "reason": "no_unresolved_candidates",
                "execution_enabled": False,
                "can_submit_orders": False,
            }, indent=2))
            return 0
    client = db.Historical(_load_api_key())
    dataset_range = client.metadata.get_dataset_range(dataset=DATASET)
    schema_range = (dataset_range.get("schema") or {}).get(SCHEMA) or {}
    availability_end = _parse_ts(schema_range.get("end") or dataset_range.get("end"))
    if availability_end is None:
        raise RuntimeError(f"Databento did not return an availability end for {DATASET}/{SCHEMA}")
    coverage = existing_symbol_coverage(args.output)
    spec = None
    cost_estimate = None
    if args.incremental and args.download:
        selected, cheapest_spec, cheapest_cost = cheapest_budget_candidate(
            rows,
            build_spec=lambda row: incremental_candidate_spec(
                [row],
                coverage,
                end=_parse_ts(args.end),
                availability_end=availability_end,
            ),
            estimate=lambda candidate_spec: estimate_cost(client, candidate_spec),
            max_cost=args.max_cost,
        )
        if selected is None:
            print(json.dumps({
                "mode": "no_op",
                "reason": "no_incremental_candidate_fits_budget",
                "max_cost_usd": args.max_cost,
                "cheapest_estimated_cost_usd": round(cheapest_cost.cost_usd, 6) if cheapest_cost else None,
                "cheapest_spec": asdict(cheapest_spec) if cheapest_spec else None,
                "execution_enabled": False,
                "can_submit_orders": False,
            }, indent=2))
            return 0
        rows = [selected]
        spec = cheapest_spec
        cost_estimate = cheapest_cost
    try:
        spec = spec or (
            incremental_candidate_spec(
                rows,
                coverage,
                end=_parse_ts(args.end),
                availability_end=availability_end,
            )
            if args.incremental
            else extract_candidate_spec(
                rows,
                end=_parse_ts(args.end),
                availability_end=availability_end,
            )
        )
    except ValueError as exc:
        if str(exc) != "no_new_provider_interval":
            raise
        print(json.dumps({
            "mode": "no_op",
            "reason": "no_new_provider_interval",
            "execution_enabled": False,
            "can_submit_orders": False,
        }, indent=2))
        return 0
    fingerprint = request_fingerprint(spec)
    cache = cache_path_for(spec, args.cache_dir)
    cost_estimate = cost_estimate or estimate_cost(client, spec)
    cost = cost_estimate.cost_usd
    preview = {
        "mode": "estimate",
        "dataset": DATASET,
        "schema": SCHEMA,
        "candidate_path": str(args.candidates),
        "candidate_sha256": _sha256(args.candidates),
        "spec": asdict(spec),
        "request_fingerprint": fingerprint,
        "estimated_cost_usd": round(cost, 6),
        "billable_bytes": cost_estimate.billable_bytes,
        "unit_price_usd_per_gib": cost_estimate.unit_price_usd_per_gib,
        "unit_price_source": cost_estimate.unit_price_source,
        "provider_availability_end": _iso(availability_end),
        "cache": str(cache),
        "cache_exists": cache.exists(),
        "execution_enabled": False,
        "can_submit_orders": False,
    }
    print(json.dumps(preview, indent=2))
    if not args.download:
        print("Estimate only. Re-run with --download after reviewing the amount.")
        return 0
    enforce_cost_guard(cost, args.max_cost)
    cache.parent.mkdir(parents=True, exist_ok=True)
    if cache.exists():
        store = db.DBNStore.from_file(cache)
        cache_reused = True
    else:
        store = client.timeseries.get_range(**request_kwargs(spec), path=cache)
        cache_reused = False
    normalized, audit = normalize_cbbo_frame(store.to_df(), fingerprint=fingerprint, cache=cache)
    newly_merged_rows = len(normalized)
    if args.incremental:
        output_rows, newly_merged_rows = merge_normalized_rows(args.output, normalized)
    else:
        output_rows = normalized
    _write_jsonl(args.output, output_rows)
    manifest = {
        **preview,
        "mode": "downloaded",
        "cache_reused": cache_reused,
        "cache_bytes": cache.stat().st_size,
        "cache_sha256": _sha256(cache),
        "output": str(args.output),
        "output_sha256": _sha256(args.output),
        "normalization_audit": audit,
        "incremental": args.incremental,
        "newly_merged_rows": newly_merged_rows,
        "cumulative_output_rows": len(output_rows),
    }
    _write_json(args.manifest, manifest)
    print(json.dumps(manifest, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

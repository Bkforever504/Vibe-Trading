#!/usr/bin/env python3
"""Fail-closed Databento MES evidence adapter.

This module has no broker or order-routing imports.  It acquires one explicit
raw MES contract at a time, normalizes historical OHLCV/BBO data, and models
marketable fills from the executable side of the quote.
"""
from __future__ import annotations

import calendar
import hashlib
import json
import math
import os
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Mapping


ROOT = Path(__file__).resolve().parents[1]
DATASET = "GLBX.MDP3"
SUPPORTED_SCHEMAS = frozenset({"ohlcv-1m", "bbo-1s", "mbo"})
SUPPORTED_INDEX_ROOTS = frozenset({"MES", "MNQ", "ES", "NQ"})
CONTRACT_MONTH_CODES = {3: "H", 6: "M", 9: "U", 12: "Z"}
DEFAULT_MAX_COST_USD = 5.0
DEFAULT_MAX_QUOTE_AGE_SECONDS = 2.0
DEFAULT_MAX_SPREAD_POINTS = 1.0
BAR_MINUTES = {"1m": 1, "2m": 2, "5m": 5, "30m": 30, "1h": 60}


@dataclass(frozen=True)
class ContractSelection:
    raw_symbol: str
    expiry: date
    roll_at: date


def load_api_key(
    *,
    environ: Mapping[str, str] | None = None,
    env_path: Path = ROOT / "agent" / ".env",
) -> str:
    """Load the credential without printing or returning its provenance."""
    source = os.environ if environ is None else environ
    key = str(source.get("DATABENTO_API_KEY", "")).strip()
    if key:
        return key
    try:
        lines = env_path.read_text(encoding="utf-8", errors="ignore").splitlines()
    except OSError:
        lines = []
    for raw in lines:
        if raw.startswith("DATABENTO_API_KEY="):
            key = raw.split("=", 1)[1].strip()
            if key:
                return key
    raise RuntimeError("DATABENTO_API_KEY is not configured")


def third_friday(year: int, month: int) -> date:
    if month not in CONTRACT_MONTH_CODES:
        raise ValueError("MES expiry month must be quarterly")
    first_weekday, _ = calendar.monthrange(year, month)
    first_friday = 1 + (calendar.FRIDAY - first_weekday) % 7
    return date(year, month, first_friday + 14)


def _quarter_sequence(start_year: int):
    year = start_year
    while True:
        for month in (3, 6, 9, 12):
            yield year, month
        year += 1


def index_future_front_contract(root: str, value: date | datetime) -> ContractSelection:
    """Select a frozen quarterly index future using the eight-day roll rule."""
    normalized_root = str(root).strip().upper()
    if normalized_root not in SUPPORTED_INDEX_ROOTS:
        raise ValueError(f"unsupported CME equity-index future root: {normalized_root}")
    session_date = value.date() if isinstance(value, datetime) else value
    for year, month in _quarter_sequence(session_date.year):
        expiry = third_friday(year, month)
        roll_at = expiry - timedelta(days=8)
        if session_date < roll_at:
            return ContractSelection(
                raw_symbol=f"{normalized_root}{CONTRACT_MONTH_CODES[month]}{year % 10}",
                expiry=expiry,
                roll_at=roll_at,
            )
    raise AssertionError("unreachable")


def mes_front_contract(value: date | datetime) -> ContractSelection:
    """Backward-compatible MES contract selector."""
    return index_future_front_contract("MES", value)


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        raise ValueError("timestamps must be timezone-aware")
    return value.astimezone(timezone.utc)


def historical_request(
    *, schema: str, start: datetime, end: datetime, root: str = "MES",
    contract_date: date | None = None,
) -> tuple[dict[str, Any], ContractSelection]:
    if schema not in SUPPORTED_SCHEMAS:
        raise ValueError(f"unsupported Databento schema: {schema}")
    start_utc, end_utc = _utc(start), _utc(end)
    if end_utc <= start_utc:
        raise ValueError("end must be after start")
    if schema == "mbo" and start_utc.time() != datetime.min.time():
        raise ValueError("MBO requests must start at midnight UTC to include the mandatory snapshot")
    first = index_future_front_contract(root, contract_date or start_utc)
    last = index_future_front_contract(root, end_utc - timedelta(microseconds=1))
    if contract_date is None and first.raw_symbol != last.raw_symbol:
        raise ValueError("request crosses the frozen eight-day index-future roll boundary")
    if contract_date is not None and end_utc.date() > first.expiry:
        raise ValueError("raw-contract context request extends beyond contract expiry")
    return (
        {
            "dataset": DATASET,
            "schema": schema,
            "symbols": first.raw_symbol,
            "stype_in": "raw_symbol",
            "start": start_utc,
            "end": end_utc,
        },
        first,
    )


def _atomic_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    partial = path.with_suffix(path.suffix + ".partial")
    partial.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    partial.replace(path)


def fetch_historical_cache(
    *,
    schema: str,
    start: datetime,
    end: datetime,
    cache_dir: Path,
    max_cost_usd: float = DEFAULT_MAX_COST_USD,
    client: Any | None = None,
    manifest_path: Path | None = None,
    reserve_cost: Callable[[float], None] | None = None,
    root: str = "MES",
    contract_date: date | None = None,
) -> dict[str, Any]:
    """Estimate first, enforce a hard cap, then atomically cache a DBN file."""
    if max_cost_usd < 0:
        raise ValueError("max_cost_usd cannot be negative")
    normalized_root = str(root).strip().upper()
    request, contract = historical_request(
        schema=schema,
        start=start,
        end=end,
        root=normalized_root,
        contract_date=contract_date,
    )
    if client is None:
        import databento as db

        client = db.Historical(load_api_key())
    estimate = float(client.metadata.get_cost(**request))
    if not math.isfinite(estimate) or estimate < 0:
        raise RuntimeError("Databento returned an invalid cost estimate")
    fingerprint = hashlib.sha256(
        json.dumps(
            {
                **request,
                "start": request["start"].isoformat(),
                "end": request["end"].isoformat(),
            },
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()[:20]
    cache = cache_dir / f"{normalized_root.lower()}_{contract.raw_symbol.lower()}_{schema}_{fingerprint}.dbn.zst"
    cache.parent.mkdir(parents=True, exist_ok=True)
    reused = cache.exists() and cache.stat().st_size > 0
    if not reused and estimate > max_cost_usd:
        raise RuntimeError(
            f"databento_cost_limit_exceeded: ${estimate:.4f} > ${max_cost_usd:.4f}"
        )
    if not reused:
        # Reserve aggregate budget before the provider call. A failed or
        # interrupted transfer may still be billable and must not permit the
        # next candidate to reuse the same allowance.
        if reserve_cost is not None:
            reserve_cost(estimate)
        partial = cache.with_suffix(cache.suffix + ".partial")
        partial.unlink(missing_ok=True)
        client.timeseries.get_range(**request, path=partial)
        if not partial.exists() or partial.stat().st_size == 0:
            partial.unlink(missing_ok=True)
            raise RuntimeError("Databento download returned an empty cache")
        partial.replace(cache)

    hasher = hashlib.sha256()
    with cache.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            hasher.update(chunk)
    digest = hasher.hexdigest().upper()
    manifest = {
        "schema_version": 1,
        "provider": "databento",
        "dataset": DATASET,
        "schema": schema,
        "root": normalized_root,
        "raw_symbol": contract.raw_symbol,
        "stype_in": "raw_symbol",
        "start": request["start"].isoformat().replace("+00:00", "Z"),
        "end": request["end"].isoformat().replace("+00:00", "Z"),
        "expiry": contract.expiry.isoformat(),
        "roll_at": contract.roll_at.isoformat(),
        "roll_policy": "eight_calendar_days_before_quarterly_third_friday_expiry",
        "contract_selected_for": contract_date.isoformat() if contract_date else None,
        "estimated_cost_usd": round(estimate, 6),
        "hard_cost_cap_usd": float(max_cost_usd),
        "cache": str(cache),
        "cache_reused": reused,
        "bytes": cache.stat().st_size,
        "sha256": digest,
        "execution_enabled": False,
        "can_submit_orders": False,
    }
    if manifest_path is not None:
        _atomic_json(manifest_path, manifest)
    return manifest


def _indexed_frame(frame: Any):
    import pandas as pd

    data = frame.copy()
    if not isinstance(data.index, pd.DatetimeIndex):
        timestamp_column = next(
            (name for name in ("ts_event", "ts_recv", "timestamp") if name in data.columns),
            None,
        )
        if timestamp_column is None:
            raise ValueError("Databento frame has no timestamp index or column")
        data.index = pd.to_datetime(data.pop(timestamp_column), utc=True)
    elif data.index.tz is None:
        data.index = data.index.tz_localize("UTC")
    else:
        data.index = data.index.tz_convert("UTC")
    if data.index.has_duplicates:
        raise ValueError("Databento frame contains duplicate timestamps")
    if not data.index.is_monotonic_increasing:
        data = data.sort_index()
    return data


def _validate_one_contract(data: Any, expected_raw_symbol: str) -> None:
    if "symbol" not in data.columns:
        raise ValueError("Databento frame missing raw symbol provenance")
    symbols = {str(value) for value in data["symbol"].dropna().unique()}
    if symbols != {expected_raw_symbol}:
        raise ValueError(
            f"Databento frame contract mismatch: expected {expected_raw_symbol}, got {sorted(symbols)}"
        )


def normalize_ohlcv_1m(frame: Any, *, expected_raw_symbol: str):
    import pandas as pd

    data = _indexed_frame(frame)
    _validate_one_contract(data, expected_raw_symbol)
    required = ("open", "high", "low", "close", "volume")
    missing = [name for name in required if name not in data.columns]
    if missing:
        raise ValueError(f"Databento OHLCV frame missing columns: {missing}")
    result = data[list(required) + ["symbol"]].copy()
    for name in required:
        result[name] = pd.to_numeric(result[name], errors="raise")
    invalid_ohlc = (
        (result["high"] < result[["open", "close", "low"]].max(axis=1))
        | (result["low"] > result[["open", "close", "high"]].min(axis=1))
    )
    if result.empty or invalid_ohlc.any() or (result["volume"] < 0).any():
        raise ValueError("Databento OHLCV frame failed integrity checks")
    return result


def resample_completed_bars(frame_1m: Any, timeframe: str, *, as_of: datetime):
    """Aggregate complete, gap-free UTC minute buckets only."""
    import pandas as pd

    if timeframe not in BAR_MINUTES:
        raise ValueError(f"unsupported timeframe: {timeframe}")
    minutes = BAR_MINUTES[timeframe]
    as_of_utc = _utc(as_of)
    data = frame_1m.copy()
    if not isinstance(data.index, pd.DatetimeIndex) or data.index.tz is None:
        raise ValueError("normalized timezone-aware OHLCV frame required")
    if timeframe == "1m":
        return data[data.index + pd.Timedelta(minutes=1) <= as_of_utc].copy()
    rule = f"{minutes}min"
    bars = data.resample(rule, label="left", closed="left").agg(
        open=("open", "first"),
        high=("high", "max"),
        low=("low", "min"),
        close=("close", "last"),
        volume=("volume", "sum"),
        symbol=("symbol", "first"),
        minute_count=("close", "count"),
    )
    bars = bars[
        (bars["minute_count"] == minutes)
        & (bars.index + pd.Timedelta(minutes=minutes) <= as_of_utc)
    ]
    return bars.drop(columns=["minute_count"])


def normalize_bbo_1s(
    frame: Any,
    *,
    expected_raw_symbol: str,
    as_of: datetime | None = None,
    max_age_seconds: float = DEFAULT_MAX_QUOTE_AGE_SECONDS,
):
    import pandas as pd

    if max_age_seconds < 0:
        raise ValueError("max_age_seconds cannot be negative")
    data = _indexed_frame(frame)
    _validate_one_contract(data, expected_raw_symbol)
    aliases = {
        "bid": "bid_px_00" if "bid_px_00" in data.columns else "bid_px",
        "ask": "ask_px_00" if "ask_px_00" in data.columns else "ask_px",
        "bid_size": "bid_sz_00" if "bid_sz_00" in data.columns else "bid_sz",
        "ask_size": "ask_sz_00" if "ask_sz_00" in data.columns else "ask_sz",
    }
    missing = [source for source in aliases.values() if source not in data.columns]
    if missing:
        raise ValueError(f"Databento BBO frame missing columns: {missing}")
    result = pd.DataFrame(
        {name: pd.to_numeric(data[source], errors="raise") for name, source in aliases.items()},
        index=data.index,
    )
    result["symbol"] = data["symbol"].astype(str)
    if result.empty or (result[["bid", "ask", "bid_size", "ask_size"]] <= 0).any().any():
        raise ValueError("Databento BBO frame contains missing or non-positive quotes")
    if (result["ask"] <= result["bid"]).any():
        raise ValueError("Databento BBO frame contains crossed or locked quotes")
    result["spread"] = result["ask"] - result["bid"]
    result["evidence_tier"] = "databento_bbo_diagnostic"
    result["promotion_eligible"] = False
    if as_of is not None:
        age = (_utc(as_of) - result.index[-1].to_pydatetime()).total_seconds()
        if age < 0 or age > max_age_seconds:
            raise ValueError("Databento BBO quote is stale or from the future")
    return result


def _record_value(record: Any, name: str, default: Any = None) -> Any:
    if isinstance(record, Mapping):
        return record.get(name, default)
    return getattr(record, name, default)


def build_mbo_quote_frame(records: Any, *, expected_raw_symbol: str):
    """Reconstruct promotion-grade top-of-book quotes from a full MBO snapshot.

    The request must begin at midnight UTC.  No quote is emitted until a
    snapshot clear and terminal snapshot record have been observed.  Any bad
    timestamp/book flag, time reversal, missing side, or crossed book after the
    snapshot fails the entire evidence slice closed.
    """
    import pandas as pd

    rows = list(iter_mbo_quotes(records, expected_raw_symbol=expected_raw_symbol))
    frame = pd.DataFrame(rows).set_index("ts_recv")
    # Multiple order events can share ts_recv.  The last state at that receive
    # timestamp is the only actionable state and gives a unique quote index.
    return frame.groupby(level=0, sort=True).last()


def iter_mbo_quotes(records: Any, *, expected_raw_symbol: str):
    """Yield packet-complete MBO top-of-book states without materializing a day."""
    import pandas as pd

    from research.mes_mbo_phase_a import BookState

    snapshot_flag, last_flag = 32, 128
    bad_timestamp_flag, bad_book_flag = 8, 4
    valid_actions, valid_sides = frozenset("ACMFNRT"), frozenset("ABN")
    day_ns = 86_400_000_000_000
    book = BookState()
    snapshot_clear_seen = False
    snapshot_complete = False
    previous_ts: int | None = None
    emitted = 0

    for record in records:
        action = str(_record_value(record, "action", ""))
        side = str(_record_value(record, "side", ""))
        flags = int(_record_value(record, "flags", 0))
        ts_recv = int(_record_value(record, "ts_recv", -1))
        if action not in valid_actions or side not in valid_sides or ts_recv < 0:
            raise ValueError("MBO record contains unrecognized action, side, or timestamp")
        symbol = _record_value(record, "symbol")
        if symbol is not None and str(symbol) != expected_raw_symbol:
            raise ValueError("MBO record raw contract does not match the requested contract")
        if previous_ts is not None and ts_recv < previous_ts:
            raise ValueError("MBO records are not ordered by ts_recv")
        previous_ts = ts_recv
        # Databento historical MBO snapshots legitimately carry
        # F_SNAPSHOT | F_BAD_TS_RECV because snapshot receive times are
        # synthetic.  The flag remains fatal for every incremental record.
        if flags & bad_timestamp_flag and not flags & snapshot_flag:
            raise ValueError("MBO record has a bad timestamp quality flag")
        if flags & bad_book_flag:
            raise ValueError("MBO record has a bad-book quality flag")
        if flags & snapshot_flag and action == "R":
            if ts_recv % day_ns >= 60_000_000_000:
                raise ValueError("MBO mandatory snapshot clear is not at the midnight UTC request boundary")
            snapshot_clear_seen = True

        book.apply(
            action,
            side,
            int(_record_value(record, "order_id", 0)),
            int(_record_value(record, "price", 0)),
            int(_record_value(record, "size", 0)),
        )
        if book.missing_order_events or book.duplicate_adds or book.oversize_cancels:
            raise ValueError("MBO reconstruction encountered an anomalous order event")
        if flags & snapshot_flag and flags & last_flag:
            if not snapshot_clear_seen:
                raise ValueError("MBO terminal snapshot arrived before the mandatory clear")
            snapshot_complete = True
        if not snapshot_complete or not (flags & last_flag):
            continue
        bid, ask = book.best("B"), book.best("A")
        if bid is None or ask is None:
            raise ValueError("MBO reconstructed book is missing a side")
        if bid[0] >= ask[0]:
            raise ValueError("MBO reconstructed book is crossed or locked")
        emitted += 1
        yield {
            "ts_recv": pd.to_datetime(ts_recv, unit="ns", utc=True),
            "bid": bid[0] / 1_000_000_000,
            "ask": ask[0] / 1_000_000_000,
            "bid_size": bid[1],
            "ask_size": ask[1],
            "symbol": expected_raw_symbol,
            "snapshot_clear_seen": True,
            "snapshot_complete": True,
            "crossed": False,
            "bad_timestamp_flag": False,
            "bad_book_flag": False,
            "book_valid": True,
            "evidence_tier": "databento_mbo_reconstructed_executable",
            "promotion_eligible": True,
        }

    if not snapshot_clear_seen or not snapshot_complete:
        raise ValueError("MBO evidence is missing the mandatory complete midnight snapshot")
    if emitted == 0:
        raise ValueError("MBO evidence produced no valid reconstructed quotes")


def executable_fill(
    quotes: Any,
    *,
    direction: str,
    action: str,
    decision_at: datetime,
    max_age_seconds: float = DEFAULT_MAX_QUOTE_AGE_SECONDS,
    max_spread_points: float = DEFAULT_MAX_SPREAD_POINTS,
) -> dict[str, Any]:
    """Return the first marketable quote at/after a decision, or fail closed."""
    import pandas as pd

    if direction not in {"long", "short"} or action not in {"entry", "exit"}:
        raise ValueError("direction/action must be long|short and entry|exit")
    if max_age_seconds < 0 or max_spread_points <= 0:
        raise ValueError("quote limits must be positive")
    decision = pd.Timestamp(_utc(decision_at))
    eligible = quotes[quotes.index >= decision]
    if eligible.empty:
        raise ValueError("executable quote missing")
    row = eligible.iloc[0]
    timestamp = eligible.index[0]
    age = (timestamp - decision).total_seconds()
    if age < 0 or age > max_age_seconds:
        raise ValueError("executable quote is stale")
    spread = float(row["ask"] - row["bid"])
    if not math.isfinite(spread) or spread <= 0 or spread > max_spread_points:
        raise ValueError("executable quote spread is too wide")
    price_column = {
        ("long", "entry"): "ask",
        ("long", "exit"): "bid",
        ("short", "entry"): "bid",
        ("short", "exit"): "ask",
    }[(direction, action)]
    return {
        "price": float(row[price_column]),
        "price_side": price_column,
        "quote_timestamp": timestamp.isoformat().replace("+00:00", "Z"),
        "decision_at": decision.isoformat().replace("+00:00", "Z"),
        "quote_age_seconds": age,
        "spread_points": spread,
        "evidence_tier": row.get("evidence_tier"),
        "promotion_eligible": bool(row.get("promotion_eligible", False)),
        "execution_enabled": False,
        "can_submit_orders": False,
    }

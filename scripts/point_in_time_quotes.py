#!/usr/bin/env python3
"""Vendor-neutral point-in-time option quote capture (telemetry only).

Records provider quotes, timestamps, underlying price, IV, Greeks, OI, volume and
trade conditions at lifecycle events (signal, fill, monitor, exit) into an
append-only JSONL store keyed by trade/order/contract. This is the
execution-grade provenance layer the research handoff requires: every field
is either observed (with source and timestamp) or null - nothing is imputed.

Contracts:
- Never raises into a trading path: `capture_lifecycle_sample` swallows and
  logs every failure and returns None.
- Never fabricates: missing fields are null and listed in
  provenance.missing_fields; a failed fetch is provenance.status
  "unavailable", not a guess.
- Flow classification is ALWAYS "unknown" until a licensed/classified OPRA
  adapter exists (see `classified_flow`). Public snapshots are unsigned.
- Cannot place orders. No broker trading endpoints are imported or called.

Providers:
- alpaca_options_snapshot_v1beta1 (default): latest quote/trade, greeks,
  implied volatility, open interest and daily volume where the API returns
  them.
- Additional vendors implement `fetch_fn(occ_symbol) -> (payload, meta)` and
  a parser; the record schema stays identical.
"""
from __future__ import annotations

import json
import logging
import math
import os
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Optional

log = logging.getLogger("point-in-time-quotes")

SCHEMA_VERSION = 1
LIFECYCLE_EVENTS = ("signal", "fill", "monitor", "exit")
PROVIDER_ALPACA = "alpaca_options_snapshot_v1beta1"
ALPACA_OPTIONS_FEED = "indicative"
ALPACA_STOCK_FEED = "iex"
ALPACA_OPTIONS_SNAPSHOT_URL = "https://data.alpaca.markets/v1beta1/options/snapshots"
ALPACA_STOCK_TRADE_LATEST_URL = "https://data.alpaca.markets/v2/stocks/{symbol}/trades/latest"

DEFAULT_SAMPLES_PATH = Path(
    os.getenv("OPTION_QUOTE_SAMPLES_FILE")
    or str(Path(os.path.expanduser("~")) / ".vibe-trading" / "logs" / "option-quote-samples.jsonl")
)

# Fields the record schema promises; absent ones become null + listed missing.
_QUOTE_FIELDS = ("bid", "ask", "bid_size", "ask_size", "quote_timestamp")
_GREEK_FIELDS = ("delta", "gamma", "theta", "vega", "rho")
_APPEND_LOCK = threading.Lock()


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(ts: datetime) -> str:
    return ts.isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _parse_ts(text: Any) -> Optional[datetime]:
    if not text:
        return None
    import re

    raw = str(text).replace("Z", "+00:00")
    # Alpaca nanosecond timestamps exceed fromisoformat precision; trim to us.
    raw = re.sub(r"\.(\d{6})\d+", r".\1", raw)
    try:
        parsed = datetime.fromisoformat(raw)
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _num(value: Any) -> Optional[float]:
    try:
        if value is None:
            return None
        out = float(value)
        return out if math.isfinite(out) else None
    except (TypeError, ValueError):
        return None


def quote_age_seconds(quote_timestamp: Any, captured_at: datetime) -> Optional[float]:
    parsed = _parse_ts(quote_timestamp)
    if parsed is None:
        return None
    return round(max(0.0, (captured_at - parsed).total_seconds()), 3)


def classified_flow() -> dict:
    """Classified (buyer/seller-initiated) flow status.

    There is no licensed OPRA adapter yet. Per the hard stops, missing
    classified data fails to "unknown" - never to a directional label.
    """
    return {
        "flow_classification": "unknown",
        "reason": "no_licensed_classified_opra_adapter",
    }


def parse_alpaca_option_snapshot(
    occ_symbol: str,
    payload: dict,
    captured_at: datetime,
) -> dict:
    """Pure parser for one contract from an Alpaca options snapshot payload.

    Returns the vendor-neutral snapshot body plus provenance. Missing pieces
    are null and enumerated; nothing is estimated.
    """
    snap = {}
    if isinstance(payload, dict):
        snap = (payload.get("snapshots") or {}).get(occ_symbol) or {}
        if not snap and set(payload.keys()) & {"latestQuote", "latestTrade", "greeks"}:
            snap = payload  # already-unwrapped single-contract payload

    quote_raw = snap.get("latestQuote") or {}
    trade_raw = snap.get("latestTrade") or {}
    greeks_raw = snap.get("greeks") or {}
    bar_raw = snap.get("dailyBar") or {}

    bid = _num(quote_raw.get("bp"))
    ask = _num(quote_raw.get("ap"))
    quote_ts = quote_raw.get("t")
    valid_market = bid is not None and ask is not None and bid > 0 and ask >= bid
    quote = {
        "bid": bid,
        "ask": ask,
        "bid_size": _num(quote_raw.get("bs")),
        "ask_size": _num(quote_raw.get("as")),
        "quote_timestamp": str(quote_ts) if quote_ts else None,
        "quote_age_seconds": quote_age_seconds(quote_ts, captured_at),
        "mid": round((bid + ask) / 2, 4) if valid_market else None,
        "spread_cents": int(round((ask - bid) * 100)) if valid_market else None,
    }
    trade_ts = trade_raw.get("t")
    trade = {
        "price": _num(trade_raw.get("p")),
        "size": _num(trade_raw.get("s")),
        "trade_timestamp": str(trade_ts) if trade_ts else None,
        "conditions": trade_raw.get("c") if isinstance(trade_raw.get("c"), list) else None,
    }
    greeks = {name: _num(greeks_raw.get(name)) for name in _GREEK_FIELDS}

    missing: list[str] = []
    for name in _QUOTE_FIELDS:
        if quote.get(name if name != "quote_timestamp" else "quote_timestamp") is None:
            missing.append(f"quote.{name}")
    for name in _GREEK_FIELDS:
        if greeks[name] is None:
            missing.append(f"greeks.{name}")
    if bid is not None and ask is not None and not valid_market:
        missing.append("quote.valid_market")
    implied_volatility = _num(snap.get("impliedVolatility"))
    if implied_volatility is None:
        missing.append("implied_volatility")
    open_interest = _num(snap.get("openInterest"))
    if open_interest is None:
        missing.append("open_interest")
    volume = _num(bar_raw.get("v"))
    if volume is None:
        missing.append("volume")

    has_quote = quote["bid"] is not None or quote["ask"] is not None
    status = "ok" if has_quote and not missing else ("partial" if has_quote or trade["price"] is not None else "unavailable")

    return {
        "quote": quote,
        "trade": trade,
        "greeks": greeks,
        "implied_volatility": implied_volatility,
        "open_interest": open_interest,
        "volume": volume,
        "provenance": {
            "provider": PROVIDER_ALPACA,
            "feed": ALPACA_OPTIONS_FEED,
            "quote_scope": "indicative_modified_not_opra_nbbo",
            "status": status,
            "missing_fields": missing,
        },
    }


def fetch_alpaca_option_snapshot(
    occ_symbol: str,
    headers: dict,
    timeout: float = 10.0,
) -> tuple[Optional[dict], dict]:
    """Network fetch. Returns (payload_or_None, fetch_meta)."""
    import requests

    started = _utc_now()
    meta: dict[str, Any] = {
        "endpoint": ALPACA_OPTIONS_SNAPSHOT_URL,
        "feed": ALPACA_OPTIONS_FEED,
        "quote_scope": "indicative_modified_not_opra_nbbo",
        "http_status": None,
    }
    try:
        resp = requests.get(
            ALPACA_OPTIONS_SNAPSHOT_URL,
            headers=headers,
            params={"symbols": occ_symbol, "feed": ALPACA_OPTIONS_FEED},
            timeout=timeout,
        )
        meta["http_status"] = resp.status_code
        meta["latency_ms"] = int((_utc_now() - started).total_seconds() * 1000)
        if resp.status_code != 200:
            return None, meta
        return resp.json(), meta
    except Exception as exc:
        meta["error"] = str(exc)[:200]
        return None, meta


def fetch_alpaca_underlying_price(
    symbol: str,
    headers: dict,
    timeout: float = 10.0,
) -> dict:
    """Latest underlying trade price with its own source timestamp."""
    import requests

    out = {
        "symbol": symbol,
        "price": None,
        "price_timestamp": None,
        "source": "alpaca_stocks_trades_latest_iex",
    }
    try:
        resp = requests.get(
            ALPACA_STOCK_TRADE_LATEST_URL.format(symbol=symbol),
            headers=headers,
            params={"feed": ALPACA_STOCK_FEED},
            timeout=timeout,
        )
        if resp.status_code != 200:
            return out
        trade = (resp.json() or {}).get("trade") or {}
        out["price"] = _num(trade.get("p"))
        ts = trade.get("t")
        out["price_timestamp"] = str(ts) if ts else None
    except Exception:
        pass
    return out


def build_lifecycle_record(
    event: str,
    occ_symbol: str,
    parsed: dict,
    *,
    bot: str,
    trade_id: Optional[str] = None,
    order_id: Optional[str] = None,
    underlying: Optional[dict] = None,
    context: Optional[dict] = None,
    fetch_meta: Optional[dict] = None,
    captured_at: Optional[datetime] = None,
) -> dict:
    """Assemble the durable record. Pure; fully testable."""
    if event not in LIFECYCLE_EVENTS:
        raise ValueError(f"unknown lifecycle event {event!r}; expected one of {LIFECYCLE_EVENTS}")
    captured_at = captured_at or _utc_now()
    provenance = dict(parsed.get("provenance") or {})
    if fetch_meta:
        provenance.update({k: v for k, v in fetch_meta.items() if v is not None})
    record = {
        "schema_version": SCHEMA_VERSION,
        "event": event,
        "captured_at": _iso(captured_at),
        "bot": bot,
        "trade_id": trade_id,
        "order_id": order_id,
        "contract": occ_symbol,
        "quote": parsed.get("quote"),
        "trade": parsed.get("trade"),
        "greeks": parsed.get("greeks"),
        "implied_volatility": parsed.get("implied_volatility"),
        "open_interest": parsed.get("open_interest"),
        "volume": parsed.get("volume"),
        "underlying": underlying,
        "provenance": provenance,
        "context": context or {},
    }
    record.update(classified_flow())
    return record


def append_sample(record: dict, path: Path | str = DEFAULT_SAMPLES_PATH) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with _APPEND_LOCK:
        with path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(record, sort_keys=True, allow_nan=False) + "\n")


def capture_lifecycle_sample(
    event: str,
    occ_symbol: str,
    *,
    bot: str,
    headers: Optional[dict] = None,
    trade_id: Optional[str] = None,
    order_id: Optional[str] = None,
    underlying_symbol: Optional[str] = None,
    context: Optional[dict] = None,
    path: Path | str = DEFAULT_SAMPLES_PATH,
    fetch_fn: Optional[Callable[[str], tuple[Optional[dict], dict]]] = None,
) -> Optional[dict]:
    """Fetch, build, and persist one lifecycle sample.

    NEVER raises: any failure logs a warning and returns None so telemetry
    can never break an entry, monitor, or exit path. A failed fetch is still
    recorded (provenance.status="unavailable") so gaps are visible later.
    """
    try:
        captured_at = _utc_now()
        if fetch_fn is not None:
            try:
                payload, meta = fetch_fn(occ_symbol)
            except Exception as exc:
                payload, meta = None, {"error": str(exc)[:200]}
        elif headers:
            payload, meta = fetch_alpaca_option_snapshot(occ_symbol, headers)
        else:
            payload, meta = None, {"error": "no_headers_and_no_fetch_fn"}

        if payload is not None:
            parsed = parse_alpaca_option_snapshot(occ_symbol, payload, captured_at)
        else:
            parsed = {
                "quote": None,
                "trade": None,
                "greeks": None,
                "implied_volatility": None,
                "open_interest": None,
                "volume": None,
                "provenance": {
                    "provider": PROVIDER_ALPACA,
                    "feed": ALPACA_OPTIONS_FEED,
                    "quote_scope": "indicative_modified_not_opra_nbbo",
                    "status": "unavailable",
                    "missing_fields": ["all"],
                },
            }

        underlying = None
        if underlying_symbol and headers:
            underlying = fetch_alpaca_underlying_price(underlying_symbol, headers)
        elif underlying_symbol:
            underlying = {"symbol": underlying_symbol, "price": None, "price_timestamp": None, "source": "unavailable"}

        record = build_lifecycle_record(
            event,
            occ_symbol,
            parsed,
            bot=bot,
            trade_id=trade_id,
            order_id=order_id,
            underlying=underlying,
            context=context,
            fetch_meta=meta,
            captured_at=captured_at,
        )
        append_sample(record, path=path)
        return record
    except Exception as exc:
        log.warning(f"point-in-time capture failed for {occ_symbol} event={event}: {exc}")
        return None

#!/usr/bin/env python3
"""Read-only Tradier market-data adapter for US equity and option quotes.

This module intentionally exposes no account or order endpoints. A Tradier
production brokerage token is required because sandbox market data is delayed.
"""
from __future__ import annotations

import math
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterable, Optional

from dotenv import load_dotenv


ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / "agent" / ".env")

PROVIDER_TRADIER = "tradier_marketdata_quotes_v1"
TRADIER_QUOTE_SCOPE = "tradier_consolidated_us_options_level1"
TRADIER_QUOTES_URL = "https://api.tradier.com/v1/markets/quotes"
DEFAULT_TIMEOUT_SECONDS = float(os.getenv("TRADIER_TIMEOUT_SECONDS", "10"))
DEFAULT_BATCH_SIZE = max(1, min(500, int(os.getenv("TRADIER_QUOTE_BATCH_SIZE", "100"))))
DEFAULT_MAX_QUOTE_AGE_SECONDS = max(
    1.0, float(os.getenv("TRADIER_MAX_QUOTE_AGE_SECONDS", "120"))
)
RETRY_ATTEMPTS = max(1, int(os.getenv("TRADIER_RETRY_ATTEMPTS", "3")))
RETRY_BASE_SECONDS = max(0.0, float(os.getenv("TRADIER_RETRY_BASE_SECONDS", "0.5")))


class TradierDataError(RuntimeError):
    """Raised when read-only Tradier market data cannot be trusted."""


def configured_quote_provider() -> str:
    provider = os.getenv("OPTION_QUOTE_PROVIDER", "alpaca").strip().lower()
    return provider if provider in {"alpaca", "tradier"} else "alpaca"


def tradier_selected() -> bool:
    return configured_quote_provider() == "tradier"


def access_token() -> str:
    return os.getenv("TRADIER_ACCESS_TOKEN", "").strip()


def is_configured() -> bool:
    return bool(access_token())


def _number(value: Any) -> Optional[float]:
    try:
        if value is None:
            return None
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def _epoch_datetime(value: Any) -> Optional[datetime]:
    number = _number(value)
    if number is None or number <= 0:
        return None
    # Tradier documents quote dates as Unix milliseconds. Tolerate seconds and
    # nanoseconds so a malformed unit cannot create a plausible stale quote.
    if number > 1e17:
        number /= 1e9
    elif number > 1e14:
        number /= 1e6
    elif number > 1e11:
        number /= 1e3
    try:
        return datetime.fromtimestamp(number, tz=timezone.utc)
    except (OverflowError, OSError, ValueError):
        return None


def _iso(value: Optional[datetime]) -> Optional[str]:
    if value is None:
        return None
    return value.astimezone(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _quote_timestamp(row: dict[str, Any]) -> Optional[datetime]:
    bid_at = _epoch_datetime(row.get("bid_date"))
    ask_at = _epoch_datetime(row.get("ask_date"))
    if bid_at and ask_at:
        return min(bid_at, ask_at)
    return bid_at or ask_at


def normalize_quote(row: dict[str, Any], captured_at: Optional[datetime] = None) -> dict[str, Any]:
    """Normalize one Tradier quote into the shared option-snapshot schema."""
    captured_at = captured_at or datetime.now(timezone.utc)
    bid = _number(row.get("bid"))
    ask = _number(row.get("ask"))
    bid_size = _number(row.get("bidsize"))
    ask_size = _number(row.get("asksize"))
    quote_at = _quote_timestamp(row)
    valid_market = bid is not None and ask is not None and bid > 0 and ask >= bid
    age = max(0.0, (captured_at - quote_at).total_seconds()) if quote_at else None
    greeks_raw = row.get("greeks") if isinstance(row.get("greeks"), dict) else {}
    greeks = {
        name: _number(greeks_raw.get(name))
        for name in ("delta", "gamma", "theta", "vega", "rho")
    }
    implied_volatility = _number(greeks_raw.get("mid_iv"))
    if implied_volatility is None:
        implied_volatility = _number(greeks_raw.get("smv_vol"))

    missing: list[str] = []
    for name, value in (
        ("quote.bid", bid),
        ("quote.ask", ask),
        ("quote.bid_size", bid_size),
        ("quote.ask_size", ask_size),
        ("quote.quote_timestamp", quote_at),
    ):
        if value is None:
            missing.append(name)
    if bid is not None and ask is not None and not valid_market:
        missing.append("quote.valid_market")
    for name, value in greeks.items():
        if value is None:
            missing.append(f"greeks.{name}")
    if implied_volatility is None:
        missing.append("implied_volatility")
    open_interest = _number(row.get("open_interest"))
    if open_interest is None:
        missing.append("open_interest")
    volume = _number(row.get("volume"))
    if volume is None:
        missing.append("volume")

    has_quote = bid is not None or ask is not None
    status = "ok" if valid_market and not missing else ("partial" if has_quote else "unavailable")
    trade_at = _epoch_datetime(row.get("trade_date"))
    return {
        "quote": {
            "bid": bid,
            "ask": ask,
            "bid_size": bid_size,
            "ask_size": ask_size,
            "quote_timestamp": _iso(quote_at),
            "quote_age_seconds": round(age, 3) if age is not None else None,
            "mid": round((bid + ask) / 2.0, 4) if valid_market else None,
            "spread_cents": int(round((ask - bid) * 100)) if valid_market else None,
        },
        "trade": {
            "price": _number(row.get("last")),
            "size": _number(row.get("last_volume")),
            "trade_timestamp": _iso(trade_at),
            "conditions": None,
        },
        "greeks": greeks,
        "implied_volatility": implied_volatility,
        "open_interest": open_interest,
        "volume": volume,
        "provenance": {
            "provider": PROVIDER_TRADIER,
            "feed": "production_consolidated",
            "quote_scope": TRADIER_QUOTE_SCOPE,
            "status": status,
            "missing_fields": missing,
            "bid_exchange": row.get("bidexch"),
            "ask_exchange": row.get("askexch"),
            "greeks_updated_at": greeks_raw.get("updated_at"),
            "quote_timestamp_method": "older_of_bid_date_and_ask_date",
        },
    }


def _quote_rows(payload: Any) -> list[dict[str, Any]]:
    if not isinstance(payload, dict):
        return []
    quotes = payload.get("quotes")
    if not isinstance(quotes, dict):
        return []
    rows = quotes.get("quote")
    if isinstance(rows, dict):
        return [rows]
    if isinstance(rows, list):
        return [row for row in rows if isinstance(row, dict)]
    return []


def fetch_quotes_with_meta(
    symbols: Iterable[str],
    *,
    token: Optional[str] = None,
    request_get: Optional[Callable[..., Any]] = None,
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
    batch_size: int = DEFAULT_BATCH_SIZE,
    captured_at: Optional[datetime] = None,
) -> tuple[dict[str, dict[str, Any]], dict[str, Any]]:
    """Fetch current production quotes in bounded batches with retries."""
    requested = sorted({str(symbol).strip().upper() for symbol in symbols if str(symbol).strip()})
    meta: dict[str, Any] = {
        "provider": PROVIDER_TRADIER,
        "endpoint": TRADIER_QUOTES_URL,
        "feed": "production_consolidated",
        "quote_scope": TRADIER_QUOTE_SCOPE,
        "requested_symbols": len(requested),
        "received_symbols": 0,
        "http_status": None,
    }
    if not requested:
        return {}, meta
    resolved_token = (token or access_token()).strip()
    if not resolved_token:
        raise TradierDataError("TRADIER_ACCESS_TOKEN is required for production real-time quotes")
    if request_get is None:
        import requests

        request_get = requests.get

    captured_at = captured_at or datetime.now(timezone.utc)
    normalized: dict[str, dict[str, Any]] = {}
    started = time.monotonic()
    for start in range(0, len(requested), max(1, batch_size)):
        chunk = requested[start : start + max(1, batch_size)]
        response = None
        for attempt in range(1, RETRY_ATTEMPTS + 1):
            try:
                response = request_get(
                    TRADIER_QUOTES_URL,
                    headers={
                        "Authorization": f"Bearer {resolved_token}",
                        "Accept": "application/json",
                    },
                    params={"symbols": ",".join(chunk), "greeks": "true"},
                    timeout=timeout,
                )
                meta["http_status"] = int(response.status_code)
                if response.status_code == 200:
                    break
                if response.status_code != 429 and response.status_code < 500:
                    raise TradierDataError(f"Tradier quote request returned HTTP {response.status_code}")
            except TradierDataError:
                raise
            except Exception as exc:
                if attempt >= RETRY_ATTEMPTS:
                    raise TradierDataError(f"Tradier quote request failed: {type(exc).__name__}: {exc}") from exc
            if attempt < RETRY_ATTEMPTS and RETRY_BASE_SECONDS:
                time.sleep(RETRY_BASE_SECONDS * (2 ** (attempt - 1)))
        if response is None or response.status_code != 200:
            status = getattr(response, "status_code", "unavailable")
            raise TradierDataError(f"Tradier quote request exhausted retries: HTTP {status}")
        try:
            rows = _quote_rows(response.json())
        except Exception as exc:
            raise TradierDataError(f"Tradier quote response was not valid JSON: {exc}") from exc
        for row in rows:
            symbol = str(row.get("symbol") or "").strip().upper()
            if symbol:
                normalized[symbol] = normalize_quote(row, captured_at)
        headers = getattr(response, "headers", {}) or {}
        if headers.get("X-Ratelimit-Available") is not None:
            meta["rate_limit_available"] = headers.get("X-Ratelimit-Available")

    meta["received_symbols"] = len(normalized)
    meta["latency_ms"] = int((time.monotonic() - started) * 1000)
    return normalized, meta


def fetch_quotes(symbols: Iterable[str], **kwargs: Any) -> dict[str, dict[str, Any]]:
    quotes, _ = fetch_quotes_with_meta(symbols, **kwargs)
    return quotes


def fetch_option_snapshot(occ_symbol: str, **kwargs: Any) -> tuple[Optional[dict], dict[str, Any]]:
    quotes, meta = fetch_quotes_with_meta([occ_symbol], **kwargs)
    return quotes.get(occ_symbol.upper()), meta


def quote_is_fresh(
    parsed: dict[str, Any],
    max_age_seconds: float = DEFAULT_MAX_QUOTE_AGE_SECONDS,
) -> bool:
    quote = parsed.get("quote") if isinstance(parsed, dict) else None
    provenance = parsed.get("provenance") if isinstance(parsed, dict) else None
    if not isinstance(quote, dict) or not isinstance(provenance, dict):
        return False
    if provenance.get("status") not in {"ok", "partial"}:
        return False
    bid = _number(quote.get("bid"))
    ask = _number(quote.get("ask"))
    age = _number(quote.get("quote_age_seconds"))
    return bool(
        bid is not None
        and ask is not None
        and bid > 0
        and ask >= bid
        and age is not None
        and 0 <= age <= max_age_seconds
    )


def fetch_underlying_price(symbol: str, **kwargs: Any) -> dict[str, Any]:
    quotes, _ = fetch_quotes_with_meta([symbol], **kwargs)
    parsed = quotes.get(symbol.upper()) or {}
    quote = parsed.get("quote") if isinstance(parsed, dict) else {}
    trade = parsed.get("trade") if isinstance(parsed, dict) else {}
    price = _number((trade or {}).get("price"))
    timestamp = (trade or {}).get("trade_timestamp")
    if price is None and isinstance(quote, dict):
        price = _number(quote.get("mid"))
        timestamp = quote.get("quote_timestamp")
    return {
        "symbol": symbol.upper(),
        "price": price,
        "price_timestamp": timestamp,
        "source": PROVIDER_TRADIER,
    }

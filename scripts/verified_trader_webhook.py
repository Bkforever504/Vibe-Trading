#!/usr/bin/env python3
"""Authenticated, shadow-only TradingView webhook receiver.

The opaque URL token authenticates the sender. It is never written to the
evidence journal. This service only normalizes alerts; it has no broker client.
"""
from __future__ import annotations

import os
import secrets
import sys
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from fastapi import FastAPI, HTTPException

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.verified_trader_intake import DEFAULT_JOURNAL, ingest_rows

app = FastAPI(
    title="Verified Trader Shadow Webhook",
    version="1.0.0",
    docs_url=None,
    redoc_url=None,
)


def fetch_alpaca_observed_market(payload: Mapping[str, Any]) -> dict[str, Any]:
    """Read the currently executable-ish market price from Alpaca data only."""
    from scripts.point_in_time_quotes import (
        fetch_alpaca_option_snapshot,
        fetch_alpaca_underlying_price,
        parse_alpaca_option_snapshot,
    )
    from scripts.x_spy_research_intake import load_env_file

    load_env_file()
    key = os.environ.get("APCA_API_KEY_ID") or os.environ.get("ALPACA_API_KEY")
    secret = os.environ.get("APCA_API_SECRET_KEY") or os.environ.get("ALPACA_SECRET_KEY")
    if not key or not secret:
        return {}
    headers = {
        "APCA-API-KEY-ID": key,
        "APCA-API-SECRET-KEY": secret,
    }
    option_symbol = str(payload.get("option_symbol") or "").strip()
    action = str(payload.get("action") or payload.get("side") or "").upper()
    direction = str(payload.get("direction") or "").upper()
    if option_symbol:
        raw, meta = fetch_alpaca_option_snapshot(option_symbol, headers)
        if raw is None:
            return {"observed_market_source": meta.get("endpoint")}
        captured_at = datetime.now(timezone.utc)
        parsed = parse_alpaca_option_snapshot(option_symbol, raw, captured_at)
        quote = parsed.get("quote") or {}
        if action == "SELL" or direction == "SHORT":
            price = quote.get("bid")
        else:
            price = quote.get("ask")
        return {
            "observed_market_price": price,
            "observed_market_timestamp": quote.get("quote_timestamp"),
            "observed_market_source": parsed.get("provenance", {}).get("provider"),
        }

    symbol = str(payload.get("symbol") or payload.get("underlying") or "").strip().upper()
    if not symbol:
        return {}
    result = fetch_alpaca_underlying_price(symbol, headers)
    return {
        "observed_market_price": result.get("price"),
        "observed_market_timestamp": result.get("price_timestamp"),
        "observed_market_source": result.get("source"),
    }


def process_tradingview_payload(
    payload: Mapping[str, Any],
    *,
    supplied_token: str,
    expected_token: str,
    source_id: str,
    consent_ref: str,
    trader_id: str | None = None,
    journal_path: Path = DEFAULT_JOURNAL,
    market_price_provider: Callable[[Mapping[str, Any]], Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    if not expected_token or not secrets.compare_digest(supplied_token, expected_token):
        raise PermissionError("invalid webhook token")
    prepared = dict(payload)
    if prepared.get("observed_market_price") is None and market_price_provider is not None:
        try:
            market = dict(market_price_provider(prepared) or {})
        except Exception:
            market = {}
        for key in (
            "observed_market_price",
            "observed_market_timestamp",
            "observed_market_source",
        ):
            if market.get(key) is not None:
                prepared[key] = market[key]
    _, result = ingest_rows(
        [prepared],
        source_type="tradingview_webhook",
        source_id=source_id,
        consent_ref=consent_ref,
        trader_id=trader_id,
        journal_path=journal_path,
        write=True,
    )
    return {
        "accepted": result["accepted"],
        "duplicates": result["duplicates"],
        "quarantined": result["quarantined"],
        "mode": "shadow_only",
        "execution_enabled": False,
        "market_joined": prepared.get("observed_market_price") is not None,
    }


@app.get("/health")
def health() -> dict[str, Any]:
    return {
        "status": "ok",
        "mode": "shadow_only",
        "execution_enabled": False,
        "webhook_configured": bool(os.environ.get("VERIFIED_TRADER_WEBHOOK_TOKEN")),
    }


@app.post("/webhooks/tradingview/{webhook_token}")
def tradingview_webhook(webhook_token: str, payload: dict[str, Any]) -> dict[str, Any]:
    expected = os.environ.get("VERIFIED_TRADER_WEBHOOK_TOKEN", "")
    source_id = os.environ.get("VERIFIED_TRADER_SOURCE_ID", "tradingview-cooperating-trader")
    consent_ref = os.environ.get("VERIFIED_TRADER_CONSENT_REF", "")
    trader_id = os.environ.get("VERIFIED_TRADER_TRADER_ID")
    auto_quote = os.environ.get("VERIFIED_TRADER_AUTO_QUOTE", "1") not in {"0", "false", "False"}
    if not expected:
        raise HTTPException(status_code=503, detail="webhook is not configured")
    try:
        return process_tradingview_payload(
            payload,
            supplied_token=webhook_token,
            expected_token=expected,
            source_id=source_id,
            consent_ref=consent_ref,
            trader_id=trader_id,
            market_price_provider=fetch_alpaca_observed_market if auto_quote else None,
        )
    except PermissionError:
        # Do not reveal whether a token was close or whether the endpoint is in use.
        raise HTTPException(status_code=404, detail="not found") from None


def main() -> int:
    import uvicorn

    host = os.environ.get("VERIFIED_TRADER_WEBHOOK_HOST", "127.0.0.1")
    port = int(os.environ.get("VERIFIED_TRADER_WEBHOOK_PORT", "8787"))
    uvicorn.run(app, host=host, port=port, log_level="warning")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

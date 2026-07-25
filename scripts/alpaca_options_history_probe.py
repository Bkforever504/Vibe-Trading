#!/usr/bin/env python3
"""Read-only probe: how much historical SPY option data does the current
Alpaca data plan actually return?

The research sweep's next step is "identify a no-surprise-cost source of
historical SPY option minute NBBO". Before any purchase discussion, this
probe measures what the already-configured free/indicative Alpaca feed
serves: minute quotes, trades, and bars for expired SPY contracts across
known third-Friday expiries.

Data API only (data.alpaca.markets). No trading endpoints, no orders,
no subscriptions, no spending.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

try:
    from dotenv import load_dotenv
except ImportError:  # pragma: no cover
    load_dotenv = None

DATA_BASE = "https://data.alpaca.markets"
STOCK_BARS_URL = DATA_BASE + "/v2/stocks/{symbol}/bars"
OPTION_QUOTES_URL = DATA_BASE + "/v1beta1/options/quotes"
OPTION_TRADES_URL = DATA_BASE + "/v1beta1/options/trades"
OPTION_BARS_URL = DATA_BASE + "/v1beta1/options/bars"

REPORT_PATH = Path.home() / ".vibe-trading" / "reports" / "alpaca-options-history-probe.json"

# Standard third-Friday SPY expiries; each probe queries the expiry day itself
# so the contract is 0DTE at capture time.
PROBE_EXPIRIES = (
    "2024-03-15",
    "2024-06-21",
    "2024-12-20",
    "2025-03-21",
    "2025-06-20",
    "2025-12-19",
    "2026-03-20",
    "2026-06-19",
)
FEEDS = ("indicative", "opra")


def build_occ_symbol(underlying: str, expiry: str, right: str, strike: float) -> str:
    day = datetime.strptime(expiry, "%Y-%m-%d")
    return f"{underlying}{day:%y%m%d}{right[0].upper()}{int(round(strike * 1000)):08d}"


def _headers() -> dict[str, str]:
    key = os.getenv("ALPACA_API_KEY", "")
    secret = os.getenv("ALPACA_SECRET_KEY", "")
    if not key or not secret:
        raise SystemExit("ALPACA_API_KEY / ALPACA_SECRET_KEY not configured in agent/.env")
    return {"APCA-API-KEY-ID": key, "APCA-API-SECRET-KEY": secret}


def _get(url: str, headers: dict[str, str], params: dict[str, Any]) -> tuple[int, Any]:
    try:
        resp = requests.get(url, headers=headers, params=params, timeout=15)
    except requests.RequestException as exc:
        return -1, {"error": str(exc)[:200]}
    try:
        payload = resp.json()
    except ValueError:
        payload = {"error": resp.text[:200]}
    return resp.status_code, payload


def _underlying_close(symbol: str, day: str, headers: dict[str, str]) -> float | None:
    status, payload = _get(
        STOCK_BARS_URL.format(symbol=symbol),
        headers,
        {"timeframe": "1Day", "start": day, "end": day, "feed": "iex", "limit": 1},
    )
    bars = (payload or {}).get("bars") if isinstance(payload, dict) else None
    if status == 200 and isinstance(bars, list) and bars:
        try:
            return float(bars[0].get("c"))
        except (TypeError, ValueError):
            return None
    return None


def _summarize_rows(payload: Any, symbol: str, key: str) -> dict[str, Any]:
    container = (payload or {}).get(key) if isinstance(payload, dict) else None
    rows = container.get(symbol) if isinstance(container, dict) else None
    rows = rows if isinstance(rows, list) else []
    timestamps = [str(row.get("t")) for row in rows if isinstance(row, dict) and row.get("t")]
    first = rows[0] if rows else {}
    return {
        "row_count": len(rows),
        "first_timestamp": min(timestamps) if timestamps else None,
        "last_timestamp": max(timestamps) if timestamps else None,
        "sample_fields": sorted(first.keys()) if isinstance(first, dict) else [],
    }


def probe_expiry(expiry: str, headers: dict[str, str]) -> dict[str, Any]:
    close = _underlying_close("SPY", expiry, headers)
    result: dict[str, Any] = {"expiry": expiry, "spy_close": close}
    if close is None:
        result["error"] = "no_underlying_daily_bar"
        return result
    strike = round(close / 5) * 5
    occ = build_occ_symbol("SPY", expiry, "C", strike)
    result["occ_symbol"] = occ
    window = {"start": f"{expiry}T14:00:00Z", "end": f"{expiry}T20:00:00Z", "limit": 10}
    # The trades/bars endpoints reject a feed parameter; quotes accepts feed
    # only for plans that have it, so probe quotes with and without it.
    checks: list[tuple[str, str, str, dict[str, Any]]] = [
        ("quotes_default", OPTION_QUOTES_URL, "quotes", {**window, "symbols": occ}),
        ("trades", OPTION_TRADES_URL, "trades", {**window, "symbols": occ}),
        ("bars_1min", OPTION_BARS_URL, "bars", {**window, "symbols": occ, "timeframe": "1Min"}),
    ]
    for feed in FEEDS:
        checks.append(
            (f"quotes_feed_{feed}", OPTION_QUOTES_URL, "quotes", {**window, "symbols": occ, "feed": feed})
        )
    endpoint_results: dict[str, Any] = {}
    for name, url, key, params in checks:
        status, payload = _get(url, headers, params)
        entry = {"http_status": status, **_summarize_rows(payload, occ, key)}
        if status != 200 and isinstance(payload, dict):
            entry["message"] = str(payload.get("message") or payload.get("error") or "")[:160]
        endpoint_results[name] = entry
    result["endpoints"] = endpoint_results
    return result


def summarize(probes: list[dict[str, Any]]) -> dict[str, Any]:
    kinds = ("quotes_default", "quotes_feed_indicative", "quotes_feed_opra", "trades", "bars_1min")

    def dates_with_data(kind: str) -> list[str]:
        out = []
        for probe in probes:
            entry = (probe.get("endpoints") or {}).get(kind) or {}
            if entry.get("http_status") == 200 and entry.get("row_count", 0) > 0:
                out.append(probe["expiry"])
        return out

    summary: dict[str, Any] = {
        kind: {
            "dates_with_data": dates_with_data(kind),
            "earliest": min(dates_with_data(kind), default=None),
        }
        for kind in kinds
    }
    quote_dates = (
        summary["quotes_default"]["dates_with_data"]
        or summary["quotes_feed_opra"]["dates_with_data"]
        or summary["quotes_feed_indicative"]["dates_with_data"]
    )
    if quote_dates:
        verdict = "historical_option_quotes_available_review_nbbo_semantics_and_depth"
    elif summary["trades"]["dates_with_data"] or summary["bars_1min"]["dates_with_data"]:
        verdict = "trades_or_bars_only_no_quote_history_spread_aware_replay_still_blocked"
    else:
        verdict = "no_free_historical_minute_option_quotes_replay_requires_data_purchase_or_forward_capture"
    summary["verdict"] = verdict
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--print", action="store_true", dest="do_print")
    args = parser.parse_args()
    if load_dotenv is not None:
        load_dotenv(ROOT / "agent" / ".env")
    headers = _headers()
    probes = [probe_expiry(expiry, headers) for expiry in PROBE_EXPIRIES]
    report = {
        "provider": "alpaca_options_history_probe",
        "mode": "read_only",
        "execution_enabled": False,
        "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "summary": summarize(probes),
        "probes": probes,
        "notes": [
            "Data API only; no trading endpoints were called.",
            "A 403/entitlement response on feed=opra documents the paid boundary without purchasing it.",
        ],
    }
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(report["summary"], indent=2, sort_keys=True))
    if args.do_print:
        print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

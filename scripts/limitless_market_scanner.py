"""Read-only Limitless prediction-market scanner.

Collects active market book/spread/volume metadata and recent large feed events
from public Limitless endpoints. No API keys. No orders. No wallet connection.

This gives Vibe-Trading a third prediction-market venue beside Kalshi and
Polymarket, while keeping MoonDev-derived ideas safely in data-gathering mode.
"""
from __future__ import annotations

import argparse
import json
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
LOG_PATH = ROOT / "data" / "limitless_market_scan_log.jsonl"
REPORT_PATH = Path.home() / ".vibe-trading" / "reports" / "limitless-market-scanner.json"

API_BASE = "https://api.limitless.exchange"
MARKET_URL = "https://limitless.exchange/markets/{slug}"
PROFILE_URL = "https://limitless.exchange/profile/{wallet}"
USER_AGENT = "VibeTradingLimitlessScanner/1.0"


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        if value in (None, ""):
            return default
        return float(str(value).replace(",", ""))
    except (TypeError, ValueError):
        return default


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        if value in (None, ""):
            return default
        return int(float(str(value).replace(",", "")))
    except (TypeError, ValueError):
        return default


def _get_json(path: str, params: dict[str, Any] | None = None, timeout: int = 20) -> dict[str, Any]:
    query = urllib.parse.urlencode(params or {})
    url = f"{API_BASE}{path}" + (f"?{query}" if query else "")
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8", errors="replace"))


def _coerce_market_rows(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, dict):
        rows = payload.get("data") or payload.get("markets") or payload.get("results") or []
    elif isinstance(payload, list):
        rows = payload
    else:
        rows = []
    return [row for row in rows if isinstance(row, dict)]


def fetch_active_markets(*, pages: int = 2, page_limit: int = 25) -> list[dict[str, Any]]:
    """Fetch active Limitless markets. API currently caps page limit at 25."""
    markets: list[dict[str, Any]] = []
    for page in range(1, pages + 1):
        payload = _get_json("/markets/active", {"page": page, "limit": min(page_limit, 25)})
        rows = _coerce_market_rows(payload)
        markets.extend(rows)
        if len(rows) < min(page_limit, 25):
            break
    return markets


def fetch_feed_events(slug: str, *, limit: int = 100) -> list[dict[str, Any]]:
    payload = _get_json(f"/markets/{slug}/get-feed-events", {"page": 1, "limit": limit})
    rows = payload.get("events") if isinstance(payload, dict) else []
    return [row for row in rows or [] if isinstance(row, dict)]


def _prices_from_market(market: dict[str, Any]) -> tuple[float | None, float | None]:
    prices = market.get("prices")
    if isinstance(prices, list) and len(prices) >= 2:
        return _safe_float(prices[0]), _safe_float(prices[1])
    return None, None


def _limit_prices_from_market(market: dict[str, Any]) -> dict[str, float | None]:
    trade_prices = market.get("tradePrices") or market.get("trade_prices") or {}
    buy = trade_prices.get("buy") if isinstance(trade_prices, dict) else {}
    sell = trade_prices.get("sell") if isinstance(trade_prices, dict) else {}

    def parse_pair(value: Any) -> tuple[float | None, float | None]:
        if isinstance(value, str):
            parts = value.replace(",", " ").split()
            if len(parts) >= 2:
                return _safe_float(parts[0]), _safe_float(parts[1])
        if isinstance(value, list) and len(value) >= 2:
            return _safe_float(value[0]), _safe_float(value[1])
        return None, None

    yes_ask, no_ask = parse_pair(buy.get("limit") if isinstance(buy, dict) else None)
    yes_bid, no_bid = parse_pair(sell.get("limit") if isinstance(sell, dict) else None)
    yes_bid, yes_ask = _normalize_bid_ask(yes_bid, yes_ask)
    no_bid, no_ask = _normalize_bid_ask(no_bid, no_ask)
    return {
        "yes_bid": yes_bid,
        "yes_ask": yes_ask,
        "no_bid": no_bid,
        "no_ask": no_ask,
    }


def _normalize_bid_ask(bid: float | None, ask: float | None) -> tuple[float | None, float | None]:
    """Return bid <= ask when both sides are present.

    Limitless tradePrices can be presented from the user's buy/sell perspective.
    For scanner context we only need a non-negative width, so normalize the pair.
    """
    if bid is None or ask is None:
        return bid, ask
    return (bid, ask) if bid <= ask else (ask, bid)


def normalize_market(market: dict[str, Any]) -> dict[str, Any]:
    slug = str(market.get("slug") or "")
    yes_price, no_price = _prices_from_market(market)
    book = _limit_prices_from_market(market)
    yes_spread = None
    no_spread = None
    if book["yes_bid"] is not None and book["yes_ask"] is not None:
        yes_spread = round(float(book["yes_ask"]) - float(book["yes_bid"]), 4)
    if book["no_bid"] is not None and book["no_ask"] is not None:
        no_spread = round(float(book["no_ask"]) - float(book["no_bid"]), 4)

    metadata = market.get("metadata") if isinstance(market.get("metadata"), dict) else {}
    settings = market.get("settings") if isinstance(market.get("settings"), dict) else {}
    return {
        "id": market.get("id"),
        "slug": slug,
        "stable_slug": market.get("stableSlug") or market.get("stable_slug"),
        "title": market.get("title") or market.get("question"),
        "status": market.get("status"),
        "categories": market.get("categories") or [],
        "expiration_timestamp": market.get("expirationTimestamp") or market.get("expiration_timestamp"),
        "volume": _safe_float(market.get("volumeFormatted") or market.get("volume")),
        "trade_type": market.get("tradeType") or market.get("trade_type"),
        "market_type": market.get("marketType") or market.get("market_type"),
        "yes_price": yes_price,
        "no_price": no_price,
        "book": book,
        "yes_spread": yes_spread,
        "no_spread": no_spread,
        "max_spread": _safe_float(metadata.get("maxSpread") or settings.get("maxSpread"), default=0.0),
        "is_poly_arbitrage": bool(metadata.get("isPolyArbitrage") or market.get("isPolyArbitrage")),
        "open_price": metadata.get("openPrice"),
        "oracle_pair": (metadata.get("chainlinkDataStream") or {}).get("pair") if isinstance(metadata.get("chainlinkDataStream"), dict) else None,
        "url": MARKET_URL.format(slug=slug) if slug else None,
    }


def _event_id(event: dict[str, Any]) -> str:
    for key in ("id", "txHash", "transactionHash", "transaction_hash", "hash"):
        value = event.get(key)
        if value:
            return str(value)
    data = event.get("data") if isinstance(event.get("data"), dict) else {}
    for key in ("id", "txHash", "transactionHash", "transaction_hash", "hash"):
        value = data.get(key)
        if value:
            return str(value)
    return json.dumps(event, sort_keys=True)[:120]


def normalize_feed_event(event: dict[str, Any], market: dict[str, Any]) -> dict[str, Any] | None:
    data = event.get("data") if isinstance(event.get("data"), dict) else event
    usd = _safe_float(
        data.get("tradeAmountUSD")
        or data.get("trade_amount_usd")
        or data.get("amountUSD")
        or data.get("value")
        or data.get("notional")
    )
    wallet = str(data.get("wallet") or data.get("address") or data.get("user") or data.get("maker") or "")
    if not usd and not wallet:
        return None
    outcome = data.get("outcome") or data.get("outcomeName") or data.get("side")
    return {
        "event_id": _event_id(event),
        "market_slug": market.get("slug"),
        "market_title": market.get("title"),
        "timestamp": event.get("timestamp") or data.get("timestamp") or data.get("createdAt"),
        "wallet": wallet or None,
        "wallet_url": PROFILE_URL.format(wallet=wallet.lower()) if wallet else None,
        "outcome": outcome,
        "side": data.get("side") or data.get("type"),
        "usd": round(usd, 2),
        "raw_type": event.get("type") or data.get("type"),
    }


def scan_limitless(*, top: int = 50, min_usd: float = 100.0, feed_limit: int = 100) -> dict[str, Any]:
    markets = fetch_active_markets(pages=max(1, (top + 24) // 25), page_limit=25)
    normalized = [normalize_market(market) for market in markets]
    normalized.sort(key=lambda row: row.get("volume") or 0.0, reverse=True)
    selected = normalized[:top]

    market_by_slug = {row["slug"]: row for row in selected if row.get("slug")}
    whale_events: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []
    for market in selected:
        slug = market.get("slug")
        if not slug:
            continue
        try:
            for event in fetch_feed_events(slug, limit=feed_limit):
                normalized_event = normalize_feed_event(event, market)
                if normalized_event and normalized_event["usd"] >= min_usd:
                    whale_events.append(normalized_event)
        except Exception as exc:
            errors.append({"slug": slug, "error": str(exc)[:160]})
        time.sleep(0.05)

    whale_events.sort(key=lambda row: row.get("usd") or 0.0, reverse=True)
    poly_markets = [m for m in selected if m.get("is_poly_arbitrage")]
    wide_spread = [
        m for m in selected
        if (m.get("yes_spread") is not None and m["yes_spread"] >= 0.08)
        or (m.get("no_spread") is not None and m["no_spread"] >= 0.08)
    ]
    return {
        "date": datetime.now(timezone.utc).date().isoformat(),
        "timestamp": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "provider": "limitless_market_scanner",
        "mode": "read_only",
        "execution_enabled": False,
        "api_base": API_BASE,
        "markets_scanned": len(selected),
        "poly_arbitrage_count": len(poly_markets),
        "wide_spread_count": len(wide_spread),
        "whale_event_count": len(whale_events),
        "min_usd": min_usd,
        "top_markets": selected[:10],
        "poly_arbitrage_markets": poly_markets[:10],
        "wide_spread_markets": wide_spread[:10],
        "whale_events": whale_events[:50],
        "errors": errors,
        "warnings": [
            "Read-only scanner. No API keys, wallet signatures, approvals, or orders are used.",
            "Limitless is a lower-liquidity venue; spreads and fill probability must be measured before any paper execution.",
        ],
    }


def append_log(entry: dict[str, Any], log_path: Path = LOG_PATH) -> None:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(entry, separators=(",", ":")) + "\n")


def write_report(entry: dict[str, Any], report_path: Path = REPORT_PATH) -> Path:
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(entry, indent=2), encoding="utf-8")
    return report_path


def print_report(entry: dict[str, Any]) -> None:
    print("\nLimitless Market Scanner | read-only")
    print("=" * 60)
    print(
        f"Markets={entry['markets_scanned']} poly_arb={entry['poly_arbitrage_count']} "
        f"wide_spread={entry['wide_spread_count']} whale_events={entry['whale_event_count']}"
    )
    print("\nTop markets:")
    for market in entry["top_markets"][:5]:
        print(
            f"- {market.get('title')} | vol={market.get('volume'):.2f} "
            f"yes={market.get('yes_price')} no={market.get('no_price')} "
            f"spread={market.get('yes_spread')}/{market.get('no_spread')}"
        )
    if entry["whale_events"]:
        print("\nLargest feed events:")
        for event in entry["whale_events"][:5]:
            print(f"- ${event['usd']:,.0f} {event.get('outcome') or ''} | {event.get('market_title')}")
    print("\nNo orders placed.\n")


def main() -> int:
    parser = argparse.ArgumentParser(description="Scan public Limitless prediction-market data.")
    parser.add_argument("--top", type=int, default=50, help="Top active markets by volume to inspect.")
    parser.add_argument("--min-usd", type=float, default=100.0, help="Minimum feed event USD notional.")
    parser.add_argument("--feed-limit", type=int, default=100, help="Feed events per market.")
    parser.add_argument("--log-path", type=Path, default=LOG_PATH)
    parser.add_argument("--report-path", type=Path, default=REPORT_PATH)
    parser.add_argument("--print", action="store_true", dest="print_output")
    args = parser.parse_args()

    entry = scan_limitless(top=args.top, min_usd=args.min_usd, feed_limit=args.feed_limit)
    append_log(entry, args.log_path)
    write_report(entry, args.report_path)
    if args.print_output:
        print_report(entry)
    else:
        print(f"Limitless scan logged to {args.log_path}")
        print(f"Limitless report written to {args.report_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

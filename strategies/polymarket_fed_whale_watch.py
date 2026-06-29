#!/usr/bin/env python3
"""Read-only Polymarket Fed whale watch.

Tracks large public trades in Fed/rate decision markets using Polymarket's
public data endpoints. This is an intelligence layer only: no keys, no
signatures, no orders, and no copy execution.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from strategies.copy_trader_watchlist import DEFAULT_PROFILES_FILE, load_profiles, score_trader

GAMMA_API_BASE = "https://gamma-api.polymarket.com"
DATA_API_BASE = "https://data-api.polymarket.com"
RUNTIME_DIR = Path(os.path.expanduser(r"~\.vibe-trading"))
REPORT_DIR = RUNTIME_DIR / "reports"
REPORT_FILE = REPORT_DIR / "polymarket-fed-whale-watch.json"
DEFAULT_CONFIG_FILE = RUNTIME_DIR / "polymarket-fed-watch.json"
DEFAULT_TIMEOUT_SECONDS = 20
DEFAULT_MIN_TRADE_NOTIONAL = 10_000.0
DEFAULT_CONSENSUS_NOTIONAL = 250_000.0
DEFAULT_MIN_WHALES = 3
DEFAULT_EVENT_SLUGS = [
    "how-many-fed-rate-cuts-in-2026",
    "fed-emergency-rate-cut-before-2027",
    "what-will-fed-rate-hit-before-2027",
    "fed-decision-in-july",
    "fed-decision-in-september",
    "fed-decision-in-december",
]
FED_KEYWORDS = ("fed", "fomc", "interest rate", "rate cut", "rate hike", "bps", "federal reserve")


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None or value == "":
            return default
        return float(str(value).replace(",", "").replace("$", ""))
    except (TypeError, ValueError):
        return default


def _coerce_rows(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    if isinstance(payload, dict):
        for key in ("data", "events", "markets", "trades", "results"):
            value = payload.get(key)
            if isinstance(value, list):
                return [item for item in value if isinstance(item, dict)]
    return []


def _parse_json_list(value: Any) -> list[Any]:
    if isinstance(value, list):
        return value
    if isinstance(value, str) and value.strip():
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            return []
        return parsed if isinstance(parsed, list) else []
    return []


def _utc_date(value: Any) -> str:
    if value in (None, ""):
        return ""
    if isinstance(value, (int, float)) or str(value).isdigit():
        ts = float(value)
        if ts > 10_000_000_000:
            ts = ts / 1000
        return datetime.fromtimestamp(ts, timezone.utc).isoformat()
    return str(value)


def _is_fed_market(row: dict[str, Any]) -> bool:
    text = " ".join(
        str(row.get(key) or "")
        for key in ("question", "title", "description", "slug", "eventSlug")
    ).lower()
    return any(keyword in text for keyword in FED_KEYWORDS)


@dataclass(frozen=True)
class FedMarket:
    condition_id: str
    question: str
    slug: str
    event_slug: str
    active: bool
    closed: bool
    accepting_orders: bool
    volume: float
    liquidity: float
    prices: dict[str, float]


class PolymarketFedClient:
    def __init__(self, *, session: Any | None = None, timeout: int = DEFAULT_TIMEOUT_SECONDS):
        self.session = session or requests.Session()
        self.timeout = timeout

    def _get(self, url: str, params: dict[str, Any]) -> Any:
        response = self.session.get(url, params=params, timeout=self.timeout)
        response.raise_for_status()
        return response.json()

    def fetch_event(self, slug: str) -> dict[str, Any] | None:
        rows = _coerce_rows(self._get(f"{GAMMA_API_BASE}/events", {"slug": slug}))
        return rows[0] if rows else None

    def fetch_recent_trades(self, condition_id: str, *, limit: int = 500) -> list[dict[str, Any]]:
        return _coerce_rows(self._get(f"{DATA_API_BASE}/trades", {"market": condition_id, "limit": limit}))


def _market_from_gamma(row: dict[str, Any], *, event_slug: str) -> FedMarket | None:
    condition_id = str(row.get("conditionId") or row.get("condition_id") or "")
    if not condition_id:
        return None
    outcomes = [str(item) for item in _parse_json_list(row.get("outcomes"))]
    prices = [_safe_float(item) for item in _parse_json_list(row.get("outcomePrices"))]
    price_map = {outcome: prices[idx] for idx, outcome in enumerate(outcomes) if idx < len(prices)}
    return FedMarket(
        condition_id=condition_id,
        question=str(row.get("question") or row.get("title") or condition_id),
        slug=str(row.get("slug") or ""),
        event_slug=event_slug,
        active=bool(row.get("active")),
        closed=bool(row.get("closed")),
        accepting_orders=bool(row.get("acceptingOrders", row.get("accepting_orders", False))),
        volume=_safe_float(row.get("volume") or row.get("volumeNum") or row.get("volumeClob")),
        liquidity=_safe_float(row.get("liquidity") or row.get("liquidityClob")),
        prices=price_map,
    )


def discover_fed_markets(
    client: PolymarketFedClient,
    *,
    event_slugs: list[str],
    include_closed: bool = False,
) -> list[FedMarket]:
    markets: list[FedMarket] = []
    seen: set[str] = set()
    for slug in event_slugs:
        event = client.fetch_event(slug)
        if not event:
            continue
        for row in _coerce_rows(event.get("markets")):
            market = _market_from_gamma(row, event_slug=str(event.get("slug") or slug))
            if not market or market.condition_id in seen:
                continue
            if not _is_fed_market(row):
                continue
            if market.closed and not include_closed:
                continue
            markets.append(market)
            seen.add(market.condition_id)
    return sorted(markets, key=lambda item: item.volume, reverse=True)


def _known_wallet_scores(profiles_path: Path) -> dict[str, dict[str, Any]]:
    scores: dict[str, dict[str, Any]] = {}
    for profile in load_profiles(profiles_path):
        scored = score_trader(profile)
        handle = profile.handle.lower()
        scores[handle] = {
            "status": scored.status,
            "confidence": scored.confidence,
            "trades": scored.trades,
            "win_rate": scored.win_rate,
            "profit_factor": scored.profit_factor,
        }
    return scores


def _normalize_trade(row: dict[str, Any], market: FedMarket, wallet_scores: dict[str, dict[str, Any]]) -> dict[str, Any]:
    size = _safe_float(row.get("size") or row.get("shares") or row.get("amount"))
    price = _safe_float(row.get("price"))
    notional = size * price
    wallet = str(row.get("proxyWallet") or row.get("wallet") or row.get("user") or "")
    score = wallet_scores.get(wallet.lower(), {})
    return {
        "wallet": wallet,
        "name": str(row.get("name") or row.get("pseudonym") or ""),
        "market": str(row.get("title") or market.question),
        "market_slug": str(row.get("slug") or market.slug),
        "event_slug": str(row.get("eventSlug") or market.event_slug),
        "condition_id": market.condition_id,
        "side": str(row.get("side") or "").upper(),
        "outcome": str(row.get("outcome") or ""),
        "price": price,
        "size": size,
        "notional": round(notional, 2),
        "timestamp": _utc_date(row.get("timestamp") or row.get("createdAt")),
        "transaction_hash": str(row.get("transactionHash") or ""),
        "known_profile_status": score.get("status", "unknown"),
        "known_profile_confidence": int(_safe_float(score.get("confidence"))),
    }


def _consensus_from_trades(
    whale_trades: list[dict[str, Any]],
    *,
    min_whales: int,
    consensus_notional: float,
) -> list[dict[str, Any]]:
    groups: dict[tuple[str, str, str], list[dict[str, Any]]] = defaultdict(list)
    for trade in whale_trades:
        groups[(str(trade["condition_id"]), str(trade["outcome"]), str(trade["side"]))].append(trade)

    rows: list[dict[str, Any]] = []
    for (condition_id, outcome, side), trades in groups.items():
        wallets = sorted({str(trade.get("wallet")) for trade in trades if trade.get("wallet")})
        total = sum(_safe_float(trade.get("notional")) for trade in trades)
        if len(wallets) >= min_whales and total >= consensus_notional:
            rows.append({
                "condition_id": condition_id,
                "market": str(trades[0].get("market") or ""),
                "event_slug": str(trades[0].get("event_slug") or ""),
                "outcome": outcome,
                "side": side,
                "wallet_count": len(wallets),
                "total_notional": round(total, 2),
                "wallets": wallets[:10],
                "action": "paper_watch",
                "reason": "large same-market whale consensus; read-only signal only",
            })
    return sorted(rows, key=lambda item: item["total_notional"], reverse=True)


def load_watch_config(path: Path = DEFAULT_CONFIG_FILE) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def build_fed_whale_report(
    *,
    client: PolymarketFedClient | None = None,
    event_slugs: list[str] | None = None,
    include_closed: bool = False,
    min_trade_notional: float = DEFAULT_MIN_TRADE_NOTIONAL,
    consensus_notional: float = DEFAULT_CONSENSUS_NOTIONAL,
    min_whales: int = DEFAULT_MIN_WHALES,
    limit: int = 500,
    profiles_path: Path = DEFAULT_PROFILES_FILE,
) -> dict[str, Any]:
    active_client = client or PolymarketFedClient()
    slugs = event_slugs or DEFAULT_EVENT_SLUGS
    markets = discover_fed_markets(active_client, event_slugs=slugs, include_closed=include_closed)
    wallet_scores = _known_wallet_scores(profiles_path)

    all_whales: list[dict[str, Any]] = []
    market_rows: list[dict[str, Any]] = []
    for market in markets:
        raw_trades = active_client.fetch_recent_trades(market.condition_id, limit=limit)
        normalized = [_normalize_trade(row, market, wallet_scores) for row in raw_trades]
        whales = [trade for trade in normalized if _safe_float(trade.get("notional")) >= min_trade_notional]
        whales.sort(key=lambda item: _safe_float(item.get("notional")), reverse=True)
        all_whales.extend(whales)
        market_rows.append({
            "condition_id": market.condition_id,
            "question": market.question,
            "slug": market.slug,
            "event_slug": market.event_slug,
            "active": market.active,
            "closed": market.closed,
            "accepting_orders": market.accepting_orders,
            "volume": market.volume,
            "liquidity": market.liquidity,
            "prices": market.prices,
            "whale_trade_count": len(whales),
            "top_whale_notional": max([_safe_float(item.get("notional")) for item in whales] or [0.0]),
        })

    all_whales.sort(key=lambda item: _safe_float(item.get("notional")), reverse=True)
    consensus = _consensus_from_trades(all_whales, min_whales=min_whales, consensus_notional=consensus_notional)
    return {
        "provider": "polymarket_fed_whale_watch",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "mode": "read_only",
        "execution_enabled": False,
        "event_slugs": slugs,
        "markets_scanned": len(markets),
        "min_trade_notional": min_trade_notional,
        "consensus_notional": consensus_notional,
        "min_whales": min_whales,
        "whale_trade_count": len(all_whales),
        "consensus_count": len(consensus),
        "markets": market_rows[:20],
        "top_whale_trades": all_whales[:25],
        "consensus": consensus,
        "warnings": [
            "Read-only Fed/rates intelligence. No Polymarket orders are wired.",
            "A large wallet is not automatically a sharp wallet; use copy-trader scoring before trusting it.",
            "Public trade feeds can lag or omit context. Treat signals as paper_watch only.",
        ],
    }


def write_report(report: dict[str, Any], path: Path = REPORT_FILE) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    return path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build read-only Polymarket Fed whale watch report.")
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG_FILE, help="Optional JSON config with event_slugs and thresholds.")
    parser.add_argument("--event-slug", action="append", dest="event_slugs", default=[], help="Polymarket event slug to scan.")
    parser.add_argument("--include-closed", action="store_true", help="Include closed markets for endpoint/debug validation.")
    parser.add_argument("--min-trade-notional", type=float, default=None, help="Minimum trade notional for whale rows.")
    parser.add_argument("--consensus-notional", type=float, default=None, help="Minimum grouped notional for consensus.")
    parser.add_argument("--min-whales", type=int, default=None, help="Minimum unique wallets for consensus.")
    parser.add_argument("--limit", type=int, default=500, help="Max trades per market.")
    parser.add_argument("--profiles", type=Path, default=DEFAULT_PROFILES_FILE, help="Copy-trader profiles for known wallet scoring.")
    parser.add_argument("--out", type=Path, default=REPORT_FILE, help="JSON report output path.")
    parser.add_argument("--print", action="store_true", help="Print report JSON.")
    args = parser.parse_args(argv)

    config = load_watch_config(args.config)
    slugs = args.event_slugs or [str(item) for item in config.get("event_slugs", []) if item] or DEFAULT_EVENT_SLUGS
    report = build_fed_whale_report(
        event_slugs=slugs,
        include_closed=bool(args.include_closed or config.get("include_closed")),
        min_trade_notional=args.min_trade_notional
        if args.min_trade_notional is not None else _safe_float(config.get("min_trade_notional"), DEFAULT_MIN_TRADE_NOTIONAL),
        consensus_notional=args.consensus_notional
        if args.consensus_notional is not None else _safe_float(config.get("consensus_notional"), DEFAULT_CONSENSUS_NOTIONAL),
        min_whales=args.min_whales if args.min_whales is not None else int(_safe_float(config.get("min_whales"), DEFAULT_MIN_WHALES)),
        limit=args.limit,
        profiles_path=args.profiles,
    )
    write_report(report, args.out)
    if args.print:
        print(json.dumps(report, indent=2))
    else:
        print(f"Polymarket Fed whale watch report written to: {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

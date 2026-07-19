#!/usr/bin/env python3
"""Paper-only Kalshi prediction-market research helpers.

This module is intentionally read-only. It fetches/normalizes market data,
scores simulated opportunities, and writes dashboard reports. It does not
submit orders.
"""
from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

RUNTIME_DIR = Path(os.path.expanduser(r"~\.vibe-trading"))
REPORT_DIR = RUNTIME_DIR / "reports"
REPORT_FILE = REPORT_DIR / "kalshi-prediction-report.json"

DEMO_BASE_URL = "https://external-api.demo.kalshi.co/trade-api/v2"
PROD_BASE_URL = "https://external-api.kalshi.com/trade-api/v2"
DEFAULT_MAX_RISK_DOLLARS = 25.0
MIN_EDGE = 0.03
WEATHER_MAX_SOURCE_DISAGREEMENT_F = 1.5


@dataclass(frozen=True)
class KalshiSettings:
    env: str = "demo"
    base_url: str = DEMO_BASE_URL
    paper_only: bool = True
    max_risk_dollars: float = DEFAULT_MAX_RISK_DOLLARS

    @classmethod
    def from_env(cls) -> "KalshiSettings":
        env = os.getenv("KALSHI_ENV", "demo").strip().lower() or "demo"
        live_requested = os.getenv("KALSHI_ENABLE_LIVE_TRADING", "false").strip().lower() == "true"
        base_url = os.getenv("KALSHI_BASE_URL", "").strip().rstrip("/")
        if not base_url:
            base_url = PROD_BASE_URL if env == "prod" else DEMO_BASE_URL
        try:
            max_risk = float(os.getenv("KALSHI_MAX_RISK_DOLLARS", str(DEFAULT_MAX_RISK_DOLLARS)))
        except ValueError:
            max_risk = DEFAULT_MAX_RISK_DOLLARS
        return cls(
            env=env,
            base_url=base_url,
            paper_only=not live_requested,
            max_risk_dollars=max(0.0, min(max_risk, 100.0)),
        )


@dataclass(frozen=True)
class MarketSnapshot:
    ticker: str
    title: str
    category: str = ""
    close_time: str = ""
    yes_bid: float = 0.0
    yes_ask: float = 0.0
    no_bid: float = 0.0
    no_ask: float = 0.0
    volume: float = 0.0
    liquidity: float = 0.0
    open_interest: float = 0.0


@dataclass(frozen=True)
class KalshiOpportunity:
    ticker: str
    title: str
    side: str
    entry_price: float
    fair_value: float
    edge: float
    confidence: int
    max_risk_dollars: float
    reason: str


class KalshiClient:
    def __init__(self, settings: KalshiSettings | None = None, *, session: Any | None = None) -> None:
        self.settings = settings or KalshiSettings.from_env()
        if session is None:
            import requests

            session = requests.Session()
        self.session = session

    def _get(self, path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        resp = self.session.get(f"{self.settings.base_url}{path}", params=params or {}, timeout=15)
        resp.raise_for_status()
        data = resp.json()
        return data if isinstance(data, dict) else {}

    def fetch_markets(self, *, limit: int = 25, status: str = "open") -> list[dict[str, Any]]:
        data = self._get("/markets", {"limit": limit, "status": status})
        markets = data.get("markets")
        return [item for item in markets if isinstance(item, dict)] if isinstance(markets, list) else []

    def fetch_orderbook(self, ticker: str) -> dict[str, Any]:
        data = self._get(f"/markets/{ticker}/orderbook")
        orderbook = data.get("orderbook_fp") or data.get("orderbook")
        return orderbook if isinstance(orderbook, dict) else {}

    def fetch_market_snapshots(self, *, limit: int = 25) -> list[MarketSnapshot]:
        snapshots: list[MarketSnapshot] = []
        for raw in self.fetch_markets(limit=limit):
            ticker = str(raw.get("ticker") or raw.get("market_ticker") or "")
            if not ticker:
                continue
            snapshots.append(market_from_api(raw, self.fetch_orderbook(ticker)))
        return snapshots


def _safe_float(value: object, default: float = 0.0) -> float:
    try:
        if value is None or value == "":
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def _price(value: object) -> float:
    raw = _safe_float(value)
    return raw / 100.0 if raw > 1 else raw


def market_from_api(raw: dict[str, Any], orderbook: dict[str, Any] | None = None) -> MarketSnapshot:
    orderbook = orderbook or {}
    yes_raw = orderbook.get("yes_dollars") if "yes_dollars" in orderbook else orderbook.get("yes")
    no_raw = orderbook.get("no_dollars") if "no_dollars" in orderbook else orderbook.get("no")
    yes = yes_raw if isinstance(yes_raw, list) else []
    no = no_raw if isinstance(no_raw, list) else []
    yes_bids = [_price(level[0]) for level in yes if isinstance(level, list) and level]
    no_bids = [_price(level[0]) for level in no if isinstance(level, list) and level]
    yes_bid = max(yes_bids, default=_price(raw.get("yes_bid") or raw.get("yes_bid_dollars")))
    no_bid = max(no_bids, default=_price(raw.get("no_bid") or raw.get("no_bid_dollars")))
    yes_ask = max(0.0, 1.0 - no_bid) if no_bid else _price(raw.get("yes_ask") or raw.get("yes_ask_dollars"))
    no_ask = max(0.0, 1.0 - yes_bid) if yes_bid else _price(raw.get("no_ask") or raw.get("no_ask_dollars"))

    return MarketSnapshot(
        ticker=str(raw.get("ticker") or raw.get("market_ticker") or ""),
        title=str(raw.get("title") or raw.get("subtitle") or raw.get("event_title") or ""),
        category=str(raw.get("category") or raw.get("category_name") or ""),
        close_time=str(raw.get("close_time") or raw.get("expiration_time") or raw.get("latest_expiration_time") or ""),
        yes_bid=round(yes_bid, 4),
        yes_ask=round(yes_ask, 4),
        no_bid=round(no_bid, 4),
        no_ask=round(no_ask, 4),
        volume=_safe_float(raw.get("volume_fp") or raw.get("volume") or raw.get("volume_24h_fp") or raw.get("volume_24h")),
        liquidity=_safe_float(raw.get("liquidity_dollars") or raw.get("liquidity") or raw.get("liquidity_num")),
        open_interest=_safe_float(raw.get("open_interest_fp") or raw.get("open_interest")),
    )


def score_market(
    market: MarketSnapshot,
    *,
    fair_yes: float,
    source: str = "manual",
    settings: KalshiSettings | None = None,
) -> KalshiOpportunity | None:
    settings = settings or KalshiSettings.from_env()
    fair_yes = max(0.0, min(float(fair_yes), 1.0))
    yes_edge = fair_yes - market.yes_ask
    no_fair = 1.0 - fair_yes
    no_edge = no_fair - market.no_ask

    if yes_edge >= no_edge:
        side = "YES"
        entry = market.yes_ask
        edge = yes_edge
    else:
        side = "NO"
        entry = market.no_ask
        edge = no_edge

    if entry <= 0 or edge < MIN_EDGE:
        return None

    confidence = 5
    reasons = [f"{source} fair value edge"]
    if edge >= 0.05:
        confidence += 2
    elif edge >= MIN_EDGE:
        confidence += 1
    if market.volume >= 50_000 or market.open_interest >= 25_000:
        confidence += 1
        reasons.append("liquid market")
    if market.liquidity >= 5_000:
        confidence += 1
        reasons.append("visible depth")
    if max(market.yes_ask - market.yes_bid, market.no_ask - market.no_bid) <= 0.08:
        confidence += 1
        reasons.append("spread controlled")

    return KalshiOpportunity(
        ticker=market.ticker,
        title=market.title,
        side=side,
        entry_price=round(entry, 4),
        fair_value=round(fair_yes if side == "YES" else no_fair, 4),
        edge=round(edge, 4),
        confidence=min(confidence, 10),
        max_risk_dollars=settings.max_risk_dollars,
        reason=", ".join(reasons),
    )


def weather_consensus_fair_temperature(
    forecasts: dict[str, float],
    *,
    max_source_disagreement: float = WEATHER_MAX_SOURCE_DISAGREEMENT_F,
) -> dict[str, Any] | None:
    clean = {str(source): _safe_float(value) for source, value in forecasts.items() if value is not None}
    clean = {source: value for source, value in clean.items() if value != 0.0}
    if len(clean) < 2:
        return None
    values = list(clean.values())
    source_range = round(max(values) - min(values), 2)
    fair_temperature = round(sum(values) / len(values), 1)
    allowed = source_range <= max_source_disagreement
    return {
        "allowed": allowed,
        "fair_temperature": fair_temperature,
        "source_range": source_range,
        "sources": clean,
        "reason": "forecast consensus" if allowed else "sources disagree beyond 1.5F",
    }


def build_report(
    markets: list[MarketSnapshot],
    *,
    fair_values: dict[str, float] | None = None,
    settings: KalshiSettings | None = None,
) -> dict[str, Any]:
    settings = settings or KalshiSettings.from_env()
    fair_values = fair_values or {}
    opportunities: list[KalshiOpportunity] = []
    for market in markets:
        if market.ticker not in fair_values:
            continue
        scored = score_market(market, fair_yes=fair_values[market.ticker], source="model", settings=settings)
        if scored:
            opportunities.append(scored)
    opportunities.sort(key=lambda item: (item.confidence, item.edge), reverse=True)

    warnings = ["Paper-only: no Kalshi order submission is implemented."]
    if not fair_values:
        warnings.append("No fair-value model supplied yet; report is market-data only.")
    if not settings.paper_only:
        warnings.append("Live trading was requested, but this module still refuses to execute orders.")

    return {
        "provider": "kalshi",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "env": settings.env,
        "base_url": settings.base_url,
        "mode": "paper_only",
        "execution_enabled": False,
        "can_submit_orders": False,
        "markets_scanned": len(markets),
        "opportunities": [asdict(item) for item in opportunities[:20]],
        "warnings": warnings,
    }


def write_report(report: dict[str, Any], path: Path = REPORT_FILE) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, indent=2), encoding="utf-8")


def load_fair_values(path: Path | None) -> dict[str, float]:
    if path is None or not path.exists():
        return {}
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        return {}
    return {str(key): _safe_float(value) for key, value in data.items()}


def run_scan(
    *,
    client: KalshiClient | Any | None = None,
    fair_values: dict[str, float] | None = None,
    out: Path = REPORT_FILE,
    limit: int = 25,
    settings: KalshiSettings | None = None,
) -> dict[str, Any]:
    settings = settings or KalshiSettings.from_env()
    client = client or KalshiClient(settings)
    markets = client.fetch_market_snapshots(limit=limit)
    report = build_report(markets, fair_values=fair_values or {}, settings=settings)
    write_report(report, out)
    return report

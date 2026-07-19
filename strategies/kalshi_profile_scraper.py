#!/usr/bin/env python3
"""Read-only Kalshi public profile scraper for copy-trader scoring.

Uses unauthenticated public social endpoints discovered from Kalshi profile
pages. This module never follows users, logs in, or places orders.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from strategies.copy_trader_watchlist import DEFAULT_PROFILES_FILE, TraderProfile
from strategies.trade_history_importer import NormalisedTrade, derive_all_metrics, upsert_profile

KALSHI_SOCIAL_BASE = "https://api.elections.kalshi.com/v1"
RUNTIME_DIR = Path.home() / ".vibe-trading"
REPORT_DIR = RUNTIME_DIR / "reports"
REPORT_FILE = REPORT_DIR / "kalshi-profile-scraper-report.json"


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None or value == "":
            return default
        return float(str(value).replace(",", "").replace("$", ""))
    except (TypeError, ValueError):
        return default


def _money_from_kalshi(value: Any) -> float:
    """Kalshi social PnL values render as value / 10_000 dollars in the app."""
    return round(_safe_float(value) / 10_000.0, 6)


def _event_date(event_ticker: str) -> str:
    match = re.search(r"-(\d{2})(JAN|FEB|MAR|APR|MAY|JUN|JUL|AUG|SEP|OCT|NOV|DEC)(\d{2})", event_ticker.upper())
    if not match:
        return datetime.now(timezone.utc).strftime("%Y-%m-%d")
    year, month_text, day = match.groups()
    months = {
        "JAN": "01",
        "FEB": "02",
        "MAR": "03",
        "APR": "04",
        "MAY": "05",
        "JUN": "06",
        "JUL": "07",
        "AUG": "08",
        "SEP": "09",
        "OCT": "10",
        "NOV": "11",
        "DEC": "12",
    }
    return f"20{year}-{months[month_text]}-{day}"


class KalshiProfileClient:
    def __init__(self, *, base_url: str = KALSHI_SOCIAL_BASE, session: Any | None = None) -> None:
        self.base_url = base_url.rstrip("/")
        self.session = session or requests.Session()

    def _get(self, path: str, params: dict[str, Any]) -> dict[str, Any]:
        response = self.session.get(
            f"{self.base_url}{path}",
            params=params,
            headers={"Accept": "application/json", "User-Agent": "VibeTradingBot/1.0"},
            timeout=20,
        )
        response.raise_for_status()
        data = response.json()
        return data if isinstance(data, dict) else {}

    def fetch_metrics(self, nickname: str) -> dict[str, Any]:
        return self._get("/social/profile/metrics", {"nickname": nickname})

    def fetch_holdings(
        self,
        nickname: str,
        *,
        include_closed: bool = True,
        limit: int = 100,
        cursor: str | None = None,
    ) -> dict[str, Any]:
        params: dict[str, Any] = {
            "nickname": nickname,
            "limit": max(1, min(limit, 100)),
            "closed_positions": str(include_closed).lower(),
        }
        if cursor:
            params["cursor"] = cursor
        return self._get("/social/profile/holdings", params)


def holding_to_trades(holding: dict[str, Any]) -> list[NormalisedTrade]:
    event_ticker = str(holding.get("event_ticker") or holding.get("series_ticker") or "")
    date = _event_date(event_ticker)
    trades: list[NormalisedTrade] = []
    for market in holding.get("market_holdings") or []:
        if not isinstance(market, dict):
            continue
        symbol = str(market.get("market_ticker") or event_ticker)
        position = abs(_safe_float(market.get("signed_open_position") or market.get("signed_open_position_fp")))
        trades.append(
            NormalisedTrade(
                date=date,
                symbol=symbol,
                pnl=_money_from_kalshi(market.get("pnl")),
                fee=0.0,
                notional=position,
            )
        )
    return trades


def _public_metrics(raw: dict[str, Any]) -> dict[str, Any]:
    metrics = raw.get("metrics") if isinstance(raw.get("metrics"), dict) else {}
    return {
        "pnl": _money_from_kalshi(metrics.get("pnl")),
        "num_markets_traded": int(_safe_float(metrics.get("num_markets_traded"))),
        "volume": _safe_float(metrics.get("volume") or metrics.get("volume_fp")),
        "dollars_traded": _money_from_kalshi(metrics.get("dollars_traded")),
        "social_id": raw.get("social_id"),
    }


def fetch_closed_position_trades(
    nickname: str,
    *,
    client: KalshiProfileClient,
    max_pages: int = 5,
    page_limit: int = 100,
) -> tuple[list[NormalisedTrade], str]:
    trades: list[NormalisedTrade] = []
    cursor: str | None = None
    visibility = "unknown"
    for _ in range(max_pages):
        data = client.fetch_holdings(nickname, include_closed=True, limit=page_limit, cursor=cursor)
        visibility = str(data.get("visibility_state") or visibility)
        holdings = data.get("holdings") if isinstance(data.get("holdings"), list) else []
        for holding in holdings:
            if isinstance(holding, dict):
                trades.extend(holding_to_trades(holding))
        cursor = data.get("cursor")
        if not cursor:
            break
    return trades, visibility


def build_profile_report(
    nickname: str,
    *,
    client: KalshiProfileClient | None = None,
    max_pages: int = 5,
) -> dict[str, Any]:
    client = client or KalshiProfileClient()
    metrics_raw = client.fetch_metrics(nickname)
    trades, visibility = fetch_closed_position_trades(nickname, client=client, max_pages=max_pages)
    derived = derive_all_metrics(trades)
    wins = [trade for trade in trades if trade.pnl > 0]
    if trades:
        derived["win_rate"] = round(len(wins) / len(trades), 4)
    public_metrics = _public_metrics(metrics_raw)
    return {
        "provider": "kalshi_profile_scraper",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "mode": "read_only",
        "execution_enabled": False,
        "handle": nickname,
        "platform": "kalshi",
        "source": "public_profile",
        "category": "prediction_market",
        "visibility_state": visibility,
        "public_metrics": public_metrics,
        **derived,
        "warnings": [
            "Read-only: public Kalshi social profile endpoints only.",
            "Win rate is computed from closed public holdings where Kalshi exposes PnL.",
        ],
    }


def write_report(report: dict[str, Any], path: Path = REPORT_FILE) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    return path


def upsert_kalshi_public_profile(report: dict[str, Any], *, profiles_path: Path = DEFAULT_PROFILES_FILE) -> TraderProfile:
    metric_keys = {
        "trades",
        "win_rate",
        "realized_pnl",
        "max_drawdown_pct",
        "profit_factor",
        "pnl_smoothness",
        "green_months",
        "monthly_consistency",
        "worst_month_pct",
        "avg_edge_per_trade",
        "fee_adjusted_return",
        "trade_frequency",
    }
    metrics = {key: report[key] for key in metric_keys if key in report}
    profile = upsert_profile(
        handle=str(report.get("handle") or ""),
        platform="kalshi",
        source="public_profile",
        category=str(report.get("category") or "prediction_market"),
        metrics=metrics,
        profiles_path=profiles_path,
    )
    data = json.loads(profiles_path.read_text(encoding="utf-8-sig"))
    for item in data:
        if item.get("handle") == profile.handle and item.get("platform") == profile.platform:
            item["verified"] = True
            break
    profiles_path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    return TraderProfile(**{**profile.__dict__, "verified": True}) if hasattr(profile, "__dict__") else profile


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Fetch public Kalshi profile holdings and update copy-trader scoring.")
    parser.add_argument("--username", "--nickname", dest="nickname", required=True)
    parser.add_argument("--max-pages", type=int, default=5)
    parser.add_argument("--out", type=Path, default=REPORT_FILE)
    parser.add_argument("--append-profiles", action="store_true")
    parser.add_argument("--profiles", type=Path, default=DEFAULT_PROFILES_FILE)
    parser.add_argument("--print", action="store_true")
    args = parser.parse_args(argv)

    report = build_profile_report(args.nickname, max_pages=args.max_pages)
    write_report(report, args.out)
    if args.append_profiles:
        upsert_kalshi_public_profile(report, profiles_path=args.profiles)
    if args.print:
        print(json.dumps(report, indent=2))
    else:
        print(f"Kalshi profile report written to: {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

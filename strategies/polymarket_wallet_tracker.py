#!/usr/bin/env python3
"""Read-only Polymarket public wallet tracker.

Fetches public wallet activity and closed-position history, normalizes it into
the copy-trader diligence model, and can upsert the resulting profile into
copy-trader-profiles.json.

No API keys. No private keys. No order placement.
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from strategies.copy_trader_watchlist import DEFAULT_PROFILES_FILE, TraderProfile, profile_from_dict, score_trader
from strategies.trade_history_importer import NormalisedTrade, derive_all_metrics, upsert_profile

DATA_API_BASE = "https://data-api.polymarket.com"
CLOB_API_BASE = "https://clob.polymarket.com"
RUNTIME_DIR = Path.home() / ".vibe-trading"
REPORT_DIR = RUNTIME_DIR / "reports"
REPORT_FILE = REPORT_DIR / "polymarket-wallet-tracker.json"
DEFAULT_TIMEOUT_SECONDS = 20


def _coerce_rows(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    if isinstance(payload, dict):
        for key in ("data", "activity", "trades", "positions", "results"):
            value = payload.get(key)
            if isinstance(value, list):
                return [item for item in value if isinstance(item, dict)]
    return []


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None or value == "":
            return default
        return float(str(value).replace("$", "").replace(",", ""))
    except (TypeError, ValueError):
        return default


def _safe_timestamp(value: Any) -> str:
    if value in (None, ""):
        return datetime.now(timezone.utc).strftime("%Y-%m-%d")
    if isinstance(value, (int, float)) or str(value).isdigit():
        ts = float(value)
        if ts > 10_000_000_000:
            ts = ts / 1000
        return datetime.fromtimestamp(ts, timezone.utc).strftime("%Y-%m-%d")
    text = str(value)
    return text[:10]


def _first(row: dict[str, Any], *keys: str, default: Any = "") -> Any:
    lower = {str(k).lower(): v for k, v in row.items()}
    for key in keys:
        if key in row and row[key] not in (None, ""):
            return row[key]
        value = lower.get(key.lower())
        if value not in (None, ""):
            return value
    return default


def _market_name(row: dict[str, Any]) -> str:
    return str(_first(row, "market", "market_title", "title", "question", "conditionId", "asset", default=""))


def _outcome(row: dict[str, Any]) -> str:
    return str(_first(row, "outcome", "outcomeName", "asset", "side", default="")).upper()


def _row_to_activity_trade(row: dict[str, Any]) -> NormalisedTrade:
    size = _safe_float(_first(row, "size", "shares", "amount", "quantity"))
    price = _safe_float(_first(row, "price", "avgPrice", "avg_price", "lastPrice"))
    notional = _safe_float(_first(row, "notional", "value"), size * price)
    pnl = _safe_float(_first(row, "profit_loss", "profitLoss", "realized_pnl", "realizedPnl", "pnl"))
    fee = _safe_float(_first(row, "fee", "fees", "maker_fee", "taker_fee"))
    return NormalisedTrade(
        date=_safe_timestamp(_first(row, "timestamp", "createdAt", "created_at", "time", "date")),
        symbol=_market_name(row) or _outcome(row),
        pnl=pnl,
        fee=fee,
        notional=notional,
    )


def _row_to_closed_position_trade(row: dict[str, Any]) -> NormalisedTrade:
    size = _safe_float(_first(row, "size", "shares", "amount", "quantity", "position"))
    price = _safe_float(_first(row, "avgPrice", "averagePrice", "price", "avg_price"), 1.0)
    notional = _safe_float(_first(row, "notional", "value", "totalBought", "total_bought"), abs(size * price))
    pnl = _safe_float(_first(row, "realized_pnl", "realizedPnl", "profit_loss", "profitLoss", "pnl"))
    fee = _safe_float(_first(row, "fee", "fees"))
    return NormalisedTrade(
        date=_safe_timestamp(_first(row, "timestamp", "closedAt", "closed_at", "createdAt", "date")),
        symbol=_market_name(row) or _outcome(row),
        pnl=pnl,
        fee=fee,
        notional=notional,
    )


def _profile_metrics_from_rows(activity: list[dict[str, Any]], closed_positions: list[dict[str, Any]]) -> dict[str, Any]:
    # Prefer activity (all trades incl. losses) over closed-positions.
    # Polymarket /closed-positions only returns winning resolved positions —
    # using it alone produces 100% win rate / infinite profit_factor (survivorship bias).
    source_rows = activity if activity else closed_positions
    parser = _row_to_activity_trade if activity else _row_to_closed_position_trade
    trades = [parser(row) for row in source_rows]
    metrics = derive_all_metrics(trades)
    if not metrics and activity:
        metrics = {"trades": len(activity), "win_rate": 0.0, "realized_pnl": 0.0}
    metrics["raw_activity_count"] = len(activity)
    metrics["closed_position_count"] = len(closed_positions)
    return metrics


class PolymarketPublicClient:
    """Small read-only client for public Polymarket wallet endpoints."""

    def __init__(self, *, session: Any | None = None, timeout: int = DEFAULT_TIMEOUT_SECONDS):
        self.session = session or requests.Session()
        self.timeout = timeout

    def _get(self, url: str, params: dict[str, Any]) -> list[dict[str, Any]]:
        response = self.session.get(url, params=params, timeout=self.timeout)
        response.raise_for_status()
        return _coerce_rows(response.json())

    def fetch_wallet_activity(self, address: str, *, limit: int = 500) -> list[dict[str, Any]]:
        return self._get(f"{DATA_API_BASE}/activity", {"user": address, "limit": limit})

    def fetch_closed_positions(self, address: str, *, limit: int = 500) -> list[dict[str, Any]]:
        return self._get(f"{DATA_API_BASE}/closed-positions", {"user": address, "limit": limit})

    def fetch_clob_trades(self, address: str, *, limit: int = 500) -> list[dict[str, Any]]:
        return self._get(f"{CLOB_API_BASE}/trades", {"maker_address": address, "limit": limit})

    def fetch_wallet_trades(self, address: str, *, limit: int = 500) -> list[dict[str, Any]]:
        try:
            activity = self.fetch_wallet_activity(address, limit=limit)
            if activity:
                return activity
        except Exception:
            pass
        return self.fetch_clob_trades(address, limit=limit)


def fetch_wallet_trades(
    address: str,
    *,
    limit: int = 500,
    client: PolymarketPublicClient | None = None,
) -> list[dict[str, Any]]:
    return (client or PolymarketPublicClient()).fetch_wallet_trades(address, limit=limit)


def wallet_to_csv(
    address: str,
    out_path: Path,
    *,
    limit: int = 500,
    client: PolymarketPublicClient | None = None,
) -> Path:
    rows = fetch_wallet_trades(address, limit=limit, client=client)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=["timestamp", "market", "outcome", "shares", "price", "profit_loss", "fee"],
        )
        writer.writeheader()
        for row in rows:
            size = _safe_float(_first(row, "size", "shares", "amount", "quantity"))
            price = _safe_float(_first(row, "price", "avgPrice", "avg_price", "lastPrice"))
            writer.writerow(
                {
                    "timestamp": _safe_timestamp(_first(row, "timestamp", "createdAt", "created_at", "time", "date")),
                    "market": _market_name(row),
                    "outcome": _outcome(row),
                    "shares": size,
                    "price": price,
                    "profit_loss": _safe_float(_first(row, "profit_loss", "profitLoss", "realized_pnl", "realizedPnl", "pnl")),
                    "fee": _safe_float(_first(row, "fee", "fees", "maker_fee", "taker_fee")),
                }
            )
    return out_path


def wallet_profile_dict(
    address: str,
    *,
    handle: str | None = None,
    client: PolymarketPublicClient | None = None,
    limit: int = 500,
) -> dict[str, Any]:
    active_client = client or PolymarketPublicClient()
    activity = active_client.fetch_wallet_trades(address, limit=limit)
    try:
        closed_positions = active_client.fetch_closed_positions(address, limit=limit)
    except Exception:
        closed_positions = []
    metrics = _profile_metrics_from_rows(activity, closed_positions)
    profile = {
        "handle": handle or address,
        "wallet": address,
        "platform": "polymarket",
        "source": "public_wallet",
        "category": "prediction_market",
        "verified": True,
        **metrics,
    }
    scored = score_trader(profile_from_dict(profile))
    profile["confidence"] = scored.confidence
    profile["status"] = scored.status
    profile["risk_flags"] = scored.risk_flags
    profile["reason"] = scored.reason
    return profile


def build_wallet_report(
    wallets: list[str],
    *,
    client: PolymarketPublicClient | None = None,
    limit: int = 500,
) -> dict[str, Any]:
    active_client = client or PolymarketPublicClient()
    profiles = [wallet_profile_dict(wallet, client=active_client, limit=limit) for wallet in wallets if wallet]
    return {
        "provider": "polymarket_wallet_tracker",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "mode": "read_only",
        "execution_enabled": False,
        "wallet_count": len(profiles),
        "wallets": profiles,
        "warnings": [
            "Read-only: public Polymarket endpoints only.",
            "No private keys, signatures, approvals, or copy-trading execution are used.",
            "Promote to paper_watch only after verified history passes copy-trader scoring.",
        ],
    }


def write_wallet_report(report: dict[str, Any], path: Path = REPORT_FILE) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    return path


def upsert_wallet_profile(wallet_profile: dict[str, Any], *, profiles_path: Path = DEFAULT_PROFILES_FILE) -> TraderProfile:
    metrics = {
        key: value
        for key, value in wallet_profile.items()
        if key
        in {
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
    }
    return upsert_profile(
        handle=str(wallet_profile.get("handle") or wallet_profile.get("wallet") or ""),
        platform="polymarket",
        source="public_wallet",
        category="prediction_market",
        metrics=metrics,
        profiles_path=profiles_path,
    )


def _load_wallets_from_file(path: Path) -> list[str]:
    data = json.loads(path.read_text(encoding="utf-8-sig"))
    if isinstance(data, list):
        return [str(item.get("wallet") or item.get("address") or item) for item in data]
    if isinstance(data, dict):
        wallets = data.get("wallets", [])
        if isinstance(wallets, list):
            return [str(item.get("wallet") or item.get("address") or item) for item in wallets]
    return []


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Fetch public Polymarket wallet history and score copy-trader profiles.")
    parser.add_argument("--wallet", "--address", action="append", dest="wallets", default=[], help="Public Polymarket wallet address.")
    parser.add_argument("--wallets-file", type=Path, help="JSON list of wallet addresses or objects with wallet/address fields.")
    parser.add_argument("--limit", type=int, default=500, help="Max rows per public endpoint.")
    parser.add_argument("--out", type=Path, default=REPORT_FILE, help="JSON report output path.")
    parser.add_argument("--csv-out", type=Path, help="Optional CSV output path when exactly one wallet is provided.")
    parser.add_argument("--append-profiles", action="store_true", help="Upsert scored wallets into copy-trader-profiles.json.")
    parser.add_argument("--profiles", type=Path, default=DEFAULT_PROFILES_FILE, help="Profiles JSON to update.")
    parser.add_argument("--print", action="store_true", help="Print report JSON.")
    args = parser.parse_args(argv)

    wallets = list(args.wallets)
    if args.wallets_file:
        wallets.extend(_load_wallets_from_file(args.wallets_file))
    wallets = [wallet.strip() for wallet in wallets if wallet and wallet.strip()]
    if not wallets:
        parser.error("Provide --wallet 0x... or --wallets-file wallets.json")

    client = PolymarketPublicClient()
    if args.csv_out:
        if len(wallets) != 1:
            parser.error("--csv-out requires exactly one --wallet")
        wallet_to_csv(wallets[0], args.csv_out, limit=args.limit, client=client)

    report = build_wallet_report(wallets, client=client, limit=args.limit)
    write_wallet_report(report, args.out)

    if args.append_profiles:
        for wallet in report["wallets"]:
            upsert_wallet_profile(wallet, profiles_path=args.profiles)

    if args.print:
        print(json.dumps(report, indent=2))
    else:
        print(f"Polymarket wallet report written to: {args.out}")
        if args.append_profiles:
            print(f"Profiles upserted to: {args.profiles}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

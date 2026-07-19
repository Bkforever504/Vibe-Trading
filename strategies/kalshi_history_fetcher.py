#!/usr/bin/env python3
"""Read-only Kalshi fills fetcher for copy-trader scoring.

Pulls the user's own Kalshi fills via RSA auth, normalizes fills to the
trade_history_importer schema, and can upsert a profile into the copy-trader
watchlist. This module never places orders.
"""
from __future__ import annotations

import argparse
import base64
import csv
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urlparse

import requests

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from strategies.copy_trader_watchlist import DEFAULT_PROFILES_FILE, TraderProfile
from strategies.trade_history_importer import NormalisedTrade, derive_all_metrics, upsert_profile

KALSHI_API_BASE = os.getenv("KALSHI_API_BASE", "https://external-api.kalshi.com/trade-api/v2").rstrip("/")
RUNTIME_DIR = Path.home() / ".vibe-trading"
REPORT_DIR = RUNTIME_DIR / "reports"
REPORT_FILE = REPORT_DIR / "kalshi-fills-report.json"


def make_headers(key_id: str, private_key_pem: str, method: str, path: str) -> dict[str, str]:
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import padding

    ts = str(int(time.time() * 1000))
    sign_path = path.split("?")[0]
    msg = (ts + method.upper() + sign_path).encode("utf-8")
    private_key = serialization.load_pem_private_key(private_key_pem.encode("utf-8"), password=None)
    signature = private_key.sign(
        msg,
        padding.PSS(mgf=padding.MGF1(hashes.SHA256()), salt_length=padding.PSS.DIGEST_LENGTH),
        hashes.SHA256(),
    )
    return {
        "KALSHI-ACCESS-KEY": key_id,
        "KALSHI-ACCESS-TIMESTAMP": ts,
        "KALSHI-ACCESS-SIGNATURE": base64.b64encode(signature).decode("utf-8"),
        "Content-Type": "application/json",
    }


def _load_private_key(path: str) -> str:
    return Path(path).read_text(encoding="utf-8")


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None or value == "":
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def _cent_price(value: Any) -> float:
    raw = _safe_float(value)
    return raw / 100.0 if raw > 1 else raw


def _money_from_cents(row: dict[str, Any], *keys: str) -> float:
    for key in keys:
        if key in row and row[key] not in (None, ""):
            return round(_safe_float(row[key]) / 100.0, 6)
    return 0.0


def _date(value: Any) -> str:
    if not value:
        return datetime.now(timezone.utc).strftime("%Y-%m-%d")
    text = str(value)
    return text[:10]


class KalshiHistoryClient:
    def __init__(
        self,
        *,
        key_id: str | None = None,
        private_key_pem: str | None = None,
        base_url: str = KALSHI_API_BASE,
        session: Any | None = None,
        signer: Callable[[str, str, str, str], dict[str, str]] = make_headers,
    ) -> None:
        self.key_id = key_id or os.getenv("KALSHI_API_KEY_ID", "").strip()
        self.private_key_pem = private_key_pem or _load_private_key(os.getenv("KALSHI_PRIVATE_KEY_PATH", "").strip())
        self.base_url = base_url.rstrip("/")
        self.session = session or requests.Session()
        self.signer = signer

    def _headers(self, method: str, path: str) -> dict[str, str]:
        sign_path = urlparse(self.base_url + path).path
        return self.signer(self.key_id, self.private_key_pem, method, sign_path)

    def fetch_fills(self, *, limit: int = 500, cursor: str | None = None) -> list[dict[str, Any]]:
        path = "/portfolio/fills"
        params: dict[str, Any] = {"limit": limit}
        if cursor:
            params["cursor"] = cursor
        response = self.session.get(
            f"{self.base_url}{path}",
            params=params,
            headers=self._headers("GET", path),
            timeout=20,
        )
        response.raise_for_status()
        data = response.json()
        fills = data.get("fills") if isinstance(data, dict) else []
        return [item for item in fills if isinstance(item, dict)] if isinstance(fills, list) else []


def fill_to_trade_row(fill: dict[str, Any]) -> dict[str, Any]:
    ticker = str(fill.get("ticker") or fill.get("market_ticker") or fill.get("market") or "")
    count = abs(_safe_float(fill.get("count_fp") or fill.get("count") or fill.get("contracts") or fill.get("quantity")))
    dollar_price = fill.get("yes_price_dollars") or fill.get("no_price_dollars")
    price = _safe_float(dollar_price) if dollar_price not in (None, "") else _cent_price(fill.get("yes_price") or fill.get("no_price") or fill.get("price"))
    fee = _safe_float(fill.get("fee_cost")) if fill.get("fee_cost") not in (None, "") else _money_from_cents(fill, "fee_cents", "fees_cents")
    return {
        "date": _date(fill.get("created_time") or fill.get("created_at") or fill.get("trade_time")),
        "market": ticker,
        "contract": str(fill.get("side") or fill.get("outcome") or ""),
        "action": str(fill.get("action") or ""),
        "price": round(price, 6),
        "contracts": count,
        "notional": round(count * price, 6),
        "profit_loss": _money_from_cents(fill, "realized_pnl_cents", "profit_loss_cents", "pnl_cents"),
        "fee": round(fee, 6),
    }


def fills_to_csv(fills: list[dict[str, Any]], out_path: Path) -> Path:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = ["date", "market", "contract", "action", "price", "contracts", "notional", "profit_loss", "fee"]
    with out_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for fill in fills:
            writer.writerow(fill_to_trade_row(fill))
    return out_path


def _fills_to_normalised(fills: list[dict[str, Any]]) -> list[NormalisedTrade]:
    rows = [fill_to_trade_row(fill) for fill in fills]
    return [
        NormalisedTrade(
            date=str(row["date"]),
            symbol=str(row["market"]),
            pnl=_safe_float(row["profit_loss"]),
            fee=_safe_float(row["fee"]),
            notional=_safe_float(row["notional"]),
        )
        for row in rows
    ]


def build_fills_report(fills: list[dict[str, Any]], *, handle: str = "kalshi_self") -> dict[str, Any]:
    metrics = derive_all_metrics(_fills_to_normalised(fills))
    return {
        "provider": "kalshi_history_fetcher",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "mode": "read_only",
        "execution_enabled": False,
        "handle": handle,
        "platform": "kalshi",
        "source": "exported_history",
        "category": "prediction_market",
        **metrics,
        "warnings": [
            "Read-only: fetches your own Kalshi fill history only.",
            "No Kalshi order placement is implemented in this fetcher.",
        ],
    }


def write_report(report: dict[str, Any], path: Path = REPORT_FILE) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    return path


def upsert_kalshi_profile(report: dict[str, Any], *, profiles_path: Path = DEFAULT_PROFILES_FILE) -> TraderProfile:
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
    return upsert_profile(
        handle=str(report.get("handle") or "kalshi_self"),
        platform="kalshi",
        source="exported_history",
        category="prediction_market",
        metrics=metrics,
        profiles_path=profiles_path,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Fetch Kalshi fills and update copy-trader scoring.")
    parser.add_argument("--handle", default="kalshi_self")
    parser.add_argument("--limit", type=int, default=500)
    parser.add_argument("--csv-out", type=Path)
    parser.add_argument("--out", type=Path, default=REPORT_FILE)
    parser.add_argument("--append-profiles", action="store_true")
    parser.add_argument("--profiles", type=Path, default=DEFAULT_PROFILES_FILE)
    parser.add_argument("--print", action="store_true")
    args = parser.parse_args(argv)

    client = KalshiHistoryClient()
    fills = client.fetch_fills(limit=args.limit)
    if args.csv_out:
        fills_to_csv(fills, args.csv_out)
    report = build_fills_report(fills, handle=args.handle)
    write_report(report, args.out)
    if args.append_profiles:
        upsert_kalshi_profile(report, profiles_path=args.profiles)
    if args.print:
        print(json.dumps(report, indent=2))
    else:
        print(f"Kalshi fills report written to: {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Trade history importer for copy-trader watchlist.

Reads CSV or JSON trade exports from Polymarket, Kalshi, or generic brokers,
computes all diligence metrics, and upserts the resulting TraderProfile into
copy-trader-profiles.json.

Usage:
  python trade_history_importer.py --file trades.csv --handle "wallet_addr" --platform polymarket
  python trade_history_importer.py --file kalshi_history.csv --handle "my_kalshi" --platform kalshi
  python trade_history_importer.py --file trades.json --handle "whale_xyz" --platform generic

Read-only output: only writes to copy-trader-profiles.json.
No orders, no keys, no live execution.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import sys
from collections import defaultdict
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from strategies.copy_trader_watchlist import (
    DEFAULT_PROFILES_FILE,
    TraderProfile,
    profile_from_dict,
)

# ---------------------------------------------------------------------------
# Normalised trade record
# ---------------------------------------------------------------------------

class NormalisedTrade:
    """One settled trade reduced to the fields we need for metric derivation."""
    __slots__ = ("date", "symbol", "pnl", "fee", "notional")

    def __init__(self, date: str, symbol: str, pnl: float, fee: float, notional: float):
        self.date = date          # YYYY-MM-DD
        self.symbol = symbol
        self.pnl = pnl            # net P&L after fees
        self.fee = fee
        self.notional = notional  # gross trade size


# ---------------------------------------------------------------------------
# Format detection helpers
# ---------------------------------------------------------------------------

def _col(row: dict, *candidates: str, default: str = "") -> str:
    """Return first matching column value (case-insensitive)."""
    lower = {k.lower(): v for k, v in row.items()}
    for c in candidates:
        v = lower.get(c.lower())
        if v is not None and v != "":
            return str(v)
    return default


def _float(val: str, default: float = 0.0) -> float:
    try:
        return float(str(val).replace(",", "").replace("$", "").replace("%", ""))
    except (ValueError, TypeError):
        return default


def _parse_date(val: str) -> str:
    """Coerce various datetime strings to YYYY-MM-DD."""
    for fmt in ("%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%dT%H:%M:%S",
                "%Y-%m-%d %H:%M:%S", "%Y-%m-%d", "%m/%d/%Y", "%d/%m/%Y"):
        try:
            return datetime.strptime(val[:19], fmt[:len(val[:19])]).strftime("%Y-%m-%d")
        except ValueError:
            continue
    return val[:10]  # best-effort


# ---------------------------------------------------------------------------
# Format parsers
# ---------------------------------------------------------------------------

def _detect_format(headers: list[str]) -> str:
    lower = {h.lower() for h in headers}
    if "profit_loss" in lower or "profit/loss" in lower:
        if "outcome" in lower or "shares" in lower:
            return "polymarket"
        return "kalshi"
    return "generic"


def _parse_polymarket_row(row: dict) -> NormalisedTrade | None:
    pnl = _float(_col(row, "profit_loss", "pnl", "net_pnl"))
    fee = _float(_col(row, "fee", "fees", "maker_fee"))
    notional = _float(_col(row, "notional", "amount", "shares"))
    raw_date = _col(row, "timestamp", "date", "created_at", "time")
    if not raw_date:
        return None
    return NormalisedTrade(
        date=_parse_date(raw_date),
        symbol=_col(row, "market", "symbol", "contract", "outcome"),
        pnl=pnl,
        fee=fee,
        notional=notional,
    )


def _parse_kalshi_row(row: dict) -> NormalisedTrade | None:
    pnl = _float(_col(row, "profit/loss", "profit_loss", "pnl", "realized"))
    fee = _float(_col(row, "fee", "fees"))
    notional = _float(_col(row, "notional", "contracts", "amount", "size"))
    raw_date = _col(row, "date", "Date", "timestamp", "created_at")
    if not raw_date:
        return None
    return NormalisedTrade(
        date=_parse_date(raw_date),
        symbol=_col(row, "market", "Market", "contract", "Contract", "symbol"),
        pnl=pnl,
        fee=fee,
        notional=notional,
    )


def _parse_generic_row(row: dict) -> NormalisedTrade | None:
    pnl = _float(_col(row, "pnl", "profit_loss", "profit/loss", "net_pnl",
                       "realized_pnl", "return", "gain_loss"))
    fee = _float(_col(row, "fee", "fees", "commission"))
    notional = _float(_col(row, "notional", "amount", "size", "value",
                            "contracts", "shares", "qty"))
    raw_date = _col(row, "date", "Date", "timestamp", "time", "created_at",
                    "trade_date", "settlement_date")
    if not raw_date:
        return None
    return NormalisedTrade(
        date=_parse_date(raw_date),
        symbol=_col(row, "symbol", "market", "contract", "ticker", "instrument"),
        pnl=pnl,
        fee=fee,
        notional=notional,
    )


# ---------------------------------------------------------------------------
# CSV / JSON loader
# ---------------------------------------------------------------------------

def load_trades(path: Path) -> list[NormalisedTrade]:
    suffix = path.suffix.lower()
    if suffix == ".json":
        rows = json.loads(path.read_text(encoding="utf-8-sig"))
        if not isinstance(rows, list):
            raise ValueError("JSON file must be an array of trade objects")
        fmt = _detect_format(list(rows[0].keys()) if rows else [])
    elif suffix == ".csv":
        import csv
        with path.open(encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            rows = list(reader)
        fmt = _detect_format(list(rows[0].keys()) if rows else [])
    else:
        raise ValueError(f"Unsupported file type: {suffix}. Use .csv or .json")

    parsers = {
        "polymarket": _parse_polymarket_row,
        "kalshi":     _parse_kalshi_row,
        "generic":    _parse_generic_row,
    }
    parser = parsers[fmt]
    trades = [t for row in rows if (t := parser(row)) is not None]
    return trades


# ---------------------------------------------------------------------------
# Metric derivation
# ---------------------------------------------------------------------------

def _equity_curve(trades: list[NormalisedTrade]) -> list[float]:
    """Cumulative PnL sorted by date."""
    sorted_trades = sorted(trades, key=lambda t: t.date)
    cumulative = 0.0
    curve = [0.0]
    for t in sorted_trades:
        cumulative += t.pnl
        curve.append(cumulative)
    return curve


def _pearson_r(xs: list[float], ys: list[float]) -> float:
    n = len(xs)
    if n < 2:
        return 0.0
    mx = sum(xs) / n
    my = sum(ys) / n
    num = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    sx = math.sqrt(sum((x - mx) ** 2 for x in xs))
    sy = math.sqrt(sum((y - my) ** 2 for y in ys))
    if sx == 0 or sy == 0:
        return 0.0
    return num / (sx * sy)


def compute_pnl_smoothness(trades: list[NormalisedTrade]) -> float:
    """Pearson R of equity curve vs perfect linear growth. 0-1 scale."""
    curve = _equity_curve(trades)
    if len(curve) < 3:
        return 0.0
    n = len(curve)
    linear = [i / (n - 1) * curve[-1] for i in range(n)]
    r = _pearson_r(curve, linear)
    return round(max(0.0, r), 4)


def _monthly_pnl(trades: list[NormalisedTrade]) -> dict[str, float]:
    monthly: dict[str, float] = defaultdict(float)
    for t in trades:
        month = t.date[:7]  # YYYY-MM
        monthly[month] += t.pnl
    return dict(monthly)


def compute_green_months(trades: list[NormalisedTrade]) -> int:
    return sum(1 for v in _monthly_pnl(trades).values() if v > 0)


def compute_monthly_consistency(trades: list[NormalisedTrade]) -> float:
    monthly = _monthly_pnl(trades)
    if not monthly:
        return 0.0
    green = sum(1 for v in monthly.values() if v > 0)
    return round(green / len(monthly), 4)


def compute_worst_month_pct(trades: list[NormalisedTrade]) -> float:
    """Worst month PnL as fraction of total gross notional (negative = loss)."""
    monthly = _monthly_pnl(trades)
    if not monthly:
        return 0.0
    total_notional = sum(abs(t.notional) for t in trades) or 1.0
    worst = min(monthly.values())
    return round(worst / total_notional, 4)


def compute_avg_edge_per_trade(trades: list[NormalisedTrade]) -> float:
    """Mean PnL per trade normalised by average notional."""
    if not trades:
        return 0.0
    avg_notional = sum(abs(t.notional) for t in trades) / len(trades) or 1.0
    avg_pnl = sum(t.pnl for t in trades) / len(trades)
    return round(avg_pnl / avg_notional, 6)


def compute_fee_adjusted_return(trades: list[NormalisedTrade]) -> float:
    """Total net PnL / total gross notional."""
    total_notional = sum(abs(t.notional) for t in trades)
    if total_notional == 0:
        return 0.0
    total_pnl = sum(t.pnl for t in trades)
    return round(total_pnl / total_notional, 6)


def compute_trade_frequency(trades: list[NormalisedTrade]) -> str:
    """Avg trades/month → selective / moderate / hyperactive."""
    monthly = _monthly_pnl(trades)
    if not monthly:
        return "unknown"
    avg_per_month = len(trades) / len(monthly)
    if avg_per_month < 10:
        return "selective"
    if avg_per_month <= 30:
        return "moderate"
    return "hyperactive"


def compute_max_drawdown(trades: list[NormalisedTrade]) -> float:
    """Max peak-to-trough drawdown as fraction of peak equity."""
    curve = _equity_curve(trades)
    peak = curve[0]
    max_dd = 0.0
    for v in curve:
        if v > peak:
            peak = v
        if peak > 0:
            dd = (peak - v) / peak
            max_dd = max(max_dd, dd)
    return round(max_dd, 4)


def compute_profit_factor(trades: list[NormalisedTrade]) -> float:
    gross_win  = sum(t.pnl for t in trades if t.pnl > 0)
    gross_loss = sum(abs(t.pnl) for t in trades if t.pnl < 0)
    if gross_loss == 0:
        return round(gross_win, 4) if gross_win > 0 else 0.0
    return round(gross_win / gross_loss, 4)


def derive_all_metrics(trades: list[NormalisedTrade]) -> dict[str, Any]:
    if not trades:
        return {}
    wins = [t for t in trades if t.pnl > 0]
    return {
        "trades":              len(trades),
        "win_rate":            round(len(wins) / len(trades), 4),
        "realized_pnl":        round(sum(t.pnl for t in trades), 4),
        "max_drawdown_pct":    compute_max_drawdown(trades),
        "profit_factor":       compute_profit_factor(trades),
        "pnl_smoothness":      compute_pnl_smoothness(trades),
        "green_months":        compute_green_months(trades),
        "monthly_consistency": compute_monthly_consistency(trades),
        "worst_month_pct":     compute_worst_month_pct(trades),
        "avg_edge_per_trade":  compute_avg_edge_per_trade(trades),
        "fee_adjusted_return": compute_fee_adjusted_return(trades),
        "trade_frequency":     compute_trade_frequency(trades),
    }


# ---------------------------------------------------------------------------
# Profiles upsert
# ---------------------------------------------------------------------------

def upsert_profile(
    handle: str,
    platform: str,
    source: str,
    category: str,
    metrics: dict[str, Any],
    profiles_path: Path = DEFAULT_PROFILES_FILE,
) -> TraderProfile:
    profiles_path.parent.mkdir(parents=True, exist_ok=True)
    existing: list[dict] = []
    if profiles_path.exists():
        try:
            existing = json.loads(profiles_path.read_text(encoding="utf-8-sig"))
            if not isinstance(existing, list):
                existing = []
        except json.JSONDecodeError:
            existing = []

    entry: dict[str, Any] = {
        "handle":   handle,
        "platform": platform,
        "source":   source,
        "category": category,
        "verified": source in {"public_wallet", "exported_history"},
        **metrics,
    }

    # upsert: replace existing record with same handle+platform
    updated = False
    for i, p in enumerate(existing):
        if p.get("handle") == handle and p.get("platform") == platform:
            existing[i] = {**p, **entry}
            updated = True
            break
    if not updated:
        existing.append(entry)

    profiles_path.write_text(json.dumps(existing, indent=2), encoding="utf-8")
    return profile_from_dict(entry)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Import trade history → copy-trader profile")
    parser.add_argument("--file",     required=True, help="CSV or JSON trade export file")
    parser.add_argument("--handle",   required=True, help="Wallet address or username")
    parser.add_argument("--platform", required=True,
                        help="Platform: polymarket | kalshi | generic | solana | …")
    parser.add_argument("--category", default="general",
                        help="Category: prediction_market | weather | crypto_wallet | …")
    parser.add_argument("--source",   default="exported_history",
                        help="Source: exported_history | public_wallet | manual")
    parser.add_argument("--profiles", default=str(DEFAULT_PROFILES_FILE),
                        help="Path to copy-trader-profiles.json")
    args = parser.parse_args(argv)

    path = Path(args.file)
    if not path.exists():
        print(f"ERROR: file not found: {path}", file=sys.stderr)
        sys.exit(1)

    print(f"Loading trades from {path} ...")
    trades = load_trades(path)
    if not trades:
        print("ERROR: no parseable trades found in file.", file=sys.stderr)
        sys.exit(1)

    print(f"Parsed {len(trades)} trades. Computing metrics ...")
    metrics = derive_all_metrics(trades)

    for k, v in metrics.items():
        print(f"  {k:25s}: {v}")

    profile = upsert_profile(
        handle=args.handle,
        platform=args.platform,
        source=args.source,
        category=args.category,
        metrics=metrics,
        profiles_path=Path(args.profiles),
    )
    print(f"\nProfile upserted → {args.profiles}")
    print(f"  handle      : {profile.handle}")
    print(f"  platform    : {profile.platform}")
    print(f"  trades      : {profile.trades}")
    print(f"  win_rate    : {profile.win_rate:.1%}")
    print(f"  realized_pnl: ${profile.realized_pnl:,.2f}")
    print(f"  smoothness  : {profile.pnl_smoothness:.2f}")
    print(f"  green_months: {profile.green_months}")
    print(f"  frequency   : {profile.trade_frequency}")
    print("\nRun copy_trader_watchlist.py to regenerate the scored report.")


if __name__ == "__main__":
    main()

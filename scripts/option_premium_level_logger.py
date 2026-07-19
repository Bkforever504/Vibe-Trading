#!/usr/bin/env python3
"""Build read-only option premium-by-strike levels from executed trade prints."""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from collections import defaultdict
from datetime import date, datetime, time, timezone
from pathlib import Path
from typing import Any, Iterable
from zoneinfo import ZoneInfo

import requests
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

load_dotenv(ROOT / "agent" / ".env")

ET = ZoneInfo("America/New_York")
DATA_BASE = "https://data.alpaca.markets"
PAPER_TRADING_BASE = "https://paper-api.alpaca.markets"
LIVE_TRADING_BASE = "https://api.alpaca.markets"
REPORT_PATH = Path.home() / ".vibe-trading" / "reports" / "option-premium-levels.json"
LOG_PATH = ROOT / "data" / "option_premium_level_log.jsonl"
OCC_PATTERN = re.compile(r"^([A-Z]{1,6})(\d{6})([CP])(\d{8})$")


def parse_occ_symbol(symbol: str) -> dict[str, Any] | None:
    match = OCC_PATTERN.fullmatch(str(symbol or "").upper())
    if not match:
        return None
    underlying, expiry_text, right, strike_text = match.groups()
    try:
        expiry = datetime.strptime(expiry_text, "%y%m%d").date()
        strike = int(strike_text) / 1000.0
    except (ValueError, OverflowError):
        return None
    return {
        "underlying": underlying,
        "expiry": expiry.isoformat(),
        "right": "CALL" if right == "C" else "PUT",
        "strike": strike,
    }


def _trade_value(trade: dict[str, Any]) -> tuple[float, int] | None:
    try:
        price = float(trade.get("p") if trade.get("p") is not None else trade.get("price"))
        size = int(trade.get("s") if trade.get("s") is not None else trade.get("size"))
    except (TypeError, ValueError):
        return None
    if price <= 0 or size <= 0:
        return None
    return price, size


def aggregate_premium_levels(
    trades_by_contract: dict[str, Iterable[dict[str, Any]]],
    *,
    top_n: int = 4,
) -> dict[str, list[dict[str, Any]]]:
    """Rank call and put strikes by executed premium dollars (price * size * 100)."""
    grouped: dict[tuple[str, str, float], dict[str, Any]] = {}
    for option_symbol, trades in trades_by_contract.items():
        parsed = parse_occ_symbol(option_symbol)
        if not parsed:
            continue
        key = (parsed["underlying"], parsed["right"], parsed["strike"])
        level = grouped.setdefault(
            key,
            {
                **parsed,
                "total_premium_dollars": 0.0,
                "contracts_traded": 0,
                "trade_count": 0,
                "premium_price_size_sum": 0.0,
                "first_trade_at": None,
                "last_trade_at": None,
                "condition_codes": set(),
                "option_symbols": set(),
            },
        )
        for trade in trades or []:
            value = _trade_value(trade)
            if value is None:
                continue
            price, size = value
            premium = price * size * 100.0
            level["total_premium_dollars"] += premium
            level["premium_price_size_sum"] += price * size
            level["contracts_traded"] += size
            level["trade_count"] += 1
            level["option_symbols"].add(option_symbol)
            timestamp = trade.get("t") or trade.get("timestamp")
            if timestamp:
                timestamp = str(timestamp)
                if level["first_trade_at"] is None or timestamp < level["first_trade_at"]:
                    level["first_trade_at"] = timestamp
                if level["last_trade_at"] is None or timestamp > level["last_trade_at"]:
                    level["last_trade_at"] = timestamp
            for code in trade.get("c") or trade.get("conditions") or []:
                level["condition_codes"].add(str(code))

    output = {"CALL": [], "PUT": []}
    for level in grouped.values():
        if level["trade_count"] <= 0:
            continue
        contracts = int(level["contracts_traded"])
        row = {
            "underlying": level["underlying"],
            "expiry": level["expiry"],
            "right": level["right"],
            "underlying_level": level["strike"],
            "total_premium_dollars": round(level["total_premium_dollars"], 2),
            "contracts_traded": contracts,
            "trade_count": int(level["trade_count"]),
            "vwap_option_price": round(level["premium_price_size_sum"] / contracts, 4),
            "first_trade_at": level["first_trade_at"],
            "last_trade_at": level["last_trade_at"],
            "condition_codes": sorted(level["condition_codes"]),
            "option_symbols": sorted(level["option_symbols"]),
        }
        output[level["right"]].append(row)
    for right in output:
        output[right] = sorted(
            output[right],
            key=lambda row: (-row["total_premium_dollars"], row["underlying_level"]),
        )[:max(1, top_n)]
    return output


def _headers() -> dict[str, str]:
    return {
        "APCA-API-KEY-ID": os.getenv("ALPACA_API_KEY", ""),
        "APCA-API-SECRET-KEY": os.getenv("ALPACA_SECRET_KEY", ""),
    }


def _get_json(session: requests.Session, url: str, *, params: dict[str, Any]) -> dict[str, Any]:
    response = session.get(url, headers=_headers(), params=params, timeout=20)
    response.raise_for_status()
    payload = response.json()
    return payload if isinstance(payload, dict) else {}


def fetch_spot(session: requests.Session, symbol: str) -> float | None:
    payload = _get_json(
        session,
        f"{DATA_BASE}/v2/stocks/trades/latest",
        params={"symbols": symbol, "feed": "iex"},
    )
    trade = (payload.get("trades") or {}).get(symbol) or {}
    try:
        price = float(trade.get("p") or 0.0)
    except (TypeError, ValueError):
        return None
    return price if price > 0 else None


def discover_near_money_contracts(
    session: requests.Session,
    symbol: str,
    expiry: date,
    spot: float,
    *,
    max_contracts: int = 16,
    strike_band_pct: float = 0.03,
) -> list[str]:
    trading_base = PAPER_TRADING_BASE if os.getenv("ALPACA_PAPER", "true").lower() == "true" else LIVE_TRADING_BASE
    params: dict[str, Any] = {
        "underlying_symbols": symbol,
        "expiration_date": expiry.isoformat(),
        "status": "active",
        "strike_price_gte": f"{spot * (1.0 - strike_band_pct):.3f}",
        "strike_price_lte": f"{spot * (1.0 + strike_band_pct):.3f}",
        "limit": 1000,
    }
    contracts: list[tuple[float, str, str]] = []
    for _ in range(10):
        payload = _get_json(session, f"{trading_base}/v2/options/contracts", params=params)
        for row in payload.get("option_contracts") or []:
            option_symbol = str(row.get("symbol") or "")
            parsed = parse_occ_symbol(option_symbol)
            if not parsed or parsed["underlying"] != symbol or parsed["expiry"] != expiry.isoformat():
                continue
            contracts.append((abs(float(parsed["strike"]) - spot), parsed["right"], option_symbol))
        token = payload.get("next_page_token")
        if not token:
            break
        params["page_token"] = token
    per_side = max(1, max_contracts // 2)
    selected: list[str] = []
    for right in ("CALL", "PUT"):
        selected.extend(symbol_text for _, _, symbol_text in sorted(row for row in contracts if row[1] == right)[:per_side])
    return selected[:max_contracts]


def fetch_option_trades(
    session: requests.Session,
    option_symbols: list[str],
    start: datetime,
    end: datetime,
    *,
    max_pages_per_contract: int = 12,
) -> tuple[dict[str, list[dict[str, Any]]], list[str]]:
    """Fetch each contract independently so API symbol ordering cannot starve one side."""
    trades: dict[str, list[dict[str, Any]]] = defaultdict(list)
    truncated: list[str] = []
    for option_symbol in option_symbols:
        params: dict[str, Any] = {
            "symbols": option_symbol,
            "start": start.astimezone(timezone.utc).isoformat().replace("+00:00", "Z"),
            "end": end.astimezone(timezone.utc).isoformat().replace("+00:00", "Z"),
            "limit": 10000,
            "sort": "asc",
        }
        next_token = None
        for _ in range(max_pages_per_contract):
            payload = _get_json(session, f"{DATA_BASE}/v1beta1/options/trades", params=params)
            for symbol, rows in (payload.get("trades") or {}).items():
                if isinstance(rows, list):
                    trades[symbol].extend(row for row in rows if isinstance(row, dict))
            next_token = payload.get("next_page_token")
            if not next_token:
                break
            params["page_token"] = next_token
        if next_token:
            truncated.append(option_symbol)
    return dict(trades), truncated


def build_report(
    symbols: list[str],
    *,
    trading_day: date | None = None,
    top_n: int = 4,
    session: requests.Session | None = None,
) -> dict[str, Any]:
    trading_day = trading_day or datetime.now(ET).date()
    now_et = datetime.now(ET)
    start = datetime.combine(trading_day, time(9, 30), tzinfo=ET)
    end = min(now_et, datetime.combine(trading_day, time(16, 0), tzinfo=ET))
    configured_feed = os.getenv("OPTION_PREMIUM_DATA_FEED", "account_default_unverified").strip().lower()
    report: dict[str, Any] = {
        "provider": "option_premium_level_logger",
        "mode": "read_only_research",
        "execution_enabled": False,
        "can_submit_orders": False,
        "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "date": trading_day.isoformat(),
        "window": {"start": start.isoformat(), "end": end.isoformat()},
        "aggregation": "executed_option_price_x_contract_size_x_100_grouped_by_strike",
        "top_n_per_right": top_n,
        "feed_provenance": configured_feed,
        "provenance_qualified": configured_feed == "opra",
        "symbols": {},
        "warnings": [
            "Read-only research; no order path is present.",
            "Aggressor side is not inferred because contemporaneous quote classification is unavailable.",
            "Indicative option trades are delayed/derived and cannot qualify a live execution level.",
            "Condition codes are retained for review but not silently filtered.",
        ],
    }
    if not _headers()["APCA-API-KEY-ID"] or not _headers()["APCA-API-SECRET-KEY"]:
        report["status"] = "credentials_missing"
        return report
    if end <= start:
        report["status"] = "market_session_not_started"
        return report
    session = session or requests.Session()
    for symbol in symbols:
        symbol = symbol.upper()
        try:
            spot = fetch_spot(session, symbol)
            if spot is None:
                raise ValueError("latest IEX trade unavailable")
            contracts = discover_near_money_contracts(session, symbol, trading_day, spot)
            trade_map, truncated = fetch_option_trades(session, contracts, start, end) if contracts else ({}, [])
            levels = aggregate_premium_levels(trade_map, top_n=top_n)
            report["symbols"][symbol] = {
                "status": "ok",
                "spot": round(spot, 4),
                "expiry": trading_day.isoformat(),
                "contract_count": len(contracts),
                "trade_print_count": sum(len(rows) for rows in trade_map.values()),
                "truncated_contracts": truncated,
                "trade_history_complete": not truncated,
                "levels": levels,
            }
        except Exception as exc:
            report["symbols"][symbol] = {"status": "error", "error": str(exc)[:300]}
    report["status"] = "ok" if any(row.get("status") == "ok" for row in report["symbols"].values()) else "error"
    return report


def write_report(report: dict[str, Any], report_path: Path = REPORT_PATH, log_path: Path = LOG_PATH) -> None:
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(report, separators=(",", ":"), sort_keys=True) + "\n")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--symbols", default=os.getenv("OPTION_PREMIUM_LEVEL_SYMBOLS", "SPY,QQQ,IWM"))
    parser.add_argument("--date", type=date.fromisoformat)
    parser.add_argument("--top", type=int, default=4)
    parser.add_argument("--print", action="store_true", dest="print_report")
    args = parser.parse_args()
    symbols = [symbol.strip().upper() for symbol in args.symbols.split(",") if symbol.strip()]
    report = build_report(symbols, trading_day=args.date, top_n=max(1, min(args.top, 10)))
    write_report(report)
    if args.print_report:
        print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report.get("status") not in {"error", "credentials_missing"} else 1


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""
Read-only trading dashboard for the Alpaca paper bot.

This creates a static HTML report similar to the analytics view Kenny shared:
P&L, win rate, profit factor, open positions, recent account equity, and a
practical confidence score. It never submits orders.

Usage:
    python strategies/trading_dashboard.py
    python strategies/trading_dashboard.py --days 30
    python strategies/trading_dashboard.py --open
"""
from __future__ import annotations

import argparse
import html
import json
import os
import sys
import webbrowser
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import requests
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
RUNTIME_DIR = Path(os.path.expanduser(r"~\.vibe-trading"))
REPORT_DIR = RUNTIME_DIR / "reports"
REPORT_FILE = REPORT_DIR / "trading-dashboard.html"
OPTIONS_STATE_FILE = RUNTIME_DIR / "options-trades.json"
FLIP_STATE_FILE = RUNTIME_DIR / "flip-trades.json"
TRADINGVIEW_REPORT_FILE = REPORT_DIR / "tradingview-validation.json"
KALSHI_REPORT_FILE = REPORT_DIR / "kalshi-prediction-report.json"
COPY_WATCHLIST_REPORT_FILE = REPORT_DIR / "copy-trader-watchlist.json"
POLYMARKET_WALLET_REPORT_FILE = REPORT_DIR / "polymarket-wallet-tracker.json"
POLYMARKET_FED_WHALE_REPORT_FILE = REPORT_DIR / "polymarket-fed-whale-watch.json"
SOCIAL_ARBITRAGE_REPORT_FILE = REPORT_DIR / "social-arbitrage-watchlist.json"
MOMENTUM_SHADOW_LOG_FILE = ROOT / "data" / "momentum_shadow_log.jsonl"
RSI2_SHADOW_LOG_FILE = ROOT / "data" / "rsi2_shadow_log.jsonl"
KAMA_SHADOW_LOG_FILE = ROOT / "data" / "kama_shadow_log.jsonl"
GUARD_BLOCK_LOG_FILE = RUNTIME_DIR / "guard-blocks.jsonl"
KALSHI_GUARD_BLOCK_LOG_FILE = RUNTIME_DIR / "kalshi-guard-blocks.jsonl"
ALPACA_BLOCK_FILE = RUNTIME_DIR / "MANUAL_RESET_REQUIRED.json"
KALSHI_BLOCK_FILE = RUNTIME_DIR / "KALSHI_MANUAL_RESET_REQUIRED.json"
KALSHI_BOT_ENV = Path(os.path.expanduser(r"~\Desktop\MAILK-Repos\Kalshi-Weather-Bot\.env"))

load_dotenv(dotenv_path=ROOT / "agent" / ".env")

KEY = os.getenv("ALPACA_API_KEY", "")
SECRET = os.getenv("ALPACA_SECRET_KEY", "")
PAPER = os.getenv("ALPACA_PAPER", "true").lower() == "true"
BASE = "https://paper-api.alpaca.markets" if PAPER else "https://api.alpaca.markets"
HDR = {"APCA-API-KEY-ID": KEY, "APCA-API-SECRET-KEY": SECRET}


def _get(path: str, params: dict | None = None) -> list | dict:
    resp = requests.get(f"{BASE}{path}", headers=HDR, params=params or {}, timeout=15)
    resp.raise_for_status()
    return resp.json()


def _money(value: float) -> str:
    return f"${value:,.2f}"


def _pct(value: float) -> str:
    return f"{value:.1f}%"


def _safe_float(value: object, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def fetch_account() -> dict:
    return _get("/v2/account")


def fetch_positions() -> list[dict]:
    data = _get("/v2/positions")
    return data if isinstance(data, list) else []


def fetch_orders(days: int) -> list[dict]:
    since = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    data = _get(
        "/v2/orders",
        {"status": "closed", "after": since, "limit": 500, "direction": "asc", "nested": "true"},
    )
    return [o for o in data if isinstance(o, dict) and o.get("filled_at")] if isinstance(data, list) else []


def fetch_portfolio_history(days: int) -> dict:
    period = f"{max(1, min(days, 365))}D"
    data = _get("/v2/account/portfolio/history", {"period": period, "timeframe": "1D"})
    return data if isinstance(data, dict) else {}


def leg_cashflow(order: dict) -> float:
    qty = _safe_float(order.get("filled_qty") or order.get("qty"))
    price = _safe_float(order.get("filled_avg_price") or order.get("limit_price"))
    multiplier = 100 if str(order.get("asset_class", "us_option")) == "us_option" else 1
    cashflow = qty * price * multiplier
    return cashflow if order.get("side") == "sell" else -cashflow


def net_order_event(order: dict) -> dict:
    legs = order.get("legs") or []
    filled_at = order.get("filled_at", "")
    day = filled_at[:10] if filled_at else "unknown"

    if legs:
        symbols = [leg.get("symbol", "") for leg in legs if leg.get("symbol")]
        cashflow = sum(leg_cashflow(leg) for leg in legs)
        return {
            "day": day,
            "symbol": " / ".join(symbols),
            "strategy": "multi-leg",
            "cashflow": cashflow,
            "filled_at": filled_at,
        }

    return {
        "day": day,
        "symbol": order.get("symbol", ""),
        "strategy": order.get("side", "single-leg"),
        "cashflow": leg_cashflow(order),
        "filled_at": filled_at,
    }


def load_json(path: Path, fallback):
    if not path.exists():
        return fallback
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return fallback


def flip_closed_trades() -> list[dict]:
    trades = load_json(FLIP_STATE_FILE, [])
    if not isinstance(trades, list):
        return []
    return [t for t in trades if t.get("status") == "closed"]


def options_state() -> dict:
    state = load_json(OPTIONS_STATE_FILE, {})
    return state if isinstance(state, dict) else {}


def tradingview_context(path: Path = TRADINGVIEW_REPORT_FILE) -> dict:
    report = load_json(path, {})
    if not isinstance(report, dict) or not report:
        return {
            "available": False,
            "connected": False,
            "symbol": "",
            "timeframe": "",
            "description": "",
            "is_delayed": False,
            "bias": "unknown",
            "last": 0.0,
            "change": 0.0,
            "change_pct": "",
            "bar_count": 0,
            "warnings": ["TradingView validation report has not been generated yet."],
        }

    quote = report.get("quote") if isinstance(report.get("quote"), dict) else {}
    ohlcv = report.get("ohlcv_summary") if isinstance(report.get("ohlcv_summary"), dict) else {}
    warnings = report.get("warnings") if isinstance(report.get("warnings"), list) else []
    return {
        "available": True,
        "connected": bool(report.get("connected")),
        "symbol": str(report.get("symbol") or quote.get("symbol") or ""),
        "timeframe": str(report.get("timeframe") or ""),
        "description": str(report.get("description") or quote.get("description") or ""),
        "is_delayed": bool(report.get("is_delayed")),
        "bias": str(report.get("bias") or "unknown"),
        "last": _safe_float(quote.get("last") if quote.get("last") is not None else quote.get("close")),
        "change": _safe_float(ohlcv.get("change")),
        "change_pct": str(ohlcv.get("change_pct") or ""),
        "bar_count": int(_safe_float(ohlcv.get("bar_count"))),
        "warnings": [str(item) for item in warnings],
    }


def kalshi_context(path: Path = KALSHI_REPORT_FILE) -> dict:
    report = load_json(path, {})
    if not isinstance(report, dict) or not report:
        return {
            "available": False,
            "mode": "paper_only",
            "execution_enabled": False,
            "markets_scanned": 0,
            "top_opportunities": [],
            "warnings": ["Kalshi prediction report has not been generated yet."],
        }

    opportunities = report.get("opportunities") if isinstance(report.get("opportunities"), list) else []
    warnings = report.get("warnings") if isinstance(report.get("warnings"), list) else []
    return {
        "available": True,
        "mode": str(report.get("mode") or "paper_only"),
        "execution_enabled": bool(report.get("execution_enabled")),
        "markets_scanned": int(_safe_float(report.get("markets_scanned"))),
        "top_opportunities": [item for item in opportunities if isinstance(item, dict)][:5],
        "warnings": [str(item) for item in warnings],
    }


def copy_watchlist_context(path: Path = COPY_WATCHLIST_REPORT_FILE) -> dict:
    report = load_json(path, {})
    if not isinstance(report, dict) or not report:
        return {
            "available": False,
            "mode": "paper_only",
            "execution_enabled": False,
            "watched_count": 0,
            "top_traders": [],
            "warnings": ["Copy trader watchlist report has not been generated yet."],
        }

    traders = report.get("watched_traders") if isinstance(report.get("watched_traders"), list) else []
    warnings = report.get("warnings") if isinstance(report.get("warnings"), list) else []
    return {
        "available": True,
        "mode": str(report.get("mode") or "paper_only"),
        "execution_enabled": bool(report.get("execution_enabled")),
        "watched_count": int(_safe_float(report.get("watched_count"))),
        "paper_signal_count": int(_safe_float(report.get("paper_signal_count"))),
        "paper_signals": [item for item in report.get("paper_signals", []) if isinstance(item, dict)][:5]
        if isinstance(report.get("paper_signals"), list)
        else [],
        "top_traders": [item for item in traders if isinstance(item, dict)][:5],
        "warnings": [str(item) for item in warnings],
    }


def guard_blocks_context(path: Path = GUARD_BLOCK_LOG_FILE, limit: int = 20) -> dict:
    if not path.exists():
        return {"available": False, "blocks": [], "total": 0}
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
        entries = []
        for line in lines:
            line = line.strip()
            if not line:
                continue
            try:
                entries.append(json.loads(line))
            except Exception:
                continue
        recent = entries[-limit:][::-1]
        return {"available": True, "blocks": recent, "total": len(entries)}
    except Exception:
        return {"available": False, "blocks": [], "total": 0}


def polymarket_wallet_context(path: Path = POLYMARKET_WALLET_REPORT_FILE) -> dict:
    report = load_json(path, {})
    if not isinstance(report, dict) or not report:
        return {
            "available": False,
            "mode": "read_only",
            "execution_enabled": False,
            "wallet_count": 0,
            "wallets": [],
            "warnings": ["Polymarket wallet tracker report has not been generated yet."],
        }

    wallets = report.get("wallets") if isinstance(report.get("wallets"), list) else []
    warnings = report.get("warnings") if isinstance(report.get("warnings"), list) else []
    return {
        "available": True,
        "mode": str(report.get("mode") or "read_only"),
        "execution_enabled": bool(report.get("execution_enabled")),
        "wallet_count": int(_safe_float(report.get("wallet_count"))),
        "wallets": [item for item in wallets if isinstance(item, dict)][:5],
        "warnings": [str(item) for item in warnings],
    }


def polymarket_fed_whale_context(path: Path = POLYMARKET_FED_WHALE_REPORT_FILE) -> dict:
    report = load_json(path, {})
    if not isinstance(report, dict) or not report:
        return {
            "available": False,
            "mode": "read_only",
            "execution_enabled": False,
            "markets_scanned": 0,
            "whale_trade_count": 0,
            "consensus_count": 0,
            "consensus": [],
            "top_whale_trades": [],
            "warnings": ["Polymarket Fed whale watch report has not been generated yet."],
        }

    warnings = report.get("warnings") if isinstance(report.get("warnings"), list) else []
    consensus = report.get("consensus") if isinstance(report.get("consensus"), list) else []
    trades = report.get("top_whale_trades") if isinstance(report.get("top_whale_trades"), list) else []
    return {
        "available": True,
        "mode": str(report.get("mode") or "read_only"),
        "execution_enabled": bool(report.get("execution_enabled")),
        "markets_scanned": int(_safe_float(report.get("markets_scanned"))),
        "whale_trade_count": int(_safe_float(report.get("whale_trade_count"))),
        "consensus_count": int(_safe_float(report.get("consensus_count"))),
        "consensus": [item for item in consensus if isinstance(item, dict)][:5],
        "top_whale_trades": [item for item in trades if isinstance(item, dict)][:8],
        "warnings": [str(item) for item in warnings],
    }


def social_arbitrage_context(path: Path = SOCIAL_ARBITRAGE_REPORT_FILE) -> dict:
    report = load_json(path, {})
    if not isinstance(report, dict) or not report:
        return {
            "available": False,
            "mode": "research_only",
            "execution_enabled": False,
            "observation_count": 0,
            "idea_count": 0,
            "ideas": [],
            "warnings": ["Social arbitrage watchlist report has not been generated yet."],
        }

    warnings = report.get("warnings") if isinstance(report.get("warnings"), list) else []
    ideas = report.get("ideas") if isinstance(report.get("ideas"), list) else []
    return {
        "available": True,
        "mode": str(report.get("mode") or "research_only"),
        "execution_enabled": bool(report.get("execution_enabled")),
        "observation_count": int(_safe_float(report.get("observation_count"))),
        "idea_count": int(_safe_float(report.get("idea_count"))),
        "ideas": [item for item in ideas if isinstance(item, dict)][:8],
        "warnings": [str(item) for item in warnings],
    }


def _read_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    rows: list[dict] = []
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                item = json.loads(line)
            except Exception:
                continue
            if isinstance(item, dict):
                rows.append(item)
    except Exception:
        return []
    return rows


def _shadow_period_return_pct(previous: dict | None, latest: dict | None) -> float | None:
    if not previous or not latest:
        return None
    weights = previous.get("weights") if isinstance(previous.get("weights"), dict) else {}
    start_prices = previous.get("close_prices") if isinstance(previous.get("close_prices"), dict) else {}
    end_prices = latest.get("close_prices") if isinstance(latest.get("close_prices"), dict) else {}
    if not weights or not start_prices or not end_prices:
        return None

    total = 0.0
    used = 0
    for symbol, raw_weight in weights.items():
        if symbol not in start_prices or symbol not in end_prices:
            continue
        start = _safe_float(start_prices.get(symbol))
        end = _safe_float(end_prices.get(symbol))
        weight = _safe_float(raw_weight)
        if start <= 0:
            continue
        total += weight * ((end / start) - 1)
        used += 1
    return round(total * 100, 3) if used else None


def momentum_shadow_context(path: Path = MOMENTUM_SHADOW_LOG_FILE) -> dict:
    entries = _read_jsonl(path)
    if not entries:
        return {
            "available": False,
            "execution_enabled": False,
            "log_count": 0,
            "latest": {},
            "previous": None,
            "last_period_return_pct": None,
            "warnings": ["Momentum shadow log has not been generated yet."],
        }

    latest = entries[-1]
    previous = entries[-2] if len(entries) >= 2 else None
    warnings = [
        "Shadow-only. No Alpaca orders are wired.",
        "Needs 30-60 days of forward logs before execution review.",
    ]
    if latest.get("in_cash"):
        warnings.append("Cash filter is active: all assets failed positive-momentum selection.")

    return {
        "available": True,
        "execution_enabled": False,
        "log_count": len(entries),
        "latest": latest,
        "previous": previous,
        "last_period_return_pct": _shadow_period_return_pct(previous, latest),
        "warnings": warnings,
    }


def daily_shadow_context(path: Path, title: str) -> dict:
    entries = _read_jsonl(path)
    if not entries:
        return {
            "available": False,
            "title": title,
            "execution_enabled": False,
            "log_count": 0,
            "entry_count": 0,
            "latest": {},
            "min_days": 30,
            "min_entries": 10,
            "warnings": [f"{title} log has not been generated yet."],
        }

    latest = entries[-1]
    rules = latest.get("paper_rules") if isinstance(latest.get("paper_rules"), dict) else {}
    min_days = int(_safe_float(rules.get("minimum_forward_days"), 30))
    min_entries = int(_safe_float(rules.get("minimum_signals_before_review"), 10))
    entry_count = sum(
        1 for row in entries
        if isinstance(row.get("primary_setup"), dict)
        and row["primary_setup"].get("action") == "enter_long"
    )
    warnings = [
        "Shadow-only. No broker orders are wired.",
        f"Requires {min_days} log days and {min_entries} entry signals before execution review.",
    ]
    return {
        "available": True,
        "title": title,
        "execution_enabled": False,
        "log_count": len(entries),
        "entry_count": entry_count,
        "latest": latest,
        "min_days": min_days,
        "min_entries": min_entries,
        "warnings": warnings,
    }


def portfolio_points(history: dict) -> list[tuple[str, float]]:
    timestamps = history.get("timestamp") or []
    equity = history.get("equity") or []
    points: list[tuple[str, float]] = []
    for ts, val in zip(timestamps, equity):
        try:
            label = datetime.fromtimestamp(int(ts), tz=timezone.utc).strftime("%m/%d")
            points.append((label, float(val)))
        except Exception:
            continue
    return points


def performance_summary(events: list[dict], flips: list[dict]) -> dict:
    closed_pnls = [_safe_float(t.get("pnl")) for t in flips if "pnl" in t]
    wins = [p for p in closed_pnls if p > 0]
    losses = [p for p in closed_pnls if p < 0]
    gross_profit = sum(wins)
    gross_loss = abs(sum(losses))
    profit_factor = gross_profit / gross_loss if gross_loss else (float("inf") if gross_profit else 0.0)
    total_closed = len(closed_pnls)

    daily_cashflow: dict[str, float] = defaultdict(float)
    for event in events:
        daily_cashflow[event["day"]] += _safe_float(event.get("cashflow"))
    for trade in flips:
        day = str(trade.get("exit_date") or "unknown")
        daily_cashflow[day] += _safe_float(trade.get("pnl"))

    return {
        "closed_trade_pnls": closed_pnls,
        "wins": len(wins),
        "losses": len(losses),
        "win_rate": (len(wins) / total_closed * 100) if total_closed else 0.0,
        "profit_factor": profit_factor,
        "avg_win": (gross_profit / len(wins)) if wins else 0.0,
        "avg_loss": (sum(losses) / len(losses)) if losses else 0.0,
        "total_closed": total_closed,
        "net_realized": sum(closed_pnls),
        "order_cashflow": sum(_safe_float(e.get("cashflow")) for e in events),
        "daily_cashflow": dict(sorted(daily_cashflow.items())),
    }


def confidence_score(account: dict, positions: list[dict], summary: dict, paper: bool) -> tuple[int, list[str]]:
    score = 0
    notes: list[str] = []

    if paper:
        score += 15
        notes.append("Paper mode is on, so testing can continue without real-money execution risk.")
    else:
        notes.append("Live mode is on. Require manual approval and tighter size limits before automation.")

    if KEY and SECRET:
        score += 10
    else:
        notes.append("Alpaca credentials are missing.")

    closed = int(summary["total_closed"])
    if closed >= 50:
        score += 25
    elif closed >= 20:
        score += 15
        notes.append("Trade sample is still small; aim for 50+ closed trades before scaling.")
    else:
        score += 5
        notes.append("Not enough closed trades yet to trust win rate or profit factor.")

    pf = summary["profit_factor"]
    if pf >= 1.5:
        score += 20
    elif pf >= 1.2:
        score += 12
        notes.append("Profit factor is positive but needs a larger sample.")
    else:
        notes.append("Profit factor is not proven yet.")

    if len(positions) <= 4:
        score += 10
    else:
        notes.append("Open position count is elevated; watch concentration risk.")

    equity = _safe_float(account.get("equity"))
    last_equity = _safe_float(account.get("last_equity"))
    daily_pl = equity - last_equity if equity and last_equity else 0.0
    daily_dd = abs(daily_pl) / last_equity * 100 if daily_pl < 0 and last_equity else 0.0
    if daily_dd <= 1.0:
        score += 10
    else:
        notes.append("Daily drawdown is above 1%; prop-firm sizing would need to be smaller.")

    if (ROOT / "strategies" / "iwm_options_bot.py").exists():
        score += 10

    return min(score, 100), notes


def bars(points: list[tuple[str, float]]) -> str:
    if not points:
        return '<div class="empty">No portfolio history returned.</div>'
    vals = [p[1] for p in points]
    lo, hi = min(vals), max(vals)
    span = max(hi - lo, 1)
    items = []
    for label, val in points[-30:]:
        height = 18 + ((val - lo) / span * 82)
        items.append(
            f'<div class="bar" style="height:{height:.1f}%"><span>{html.escape(label)}</span><b>{_money(val)}</b></div>'
        )
    return "".join(items)


def daily_rows(summary: dict) -> str:
    rows = []
    for day, pnl in summary["daily_cashflow"].items():
        cls = "good" if pnl >= 0 else "bad"
        rows.append(f"<tr><td>{html.escape(day)}</td><td class=\"{cls}\">{_money(pnl)}</td></tr>")
    return "".join(rows) or '<tr><td colspan="2">No closed events in range.</td></tr>'


def position_rows(positions: list[dict]) -> str:
    rows = []
    for pos in positions:
        pnl = _safe_float(pos.get("unrealized_pl"))
        cls = "good" if pnl >= 0 else "bad"
        rows.append(
            "<tr>"
            f"<td>{html.escape(str(pos.get('symbol', '')))}</td>"
            f"<td>{html.escape(str(pos.get('qty', '')))}</td>"
            f"<td>{_money(_safe_float(pos.get('market_value')))}</td>"
            f"<td class=\"{cls}\">{_money(pnl)}</td>"
            "</tr>"
        )
    return "".join(rows) or '<tr><td colspan="4">No open positions.</td></tr>'


def option_group_summaries(
    state: dict,
    positions: list[dict],
    *,
    today: date | None = None,
) -> list[dict]:
    today = today or date.today()
    position_by_symbol = {
        str(pos.get("symbol", "")): pos
        for pos in positions
        if pos.get("symbol")
    }
    rows: list[dict] = []

    for trade in state.get("trades", []):
        if trade.get("status") not in ("open", "closing"):
            continue

        legs = [str(symbol) for symbol in trade.get("legs", []) if symbol]
        found = [position_by_symbol[symbol] for symbol in legs if symbol in position_by_symbol]
        credit_received = _safe_float(trade.get("net_credit")) * 100 * int(_safe_float(trade.get("qty"), 1) or 1)
        pnl = sum(_safe_float(pos.get("unrealized_pl")) for pos in found)
        pnl_pct = (pnl / credit_received * 100) if credit_received else 0.0

        profit_close_pct = _safe_float(trade.get("profit_close_pct"), 0.50)
        stop_loss_pct = _safe_float(trade.get("stop_loss_pct"), -2.0)
        profit_target = credit_received * profit_close_pct
        stop_loss = credit_received * stop_loss_pct
        profit_target_distance = profit_target - pnl
        stop_loss_distance = pnl - stop_loss

        expiry_text = str(trade.get("expiry") or "")
        days_to_expiry: int | None = None
        if expiry_text:
            try:
                days_to_expiry = (datetime.strptime(expiry_text, "%Y-%m-%d").date() - today).days
            except ValueError:
                days_to_expiry = None

        if not found:
            exit_status = "no open legs"
        elif len(found) != len(legs):
            exit_status = "manual review: missing legs"
        elif pnl >= profit_target:
            exit_status = "profit target hit"
        elif pnl <= stop_loss:
            exit_status = "stop loss hit"
        else:
            exit_status = "open"

        rows.append(
            {
                "label": str(trade.get("label") or trade.get("id") or "options group"),
                "strategy": str(trade.get("strategy") or ""),
                "underlying": str(trade.get("underlying") or ""),
                "status": str(trade.get("status") or ""),
                "exit_status": exit_status,
                "legs_open": len(found),
                "legs_expected": len(legs),
                "credit_received": round(credit_received, 2),
                "pnl": round(pnl, 2),
                "pnl_pct": pnl_pct,
                "profit_target": round(profit_target, 2),
                "profit_target_distance": round(profit_target_distance, 2),
                "stop_loss": round(stop_loss, 2),
                "stop_loss_distance": round(stop_loss_distance, 2),
                "days_to_expiry": days_to_expiry,
            }
        )

    return rows


def option_group_rows(groups: list[dict]) -> str:
    rows = []
    for group in groups:
        pnl = _safe_float(group.get("pnl"))
        pnl_cls = "good" if pnl >= 0 else "bad"
        target_distance = _safe_float(group.get("profit_target_distance"))
        stop_distance = _safe_float(group.get("stop_loss_distance"))
        exit_status = str(group.get("exit_status", ""))
        status_cls = "bad" if "hit" in exit_status or "missing" in exit_status else "good"
        dte = group.get("days_to_expiry")
        dte_text = "-" if dte is None else str(dte)
        rows.append(
            "<tr>"
            f"<td>{html.escape(str(group.get('label', '')))}</td>"
            f"<td>{html.escape(str(group.get('strategy', '')))}</td>"
            f"<td>{group.get('legs_open', 0)}/{group.get('legs_expected', 0)}</td>"
            f"<td>{_money(_safe_float(group.get('credit_received')))}</td>"
            f"<td class=\"{pnl_cls}\">{_money(pnl)} ({_pct(_safe_float(group.get('pnl_pct')))})</td>"
            f"<td>{_money(_safe_float(group.get('profit_target')))}</td>"
            f"<td class=\"{'good' if target_distance <= 0 else 'warn'}\">{_money(target_distance)}</td>"
            f"<td>{_money(_safe_float(group.get('stop_loss')))}</td>"
            f"<td class=\"{'bad' if stop_distance <= 0 else 'good'}\">{_money(stop_distance)}</td>"
            f"<td>{html.escape(dte_text)}</td>"
            f"<td class=\"{status_cls}\">{html.escape(exit_status)}</td>"
            "</tr>"
        )
    return "".join(rows) or '<tr><td colspan="11">No open grouped option trades.</td></tr>'


def tradingview_panel(context: dict) -> str:
    available = bool(context.get("available"))
    connected = bool(context.get("connected"))
    bias = str(context.get("bias") or "unknown")
    bias_cls = "bad" if bias == "bearish" else "good" if bias == "bullish" else "warn"
    status = "connected" if connected else "not connected"
    delayed = "Delayed" if context.get("is_delayed") else "Real-time entitlement unverified"
    warnings = context.get("warnings") if isinstance(context.get("warnings"), list) else []
    warning_items = "".join(f"<li>{html.escape(str(warning))}</li>" for warning in warnings)
    if not warning_items:
        warning_items = "<li>Use this as chart validation beside bot logs.</li>"

    if not available:
        return f"""
    <div class="panel">
      <h2>TradingView Futures Context</h2>
      <p class="footer">No TradingView validation snapshot is available yet.</p>
      <ul>{warning_items}</ul>
    </div>"""

    return f"""
    <div class="panel">
      <h2>TradingView Futures Context</h2>
      <div class="tv-grid">
        <div><span>Bridge</span><strong class="{'good' if connected else 'bad'}">{html.escape(status)}</strong></div>
        <div><span>Symbol</span><strong>{html.escape(str(context.get('symbol') or ''))}</strong></div>
        <div><span>Timeframe</span><strong>{html.escape(str(context.get('timeframe') or ''))}</strong></div>
        <div><span>Last</span><strong>{_safe_float(context.get('last')):,.2f}</strong></div>
        <div><span>100-bar change</span><strong class="{'good' if _safe_float(context.get('change')) >= 0 else 'bad'}">{_safe_float(context.get('change')):,.2f} {html.escape(str(context.get('change_pct') or ''))}</strong></div>
        <div><span>Bias</span><strong class="{bias_cls}">{html.escape(bias)}</strong></div>
      </div>
      <p class="footer">{html.escape(str(context.get('description') or ''))} · {html.escape(delayed)} · bars={int(_safe_float(context.get('bar_count')))}</p>
      <ul>{warning_items}</ul>
    </div>"""


def kalshi_panel(context: dict) -> str:
    warnings = context.get("warnings") if isinstance(context.get("warnings"), list) else []
    warning_items = "".join(f"<li>{html.escape(str(warning))}</li>" for warning in warnings)
    if not warning_items:
        warning_items = "<li>Paper opportunities only. No live order execution is wired.</li>"

    rows = []
    for item in context.get("top_opportunities", []):
        edge = _safe_float(item.get("edge"))
        rows.append(
            "<tr>"
            f"<td>{html.escape(str(item.get('ticker', '')))}</td>"
            f"<td>{html.escape(str(item.get('side', '')))}</td>"
            f"<td>{_safe_float(item.get('entry_price')):.2f}</td>"
            f"<td>{_safe_float(item.get('fair_value')):.2f}</td>"
            f"<td class=\"{'good' if edge >= 0.05 else 'warn'}\">{edge:.2f}</td>"
            f"<td>{int(_safe_float(item.get('confidence')))}</td>"
            f"<td>{_money(_safe_float(item.get('max_risk_dollars')))}</td>"
            "</tr>"
        )
    body = "".join(rows) or '<tr><td colspan="7">No scored Kalshi opportunities yet.</td></tr>'
    mode = str(context.get("mode") or "paper_only")
    exec_status = "execution disabled" if not context.get("execution_enabled") else "execution requested but blocked"

    return f"""
    <div class="panel">
      <h2>Kalshi Prediction Lab</h2>
      <div class="tv-grid">
        <div><span>Mode</span><strong>{html.escape(mode)}</strong></div>
        <div><span>Orders</span><strong class="good">{html.escape(exec_status)}</strong></div>
        <div><span>Markets scanned</span><strong>{int(_safe_float(context.get('markets_scanned')))}</strong></div>
      </div>
      <table style="margin-top: 14px;">
        <thead><tr><th>Ticker</th><th>Side</th><th>Entry</th><th>Fair</th><th>Edge</th><th>Conf</th><th>Risk Cap</th></tr></thead>
        <tbody>{body}</tbody>
      </table>
      <ul>{warning_items}</ul>
    </div>"""


def copy_watchlist_panel(context: dict) -> str:
    warnings = context.get("warnings") if isinstance(context.get("warnings"), list) else []
    warning_items = "".join(f"<li>{html.escape(str(warning))}</li>" for warning in warnings)
    if not warning_items:
        warning_items = "<li>Paper-only watchlist. No copy orders are wired.</li>"

    rows = []
    for trader in context.get("top_traders", []):
        flags = trader.get("risk_flags") if isinstance(trader.get("risk_flags"), list) else []
        flags_text = ", ".join(str(flag) for flag in flags) if flags else "none"
        confidence = int(_safe_float(trader.get("confidence")))
        conviction = int(_safe_float(trader.get("conviction_score")))
        rows.append(
            "<tr>"
            f"<td>{html.escape(str(trader.get('handle', '')))}</td>"
            f"<td>{html.escape(str(trader.get('platform', '')))}</td>"
            f"<td>{int(_safe_float(trader.get('trades')))}</td>"
            f"<td>{_pct(_safe_float(trader.get('win_rate')) * 100)}</td>"
            f"<td>{_safe_float(trader.get('profit_factor')):.2f}</td>"
            f"<td class=\"{'good' if _safe_float(trader.get('realized_pnl')) >= 0 else 'bad'}\">{_money(_safe_float(trader.get('realized_pnl')))}</td>"
            f"<td class=\"{'good' if confidence >= 8 else 'warn' if confidence >= 5 else 'bad'}\">{confidence}</td>"
            f"<td class=\"{'good' if conviction >= 8 else 'warn' if conviction >= 5 else 'bad'}\">{conviction}</td>"
            f"<td>{_money(_safe_float(trader.get('suggested_copy_size')))}</td>"
            f"<td>{html.escape(str(trader.get('status', '')))}</td>"
            f"<td>{html.escape(flags_text)}</td>"
            "</tr>"
        )
    body = "".join(rows) or '<tr><td colspan="11">No copy-trader profiles loaded yet.</td></tr>'
    signal_rows = []
    for signal in context.get("paper_signals", []):
        action = str(signal.get("action") or "")
        signal_rows.append(
            "<tr>"
            f"<td>{html.escape(str(signal.get('trader', '')))}</td>"
            f"<td>{html.escape(str(signal.get('platform', '')))}</td>"
            f"<td>{html.escape(str(signal.get('symbol', '')))}</td>"
            f"<td>{html.escape(str(signal.get('side', '')))}</td>"
            f"<td class=\"{'good' if action == 'paper_copy' else 'bad'}\">{html.escape(action)}</td>"
            f"<td>{_money(_safe_float(signal.get('notional')))}</td>"
            f"<td>{_safe_float(signal.get('price_drift')):.1%}</td>"
            "</tr>"
        )
    signal_body = "".join(signal_rows) or '<tr><td colspan="7">No observed copy signals loaded yet.</td></tr>'
    exec_status = "execution disabled" if not context.get("execution_enabled") else "execution requested but blocked"

    return f"""
    <div class="panel">
      <h2>Copy Trader Watchlist</h2>
      <div class="tv-grid">
        <div><span>Mode</span><strong>{html.escape(str(context.get('mode') or 'paper_only'))}</strong></div>
        <div><span>Orders</span><strong class="good">{html.escape(exec_status)}</strong></div>
        <div><span>Watched</span><strong>{int(_safe_float(context.get('watched_count')))}</strong></div>
        <div><span>Paper signals</span><strong>{int(_safe_float(context.get('paper_signal_count')))}</strong></div>
      </div>
      <table style="margin-top: 14px;">
        <thead><tr><th>Trader</th><th>Platform</th><th>Trades</th><th>Win</th><th>PF</th><th>P&L</th><th>Conf</th><th>Conviction</th><th>Copy Size</th><th>Status</th><th>Flags</th></tr></thead>
        <tbody>{body}</tbody>
      </table>
      <table style="margin-top: 14px;">
        <thead><tr><th>Trader</th><th>Platform</th><th>Symbol</th><th>Side</th><th>Action</th><th>Notional</th><th>Drift</th></tr></thead>
        <tbody>{signal_body}</tbody>
      </table>
      <ul>{warning_items}</ul>
    </div>"""


def polymarket_wallet_panel(context: dict) -> str:
    warnings = context.get("warnings") if isinstance(context.get("warnings"), list) else []
    warning_items = "".join(f"<li>{html.escape(str(warning))}</li>" for warning in warnings)
    rows = []
    for wallet in context.get("wallets", []):
        flags = wallet.get("risk_flags") if isinstance(wallet.get("risk_flags"), list) else []
        flags_text = ", ".join(str(flag) for flag in flags) if flags else "none"
        confidence = int(_safe_float(wallet.get("confidence")))
        rows.append(
            "<tr>"
            f"<td>{html.escape(str(wallet.get('handle') or wallet.get('wallet') or ''))}</td>"
            f"<td>{int(_safe_float(wallet.get('trades')))}</td>"
            f"<td>{_pct(_safe_float(wallet.get('win_rate')) * 100)}</td>"
            f"<td>{_safe_float(wallet.get('profit_factor')):.2f}</td>"
            f"<td class=\"{'good' if _safe_float(wallet.get('realized_pnl')) >= 0 else 'bad'}\">{_money(_safe_float(wallet.get('realized_pnl')))}</td>"
            f"<td>{int(_safe_float(wallet.get('green_months')))}</td>"
            f"<td class=\"{'good' if confidence >= 8 else 'warn' if confidence >= 5 else 'bad'}\">{confidence}</td>"
            f"<td>{html.escape(str(wallet.get('status') or ''))}</td>"
            f"<td>{html.escape(flags_text)}</td>"
            "</tr>"
        )
    body = "".join(rows) or '<tr><td colspan="9">No public wallets tracked yet.</td></tr>'
    exec_status = "execution disabled" if not context.get("execution_enabled") else "execution requested but blocked"
    if not warning_items:
        warning_items = "<li>Read-only wallet evidence. Promote only through paper watch scoring.</li>"

    return f"""
    <div class="panel">
      <h2>Polymarket Wallet Tracker</h2>
      <div class="tv-grid">
        <div><span>Mode</span><strong>{html.escape(str(context.get('mode') or 'read_only'))}</strong></div>
        <div><span>Orders</span><strong class="good">{html.escape(exec_status)}</strong></div>
        <div><span>Wallets</span><strong>{int(_safe_float(context.get('wallet_count')))}</strong></div>
      </div>
      <table style="margin-top: 14px;">
        <thead><tr><th>Wallet</th><th>Trades</th><th>Win</th><th>PF</th><th>P&L</th><th>Green Mo</th><th>Conf</th><th>Status</th><th>Flags</th></tr></thead>
        <tbody>{body}</tbody>
      </table>
      <ul>{warning_items}</ul>
    </div>"""


def polymarket_fed_whale_panel(context: dict) -> str:
    warnings = context.get("warnings") if isinstance(context.get("warnings"), list) else []
    warning_items = "".join(f"<li>{html.escape(str(warning))}</li>" for warning in warnings)
    if not warning_items:
        warning_items = "<li>Read-only Fed whale intelligence. No prediction-market orders are wired.</li>"

    consensus_rows = []
    for item in context.get("consensus", []):
        consensus_rows.append(
            "<tr>"
            f"<td>{html.escape(str(item.get('market') or ''))}</td>"
            f"<td>{html.escape(str(item.get('outcome') or ''))}</td>"
            f"<td>{html.escape(str(item.get('side') or ''))}</td>"
            f"<td>{int(_safe_float(item.get('wallet_count')))}</td>"
            f"<td>{_money(_safe_float(item.get('total_notional')))}</td>"
            f"<td>{html.escape(str(item.get('action') or ''))}</td>"
            "</tr>"
        )
    consensus_body = "".join(consensus_rows) or '<tr><td colspan="6">No Fed whale consensus yet.</td></tr>'

    trade_rows = []
    for trade in context.get("top_whale_trades", []):
        wallet = str(trade.get("wallet") or "")
        short_wallet = wallet[:8] + "..." + wallet[-4:] if len(wallet) > 14 else wallet
        trade_rows.append(
            "<tr>"
            f"<td>{html.escape(short_wallet)}</td>"
            f"<td>{html.escape(str(trade.get('outcome') or ''))}</td>"
            f"<td>{html.escape(str(trade.get('side') or ''))}</td>"
            f"<td>{_money(_safe_float(trade.get('notional')))}</td>"
            f"<td>{_safe_float(trade.get('price')):.3f}</td>"
            f"<td>{html.escape(str(trade.get('known_profile_status') or 'unknown'))}</td>"
            "</tr>"
        )
    trade_body = "".join(trade_rows) or '<tr><td colspan="6">No whale trades above threshold.</td></tr>'
    exec_status = "execution disabled" if not context.get("execution_enabled") else "execution requested but blocked"

    return f"""
    <div class="panel">
      <h2>Fed Whale Watch</h2>
      <div class="tv-grid">
        <div><span>Mode</span><strong>{html.escape(str(context.get('mode') or 'read_only'))}</strong></div>
        <div><span>Orders</span><strong class="good">{html.escape(exec_status)}</strong></div>
        <div><span>Markets</span><strong>{int(_safe_float(context.get('markets_scanned')))}</strong></div>
        <div><span>Whale trades</span><strong>{int(_safe_float(context.get('whale_trade_count')))}</strong></div>
        <div><span>Consensus</span><strong>{int(_safe_float(context.get('consensus_count')))}</strong></div>
      </div>
      <table style="margin-top: 14px;">
        <thead><tr><th>Market</th><th>Outcome</th><th>Side</th><th>Wallets</th><th>Notional</th><th>Action</th></tr></thead>
        <tbody>{consensus_body}</tbody>
      </table>
      <table style="margin-top: 14px;">
        <thead><tr><th>Wallet</th><th>Outcome</th><th>Side</th><th>Notional</th><th>Price</th><th>Profile</th></tr></thead>
        <tbody>{trade_body}</tbody>
      </table>
      <ul>{warning_items}</ul>
    </div>"""


def social_arbitrage_panel(context: dict) -> str:
    warnings = context.get("warnings") if isinstance(context.get("warnings"), list) else []
    warning_items = "".join(f"<li>{html.escape(str(warning))}</li>" for warning in warnings)
    if not warning_items:
        warning_items = "<li>Research-only social trend scanner. No broker orders are wired.</li>"

    rows = []
    for idea in context.get("ideas", []):
        rows.append(
            "<tr>"
            f"<td>{html.escape(str(idea.get('ticker') or ''))}</td>"
            f"<td>{html.escape(str(idea.get('theme') or ''))}</td>"
            f"<td>{_safe_float(idea.get('score')):.1f}</td>"
            f"<td>{int(_safe_float(idea.get('source_count')))}</td>"
            f"<td>{html.escape(', '.join(str(src) for src in idea.get('sources', [])[:4]))}</td>"
            f"<td>{html.escape(str(idea.get('action') or ''))}</td>"
            "</tr>"
        )
    body = "".join(rows) or '<tr><td colspan="6">No social-arb ideas loaded yet.</td></tr>'
    exec_status = "execution disabled" if not context.get("execution_enabled") else "execution requested but blocked"

    return f"""
    <div class="panel">
      <h2>Social Arbitrage Watchlist</h2>
      <div class="tv-grid">
        <div><span>Mode</span><strong>{html.escape(str(context.get('mode') or 'research_only'))}</strong></div>
        <div><span>Orders</span><strong class="good">{html.escape(exec_status)}</strong></div>
        <div><span>Observations</span><strong>{int(_safe_float(context.get('observation_count')))}</strong></div>
        <div><span>Ideas</span><strong>{int(_safe_float(context.get('idea_count')))}</strong></div>
      </div>
      <table style="margin-top: 14px;">
        <thead><tr><th>Ticker</th><th>Theme</th><th>Score</th><th>Sources</th><th>Platforms</th><th>Action</th></tr></thead>
        <tbody>{body}</tbody>
      </table>
      <ul>{warning_items}</ul>
    </div>"""


def momentum_shadow_panel(context: dict) -> str:
    warnings = context.get("warnings") if isinstance(context.get("warnings"), list) else []
    warning_items = "".join(f"<li>{html.escape(str(warning))}</li>" for warning in warnings)
    if not warning_items:
        warning_items = "<li>Shadow-only weekly ETF rotation forward test.</li>"

    if not context.get("available"):
        return f"""
    <div class="panel">
      <h2>Momentum Rotation Shadow</h2>
      <p class="footer">No momentum shadow log exists yet. Run scripts/momentum_shadow_logger.py once.</p>
      <ul>{warning_items}</ul>
    </div>"""

    latest = context.get("latest") if isinstance(context.get("latest"), dict) else {}
    previous = context.get("previous") if isinstance(context.get("previous"), dict) else None
    holdings = latest.get("holdings") if isinstance(latest.get("holdings"), list) else []
    weights = latest.get("weights") if isinstance(latest.get("weights"), dict) else {}
    ranked = latest.get("ranked") if isinstance(latest.get("ranked"), list) else []
    target = "CASH" if latest.get("in_cash") else ", ".join(
        f"{html.escape(str(symbol))} ({_safe_float(weights.get(symbol)) * 100:.0f}%)"
        for symbol in holdings
    )
    if not target:
        target = "No target"

    last_ret = context.get("last_period_return_pct")
    if last_ret is None:
        ret_text = "pending"
        ret_cls = "warn"
    else:
        last_ret_float = _safe_float(last_ret)
        ret_text = f"{last_ret_float:+.2f}%"
        ret_cls = "good" if last_ret_float >= 0 else "bad"

    prev_text = "none" if not previous else f"{previous.get('date', '')}: {', '.join(previous.get('holdings', []) or ['CASH'])}"
    rank_rows = []
    for row in ranked[:5]:
        if not isinstance(row, (list, tuple)) or len(row) < 2:
            continue
        symbol, ret = row[0], _safe_float(row[1])
        hold = "yes" if str(symbol) in {str(item) for item in holdings} else "no"
        rank_rows.append(
            "<tr>"
            f"<td>{html.escape(str(symbol))}</td>"
            f"<td class=\"{'good' if ret > 0 else 'bad'}\">{ret * 100:+.1f}%</td>"
            f"<td>{hold}</td>"
            "</tr>"
        )
    rank_body = "".join(rank_rows) or '<tr><td colspan="3">No ranking snapshot available.</td></tr>'

    return f"""
    <div class="panel">
      <h2>Momentum Rotation Shadow</h2>
      <div class="tv-grid">
        <div><span>Mode</span><strong class="good">shadow-only</strong></div>
        <div><span>Latest</span><strong>{html.escape(str(latest.get('date') or ''))}</strong></div>
        <div><span>Target</span><strong>{target}</strong></div>
        <div><span>Last period</span><strong class="{ret_cls}">{ret_text}</strong></div>
        <div><span>Logs</span><strong>{int(_safe_float(context.get('log_count')))}</strong></div>
        <div><span>Config</span><strong>{int(_safe_float(latest.get('lookback_months')))}m / top-{int(_safe_float(latest.get('top_n')))}</strong></div>
      </div>
      <p class="footer">Previous target: {html.escape(prev_text)}</p>
      <table style="margin-top: 14px;">
        <thead><tr><th>Rank</th><th>12m Return</th><th>Held</th></tr></thead>
        <tbody>{rank_body}</tbody>
      </table>
      <ul>{warning_items}</ul>
    </div>"""


def daily_shadow_panel(context: dict) -> str:
    title = html.escape(str(context.get("title") or "Daily Shadow"))
    warnings = context.get("warnings") if isinstance(context.get("warnings"), list) else []
    warning_items = "".join(f"<li>{html.escape(str(warning))}</li>" for warning in warnings)
    if not warning_items:
        warning_items = "<li>Shadow-only daily forward test.</li>"

    if not context.get("available"):
        return f"""
    <div class="panel">
      <h2>{title}</h2>
      <p class="footer">No shadow log exists yet. Run the matching logger once.</p>
      <ul>{warning_items}</ul>
    </div>"""

    latest = context.get("latest") if isinstance(context.get("latest"), dict) else {}
    primary = latest.get("primary_setup") if isinstance(latest.get("primary_setup"), dict) else {}
    comparison = latest.get("comparison_setup") if isinstance(latest.get("comparison_setup"), dict) else {}
    features = latest.get("features") if isinstance(latest.get("features"), dict) else {}
    log_count = int(_safe_float(context.get("log_count")))
    entry_count = int(_safe_float(context.get("entry_count")))
    min_days = int(_safe_float(context.get("min_days"), 30))
    min_entries = int(_safe_float(context.get("min_entries"), 10))
    ready = log_count >= min_days and entry_count >= min_entries
    status_cls = "good" if ready else "warn"
    status = "READY FOR REVIEW" if ready else "NOT READY"

    feature_rows = []
    for key, value in list(features.items())[:8]:
        feature_rows.append(
            "<tr>"
            f"<td>{html.escape(str(key))}</td>"
            f"<td>{html.escape(str(value))}</td>"
            "</tr>"
        )
    feature_body = "".join(feature_rows) or '<tr><td colspan="2">No feature snapshot available.</td></tr>'

    return f"""
    <div class="panel">
      <h2>{title}</h2>
      <div class="tv-grid">
        <div><span>Mode</span><strong class="good">shadow-only</strong></div>
        <div><span>Latest</span><strong>{html.escape(str(latest.get('date') or ''))}</strong></div>
        <div><span>Symbol</span><strong>{html.escape(str(latest.get('symbol') or ''))}</strong></div>
        <div><span>Primary</span><strong>{html.escape(str(primary.get('action') or ''))}</strong></div>
        <div><span>Logs</span><strong>{log_count}/{min_days}</strong></div>
        <div><span>Entries</span><strong>{entry_count}/{min_entries}</strong></div>
      </div>
      <p class="footer">
        Primary: {html.escape(str(primary.get('name') or ''))} (conf {html.escape(str(primary.get('confidence') or ''))}) |
        Comparison: {html.escape(str(comparison.get('name') or ''))} (conf {html.escape(str(comparison.get('confidence') or ''))}) |
        Gate: <strong class="{status_cls}">{status}</strong>
      </p>
      <table style="margin-top: 14px;">
        <thead><tr><th>Feature</th><th>Value</th></tr></thead>
        <tbody>{feature_body}</tbody>
      </table>
      <ul>{warning_items}</ul>
    </div>"""


def kalshi_guard_blocks_context(path: Path = KALSHI_GUARD_BLOCK_LOG_FILE, limit: int = 20) -> dict:
    return guard_blocks_context(path=path, limit=limit)


def _read_env_flag(env_file: Path, key: str, default: str = "true") -> str:
    """Read a single key from a .env file without importing dotenv."""
    if not env_file.exists():
        return default
    try:
        for line in env_file.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line.startswith(key + "="):
                return line.split("=", 1)[1].strip().strip('"').strip("'")
    except Exception:
        pass
    return default


def bot_status_context() -> dict:
    agent_env = ROOT / "agent" / ".env"
    alpaca_paper = _read_env_flag(agent_env, "ALPACA_PAPER", "true").lower() == "true"
    flip_live = _read_env_flag(agent_env, "FLIP_LIVE_EXECUTION_ENABLED", "false").lower() == "true"
    options_live = _read_env_flag(agent_env, "OPTIONS_LIVE_EXECUTION_ENABLED", "false").lower() == "true"
    kalshi_dry_run = _read_env_flag(KALSHI_BOT_ENV, "DRY_RUN", "true").lower() != "false"
    kalshi_live = _read_env_flag(KALSHI_BOT_ENV, "KALSHI_LIVE_EXECUTION_ENABLED", "false").lower() == "true"

    return {
        "bots": [
            {
                "name": "Flip Bot",
                "mode": "paper" if alpaca_paper else "live",
                "live_enabled": flip_live,
                "manual_reset": ALPACA_BLOCK_FILE.exists(),
                "execution": "shadow" if (not flip_live and alpaca_paper) else ("live" if (not alpaca_paper and flip_live) else "paper-auto"),
            },
            {
                "name": "IWM Options Bot",
                "mode": "paper" if alpaca_paper else "live",
                "live_enabled": options_live,
                "manual_reset": ALPACA_BLOCK_FILE.exists(),
                "execution": "shadow" if (not options_live and alpaca_paper) else ("live" if (not alpaca_paper and options_live) else "paper-auto"),
            },
            {
                "name": "Kalshi Weather Bot",
                "mode": "dry-run" if kalshi_dry_run else "live",
                "live_enabled": kalshi_live,
                "manual_reset": KALSHI_BLOCK_FILE.exists(),
                "execution": "dry-run" if kalshi_dry_run else ("live" if kalshi_live else "blocked"),
            },
            {
                "name": "MNQ Shadow Scanner",
                "mode": "shadow",
                "live_enabled": False,
                "manual_reset": False,
                "execution": "shadow-only",
            },
            {
                "name": "Copy Trader / Polymarket",
                "mode": "watch",
                "live_enabled": False,
                "manual_reset": False,
                "execution": "watch-only",
            },
            {
                "name": "Fed Whale Watch",
                "mode": "watch",
                "live_enabled": False,
                "manual_reset": False,
                "execution": "watch-only",
            },
            {
                "name": "Social Arbitrage Watchlist",
                "mode": "research",
                "live_enabled": False,
                "manual_reset": False,
                "execution": "research-only",
            },
            {
                "name": "Momentum Rotation Shadow",
                "mode": "shadow",
                "live_enabled": False,
                "manual_reset": False,
                "execution": "weekly-shadow-only",
            },
            {
                "name": "RSI-2 QQQ Shadow",
                "mode": "shadow",
                "live_enabled": False,
                "manual_reset": False,
                "execution": "daily-shadow-only",
            },
            {
                "name": "KAMA QQQ Shadow",
                "mode": "shadow",
                "live_enabled": False,
                "manual_reset": False,
                "execution": "daily-shadow-only",
            },
        ]
    }


def bot_status_panel(context: dict) -> str:
    _MODE_CLS = {
        "paper": "warn", "paper-auto": "warn", "live": "bad",
        "dry-run": "good", "shadow": "good", "shadow-only": "good", "weekly-shadow-only": "good", "daily-shadow-only": "good",
        "watch": "good", "watch-only": "good", "research": "good", "research-only": "good", "blocked": "bad",
    }
    rows = []
    for bot in context.get("bots", []):
        name = html.escape(str(bot.get("name", "")))
        mode = str(bot.get("mode", ""))
        execution = str(bot.get("execution", ""))
        live_enabled = bool(bot.get("live_enabled"))
        manual_reset = bool(bot.get("manual_reset"))
        mode_cls = _MODE_CLS.get(mode, "warn")
        exec_cls = "bad" if execution in ("live", "blocked") else "good" if execution in ("dry-run", "shadow-only", "weekly-shadow-only", "daily-shadow-only", "watch-only", "research-only") else "warn"
        live_cls = "bad" if live_enabled else "good"
        reset_cls = "bad" if manual_reset else "good"
        rows.append(
            "<tr>"
            f"<td><strong>{name}</strong></td>"
            f"<td class=\"{mode_cls}\">{html.escape(mode)}</td>"
            f"<td class=\"{exec_cls}\">{html.escape(execution)}</td>"
            f"<td class=\"{live_cls}\">{'ENABLED' if live_enabled else 'blocked'}</td>"
            f"<td class=\"{reset_cls}\">{'REQUIRED' if manual_reset else 'clear'}</td>"
            "</tr>"
        )
    body = "".join(rows) or '<tr><td colspan="5">No bots configured.</td></tr>'
    return f"""
    <div class="panel">
      <h2>Bot Execution Status</h2>
      <table>
        <thead><tr><th>Bot</th><th>Mode</th><th>Execution</th><th>Live Unlock</th><th>Manual Reset</th></tr></thead>
        <tbody>{body}</tbody>
      </table>
      <p class="footer">Live unlock = bot-specific env var set. Manual reset = block file exists at ~/.vibe-trading/. Delete block file to resume after daily loss trigger.</p>
    </div>"""


def kalshi_guard_blocks_panel(context: dict) -> str:
    if not context.get("available"):
        return """
    <div class="panel">
      <h2>Kalshi Guard Blocks</h2>
      <p class="footer">No kalshi-guard-blocks.jsonl yet — will appear after first blocked Kalshi order.</p>
    </div>"""

    rows = []
    for entry in context.get("blocks", []):
        details = entry.get("details") or {}
        reason = html.escape(str(entry.get("reason", "")))
        ticker = html.escape(str(details.get("market_ticker", "")))
        side = html.escape(str(details.get("side", "")))
        price = _safe_float(details.get("price_cents"))
        contracts = int(_safe_float(details.get("contracts")))
        edge = _safe_float(details.get("edge")) * 100
        notional = _safe_float(details.get("estimated_notional_dollars"))
        daily_loss = _safe_float(details.get("daily_loss_dollars"))
        checked = html.escape(str(details.get("checked_at", "")))
        rows.append(
            "<tr>"
            f"<td>{checked}</td>"
            f"<td>{ticker}</td>"
            f"<td>{side}</td>"
            f"<td class=\"bad\">{reason}</td>"
            f"<td>{price:.0f}¢</td>"
            f"<td>{contracts}</td>"
            f"<td>{edge:.1f}%</td>"
            f"<td>{_money(notional)}</td>"
            f"<td>{_money(daily_loss)}</td>"
            "</tr>"
        )
    body = "".join(rows) or '<tr><td colspan="9">No recent Kalshi blocks.</td></tr>'
    total = int(_safe_float(context.get("total")))
    return f"""
    <div class="panel">
      <h2>Kalshi Guard Blocks (last 20 of {total})</h2>
      <table>
        <thead><tr><th>Timestamp</th><th>Market</th><th>Side</th><th>Reason</th><th>Price</th><th>Qty</th><th>Edge</th><th>Notional</th><th>Daily Loss</th></tr></thead>
        <tbody>{body}</tbody>
      </table>
      <p class="footer">Kalshi live orders blocked unless DRY_RUN=false AND KALSHI_LIVE_EXECUTION_ENABLED=true.</p>
    </div>"""


def guard_blocks_panel(context: dict) -> str:
    if not context.get("available"):
        return """
    <div class="panel">
      <h2>Execution Guard Blocks</h2>
      <p class="footer">No guard-blocks.jsonl yet — will appear after first blocked order.</p>
    </div>"""

    rows = []
    for entry in context.get("blocks", []):
        details = entry.get("details") or {}
        reason = html.escape(str(entry.get("reason", "")))
        bot = html.escape(str(details.get("bot", "")))
        sym = html.escape(str(details.get("symbol", "")))
        conf = details.get("confidence")
        conf_text = f"{conf:.1f}" if conf is not None else "—"
        min_conf = _safe_float(details.get("min_confidence"))
        notional = _safe_float(details.get("estimated_notional"))
        daily_loss = _safe_float(details.get("daily_loss_pct")) * 100
        manual = "YES" if details.get("block_file") else "no"
        checked = html.escape(str(details.get("checked_at", "")))
        rows.append(
            "<tr>"
            f"<td>{checked}</td>"
            f"<td>{bot}</td>"
            f"<td>{sym}</td>"
            f"<td class=\"bad\">{reason}</td>"
            f"<td class=\"{'bad' if conf is None or _safe_float(conf) < min_conf else 'good'}\">{conf_text} / {min_conf:.1f}</td>"
            f"<td>{_money(notional)}</td>"
            f"<td>{daily_loss:.1f}%</td>"
            f"<td class=\"{'bad' if manual == 'YES' else 'good'}\">{manual}</td>"
            "</tr>"
        )
    body = "".join(rows) or '<tr><td colspan="8">No recent blocks.</td></tr>'
    total = int(_safe_float(context.get("total")))

    return f"""
    <div class="panel">
      <h2>Execution Guard Blocks (last 20 of {total})</h2>
      <table>
        <thead><tr><th>Timestamp</th><th>Bot</th><th>Symbol</th><th>Reason</th><th>Conf / Min</th><th>Notional</th><th>Daily Loss</th><th>Manual Reset</th></tr></thead>
        <tbody>{body}</tbody>
      </table>
      <p class="footer">All blocked orders are logged to guard-blocks.jsonl. Manual reset = block file exists and must be deleted before trading resumes.</p>
    </div>"""


def render(account: dict, positions: list[dict], events: list[dict], flips: list[dict], history: dict, days: int) -> str:
    summary = performance_summary(events, flips)
    score, notes = confidence_score(account, positions, summary, PAPER)
    points = portfolio_points(history)
    option_groups = option_group_summaries(options_state(), positions)
    tv_context = tradingview_context()
    prediction_context = kalshi_context()
    copy_context = copy_watchlist_context()
    poly_wallet_context = polymarket_wallet_context()
    fed_whale_context = polymarket_fed_whale_context()
    social_context = social_arbitrage_context()
    momentum_context = momentum_shadow_context()
    rsi2_context = daily_shadow_context(RSI2_SHADOW_LOG_FILE, "RSI-2 QQQ Shadow")
    kama_context = daily_shadow_context(KAMA_SHADOW_LOG_FILE, "KAMA QQQ Shadow")
    guard_context = guard_blocks_context()
    kalshi_guard_context = kalshi_guard_blocks_context()
    bot_status = bot_status_context()
    equity = _safe_float(account.get("equity"))
    last_equity = _safe_float(account.get("last_equity"))
    daily_pl = equity - last_equity if equity and last_equity else 0.0
    unrealized = sum(_safe_float(p.get("unrealized_pl")) for p in positions)
    pf = summary["profit_factor"]
    pf_label = "Inf" if pf == float("inf") else f"{pf:.2f}"
    generated = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    note_items = "".join(f"<li>{html.escape(n)}</li>" for n in notes)
    if not note_items:
        note_items = "<li>Metrics are healthy enough for continued paper testing.</li>"

    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Vibe Trading Dashboard</title>
  <style>
    :root {{
      color-scheme: light;
      --ink: #102027;
      --muted: #61707a;
      --line: #dce5e8;
      --panel: #ffffff;
      --bg: #f3f7f4;
      --green: #16834a;
      --red: #c24135;
      --blue: #1768ac;
      --amber: #a96500;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      color: var(--ink);
      background: radial-gradient(circle at 15% 0%, #dff3e8, transparent 26rem), var(--bg);
    }}
    main {{ width: min(1180px, calc(100% - 32px)); margin: 0 auto; padding: 32px 0 48px; }}
    header {{ display: flex; justify-content: space-between; gap: 24px; align-items: end; margin-bottom: 22px; }}
    h1 {{ font-size: clamp(32px, 5vw, 58px); line-height: 0.95; margin: 0 0 10px; letter-spacing: 0; }}
    h2 {{ font-size: 18px; margin: 0 0 14px; }}
    p {{ margin: 0; color: var(--muted); }}
    .badge {{ display: inline-flex; align-items: center; gap: 8px; border: 1px solid var(--line); background: #fff; padding: 8px 12px; border-radius: 999px; font-weight: 700; }}
    .dot {{ width: 9px; height: 9px; border-radius: 99px; background: var(--green); }}
    .grid {{ display: grid; gap: 14px; }}
    .metrics {{ grid-template-columns: repeat(6, minmax(0, 1fr)); }}
    .two {{ grid-template-columns: 1.15fr .85fr; margin-top: 14px; }}
    .panel {{ background: rgba(255,255,255,.88); border: 1px solid var(--line); border-radius: 8px; padding: 18px; box-shadow: 0 18px 48px rgba(35, 58, 50, .08); }}
    .metric strong {{ display: block; font-size: 25px; margin-top: 8px; }}
    .metric span {{ color: var(--muted); font-size: 13px; font-weight: 700; text-transform: uppercase; }}
    .tv-grid {{ display: grid; grid-template-columns: repeat(6, minmax(0, 1fr)); gap: 12px; }}
    .tv-grid div {{ border-top: 1px solid var(--line); padding-top: 10px; }}
    .tv-grid span {{ color: var(--muted); font-size: 12px; font-weight: 800; text-transform: uppercase; display: block; }}
    .tv-grid strong {{ display: block; font-size: 18px; margin-top: 5px; overflow-wrap: anywhere; }}
    .good {{ color: var(--green); }}
    .bad {{ color: var(--red); }}
    .warn {{ color: var(--amber); }}
    .score {{ display: grid; place-items: center; min-height: 230px; text-align: center; }}
    .score-num {{ font-size: 72px; font-weight: 850; line-height: 1; }}
    .bars {{ height: 260px; display: flex; align-items: end; gap: 7px; border-bottom: 1px solid var(--line); padding-top: 16px; overflow: hidden; }}
    .bar {{ flex: 1; min-width: 14px; position: relative; border-radius: 5px 5px 0 0; background: linear-gradient(180deg, #31b977, #1768ac); }}
    .bar span {{ position: absolute; bottom: -24px; left: 50%; transform: translateX(-50%) rotate(-45deg); font-size: 10px; color: var(--muted); }}
    .bar b {{ display: none; position: absolute; left: 50%; top: -30px; transform: translateX(-50%); white-space: nowrap; background: var(--ink); color: #fff; border-radius: 4px; padding: 4px 7px; font-size: 11px; }}
    .bar:hover b {{ display: block; }}
    table {{ width: 100%; border-collapse: collapse; font-size: 14px; }}
    td, th {{ padding: 10px 8px; border-top: 1px solid var(--line); text-align: left; }}
    th {{ color: var(--muted); font-size: 12px; text-transform: uppercase; }}
    ul {{ margin: 12px 0 0; padding-left: 18px; color: var(--muted); }}
    li {{ margin: 7px 0; }}
    .footer {{ margin-top: 14px; font-size: 13px; color: var(--muted); }}
    @media (max-width: 920px) {{
      header, .two {{ grid-template-columns: 1fr; display: grid; align-items: start; }}
      .metrics {{ grid-template-columns: repeat(2, minmax(0, 1fr)); }}
    }}
  </style>
</head>
<body>
<main>
  <header>
    <div>
      <div class="badge"><span class="dot"></span>{'PAPER' if PAPER else 'LIVE'} account analytics</div>
      <h1>Vibe Trading Dashboard</h1>
      <p>Read-only bot performance report. Generated {html.escape(generated)} from the last {days} day(s).</p>
    </div>
    <div class="badge">Mode: {'Paper safety' if PAPER else 'Live risk'}</div>
  </header>

  <section class="grid metrics">
    <div class="panel metric"><span>Equity</span><strong>{_money(equity)}</strong></div>
    <div class="panel metric"><span>Daily P&L</span><strong class="{'good' if daily_pl >= 0 else 'bad'}">{_money(daily_pl)}</strong></div>
    <div class="panel metric"><span>Unrealized P&L</span><strong class="{'good' if unrealized >= 0 else 'bad'}">{_money(unrealized)}</strong></div>
    <div class="panel metric"><span>Win rate</span><strong>{_pct(summary['win_rate'])}</strong></div>
    <div class="panel metric"><span>Order cashflow</span><strong class="{'good' if summary['order_cashflow'] >= 0 else 'bad'}">{_money(summary['order_cashflow'])}</strong></div>
    <div class="panel metric"><span>Order events</span><strong>{len(events)}</strong></div>
  </section>

  <section class="grid" style="margin-top: 14px;">
    {tradingview_panel(tv_context)}
  </section>

  <section class="grid" style="margin-top: 14px;">
    {kalshi_panel(prediction_context)}
  </section>

  <section class="grid" style="margin-top: 14px;">
    {copy_watchlist_panel(copy_context)}
  </section>

  <section class="grid" style="margin-top: 14px;">
    {polymarket_wallet_panel(poly_wallet_context)}
  </section>

  <section class="grid two">
    {polymarket_fed_whale_panel(fed_whale_context)}
    {social_arbitrage_panel(social_context)}
  </section>

  <section class="grid" style="margin-top: 14px;">
    {momentum_shadow_panel(momentum_context)}
  </section>

  <section class="grid two">
    {daily_shadow_panel(rsi2_context)}
    {daily_shadow_panel(kama_context)}
  </section>

  <section class="grid" style="margin-top: 14px;">
    {bot_status_panel(bot_status)}
  </section>

  <section class="grid" style="margin-top: 14px;">
    {guard_blocks_panel(guard_context)}
  </section>

  <section class="grid" style="margin-top: 14px;">
    {kalshi_guard_blocks_panel(kalshi_guard_context)}
  </section>

  <section class="grid two">
    <div class="panel">
      <h2>Account Equity</h2>
      <div class="bars">{bars(points)}</div>
      <p class="footer">Hover bars for equity. Use this to catch drawdown before scaling size.</p>
    </div>
    <div class="panel score">
      <div>
        <p>Project confidence score</p>
        <div class="score-num {'good' if score >= 80 else 'warn' if score >= 55 else 'bad'}">{score}</div>
        <p>Goal: 90+ before prop-firm scaling or live automation.</p>
        <ul>{note_items}</ul>
      </div>
    </div>
  </section>

  <section class="grid two">
    <div class="panel" style="grid-column: 1 / -1;">
      <h2>Grouped Options</h2>
      <table>
        <thead>
          <tr>
            <th>Group</th><th>Strategy</th><th>Legs</th><th>Credit</th><th>Group P&L</th>
            <th>Target</th><th>To Target</th><th>Stop</th><th>To Stop</th><th>DTE</th><th>Status</th>
          </tr>
        </thead>
        <tbody>{option_group_rows(option_groups)}</tbody>
      </table>
    </div>
  </section>

  <section class="grid two">
    <div class="panel">
      <h2>Open Positions</h2>
      <table>
        <thead><tr><th>Symbol</th><th>Qty</th><th>Market Value</th><th>Unrealized</th></tr></thead>
        <tbody>{position_rows(positions)}</tbody>
      </table>
    </div>
    <div class="panel">
      <h2>Daily Closed Events</h2>
      <table>
        <thead><tr><th>Day</th><th>Net</th></tr></thead>
        <tbody>{daily_rows(summary)}</tbody>
      </table>
      <p class="footer">Order cashflow is estimated. Exact broker-closed P&L should be reconciled with Alpaca history.</p>
    </div>
  </section>
</main>
</body>
</html>"""


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate read-only Alpaca trading dashboard.")
    parser.add_argument("--days", type=int, default=30, help="Lookback window for closed orders and equity history.")
    parser.add_argument("--open", action="store_true", help="Open the generated dashboard in the default browser.")
    args = parser.parse_args()

    if not KEY or not SECRET:
        print("ERROR: ALPACA_API_KEY / ALPACA_SECRET_KEY missing in agent/.env")
        sys.exit(1)

    account = fetch_account()
    positions = fetch_positions()
    orders = fetch_orders(args.days)
    events = [net_order_event(order) for order in orders]
    flips = flip_closed_trades()
    history = fetch_portfolio_history(args.days)

    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    REPORT_FILE.write_text(render(account, positions, events, flips, history, args.days), encoding="utf-8")

    print(f"Dashboard written to: {REPORT_FILE}")
    if args.open:
        webbrowser.open(REPORT_FILE.as_uri())


if __name__ == "__main__":
    main()

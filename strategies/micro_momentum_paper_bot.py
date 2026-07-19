#!/usr/bin/env python3
"""Isolated $1,000 paper ledger for the half-deployed momentum lane.

This module deliberately has no broker order client. ``--execute-paper`` only
updates a local virtual ledger using point-in-time Alpaca quotes and modeled
friction. The lane is evaluated independently from the repository's much
larger shared Alpaca paper account.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import sys
import urllib.parse
import urllib.request
from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo


ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.momentum_shadow_logger import compute_current_signal


NY = ZoneInfo("America/New_York")
VIBE_HOME = Path.home() / ".vibe-trading"
DEFAULT_STATE = VIBE_HOME / "state" / "micro-momentum-paper.json"
DEFAULT_REPORT = VIBE_HOME / "reports" / "micro-momentum-paper.json"
DEFAULT_LOG = ROOT / "data" / "micro_momentum_paper_log.jsonl"
ENV_PATH = ROOT / "agent" / ".env"


@dataclass(frozen=True)
class PaperConfig:
    initial_cash: float = 1000.0
    deployment_fraction: float = 0.50
    top_n: int = 2
    modeled_cost_bps: float = 6.0
    max_drawdown_pct: float = 8.0
    minimum_order_notional: float = 5.0
    quote_max_age_minutes: float = 20.0


def _finite_positive(value: Any) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if math.isfinite(parsed) and parsed > 0 else None


def initial_state(config: PaperConfig = PaperConfig()) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "mode": "isolated_virtual_paper",
        "initial_cash": round(config.initial_cash, 2),
        "cash": round(config.initial_cash, 2),
        "positions": {},
        "high_water_mark": round(config.initial_cash, 2),
        "last_equity": round(config.initial_cash, 2),
        "max_observed_drawdown_pct": 0.0,
        "last_rebalance_week": None,
        "last_signal_asof": None,
        "halted": False,
        "halt_reason": None,
        "weekly_decisions": [],
        "fills": [],
    }


def load_state(path: Path, config: PaperConfig = PaperConfig()) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        return initial_state(config)
    if not isinstance(payload, dict) or payload.get("mode") != "isolated_virtual_paper":
        raise ValueError(f"Invalid micro momentum state: {path}")
    return payload


def save_state(path: Path, state: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(state, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temp.replace(path)


def _credentials() -> tuple[str, str]:
    values = {
        "ALPACA_API_KEY": os.environ.get("ALPACA_API_KEY", "").strip(),
        "ALPACA_SECRET_KEY": os.environ.get("ALPACA_SECRET_KEY", "").strip(),
    }
    if ENV_PATH.exists() and not all(values.values()):
        for raw in ENV_PATH.read_text(encoding="utf-8-sig").splitlines():
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            if key.strip() in values and not values[key.strip()]:
                values[key.strip()] = value.strip()
    if not all(values.values()):
        raise RuntimeError("ALPACA_API_KEY and ALPACA_SECRET_KEY are required for paper quotes")
    return values["ALPACA_API_KEY"], values["ALPACA_SECRET_KEY"]


def _request_json(url: str) -> dict[str, Any]:
    key, secret = _credentials()
    request = urllib.request.Request(
        url,
        headers={"APCA-API-KEY-ID": key, "APCA-API-SECRET-KEY": secret},
    )
    with urllib.request.urlopen(request, timeout=15) as response:
        payload = json.loads(response.read().decode("utf-8"))
    if not isinstance(payload, dict):
        raise RuntimeError(f"Unexpected Alpaca response from {url}")
    return payload


def fetch_market_clock() -> dict[str, Any]:
    payload = _request_json("https://paper-api.alpaca.markets/v2/clock")
    return {
        "is_open": bool(payload.get("is_open")),
        "timestamp": payload.get("timestamp"),
        "next_open": payload.get("next_open"),
        "next_close": payload.get("next_close"),
    }


def fetch_point_in_time_quotes(
    symbols: list[str],
    *,
    now: datetime | None = None,
    max_age_minutes: float = 20.0,
) -> tuple[dict[str, float], dict[str, Any]]:
    if not symbols:
        return {}, {}
    query = urllib.parse.urlencode({"symbols": ",".join(sorted(set(symbols))), "feed": "iex"})
    payload = _request_json(f"https://data.alpaca.markets/v2/stocks/quotes/latest?{query}")
    rows = payload.get("quotes") or {}
    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    prices: dict[str, float] = {}
    evidence: dict[str, Any] = {}
    for symbol in sorted(set(symbols)):
        row = rows.get(symbol) or {}
        bid = _finite_positive(row.get("bp"))
        ask = _finite_positive(row.get("ap"))
        timestamp = row.get("t")
        if bid is None or ask is None or ask < bid or not timestamp:
            raise RuntimeError(f"No executable bid/ask quote for {symbol}")
        quoted_at = datetime.fromisoformat(str(timestamp).replace("Z", "+00:00"))
        age_minutes = max(0.0, (current.astimezone(timezone.utc) - quoted_at.astimezone(timezone.utc)).total_seconds() / 60.0)
        if age_minutes > max_age_minutes:
            raise RuntimeError(f"Stale quote for {symbol}: {age_minutes:.1f} minutes old")
        midpoint = (bid + ask) / 2.0
        prices[symbol] = midpoint
        evidence[symbol] = {
            "bid": round(bid, 6),
            "ask": round(ask, 6),
            "midpoint": round(midpoint, 6),
            "quoted_at": quoted_at.isoformat(),
            "age_minutes": round(age_minutes, 3),
        }
    return prices, evidence


def mark_to_market(state: dict[str, Any], prices: dict[str, float]) -> dict[str, float]:
    position_value = 0.0
    for symbol, position in (state.get("positions") or {}).items():
        price = _finite_positive(prices.get(symbol))
        if price is None:
            raise ValueError(f"Missing mark for open position {symbol}")
        position_value += float(position.get("qty") or 0.0) * price
    cash = float(state.get("cash") or 0.0)
    equity = cash + position_value
    high_water = max(float(state.get("high_water_mark") or equity), equity)
    drawdown_pct = 0.0 if high_water <= 0 else max(0.0, (high_water - equity) / high_water * 100.0)
    return {
        "cash": cash,
        "position_value": position_value,
        "gross_exposure_pct": 0.0 if equity <= 0 else position_value / equity * 100.0,
        "equity": equity,
        "high_water_mark": high_water,
        "drawdown_pct": drawdown_pct,
    }


def target_notionals(
    holdings: list[str],
    equity: float,
    config: PaperConfig = PaperConfig(),
) -> dict[str, float]:
    selected = list(dict.fromkeys(holdings))[: config.top_n]
    if not selected or equity <= 0:
        return {}
    per_symbol = equity * config.deployment_fraction / len(selected)
    return {symbol: per_symbol for symbol in selected}


def build_orders(
    state: dict[str, Any],
    prices: dict[str, float],
    targets: dict[str, float],
    config: PaperConfig = PaperConfig(),
) -> list[dict[str, Any]]:
    symbols = sorted(set((state.get("positions") or {})) | set(targets))
    orders = []
    for symbol in symbols:
        price = _finite_positive(prices.get(symbol))
        if price is None:
            raise ValueError(f"Missing order price for {symbol}")
        current_qty = float((state.get("positions") or {}).get(symbol, {}).get("qty") or 0.0)
        current_notional = current_qty * price
        delta = float(targets.get(symbol, 0.0)) - current_notional
        if abs(delta) < config.minimum_order_notional:
            continue
        orders.append({
            "symbol": symbol,
            "side": "buy" if delta > 0 else "sell",
            "midpoint": price,
            "requested_notional": abs(delta),
        })
    return sorted(orders, key=lambda row: 0 if row["side"] == "sell" else 1)


def execute_virtual_orders(
    state: dict[str, Any],
    orders: list[dict[str, Any]],
    *,
    now: datetime,
    cost_bps: float,
) -> list[dict[str, Any]]:
    fills: list[dict[str, Any]] = []
    positions = state.setdefault("positions", {})
    for order in orders:
        symbol = str(order["symbol"])
        side = str(order["side"])
        midpoint = float(order["midpoint"])
        requested = float(order["requested_notional"])
        cost_rate = float(cost_bps) / 10_000.0
        fill_price = midpoint * (1.0 + cost_rate if side == "buy" else 1.0 - cost_rate)
        current = positions.get(symbol) or {"qty": 0.0, "average_cost": 0.0}
        current_qty = float(current.get("qty") or 0.0)
        if side == "sell":
            qty = min(current_qty, requested / midpoint)
            cash_change = qty * fill_price
            new_qty = current_qty - qty
            state["cash"] = float(state.get("cash") or 0.0) + cash_change
            if new_qty <= 1e-9:
                positions.pop(symbol, None)
            else:
                current["qty"] = new_qty
                positions[symbol] = current
        else:
            available = max(0.0, float(state.get("cash") or 0.0))
            spend = min(requested, available)
            qty = spend / fill_price
            cash_change = -(qty * fill_price)
            old_cost = current_qty * float(current.get("average_cost") or 0.0)
            new_qty = current_qty + qty
            state["cash"] = available + cash_change
            positions[symbol] = {
                "qty": new_qty,
                "average_cost": (old_cost + qty * fill_price) / new_qty,
            }
        fill = {
            "filled_at": now.isoformat(),
            "symbol": symbol,
            "side": side,
            "qty": round(qty, 8),
            "midpoint": round(midpoint, 6),
            "fill_price": round(fill_price, 6),
            "modeled_cost_bps": round(cost_bps, 3),
            "cash_change": round(cash_change, 6),
        }
        fills.append(fill)
        state.setdefault("fills", []).append(fill)
    return fills


def run_cycle(
    signal: dict[str, Any],
    prices: dict[str, float],
    state: dict[str, Any],
    *,
    market_open: bool,
    execute_paper: bool,
    now: datetime,
    config: PaperConfig = PaperConfig(),
) -> tuple[dict[str, Any], dict[str, Any]]:
    working = deepcopy(state)
    marks = mark_to_market(working, prices)
    working["last_equity"] = marks["equity"]
    working["high_water_mark"] = marks["high_water_mark"]
    working["max_observed_drawdown_pct"] = max(
        float(working.get("max_observed_drawdown_pct") or 0.0),
        marks["drawdown_pct"],
    )
    week_key = f"{now.astimezone(NY).isocalendar().year}-W{now.astimezone(NY).isocalendar().week:02d}"
    halted_now = bool(working.get("halted")) or marks["drawdown_pct"] >= config.max_drawdown_pct
    if halted_now:
        working["halted"] = True
        working["halt_reason"] = working.get("halt_reason") or f"drawdown_{marks['drawdown_pct']:.3f}_pct"
    holdings = [] if halted_now else list(signal.get("holdings") or [])
    targets = target_notionals(holdings, marks["equity"], config)
    orders = build_orders(working, prices, targets, config)
    due = working.get("last_rebalance_week") != week_key
    reason = "preview_only"
    fills: list[dict[str, Any]] = []
    state_changed = False
    if execute_paper and not market_open:
        reason = "market_closed_fail_closed"
    elif execute_paper and halted_now and orders:
        fills = execute_virtual_orders(working, orders, now=now, cost_bps=config.modeled_cost_bps)
        reason = "drawdown_halt_liquidated"
        state_changed = True
    elif execute_paper and not due:
        reason = "already_rebalanced_this_week"
        state_changed = True
    elif execute_paper:
        fills = execute_virtual_orders(working, orders, now=now, cost_bps=config.modeled_cost_bps)
        working["last_rebalance_week"] = week_key
        working["last_signal_asof"] = signal.get("signal_asof") or signal.get("date")
        working.setdefault("weekly_decisions", []).append({
            "week_key": week_key,
            "recorded_at": now.isoformat(),
            "signal_asof": signal.get("signal_asof") or signal.get("date"),
            "holdings": holdings,
            "pre_trade_equity": round(marks["equity"], 4),
        })
        reason = "weekly_rebalance_completed" if fills else "weekly_rebalance_no_orders"
        state_changed = True

    post_marks = mark_to_market(working, prices)
    working["last_equity"] = post_marks["equity"]
    working["high_water_mark"] = post_marks["high_water_mark"]
    working["max_observed_drawdown_pct"] = max(
        float(working.get("max_observed_drawdown_pct") or 0.0),
        post_marks["drawdown_pct"],
    )
    decision_count = len({row.get("week_key") for row in working.get("weekly_decisions", []) if row.get("week_key")})
    review_eligible = (
        decision_count >= 26
        and post_marks["equity"] > float(working.get("initial_cash") or config.initial_cash)
        and float(working.get("max_observed_drawdown_pct") or 0.0) <= config.max_drawdown_pct
        and not bool(working.get("halted"))
    )
    fingerprint = hashlib.sha256(json.dumps(targets, sort_keys=True).encode("utf-8")).hexdigest()[:16]
    report = {
        "provider": "micro_momentum_paper_bot",
        "generated_at": now.isoformat(),
        "mode": "isolated_virtual_paper",
        "broker_orders_enabled": False,
        "live_trading_enabled": False,
        "paper_ledger_mutation_requested": bool(execute_paper),
        "paper_ledger_changed": state_changed,
        "market_open": bool(market_open),
        "status": reason,
        "week_key": week_key,
        "signal_asof": signal.get("signal_asof") or signal.get("date"),
        "selected_holdings": holdings,
        "target_notionals": {key: round(value, 2) for key, value in targets.items()},
        "target_fingerprint": fingerprint,
        "orders": [{**row, "midpoint": round(float(row["midpoint"]), 6), "requested_notional": round(float(row["requested_notional"]), 2)} for row in orders],
        "fills": fills,
        "pre_trade": {key: round(value, 4) for key, value in marks.items()},
        "post_trade": {key: round(value, 4) for key, value in post_marks.items()},
        "risk": {
            "deployment_fraction": config.deployment_fraction,
            "cash_reserve_fraction": 1.0 - config.deployment_fraction,
            "max_drawdown_pct": config.max_drawdown_pct,
            "halted": bool(working.get("halted")),
            "halt_reason": working.get("halt_reason"),
        },
        "promotion": {
            "eligible_for_manual_review": review_eligible,
            "live_execution_automatic": False,
            "required_weekly_decisions": 26,
            "completed_weekly_decisions": decision_count,
            "reason": "Manual review is required after 26 point-in-time weekly decisions, positive net P&L, and drawdown at or below 8%.",
        },
        "evidence_boundary": "The 8% liquidation halt is a new paper overlay and was not included in the historical 21.25% result.",
    }
    return report, working


def append_log(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, sort_keys=True) + "\n")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--execute-paper", action="store_true", help="Mutate only the isolated local paper ledger")
    parser.add_argument("--state", type=Path, default=DEFAULT_STATE)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    parser.add_argument("--log", type=Path, default=DEFAULT_LOG)
    args = parser.parse_args()
    now = datetime.now(timezone.utc)
    signal = compute_current_signal()
    state = load_state(args.state)
    symbols = sorted(set(signal.get("holdings") or []) | set(state.get("positions") or {}))
    clock = fetch_market_clock()
    if clock["is_open"]:
        prices, quote_evidence = fetch_point_in_time_quotes(symbols, now=now)
    else:
        reference = signal.get("close_prices") or {}
        prices = {}
        quote_evidence = {}
        for symbol in symbols:
            price = _finite_positive(reference.get(symbol))
            if price is None:
                raise RuntimeError(f"No closed-market reference price for {symbol}")
            prices[symbol] = price
            quote_evidence[symbol] = {
                "midpoint": round(price, 6),
                "source": "latest_complete_daily_bar",
                "executable": False,
            }
    report, updated = run_cycle(
        signal,
        prices,
        state,
        market_open=bool(clock["is_open"]),
        execute_paper=args.execute_paper,
        now=now,
    )
    report["market_clock"] = clock
    report["quote_evidence"] = quote_evidence
    if report["paper_ledger_changed"]:
        save_state(args.state, updated)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    append_log(args.log, report)
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

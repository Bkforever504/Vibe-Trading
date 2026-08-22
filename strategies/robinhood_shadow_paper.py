#!/usr/bin/env python3
"""Local-only Robinhood options shadow ledger.

The input is an exported packet from Robinhood's official Trading MCP. This
module contains no HTTP client, credentials, MCP client, or broker order
method. ``--execute-paper`` mutates only a local JSON ledger.
"""
from __future__ import annotations

import argparse
import json
import math
from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


VIBE_HOME = Path.home() / ".vibe-trading"
DEFAULT_STATE = VIBE_HOME / "state" / "robinhood-options-shadow.json"
DEFAULT_REPORT = VIBE_HOME / "reports" / "robinhood-options-shadow.json"

OPEN_SIDES = {"buy_to_open", "sell_to_open"}


@dataclass(frozen=True)
class ShadowConfig:
    initial_cash: float = 1000.0
    max_risk_per_trade_pct: float = 0.02
    max_total_open_risk_pct: float = 0.06
    max_drawdown_pct: float = 8.0
    quote_max_age_seconds: float = 90.0
    contract_multiplier: int = 100


def _number(value: Any) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        raise ValueError(f"Expected finite number, received {value!r}") from None
    if not math.isfinite(parsed):
        raise ValueError(f"Expected finite number, received {value!r}")
    return parsed


def _timestamp(value: Any) -> datetime:
    if not value:
        raise ValueError("Missing quote timestamp")
    parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def initial_state(config: ShadowConfig = ShadowConfig()) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "mode": "robinhood_mcp_local_shadow",
        "initial_cash": config.initial_cash,
        "cash": config.initial_cash,
        "positions": {},
        "closed_positions": [],
        "realized_pnl": 0.0,
        "high_water_mark": config.initial_cash,
        "max_observed_drawdown_pct": 0.0,
        "halted": False,
        "halt_reason": None,
    }


def load_state(path: Path, config: ShadowConfig = ShadowConfig()) -> dict[str, Any]:
    if not path.exists():
        return initial_state(config)
    payload = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(payload, dict) or payload.get("mode") != "robinhood_mcp_local_shadow":
        raise ValueError(f"Invalid Robinhood shadow state: {path}")
    return payload


def save_state(path: Path, state: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(state, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temp.replace(path)


def validate_packet(
    packet: dict[str, Any],
    *,
    now: datetime,
    config: ShadowConfig = ShadowConfig(),
    require_review: bool,
) -> list[dict[str, Any]]:
    if packet.get("source") != "robinhood_official_trading_mcp":
        raise ValueError("Packet must come from robinhood_official_trading_mcp")
    if not packet.get("packet_id"):
        raise ValueError("Missing packet_id")
    if require_review:
        review = packet.get("review") or {}
        if review.get("source") != "robinhood_review_option_order" or review.get("status") != "ok":
            raise ValueError("Robinhood option review evidence is required")
        if review.get("warnings"):
            raise ValueError("Robinhood option review returned warnings")
    legs = packet.get("legs") or []
    if not isinstance(legs, list) or not legs:
        raise ValueError("At least one option leg is required")
    normalized = []
    current = now.astimezone(timezone.utc)
    for raw in legs:
        side = str(raw.get("side") or "")
        if side not in OPEN_SIDES:
            raise ValueError(f"Unsupported opening side: {side}")
        symbol = str(raw.get("symbol") or "").strip().upper()
        quantity = int(_number(raw.get("quantity", 1)))
        bid = _number(raw.get("bid"))
        ask = _number(raw.get("ask"))
        quoted_at = _timestamp(raw.get("quoted_at"))
        age = (current - quoted_at).total_seconds()
        if not symbol or quantity <= 0:
            raise ValueError("Each leg requires a symbol and positive integer quantity")
        if bid < 0 or ask <= 0 or ask < bid:
            raise ValueError(f"Invalid executable quote for {symbol}")
        if age < -5 or age > config.quote_max_age_seconds:
            raise ValueError(f"Stale or future quote for {symbol}: {age:.1f} seconds")
        normalized.append({
            "symbol": symbol,
            "side": side,
            "quantity": quantity,
            "bid": bid,
            "ask": ask,
            "quoted_at": quoted_at.isoformat(),
            "quote_age_seconds": round(age, 3),
        })
    return normalized


def opening_cashflow(legs: list[dict[str, Any]], multiplier: int = 100) -> tuple[float, list[dict[str, Any]]]:
    cashflow = 0.0
    fills = []
    for leg in legs:
        side = leg["side"]
        price = leg["ask"] if side == "buy_to_open" else leg["bid"]
        signed = -1.0 if side == "buy_to_open" else 1.0
        leg_cashflow = signed * price * leg["quantity"] * multiplier
        cashflow += leg_cashflow
        fills.append({
            "symbol": leg["symbol"],
            "side": side,
            "quantity": leg["quantity"],
            "fill_price": round(price, 4),
            "cashflow": round(leg_cashflow, 2),
            "fill_model": "buy_at_ask_sell_at_bid",
        })
    return round(cashflow, 2), fills


def closing_cashflow(
    opening_legs: list[dict[str, Any]],
    quote_legs: list[dict[str, Any]],
    multiplier: int = 100,
) -> tuple[float, list[dict[str, Any]]]:
    quotes = {row["symbol"]: row for row in quote_legs}
    cashflow = 0.0
    fills = []
    for opened in opening_legs:
        quote = quotes.get(opened["symbol"])
        if quote is None:
            raise ValueError(f"Missing close quote for {opened['symbol']}")
        if opened["side"] == "buy_to_open":
            side, price, signed = "sell_to_close", quote["bid"], 1.0
        else:
            side, price, signed = "buy_to_close", quote["ask"], -1.0
        leg_cashflow = signed * price * opened["quantity"] * multiplier
        cashflow += leg_cashflow
        fills.append({
            "symbol": opened["symbol"],
            "side": side,
            "quantity": opened["quantity"],
            "fill_price": round(price, 4),
            "cashflow": round(leg_cashflow, 2),
            "fill_model": "buy_at_ask_sell_at_bid",
        })
    return round(cashflow, 2), fills


def _accounting(state: dict[str, Any], marks: dict[str, float] | None = None) -> dict[str, float]:
    unrealized = sum((marks or {}).values())
    equity = float(state.get("cash") or 0.0) + unrealized
    high_water = max(float(state.get("high_water_mark") or equity), equity)
    drawdown = 0.0 if high_water <= 0 else max(0.0, (high_water - equity) / high_water * 100.0)
    return {
        "cash": round(float(state.get("cash") or 0.0), 2),
        "unrealized_close_value": round(unrealized, 2),
        "equity": round(equity, 2),
        "high_water_mark": round(high_water, 2),
        "drawdown_pct": round(drawdown, 4),
    }


def open_shadow(
    packet: dict[str, Any],
    state: dict[str, Any],
    *,
    now: datetime,
    execute_paper: bool,
    config: ShadowConfig = ShadowConfig(),
) -> tuple[dict[str, Any], dict[str, Any]]:
    working = deepcopy(state)
    packet_id = str(packet.get("packet_id") or "")
    if packet_id in (working.get("positions") or {}):
        return _report("duplicate_packet", packet_id, [], _accounting(working), working), working
    legs = validate_packet(packet, now=now, config=config, require_review=True)
    max_loss = _number(packet.get("max_loss_dollars"))
    if max_loss <= 0:
        raise ValueError("max_loss_dollars must be positive")
    entry_cashflow, fills = opening_cashflow(legs, config.contract_multiplier)
    if max_loss + 1e-9 < max(0.0, -entry_cashflow):
        raise ValueError("Declared max loss is below executable entry debit")
    accounting = _accounting(working)
    risk_limit = accounting["equity"] * config.max_risk_per_trade_pct
    total_limit = accounting["equity"] * config.max_total_open_risk_pct
    open_risk = sum(float(row.get("max_loss_dollars") or 0.0) for row in (working.get("positions") or {}).values())
    blockers = []
    if working.get("halted"):
        blockers.append("ledger_halted")
    if max_loss > risk_limit + 1e-9:
        blockers.append("per_trade_risk_budget_exceeded")
    if open_risk + max_loss > total_limit + 1e-9:
        blockers.append("total_open_risk_budget_exceeded")
    if entry_cashflow < 0 and abs(entry_cashflow) > accounting["cash"] + 1e-9:
        blockers.append("insufficient_shadow_cash")
    if blockers:
        report = _report("blocked", packet_id, [], accounting, working, blockers=blockers)
        report["risk"] = {"max_loss_dollars": max_loss, "per_trade_limit": round(risk_limit, 2), "total_open_limit": round(total_limit, 2)}
        return report, working
    status = "preview_only"
    if execute_paper:
        working["cash"] = round(float(working.get("cash") or 0.0) + entry_cashflow, 2)
        working.setdefault("positions", {})[packet_id] = {
            "packet_id": packet_id,
            "strategy": packet.get("strategy"),
            "underlying": packet.get("underlying"),
            "opened_at": now.astimezone(timezone.utc).isoformat(),
            "entry_cashflow": entry_cashflow,
            "max_loss_dollars": max_loss,
            "profit_target": packet.get("profit_target"),
            "stop_policy": packet.get("stop_policy"),
            "leader_evidence": packet.get("leader_evidence"),
            "legs": legs,
            "fills": fills,
        }
        status = "paper_opened"
    post = _accounting(working, {packet_id: -entry_cashflow} if execute_paper else None)
    working["high_water_mark"] = post["high_water_mark"]
    report = _report(status, packet_id, fills if execute_paper else [], post, working)
    report["risk"] = {"max_loss_dollars": max_loss, "per_trade_limit": round(risk_limit, 2), "total_open_limit": round(total_limit, 2)}
    return report, working


def close_shadow(
    packet: dict[str, Any],
    state: dict[str, Any],
    *,
    now: datetime,
    execute_paper: bool,
    config: ShadowConfig = ShadowConfig(),
) -> tuple[dict[str, Any], dict[str, Any]]:
    working = deepcopy(state)
    packet_id = str(packet.get("packet_id") or "")
    position = (working.get("positions") or {}).get(packet_id)
    if position is None:
        raise ValueError(f"Unknown open packet_id: {packet_id}")
    quote_legs = validate_packet(packet, now=now, config=config, require_review=False)
    close_cash, fills = closing_cashflow(position["legs"], quote_legs, config.contract_multiplier)
    pnl = round(float(position["entry_cashflow"]) + close_cash, 2)
    status = "preview_only"
    if execute_paper:
        working["cash"] = round(float(working.get("cash") or 0.0) + close_cash, 2)
        closed = {**position, "closed_at": now.astimezone(timezone.utc).isoformat(), "close_cashflow": close_cash, "pnl": pnl, "close_reason": packet.get("close_reason"), "close_fills": fills}
        working.setdefault("closed_positions", []).append(closed)
        working["positions"].pop(packet_id, None)
        working["realized_pnl"] = round(float(working.get("realized_pnl") or 0.0) + pnl, 2)
        status = "paper_closed"
    accounting = _accounting(working)
    working["high_water_mark"] = accounting["high_water_mark"]
    working["max_observed_drawdown_pct"] = max(float(working.get("max_observed_drawdown_pct") or 0.0), accounting["drawdown_pct"])
    if accounting["drawdown_pct"] >= config.max_drawdown_pct:
        working["halted"] = True
        working["halt_reason"] = f"drawdown_{accounting['drawdown_pct']:.4f}_pct"
    report = _report(status, packet_id, fills if execute_paper else [], accounting, working)
    report["pnl"] = pnl
    return report, working


def _report(status: str, packet_id: str, fills: list[dict[str, Any]], accounting: dict[str, float], state: dict[str, Any], *, blockers: list[str] | None = None) -> dict[str, Any]:
    return {
        "provider": "robinhood_shadow_paper",
        "mode": "local_shadow_only",
        "execution_enabled": False,
        "can_submit_orders": False,
        "broker_client_present": False,
        "status": status,
        "packet_id": packet_id,
        "blockers": blockers or [],
        "fills": fills,
        "accounting": accounting,
        "open_position_count": len(state.get("positions") or {}),
        "halted": bool(state.get("halted")),
        "warnings": [
            "Paper fills use Robinhood executable bid/ask snapshots and are not broker fills.",
            "No function in this module can submit, cancel, or replace an order.",
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("open", "close"))
    parser.add_argument("packet", type=Path)
    parser.add_argument("--state", type=Path, default=DEFAULT_STATE)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    parser.add_argument("--execute-paper", action="store_true")
    args = parser.parse_args()
    now = datetime.now(timezone.utc)
    packet = json.loads(args.packet.read_text(encoding="utf-8-sig"))
    state = load_state(args.state)
    runner = open_shadow if args.action == "open" else close_shadow
    report, updated = runner(packet, state, now=now, execute_paper=args.execute_paper)
    if args.execute_paper and report["status"] in {"paper_opened", "paper_closed"}:
        save_state(args.state, updated)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

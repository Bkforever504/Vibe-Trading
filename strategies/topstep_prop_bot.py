#!/usr/bin/env python3
"""Separate Topstep-style futures prop bot arena.

This module is paper/shadow infrastructure. It does not connect to Topstep or
submit live orders. The first strategy is intentionally simple and testable:
opening-range breakout with VWAP confirmation on MNQ/MES-style futures.
"""
from __future__ import annotations

import argparse
import csv
import json
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Literal

try:
    from strategies.prop_rule_gate import (
        AccountState,
        PropGateDecision,
        ProposedTrade,
        evaluate_prop_trade,
        load_rule_profile,
    )
except ModuleNotFoundError:
    from prop_rule_gate import AccountState, PropGateDecision, ProposedTrade, evaluate_prop_trade, load_rule_profile

Side = Literal["buy", "sell"]


@dataclass(frozen=True)
class Candle:
    timestamp: datetime
    open: float
    high: float
    low: float
    close: float
    volume: int


@dataclass(frozen=True)
class FuturesContract:
    symbol: str
    point_value: float
    tick_size: float


@dataclass(frozen=True)
class OpeningRangeConfig:
    range_minutes: int = 15
    min_breakout_points: float = 2.0
    reward_risk: float = 1.5
    max_risk_per_trade: float = 100.0
    max_contracts: int = 2


@dataclass(frozen=True)
class PropSignal:
    symbol: str
    strategy: str
    side: Side
    entry: float
    stop: float
    target: float
    opening_range_high: float
    opening_range_low: float
    vwap: float
    confidence: float

    @property
    def risk_points(self) -> float:
        return abs(self.entry - self.stop)

    def evaluate_rules(
        self,
        *,
        profile: dict,
        account: AccountState,
        contracts: int,
        running_on_vps: bool,
    ) -> PropGateDecision:
        return evaluate_prop_trade(
            profile,
            ProposedTrade(
                symbol=self.symbol,
                side=self.side,
                contracts=contracts,
                risk_dollars=self.risk_points * contracts * contract_for_symbol(self.symbol).point_value,
                automated=True,
                running_on_vps=running_on_vps,
            ),
            account,
        )


def contract_for_symbol(symbol: str) -> FuturesContract:
    root = symbol.upper()
    if root.startswith("MNQ"):
        return FuturesContract("MNQ", point_value=2.0, tick_size=0.25)
    if root.startswith("NQ"):
        return FuturesContract("NQ", point_value=20.0, tick_size=0.25)
    if root.startswith("MES"):
        return FuturesContract("MES", point_value=5.0, tick_size=0.25)
    if root.startswith("ES"):
        return FuturesContract("ES", point_value=50.0, tick_size=0.25)
    raise ValueError(f"Unsupported futures symbol for prop bot: {symbol}")


def load_candles_csv(path: Path) -> list[Candle]:
    candles: list[Candle] = []
    with path.open("r", newline="", encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            candles.append(
                Candle(
                    timestamp=datetime.fromisoformat(row["timestamp"]),
                    open=float(row["open"]),
                    high=float(row["high"]),
                    low=float(row["low"]),
                    close=float(row["close"]),
                    volume=int(float(row.get("volume") or 0)),
                )
            )
    return candles


def session_vwap(candles: list[Candle]) -> float:
    volume_sum = sum(max(0, c.volume) for c in candles)
    if volume_sum <= 0:
        return candles[-1].close if candles else 0.0
    typical_value_sum = sum(((c.high + c.low + c.close) / 3) * c.volume for c in candles)
    return typical_value_sum / volume_sum


def build_opening_range_signal(candles: list[Candle], config: OpeningRangeConfig, symbol: str = "MNQ") -> PropSignal | None:
    if len(candles) <= config.range_minutes:
        return None

    opening = candles[: config.range_minutes]
    trigger = candles[config.range_minutes]
    range_high = max(c.high for c in opening)
    range_low = min(c.low for c in opening)
    vwap = session_vwap(candles[: config.range_minutes + 1])

    long_breakout = trigger.close >= range_high + config.min_breakout_points and trigger.close > vwap
    short_breakout = trigger.close <= range_low - config.min_breakout_points and trigger.close < vwap

    if not long_breakout and not short_breakout:
        return None

    if long_breakout:
        side: Side = "buy"
        entry = trigger.close
        stop = range_low
        target = entry + (entry - stop) * config.reward_risk
    else:
        side = "sell"
        entry = trigger.close
        stop = range_high
        target = entry - (stop - entry) * config.reward_risk

    return PropSignal(
        symbol=symbol.upper(),
        strategy="opening_range_vwap",
        side=side,
        entry=entry,
        stop=stop,
        target=target,
        opening_range_high=range_high,
        opening_range_low=range_low,
        vwap=round(vwap, 4),
        confidence=0.65,
    )


def build_first_pullback_signal(
    candles: list[Candle],
    config: OpeningRangeConfig,
    symbol: str = "MNQ",
    *,
    pullback_tolerance_ticks: int = 4,
    pullback_stop_ticks: int = 8,
    max_scan_candles: int = 30,
    require_bos_confirm: bool = False,
) -> tuple[PropSignal, int] | None:
    """ORB direction + first pullback-to-range-level entry.

    Returns (signal, entry_candle_index) or None.
    Stop is pullback_stop_ticks below range_high (long) or above range_low (short).
    """
    if len(candles) <= config.range_minutes + 1:
        return None

    opening = candles[: config.range_minutes]
    trigger = candles[config.range_minutes]
    range_high = max(c.high for c in opening)
    range_low = min(c.low for c in opening)
    vwap = session_vwap(candles[: config.range_minutes + 1])

    long_breakout = trigger.close >= range_high + config.min_breakout_points and trigger.close > vwap
    short_breakout = trigger.close <= range_low - config.min_breakout_points and trigger.close < vwap

    if not long_breakout and not short_breakout:
        return None

    side: Side = "buy" if long_breakout else "sell"
    contract = contract_for_symbol(symbol)
    tolerance = pullback_tolerance_ticks * contract.tick_size
    breakout_high = trigger.high
    breakout_low = trigger.low
    bos_confirmed = not require_bos_confirm

    scan_start = config.range_minutes + 1
    scan_end = min(len(candles), scan_start + max_scan_candles)

    for idx in range(scan_start, scan_end):
        c = candles[idx]
        if side == "buy":
            touched = c.low <= range_high + tolerance
            held = c.close > range_high - tolerance
            if touched and held and bos_confirmed:
                entry = c.close
                stop = range_high - pullback_stop_ticks * contract.tick_size
                stop_dist = entry - stop
                if stop_dist <= 0:
                    continue
                target = entry + stop_dist * config.reward_risk
                return PropSignal(
                    symbol=symbol.upper(),
                    strategy="first_pullback",
                    side=side,
                    entry=entry,
                    stop=stop,
                    target=target,
                    opening_range_high=range_high,
                    opening_range_low=range_low,
                    vwap=round(vwap, 4),
                    confidence=0.70,
                ), idx
            if c.high > breakout_high:
                bos_confirmed = True
        else:
            touched = c.high >= range_low - tolerance
            held = c.close < range_low + tolerance
            if touched and held and bos_confirmed:
                entry = c.close
                stop = range_low + pullback_stop_ticks * contract.tick_size
                stop_dist = stop - entry
                if stop_dist <= 0:
                    continue
                target = entry - stop_dist * config.reward_risk
                return PropSignal(
                    symbol=symbol.upper(),
                    strategy="first_pullback",
                    side=side,
                    entry=entry,
                    stop=stop,
                    target=target,
                    opening_range_high=range_high,
                    opening_range_low=range_low,
                    vwap=round(vwap, 4),
                    confidence=0.70,
                ), idx
            if c.low < breakout_low:
                bos_confirmed = True

    return None


def size_contracts(
    *,
    entry: float,
    stop: float,
    contract: FuturesContract,
    risk_budget: float,
    max_contracts: int,
) -> int:
    risk_per_contract = abs(entry - stop) * contract.point_value
    if risk_per_contract <= 0:
        return 0
    return max(0, min(max_contracts, int(risk_budget // risk_per_contract)))


def evaluate_csv_setup(
    *,
    csv_path: Path,
    profile_path: Path,
    symbol: str,
    account: AccountState,
    config: OpeningRangeConfig,
    running_on_vps: bool = False,
) -> dict:
    candles = load_candles_csv(csv_path)
    signal = build_opening_range_signal(candles, config, symbol=symbol)
    if signal is None:
        return {"status": "no_signal", "symbol": symbol.upper(), "strategy": "opening_range_vwap"}

    contract = contract_for_symbol(symbol)
    contracts = size_contracts(
        entry=signal.entry,
        stop=signal.stop,
        contract=contract,
        risk_budget=config.max_risk_per_trade,
        max_contracts=config.max_contracts,
    )
    if contracts <= 0:
        return {"status": "blocked", "reason": "risk_budget_too_small", "signal": asdict(signal)}

    profile = load_rule_profile(profile_path)
    decision = signal.evaluate_rules(profile=profile, account=account, contracts=contracts, running_on_vps=running_on_vps)
    return {
        "status": "paper_order_ready" if decision.allowed else "blocked",
        "mode": "paper_only",
        "contracts": contracts,
        "contract": asdict(contract),
        "signal": asdict(signal),
        "rule_gate": asdict(decision),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Topstep-style futures prop bot paper scanner")
    parser.add_argument("--csv", type=Path, required=True, help="Minute candle CSV with timestamp,open,high,low,close,volume")
    parser.add_argument("--profile", type=Path, default=Path("rules/prop_firms/topstep_topstepx_api.json"))
    parser.add_argument("--symbol", default="MNQ")
    parser.add_argument("--equity", type=float, default=50_000)
    parser.add_argument("--start-equity", type=float, default=50_000)
    parser.add_argument("--day-pnl", type=float, default=0)
    parser.add_argument("--drawdown-remaining", type=float, default=2_000)
    parser.add_argument("--range-minutes", type=int, default=15)
    parser.add_argument("--min-breakout-points", type=float, default=2.0)
    parser.add_argument("--risk", type=float, default=100)
    parser.add_argument("--max-contracts", type=int, default=2)
    parser.add_argument("--vps", action="store_true")
    args = parser.parse_args()

    result = evaluate_csv_setup(
        csv_path=args.csv,
        profile_path=args.profile,
        symbol=args.symbol,
        account=AccountState(
            equity=args.equity,
            start_equity=args.start_equity,
            day_pnl=args.day_pnl,
            trailing_drawdown_remaining=args.drawdown_remaining,
        ),
        config=OpeningRangeConfig(
            range_minutes=args.range_minutes,
            min_breakout_points=args.min_breakout_points,
            max_risk_per_trade=args.risk,
            max_contracts=args.max_contracts,
        ),
        running_on_vps=args.vps,
    )
    print(json.dumps(result, indent=2, sort_keys=True, default=str))


if __name__ == "__main__":
    main()

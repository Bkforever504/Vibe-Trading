#!/usr/bin/env python3
"""Paper forward-tracker for the three passing edge lanes.

Lanes: momentum rotation (frozen 2024 candidate), SPY turn-of-month,
PEAD long-only proxy. Logs point-in-time signals and resolves outcomes.
Research only - never places orders.
"""
from __future__ import annotations

import json
import sys
import warnings
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from research.momentum_rotation_backtest import _momentum_signal, _normalize_position

STATE_PATH = ROOT / "data" / "edge_forward_state.json"
LOG_PATH = ROOT / "data" / "edge_forward_log.jsonl"
NY = ZoneInfo("America/New_York")

MOMENTUM_SYMBOLS = ["SPY", "QQQ", "GLD", "XLE", "TLT", "IWM", "XLK", "XLV", "XLF", "XLI"]
MOMENTUM_LOOKBACK_DAYS = 12 * 21
MOMENTUM_TOP_N = 2
MOMENTUM_REBALANCE_DAYS = 5
MOMENTUM_DATA_START = "2015-01-01"
MOMENTUM_STRATEGY_VERSION = "momentum-12m-5d-top2-canonical-phase-v2"
PEAD_UNIVERSE = (
    "AAPL MSFT NVDA AMZN GOOGL META TSLA AVGO JPM V UNH XOM WMT JNJ PG MA HD "
    "COST ORCL BAC KO PEP MRK ADBE CRM AMD NFLX DIS CSCO INTC"
).split()
PEAD_REACTION_MIN = 0.03
PEAD_HOLD_DAYS = 20


def now_iso() -> str:
    return datetime.now(NY).isoformat(timespec="seconds")


def log_event(event: dict) -> None:
    event = {"ts": now_iso(), **event}
    with LOG_PATH.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(event) + "\n")
    print(json.dumps(event))


def load_state() -> dict:
    if STATE_PATH.exists():
        return json.loads(STATE_PATH.read_text(encoding="utf-8"))
    return {
        "momentum": {"strategy_version": MOMENTUM_STRATEGY_VERSION, "position": None},
        "tom": {"open": None},
        "pead": {"open": []},
    }


def save_state(state: dict) -> None:
    STATE_PATH.write_text(json.dumps(state, indent=2) + "\n", encoding="utf-8")


def fetch_closes(symbols: list[str], start: str) -> pd.DataFrame:
    import yfinance as yf

    frames = {}
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        for symbol in symbols:
            df = yf.download(symbol, start=start, progress=False, auto_adjust=True)
            df.columns = [c.lower() if isinstance(c, str) else c[0].lower() for c in df.columns]
            frames[symbol] = df["close"]
    return pd.DataFrame(frames).dropna()


def momentum_snapshot(closes: pd.DataFrame) -> tuple[tuple[str, ...], str]:
    """Return the exact frozen signal and its most recent scheduled rebalance date."""
    signal = _momentum_signal(
        closes,
        lookback_days=MOMENTUM_LOOKBACK_DAYS,
        rebalance_days=MOMENTUM_REBALANCE_DAYS,
        top_n=MOMENTUM_TOP_N,
    )
    target = _normalize_position(signal.iloc[-1]) or ()
    last_index = MOMENTUM_LOOKBACK_DAYS + (
        (len(closes) - 1 - MOMENTUM_LOOKBACK_DAYS) // MOMENTUM_REBALANCE_DAYS
    ) * MOMENTUM_REBALANCE_DAYS
    return target, str(closes.index[last_index].date())


def _migrate_momentum_lane(lane: dict) -> None:
    if lane.get("strategy_version") == MOMENTUM_STRATEGY_VERSION and "position" in lane:
        return
    for symbol, entry in lane.get("holdings", {}).items():
        log_event({
            "lane": "momentum",
            "action": "invalidated",
            "symbol": symbol,
            "entry_date": entry.get("date"),
            "entry_price": entry.get("price"),
            "reason": "tracker_rebalance_phase_did_not_match_frozen_backtest",
        })
    lane.clear()
    lane.update({"strategy_version": MOMENTUM_STRATEGY_VERSION, "position": None})


def run_momentum(state: dict) -> None:
    # Starting in 2015 preserves the exact rebalance phase used by frozen validation.
    closes = fetch_closes(MOMENTUM_SYMBOLS, MOMENTUM_DATA_START)
    lane = state["momentum"]
    _migrate_momentum_lane(lane)
    target, rebalance_date = momentum_snapshot(closes)
    today = str(closes.index[-1].date())
    prices = closes.iloc[-1]
    current = lane.get("position")
    current_symbols = tuple(current["symbols"]) if current else ()
    lane_was_initialized = bool(lane.get("signal_date"))

    if current_symbols != target:
        if current:
            leg_pnl = [
                float(prices[symbol] / current["prices"][symbol] - 1.0) * 100.0
                for symbol in current_symbols
            ]
            log_event({
                "lane": "momentum",
                "action": "exit",
                "symbols": list(current_symbols),
                "entry_date": current["date"],
                "entry_prices": current["prices"],
                "exit_prices": {s: round(float(prices[s]), 2) for s in current_symbols},
                "pnl_pct": round(sum(leg_pnl) / len(leg_pnl), 3),
                "eligible_for_gate": current.get("eligible_for_gate", True),
            })
        if target:
            lane["position"] = {
                "symbols": list(target),
                "date": today,
                "prices": {s: round(float(prices[s]), 2) for s in target},
                # A migration starts mid-holding-period, so its first outcome is diagnostic only.
                "eligible_for_gate": current is not None or lane_was_initialized,
            }
            log_event({
                "lane": "momentum",
                "action": "entry",
                "symbols": list(target),
                "prices": lane["position"]["prices"],
                "eligible_for_gate": lane["position"]["eligible_for_gate"],
            })
        else:
            lane["position"] = None
    lane["signal_date"] = today
    lane["last_rebalance"] = rebalance_date


def tom_calendar(today: pd.Timestamp) -> tuple[bool, bool]:
    import pandas_market_calendars as mcal

    nyse = mcal.get_calendar("NYSE")
    schedule = nyse.schedule(start_date=today - pd.Timedelta(days=45), end_date=today + pd.Timedelta(days=45))
    days = schedule.index.normalize()
    month = today.to_period("M")
    this_month = [d for d in days if d.to_period("M") == month]
    next_month = [d for d in days if d.to_period("M") == month + 1]
    is_entry = len(this_month) >= 5 and today == this_month[-5]
    is_exit = len(this_month) >= 3 and today == this_month[2]
    return is_entry, is_exit


def run_tom(state: dict) -> None:
    closes = fetch_closes(["SPY"], "2026-01-01")["SPY"]
    today = closes.index[-1].normalize()
    price = round(float(closes.iloc[-1]), 2)
    is_entry, is_exit = tom_calendar(today)
    lane = state["tom"]
    if is_exit and lane["open"]:
        pnl = (price / lane["open"]["price"] - 1.0) * 100.0
        log_event({"lane": "tom", "action": "exit", "symbol": "SPY",
                   "entry_date": lane["open"]["date"], "entry_price": lane["open"]["price"],
                   "exit_price": price, "pnl_pct": round(pnl, 3)})
        lane["open"] = None
    if is_entry and not lane["open"]:
        lane["open"] = {"date": str(today.date()), "price": price}
        log_event({"lane": "tom", "action": "entry", "symbol": "SPY", "price": price})


def run_pead(state: dict) -> None:
    import yfinance as yf

    closes = fetch_closes(PEAD_UNIVERSE, "2026-01-01")
    index = closes.index
    lane = state["pead"]
    still_open = []
    for position in lane["open"]:
        entry_loc = index.searchsorted(pd.Timestamp(position["date"]))
        if len(index) - 1 - entry_loc >= PEAD_HOLD_DAYS:
            exit_loc = entry_loc + PEAD_HOLD_DAYS
            exit_price = round(float(closes[position["symbol"]].iloc[exit_loc]), 2)
            pnl = (exit_price / position["price"] - 1.0) * 100.0
            log_event({"lane": "pead", "action": "exit", "symbol": position["symbol"],
                       "entry_date": position["date"], "entry_price": position["price"],
                       "exit_price": exit_price, "pnl_pct": round(pnl, 3)})
        else:
            still_open.append(position)
    lane["open"] = still_open
    open_symbols = {p["symbol"] for p in lane["open"]}
    daily = closes.pct_change()
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        for symbol in PEAD_UNIVERSE:
            if symbol in open_symbols:
                continue
            try:
                earnings = yf.Ticker(symbol).get_earnings_dates(limit=8)
            except Exception:
                continue
            if earnings is None or earnings.empty:
                continue
            for stamp in earnings.index.unique():
                day = pd.Timestamp(stamp).tz_localize(None).normalize()
                loc = index.searchsorted(day)
                if loc >= len(index):
                    continue
                candidates = [loc, loc + 1] if index[loc] == day else [loc]
                candidates = [i for i in candidates if i < len(index)]
                reaction_loc = max(candidates, key=lambda i: abs(float(daily[symbol].iloc[i])))
                if len(index) - 1 - reaction_loc > 1:
                    continue  # only act on fresh reactions (today or yesterday)
                if float(daily[symbol].iloc[reaction_loc]) >= PEAD_REACTION_MIN:
                    price = round(float(closes[symbol].iloc[reaction_loc]), 2)
                    lane["open"].append({"symbol": symbol, "date": str(index[reaction_loc].date()), "price": price})
                    log_event({"lane": "pead", "action": "entry", "symbol": symbol, "price": price,
                               "reaction_pct": round(float(daily[symbol].iloc[reaction_loc]) * 100.0, 2)})


def summary() -> None:
    if not LOG_PATH.exists():
        return
    events = [json.loads(line) for line in LOG_PATH.read_text(encoding="utf-8").splitlines() if line.strip()]
    print("--- forward evidence summary ---")
    for lane in ("momentum", "tom", "pead"):
        exits = [
            e for e in events
            if e["lane"] == lane and e["action"] == "exit" and e.get("eligible_for_gate", True)
        ]
        pnl = [e["pnl_pct"] for e in exits]
        wins = sum(1 for p in pnl if p > 0)
        print(json.dumps({"lane": lane, "resolved_trades": len(exits),
                          "progress_to_30": f"{len(exits)}/30",
                          "win_rate": round(wins / len(pnl), 3) if pnl else None,
                          "sum_trade_pnl_pct": round(sum(pnl), 2) if pnl else 0}))


def main() -> None:
    state = load_state()
    run_momentum(state)
    run_tom(state)
    run_pead(state)
    save_state(state)
    summary()


if __name__ == "__main__":
    main()

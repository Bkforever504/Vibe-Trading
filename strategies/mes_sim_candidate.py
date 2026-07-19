#!/usr/bin/env python3
"""Retired MES 1h pullback candidate retained for research reproducibility."""
from __future__ import annotations

from datetime import datetime, time as dtime
from typing import Callable
from zoneinfo import ZoneInfo

from strategies.topstep_prop_bot import Candle, OpeningRangeConfig, build_first_pullback_signal


ET = ZoneInfo("America/New_York")
RTH_START = dtime(9, 30)
RTH_END = dtime(16, 0)
MES_CONFIG = OpeningRangeConfig(range_minutes=1, min_breakout_points=3.0, reward_risk=2.0)
PULLBACK_STOP_TICKS = 40
PULLBACK_TOLERANCE_TICKS = 16
RESEARCH_APPROVED_FOR_SIM = False


def fetch_today_es_1h() -> list[Candle]:
    import yfinance as yf

    frame = yf.Ticker("ES=F").history(period="5d", interval="1h", auto_adjust=True)
    if frame.empty:
        return []
    frame.index = frame.index.tz_convert(ET)
    today = datetime.now(ET).date()
    frame = frame[frame.index.map(lambda ts: ts.date() == today and RTH_START <= ts.time() < RTH_END)]
    return [
        Candle(
            timestamp=ts.to_pydatetime().replace(tzinfo=None),
            open=float(row["Open"]), high=float(row["High"]),
            low=float(row["Low"]), close=float(row["Close"]), volume=int(row["Volume"]),
        )
        for ts, row in frame.iterrows()
    ]


def evaluate_mes_candidate(candles: list[Candle]) -> dict:
    if len(candles) < 3:
        return {"state": "waiting_for_closed_1h_bars", "bars": len(candles), "signal": None}
    result = build_first_pullback_signal(
        candles,
        MES_CONFIG,
        symbol="MES",
        pullback_tolerance_ticks=PULLBACK_TOLERANCE_TICKS,
        pullback_stop_ticks=PULLBACK_STOP_TICKS,
    )
    if result is None:
        return {"state": "no_mes_pullback_signal", "bars": len(candles), "signal": None}
    signal, entry_idx = result
    return {
        "state": "mes_pullback_signal",
        "bars": len(candles),
        "signal": {
            "side": signal.side,
            "entry": round(signal.entry, 2),
            "stop": round(signal.stop, 2),
            "target": round(signal.target, 2),
            "entry_bar_idx": entry_idx,
            "confidence": signal.confidence,
            "candidate": "es_1h_orb3_pullback_tol16_stop40_full_2r",
        },
    }


def run_mes_candidate(
    *,
    execute_sim: bool = False,
    fetch_fn: Callable[[], list[Candle]] = fetch_today_es_1h,
) -> dict:
    result = evaluate_mes_candidate(fetch_fn())
    result["mode"] = "ninjatrader_sim101_forward_test"
    result["execute_sim_requested"] = execute_sim
    result["research_approved_for_sim"] = RESEARCH_APPROVED_FOR_SIM
    if execute_sim and not RESEARCH_APPROVED_FOR_SIM:
        result["execution"] = {
            "status": "blocked",
            "reason": "candidate_failed_execution_equivalent_holdout_and_drawdown_gates",
        }
        return result
    if not execute_sim or result["signal"] is None:
        result["execution"] = None
        return result

    from strategies.ninjatrader_sim_adapter import NinjaTraderSimAdapter

    adapter = NinjaTraderSimAdapter()
    result["readiness"] = adapter.readiness()
    result["execution"] = adapter.place_mes_entry(side=result["signal"]["side"], size=1)
    return result

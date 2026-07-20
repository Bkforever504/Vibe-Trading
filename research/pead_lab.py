#!/usr/bin/env python3
"""Preregistered PEAD long-only proxy test. Spec frozen in
research/PEAD_PREREGISTRATION_2026-07-19.md. Research only."""
from __future__ import annotations

import json
import warnings
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "data" / "pead_results.json"
UNIVERSE = (
    "AAPL MSFT NVDA AMZN GOOGL META TSLA AVGO JPM V UNH XOM WMT JNJ PG MA HD "
    "COST ORCL BAC KO PEP MRK ADBE CRM AMD NFLX DIS CSCO INTC"
).split()
REACTION_MIN = 0.03
HOLD_DAYS = 20
COST_PER_SIDE = 0.0002


def event_returns() -> list[tuple[pd.Timestamp, str, float]]:
    import yfinance as yf

    events = []
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        for symbol in UNIVERSE:
            ticker = yf.Ticker(symbol)
            try:
                earnings = ticker.get_earnings_dates(limit=60)
            except Exception:
                continue
            if earnings is None or earnings.empty:
                continue
            prices = yf.download(symbol, start="2018-01-01", progress=False, auto_adjust=True)
            prices.columns = [c.lower() if isinstance(c, str) else c[0].lower() for c in prices.columns]
            close = prices["close"]
            daily = close.pct_change()
            index = close.index
            today = pd.Timestamp.now().normalize()
            for stamp in earnings.index.unique():
                day = pd.Timestamp(stamp).tz_localize(None).normalize()
                if day >= today:
                    continue
                loc = index.searchsorted(day)
                if loc >= len(index) - 1:
                    continue
                candidates = [loc, loc + 1] if index[loc] == day else [loc]
                reaction_loc = max(candidates, key=lambda i: abs(daily.iloc[i]) if i < len(daily) else 0)
                reaction = float(daily.iloc[reaction_loc])
                if reaction < REACTION_MIN:
                    continue
                exit_loc = reaction_loc + HOLD_DAYS
                if exit_loc >= len(index):
                    continue
                gross = float(close.iloc[exit_loc] / close.iloc[reaction_loc] - 1.0)
                events.append((index[reaction_loc], symbol, gross))
    return sorted(events)


def stats(gross_returns: list[float], cost_mult: float) -> dict:
    net = [g - 2 * COST_PER_SIDE * cost_mult for g in gross_returns]
    if not net:
        return {"events": 0}
    wins = sum(r for r in net if r > 0)
    losses = -sum(r for r in net if r <= 0)
    return {
        "events": len(net),
        "mean_return_pct": round(sum(net) / len(net) * 100.0, 3),
        "win_rate": round(sum(1 for r in net if r > 0) / len(net), 4),
        "profit_factor": round(wins / losses, 4) if losses > 0 else None,
        "total_return_pct_sum": round(sum(net) * 100.0, 2),
    }


def main() -> None:
    events = event_returns()
    split = int(len(events) * 0.60)
    dev, test = events[:split], events[split:]
    results = {
        "preregistration": "research/PEAD_PREREGISTRATION_2026-07-19.md",
        "total_events": len(events),
        "first_event": str(events[0][0].date()) if events else None,
        "last_event": str(events[-1][0].date()) if events else None,
        "development": stats([g for _, _, g in dev], 1.0),
        "test": None,
    }
    dev_pass = results["development"].get("mean_return_pct", -1) > 0
    results["development_pass"] = dev_pass
    if dev_pass:
        test_stats = stats([g for _, _, g in test], 1.0)
        test_2x = stats([g for _, _, g in test], 2.0)
        results["test"] = test_stats
        results["test_2x_costs"] = test_2x
        results["test_pass"] = (
            test_stats.get("mean_return_pct", -1) > 0
            and (test_stats.get("profit_factor") or 0) >= 1.10
            and test_2x.get("mean_return_pct", -1) > 0
        )
    OUT.write_text(json.dumps(results, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(results, indent=2))


if __name__ == "__main__":
    main()

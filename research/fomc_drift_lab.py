#!/usr/bin/env python3
"""Preregistered pre-FOMC drift test. Spec frozen in
research/FOMC_DRIFT_PREREGISTRATION_2026-07-19.md. Research only."""
from __future__ import annotations

import json
import warnings
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
COMMS = ROOT / "data" / "fomc_communications.csv"
OUT = ROOT / "data" / "fomc_drift_results.json"
BASE_COST_PER_SIDE = 0.0001
DEV_REGIMES = [("2000-01-01", "2005-12-31"), ("2006-01-01", "2010-12-31"), ("2011-01-01", "2015-12-31")]
SELECTION = ("2016-01-01", "2020-12-31")
FINAL = ("2021-01-01", "2099-01-01")
ACCOUNT = 1000.0


def fomc_dates() -> list[pd.Timestamp]:
    df = pd.read_csv(COMMS, usecols=["Date", "Type"])
    statements = df[df["Type"].str.contains("statement", case=False, na=False)]
    return sorted(pd.to_datetime(statements["Date"].unique()))


def fetch_close(symbol: str) -> pd.Series:
    import yfinance as yf

    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        df = yf.download(symbol, start="2000-01-01", progress=False, auto_adjust=True)
    df.columns = [c.lower() if isinstance(c, str) else c[0].lower() for c in df.columns]
    return df["close"]


def strategy_returns(close: pd.Series, dates: list[pd.Timestamp], cost_mult: float) -> pd.Series:
    daily = close.pct_change().dropna()
    hold = pd.Series(False, index=daily.index)
    positions = daily.index
    for event in dates:
        loc = positions.searchsorted(event, side="right") - 1
        if loc < 0 or loc >= len(positions):
            continue
        if positions[loc] != event:
            continue  # statement date not a trading day in data; skip
        start = max(loc - 1, 0)
        hold.iloc[start: loc + 1] = True  # returns earned on day-before and statement day
    returns = daily.where(hold, 0.0)
    entries = hold & ~hold.shift(1).fillna(False)
    exits_count = int(entries.sum())
    cost = BASE_COST_PER_SIDE * cost_mult
    returns[entries] -= 2 * cost  # entry + eventual exit charged upfront per event
    return returns


def stats(returns: pd.Series) -> dict:
    if returns.empty:
        return {"days": 0}
    equity = ACCOUNT * (1.0 + returns).cumprod()
    peak = equity.cummax()
    active = returns[returns != 0.0]
    wins = active[active > 0].sum()
    losses = -active[active <= 0].sum()
    return {
        "days_held": int((returns != 0).sum()),
        "total_return_pct": round(float((1.0 + returns).prod() - 1.0) * 100.0, 2),
        "profit_factor": round(float(wins / losses), 4) if losses > 0 else None,
        "max_drawdown_pct": round(float(((equity - peak) / peak).min()) * 100.0, 2),
        "final_equity_on_1000": round(float(equity.iloc[-1]), 2),
    }


def window(series: pd.Series, start: str, end: str) -> pd.Series:
    return series.loc[(series.index >= start) & (series.index <= end)]


def main() -> None:
    dates = fomc_dates()
    close = fetch_close("SPY")
    base = strategy_returns(close, dates, 1.0)
    results: dict[str, object] = {
        "preregistration": "research/FOMC_DRIFT_PREREGISTRATION_2026-07-19.md",
        "fomc_statement_dates": len(dates),
        "first_event": str(dates[0].date()),
        "last_event": str(dates[-1].date()),
    }
    regimes = [
        {"window": list(regime), **stats(window(base, *regime))} for regime in DEV_REGIMES
    ]
    results["development_regimes"] = regimes
    dev_pass = all(row.get("total_return_pct", -1) > 0 for row in regimes)
    results["development_pass"] = dev_pass
    if dev_pass:
        sel = stats(window(base, *SELECTION))
        sel_2x = stats(window(strategy_returns(close, dates, 2.0), *SELECTION))
        results["selection"] = sel
        results["selection_2x_costs"] = sel_2x
        sel_pass = sel["total_return_pct"] > 0 and sel_2x["total_return_pct"] > 0 and sel["max_drawdown_pct"] > -25.0
        results["selection_pass"] = sel_pass
        if sel_pass:
            fin = stats(window(base, *FINAL))
            fin_2x = stats(window(strategy_returns(close, dates, 2.0), *FINAL))
            fin_3x = stats(window(strategy_returns(close, dates, 3.0), *FINAL))
            results["final"] = fin
            results["final_2x_costs"] = fin_2x
            results["final_3x_costs"] = fin_3x
            results["final_pass"] = (
                fin["total_return_pct"] > 0
                and fin_2x["total_return_pct"] > 0
                and (fin["profit_factor"] or 0) >= 1.05
                and fin["max_drawdown_pct"] > -25.0
            )
    OUT.write_text(json.dumps(results, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(results, indent=2))


if __name__ == "__main__":
    main()

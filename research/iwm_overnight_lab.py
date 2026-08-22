#!/usr/bin/env python3
"""Preregistered IWM overnight-drift promotion test. Spec frozen in
research/IWM_OVERNIGHT_PREREGISTRATION_2026-08-17.md. Research only."""
from __future__ import annotations

import json
import math
import warnings
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "data" / "iwm_overnight_results.json"

ACCOUNT = 1000.0
BASE_COST_PER_SIDE = 0.0002  # 2 bps per side, stricter than v2 lab
DEV_REGIMES = [
    ("2000-05-26", "2009-12-31"),
    ("2010-01-01", "2015-12-31"),
]
SELECTION = ("2016-01-01", "2020-12-31")
FINAL = ("2021-01-01", "2099-12-31")


def fetch(symbol: str, start: str) -> pd.DataFrame:
    import yfinance as yf

    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        df = yf.download(symbol, start=start, progress=False, auto_adjust=False)
    if df.empty:
        raise ValueError(f"no data for {symbol}")
    df.columns = [c.lower() if isinstance(c, str) else c[0].lower() for c in df.columns]
    df = df[["open", "close", "adj close"]].dropna().copy()
    df.rename(columns={"adj close": "adj_close"}, inplace=True)
    ratio = df["adj_close"] / df["close"]
    df["adj_open"] = df["open"] * ratio
    return df


def overnight_returns(df: pd.DataFrame) -> pd.Series:
    entry_close = df["adj_close"]
    exit_open = df["adj_open"].shift(-1)
    return (exit_open / entry_close - 1.0).dropna().rename("overnight")


def apply_costs(ret: pd.Series, active: pd.Series, cost_mult: float) -> pd.Series:
    cost = 2.0 * BASE_COST_PER_SIDE * cost_mult
    out = ret.where(active, 0.0)
    return out - active.astype(float) * cost


def stats(returns: pd.Series, active: pd.Series) -> dict:
    active = active.reindex(returns.index).fillna(False)
    if returns.empty or not active.any():
        return {"trades": 0}
    equity = ACCOUNT * (1.0 + returns).cumprod()
    peak = equity.cummax()
    live = returns[active]
    wins = live[live > 0]
    losses = -live[live <= 0]
    daily_vol = live.std(ddof=1)
    sharpe = float(live.mean() / daily_vol * math.sqrt(252)) if daily_vol > 0 else None
    return {
        "trades": int(active.sum()),
        "avg_ret_bps": round(float(live.mean() * 10000), 3),
        "win_rate": round(float((live > 0).mean()), 4),
        "total_return_pct": round(float((1.0 + returns).prod() - 1.0) * 100.0, 2),
        "profit_factor": round(float(wins.sum() / losses.sum()), 4) if losses.sum() > 0 else None,
        "max_drawdown_pct": round(float(((equity - peak) / peak).min()) * 100.0, 2),
        "sharpe_annual": round(sharpe, 3) if sharpe is not None else None,
        "final_equity_on_1000": round(float(equity.iloc[-1]), 2),
    }


def window(series: pd.Series, start: str, end: str) -> pd.Series:
    return series[(series.index >= start) & (series.index <= end)]


def evaluate(ret: pd.Series, active: pd.Series, mult: float, start: str, end: str) -> dict:
    r = window(ret, start, end)
    a = window(active, start, end)
    return stats(apply_costs(r, a, mult), a)


def main() -> None:
    df = fetch("IWM", "2000-05-26")
    ret = overnight_returns(df)
    always = pd.Series(True, index=ret.index)

    dev_regimes = [
        {"window": [s, e], **evaluate(ret, always, 1.0, s, e)}
        for s, e in DEV_REGIMES
    ]
    dev_combined = evaluate(ret, always, 1.0, DEV_REGIMES[0][0], DEV_REGIMES[-1][1])
    dev_pass = (
        all((r.get("total_return_pct") or 0) > 0 for r in dev_regimes)
        and (dev_combined.get("sharpe_annual") or 0) > 0.5
    )

    sel = evaluate(ret, always, 1.0, *SELECTION)
    sel_2x = evaluate(ret, always, 2.0, *SELECTION)
    sel_pass = (
        (sel.get("total_return_pct") or 0) > 0
        and (sel_2x.get("total_return_pct") or 0) > 0
        and (sel.get("sharpe_annual") or 0) > 0.5
        and (sel.get("max_drawdown_pct") or -100) > -25.0
    )

    fin = evaluate(ret, always, 1.0, *FINAL)
    fin_2x = evaluate(ret, always, 2.0, *FINAL)
    fin_3x = evaluate(ret, always, 3.0, *FINAL)
    fin_pass = (
        (fin.get("total_return_pct") or 0) > 0
        and (fin_2x.get("total_return_pct") or 0) > 0
        and (fin.get("profit_factor") or 0) >= 1.10
        and (fin.get("sharpe_annual") or 0) > 0.5
        and (fin.get("max_drawdown_pct") or -100) > -25.0
    )

    results = {
        "preregistration": "research/IWM_OVERNIGHT_PREREGISTRATION_2026-08-17.md",
        "instrument": "IWM (yfinance, auto_adjust=False, ratio-adjusted opens)",
        "first_date": str(ret.index.min().date()),
        "last_date": str(ret.index.max().date()),
        "development_regimes": dev_regimes,
        "development_combined": dev_combined,
        "development_pass": dev_pass,
        "selection": sel,
        "selection_2x_costs": sel_2x,
        "selection_pass": sel_pass,
        "final": fin,
        "final_2x_costs": fin_2x,
        "final_3x_costs": fin_3x,
        "final_pass": fin_pass,
        "all_gates_pass": bool(dev_pass and sel_pass and fin_pass),
    }
    OUT.write_text(json.dumps(results, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(results, indent=2))


if __name__ == "__main__":
    main()

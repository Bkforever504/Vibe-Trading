#!/usr/bin/env python3
"""Preregistered turn-of-month test. Spec frozen in
research/TURN_OF_MONTH_PREREGISTRATION_2026-07-19.md. Research only."""
from __future__ import annotations

import json
import warnings
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "data" / "turn_of_month_results.json"
SYMBOLS = ("SPY", "QQQ")
BASE_COST_PER_SIDE = 0.0001
DEV_REGIMES = [("2000-01-01", "2005-12-31"), ("2006-01-01", "2010-12-31"), ("2011-01-01", "2015-12-31")]
SELECTION = ("2016-01-01", "2020-12-31")
FINAL = ("2021-01-01", "2099-01-01")
ACCOUNT = 1000.0


def fetch_close(symbol: str) -> pd.Series:
    import yfinance as yf

    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        df = yf.download(symbol, start="2000-01-01", progress=False, auto_adjust=True)
    df.columns = [c.lower() if isinstance(c, str) else c[0].lower() for c in df.columns]
    return df["close"]


def tom_mask(index: pd.DatetimeIndex) -> pd.Series:
    """True on days where the strategy holds overnight into the next day."""
    month = index.to_period("M")
    rank_in_month = pd.Series(index, index=index).groupby(month).cumcount() + 1
    days_in_month = rank_in_month.groupby(month).transform("max")
    from_end = days_in_month - rank_in_month  # 0 = last trading day
    hold = (from_end <= 4) | (rank_in_month <= 2)
    return hold


def daily_strategy_returns(close: pd.Series, cost_mult: float) -> pd.Series:
    daily = close.pct_change().dropna()
    hold = tom_mask(close.index).shift(1).reindex(daily.index).fillna(False)
    returns = daily.where(hold, 0.0)
    entries = hold & ~hold.shift(1).fillna(False)
    exits = ~hold & hold.shift(1).fillna(False)
    cost = BASE_COST_PER_SIDE * cost_mult
    returns[entries] -= cost
    returns[exits] -= cost
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
    results: dict[str, object] = {"preregistration": "research/TURN_OF_MONTH_PREREGISTRATION_2026-07-19.md"}
    for symbol in SYMBOLS:
        close = fetch_close(symbol)
        base = daily_strategy_returns(close, 1.0)
        buy_hold = close.pct_change().dropna()
        symbol_result: dict[str, object] = {
            "development_regimes": [
                {"window": list(regime), **stats(window(base, *regime)),
                 "buy_hold_return_pct": round(float((1.0 + window(buy_hold, *regime)).prod() - 1.0) * 100.0, 2)}
                for regime in DEV_REGIMES
            ]
        }
        dev_pass = all(row.get("total_return_pct", -1) > 0 for row in symbol_result["development_regimes"])
        symbol_result["development_pass"] = dev_pass
        if dev_pass:
            sel = stats(window(base, *SELECTION))
            sel_2x = stats(window(daily_strategy_returns(close, 2.0), *SELECTION))
            symbol_result["selection"] = sel
            symbol_result["selection_2x_costs"] = sel_2x
            sel_pass = sel["total_return_pct"] > 0 and sel_2x["total_return_pct"] > 0 and sel["max_drawdown_pct"] > -25.0
            symbol_result["selection_pass"] = sel_pass
            if sel_pass:
                fin = stats(window(base, *FINAL))
                fin_2x = stats(window(daily_strategy_returns(close, 2.0), *FINAL))
                fin_3x = stats(window(daily_strategy_returns(close, 3.0), *FINAL))
                symbol_result["final"] = fin
                symbol_result["final_2x_costs"] = fin_2x
                symbol_result["final_3x_costs"] = fin_3x
                symbol_result["final_buy_hold_return_pct"] = round(float((1.0 + window(buy_hold, *FINAL)).prod() - 1.0) * 100.0, 2)
                symbol_result["final_pass"] = (
                    fin["total_return_pct"] > 0
                    and fin_2x["total_return_pct"] > 0
                    and (fin["profit_factor"] or 0) >= 1.05
                    and fin["max_drawdown_pct"] > -25.0
                )
        results[symbol] = symbol_result
    OUT.write_text(json.dumps(results, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(results, indent=2))


if __name__ == "__main__":
    main()

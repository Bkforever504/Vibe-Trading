#!/usr/bin/env python3
"""Preregistered overnight-drift test. Spec frozen in
research/OVERNIGHT_DRIFT_PREREGISTRATION_2026-07-19.md. Research only."""
from __future__ import annotations

import json
import sys
import warnings
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "data" / "overnight_drift_results.json"
SYMBOLS = ("SPY", "QQQ")
BASE_COST_PER_SIDE = 0.0001
DEV_REGIMES = [("2000-01-01", "2005-12-31"), ("2006-01-01", "2010-12-31"), ("2011-01-01", "2015-12-31")]
SELECTION = ("2016-01-01", "2020-12-31")
FINAL = ("2021-01-01", "2099-01-01")
ACCOUNT = 1000.0


def fetch_daily(symbol: str) -> pd.DataFrame:
    import yfinance as yf

    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        df = yf.download(symbol, start="2000-01-01", progress=False, auto_adjust=True)
    if df.empty:
        raise ValueError(f"No data for {symbol}")
    df.columns = [c.lower() if isinstance(c, str) else c[0].lower() for c in df.columns]
    return df[["open", "close"]]


def overnight_returns(df: pd.DataFrame, cost_multiple: float) -> pd.Series:
    gross = df["open"].shift(-1) / df["close"] - 1.0
    net = gross - 2.0 * BASE_COST_PER_SIDE * cost_multiple
    return net.dropna()


def stats(returns: pd.Series) -> dict:
    if returns.empty:
        return {"trades": 0}
    equity = ACCOUNT * (1.0 + returns).cumprod()
    peak = equity.cummax()
    drawdown_pct = float(((equity - peak) / peak).min()) * 100.0
    wins = returns[returns > 0].sum()
    losses = -returns[returns <= 0].sum()
    return {
        "trades": int(returns.size),
        "total_return_pct": round(float((1.0 + returns).prod() - 1.0) * 100.0, 2),
        "mean_per_trade_pct": round(float(returns.mean()) * 100.0, 5),
        "win_rate": round(float((returns > 0).mean()), 4),
        "profit_factor": round(float(wins / losses), 4) if losses > 0 else None,
        "max_drawdown_pct": round(drawdown_pct, 2),
        "final_equity_on_1000": round(float(equity.iloc[-1]), 2),
    }


def window(returns: pd.Series, start: str, end: str) -> pd.Series:
    return returns.loc[(returns.index >= start) & (returns.index <= end)]


def main() -> None:
    results: dict[str, object] = {"preregistration": "research/OVERNIGHT_DRIFT_PREREGISTRATION_2026-07-19.md"}
    for symbol in SYMBOLS:
        df = fetch_daily(symbol)
        base = overnight_returns(df, 1.0)
        symbol_result: dict[str, object] = {
            "development_regimes": [
                {"window": list(regime), **stats(window(base, *regime))} for regime in DEV_REGIMES
            ]
        }
        dev_pass = all(
            row.get("trades", 0) > 0 and row.get("mean_per_trade_pct", 0) > 0
            for row in symbol_result["development_regimes"]
        )
        symbol_result["development_pass"] = dev_pass
        if dev_pass:
            sel = stats(window(base, *SELECTION))
            sel_2x = stats(window(overnight_returns(df, 2.0), *SELECTION))
            symbol_result["selection"] = sel
            symbol_result["selection_2x_costs"] = sel_2x
            sel_pass = (
                sel["total_return_pct"] > 0
                and sel_2x["total_return_pct"] > 0
                and sel["max_drawdown_pct"] > -25.0
            )
            symbol_result["selection_pass"] = sel_pass
            if sel_pass:
                fin = stats(window(base, *FINAL))
                fin_2x = stats(window(overnight_returns(df, 2.0), *FINAL))
                fin_3x = stats(window(overnight_returns(df, 3.0), *FINAL))
                symbol_result["final"] = fin
                symbol_result["final_2x_costs"] = fin_2x
                symbol_result["final_3x_costs"] = fin_3x
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
    sys.exit(main())

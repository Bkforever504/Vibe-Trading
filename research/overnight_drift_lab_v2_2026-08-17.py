#!/usr/bin/env python3
"""Preregistered overnight-session drift v2 backtest. Spec frozen in
research/OVERNIGHT_DRIFT_PREREGISTRATION_2026-08-17.md. Research only.

Differences from `overnight_drift_lab.py`:
  * SPY only (matching the executable Topstep pipeline via MES).
  * Extends history back to 1993 for pre-2000 dev split.
  * Reports Sharpe as a gate metric.
  * Adds diagnostic (non-gating) counterfactuals: VIX>25 skip,
    FOMC-day skip, prior-day-crash skip.
  * Adds MES executability check on 2024-2026 1s BBO parquet.
"""
from __future__ import annotations

import json
import math
import warnings
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "data" / "overnight_drift_v2_results.json"
COMMS = ROOT / "data" / "fomc_communications.csv"

ACCOUNT = 1000.0
BASE_COST_PER_SIDE = 0.0001
DEV_REGIMES = [
    ("1993-01-29", "1999-12-31"),
    ("2000-01-01", "2004-12-31"),
    ("2005-01-01", "2010-12-31"),
]
SELECTION = ("2011-01-01", "2020-12-31")
FINAL = ("2021-01-01", "2099-12-31")


def fetch_symbol(symbol: str, start: str) -> pd.DataFrame:
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


def fetch_spy() -> pd.DataFrame:
    return fetch_symbol("SPY", "1993-01-29")


def fetch_vix() -> pd.Series:
    import yfinance as yf

    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        df = yf.download("^VIX", start="1990-01-01", progress=False, auto_adjust=False)
    df.columns = [c.lower() if isinstance(c, str) else c[0].lower() for c in df.columns]
    return df["close"].rename("vix_close")


def fomc_next_day_flags(index: pd.DatetimeIndex) -> pd.Series:
    if not COMMS.exists():
        return pd.Series(False, index=index)
    events = pd.read_csv(COMMS, usecols=["Date", "Type"])
    statements = events[events["Type"].str.contains("statement", case=False, na=False)]
    dates = pd.to_datetime(statements["Date"].unique())
    flag = pd.Series(False, index=index)
    for evt in dates:
        loc = index.searchsorted(evt, side="left")
        if 0 < loc <= len(index):
            flag.iloc[loc - 1] = True
    return flag


def overnight_returns(spy: pd.DataFrame) -> pd.Series:
    entry_close = spy["adj_close"]
    exit_open = spy["adj_open"].shift(-1)
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


def window_slice(series: pd.Series, start: str, end: str) -> pd.Series:
    idx = series.index
    return series[(idx >= start) & (idx <= end)]


def evaluate(overnight: pd.Series, active: pd.Series, cost_mult: float,
             start: str, end: str) -> dict:
    win_ret = window_slice(overnight, start, end)
    win_active = window_slice(active, start, end)
    net = apply_costs(win_ret, win_active, cost_mult)
    return stats(net, win_active)


def buy_hold_stats(spy: pd.DataFrame, start: str, end: str) -> dict:
    daily = spy["adj_close"].pct_change().dropna()
    win = window_slice(daily, start, end)
    active = pd.Series(True, index=win.index)
    return stats(win, active)


def try_mes_executability(overnight: pd.Series) -> dict:
    parquet_path = ROOT / "data" / "databento" / "mes_v0_bbo1s_rth.parquet"
    if not parquet_path.exists():
        return {"available": False, "reason": "parquet missing"}
    try:
        import pyarrow.parquet as pq
    except ImportError:
        return {"available": False, "reason": "pyarrow missing"}
    df = pq.read_table(
        parquet_path,
        columns=["ts_recv", "bid_px_00", "ask_px_00"],
    ).to_pandas()
    if not isinstance(df.index, pd.DatetimeIndex):
        return {"available": False, "reason": f"index type {type(df.index).__name__}"}
    if df.index.tz is None:
        df.index = df.index.tz_localize("UTC")
    # Drop crossed / stale quotes.
    df = df[(df["bid_px_00"] > 0) & (df["ask_px_00"] > 0)]
    df = df[df["ask_px_00"] >= df["bid_px_00"]]
    df = df.sort_index()
    df_et = df.tz_convert("America/New_York")
    close_marks = df_et.between_time("15:59:55", "16:00:05")
    ask_close = close_marks["ask_px_00"].resample("1D").last().dropna()
    open_marks = df_et.between_time("09:30:00", "09:30:10")
    bid_open = open_marks["bid_px_00"].resample("1D").first().dropna()
    aligned = pd.DataFrame({"buy_ask": ask_close}).join(
        bid_open.rename("sell_bid").shift(-1), how="inner"
    ).dropna()
    if aligned.empty:
        return {"available": False, "reason": "no aligned bars"}
    tick_pnl = aligned["sell_bid"] - aligned["buy_ask"]
    dollar_pnl = tick_pnl * 5.0 - 0.70  # 1 contract MES: $5/pt notional, $0.35/side fees
    aligned["dollar_pnl"] = dollar_pnl
    aligned["notional"] = aligned["buy_ask"] * 5.0
    aligned["return"] = aligned["dollar_pnl"] / aligned["notional"]
    aligned.index = aligned.index.tz_localize(None).normalize()
    spy_over = overnight.copy()
    spy_over.index = spy_over.index.normalize()
    joined = aligned.join(spy_over.rename("spy_over"), how="inner")
    if joined.empty:
        return {"available": True, "reason": "no SPY overlap"}
    corr = float(joined["return"].corr(joined["spy_over"]))
    equity_curve = ACCOUNT * (1.0 + joined["return"]).cumprod()
    peak = equity_curve.cummax()
    return {
        "available": True,
        "trades": int(len(joined)),
        "start": str(joined.index.min().date()),
        "end": str(joined.index.max().date()),
        "avg_dollar_pnl_per_contract": round(float(joined["dollar_pnl"].mean()), 3),
        "median_dollar_pnl_per_contract": round(float(joined["dollar_pnl"].median()), 3),
        "win_rate": round(float((joined["dollar_pnl"] > 0).mean()), 4),
        "avg_return_bps": round(float(joined["return"].mean() * 10000), 3),
        "total_return_pct": round(float((1 + joined["return"]).prod() - 1.0) * 100.0, 2),
        "corr_with_spy_overnight": round(corr, 4),
        "max_dd_pct": round(float(((equity_curve - peak) / peak).min()) * 100.0, 2),
    }


def main() -> None:
    spy = fetch_spy()
    overnight = overnight_returns(spy)
    idx = overnight.index

    always = pd.Series(True, index=idx)
    baseline = {
        "development_regimes": [
            {"window": [s, e], **evaluate(overnight, always, 1.0, s, e)}
            for s, e in DEV_REGIMES
        ],
        "selection": evaluate(overnight, always, 1.0, *SELECTION),
        "selection_2x_costs": evaluate(overnight, always, 2.0, *SELECTION),
        "final": evaluate(overnight, always, 1.0, *FINAL),
        "final_2x_costs": evaluate(overnight, always, 2.0, *FINAL),
        "final_3x_costs": evaluate(overnight, always, 3.0, *FINAL),
    }

    combined_dev = evaluate(overnight, always, 1.0,
                            DEV_REGIMES[0][0], DEV_REGIMES[-1][1])
    dev_pass = (
        all(row.get("total_return_pct", -1) > 0 for row in baseline["development_regimes"])
        and (combined_dev.get("sharpe_annual") or 0) > 0.3
    )
    baseline["development_combined"] = combined_dev
    baseline["development_pass"] = dev_pass

    sel = baseline["selection"]
    sel_2x = baseline["selection_2x_costs"]
    baseline["selection_pass"] = (
        (sel.get("total_return_pct") or 0) > 0
        and (sel_2x.get("total_return_pct") or 0) > 0
        and (sel.get("sharpe_annual") or 0) > 0.3
        and (sel.get("max_drawdown_pct") or -100) > -20.0
    )

    fin = baseline["final"]
    fin_2x = baseline["final_2x_costs"]
    baseline["final_pass"] = (
        (fin.get("total_return_pct") or 0) > 0
        and (fin_2x.get("total_return_pct") or 0) > 0
        and (fin.get("profit_factor") or 0) >= 1.05
        and (fin.get("sharpe_annual") or 0) > 0.3
        and (fin.get("max_drawdown_pct") or -100) > -20.0
    )

    vix = fetch_vix()
    vix_ffill = vix.reindex(idx, method="ffill")
    fomc_flag = fomc_next_day_flags(idx)
    spy_ret = spy["adj_close"].pct_change().reindex(idx)
    v2 = (vix_ffill <= 25).fillna(False)
    v3 = ~fomc_flag
    v4 = (spy_ret >= -0.02).fillna(True)

    counterfactuals = {
        "v2_skip_vix_gt_25_final": evaluate(overnight, v2, 1.0, *FINAL),
        "v3_skip_fomc_next_day_final": evaluate(overnight, v3, 1.0, *FINAL),
        "v4_skip_prior_drop_gt_2pct_final": evaluate(overnight, v4, 1.0, *FINAL),
        "v2_skip_vix_gt_25_full": evaluate(overnight, v2, 1.0,
                                           DEV_REGIMES[0][0], "2099-12-31"),
    }

    buy_hold = {
        "development_combined": buy_hold_stats(spy, DEV_REGIMES[0][0], DEV_REGIMES[-1][1]),
        "selection": buy_hold_stats(spy, *SELECTION),
        "final": buy_hold_stats(spy, *FINAL),
    }

    mes_check = try_mes_executability(overnight)

    # Diagnostic scan across additional broad-market symbols using the
    # baseline unconditional rule ONLY. Reported as supplementary
    # evidence — not treated as a promotion path per the preregistration.
    diagnostic_symbols = {
        "IWM": "2000-05-26",
        "QQQ": "1999-03-10",
        "MDY": "1995-05-04",
        "EEM": "2003-04-14",
    }
    symbol_diagnostics = {}
    for sym, start in diagnostic_symbols.items():
        try:
            sdf = fetch_symbol(sym, start)
        except Exception as exc:
            symbol_diagnostics[sym] = {"error": str(exc)}
            continue
        sret = overnight_returns(sdf)
        sidx = sret.index
        always_s = pd.Series(True, index=sidx)
        vix_s = vix.reindex(sidx, method="ffill")
        v2_s = (vix_s <= 25).fillna(False)
        symbol_diagnostics[sym] = {
            "range": [str(sidx.min().date()), str(sidx.max().date())],
            "baseline_full": evaluate(sret, always_s, 1.0,
                                      str(sidx.min().date()), "2099-12-31"),
            "baseline_final": evaluate(sret, always_s, 1.0, *FINAL),
            "baseline_final_2x_costs": evaluate(sret, always_s, 2.0, *FINAL),
            "vix25_full": evaluate(sret, v2_s, 1.0,
                                   str(sidx.min().date()), "2099-12-31"),
            "vix25_final": evaluate(sret, v2_s, 1.0, *FINAL),
        }

    results = {
        "preregistration": "research/OVERNIGHT_DRIFT_PREREGISTRATION_2026-08-17.md",
        "instrument": "SPY (yfinance, auto_adjust=False, ratio-adjusted opens)",
        "first_date": str(idx.min().date()),
        "last_date": str(idx.max().date()),
        "baseline": baseline,
        "buy_hold_reference": buy_hold,
        "counterfactuals_diagnostic_only": counterfactuals,
        "mes_executability_2024_2026": mes_check,
        "symbol_diagnostics_unconditional": symbol_diagnostics,
    }
    OUT.write_text(json.dumps(results, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(results, indent=2))


if __name__ == "__main__":
    main()

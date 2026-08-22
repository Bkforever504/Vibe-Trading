#!/usr/bin/env python3
"""MES-native overnight-drift executability test. Reads databento 1-min
MES bars 2022-01 through 2026-07 and simulates per-contract dollar P&L
with realistic Topstep friction (1-tick slippage per side + commission).

This is the actual executability follow-on to
OVERNIGHT_DRIFT_PREREGISTRATION_2026-08-17.md and
IWM_OVERNIGHT_PREREGISTRATION_2026-08-17.md, which both showed that
ETF-based backtests fail once realistic retail spread is applied but
that MES BBO-based fills (2024-2026 window) survived friction.
Extending the window back to 2022 with the 1-min bar file lets us
check whether the overnight drift survives the 2022 bear market.

Research only, no execution.
"""
from __future__ import annotations

import json
import math
import warnings
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
DBN_PATH = ROOT / "data" / "databento" / "mes_v0_1m_2022-01-01_2026-07-19.dbn.zst"
OUT = ROOT / "data" / "mes_overnight_results.json"
COMMS = ROOT / "data" / "fomc_communications.csv"

TICK_VALUE = 1.25       # MES: 0.25 point * $5/point
SLIPPAGE_TICKS_PER_SIDE = 1.0
COMMISSION_PER_SIDE = 0.74
MULT = 5.0              # $5 per point
ACCOUNT = 1000.0        # per-contract-equivalent starting notional for pct

FRICTION_ROUND_TRIP = 2.0 * (SLIPPAGE_TICKS_PER_SIDE * TICK_VALUE + COMMISSION_PER_SIDE)


def load_mes() -> pd.DataFrame:
    import databento as db

    dbn = db.DBNStore.from_file(str(DBN_PATH))
    df = dbn.to_df()[["open", "high", "low", "close"]]
    if df.index.tz is None:
        df.index = df.index.tz_localize("UTC")
    return df.sort_index()


def fetch_vix() -> pd.Series:
    import yfinance as yf

    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        df = yf.download("^VIX", start="2021-01-01", progress=False, auto_adjust=False)
    df.columns = [c.lower() if isinstance(c, str) else c[0].lower() for c in df.columns]
    return df["close"].rename("vix_close")


def fomc_next_day_flags(dates: pd.DatetimeIndex) -> pd.Series:
    if not COMMS.exists():
        return pd.Series(False, index=dates)
    events = pd.read_csv(COMMS, usecols=["Date", "Type"])
    statements = events[events["Type"].str.contains("statement", case=False, na=False)]
    ev_dates = pd.to_datetime(statements["Date"].unique())
    flag = pd.Series(False, index=dates)
    for evt in ev_dates:
        loc = dates.searchsorted(evt, side="left")
        if 0 < loc <= len(dates):
            flag.iloc[loc - 1] = True
    return flag


def build_overnight_trades(bars: pd.DataFrame) -> pd.DataFrame:
    et = bars.tz_convert("America/New_York")
    close_window = et.between_time("15:59:00", "16:00:00")
    open_window = et.between_time("09:30:00", "09:31:00")
    entry = close_window["close"].resample("1D").last().dropna()
    exit_next = open_window["open"].resample("1D").first().dropna()
    exit_next = exit_next.shift(-1)  # align t exit to t open of t+1
    aligned = pd.DataFrame({"entry": entry}).join(exit_next.rename("exit"), how="inner").dropna()
    aligned.index = aligned.index.tz_localize(None).normalize()
    aligned["points"] = aligned["exit"] - aligned["entry"]
    aligned["gross_dollar"] = aligned["points"] * MULT
    aligned["net_dollar"] = aligned["gross_dollar"] - FRICTION_ROUND_TRIP
    aligned["notional"] = aligned["entry"] * MULT
    aligned["net_return"] = aligned["net_dollar"] / aligned["notional"]
    return aligned


def stats(trades: pd.DataFrame) -> dict:
    if trades.empty:
        return {"trades": 0}
    ret = trades["net_return"]
    doll = trades["net_dollar"]
    equity_dollars = doll.cumsum()
    peak = equity_dollars.cummax()
    dd = float((equity_dollars - peak).min())
    equity_pct = (1.0 + ret).cumprod() * ACCOUNT
    peak_pct = equity_pct.cummax()
    dd_pct = float(((equity_pct - peak_pct) / peak_pct).min()) * 100.0
    wins = doll[doll > 0]
    losses = -doll[doll <= 0]
    vol = ret.std(ddof=1)
    sharpe = float(ret.mean() / vol * math.sqrt(252)) if vol > 0 else None
    return {
        "trades": int(len(trades)),
        "avg_dollar_per_contract": round(float(doll.mean()), 3),
        "median_dollar_per_contract": round(float(doll.median()), 3),
        "total_dollar_per_contract": round(float(doll.sum()), 2),
        "win_rate": round(float((doll > 0).mean()), 4),
        "profit_factor": round(float(wins.sum() / losses.sum()), 4) if losses.sum() > 0 else None,
        "sharpe_annual": round(sharpe, 3) if sharpe is not None else None,
        "max_dd_dollar_per_contract": round(dd, 2),
        "max_dd_pct_on_notional": round(dd_pct, 2),
        "avg_return_bps": round(float(ret.mean() * 10000), 3),
        "total_return_pct_on_notional": round(float((1.0 + ret).prod() - 1.0) * 100.0, 2),
    }


def by_year(trades: pd.DataFrame) -> dict:
    out = {}
    for year, g in trades.groupby(trades.index.year):
        out[int(year)] = stats(g)
    return out


def main() -> None:
    print(f"[mes_overnight_lab] round-trip friction $/contract = {FRICTION_ROUND_TRIP:.2f}")
    bars = load_mes()
    print(f"[mes_overnight_lab] loaded {len(bars):,} 1m bars {bars.index.min()} -> {bars.index.max()}")

    trades = build_overnight_trades(bars)
    print(f"[mes_overnight_lab] built {len(trades)} overnight trades")

    baseline_full = stats(trades)
    year_stats = by_year(trades)

    vix = fetch_vix()
    vix_by_date = vix.reindex(trades.index, method="ffill")
    fomc_flag = fomc_next_day_flags(trades.index)
    prior_move = (trades["entry"].pct_change()).fillna(0)
    v2_mask = (vix_by_date <= 25).fillna(False)
    v3_mask = ~fomc_flag
    v4_mask = prior_move >= -0.02
    v5_mask = (vix_by_date <= 20).fillna(False)

    counterfactuals = {
        "v2_skip_vix_gt_25": stats(trades[v2_mask]),
        "v3_skip_fomc_next_day": stats(trades[v3_mask]),
        "v4_skip_prior_drop_gt_2pct": stats(trades[v4_mask]),
        "v5_skip_vix_gt_20": stats(trades[v5_mask]),
        "v2_and_v3": stats(trades[v2_mask & v3_mask]),
        "v2_and_v4": stats(trades[v2_mask & v4_mask]),
    }

    results = {
        "preregistration": [
            "research/OVERNIGHT_DRIFT_PREREGISTRATION_2026-08-17.md",
            "research/IWM_OVERNIGHT_PREREGISTRATION_2026-08-17.md",
        ],
        "instrument": "MES front-month continuous (databento mes_v0_1m 2022-01 through 2026-07)",
        "friction_round_trip_per_contract": FRICTION_ROUND_TRIP,
        "friction_breakdown": {
            "slippage_ticks_per_side": SLIPPAGE_TICKS_PER_SIDE,
            "tick_value": TICK_VALUE,
            "commission_per_side": COMMISSION_PER_SIDE,
        },
        "trade_range": [str(trades.index.min().date()), str(trades.index.max().date())],
        "baseline_full": baseline_full,
        "by_year": year_stats,
        "counterfactuals": counterfactuals,
    }
    OUT.write_text(json.dumps(results, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(results, indent=2))


if __name__ == "__main__":
    main()

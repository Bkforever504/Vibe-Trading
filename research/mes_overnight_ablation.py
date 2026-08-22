#!/usr/bin/env python3
"""MES overnight edge ablation: with the VIX<=18 + prior-move>=-1% base
already frozen for shadow, this lab explores whether additional
covariates measurably improve Sharpe on the TRAIN window only. Any
finding must be independently re-tested on a genuinely fresh holdout
(future forward data) before rule change; this file's job is to
enumerate candidates, not to promote them.
"""
from __future__ import annotations

import json
import math
import warnings
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "data" / "mes_overnight_ablation.json"

TICK_VALUE = 1.25
SLIPPAGE_TICKS_PER_SIDE = 1.0
COMMISSION_PER_SIDE = 0.74
MULT = 5.0
FRICTION = 2.0 * (SLIPPAGE_TICKS_PER_SIDE * TICK_VALUE + COMMISSION_PER_SIDE)
VIX_CAP = 18.0
PRIOR_MOVE_FLOOR = -0.01
TRAIN_END = "2024-12-31"


def load_mes() -> pd.DataFrame:
    import databento as db

    path = ROOT / "data" / "databento" / "mes_v0_1m_2022-01-01_2026-07-19.dbn.zst"
    dbn = db.DBNStore.from_file(str(path))
    df = dbn.to_df()[["open", "close"]]
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


def build_trades(bars: pd.DataFrame) -> pd.DataFrame:
    et = bars.tz_convert("America/New_York")
    close_win = et.between_time("15:59:00", "16:00:00")
    open_win = et.between_time("09:30:00", "09:31:00")
    entry = close_win["close"].resample("1D").last().dropna()
    exit_ = open_win["open"].resample("1D").first().dropna().shift(-1)
    df = pd.DataFrame({"entry": entry}).join(exit_.rename("exit"), how="inner").dropna()
    df.index = df.index.tz_localize(None).normalize()
    df["net_dollar"] = (df["exit"] - df["entry"]) * MULT - FRICTION
    df["notional"] = df["entry"] * MULT
    df["net_return"] = df["net_dollar"] / df["notional"]
    return df


def stats(t: pd.DataFrame) -> dict:
    if t.empty:
        return {"trades": 0}
    ret = t["net_return"]
    doll = t["net_dollar"]
    equity = doll.cumsum()
    peak = equity.cummax()
    vol = ret.std(ddof=1)
    sharpe = float(ret.mean() / vol * math.sqrt(252)) if vol > 0 else None
    wins = doll[doll > 0]
    losses = -doll[doll <= 0]
    return {
        "trades": int(len(t)),
        "avg_dollar": round(float(doll.mean()), 3),
        "sharpe": round(sharpe, 3) if sharpe is not None else None,
        "PF": round(float(wins.sum() / losses.sum()), 4) if losses.sum() > 0 else None,
        "win_rate": round(float((doll > 0).mean()), 4),
        "max_dd": round(float((equity - peak).min()), 2),
    }


def main() -> None:
    bars = load_mes()
    trades = build_trades(bars)
    vix = fetch_vix()
    v = vix.reindex(trades.index, method="ffill")
    trades["vix"] = v
    trades["prior_move"] = trades["entry"].pct_change()
    trades["dow"] = trades.index.dayofweek       # 0=Mon .. 4=Fri
    trades["month"] = trades.index.month
    trades["month_third"] = pd.cut(trades.index.day, bins=[0, 10, 20, 31], labels=["early", "mid", "late"])

    base_mask = (trades["vix"] <= VIX_CAP) & (trades["prior_move"] >= PRIOR_MOVE_FLOOR)
    train_mask = trades.index <= TRAIN_END
    test_mask = trades.index > TRAIN_END
    train_base = trades[base_mask & train_mask]
    test_base = trades[base_mask & test_mask]

    baseline_stats = {"train": stats(train_base), "test": stats(test_base)}

    # Day-of-week ablation (train only).
    dow_train = {}
    for d, label in enumerate(("Mon", "Tue", "Wed", "Thu", "Fri")):
        subset = train_base[train_base["dow"] == d]
        dow_train[label] = stats(subset)

    # Also DoW on test (report separately, don't refit).
    dow_test = {}
    for d, label in enumerate(("Mon", "Tue", "Wed", "Thu", "Fri")):
        subset = test_base[test_base["dow"] == d]
        dow_test[label] = stats(subset)

    # Month ablation (train only).
    month_train = {int(m): stats(train_base[train_base["month"] == m]) for m in range(1, 13)}
    month_test = {int(m): stats(test_base[test_base["month"] == m]) for m in range(1, 13)}

    # Turn-of-month effect: is the last 3 sessions of month + first 3 sessions
    # of next month a persistent skew?
    def near_tom(idx: pd.DatetimeIndex) -> pd.Series:
        s = pd.Series(False, index=idx)
        for day, tag in [(idx.day <= 3, True), (idx.day >= 26, True)]:
            s = s | day
        return s

    tom_mask = pd.Series(near_tom(trades.index).values, index=trades.index)
    tom = {
        "train_TOM": stats(train_base[tom_mask.reindex(train_base.index).fillna(False)]),
        "train_non_TOM": stats(train_base[~tom_mask.reindex(train_base.index).fillna(False)]),
        "test_TOM": stats(test_base[tom_mask.reindex(test_base.index).fillna(False)]),
        "test_non_TOM": stats(test_base[~tom_mask.reindex(test_base.index).fillna(False)]),
    }

    # VIX bucketing beyond the cap (train only).
    def bucket(vix_val: float) -> str:
        if vix_val <= 14: return "<=14"
        if vix_val <= 16: return "15-16"
        if vix_val <= 18: return "17-18"
        return ">18"

    train_base = train_base.copy()
    train_base["vix_bucket"] = train_base["vix"].apply(bucket)
    vix_train = {b: stats(train_base[train_base["vix_bucket"] == b])
                 for b in ("<=14", "15-16", "17-18")}

    # Prior-move sign effect (train only).
    train_base["prior_sign"] = train_base["prior_move"].apply(
        lambda x: "up" if x > 0 else ("flat" if abs(x) < 0.001 else "down")
    )
    prior_train = {s: stats(train_base[train_base["prior_sign"] == s])
                   for s in ("up", "down", "flat")}

    results = {
        "baseline": baseline_stats,
        "day_of_week_TRAIN": dow_train,
        "day_of_week_TEST_reference_only": dow_test,
        "month_TRAIN": month_train,
        "month_TEST_reference_only": month_test,
        "turn_of_month_effect": tom,
        "vix_bucket_TRAIN": vix_train,
        "prior_move_sign_TRAIN": prior_train,
        "notes": "Train = 2022-01-03 through 2024-12-31. Test = 2025-01-02 through 2026-07-16. TEST results are reference only — no promotion permitted from this document.",
    }
    OUT.write_text(json.dumps(results, indent=2, default=str) + "\n", encoding="utf-8")
    print(json.dumps(results, indent=2, default=str))


if __name__ == "__main__":
    main()

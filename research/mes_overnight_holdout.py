#!/usr/bin/env python3
"""Honest train/test split for the MES overnight + VIX filter that
looked strong on the full 2022-2026 sample. This does NOT touch the
2025-2026 window when selecting the filter threshold, so any pass here
is real out-of-sample evidence — subject to the caveat that we saw
2022-2024 patterns before writing this file."""
from __future__ import annotations

import json
import math
import warnings
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "data" / "mes_overnight_holdout.json"

TICK_VALUE = 1.25
SLIPPAGE_TICKS_PER_SIDE = 1.0
COMMISSION_PER_SIDE = 0.74
MULT = 5.0
FRICTION_ROUND_TRIP = 2.0 * (SLIPPAGE_TICKS_PER_SIDE * TICK_VALUE + COMMISSION_PER_SIDE)

TRAIN_END = "2024-12-31"
TEST_START = "2025-01-01"

# Filter grid searched ONLY on TRAIN. Same grid then evaluated on TEST.
VIX_GRID = [None, 30, 25, 22, 20, 18, 16]
PRIOR_MOVE_GRID = [None, -0.03, -0.02, -0.01]


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
    close_window = et.between_time("15:59:00", "16:00:00")
    open_window = et.between_time("09:30:00", "09:31:00")
    entry = close_window["close"].resample("1D").last().dropna()
    exit_ = open_window["open"].resample("1D").first().dropna().shift(-1)
    aligned = pd.DataFrame({"entry": entry}).join(exit_.rename("exit"), how="inner").dropna()
    aligned.index = aligned.index.tz_localize(None).normalize()
    aligned["net_dollar"] = (aligned["exit"] - aligned["entry"]) * MULT - FRICTION_ROUND_TRIP
    aligned["notional"] = aligned["entry"] * MULT
    aligned["net_return"] = aligned["net_dollar"] / aligned["notional"]
    return aligned


def stats(trades: pd.DataFrame) -> dict:
    if trades.empty:
        return {"trades": 0}
    ret = trades["net_return"]
    doll = trades["net_dollar"]
    equity = doll.cumsum()
    peak = equity.cummax()
    dd = float((equity - peak).min())
    vol = ret.std(ddof=1)
    sharpe = float(ret.mean() / vol * math.sqrt(252)) if vol > 0 else None
    wins = doll[doll > 0]
    losses = -doll[doll <= 0]
    return {
        "trades": int(len(trades)),
        "avg_dollar": round(float(doll.mean()), 3),
        "total_dollar": round(float(doll.sum()), 2),
        "win_rate": round(float((doll > 0).mean()), 4),
        "profit_factor": round(float(wins.sum() / losses.sum()), 4) if losses.sum() > 0 else None,
        "sharpe_annual": round(sharpe, 3) if sharpe is not None else None,
        "max_dd_dollar": round(dd, 2),
        "avg_return_bps": round(float(ret.mean() * 10000), 3),
    }


def filter_mask(trades: pd.DataFrame, vix: pd.Series,
                vix_cap: float | None, prior_move_floor: float | None) -> pd.Series:
    mask = pd.Series(True, index=trades.index)
    if vix_cap is not None:
        v = vix.reindex(trades.index, method="ffill")
        mask &= (v <= vix_cap).fillna(False)
    if prior_move_floor is not None:
        prior_move = trades["entry"].pct_change().fillna(0)
        mask &= (prior_move >= prior_move_floor)
    return mask


def main() -> None:
    bars = load_mes()
    trades = build_trades(bars)
    vix = fetch_vix()

    train = trades[trades.index <= TRAIN_END]
    test = trades[trades.index >= TEST_START]
    print(f"[holdout] train {train.index.min().date()}-{train.index.max().date()} "
          f"n={len(train)}, test {test.index.min().date()}-{test.index.max().date()} n={len(test)}")

    # Grid search on TRAIN only.
    train_grid = []
    for v_cap in VIX_GRID:
        for pm in PRIOR_MOVE_GRID:
            mask = filter_mask(train, vix, v_cap, pm)
            s = stats(train[mask])
            if s.get("trades", 0) < 200:
                continue
            train_grid.append({
                "vix_cap": v_cap,
                "prior_move_floor": pm,
                **s,
            })
    train_grid.sort(key=lambda r: (r.get("sharpe_annual") or -1e9), reverse=True)

    best = train_grid[0] if train_grid else None
    if best is None:
        results = {"train_grid": [], "note": "no filter passed the 200-trade floor on train"}
        OUT.write_text(json.dumps(results, indent=2) + "\n", encoding="utf-8")
        print(json.dumps(results, indent=2))
        return

    # Evaluate best filter on TEST — the honest out-of-sample check.
    best_mask_test = filter_mask(test, vix, best["vix_cap"], best["prior_move_floor"])
    test_stats = stats(test[best_mask_test])

    # Also report unconditional baseline on both windows for reference.
    baseline_train = stats(train)
    baseline_test = stats(test)

    # And an execution-realistic sizing example on the test window.
    if best_mask_test.any():
        live = test[best_mask_test]
        equity_curve = live["net_dollar"].cumsum()
    else:
        equity_curve = pd.Series(dtype=float)

    results = {
        "instrument": "MES front-month continuous",
        "friction_round_trip": FRICTION_ROUND_TRIP,
        "train_window": [str(train.index.min().date()), str(train.index.max().date())],
        "test_window": [str(test.index.min().date()), str(test.index.max().date())],
        "top_train_configs": train_grid[:5],
        "chosen_config": {"vix_cap": best["vix_cap"], "prior_move_floor": best["prior_move_floor"]},
        "train_baseline_no_filter": baseline_train,
        "test_baseline_no_filter": baseline_test,
        "test_with_chosen_filter": test_stats,
        "test_equity_curve_dollars": [
            [str(d.date()), round(float(v), 2)]
            for d, v in equity_curve.items()
        ][:100],  # first 100 points for sanity check
        "test_pass_criteria": {
            "positive_total_dollar": (test_stats.get("total_dollar") or 0) > 0,
            "sharpe_over_0_5": (test_stats.get("sharpe_annual") or 0) > 0.5,
            "profit_factor_over_1_1": (test_stats.get("profit_factor") or 0) > 1.1,
        },
        "test_pass": (
            (test_stats.get("total_dollar") or 0) > 0
            and (test_stats.get("sharpe_annual") or 0) > 0.5
            and (test_stats.get("profit_factor") or 0) > 1.1
        ),
    }
    OUT.write_text(json.dumps(results, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(results, indent=2))


if __name__ == "__main__":
    main()

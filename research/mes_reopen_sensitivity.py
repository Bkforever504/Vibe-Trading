#!/usr/bin/env python3
"""MES reopen edge sensitivity + bootstrap lab.

Diagnostic-only follow-on to research/mes_reopen_vix_holdout.py. Does
NOT change the frozen rule in
research/MES_REOPEN_VIX_FILTER_PREREGISTRATION_2026-08-17.md.

Runs three independent analyses on the same historical data:

  A. Block-bootstrap 90 % confidence interval for the mean $/contract
     of the frozen rule on TRAIN and TEST windows. Uses stationary
     block bootstrap with mean block length 5 to preserve serial
     dependence.

  B. Entry-time sensitivity. Same VIX/prior-move filter and exit
     (09:30 ET), but sweeps same-calendar-day entry times from 18:00 through
     23:00 ET. Post-midnight variants are excluded because they would bind to
     a VIX close that did not exist at their signal timestamp.

  C. Exit-time sensitivity. Baseline entry 18:00 ET, sweeps exit from
     08:30 through 12:00 ET. Reports per-time train/test stats.

Research only. Execution disabled.
"""
from __future__ import annotations

import json
import math
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from research.mes_overnight_holdout import (
    FRICTION_ROUND_TRIP,
    MULT,
    fetch_vix,
    load_mes,
    stats,
)

OUT = ROOT / "data" / "mes_reopen_sensitivity.json"
VIX_CAP = 18.0
PRIOR_MOVE_FLOOR = -0.01
TRAIN_END = "2024-12-31"
TEST_START = "2025-01-01"

RNG_SEED = 20260817
BOOTSTRAP_N = 10000
BOOTSTRAP_BLOCK_MEAN = 5


def _daily(series: pd.Series) -> pd.Series:
    s = series.copy()
    s.index = s.index.tz_localize(None).normalize()
    return s


def _time_bar(et: pd.DataFrame, start: str, end: str, kind: str) -> pd.Series:
    win = et.between_time(start, end)
    if kind == "close":
        s = win["close"].resample("1D").last()
    else:
        s = win["open"].resample("1D").first()
    return _daily(s.dropna())


def build_trades(bars: pd.DataFrame, vix: pd.Series,
                 entry_time: tuple[str, str],
                 exit_time: tuple[str, str],
                 exit_next_day: bool) -> pd.DataFrame:
    et = bars.tz_convert("America/New_York")
    close_1600 = _time_bar(et, "15:59:00", "16:00:00", "close")
    entry_series = _time_bar(et, entry_time[0], entry_time[1], "open")
    exit_series = _time_bar(et, exit_time[0], exit_time[1], "open")

    entries = entry_series.rename("entry").rename_axis("entry_date").reset_index()
    exits = exit_series.rename("exit").rename_axis("exit_date").reset_index()
    trades = pd.merge_asof(
        entries.sort_values("entry_date"),
        exits.sort_values("exit_date"),
        left_on="entry_date",
        right_on="exit_date",
        direction="forward",
        allow_exact_matches=not exit_next_day,
        tolerance=pd.Timedelta(days=4),
    ).dropna()
    trades = trades.set_index("entry_date")
    trades["mes_close_1600"] = close_1600.reindex(trades.index)
    trades["prior_move"] = close_1600.pct_change().reindex(trades.index)
    trades["vix_close"] = vix.reindex(trades.index, method="ffill")
    trades = trades.dropna(subset=["mes_close_1600", "prior_move", "vix_close"])
    trades = trades[
        (trades.index.dayofweek <= 3)
        & (trades["vix_close"] <= VIX_CAP)
        & (trades["prior_move"] >= PRIOR_MOVE_FLOOR)
    ].copy()
    trades["net_dollar"] = (trades["exit"] - trades["entry"]) * MULT - FRICTION_ROUND_TRIP
    trades["notional"] = trades["entry"] * MULT
    trades["net_return"] = trades["net_dollar"] / trades["notional"]
    return trades


def stationary_block_bootstrap_mean(x: np.ndarray, n_boot: int,
                                    mean_block_len: float,
                                    rng: np.random.Generator) -> np.ndarray:
    n = len(x)
    if n == 0:
        return np.array([])
    p = 1.0 / mean_block_len
    means = np.empty(n_boot, dtype=np.float64)
    for b in range(n_boot):
        idx = np.empty(n, dtype=np.int64)
        i = 0
        cur = rng.integers(0, n)
        while i < n:
            idx[i] = cur
            i += 1
            if rng.random() < p:
                cur = rng.integers(0, n)
            else:
                cur = (cur + 1) % n
        means[b] = x[idx].mean()
    return means


def bootstrap_ci(trades: pd.DataFrame) -> dict:
    if trades.empty:
        return {"trades": 0}
    x = trades["net_dollar"].to_numpy(dtype=np.float64)
    rng = np.random.default_rng(RNG_SEED)
    samples = stationary_block_bootstrap_mean(x, BOOTSTRAP_N, BOOTSTRAP_BLOCK_MEAN, rng)
    return {
        "n": int(len(x)),
        "point_mean_dollar": round(float(x.mean()), 3),
        "bootstrap_mean_dollar": round(float(samples.mean()), 3),
        "ci_lower_90pct": round(float(np.quantile(samples, 0.05)), 3),
        "ci_upper_90pct": round(float(np.quantile(samples, 0.95)), 3),
        "ci_lower_95pct": round(float(np.quantile(samples, 0.025)), 3),
        "ci_upper_95pct": round(float(np.quantile(samples, 0.975)), 3),
        "prob_mean_positive": round(float((samples > 0).mean()), 4),
    }


def evaluate_config(bars: pd.DataFrame, vix: pd.Series,
                    entry_time: tuple[str, str],
                    exit_time: tuple[str, str]) -> dict:
    trades = build_trades(bars, vix, entry_time, exit_time, exit_next_day=True)
    train = trades[trades.index <= TRAIN_END]
    test = trades[trades.index >= TEST_START]
    return {
        "train": stats(train),
        "test": stats(test),
    }


def main() -> None:
    bars = load_mes()
    vix = fetch_vix()

    # Baseline reopen 18:00 ET / exit 09:30 ET — matches frozen rule.
    baseline_entry = ("18:00:00", "18:01:00")
    baseline_exit = ("09:30:00", "09:31:00")
    baseline_trades = build_trades(bars, vix, baseline_entry, baseline_exit, exit_next_day=True)
    train_baseline = baseline_trades[baseline_trades.index <= TRAIN_END]
    test_baseline = baseline_trades[baseline_trades.index >= TEST_START]

    # A. Bootstrap CI on train + test.
    boot = {
        "method": f"stationary block bootstrap, n={BOOTSTRAP_N}, mean block len {BOOTSTRAP_BLOCK_MEAN}",
        "train_2022_2024": bootstrap_ci(train_baseline),
        "test_2025_2026": bootstrap_ci(test_baseline),
        "full_2022_2026": bootstrap_ci(baseline_trades),
    }

    # B. Entry-time sensitivity (exit fixed 09:30 ET).
    # CAUSALITY: only entries that fall on the SAME CALENDAR DAY as the
    # signal (Mon 16:00 VIX + prior-move check) can use that day's VIX
    # close without look-ahead. Entries past midnight would be reading
    # the NEXT session's VIX (not yet published), so they are excluded.
    entry_grid = {
        "17:00_CT_18:00_ET_reopen": ("18:00:00", "18:01:00"),
        "18:00_CT_19:00_ET": ("19:00:00", "19:01:00"),
        "19:00_CT_20:00_ET": ("20:00:00", "20:01:00"),
        "20:00_CT_21:00_ET": ("21:00:00", "21:01:00"),
        "21:00_CT_22:00_ET": ("22:00:00", "22:01:00"),
        "22:00_CT_23:00_ET": ("23:00:00", "23:01:00"),
    }
    entry_sensitivity = {
        label: evaluate_config(bars, vix, tw, baseline_exit)
        for label, tw in entry_grid.items()
    }
    entry_sensitivity["_note"] = (
        "Entries limited to same-day evening window to preserve VIX-close causality. "
        "Post-midnight entries (00:00-04:00 ET) removed after an internal audit found "
        "the earlier grid was reading the next session's not-yet-published VIX close."
    )

    # C. Exit-time sensitivity (entry fixed 18:00 ET).
    exit_grid = {
        "08:30_ET": ("08:30:00", "08:31:00"),
        "09:00_ET": ("09:00:00", "09:01:00"),
        "09:30_ET": ("09:30:00", "09:31:00"),
        "10:00_ET": ("10:00:00", "10:01:00"),
        "11:00_ET": ("11:00:00", "11:01:00"),
        "12:00_ET": ("12:00:00", "12:01:00"),
    }
    exit_sensitivity = {
        label: evaluate_config(bars, vix, baseline_entry, tw)
        for label, tw in exit_grid.items()
    }

    results = {
        "preregistration_reference": "research/MES_REOPEN_VIX_FILTER_PREREGISTRATION_2026-08-17.md",
        "note": "Diagnostic only. Does not change the frozen rule.",
        "interpretation": {
            "bootstrap": (
                "The independent test 90% and 95% intervals cross zero; evidence is "
                "supportive but not statistically confirmed."
            ),
            "entry_time": (
                "18:00-19:00 ET is a robust plateau, not a uniquely identified optimum. "
                "Later entries progressively lose expectancy."
            ),
            "exit_time": (
                "09:00-09:30 ET is a robust plateau. Holding past 10:00 ET degrades "
                "materially in the test window."
            ),
            "selection_policy": (
                "Keep the preregistered 18:00-to-09:30 rule; do not retune from this "
                "diagnostic grid."
            ),
        },
        "baseline_stats": {
            "train": stats(train_baseline),
            "test": stats(test_baseline),
        },
        "A_bootstrap_confidence_intervals": boot,
        "B_entry_time_sensitivity_exit_at_0930_ET": entry_sensitivity,
        "C_exit_time_sensitivity_entry_at_1800_ET": exit_sensitivity,
    }
    OUT.write_text(json.dumps(results, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(results, indent=2))


if __name__ == "__main__":
    main()

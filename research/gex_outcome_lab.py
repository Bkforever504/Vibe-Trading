#!/usr/bin/env python3
"""GEX outcome analyzer. Joins the shadow log from scripts/gex_scanner.py
to SPY/QQQ/IWM daily bars from yfinance and reports whether the net_gex
regime and gex_wall proximity predict:

  H1  Next-session realized range (high-low) as % of prior close.
  H2  Mean-reversion of close-to-close move toward the wall level.
  H3  Overnight (close-to-open) return direction.

Preregistration note: only 34 shadow-log days exist as of 2026-08-17,
with 11 usable SPY scans (Alpaca OI coverage requirement drops others).
This lab therefore reports directional evidence only; promotion gates
require 30+ usable trading days per repo policy. Framework is in place
so evidence accrues automatically as the daily scanner runs.
Research only, no execution.
"""
from __future__ import annotations

import json
import math
import warnings
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
LOG_PATH = ROOT / "data" / "gex_scan_log.jsonl"
OUT = ROOT / "data" / "gex_outcome_results.json"


def load_scans() -> pd.DataFrame:
    rows = []
    with LOG_PATH.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            entry = json.loads(line)
            for scan in entry.get("scans", []):
                if scan.get("status") != "ok":
                    continue
                wall = scan.get("gex_wall") or {}
                rows.append({
                    "date": entry["date"],
                    "symbol": scan["symbol"],
                    "net_gex": scan.get("net_gex"),
                    "net_gex_regime": scan.get("net_gex_regime"),
                    "wall_strike": wall.get("strike"),
                    "wall_gex": wall.get("gex"),
                    "gamma_flip": scan.get("gamma_flip"),
                })
    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame(rows)
    df["date"] = pd.to_datetime(df["date"])
    return df


def fetch_bars(symbol: str, start: str) -> pd.DataFrame:
    import yfinance as yf

    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        df = yf.download(symbol, start=start, progress=False, auto_adjust=False)
    df.columns = [c.lower() if isinstance(c, str) else c[0].lower() for c in df.columns]
    return df[["open", "high", "low", "close"]].dropna()


def per_symbol_analysis(scans: pd.DataFrame, bars: pd.DataFrame) -> dict:
    if scans.empty or bars.empty:
        return {"usable_scans": int(len(scans)), "note": "insufficient data"}
    scans = scans.set_index("date").sort_index()
    bars = bars.copy()
    bars.index = pd.to_datetime(bars.index)
    joined = scans.join(bars, how="inner")
    if joined.empty:
        return {"usable_scans": int(len(scans)), "note": "no bar overlap"}

    joined["prev_close"] = joined["close"].shift(1)
    joined["range_pct"] = (joined["high"] - joined["low"]) / joined["prev_close"] * 100.0
    joined["oc_pct"] = (joined["close"] - joined["open"]) / joined["open"] * 100.0
    joined["overnight_pct"] = joined["open"] / joined["prev_close"].shift(-1) - 1.0
    joined["overnight_next"] = joined["open"].shift(-1) / joined["close"] * 100.0 - 100.0
    joined["cc_next_pct"] = joined["close"].shift(-1) / joined["close"] * 100.0 - 100.0

    pos = joined[joined["net_gex_regime"] == "positive"]
    neg = joined[joined["net_gex_regime"] == "negative"]

    # H1: does negative net_gex regime produce wider next-session range?
    h1 = {
        "n_positive": int(len(pos)),
        "n_negative": int(len(neg)),
        "avg_next_day_range_pct_pos": (
            round(float(pos["range_pct"].shift(-1).mean()), 4) if len(pos) else None
        ),
        "avg_next_day_range_pct_neg": (
            round(float(neg["range_pct"].shift(-1).mean()), 4) if len(neg) else None
        ),
    }

    # H2: does distance from wall predict close-to-close mean-reversion?
    def dist_pct(row):
        if pd.isna(row["wall_strike"]) or pd.isna(row["close"]):
            return None
        return (row["close"] - row["wall_strike"]) / row["wall_strike"] * 100.0

    joined["dist_from_wall_pct"] = joined.apply(dist_pct, axis=1)
    joined["revert_toward_wall"] = joined.apply(
        lambda r: (
            None if pd.isna(r["cc_next_pct"]) or pd.isna(r["dist_from_wall_pct"])
            else int((r["dist_from_wall_pct"] > 0 and r["cc_next_pct"] < 0)
                     or (r["dist_from_wall_pct"] < 0 and r["cc_next_pct"] > 0))
        ),
        axis=1,
    )
    rev = joined["revert_toward_wall"].dropna()
    h2 = {
        "n_valid": int(len(rev)),
        "reversion_rate": round(float(rev.mean()), 4) if len(rev) else None,
        "null_expected": 0.5,
    }

    # H3: next overnight return by regime.
    h3 = {
        "avg_overnight_next_pct_pos": (
            round(float(pos["overnight_next"].mean()), 4) if len(pos) else None
        ),
        "avg_overnight_next_pct_neg": (
            round(float(neg["overnight_next"].mean()), 4) if len(neg) else None
        ),
    }

    # H4: sign accuracy — does regime predict next-day close direction?
    def sign_hit(row, regime):
        if pd.isna(row["cc_next_pct"]):
            return None
        if regime == "positive":
            return int(abs(row["cc_next_pct"]) < 0.5)  # positive gamma = range bound
        else:
            return int(abs(row["cc_next_pct"]) >= 0.5)  # negative gamma = wider moves

    joined["h4_hit"] = joined.apply(lambda r: sign_hit(r, r["net_gex_regime"]), axis=1)
    hit_series = joined["h4_hit"].dropna()
    h4 = {
        "n_valid": int(len(hit_series)),
        "regime_predicts_move_bucket_rate": (
            round(float(hit_series.mean()), 4) if len(hit_series) else None
        ),
        "null_expected": 0.5,
    }

    return {
        "usable_scans": int(len(joined)),
        "hypothesis_1_range_expansion_under_negative_gex": h1,
        "hypothesis_2_mean_reversion_toward_wall": h2,
        "hypothesis_3_overnight_drift_by_regime": h3,
        "hypothesis_4_regime_predicts_move_bucket": h4,
    }


def main() -> None:
    scans_all = load_scans()
    if scans_all.empty:
        OUT.write_text(json.dumps({"note": "no usable scans"}, indent=2) + "\n", encoding="utf-8")
        print("no usable scans")
        return

    result = {"as_of": pd.Timestamp.utcnow().isoformat()}
    for symbol in ("SPY", "QQQ", "IWM"):
        sc = scans_all[scans_all["symbol"] == symbol]
        if sc.empty:
            result[symbol] = {"usable_scans": 0}
            continue
        start = str(sc["date"].min().date())
        bars = fetch_bars(symbol, start)
        result[symbol] = per_symbol_analysis(sc, bars)

    result["policy"] = {
        "shadow_days_available": int(scans_all["date"].nunique()),
        "promotion_gate": "30 usable trading days minimum per repo signal_registry policy",
        "next_step": "Continue daily scanner; rerun this lab weekly; freeze protocol at 30+ usable-day threshold",
    }
    OUT.write_text(json.dumps(result, indent=2, default=str) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2, default=str))


if __name__ == "__main__":
    main()

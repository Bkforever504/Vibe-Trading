"""
Daily shadow signal logger for WaveTrend Oscillator strategy.

No trading. No Alpaca orders. Appends to data/wavetrend_shadow_log.jsonl

WaveTrend (LazyBear TradingView — core component of Market Cipher B, ~$300/yr):
  - AP  = (High + Low + Close) / 3
  - ESA = EMA(AP, n1)
  - D   = EMA(|AP - ESA|, n1)
  - CI  = (AP - ESA) / (0.015 * D)
  - WT1 = EMA(CI, n2)   ← fast line
  - WT2 = SMA(WT1, 4)   ← signal line
  - OB = +53, OS = -53  (overbought / oversold levels)

Entry signals:
  Bull: WT1 crosses ABOVE WT2 while both are below OS (-53) = oversold bounce
  Bear: WT1 crosses BELOW WT2 while both are above OB (+53) = overbought reversal

Primary:    QQQ daily  n1=10, n2=21
Comparison: SPY daily  n1=10, n2=21

Divergence detection (bonus signal): price makes new low but WT1 makes higher low = bullish div.
"""
from __future__ import annotations

import json
import sys
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.market_data import fetch_ohlcv, data_source, fetch_vix_context
from scripts.shadow_alerts import maybe_send_shadow_alert

LOG_PATH = ROOT / "data" / "wavetrend_shadow_log.jsonl"
PRIMARY_SYMBOL = "QQQ"
COMPARISON_SYMBOL = "SPY"

# WaveTrend default parameters (LazyBear)
N1 = 10
N2 = 21
SIGNAL_LEN = 4
OB = 53.0    # overbought threshold
OS = -53.0   # oversold threshold


# ---------------------------------------------------------------------------
# WaveTrend math
# ---------------------------------------------------------------------------

def compute_wavetrend(
    df: pd.DataFrame,
    n1: int = N1,
    n2: int = N2,
    signal_len: int = SIGNAL_LEN,
) -> pd.DataFrame:
    """Return WT1 (fast), WT2 (signal), and cross signals."""
    ap = (df["high"] + df["low"] + df["close"]) / 3
    esa = ap.ewm(span=n1, adjust=False).mean()
    d = (ap - esa).abs().ewm(span=n1, adjust=False).mean()

    # Avoid division by zero
    d_safe = d.copy()
    d_safe[d_safe < 1e-10] = np.nan
    ci = (ap - esa) / (0.015 * d_safe)

    wt1 = ci.ewm(span=n2, adjust=False).mean()
    wt2 = wt1.rolling(signal_len).mean()

    # Cross signals
    cross_above = (wt1 > wt2) & (wt1.shift(1) <= wt2.shift(1))
    cross_below = (wt1 < wt2) & (wt1.shift(1) >= wt2.shift(1))

    return pd.DataFrame({
        "close": df["close"],
        "wt1": wt1,
        "wt2": wt2,
        "cross_above": cross_above,
        "cross_below": cross_below,
    }, index=df.index)


def _detect_divergence(df: pd.DataFrame, wt_df: pd.DataFrame, lookback: int = 14) -> dict:
    """Check for bullish/bearish divergence over recent bars."""
    if len(df) < lookback + 2:
        return {"bullish_div": False, "bearish_div": False}

    price_tail = df["close"].iloc[-lookback:]
    wt_tail = wt_df["wt1"].iloc[-lookback:]

    price_new_low = float(price_tail.iloc[-1]) < float(price_tail.min()) * 1.001
    wt_higher_low = float(wt_tail.iloc[-1]) > float(wt_tail.min())
    bullish_div = price_new_low and wt_higher_low and float(wt_tail.iloc[-1]) < OS

    price_new_high = float(price_tail.iloc[-1]) > float(price_tail.max()) * 0.999
    wt_lower_high = float(wt_tail.iloc[-1]) < float(wt_tail.max())
    bearish_div = price_new_high and wt_lower_high and float(wt_tail.iloc[-1]) > OB

    return {"bullish_div": bullish_div, "bearish_div": bearish_div}


def _wt_signal(df: pd.DataFrame, wt_df: pd.DataFrame) -> dict:
    if len(wt_df) < 4:
        return {"action": "flat", "wt1": None, "wt2": None}

    row = wt_df.iloc[-1]
    wt1 = float(row["wt1"]) if not pd.isna(row["wt1"]) else None
    wt2 = float(row["wt2"]) if not pd.isna(row["wt2"]) else None
    cross_above = bool(row["cross_above"])
    cross_below = bool(row["cross_below"])

    div = _detect_divergence(df, wt_df)

    if cross_above and wt1 is not None and wt1 < OS:
        action = "enter_long"
    elif cross_below and wt1 is not None and wt1 > OB:
        action = "enter_short"
    elif wt1 is not None and wt2 is not None and wt1 > wt2 and wt1 < 0:
        action = "hold_long"
    elif wt1 is not None and wt2 is not None and wt1 < wt2 and wt1 > 0:
        action = "hold_short"
    else:
        action = "flat"

    zone = "oversold" if wt1 is not None and wt1 < OS else \
           "overbought" if wt1 is not None and wt1 > OB else "neutral"

    return {
        "action": action,
        "wt1": round(wt1, 2) if wt1 is not None else None,
        "wt2": round(wt2, 2) if wt2 is not None else None,
        "zone": zone,
        "cross_above": cross_above,
        "cross_below": cross_below,
        **div,
    }


# ---------------------------------------------------------------------------
# Log helpers
# ---------------------------------------------------------------------------

def load_last_entry(log_path: Path = LOG_PATH) -> dict | None:
    if not log_path.exists():
        return None
    for line in reversed(log_path.read_text(encoding="utf-8").splitlines()):
        line = line.strip()
        if line:
            return json.loads(line)
    return None


def log_entry(entry: dict, log_path: Path = LOG_PATH) -> None:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    rows: list[dict] = []
    if log_path.exists():
        for line in log_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(row, dict):
                rows.append(row)

    entry_date = entry.get("date")
    deduped: list[dict] = []
    replaced = False
    for row in rows:
        if row.get("date") == entry_date:
            if not replaced:
                deduped.append(entry)
                replaced = True
            continue
        deduped.append(row)
    if not replaced:
        deduped.append(entry)

    log_path.write_text("".join(json.dumps(r) + "\n" for r in deduped), encoding="utf-8")


def compute_signal(primary_df: pd.DataFrame, comparison_df: pd.DataFrame) -> dict:
    today = date.today().isoformat()

    primary_wt = compute_wavetrend(primary_df)
    comparison_wt = compute_wavetrend(comparison_df)

    primary_sig = _wt_signal(primary_df, primary_wt)
    comparison_sig = _wt_signal(comparison_df, comparison_wt)

    return {
        "date": today,
        "execution_mode": "shadow_only",
        "data_source": data_source(),
        "vix_context": fetch_vix_context(),
        "primary": {
            "symbol": PRIMARY_SYMBOL,
            "params": {"n1": N1, "n2": N2, "signal_len": SIGNAL_LEN, "ob": OB, "os": OS},
            **primary_sig,
        },
        "comparison": {
            "symbol": COMPARISON_SYMBOL,
            "params": {"n1": N1, "n2": N2, "signal_len": SIGNAL_LEN, "ob": OB, "os": OS},
            **comparison_sig,
        },
        "paper_rules": {
            "minimum_forward_days": 30,
            "minimum_signals_before_review": 10,
            "live_execution_allowed": False,
            "note": "WaveTrend = core of Market Cipher B. Oversold cross + bullish divergence = highest confidence.",
        },
    }


def print_report(entry: dict, prev: dict | None = None) -> None:
    print("\n" + "=" * 62)
    print(f"WaveTrend Shadow Signal | {entry['date']}")
    print("=" * 62)
    for key in ("primary", "comparison"):
        s = entry[key]
        wt1 = s.get("wt1")
        wt2 = s.get("wt2")
        wt1_str = f"{wt1:+.1f}" if wt1 is not None else "n/a"
        wt2_str = f"{wt2:+.1f}" if wt2 is not None else "n/a"
        print(f"\n{s['symbol']}: WT1={wt1_str}  WT2={wt2_str}  zone={s.get('zone')}  action={s['action']}")
        if s.get("bullish_div"):
            print(f"  *** BULLISH DIVERGENCE DETECTED ***")
        if s.get("bearish_div"):
            print(f"  *** BEARISH DIVERGENCE DETECTED ***")
        if s.get("cross_above"):
            print(f"  Cross ABOVE signal line")
        if s.get("cross_below"):
            print(f"  Cross BELOW signal line")
    vix = entry.get("vix_context", {})
    if vix.get("close"):
        print(f"\nVIX: {vix['close']} ({vix.get('regime')})")
    if prev:
        print(f"Previous: {prev.get('date')} primary={prev.get('primary', {}).get('action')}")
    print("\nMode: shadow_only — no orders, no broker calls\n")


def main() -> int:
    print("Fetching OHLCV data...")
    primary_df = fetch_ohlcv(PRIMARY_SYMBOL)
    comparison_df = fetch_ohlcv(COMPARISON_SYMBOL)
    entry = compute_signal(primary_df, comparison_df)
    prev = load_last_entry()
    print_report(entry, prev)
    maybe_send_shadow_alert("WaveTrend", entry, prev)
    log_entry(entry)
    print(f"Logged to {LOG_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

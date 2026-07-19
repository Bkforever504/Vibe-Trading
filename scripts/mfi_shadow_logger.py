"""
Daily shadow signal logger for Money Flow Index (MFI).

No trading. No Alpaca orders. Appends to data/mfi_shadow_log.jsonl

MFI (Chaikin, period=14):
  - Typical Price (TP) = (High + Low + Close) / 3
  - Raw Money Flow = TP * Volume
  - Positive MF = sum of RMF on days where TP > prev TP
  - Negative MF = sum of RMF on days where TP < prev TP
  - MFI = 100 - (100 / (1 + Positive MF / Negative MF))
  - Overbought: MFI > 80 → bear bias (selling pressure)
  - Oversold:   MFI < 20 → bull bias (buying pressure)
  - Divergence: price new high + MFI lower high = bearish; price new low + MFI higher low = bullish

Evidence basis (MoonDev sma_variations backtest, 2025-05-01 to 2025-09-04):
  - Basic SMA (no filter): Sharpe 1.51, 78% return
  - SMA + MFI filter:      Sharpe 2.10-2.37, manageable drawdown
  Same SMA-crossover pattern is what Flip Bot uses on VWAP/EMA entry.

Primary:    SPY daily  period=14
Comparison: QQQ daily  period=14

Run daily at market close (15:20 ET) via Windows Task Scheduler.
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

LOG_PATH = ROOT / "data" / "mfi_shadow_log.jsonl"
PRIMARY_SYMBOL = "SPY"
COMPARISON_SYMBOL = "QQQ"
MFI_PERIOD = 14
OVERBOUGHT = 80.0
OVERSOLD = 20.0


# ---------------------------------------------------------------------------
# MFI math (pure Pandas — no talib required)
# ---------------------------------------------------------------------------

def compute_mfi(df: pd.DataFrame, period: int = MFI_PERIOD) -> pd.Series:
    """Return MFI series. df must have columns: high, low, close, volume."""
    tp = (df["high"] + df["low"] + df["close"]) / 3
    rmf = tp * df["volume"]

    pos_mf = rmf.where(tp > tp.shift(1), 0.0)
    neg_mf = rmf.where(tp < tp.shift(1), 0.0)

    pos_sum = pos_mf.rolling(period).sum()
    neg_sum = neg_mf.rolling(period).sum()

    # Avoid NaN when one side is zero: clamp to 100 (all positive) or 0 (all negative)
    pos_dominated = (neg_sum == 0) & (pos_sum > 0)
    neg_dominated = (pos_sum == 0) & (neg_sum > 0)
    safe_neg = neg_sum.where(neg_sum != 0, 1.0)
    mfr = pos_sum / safe_neg
    mfi = 100.0 - (100.0 / (1.0 + mfr))
    mfi = mfi.where(~pos_dominated, 100.0)
    mfi = mfi.where(~neg_dominated, 0.0)
    return mfi


def _mfi_signal(df: pd.DataFrame, symbol: str) -> dict:
    """Compute MFI signal dict for one symbol's OHLCV DataFrame."""
    if len(df) < MFI_PERIOD + 5:
        return {"symbol": symbol, "status": "insufficient_data", "action": "flat", "mfi": None}

    mfi = compute_mfi(df)
    close = df["close"]

    current = float(mfi.iloc[-1]) if not pd.isna(mfi.iloc[-1]) else None
    prev = float(mfi.iloc[-2]) if not pd.isna(mfi.iloc[-2]) else None

    if current is None:
        return {"symbol": symbol, "status": "no_data", "action": "flat", "mfi": None}

    # Direction
    rising = (prev is not None and current > prev)
    falling = (prev is not None and current < prev)

    # Zone
    if current >= OVERBOUGHT:
        zone = "overbought"
    elif current <= OVERSOLD:
        zone = "oversold"
    else:
        zone = "neutral"

    # Divergence (last 10 bars): price new high / MFI lower high = bearish div
    lookback = 10
    recent_close = close.iloc[-lookback:]
    recent_mfi = mfi.iloc[-lookback:]
    price_new_high = float(close.iloc[-1]) >= float(recent_close.max())
    price_new_low = float(close.iloc[-1]) <= float(recent_close.min())
    mfi_lower_high = current < float(recent_mfi.max())
    mfi_higher_low = current > float(recent_mfi.min())

    bearish_div = price_new_high and mfi_lower_high and zone != "oversold"
    bullish_div = price_new_low and mfi_higher_low and zone != "overbought"

    # Action
    if zone == "oversold" and rising:
        action = "bull_bias"
    elif zone == "overbought" and falling:
        action = "bear_bias"
    elif bullish_div:
        action = "bullish_divergence"
    elif bearish_div:
        action = "bearish_divergence"
    else:
        action = "flat"

    return {
        "symbol": symbol,
        "status": "ok",
        "mfi": round(current, 2),
        "mfi_prev": round(prev, 2) if prev is not None else None,
        "zone": zone,
        "rising": rising,
        "falling": falling,
        "action": action,
        "bullish_divergence": bullish_div,
        "bearish_divergence": bearish_div,
        "params": {"period": MFI_PERIOD, "overbought": OVERBOUGHT, "oversold": OVERSOLD},
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
            try:
                return json.loads(line)
            except json.JSONDecodeError:
                continue
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


# ---------------------------------------------------------------------------
# Main signal assembly
# ---------------------------------------------------------------------------

def compute_signal(primary_df: pd.DataFrame, comparison_df: pd.DataFrame) -> dict:
    today = date.today().isoformat()
    primary_sig = _mfi_signal(primary_df, PRIMARY_SYMBOL)
    comparison_sig = _mfi_signal(comparison_df, COMPARISON_SYMBOL)

    # Consensus: both symbols agree on direction
    p_action = primary_sig.get("action", "flat")
    c_action = comparison_sig.get("action", "flat")
    both_bull = p_action in {"bull_bias", "bullish_divergence"} and c_action in {"bull_bias", "bullish_divergence"}
    both_bear = p_action in {"bear_bias", "bearish_divergence"} and c_action in {"bear_bias", "bearish_divergence"}
    consensus = "bull" if both_bull else "bear" if both_bear else "none"

    return {
        "date": today,
        "execution_mode": "shadow_only",
        "data_source": data_source(),
        "vix_context": fetch_vix_context(),
        "primary": primary_sig,
        "comparison": comparison_sig,
        "consensus": consensus,
        "evidence_basis": "MoonDev sma_variations backtest: MFI filter raised Sharpe 1.51→2.37 on same SMA crossover pattern Flip Bot uses.",
        "paper_rules": {
            "minimum_forward_days": 30,
            "minimum_signals_before_review": 10,
            "live_execution_allowed": False,
            "note": "MFI oversold+rising = potential Flip Bot bull entry confirmation. MFI overbought+falling = bear bias.",
        },
    }


def print_report(entry: dict, prev: dict | None = None) -> None:
    print("\n" + "=" * 62)
    print(f"MFI Shadow Signal | {entry['date']}")
    print("=" * 62)
    for key in ("primary", "comparison"):
        s = entry[key]
        mfi = s.get("mfi")
        mfi_str = f"{mfi:.1f}" if mfi is not None else "n/a"
        print(
            f"\n{s['symbol']}: MFI={mfi_str}  zone={s.get('zone','?')}  "
            f"action={s.get('action','?')}  "
            f"rising={s.get('rising')}  falling={s.get('falling')}"
        )
        if s.get("bullish_divergence"):
            print("  *** BULLISH DIVERGENCE: price new low, MFI higher low ***")
        if s.get("bearish_divergence"):
            print("  *** BEARISH DIVERGENCE: price new high, MFI lower high ***")
    print(f"\nConsensus: {entry.get('consensus', 'none')}")
    vix = entry.get("vix_context", {})
    if vix.get("close"):
        print(f"VIX: {vix['close']} ({vix.get('regime')})")
    if prev:
        print(f"Previous: {prev.get('date')} consensus={prev.get('consensus')}")
    print("\nMode: shadow_only — no orders, no broker calls\n")


def main() -> int:
    print("Fetching OHLCV data...")
    primary_df = fetch_ohlcv(PRIMARY_SYMBOL)
    comparison_df = fetch_ohlcv(COMPARISON_SYMBOL)
    entry = compute_signal(primary_df, comparison_df)
    prev = load_last_entry()
    print_report(entry, prev)
    maybe_send_shadow_alert("MFI", entry, prev)
    log_entry(entry)
    print(f"Logged to {LOG_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

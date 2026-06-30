"""
Daily shadow signal logger for TTM Squeeze Momentum strategy.

No trading. No Alpaca orders. Appends to data/ttm_squeeze_shadow_log.jsonl

TTM Squeeze (John Carter "Mastering the Trade" ch.11, LazyBear TradingView version):
  - Squeeze ON  = Bollinger Bands inside Keltner Channels → low vol coiling
  - Squeeze OFF = first release bar → momentum direction = trade direction
  - Bull entry: first SQZ_OFF bar with momentum > 0 and rising
  - Bear entry: first SQZ_OFF bar with momentum < 0 and falling
  - Exit: momentum color flip (momentum direction reverses) OR max_hold bars

Primary:    QQQ daily  BB(20,2) KC(20,1.5)
Comparison: SPY daily  BB(20,2) KC(20,1.5)

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

LOG_PATH = ROOT / "data" / "ttm_squeeze_shadow_log.jsonl"
PRIMARY_SYMBOL = "QQQ"
COMPARISON_SYMBOL = "SPY"


# ---------------------------------------------------------------------------
# TTM Squeeze math (pure NumPy/Pandas — no pandas_ta required)
# ---------------------------------------------------------------------------

def _linreg_endpoint(series: pd.Series, length: int) -> pd.Series:
    """Rolling linear regression value at last bar (same as TradingView linreg())."""
    x = np.arange(length, dtype=float)

    def _calc(y: np.ndarray) -> float:
        if np.any(np.isnan(y)):
            return np.nan
        slope, intercept = np.polyfit(x, y, 1)
        return intercept + slope * (length - 1)

    return series.rolling(length).apply(_calc, raw=True)


def compute_squeeze(
    df: pd.DataFrame,
    bb_length: int = 20,
    bb_mult: float = 2.0,
    kc_length: int = 20,
    kc_mult: float = 1.5,
) -> pd.DataFrame:
    """Return DataFrame with squeeze state and momentum columns."""
    close = df["close"]
    high = df["high"]
    low = df["low"]

    # Bollinger Bands
    bb_mid = close.rolling(bb_length).mean()
    bb_std = close.rolling(bb_length).std(ddof=0)
    bb_upper = bb_mid + bb_mult * bb_std
    bb_lower = bb_mid - bb_mult * bb_std

    # Keltner Channels (True Range based)
    prev_close = close.shift(1)
    tr = pd.concat([
        high - low,
        (high - prev_close).abs(),
        (low - prev_close).abs(),
    ], axis=1).max(axis=1)
    kc_mid = close.rolling(kc_length).mean()
    kc_atr = tr.rolling(kc_length).mean()
    kc_upper = kc_mid + kc_mult * kc_atr
    kc_lower = kc_mid - kc_mult * kc_atr

    # Squeeze states
    sqz_on = (bb_lower > kc_lower) & (bb_upper < kc_upper)
    sqz_off = (bb_lower < kc_lower) & (bb_upper > kc_upper)
    no_sqz = ~sqz_on & ~sqz_off

    # Momentum (LazyBear version: linreg of close vs midpoint)
    hh = high.rolling(kc_length).max()
    ll = low.rolling(kc_length).min()
    delta = close - ((hh + ll) / 2 + close.rolling(kc_length).mean()) / 2
    momentum = _linreg_endpoint(delta, kc_length)

    return pd.DataFrame({
        "close": close,
        "sqz_on": sqz_on,
        "sqz_off": sqz_off,
        "no_sqz": no_sqz,
        "momentum": momentum,
    }, index=df.index)


def _squeeze_signal(sqz_df: pd.DataFrame) -> dict:
    """Derive current signal from squeeze DataFrame."""
    if len(sqz_df) < 3:
        return {"action": "flat", "sqz_state": "unknown", "momentum": None}

    row = sqz_df.iloc[-1]
    prev = sqz_df.iloc[-2]

    mom = float(row["momentum"]) if not pd.isna(row["momentum"]) else None
    mom_prev = float(prev["momentum"]) if not pd.isna(prev["momentum"]) else None
    mom_rising = (mom is not None and mom_prev is not None and mom > mom_prev)
    mom_falling = (mom is not None and mom_prev is not None and mom < mom_prev)

    if row["sqz_on"]:
        sqz_state = "on"
    elif row["sqz_off"]:
        sqz_state = "off"
    else:
        sqz_state = "none"

    # First squeeze release bar: prev was ON, current is OFF
    first_release = bool(prev["sqz_on"] and row["sqz_off"])

    if first_release and mom is not None and mom > 0 and mom_rising:
        action = "enter_long"
    elif first_release and mom is not None and mom < 0 and mom_falling:
        action = "enter_short"
    elif row["sqz_off"] and mom is not None and mom > 0 and mom_rising:
        action = "hold_long"
    elif row["sqz_off"] and mom is not None and mom < 0 and mom_falling:
        action = "hold_short"
    else:
        action = "flat"

    return {
        "action": action,
        "sqz_state": sqz_state,
        "first_release": first_release,
        "momentum": round(mom, 4) if mom is not None else None,
        "momentum_rising": mom_rising,
        "momentum_falling": mom_falling,
    }


# ---------------------------------------------------------------------------
# Log helpers (same pattern as williams_r_shadow_logger.py)
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

    primary_sqz = compute_squeeze(primary_df)
    comparison_sqz = compute_squeeze(comparison_df)

    primary_sig = _squeeze_signal(primary_sqz)
    comparison_sig = _squeeze_signal(comparison_sqz)

    # Count recent squeeze bars for context
    recent = primary_sqz.tail(10)
    consecutive_sqz_on = int(recent["sqz_on"].iloc[::-1].cumprod().sum())

    return {
        "date": today,
        "execution_mode": "shadow_only",
        "data_source": data_source(),
        "vix_context": fetch_vix_context(),
        "primary": {
            "symbol": PRIMARY_SYMBOL,
            **primary_sig,
            "consecutive_sqz_on_bars": consecutive_sqz_on,
            "params": {"bb_length": 20, "bb_mult": 2.0, "kc_length": 20, "kc_mult": 1.5},
        },
        "comparison": {
            "symbol": COMPARISON_SYMBOL,
            **comparison_sig,
            "params": {"bb_length": 20, "bb_mult": 2.0, "kc_length": 20, "kc_mult": 1.5},
        },
        "paper_rules": {
            "minimum_forward_days": 30,
            "minimum_signals_before_review": 10,
            "live_execution_allowed": False,
            "note": "Squeeze release + positive momentum = potential Flip Bot entry confirmation.",
        },
    }


def print_report(entry: dict, prev: dict | None = None) -> None:
    print("\n" + "=" * 62)
    print(f"TTM Squeeze Shadow Signal | {entry['date']}")
    print("=" * 62)
    for key in ("primary", "comparison"):
        s = entry[key]
        sqz = s["sqz_state"].upper()
        mom = s["momentum"]
        mom_str = f"{mom:+.4f}" if mom is not None else "n/a"
        print(f"\n{s['symbol']}: sqz={sqz}  action={s['action']}  mom={mom_str}  rising={s.get('momentum_rising')}")
        if s.get("first_release"):
            print(f"  *** FIRST SQUEEZE RELEASE BAR ***")
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
    maybe_send_shadow_alert("TTM Squeeze", entry, prev)
    log_entry(entry)
    print(f"Logged to {LOG_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

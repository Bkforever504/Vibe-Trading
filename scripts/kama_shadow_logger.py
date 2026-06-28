"""
Daily shadow signal logger for the KAMA trend QQQ paper candidate.

No trading. No Alpaca calls. Appends forward-test signals to:
data/kama_shadow_log.jsonl

Best sweep result: QQQ 2018-2024, conf 9.1, PF 2.53, OOS PF 3.11, WF 0.80, DD 21.9%.
Translated from everget/kaufman_adaptive_moving_average.pine (GPL-3.0).
"""
from __future__ import annotations

import importlib.util
import json
import sys
import warnings
from datetime import date, timedelta
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

KAMA_STRATEGY_PATH = ROOT / "research" / "pine_strategy_lab" / "examples" / "kama_trend_python.py"


def _load_kama_strategy():
    spec = importlib.util.spec_from_file_location("kama_trend_python", KAMA_STRATEGY_PATH)
    if spec is None or spec.loader is None:
        raise ImportError(f"Cannot load KAMA strategy from {KAMA_STRATEGY_PATH}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


kama_strategy = _load_kama_strategy()

SYMBOL = "QQQ"
LOG_PATH = ROOT / "data" / "kama_shadow_log.jsonl"

# Top sweep winner — QQQ 2018-2024, conf 9.1, PF 2.53, OOS PF 3.11
PRIMARY_PARAMS = {
    "length": 14,
    "fast_length": 3,
    "slow_length": 20,
    "slope_lookback": 3,
}
PRIMARY_CONFIDENCE = 9.1

# Second-best — conf 9.1, PF 2.03, OOS PF 3.01, lower DD (20.6%)
COMPARISON_PARAMS = {
    "length": 20,
    "fast_length": 2,
    "slow_length": 30,
    "slope_lookback": 5,
}
COMPARISON_CONFIDENCE = 9.1


def fetch_ohlcv(symbol: str = SYMBOL, lookback_days: int = 520) -> pd.DataFrame:
    try:
        import yfinance as yf
    except ImportError as exc:
        raise ImportError("yfinance required: uv add yfinance") from exc

    today = date.today()
    start = (today - timedelta(days=lookback_days)).strftime("%Y-%m-%d")
    end = (today + timedelta(days=1)).strftime("%Y-%m-%d")
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        df = yf.download(symbol, start=start, end=end, progress=False, auto_adjust=True)
    if df.empty:
        raise ValueError(f"No price data for {symbol} {start}:{end}")
    df.columns = [c.lower() if isinstance(c, str) else c[0].lower() for c in df.columns]
    return df[["open", "high", "low", "close", "volume"]].dropna().copy()


def compute_signal_from_ohlcv(ohlcv: pd.DataFrame, symbol: str = SYMBOL, as_of: str | None = None) -> dict:
    warmup = max(PRIMARY_PARAMS["length"], PRIMARY_PARAMS["slope_lookback"]) + 5
    if len(ohlcv) < warmup:
        raise ValueError(f"Insufficient bars for KAMA warmup: {len(ohlcv)} < {warmup}")

    df = ohlcv.copy()
    df.columns = [str(col).lower() for col in df.columns]
    as_of_date = as_of or _last_date(df)

    primary_signals = kama_strategy.strategy(df, **PRIMARY_PARAMS)
    comparison_signals = kama_strategy.strategy(df, **COMPARISON_PARAMS)
    features = _features(df)

    return {
        "date": as_of_date,
        "symbol": symbol,
        "execution_mode": "shadow_only",
        "primary_setup": _setup_payload(
            name="kama_trend_fast3_slow20_slope3",
            params=PRIMARY_PARAMS,
            confidence=PRIMARY_CONFIDENCE,
            signals=primary_signals,
        ),
        "comparison_setup": _setup_payload(
            name="kama_trend_fast2_slow30_slope5",
            params=COMPARISON_PARAMS,
            confidence=COMPARISON_CONFIDENCE,
            signals=comparison_signals,
        ),
        "features": features,
        "paper_rules": {
            "minimum_forward_days": 30,
            "minimum_signals_before_review": 10,
            "live_execution_allowed": False,
        },
    }


def _setup_payload(name: str, params: dict, confidence: float, signals: pd.Series) -> dict:
    current = int(signals.iloc[-1])
    previous = int(signals.iloc[-2]) if len(signals) >= 2 else 0
    if current == 1 and previous == 0:
        action = "enter_long"
    elif current == 1:
        action = "hold_long"
    else:
        action = "flat"
    return {
        "name": name,
        "action": action,
        "in_position": current == 1,
        "previous_signal": previous,
        "current_signal": current,
        "confidence": confidence,
        "params": dict(params),
    }


def _features(ohlcv: pd.DataFrame) -> dict:
    close = ohlcv["close"]
    params = PRIMARY_PARAMS
    kama_vals = kama_strategy._kama(
        close,
        length=params["length"],
        fast_length=params["fast_length"],
        slow_length=params["slow_length"],
    )
    kama_now = float(kama_vals[-1])
    kama_prev = float(kama_vals[-1 - params["slope_lookback"]])

    # Efficiency Ratio at last bar
    length = params["length"]
    prices = close.to_numpy(dtype=float)
    direction = abs(prices[-1] - prices[-1 - length])
    import numpy as np
    volatility = float(np.sum(np.abs(np.diff(prices[-1 - length:]))))
    er = direction / volatility if volatility > 0 else 0.0

    return {
        "close": round(float(close.iloc[-1]), 4),
        "kama": round(kama_now, 4),
        "kama_slope_positive": bool(kama_now > kama_prev),
        "above_kama": bool(float(close.iloc[-1]) > kama_now),
        "efficiency_ratio": round(er, 4),
    }


def _last_date(df: pd.DataFrame) -> str:
    idx = df.index[-1]
    return idx.date().isoformat() if hasattr(idx, "date") else str(idx)[:10]


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

    log_path.write_text("".join(json.dumps(row) + "\n" for row in deduped), encoding="utf-8")


def print_report(entry: dict, prev: dict | None = None) -> None:
    print("\n" + "=" * 62)
    print(f"KAMA QQQ Shadow Signal | {entry['date']}")
    print("=" * 62)
    f = entry["features"]
    print(f"Close: {f['close']:.2f} | KAMA: {f['kama']:.2f} | ER: {f['efficiency_ratio']:.3f}")
    print(f"Above KAMA: {f['above_kama']} | Slope+: {f['kama_slope_positive']}")
    print()
    for key, label in [("primary_setup", "Primary"), ("comparison_setup", "Comparison")]:
        setup = entry[key]
        print(f"{label}: {setup['name']} | conf {setup['confidence']:.1f} | {setup['action']}")
    if prev is not None:
        print(f"\nPrevious log: {prev.get('date')} primary={prev.get('primary_setup', {}).get('action')}")
    print("\nMode: shadow_only - no orders, no broker calls\n")


def main() -> int:
    df = fetch_ohlcv(SYMBOL)
    entry = compute_signal_from_ohlcv(df, symbol=SYMBOL)
    prev = load_last_entry(LOG_PATH)
    print_report(entry, prev)
    log_entry(entry, LOG_PATH)
    print(f"Logged to {LOG_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

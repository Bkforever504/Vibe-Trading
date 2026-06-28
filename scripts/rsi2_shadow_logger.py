"""
Daily shadow signal logger for the RSI-2 QQQ mean-reversion candidate.

No trading. No Alpaca calls. This only appends forward-test signals to:
data/rsi2_shadow_log.jsonl

Primary setup is the exact Handiko/Connors-style translation:
- QQQ only
- RSI(2) < 15
- Close above EMA(200)
- Exit on close above prior high

Comparison setup tracks the higher-confidence derived SMA-exit variant from
the sweep report so we can compare live behavior before any execution review.
"""
from __future__ import annotations

import json
import sys
import warnings
from datetime import date, timedelta
import importlib.util
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

RSI2_STRATEGY_PATH = ROOT / "research" / "pine_strategy_lab" / "examples" / "rsi2_mean_reversion_python.py"


def _load_rsi2_strategy():
    spec = importlib.util.spec_from_file_location("rsi2_mean_reversion_python", RSI2_STRATEGY_PATH)
    if spec is None or spec.loader is None:
        raise ImportError(f"Cannot load RSI-2 strategy from {RSI2_STRATEGY_PATH}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


rsi2_strategy = _load_rsi2_strategy()


SYMBOL = "QQQ"
LOG_PATH = ROOT / "data" / "rsi2_shadow_log.jsonl"
PRIMARY_PARAMS = {
    "rsi_threshold": 15,
    "trend_window": 200,
    "exit_sma": 5,
    "exit_mode": "prior_high",
}
COMPARISON_PARAMS = {
    "rsi_threshold": 10,
    "trend_window": 200,
    "exit_sma": 5,
    "exit_mode": "sma",
}
PRIMARY_CONFIDENCE = 8.7
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
    if len(ohlcv) < PRIMARY_PARAMS["trend_window"] + PRIMARY_PARAMS["exit_sma"] + 5:
        raise ValueError("Insufficient bars for RSI-2 warmup")

    df = ohlcv.copy()
    df.columns = [str(col).lower() for col in df.columns]
    as_of_date = as_of or _last_date(df)

    primary_signals = rsi2_strategy.strategy(df, **PRIMARY_PARAMS)
    comparison_signals = rsi2_strategy.strategy(df, **COMPARISON_PARAMS)
    features = _features(df)

    return {
        "date": as_of_date,
        "symbol": symbol,
        "execution_mode": "shadow_only",
        "primary_setup": _setup_payload(
            name="rsi2_prior_high_source",
            params=PRIMARY_PARAMS,
            confidence=PRIMARY_CONFIDENCE,
            signals=primary_signals,
        ),
        "comparison_setup": _setup_payload(
            name="rsi2_sma_exit_derived",
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
    high = ohlcv["high"]
    rsi2 = rsi2_strategy._rsi(close, window=2)
    ema200 = rsi2_strategy._ema(close, span=200)
    sma5 = close.rolling(5).mean()
    return {
        "close": round(float(close.iloc[-1]), 4),
        "prior_high": round(float(high.iloc[-2]), 4),
        "rsi2": round(float(rsi2.iloc[-1]), 4),
        "ema200": round(float(ema200.iloc[-1]), 4),
        "sma5": round(float(sma5.iloc[-1]), 4),
        "above_ema200": bool(close.iloc[-1] > ema200.iloc[-1]),
        "above_prior_high": bool(close.iloc[-1] > high.iloc[-2]),
        "above_sma5": bool(close.iloc[-1] > sma5.iloc[-1]),
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
    print(f"RSI-2 QQQ Shadow Signal | {entry['date']}")
    print("=" * 62)
    f = entry["features"]
    print(f"Close: {f['close']:.2f} | RSI2: {f['rsi2']:.2f} | EMA200: {f['ema200']:.2f}")
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

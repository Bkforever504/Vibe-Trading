"""
Daily shadow signal logger for the Williams %R oversold bounce paper candidate.

No trading. No Alpaca calls. Appends forward-test signals to:
data/williams_r_shadow_log.jsonl

Top sweep results (intake-008):
  Primary:    QQQ 2018-2024, WR(2), entry=-90, exit=-50, max_hold=5, no trend filter
              conf 10.0, PF 2.19, OOS PF 2.52, WF 1.00, DD 12.7%, 114 trades
  Comparison: SPY 2010-2024, WR(3), entry=-90, exit=-50, max_hold=5, SMA(200) filter
              conf 10.0, PF 1.91, OOS PF 2.04, WF 1.00, DD 11.4%, 126 trades

Overlap note: signal family closely related to RSI-2 QQQ (both oversold mean-reversion).
Run overlap analysis before promoting to live execution.
"""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.market_data import fetch_ohlcv, data_source, fetch_vix_context
from scripts.shadow_alerts import maybe_send_shadow_alert

WR_STRATEGY_PATH = ROOT / "research" / "pine_strategy_lab" / "examples" / "williams_r_oversold_python.py"


def _load_wr_strategy():
    spec = importlib.util.spec_from_file_location("williams_r_oversold_python", WR_STRATEGY_PATH)
    if spec is None or spec.loader is None:
        raise ImportError(f"Cannot load Williams %R strategy from {WR_STRATEGY_PATH}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


wr_strategy = _load_wr_strategy()

PRIMARY_SYMBOL = "QQQ"
COMPARISON_SYMBOL = "SPY"
LOG_PATH = ROOT / "data" / "williams_r_shadow_log.jsonl"

# Top QQQ row — conf 10.0, PF 2.19, OOS PF 2.52, WF 1.00, DD 12.7%, 114 trades
PRIMARY_PARAMS = {
    "wr_window": 2,
    "entry_threshold": -90,
    "exit_threshold": -50,
    "max_hold": 5,
    "trend_window": 0,
}
PRIMARY_CONFIDENCE = 10.0

# Top SPY row — conf 10.0, PF 1.91, OOS PF 2.04, WF 1.00, DD 11.4%, 126 trades
COMPARISON_PARAMS = {
    "wr_window": 3,
    "entry_threshold": -90,
    "exit_threshold": -50,
    "max_hold": 5,
    "trend_window": 200,
}
COMPARISON_CONFIDENCE = 10.0



def compute_signal_from_ohlcv(
    primary_ohlcv: pd.DataFrame,
    comparison_ohlcv: pd.DataFrame,
    as_of: str | None = None,
) -> dict:
    warmup = max(PRIMARY_PARAMS["wr_window"], PRIMARY_PARAMS["trend_window"] or 0) + 5
    if len(primary_ohlcv) < warmup:
        raise ValueError(f"Insufficient bars for WR warmup: {len(primary_ohlcv)} < {warmup}")

    primary_df = primary_ohlcv.copy()
    primary_df.columns = [str(col).lower() for col in primary_df.columns]
    comparison_df = comparison_ohlcv.copy()
    comparison_df.columns = [str(col).lower() for col in comparison_df.columns]

    as_of_date = as_of or _last_date(primary_df)

    primary_signals = wr_strategy.strategy(primary_df, **PRIMARY_PARAMS)
    comparison_signals = wr_strategy.strategy(comparison_df, **COMPARISON_PARAMS)

    return {
        "date": as_of_date,
        "primary_symbol": PRIMARY_SYMBOL,
        "comparison_symbol": COMPARISON_SYMBOL,
        "execution_mode": "shadow_only",
        "data_source": data_source(),
        "vix_context": fetch_vix_context(),
        "primary_setup": _setup_payload(
            name="wr2_qqq_no_trend",
            symbol=PRIMARY_SYMBOL,
            params=PRIMARY_PARAMS,
            confidence=PRIMARY_CONFIDENCE,
            signals=primary_signals,
            ohlcv=primary_df,
        ),
        "comparison_setup": _setup_payload(
            name="wr3_spy_sma200",
            symbol=COMPARISON_SYMBOL,
            params=COMPARISON_PARAMS,
            confidence=COMPARISON_CONFIDENCE,
            signals=comparison_signals,
            ohlcv=comparison_df,
        ),
        "paper_rules": {
            "minimum_forward_days": 30,
            "minimum_signals_before_review": 10,
            "live_execution_allowed": False,
            "overlap_review_required": True,
            "overlap_note": "Compare signals vs RSI-2 QQQ before promoting. Both are oversold mean-reversion.",
        },
    }


def _setup_payload(
    name: str,
    symbol: str,
    params: dict,
    confidence: float,
    signals: pd.Series,
    ohlcv: pd.DataFrame,
) -> dict:
    current = int(signals.iloc[-1])
    previous = int(signals.iloc[-2]) if len(signals) >= 2 else 0
    if current == 1 and previous == 0:
        action = "enter_long"
    elif current == 1:
        action = "hold_long"
    else:
        action = "flat"

    wr = wr_strategy._williams_r(ohlcv, params["wr_window"])
    wr_now = float(wr.iloc[-1]) if not pd.isna(wr.iloc[-1]) else float("nan")

    trend_ok = None
    if params.get("trend_window", 0):
        sma = ohlcv["close"].rolling(params["trend_window"]).mean()
        trend_ok = bool(ohlcv["close"].iloc[-1] > sma.iloc[-1])

    return {
        "name": name,
        "symbol": symbol,
        "action": action,
        "in_position": current == 1,
        "previous_signal": previous,
        "current_signal": current,
        "confidence": confidence,
        "wr_now": round(wr_now, 2),
        "trend_filter_active": params.get("trend_window", 0) > 0,
        "above_trend_sma": trend_ok,
        "params": dict(params),
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
    print(f"Williams %R Shadow Signal | {entry['date']}")
    print("=" * 62)
    for key, label in [("primary_setup", "Primary"), ("comparison_setup", "Comparison")]:
        s = entry[key]
        print(f"\n{label}: {s['name']} ({s['symbol']})")
        print(f"  WR now: {s['wr_now']:.1f} | Action: {s['action']} | Conf: {s['confidence']:.1f}")
        if s["trend_filter_active"]:
            print(f"  Above SMA: {s['above_trend_sma']}")
    if prev is not None:
        print(f"\nPrevious log: {prev.get('date')} primary={prev.get('primary_setup', {}).get('action')}")
    print("\nMode: shadow_only - no orders, no broker calls")
    print("Overlap review required before execution\n")


def main() -> int:
    primary_df = fetch_ohlcv(PRIMARY_SYMBOL)
    comparison_df = fetch_ohlcv(COMPARISON_SYMBOL)
    entry = compute_signal_from_ohlcv(primary_df, comparison_df)
    prev = load_last_entry(LOG_PATH)
    print_report(entry, prev)
    maybe_send_shadow_alert("Williams %R QQQ+SPY", entry, prev)
    log_entry(entry, LOG_PATH)
    print(f"Logged to {LOG_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

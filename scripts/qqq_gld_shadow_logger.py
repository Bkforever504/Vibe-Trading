"""
Weekly shadow signal logger for the QQQ/GLD rotation paper candidate.

No trading. No Alpaca calls. Appends forward-test signals to:
data/qqq_gld_shadow_log.jsonl

Validated intake-007 nonleveraged variant:
  QQQ 2018-2024, lookback=40 trading days
  conf 9.0, PF 4.24, OOS PF 5.64, WF 0.80, DD 24.3%, 35 trades

Important: the TQQQ leveraged rows were rejected for high drawdown. This
logger intentionally tracks QQQ vs GLD only.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.market_data import fetch_close as _market_fetch_close, data_source
PRIMARY_SYMBOL = "QQQ"
DEFENSIVE_SYMBOL = "GLD"
LOOKBACK_DAYS = 40
CONFIDENCE = 9.0
LOG_PATH = ROOT / "data" / "qqq_gld_shadow_log.jsonl"


def fetch_close(symbols: list[str], lookback_days: int = 220) -> pd.DataFrame:
    return _market_fetch_close(symbols, lookback_days=lookback_days * 2)


def compute_signal_from_close(
    close: pd.DataFrame,
    lookback_days: int = LOOKBACK_DAYS,
    as_of: str | None = None,
) -> dict:
    required = lookback_days + 2
    if len(close) < required:
        raise ValueError(f"Insufficient bars: {len(close)} < {required}")
    if PRIMARY_SYMBOL not in close.columns or DEFENSIVE_SYMBOL not in close.columns:
        raise ValueError(f"Close data must include {PRIMARY_SYMBOL} and {DEFENSIVE_SYMBOL}")

    current = close.iloc[-1]
    base = close.iloc[-(lookback_days + 1)]
    primary_ret = float(current[PRIMARY_SYMBOL] / base[PRIMARY_SYMBOL] - 1)
    defensive_ret = float(current[DEFENSIVE_SYMBOL] / base[DEFENSIVE_SYMBOL] - 1)
    selected = PRIMARY_SYMBOL if primary_ret > defensive_ret else DEFENSIVE_SYMBOL

    prev_current = close.iloc[-2]
    prev_base = close.iloc[-(lookback_days + 2)]
    prev_primary_ret = float(prev_current[PRIMARY_SYMBOL] / prev_base[PRIMARY_SYMBOL] - 1)
    prev_defensive_ret = float(prev_current[DEFENSIVE_SYMBOL] / prev_base[DEFENSIVE_SYMBOL] - 1)
    previous_selected = PRIMARY_SYMBOL if prev_primary_ret > prev_defensive_ret else DEFENSIVE_SYMBOL

    if selected == previous_selected:
        action = f"hold_{selected.lower()}"
    else:
        action = f"rotate_to_{selected.lower()}"

    as_of_date = as_of or _last_date(close)
    spread = primary_ret - defensive_ret
    return {
        "date": as_of_date,
        "strategy": "qqq_gld_40d_rotation",
        "execution_mode": "shadow_only",
        "data_source": data_source(),
        "primary_symbol": PRIMARY_SYMBOL,
        "defensive_symbol": DEFENSIVE_SYMBOL,
        "selected": selected,
        "previous_selected": previous_selected,
        "action": action,
        "confidence": CONFIDENCE,
        "lookback_days": lookback_days,
        "returns": {
            PRIMARY_SYMBOL: round(primary_ret, 6),
            DEFENSIVE_SYMBOL: round(defensive_ret, 6),
        },
        "return_spread": round(spread, 6),
        "close_prices": {
            PRIMARY_SYMBOL: round(float(current[PRIMARY_SYMBOL]), 6),
            DEFENSIVE_SYMBOL: round(float(current[DEFENSIVE_SYMBOL]), 6),
        },
        "paper_rules": {
            "minimum_forward_days": 30,
            "minimum_log_rows_before_review": 8,
            "live_execution_allowed": False,
            "leveraged_tqqq_allowed": False,
            "overlap_review_required": True,
            "overlap_note": "Compare holdings vs existing multi-asset momentum rotation before promotion.",
        },
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
    print(f"QQQ/GLD Rotation Shadow Signal | {entry['date']}")
    print("=" * 62)
    print(f"Config: {entry['lookback_days']} trading-day relative momentum")
    print(f"Confidence: {entry['confidence']:.1f}")
    print()
    print("Returns:")
    for symbol, ret in entry["returns"].items():
        marker = " [SELECTED]" if symbol == entry["selected"] else ""
        print(f"  {symbol}: {ret * 100:+.2f}%{marker}")
    print(f"\nAction: {entry['action']}")
    print(f"Selected: {entry['selected']} | Return spread: {entry['return_spread'] * 100:+.2f}%")
    if prev is not None:
        print(f"Previous log: {prev.get('date')} selected={prev.get('selected')}")
    print("\nMode: shadow_only - no orders, no broker calls")
    print("Review requires 30+ forward days and overlap check vs momentum rotation.\n")


def main() -> int:
    close = fetch_close([PRIMARY_SYMBOL, DEFENSIVE_SYMBOL])
    entry = compute_signal_from_close(close)
    prev = load_last_entry(LOG_PATH)
    print_report(entry, prev)
    log_entry(entry, LOG_PATH)
    print(f"Logged to {LOG_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

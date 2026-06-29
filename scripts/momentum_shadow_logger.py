"""
Shadow signal logger for the momentum rotation paper candidate.

Computes the current weekly target holdings and appends to the forward-test log.
No trading. No Alpaca calls. Safe to run as a weekly Windows Task Scheduler job.

Config: 10-asset universe, 12-month lookback, top-2 equal-weight, weekly rebalance.
Run once per week (Monday morning before market open is ideal).
"""
from __future__ import annotations

import json
import sys
from datetime import date
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.market_data import fetch_close, data_source

SYMBOLS = ["SPY", "QQQ", "GLD", "XLE", "TLT", "IWM", "XLK", "XLV", "XLF", "XLI"]
LOOKBACK_MONTHS = 12
LOOKBACK_DAYS = 252
TOP_N = 2
LOG_PATH = Path(__file__).resolve().parent.parent / "data" / "momentum_shadow_log.jsonl"


def compute_current_signal(
    symbols: list[str] = SYMBOLS,
    lookback_days: int = LOOKBACK_DAYS,
    top_n: int = TOP_N,
) -> dict:
    today = date.today()
    universe = fetch_close(symbols, lookback_days=lookback_days * 2)

    if len(universe) < lookback_days + 5:
        raise ValueError(
            f"Insufficient data: {len(universe)} bars available, "
            f"need at least {lookback_days + 5}. Check your internet connection."
        )

    # 12-month momentum: today's close vs close exactly lookback_days trading days ago
    current_close = universe.iloc[-1]
    base_close = universe.iloc[-(lookback_days + 1)]
    momentum_12m: dict[str, float] = ((current_close / base_close) - 1).to_dict()

    # Rank descending; exclude negative-momentum assets (absolute momentum filter)
    ranked = sorted(momentum_12m.items(), key=lambda x: x[1], reverse=True)
    positive = [(sym, ret) for sym, ret in ranked if ret > 0]
    selected = [sym for sym, _ in positive[:top_n]]

    weight = round(1.0 / len(selected), 6) if selected else 0.0
    weights = {sym: weight for sym in selected}

    return {
        "date": today.isoformat(),
        "holdings": selected,
        "weights": weights,
        "close_prices": {sym: round(float(price), 6) for sym, price in current_close.items()},
        "momentum_12m": {sym: round(ret, 6) for sym, ret in momentum_12m.items()},
        "ranked": [(sym, round(ret, 6)) for sym, ret in ranked],
        "in_cash": len(selected) == 0,
        "lookback_months": LOOKBACK_MONTHS,
        "top_n": TOP_N,
        "universe": list(symbols),
        "execution_mode": "shadow_only",
        "data_source": data_source(),
    }


def load_last_entry(log_path: Path) -> dict | None:
    if not log_path.exists():
        return None
    lines = log_path.read_text(encoding="utf-8").strip().splitlines()
    for line in reversed(lines):
        stripped = line.strip()
        if stripped:
            return json.loads(stripped)
    return None


def log_entry(entry: dict, log_path: Path) -> None:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    rows: list[dict] = []
    if log_path.exists():
        for line in log_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                item = json.loads(line)
            except Exception:
                continue
            if isinstance(item, dict):
                rows.append(item)

    entry_date = entry.get("date")
    deduped: list[dict] = []
    seen_dates: set[object] = set()
    replaced = False
    for row in rows:
        row_date = row.get("date")
        if row_date in seen_dates:
            continue
        seen_dates.add(row_date)
        if row_date == entry_date:
            deduped.append(entry)
            replaced = True
        else:
            deduped.append(row)
    if not replaced:
        deduped.append(entry)

    log_path.write_text(
        "".join(json.dumps(row) + "\n" for row in deduped),
        encoding="utf-8",
    )


def print_report(entry: dict, prev: dict | None) -> None:
    sep = "=" * 60
    print(f"\n{sep}")
    print(f"Momentum Rotation Shadow Signal | {entry['date']}")
    print(f"Config: {entry['lookback_months']}m lookback, top-{entry['top_n']}, "
          f"{len(entry['universe'])}-asset universe")
    print(f"{sep}\n")

    print("12-Month Returns (ranked):")
    for sym, ret in entry["ranked"]:
        hold = " [HOLD]" if sym in entry["holdings"] else ""
        excl = " [negative - excluded]" if ret <= 0 else ""
        print(f"  {sym:5s}  {ret * 100:+6.1f}%{hold}{excl}")

    print()
    if entry["in_cash"]:
        print("Target: CASH  (all assets have negative 12-month momentum)")
    else:
        parts = [f"{sym} ({w * 100:.0f}%)" for sym, w in entry["weights"].items()]
        print(f"Target: {', '.join(parts)}")

    if prev is not None:
        prev_set = set(prev.get("holdings", []))
        curr_set = set(entry["holdings"])
        added = curr_set - prev_set
        removed = prev_set - curr_set
        if added or removed:
            print(f"\nChanges since {prev['date']}:")
            for sym in sorted(added):
                print(f"  + {sym}  (added)")
            for sym in sorted(removed):
                print(f"  - {sym}  (removed)")
        else:
            print(f"\nNo change from last signal ({prev['date']})")
    print()


def main() -> int:
    print("Fetching 12-month momentum data...")
    entry = compute_current_signal()
    prev = load_last_entry(LOG_PATH)
    print_report(entry, prev)
    log_entry(entry, LOG_PATH)
    print(f"Appended to {LOG_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

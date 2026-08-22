#!/usr/bin/env python3
"""Resolve recorded Fibonacci shadow plans from recent five-minute bars."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import yfinance as yf


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from strategies.fibonacci_shadow_journal import DEFAULT_PATH, resolve_plans


def main() -> int:
    try:
        rows = json.loads(DEFAULT_PATH.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        rows = []
    symbols = sorted({str(row.get("symbol") or "").upper() for row in rows if isinstance(row, dict) and row.get("symbol")})
    frames = {
        symbol: yf.Ticker(symbol).history(period="5d", interval="5m", auto_adjust=True)
        for symbol in symbols
    }
    report = resolve_plans(frames)
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

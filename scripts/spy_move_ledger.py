#!/usr/bin/env python3
"""SPY intraday move ledger.

Independent scanner that records every qualifying SPY intraday move BEFORE
knowing whether any downstream scanner detected, ranked, or confirmed it.

The ledger is the denominator for SPY recall reporting: it exists so we can
measure how many real moves the rest of the stack captures, rather than only
counting the trades we happened to take.

Detection rules (SPY-only, RTH 09:30-16:00 ET):
    - 5m  window: |return| >= 0.30%
    - 15m window: |return| >= 0.50%
    - 30m window: |return| >= 0.75%

The smallest-timeframe hit wins. A new move in the same direction is only
recorded if it starts after the prior move's window ends. R-multiple uses
0.5 * ATR14 (1-min) as the notional stop.

Data source: Alpaca 1-min bars (IEX free tier is sufficient for SPY).
Falls back to yfinance if Alpaca is unavailable.

Context-only. No order path, no execution authority.

Usage:
    python scripts/spy_move_ledger.py                # today
    python scripts/spy_move_ledger.py --date 2026-08-29
    python scripts/spy_move_ledger.py --backfill 5   # last 5 sessions
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import warnings
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

LEDGER_PATH = ROOT / "data" / "spy_move_ledger.jsonl"

MARKET_TZ = ZoneInfo("America/New_York")
UTC = timezone.utc
SPEC_VERSION = "2026-08-30"
SYMBOL = "SPY"

RTH_OPEN = time(9, 30)
RTH_CLOSE = time(16, 0)

# SPY-intraday thresholds tuned for 0DTE actionability rather than the frozen
# multi-symbol retrospective ground-truth spec. Rationale: SPY intraday ranges
# compress relative to single-name movers, so a 0.20% 5m move is already
# meaningful for short-dated option premium. Override via CLI when calibrating.
WINDOW_THRESHOLDS = [
    ("5m", 5, 0.20),
    ("15m", 15, 0.35),
    ("30m", 30, 0.55),
]
ATR_LOOKBACK = 14
STOP_ATR_MULT = 0.5


def _load_env() -> tuple[str | None, str | None]:
    env_path = ROOT / "agent" / ".env"
    key = os.environ.get("ALPACA_API_KEY")
    sec = os.environ.get("ALPACA_SECRET_KEY")
    if key and sec:
        return key, sec
    if not env_path.exists():
        return key, sec
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        k, v = k.strip(), v.strip()
        if k == "ALPACA_API_KEY":
            key = v
        elif k == "ALPACA_SECRET_KEY":
            sec = v
    return key, sec


def _fetch_bars_alpaca(target_date: date) -> pd.DataFrame:
    from alpaca.data.historical import StockHistoricalDataClient
    from alpaca.data.requests import StockBarsRequest
    from alpaca.data.timeframe import TimeFrame

    key, secret = _load_env()
    if not (key and secret):
        raise RuntimeError("Alpaca credentials missing (ALPACA_API_KEY / ALPACA_SECRET_KEY)")

    client = StockHistoricalDataClient(api_key=key, secret_key=secret)

    start_et = datetime.combine(target_date, RTH_OPEN, MARKET_TZ)
    end_et = datetime.combine(target_date, RTH_CLOSE, MARKET_TZ)
    request = StockBarsRequest(
        symbol_or_symbols=SYMBOL,
        timeframe=TimeFrame.Minute,
        start=start_et.astimezone(UTC),
        end=end_et.astimezone(UTC),
        feed="iex",
    )
    bars = client.get_stock_bars(request)
    df = bars.df
    if df.empty:
        raise ValueError(f"No Alpaca 1m bars for {SYMBOL} {target_date}")

    if isinstance(df.index, pd.MultiIndex):
        df = df.xs(SYMBOL, level="symbol")

    df.index = pd.to_datetime(df.index, utc=True)
    df.columns = [c.lower() for c in df.columns]
    df = df[["open", "high", "low", "close", "volume"]].dropna()
    # Filter to RTH in ET.
    et_idx = df.index.tz_convert(MARKET_TZ)
    mask = (et_idx.time >= RTH_OPEN) & (et_idx.time < RTH_CLOSE)
    return df.loc[mask].copy()


def _fetch_bars_yfinance(target_date: date) -> pd.DataFrame:
    try:
        import yfinance as yf
    except ImportError as exc:
        raise ImportError("yfinance required as fallback: uv add yfinance") from exc

    start = target_date.strftime("%Y-%m-%d")
    end = (target_date + timedelta(days=1)).strftime("%Y-%m-%d")
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        df = yf.download(SYMBOL, start=start, end=end, interval="1m", progress=False, auto_adjust=True)
    if df.empty:
        raise ValueError(f"yfinance returned no 1m bars for {SYMBOL} {target_date}")
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = [c[0].lower() for c in df.columns]
    else:
        df.columns = [str(c).lower() for c in df.columns]
    df = df[["open", "high", "low", "close", "volume"]].dropna()
    df.index = pd.to_datetime(df.index, utc=True) if df.index.tz is None else df.index.tz_convert(UTC)
    et_idx = df.index.tz_convert(MARKET_TZ)
    mask = (et_idx.time >= RTH_OPEN) & (et_idx.time < RTH_CLOSE)
    return df.loc[mask].copy()


def fetch_bars(target_date: date) -> tuple[pd.DataFrame, str]:
    # yfinance is primary for 1-min bars because it delivers the consolidated
    # (SIP-equivalent) tape. Alpaca free-tier IEX-only 1m bars materially
    # under-report SPY intraday ranges and would produce a hollow ledger.
    # yfinance has a rolling 7-day limit for 1m intervals; Alpaca is the
    # backfill fallback for anything older.
    try:
        return _fetch_bars_yfinance(target_date), "yfinance"
    except Exception as exc:  # noqa: BLE001
        warnings.warn(f"yfinance 1m fetch failed ({exc}); trying Alpaca IEX")
    key, secret = _load_env()
    if not (key and secret):
        raise RuntimeError("Neither yfinance nor Alpaca 1m bars available")
    return _fetch_bars_alpaca(target_date), "alpaca"


def _atr14_1m(df: pd.DataFrame, anchor_idx: int) -> float | None:
    if anchor_idx < ATR_LOOKBACK:
        return None
    window = df.iloc[anchor_idx - ATR_LOOKBACK : anchor_idx]
    prev_close = window["close"].shift(1)
    tr = pd.concat(
        [
            window["high"] - window["low"],
            (window["high"] - prev_close).abs(),
            (window["low"] - prev_close).abs(),
        ],
        axis=1,
    ).max(axis=1)
    tr = tr.dropna()
    if tr.empty:
        return None
    return float(tr.mean())


def _iso_et(ts: pd.Timestamp) -> str:
    return ts.tz_convert(MARKET_TZ).isoformat()


def _move_id(symbol: str, direction: str, window_start_et_iso: str) -> str:
    payload = f"{symbol}|{direction}|{window_start_et_iso}".encode()
    return hashlib.sha1(payload).hexdigest()[:16]


def detect_moves(
    df: pd.DataFrame,
    source: str,
    thresholds: list[tuple[str, int, float]] | None = None,
) -> list[dict[str, Any]]:
    """Scan 1-min bars and emit qualifying move records."""
    if df.empty:
        return []
    active_thresholds = thresholds or WINDOW_THRESHOLDS
    moves: list[dict[str, Any]] = []
    # Occupied bar indices, per direction, to enforce non-overlap.
    last_end_idx = {"up": -1, "down": -1}
    n = len(df)
    closes = df["close"].to_numpy()
    highs = df["high"].to_numpy()
    lows = df["low"].to_numpy()
    volumes = df["volume"].to_numpy()
    index = df.index

    for i in range(n):
        for timeframe, window_min, threshold_pct in active_thresholds:
            # window_min == elapsed minutes: return from close[i] -> close[i+window_min].
            j = i + window_min
            if j >= n:
                continue
            base = closes[i]
            if base <= 0:
                continue
            ret_pct = (closes[j] - base) / base * 100.0
            direction = "up" if ret_pct > 0 else "down"
            if abs(ret_pct) < threshold_pct:
                continue
            if i <= last_end_idx[direction]:
                continue
            # First qualifying timeframe wins for this bar+direction.
            peak = float(highs[i : j + 1].max()) if direction == "up" else float(lows[i : j + 1].min())
            magnitude_pct = abs(peak - base) / base * 100.0
            atr = _atr14_1m(df, i)
            stop_notional = (atr * STOP_ATR_MULT) if atr and atr > 0 else None
            price_move = abs(peak - base)
            r_multiple = round(price_move / stop_notional, 3) if stop_notional else None
            window_start_iso = _iso_et(index[i])
            window_end_iso = _iso_et(index[j])
            move = {
                "move_id": _move_id(SYMBOL, direction, window_start_iso),
                "symbol": SYMBOL,
                "date": index[i].tz_convert(MARKET_TZ).date().isoformat(),
                "direction": direction,
                "trigger_timeframe": timeframe,
                "threshold_pct": threshold_pct,
                "window_start_et": window_start_iso,
                "window_end_et": window_end_iso,
                "trigger_price": round(float(base), 4),
                "peak_price": round(peak, 4),
                "close_at_window_end": round(float(closes[j]), 4),
                "magnitude_pct": round(magnitude_pct, 4),
                "window_return_pct": round(ret_pct, 4),
                "atr_14_1m": round(atr, 4) if atr else None,
                "r_multiple": r_multiple,
                "volume_in_window": int(volumes[i : j + 1].sum()),
                "bar_count": window_min,
                "data_source": source,
                "detected_by": "spy_move_ledger",
                "spec_version": SPEC_VERSION,
                "recorded_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
                "execution_enabled": False,
                "mode": "context_only",
            }
            moves.append(move)
            last_end_idx[direction] = j
            break  # smallest timeframe already recorded for this anchor
    return moves


def _load_existing_move_ids() -> set[str]:
    if not LEDGER_PATH.exists():
        return set()
    ids: set[str] = set()
    for raw in LEDGER_PATH.read_text(encoding="utf-8-sig").splitlines():
        raw = raw.strip()
        if not raw:
            continue
        try:
            row = json.loads(raw)
        except json.JSONDecodeError:
            continue
        mid = row.get("move_id")
        if isinstance(mid, str):
            ids.add(mid)
    return ids


def append_ledger(moves: list[dict[str, Any]]) -> tuple[int, int]:
    """Return (appended, duplicates_skipped)."""
    LEDGER_PATH.parent.mkdir(parents=True, exist_ok=True)
    existing = _load_existing_move_ids()
    appended = 0
    skipped = 0
    with LEDGER_PATH.open("a", encoding="utf-8") as fh:
        for move in moves:
            if move["move_id"] in existing:
                skipped += 1
                continue
            fh.write(json.dumps(move) + "\n")
            existing.add(move["move_id"])
            appended += 1
    return appended, skipped


def scan_date(target_date: date, thresholds: list[tuple[str, int, float]] | None = None) -> dict[str, Any]:
    df, source = fetch_bars(target_date)
    moves = detect_moves(df, source, thresholds=thresholds)
    appended, skipped = append_ledger(moves)
    return {
        "date": target_date.isoformat(),
        "bar_count": int(len(df)),
        "data_source": source,
        "detected": len(moves),
        "appended": appended,
        "duplicates_skipped": skipped,
        "moves": moves,
    }


def _target_date_from_now() -> date:
    return datetime.now(MARKET_TZ).date()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--date", help="YYYY-MM-DD (ET session date). Default: today ET.")
    parser.add_argument("--backfill", type=int, default=0, help="Also scan the N prior sessions (calendar days, weekends skipped).")
    parser.add_argument("--print-moves", action="store_true", help="Print each move record.")
    parser.add_argument(
        "--thresholds",
        help="Override thresholds. Comma-separated triples like '5m:5:0.20,15m:15:0.35,30m:30:0.55'.",
    )
    args = parser.parse_args()

    thresholds: list[tuple[str, int, float]] | None = None
    if args.thresholds:
        thresholds = []
        for chunk in args.thresholds.split(","):
            parts = chunk.strip().split(":")
            if len(parts) != 3:
                parser.error(f"bad threshold '{chunk}' (expected label:minutes:pct)")
            thresholds.append((parts[0], int(parts[1]), float(parts[2])))

    if args.date:
        target = date.fromisoformat(args.date)
    else:
        target = _target_date_from_now()

    sessions: list[date] = []
    d = target
    remaining = args.backfill
    sessions.append(d)
    while remaining > 0:
        d -= timedelta(days=1)
        if d.weekday() >= 5:
            continue
        sessions.append(d)
        remaining -= 1

    summaries = []
    for session_date in sessions:
        try:
            summary = scan_date(session_date, thresholds=thresholds)
        except Exception as exc:  # noqa: BLE001
            summary = {"date": session_date.isoformat(), "error": str(exc)[:200]}
        summaries.append(summary)
        if args.print_moves and summary.get("moves"):
            for m in summary["moves"]:
                print(json.dumps(m))

    out = {
        "generated_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "spec_version": SPEC_VERSION,
        "ledger_path": str(LEDGER_PATH),
        "sessions": summaries,
    }
    print(json.dumps({k: v for k, v in out.items() if k != "sessions"} | {
        "sessions": [{k: v for k, v in s.items() if k != "moves"} for s in summaries]
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

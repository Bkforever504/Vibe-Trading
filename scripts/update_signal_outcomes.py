#!/usr/bin/env python3
"""Resolve open shadow signals to win/loss/eod outcomes.

Reads the shadow journal, finds signals that have no outcome yet, fetches
1h NQ=F bars for each signal date via yfinance, simulates the exit, and
appends outcome records back to the journal (append-only — never rewrites).

Usage:
    uv run --no-project --with yfinance python scripts/update_signal_outcomes.py
    uv run --no-project --with yfinance python scripts/update_signal_outcomes.py --dry-run
    uv run --no-project --with yfinance python scripts/update_signal_outcomes.py --exit-model full_target_stop
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import date, datetime, timedelta, time as dtime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

try:
    import yfinance as yf
except ImportError:
    sys.exit("yfinance not installed. Run: pip install yfinance")

DEFAULT_JOURNAL = Path(os.path.expanduser(r"~\.vibe-trading\shadow-ai-signals.jsonl"))
ET = ZoneInfo("America/New_York")
RTH_START = dtime(9, 30)
RTH_END   = dtime(16, 0)

MNQ_POINT_VALUE = 2.0
COMMISSION_RT   = 4.00


# ---------------------------------------------------------------------------
# Journal I/O
# ---------------------------------------------------------------------------

def load_journal(journal: Path) -> list[dict[str, Any]]:
    if not journal.exists():
        return []
    records: list[dict[str, Any]] = []
    with journal.open("r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError:
                pass
    return records


def append_record(record: dict[str, Any], journal: Path, *, dry_run: bool) -> None:
    if dry_run:
        print(f"  [dry-run] would append: {json.dumps(record)[:120]}...")
        return
    journal.parent.mkdir(parents=True, exist_ok=True)
    with journal.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(record, sort_keys=True) + "\n")


def _utc_now() -> str:
    return datetime.now(ZoneInfo("UTC")).isoformat(timespec="seconds").replace("+00:00", "Z")


# ---------------------------------------------------------------------------
# Bar fetching
# ---------------------------------------------------------------------------

def fetch_date_bars(ticker: str, target_date: date) -> list[dict]:
    """Fetch 1h RTH bars for a specific trading date via yfinance."""
    start = (target_date - timedelta(days=5)).isoformat()
    end   = (target_date + timedelta(days=2)).isoformat()
    t = yf.Ticker(ticker)
    df = t.history(start=start, end=end, interval="1h", auto_adjust=True)
    if df.empty:
        return []
    df.index = df.index.tz_convert(ET)
    df = df[df.index.map(lambda ts: ts.date() == target_date and RTH_START <= ts.time() < RTH_END)]
    bars = []
    for ts, row in df.iterrows():
        bars.append({
            "timestamp": ts.isoformat(),
            "open":  float(row["Open"]),
            "high":  float(row["High"]),
            "low":   float(row["Low"]),
            "close": float(row["Close"]),
        })
    return bars


# ---------------------------------------------------------------------------
# Exit simulation
# ---------------------------------------------------------------------------

def _simulate_full(bars: list[dict], *, side: str, stop: float, target: float) -> tuple[float, str]:
    """Full target/stop: first hit wins. Stop takes priority on same bar."""
    for bar in bars:
        if side == "buy":
            if bar["low"] <= stop:
                return stop, "stop"
            if bar["high"] >= target:
                return target, "target"
        else:
            if bar["high"] >= stop:
                return stop, "stop"
            if bar["low"] <= target:
                return target, "target"
    if bars:
        return bars[-1]["close"], "eod"
    return 0.0, "no_bars"


def _simulate_partial(bars: list[dict], *, side: str, entry: float, stop: float, target: float) -> tuple[float, str]:
    """Half exits at 1R, runner moves to breakeven, runner exits at 2R or EOD."""
    risk  = abs(entry - stop)
    r1    = (entry + risk) if side == "buy" else (entry - risk)
    be    = entry
    half  = MNQ_POINT_VALUE / 2  # per-half point value

    phase    = "phase1"
    half_pnl = 0.0

    for bar in bars:
        if phase == "phase1":
            if side == "buy":
                if bar["low"] <= stop:
                    return (stop - entry) * MNQ_POINT_VALUE, "stop"
                if bar["high"] >= r1:
                    half_pnl = (r1 - entry) * half
                    phase = "phase2"
            else:
                if bar["high"] >= stop:
                    return (entry - stop) * MNQ_POINT_VALUE, "stop"
                if bar["low"] <= r1:
                    half_pnl = (entry - r1) * half
                    phase = "phase2"
        elif phase == "phase2":
            if side == "buy":
                if bar["low"] <= be:
                    return half_pnl + (be - entry) * half, "partial_be"
                if bar["high"] >= target:
                    return half_pnl + (target - entry) * half, "target"
            else:
                if bar["high"] >= be:
                    return half_pnl + (entry - be) * half, "partial_be"
                if bar["low"] <= target:
                    return half_pnl + (entry - target) * half, "target"

    if not bars:
        return 0.0, "no_bars"

    eod = bars[-1]["close"]
    if phase == "phase1":
        gross = (eod - entry) if side == "buy" else (entry - eod)
        return gross * MNQ_POINT_VALUE, "eod"
    else:
        runner = ((eod - entry) if side == "buy" else (entry - eod)) * half
        return half_pnl + runner, "partial_eod"


def simulate_exit(
    bars_after: list[dict],
    *,
    side: str,
    entry: float,
    stop: float,
    target: float,
    exit_model: str,
) -> tuple[float, str]:
    """Return (gross_pnl, exit_reason). Commission not deducted here."""
    if exit_model == "partial_1r_be_2r":
        return _simulate_partial(bars_after, side=side, entry=entry, stop=stop, target=target)
    return _simulate_full(bars_after, side=side, stop=stop, target=target)


# ---------------------------------------------------------------------------
# Signal parsing
# ---------------------------------------------------------------------------

def _is_signal(record: dict) -> bool:
    return (
        record.get("mode") == "shadow_only"
        and record.get("executable") is False
        and record.get("type") != "outcome"
    )


def _is_outcome(record: dict) -> bool:
    return record.get("type") == "outcome"


def _parse_signal_date(record: dict) -> date | None:
    ctx = record.get("context") or {}
    date_str = ctx.get("date") or (record.get("created_at") or "")[:10]
    try:
        return datetime.fromisoformat(date_str).date()
    except (ValueError, TypeError):
        return None


def _parse_context_float(ctx: dict, key: str) -> float | None:
    try:
        return float(ctx[key])
    except (KeyError, TypeError, ValueError):
        return None


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description="Resolve open shadow signals to win/loss outcomes")
    parser.add_argument("--journal", type=Path, default=DEFAULT_JOURNAL)
    parser.add_argument("--ticker", default="NQ=F", help="yfinance ticker for price data")
    parser.add_argument("--exit-model", choices=["full_target_stop", "partial_1r_be_2r"],
                        default="partial_1r_be_2r",
                        help="Exit model to simulate (match the live scanner config)")
    parser.add_argument("--dry-run", action="store_true",
                        help="Print what would be written without modifying the journal")
    parser.add_argument("--strategy", default=None,
                        help="Only resolve signals from this strategy (e.g. first_pullback_1h)")
    parser.add_argument("--min-age-hours", type=float, default=6.0,
                        help="Only resolve signals at least N hours old (avoids resolving same-day live signals)")
    args = parser.parse_args()

    records = load_journal(args.journal)
    if not records:
        print(f"No records in journal: {args.journal}")
        return

    # Build set of signal IDs that already have outcomes
    resolved_ids: set[str] = {
        r["signal_id"] for r in records if _is_outcome(r) and "signal_id" in r
    }

    signals = [r for r in records if _is_signal(r)]
    if args.strategy:
        signals = [s for s in signals if s.get("strategy") == args.strategy]

    now_utc = datetime.now(ZoneInfo("UTC"))
    pending = []
    for sig in signals:
        sig_id = sig.get("created_at", "")
        if sig_id in resolved_ids:
            continue
        # Only process signals old enough that the trading day is done
        try:
            sig_time = datetime.fromisoformat(sig_id.replace("Z", "+00:00"))
            age_hours = (now_utc - sig_time).total_seconds() / 3600
            if age_hours < args.min_age_hours:
                print(f"Skipping {sig_id[:19]} — only {age_hours:.1f}h old (min {args.min_age_hours}h)")
                continue
        except (ValueError, TypeError):
            pass
        pending.append(sig)

    if not pending:
        print(f"No open signals to resolve ({len(resolved_ids)} already have outcomes).")
        return

    print(f"Resolving {len(pending)} open signal(s) using exit_model={args.exit_model}...")
    if args.dry_run:
        print("[DRY RUN — journal will not be modified]")

    resolved = 0
    for sig in pending:
        sig_id  = sig.get("created_at", "")
        ctx     = sig.get("context") or {}
        symbol  = sig.get("symbol", "MNQ")
        strategy = sig.get("strategy", "unknown")

        entry  = _parse_context_float(ctx, "entry")
        stop   = _parse_context_float(ctx, "stop")
        target = _parse_context_float(ctx, "target")
        side   = str(sig.get("proposed_action") or ctx.get("side") or "")
        entry_bar_idx = ctx.get("entry_bar_idx")
        sig_date = _parse_signal_date(sig)

        if None in (entry, stop, target, sig_date) or side not in ("buy", "sell"):
            print(f"  {sig_id[:19]} — skipping: missing entry/stop/target/side/date")
            continue

        print(f"  {sig_id[:19]} | {symbol} {side.upper()} @ {entry:.2f}  stop={stop:.2f}  target={target:.2f}  date={sig_date}", end=" ... ")

        try:
            bars = fetch_date_bars(args.ticker, sig_date)
        except Exception as exc:
            print(f"fetch error: {exc}")
            continue

        if not bars:
            print("no bars returned — skipping")
            continue

        # Bars after the entry bar index (or all bars if index unknown)
        if isinstance(entry_bar_idx, int) and entry_bar_idx + 1 < len(bars):
            bars_after = bars[entry_bar_idx + 1:]
        elif isinstance(entry_bar_idx, int):
            bars_after = []
        else:
            bars_after = bars[1:]  # conservative: skip first bar

        if not bars_after:
            print("no bars after entry — signal may have fired at EOD, using entry bar close")
            eod_price = bars[entry_bar_idx]["close"] if isinstance(entry_bar_idx, int) and entry_bar_idx < len(bars) else bars[-1]["close"]
            gross = (eod_price - entry) * MNQ_POINT_VALUE if side == "buy" else (entry - eod_price) * MNQ_POINT_VALUE
            exit_reason = "eod"
            pnl = round(gross - COMMISSION_RT, 2)
        else:
            gross, exit_reason = simulate_exit(
                bars_after, side=side, entry=entry, stop=stop, target=target, exit_model=args.exit_model
            )
            pnl = round(gross - COMMISSION_RT, 2)

        outcome = "win" if pnl > 0 else ("loss" if pnl < 0 else "breakeven")
        print(f"{exit_reason} → {outcome}  pnl=${pnl:.2f}")

        outcome_record = {
            "created_at":   _utc_now(),
            "mode":         "shadow_only",
            "executable":   False,
            "type":         "outcome",
            "signal_id":    sig_id,
            "symbol":       symbol,
            "strategy":     strategy,
            "exit_model":   args.exit_model,
            "exit_reason":  exit_reason,
            "gross_pnl":    round(gross, 2),
            "commission":   COMMISSION_RT,
            "pnl":          pnl,
            "outcome":      outcome,
        }
        append_record(outcome_record, args.journal, dry_run=args.dry_run)
        resolved += 1

        time.sleep(0.5)  # polite yfinance rate limiting

    print(f"\nDone. {resolved}/{len(pending)} signal(s) resolved.")
    if args.dry_run:
        print("Run without --dry-run to write outcomes to the journal.")


if __name__ == "__main__":
    main()

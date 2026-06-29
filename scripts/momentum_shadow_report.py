"""
Weekly shadow P&L dashboard for the momentum rotation paper candidate.

Shows current holdings, prior holdings, actual period returns vs SPY/QQQ,
rolling shadow P&L, and gate status. Read-only -no orders, no log writes.

Usage:
    python scripts/momentum_shadow_report.py
"""
from __future__ import annotations

import json
import warnings
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd


LOG_PATH = Path(__file__).resolve().parent.parent / "data" / "momentum_shadow_log.jsonl"
PAPER_CANDIDATE_CONF = 9.0
FORWARD_TEST_DAYS_NEEDED = 30


def load_entries(log_path: Path) -> list[dict]:
    if not log_path.exists():
        return []
    entries = []
    for line in log_path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if stripped:
            try:
                entries.append(json.loads(stripped))
            except json.JSONDecodeError:
                pass
    return sorted(entries, key=lambda e: e["date"])


def _fetch_period_return(symbols: list[str], start: str, end: str) -> dict[str, float]:
    """Fetch close-to-close return for each symbol over [start, end]."""
    try:
        import yfinance as yf
    except ImportError:
        return {}

    results: dict[str, float] = {}
    fetch_start = (datetime.fromisoformat(start) - timedelta(days=7)).strftime("%Y-%m-%d")
    fetch_end = (datetime.fromisoformat(end) + timedelta(days=2)).strftime("%Y-%m-%d")

    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        for sym in symbols:
            try:
                df = yf.download(sym, start=fetch_start, end=fetch_end, progress=False, auto_adjust=True)
                if df.empty:
                    continue
                df.columns = [c.lower() if isinstance(c, str) else c[0].lower() for c in df.columns]
                close = df["close"]
                entry_bar = close.loc[close.index >= start]
                exit_bar = close.loc[close.index <= end]
                if entry_bar.empty or exit_bar.empty:
                    continue
                results[sym] = float(exit_bar.iloc[-1] / entry_bar.iloc[0] - 1)
            except Exception:
                pass
    return results


def compute_period_returns(entries: list[dict]) -> list[dict]:
    if len(entries) < 2:
        return []

    periods = []
    for i in range(len(entries) - 1):
        cur = entries[i]
        nxt = entries[i + 1]
        holdings = cur.get("holdings", [])
        start, end = cur["date"], nxt["date"]

        fetch_syms = list(set(holdings + ["SPY", "QQQ"]))
        rets = _fetch_period_return(fetch_syms, start, end)

        if not holdings:
            portfolio_ret = 0.0
        else:
            portfolio_ret = sum(rets.get(sym, 0.0) for sym in holdings) / len(holdings)

        spy_ret = rets.get("SPY", 0.0)
        qqq_ret = rets.get("QQQ", 0.0)
        periods.append({
            "start": start,
            "end": end,
            "holdings": holdings,
            "in_cash": cur.get("in_cash", False),
            "portfolio_return": portfolio_ret,
            "spy_return": spy_ret,
            "qqq_return": qqq_ret,
            "excess_vs_spy": portfolio_ret - spy_ret,
        })
    return periods


def print_report(entries: list[dict], periods: list[dict]) -> None:
    sep = "=" * 65
    print(f"\n{sep}")
    print("  Momentum Rotation -Shadow P&L Dashboard")
    print(f"  Generated: {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print(f"{sep}\n")

    if not entries:
        print("No log entries found. Run momentum_shadow_logger.py first.")
        return

    latest = entries[-1]
    prev = entries[-2] if len(entries) >= 2 else None

    # ── Current holdings ─────────────────────────────────────────
    print("CURRENT HOLDINGS")
    if latest.get("in_cash"):
        print("  CASH  (all assets have negative 12-month momentum)")
    else:
        for sym, w in latest.get("weights", {}).items():
            mom = latest.get("momentum_12m", {}).get(sym, 0.0)
            print(f"  {sym:5s}  {w * 100:.0f}%   12m momentum: {mom * 100:+.1f}%")
    print(f"  As of: {latest['date']}\n")

    # ── Holdings change ──────────────────────────────────────────
    if prev is not None:
        prev_set = set(prev.get("holdings", []))
        curr_set = set(latest.get("holdings", []))
        added = curr_set - prev_set
        removed = prev_set - curr_set
        if added or removed:
            print("CHANGES FROM LAST SIGNAL")
            for sym in sorted(added):
                print(f"  + {sym}  (entered)")
            for sym in sorted(removed):
                print(f"  - {sym}  (exited)")
        else:
            print(f"CHANGES FROM LAST SIGNAL ({prev['date']}): none")
        print()

    # ── Period P&L table ─────────────────────────────────────────
    if periods:
        print("PERIOD RETURNS")
        hdr = f"  {'Period':<23} {'Holdings':<18} {'Portfolio':>9} {'SPY':>7} {'Excess':>8}"
        print(hdr)
        print("  " + "-" * 63)
        cum_portfolio = 1.0
        cum_spy = 1.0
        for p in periods:
            holds = "+".join(p["holdings"]) if p["holdings"] else "CASH"
            port = p["portfolio_return"]
            spy = p["spy_return"]
            exc = p["excess_vs_spy"]
            period_str = f"{p['start']} -> {p['end']}"
            cum_portfolio *= (1 + port)
            cum_spy *= (1 + spy)
            print(f"  {period_str:<23} {holds:<18} {port * 100:>+8.2f}% {spy * 100:>+6.2f}% {exc * 100:>+7.2f}%")

        print("  " + "-" * 63)
        total_port = (cum_portfolio - 1) * 100
        total_spy = (cum_spy - 1) * 100
        total_exc = total_port - total_spy
        print(f"  {'CUMULATIVE':<42} {total_port:>+8.2f}% {total_spy:>+6.2f}% {total_exc:>+7.2f}%")
        print()
    else:
        print("PERIOD RETURNS: waiting for second log entry (run next Monday)\n")

    # ── Full momentum table ──────────────────────────────────────
    print("LATEST MOMENTUM RANKINGS")
    for sym, ret in latest.get("ranked", []):
        marker = " <<" if sym in latest.get("holdings", []) else ""
        excl = "  [excluded: negative]" if ret <= 0 else ""
        print(f"  {sym:5s}  {ret * 100:+6.1f}%{marker}{excl}")
    print()

    # ── Gate status ───────────────────────────────────────────────
    days_logged = len(entries)
    days_needed = FORWARD_TEST_DAYS_NEEDED
    pct_done = min(days_logged / days_needed * 100, 100)
    ready = days_logged >= days_needed

    print("FORWARD TEST STATUS")
    print(f"  Research result: paper_candidate (conf {PAPER_CANDIDATE_CONF}/10)")
    print(f"  Weekly logs recorded: {days_logged}")
    print(f"  Logs needed before execution review: {days_needed}")
    print(f"  Progress: {pct_done:.0f}%  {'[READY FOR REVIEW]' if ready else '[NOT READY -DO NOT EXECUTE]'}")
    print()
    print("BOT PRIORITY LADDER")
    print("  [shadow]  Momentum rotation ETF  <-- you are here")
    print("  [paper]   Flip bot options")
    print("  [paper]   IWM premium selling")
    print("  [dry-run] Kalshi scoring")
    print("  [shadow]  MNQ validation")
    print()


def main() -> int:
    entries = load_entries(LOG_PATH)
    periods = compute_period_returns(entries)
    print_report(entries, periods)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""
Catalyst Scanner — finds high-probability directional options setups for small accounts.

Strategy: buy cheap OTM or ATM options BEFORE a known catalyst.
Works when historical earnings move > implied move (options are underpriced).
Works when unusual options activity signals smart money positioning.

Usage:
    python strategies/catalyst_scanner.py
    python strategies/catalyst_scanner.py --account 500
    python strategies/catalyst_scanner.py --symbols TSLA NVDA AAPL --account 300
    python strategies/catalyst_scanner.py --uoa-only
    python strategies/catalyst_scanner.py --earnings-only
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), "..", "agent", ".env"))

try:
    import yfinance as yf
except ImportError:
    print("ERROR: yfinance not installed. Run: pip install yfinance")
    sys.exit(1)

LOG_DIR = Path(os.path.expanduser(r"~\.vibe-trading\logs"))
LOG_DIR.mkdir(parents=True, exist_ok=True)
SCAN_LOG = LOG_DIR / "catalyst-scans.jsonl"

# Default watchlist — high retail volume, liquid options
DEFAULT_SYMBOLS = [
    "SPY", "QQQ", "IWM",            # ETFs — liquid, macro plays
    "TSLA", "NVDA", "AAPL", "META", # Mega caps — high IV, big earnings moves
    "AMZN", "GOOGL", "MSFT", "AMD", # Tech — consistent earnings reactions
    "PLTR", "COIN", "MSTR",          # High beta retail favorites
]

# Macro events — update monthly. Format: (date, label, trade_note)
MACRO_EVENTS = [
    (date(2026, 7, 14), "CPI Release",   "Buy SPY ATM straddle morning of release, close by EOD"),
    (date(2026, 7, 29), "FOMC Decision", "Buy SPY/QQQ ATM straddle 2 days before, close same day"),
    (date(2026, 8, 12), "CPI Release",   "Buy SPY ATM straddle morning of release, close by EOD"),
    (date(2026, 9, 11), "CPI Release",   "Buy SPY ATM straddle morning of release, close by EOD"),
    (date(2026, 9, 16), "FOMC Decision", "Buy SPY/QQQ ATM straddle 2 days before, close same day"),
]

PROFIT_TARGET_PCT = 0.75
STOP_LOSS_PCT     = 0.50
MAX_RISK_PCT      = 0.25


# ---------------------------------------------------------------------------
# Earnings helpers
# ---------------------------------------------------------------------------

def _get_next_earnings(ticker_obj) -> date | None:
    try:
        cal = ticker_obj.calendar
        if cal is None:
            return None
        if isinstance(cal, dict):
            ed = cal.get("Earnings Date")
            if ed:
                if hasattr(ed, '__iter__') and not isinstance(ed, str):
                    ed = list(ed)[0]
                if hasattr(ed, 'date'):
                    return ed.date()
                return ed
        if hasattr(cal, 'loc'):
            try:
                ed = cal.loc["Earnings Date"]
                if hasattr(ed, 'iloc'):
                    ed = ed.iloc[0]
                if hasattr(ed, 'date'):
                    return ed.date()
            except Exception:
                pass
    except Exception:
        pass
    return None


def _get_historical_earnings_move(ticker_obj) -> float:
    """Average absolute % move on day of/after last 8 earnings. Returns 0 on failure."""
    try:
        edf = ticker_obj.earnings_dates
        if edf is None or edf.empty:
            return 0.0
        hist = ticker_obj.history(period="3y", auto_adjust=True)
        if hist.empty:
            return 0.0
        closes = hist["Close"]
        hist_map = {d.date(): float(p) for d, p in closes.items()}
        sorted_dates = sorted(hist_map.keys())

        moves = []
        for idx_e, e_ts in enumerate(edf.index):
            if idx_e >= 8:
                break
            e_date = e_ts.date() if hasattr(e_ts, 'date') else e_ts
            for i, d in enumerate(sorted_dates):
                if d >= e_date and i > 0:
                    prev = hist_map[sorted_dates[i - 1]]
                    curr = hist_map[d]
                    if prev > 0:
                        moves.append(abs(curr - prev) / prev)
                    break
        return sum(moves) / len(moves) if moves else 0.0
    except Exception:
        return 0.0


def _get_implied_move(ticker_obj, earnings_date: date) -> tuple[float, float, str]:
    """Returns (implied_move_pct, straddle_cost, expiry_used). Zeros on failure."""
    try:
        available = ticker_obj.options
        if not available:
            return 0.0, 0.0, ""

        target_expiry = None
        for exp in available:
            exp_date = datetime.strptime(exp, "%Y-%m-%d").date()
            if exp_date >= earnings_date:
                target_expiry = exp
                break
        if not target_expiry:
            return 0.0, 0.0, ""

        chain = ticker_obj.option_chain(target_expiry)
        try:
            price = float(ticker_obj.fast_info["last_price"])
        except Exception:
            price = float(ticker_obj.info.get("regularMarketPrice") or ticker_obj.info.get("currentPrice") or 0)
        if price <= 0:
            return 0.0, 0.0, target_expiry

        calls, puts = chain.calls, chain.puts
        if calls.empty or puts.empty:
            return 0.0, 0.0, target_expiry

        atm_strike = calls.iloc[(calls['strike'] - price).abs().argsort()[:1]]['strike'].values[0]
        c_row = calls[calls['strike'] == atm_strike]
        p_row = puts[puts['strike'] == atm_strike]
        if c_row.empty or p_row.empty:
            return 0.0, 0.0, target_expiry

        straddle = float(c_row['lastPrice'].values[0]) + float(p_row['lastPrice'].values[0])
        return straddle / price, straddle, target_expiry
    except Exception:
        return 0.0, 0.0, ""


def _earnings_score(hist_move: float, impl_move: float, days_out: int, straddle_cost: float, account_size: float) -> int:
    score = 0
    if hist_move > 0 and impl_move > 0:
        ratio = hist_move / impl_move
        if ratio > 1.3:   score += 4
        elif ratio > 1.1: score += 2
        elif ratio > 0.9: score += 1
    if 5 <= days_out <= 14:  score += 2
    elif days_out <= 4:      score += 1
    max_risk = account_size * MAX_RISK_PCT
    if straddle_cost > 0 and (straddle_cost * 100) <= max_risk:
        score += 2
    elif straddle_cost > 0 and (straddle_cost * 50) <= max_risk:
        score += 1
    return min(score, 10)


# ---------------------------------------------------------------------------
# Unusual options activity
# ---------------------------------------------------------------------------

def _scan_uoa(ticker_obj, symbol: str) -> list[dict]:
    hits = []
    try:
        try:
            price = float(ticker_obj.fast_info["last_price"])
        except Exception:
            price = float(ticker_obj.info.get("regularMarketPrice") or 0)
        if price <= 0:
            return []

        today   = date.today()
        cutoff  = today + timedelta(days=60)

        for expiry in ticker_obj.options:
            exp_date = datetime.strptime(expiry, "%Y-%m-%d").date()
            if exp_date < today or exp_date > cutoff:
                continue
            try:
                chain = ticker_obj.option_chain(expiry)
            except Exception:
                continue

            for right, df in [("CALL", chain.calls), ("PUT", chain.puts)]:
                if df.empty:
                    continue
                df = df.copy()
                df = df[(df['volume'] > 0) & (df['openInterest'] > 0)]
                if df.empty:
                    continue
                df['vol_oi'] = df['volume'] / df['openInterest']
                unusual = df[(df['vol_oi'] >= 3.0) & (df['volume'] >= 100)]
                for _, row in unusual.iterrows():
                    premium    = float(row.get('lastPrice', 0) or 0)
                    vol        = int(row.get('volume', 0) or 0)
                    oi         = int(row.get('openInterest', 0) or 0)
                    vol_oi     = float(row['vol_oi'])
                    strike     = float(row['strike'])
                    dollar_flow = premium * vol * 100
                    moneyness  = (strike / price - 1) * 100
                    dte        = (exp_date - today).days

                    score = 0
                    if vol_oi >= 10:   score += 3
                    elif vol_oi >= 5:  score += 2
                    else:              score += 1
                    if dollar_flow >= 50_000:   score += 2
                    elif dollar_flow >= 10_000: score += 1
                    if abs(moneyness) <= 5:     score += 1

                    hits.append({
                        "symbol":        symbol,
                        "right":         right,
                        "strike":        strike,
                        "expiry":        expiry,
                        "dte":           dte,
                        "volume":        vol,
                        "open_interest": oi,
                        "vol_oi":        round(vol_oi, 1),
                        "premium":       premium,
                        "dollar_flow":   dollar_flow,
                        "moneyness_pct": round(moneyness, 1),
                        "score":         score,
                        "direction":     "BULLISH" if right == "CALL" else "BEARISH",
                    })
    except Exception:
        pass
    return sorted(hits, key=lambda x: x['score'], reverse=True)[:3]


# ---------------------------------------------------------------------------
# Scans
# ---------------------------------------------------------------------------

def scan_earnings(symbols: list[str], account_size: float, lookahead_days: int = 30) -> list[dict]:
    results = []
    today   = date.today()
    cutoff  = today + timedelta(days=lookahead_days)
    print(f"\nScanning {len(symbols)} symbols for earnings plays (next {lookahead_days} days)...")

    for sym in symbols:
        try:
            t       = yf.Ticker(sym)
            e_date  = _get_next_earnings(t)
            if not e_date or not (today <= e_date <= cutoff):
                continue

            days_out                    = (e_date - today).days
            hist_move                   = _get_historical_earnings_move(t)
            impl_move, straddle, expiry = _get_implied_move(t, e_date)
            score                       = _earnings_score(hist_move, impl_move, days_out, straddle, account_size)

            edge = "—"
            if hist_move > 0 and impl_move > 0:
                ratio = hist_move / impl_move
                if ratio > 1.1:   edge = "BUYER EDGE"
                elif ratio < 0.9: edge = "SELLER EDGE"
                else:             edge = "FAIR"

            max_risk      = account_size * MAX_RISK_PCT
            contracts     = int(max_risk // (straddle * 100)) if straddle > 0 else 0
            cheap_entry   = round(straddle * 0.4, 2)

            results.append({
                "type":            "earnings",
                "symbol":          sym,
                "earnings_date":   str(e_date),
                "days_out":        days_out,
                "hist_move_pct":   round(hist_move * 100, 1),
                "impl_move_pct":   round(impl_move * 100, 1),
                "straddle_cost":   round(straddle, 2),
                "expiry_used":     expiry,
                "edge":            edge,
                "score":           score,
                "max_contracts":   contracts,
                "cheap_entry_est": cheap_entry,
            })
            print(f"  {sym:<6} earnings {e_date} ({days_out:>2}d)  hist={hist_move*100:.1f}%  impl={impl_move*100:.1f}%  {edge}  score={score}")
        except Exception as exc:
            print(f"  {sym:<6} skip ({exc})")

    return sorted(results, key=lambda x: x['score'], reverse=True)


def scan_uoa(symbols: list[str]) -> list[dict]:
    all_hits = []
    print(f"\nScanning {len(symbols)} symbols for unusual options activity...")
    for sym in symbols:
        try:
            t    = yf.Ticker(sym)
            hits = _scan_uoa(t, sym)
            if hits:
                print(f"  {sym:<6} {len(hits)} strike(s) flagged (top score {hits[0]['score']})")
            all_hits.extend(hits)
        except Exception as exc:
            print(f"  {sym:<6} skip ({exc})")
    return sorted(all_hits, key=lambda x: x['score'], reverse=True)


# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------

def print_macro_events() -> None:
    today    = date.today()
    upcoming = [(d, lbl, note) for d, lbl, note in MACRO_EVENTS
                if today <= d <= today + timedelta(days=60)]
    if not upcoming:
        return
    print("\n" + "=" * 65)
    print("  MACRO EVENTS (next 60 days)")
    print("=" * 65)
    for d, lbl, note in sorted(upcoming):
        days = (d - today).days
        print(f"  {d}  ({days:>2}d)  {lbl}")
        print(f"           -> {note}")


def print_earnings_report(results: list[dict], account_size: float) -> None:
    if not results:
        print("\n  No earnings plays found in next 30 days.")
        return
    max_risk = account_size * MAX_RISK_PCT
    print("\n" + "=" * 65)
    print("  EARNINGS PLAYS — ranked by setup quality")
    print("=" * 65)
    for i, r in enumerate(results[:8], 1):
        print(f"\n  #{i}  {r['symbol']}  |  earnings {r['earnings_date']}  ({r['days_out']}d)  |  score {r['score']}/10  [{r['edge']}]")
        print(f"      Historical avg move: {r['hist_move_pct']:.1f}%  |  Implied move: {r['impl_move_pct']:.1f}%")
        if r['straddle_cost'] > 0:
            print(f"      ATM straddle: ${r['straddle_cost']:.2f} = ${r['straddle_cost']*100:.0f}/contract")
            print(f"      Single call/put est: ${r['cheap_entry_est']:.2f} = ${r['cheap_entry_est']*100:.0f}/contract")
            print(f"      Account ${account_size:.0f}, risk ${max_risk:.0f} -> ~{r['max_contracts']} straddle contract(s)")
        if r['edge'] == "BUYER EDGE":
            print(f"      ACTION: Pick direction, buy call OR put {min(r['days_out']-1, 3)} days before earnings")
            print(f"              Close BEFORE earnings print — avoid IV crush on announcement")
        elif r['edge'] == "SELLER EDGE":
            print(f"      ACTION: Skip buying — options overpriced vs historical reaction")


def print_uoa_report(results: list[dict], account_size: float) -> None:
    if not results:
        print("\n  No unusual options activity found.")
        return
    max_risk = account_size * MAX_RISK_PCT
    print("\n" + "=" * 65)
    print("  UNUSUAL OPTIONS ACTIVITY — potential smart money signals")
    print("=" * 65)
    for r in results[:10]:
        contracts = int(max_risk // (r['premium'] * 100)) if r['premium'] > 0 else 0
        print(f"\n  {r['symbol']:<5}  {r['expiry']}  {r['right']:<4}  ${r['strike']:.0f}  "
              f"[{r['direction']}]  score={r['score']}")
        print(f"    Vol={r['volume']:,}  OI={r['open_interest']:,}  ratio={r['vol_oi']}x  "
              f"premium=${r['premium']:.2f}  flow=${r['dollar_flow']:,.0f}")
        print(f"    {r['dte']}d to exp  moneyness: {r['moneyness_pct']:+.1f}%  "
              f"-> {contracts} contract(s) at ${account_size:.0f} account")


def print_trade_rules(account_size: float) -> None:
    max_risk = account_size * MAX_RISK_PCT
    print("\n" + "=" * 65)
    print(f"  FLIP RULES  (account: ${account_size:,.0f})")
    print("=" * 65)
    print(f"  Max risk/trade:   ${max_risk:.0f}  (25% of account — aggressive but necessary at this size)")
    print(f"  Take profit at:   +{PROFIT_TARGET_PCT*100:.0f}%  — lock in, do NOT hold for the moonshot")
    print(f"  Hard stop at:     -{STOP_LOSS_PCT*100:.0f}%  — no exceptions, no averaging down")
    print(f"  Max open:         2 trades at a time")
    print(f"  When to trade:    BUYER EDGE earnings, UOA score 4+, macro straddle day-of")
    print(f"  When to skip:     No catalyst, VIX > 40, already in 2 trades, SELLER EDGE earnings")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    ap = argparse.ArgumentParser(description="Catalyst Scanner — directional options setups for small accounts")
    ap.add_argument("--account",       type=float, default=500.0,         help="Account size in dollars")
    ap.add_argument("--symbols",       nargs="+",  default=DEFAULT_SYMBOLS, help="Symbols to scan")
    ap.add_argument("--lookahead",     type=int,   default=30,            help="Days ahead for earnings")
    ap.add_argument("--earnings-only", action="store_true")
    ap.add_argument("--uoa-only",      action="store_true")
    ap.add_argument("--no-save",       action="store_true")
    args = ap.parse_args()

    account = float(os.getenv("ACCOUNT_SIZE_OVERRIDE") or args.account)

    print("\n" + "=" * 65)
    print(f"  CATALYST SCANNER  {date.today()}  |  account: ${account:,.0f}")
    print("=" * 65)

    earnings_results, uoa_results = [], []

    if not args.uoa_only:
        earnings_results = scan_earnings(args.symbols, account, args.lookahead)
    if not args.earnings_only:
        uoa_results = scan_uoa(args.symbols)

    print_macro_events()
    print_earnings_report(earnings_results, account)
    print_uoa_report(uoa_results, account)
    print_trade_rules(account)

    if not args.no_save:
        with open(SCAN_LOG, "a", encoding="utf-8") as f:
            f.write(json.dumps({
                "scan_date":    str(date.today()),
                "account_size": account,
                "earnings":     earnings_results,
                "uoa":          uoa_results,
            }) + "\n")
        print(f"\n  Results saved -> {SCAN_LOG}\n")
    else:
        print()


if __name__ == "__main__":
    main()

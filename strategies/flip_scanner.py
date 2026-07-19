#!/usr/bin/env python3
"""
Flip Scanner — morning routine for small account directional options trading.

Run at 9:15am ET before market open. Tells you:
  - Is today worth trading? (catalyst check)
  - Which direction? (pre-market bias)
  - What to buy and at what price?
  - Exact take-profit and stop-loss levels

Three strategies for accounts under $500:
  1. 0DTE Catalyst Scalp  — buy ATM SPY/QQQ call/put on big catalyst days
  2. Earnings Lotto        — buy OTM call/put 2-4 days before earnings (close before print)
  3. Momentum Breakout     — buy OTM weekly call when stock breaks out on volume

Account-rule note: broker day-trading and intraday-margin rules change. Verify
the current broker policy before live use; this scanner does not authorize it.

Usage:
    python strategies/flip_scanner.py
    python strategies/flip_scanner.py --account 500
    python strategies/flip_scanner.py --account 300 --symbols SPY QQQ TSLA NVDA PLTR
"""
from __future__ import annotations

import argparse
import json
import os
from datetime import date, datetime, timedelta
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), "..", "agent", ".env"))

try:
    import yfinance as yf
except ImportError:
    print("ERROR: pip install yfinance")
    raise

LOG_DIR  = Path(os.path.expanduser(r"~\.vibe-trading\logs"))
LOG_DIR.mkdir(parents=True, exist_ok=True)
FLIP_LOG = LOG_DIR / "flip-scans.jsonl"

# Catalyst calendar — update monthly
CATALYST_DAYS = [
    (date(2026, 7, 14),  "CPI",  "CPI release — buy SPY ATM straddle at open, close by noon"),
    (date(2026, 7, 29),  "FOMC", "Fed decision 2pm ET — buy SPY call/put at 9:30am, close before 2pm"),
    (date(2026, 8, 12),  "CPI",  "CPI release — buy SPY ATM straddle at open, close by noon"),
    (date(2026, 9, 11),  "CPI",  "CPI release — buy SPY ATM straddle at open, close by noon"),
    (date(2026, 9, 16),  "FOMC", "Fed decision 2pm ET — buy SPY call/put at 9:30am, close before 2pm"),
    (date(2026, 10, 14), "CPI",  "CPI release — buy SPY ATM straddle at open, close by noon"),
    (date(2026, 10, 28), "FOMC", "Fed decision 2pm ET — buy SPY call/put at 9:30am, close before 2pm"),
]

DEFAULT_SYMBOLS = ["SPY", "QQQ", "TSLA", "NVDA", "AAPL", "META", "AMZN", "AMD", "PLTR", "COIN"]

MAX_RISK_PCT      = 0.02
MAX_CONTRACTS     = 5
PROFIT_TARGET_PCT = 0.75
STOP_LOSS_PCT     = 0.50
GAP_THRESHOLD     = 0.0075
VOLUME_SPIKE      = 2.5


# ---------------------------------------------------------------------------
# Price helpers
# ---------------------------------------------------------------------------

def _last_price(sym: str) -> float:
    try:
        return float(yf.Ticker(sym).fast_info["last_price"])
    except Exception:
        try:
            return float(yf.Ticker(sym).info.get("regularMarketPrice") or 0)
        except Exception:
            return 0.0


def _prev_close(sym: str) -> float:
    try:
        hist = yf.Ticker(sym).history(period="2d", auto_adjust=True)
        return float(hist["Close"].iloc[-2]) if len(hist) >= 2 else 0.0
    except Exception:
        return 0.0


def _pre_market_gap(sym: str) -> tuple[float, str]:
    price = _last_price(sym)
    prev  = _prev_close(sym)
    if price <= 0 or prev <= 0:
        return 0.0, "UNKNOWN"
    gap = (price - prev) / prev
    return abs(gap), "UP" if gap > 0 else "DOWN"


def _atm_0dte_cost(sym: str) -> tuple[float, float, float, str]:
    """(call_price, put_price, atm_strike, expiry)"""
    try:
        t         = yf.Ticker(sym)
        price     = _last_price(sym)
        if price <= 0:
            return 0.0, 0.0, 0.0, ""
        today_str = date.today().strftime("%Y-%m-%d")
        target    = next((e for e in t.options if e >= today_str), None)
        if not target:
            return 0.0, 0.0, 0.0, ""
        chain     = t.option_chain(target)
        calls, puts = chain.calls, chain.puts
        if calls.empty or puts.empty:
            return 0.0, 0.0, 0.0, ""
        atm = calls.iloc[(calls['strike'] - price).abs().argsort()[:1]]['strike'].values[0]
        c   = calls[calls['strike'] == atm]['lastPrice'].values
        p   = puts[puts['strike'] == atm]['lastPrice'].values
        if not len(c) or not len(p):
            return 0.0, 0.0, 0.0, ""
        return float(c[0]), float(p[0]), float(atm), target
    except Exception:
        return 0.0, 0.0, 0.0, ""


# ---------------------------------------------------------------------------
# 0DTE check
# ---------------------------------------------------------------------------

def check_0dte(account_size: float) -> dict:
    today    = date.today()
    max_risk = account_size * MAX_RISK_PCT
    catalyst = next(((d, t, n) for d, t, n in CATALYST_DAYS if d == today), None)
    gap, direction = _pre_market_gap("SPY")
    strong_gap = gap >= GAP_THRESHOLD

    go = catalyst is not None or strong_gap

    if catalyst and "FOMC" in catalyst[1]:
        bias = "STRADDLE — direction unclear until 2pm Fed statement"
    elif catalyst and "CPI" in catalyst[1]:
        bias = "STRADDLE — buy both sides at open, market moves hard on CPI"
    elif strong_gap:
        side = "call" if direction == "UP" else "put"
        bias = f"{direction} bias — gap {gap*100:.2f}% pre-market -> buy {side}"
    else:
        bias = "NEUTRAL — no clear directional edge"

    call_p, put_p, atm, expiry = _atm_0dte_cost("SPY")
    straddle = call_p + put_p
    directional_cost = max(call_p, put_p)
    contracts_straddle = min(int(max_risk // (straddle * 100)), MAX_CONTRACTS) if straddle > 0 else 0
    contracts_directional = min(int(max_risk // (directional_cost * 100)), MAX_CONTRACTS) if directional_cost > 0 else 0

    return {
        "date":                  str(today),
        "go":                    go,
        "catalyst":              catalyst[1] if catalyst else ("GAP" if strong_gap else "NONE"),
        "catalyst_note":         catalyst[2] if catalyst else (f"SPY {direction} {gap*100:.2f}%" if strong_gap else ""),
        "bias":                  bias,
        "spy_price":             _last_price("SPY"),
        "atm_strike":            atm,
        "call_price":            call_p,
        "put_price":             put_p,
        "straddle_cost":         straddle,
        "expiry":                expiry,
        "contracts_straddle":    contracts_straddle,
        "contracts_directional": contracts_directional,
    }


# ---------------------------------------------------------------------------
# Earnings lotto scan
# ---------------------------------------------------------------------------

def _next_earnings(sym: str) -> date | None:
    try:
        cal = yf.Ticker(sym).calendar
        if isinstance(cal, dict):
            ed = cal.get("Earnings Date")
            if ed:
                if hasattr(ed, '__iter__') and not isinstance(ed, str):
                    ed = list(ed)[0]
                return ed.date() if hasattr(ed, 'date') else ed
    except Exception:
        pass
    return None


def _hist_vs_implied(sym: str, e_date: date) -> tuple[float, float, float]:
    """(hist_move_pct, impl_move_pct, approx_otm_call_cost)"""
    try:
        t    = yf.Ticker(sym)
        hist = t.history(period="3y", auto_adjust=True)
        if hist.empty:
            return 0.0, 0.0, 0.0

        edf   = t.earnings_dates
        moves = []
        if edf is not None and not edf.empty:
            hmap   = {d.date(): float(p) for d, p in hist["Close"].items()}
            sdates = sorted(hmap.keys())
            for i, ts in enumerate(edf.index[:6]):
                ed = ts.date() if hasattr(ts, 'date') else ts
                for j, d in enumerate(sdates):
                    if d >= ed and j > 0:
                        prev = hmap[sdates[j - 1]]
                        curr = hmap[d]
                        if prev > 0:
                            moves.append(abs(curr - prev) / prev)
                        break
        hist_avg = sum(moves) / len(moves) if moves else 0.0

        available = t.options
        target    = next((e for e in available if datetime.strptime(e, "%Y-%m-%d").date() >= e_date), None)
        if not target:
            return hist_avg, 0.0, 0.0

        chain = t.option_chain(target)
        price = _last_price(sym)
        if price <= 0 or chain.calls.empty or chain.puts.empty:
            return hist_avg, 0.0, 0.0

        atm   = chain.calls.iloc[(chain.calls['strike'] - price).abs().argsort()[:1]]['strike'].values[0]
        c_row = chain.calls[chain.calls['strike'] == atm]
        p_row = chain.puts[chain.puts['strike'] == atm]
        if c_row.empty or p_row.empty:
            return hist_avg, 0.0, 0.0

        straddle   = float(c_row['lastPrice'].values[0]) + float(p_row['lastPrice'].values[0])
        impl_move  = straddle / price
        otm_call   = round(straddle * 0.4, 2)
        return hist_avg, impl_move, otm_call
    except Exception:
        return 0.0, 0.0, 0.0


def scan_earnings_lottos(symbols: list[str], account_size: float) -> list[dict]:
    today    = date.today()
    cutoff   = today + timedelta(days=14)
    max_risk = account_size * MAX_RISK_PCT
    results  = []

    for sym in symbols:
        e_date = _next_earnings(sym)
        if not e_date or not (today < e_date <= cutoff):
            continue
        days_out              = (e_date - today).days
        hist_pct, impl_pct, otm_call = _hist_vs_implied(sym, e_date)

        score, edge = 0, "—"
        if hist_pct > 0 and impl_pct > 0:
            ratio = hist_pct / impl_pct
            if ratio > 1.3:
                edge, score = "STRONG BUYER EDGE", 3
            elif ratio > 1.1:
                edge, score = "BUYER EDGE", 2
            elif ratio > 0.9:
                edge, score = "FAIR", 1
            else:
                edge, score = "SKIP — overpriced", 0

        contracts = min(int(max_risk // (otm_call * 100)), MAX_CONTRACTS) if otm_call > 0 else 0
        action    = (f"Buy {sym} call {days_out-1}d before earnings, close BEFORE print"
                     if score >= 2 else "SKIP — options too expensive vs historical move")

        results.append({
            "symbol":        sym,
            "earnings_date": str(e_date),
            "days_out":      days_out,
            "hist_move_pct": round(hist_pct * 100, 1),
            "impl_move_pct": round(impl_pct * 100, 1),
            "edge":          edge,
            "score":         score,
            "otm_call_est":  otm_call,
            "contracts":     contracts,
            "action":        action,
        })

    return sorted(results, key=lambda x: x['score'], reverse=True)


# ---------------------------------------------------------------------------
# Momentum breakout scan
# ---------------------------------------------------------------------------

def scan_breakouts(symbols: list[str], account_size: float) -> list[dict]:
    max_risk = account_size * MAX_RISK_PCT
    results  = []

    for sym in [s for s in symbols if s not in ("SPY", "QQQ", "IWM")]:
        try:
            t    = yf.Ticker(sym)
            hist = t.history(period="30d", auto_adjust=True)
            if len(hist) < 22:
                continue

            closes    = hist["Close"].values
            volumes   = hist["Volume"].values
            price     = float(closes[-1])
            high_20   = float(max(closes[-21:-1]))
            avg_vol   = float(sum(volumes[-21:-1]) / 20)
            today_vol = float(volumes[-1])

            if not (price >= high_20 * 0.99 and today_vol >= avg_vol * VOLUME_SPIKE):
                continue

            target_strike = round(price * 1.02 / 0.5) * 0.5
            available     = t.options
            if not available:
                continue
            target_exp = available[1] if len(available) > 1 else available[0]
            chain      = t.option_chain(target_exp)
            if chain.calls.empty:
                continue

            row       = chain.calls.iloc[(chain.calls['strike'] - target_strike).abs().argsort()[:1]]
            call_px   = float(row['lastPrice'].values[0])
            call_str  = float(row['strike'].values[0])
            contracts = min(int(max_risk // (call_px * 100)), MAX_CONTRACTS) if call_px > 0 else 0

            results.append({
                "symbol":      sym,
                "price":       round(price, 2),
                "high_20d":    round(high_20, 2),
                "vol_ratio":   round(today_vol / avg_vol, 1),
                "call_strike": call_str,
                "call_price":  round(call_px, 2),
                "call_expiry": target_exp,
                "contracts":   contracts,
                "action":      f"Buy {sym} ${call_str:.0f} call exp {target_exp} @ ${call_px:.2f}",
            })
        except Exception:
            pass

    return sorted(results, key=lambda x: x['vol_ratio'], reverse=True)


# ---------------------------------------------------------------------------
# Print report
# ---------------------------------------------------------------------------

def print_0dte(r: dict, account_size: float) -> None:
    tradeable = r["contracts_straddle"] > 0 or r["contracts_directional"] > 0
    flag = "GO" if r['go'] and tradeable else ("SIGNAL / NOT AFFORDABLE" if r['go'] else "NO-GO")
    print("\n" + "=" * 65)
    print(f"  0DTE CHECK  [{flag}]")
    print("=" * 65)
    print(f"  Catalyst:  {r['catalyst']}")
    if r['catalyst_note']:
        print(f"  Detail:    {r['catalyst_note']}")
    print(f"  Bias:      {r['bias']}")
    if r['spy_price']:
        print(f"  SPY:       ${r['spy_price']:.2f}  |  ATM: ${r['atm_strike']:.0f}  |  Expiry: {r['expiry']}")
    if r['straddle_cost'] > 0:
        max_risk = account_size * MAX_RISK_PCT
        print(f"  Straddle:  ${r['straddle_cost']:.2f}/contract  (call ${r['call_price']:.2f} + put ${r['put_price']:.2f})")
        print(f"  Budget:    ${max_risk:.0f}, max {MAX_CONTRACTS} contracts -> {r['contracts_straddle']} straddle / {r['contracts_directional']} directional contract(s)")
    if r['go'] and tradeable:
        print(f"\n  ENTRY:   9:30am ET, market open, NOT before")
        print(f"  TARGET:  Close at +{PROFIT_TARGET_PCT*100:.0f}% — set limit order right after fill")
        print(f"  STOP:    Close at -{STOP_LOSS_PCT*100:.0f}% — no exceptions")
        print(f"  CUTOFF:  Exit by 2pm ET regardless — theta destroys you after 2pm")
    elif r['go']:
        print(f"\n  Signal exists, but this account size cannot afford one contract under the risk cap.")
        print(f"  Do NOT force the trade. Wait for a cheaper contract, smaller underlying, or larger bankroll.")
    else:
        nxt = next(((d,t) for d,t,_ in CATALYST_DAYS if d > date.today()), None)
        print(f"\n  No catalyst today. Do NOT trade 0DTE.")
        if nxt:
            print(f"  Next catalyst: {nxt[0]} — {nxt[1]}")


def print_earnings(results: list[dict]) -> None:
    print("\n" + "=" * 65)
    print("  EARNINGS LOTTOS  (buy before earnings, close BEFORE print)")
    print("=" * 65)
    if not results:
        print("  None in next 14 days.")
        return
    for r in results:
        mark = "GO" if r['score'] >= 2 else "SKIP"
        print(f"\n  [{mark}]  {r['symbol']}  earnings {r['earnings_date']} ({r['days_out']}d)  [{r['edge']}]")
        print(f"    Hist avg move: {r['hist_move_pct']:.1f}%  |  Implied: {r['impl_move_pct']:.1f}%")
        if r['otm_call_est'] > 0:
            print(f"    OTM call est:  ${r['otm_call_est']:.2f} = ${r['otm_call_est']*100:.0f}/contract  -> {r['contracts']} contract(s)")
        print(f"    -> {r['action']}")


def print_breakouts(results: list[dict]) -> None:
    print("\n" + "=" * 65)
    print("  MOMENTUM BREAKOUTS  (weekly call, exit in 1-3 days)")
    print("=" * 65)
    if not results:
        print("  No clean breakouts today.")
        return
    for r in results:
        print(f"\n  {r['symbol']}  ${r['price']:.2f}  |  20d high ${r['high_20d']:.2f}  |  vol {r['vol_ratio']}x avg")
        print(f"  -> {r['action']}  ({r['contracts']} contract(s))")


def print_rules(account_size: float) -> None:
    max_risk = account_size * MAX_RISK_PCT
    print("\n" + "=" * 65)
    print(f"  FLIP RULES  (${account_size:,.0f} account)")
    print("=" * 65)
    print(f"  Risk/trade:      ${max_risk:.0f}  ({MAX_RISK_PCT*100:.0f}%, max {MAX_CONTRACTS} contracts)")
    print(f"  Take profit:     +75%  — set limit order IMMEDIATELY after fill")
    print(f"  Hard stop:       -50%  — no averaging down, no hoping")
    print(f"  Max open:        2 trades at once")
    print(f"  Account rules:   Verify current broker intraday-margin and options permissions")
    print(f"                   This scanner does not authorize live trading")
    print()
    print(f"  TRADE PRIORITY:")
    print(f"  1. 0DTE on FOMC/CPI days  <- highest edge")
    print(f"  2. Earnings lotto BUYER EDGE, close day before print")
    print(f"  3. Momentum breakout weekly call on volume spike")
    print(f"  4. Everything else — WAIT, do not force a trade")
    print()


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    ap = argparse.ArgumentParser(description="Flip Scanner — morning routine for small account options")
    ap.add_argument("--account", type=float, default=None,
                    help="Account size to simulate. Overrides FLIP_ACCOUNT_SIZE_OVERRIDE / ACCOUNT_SIZE_OVERRIDE.")
    ap.add_argument("--symbols", nargs="+", default=DEFAULT_SYMBOLS)
    ap.add_argument("--no-save", action="store_true")
    args = ap.parse_args()

    account_override = float(os.getenv("FLIP_ACCOUNT_SIZE_OVERRIDE") or os.getenv("ACCOUNT_SIZE_OVERRIDE", "0") or 0)
    account = args.account if args.account is not None else (account_override if account_override > 0 else 200.0)

    print("\n" + "=" * 65)
    print(f"  FLIP SCANNER  {date.today()}  |  account: ${account:,.0f}")
    print("=" * 65)
    print("Running checks...")

    zero_dte  = check_0dte(account)
    earnings  = scan_earnings_lottos(args.symbols, account)
    breakouts = scan_breakouts(args.symbols, account)

    print_0dte(zero_dte, account)
    print_earnings(earnings)
    print_breakouts(breakouts)
    print_rules(account)

    if not args.no_save:
        with open(FLIP_LOG, "a", encoding="utf-8") as f:
            f.write(json.dumps({
                "scan_date": str(date.today()),
                "account":   account,
                "zero_dte":  zero_dte,
                "earnings":  earnings,
                "breakouts": breakouts,
            }) + "\n")
        print(f"  Saved -> {FLIP_LOG}\n")


if __name__ == "__main__":
    main()

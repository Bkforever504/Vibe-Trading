#!/usr/bin/env python3
"""
Read-only options liquidity feasibility checker.

For each candidate symbol, fetches the option chain (via yfinance) and scores
against five criteria:
  1. 0DTE available (expiry == today)
  2. Weekly available (expiry within WEEKLY_DAYS calendar days)
  3. ATM open interest >= OI_MIN on both calls AND puts
  4. ATM bid-ask spread <= SPREAD_MAX_PCT of mid
  5. ATM contract price <= PRICE_MAX per share ($x * 100 per contract)

Gate: score >= QUALIFY_SCORE (4/5) → flip_shadow_eligible = True.
Any symbol added to SHADOW_CANDIDATES in flip_bot.py should pass this gate first.

No trading. No broker calls. No orders. Safe to run any time.
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import yfinance as yf

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

LOG_PATH = ROOT / "data" / "options_liquidity_feasibility_log.jsonl"
REPORT_PATH = Path.home() / ".vibe-trading" / "reports" / "options-liquidity-feasibility.json"

OI_MIN: int = 500
VOLUME_MIN: int = 100
SPREAD_MAX_PCT: float = 15.0
PRICE_MAX: float = 5.0       # per share; $500/contract max for small-account sizing
QUALIFY_SCORE: int = 4       # out of 5 to be flip_shadow_eligible
WEEKLY_DAYS: int = 7         # calendar days ahead for "weekly" check

DEFAULT_SYMBOLS: list[str] = [
    # Current Flip Bot shadow candidates (already approved)
    "QQQ", "IWM", "NVDA", "TSLA", "AAPL", "GOOGL", "META",
    # Deep scan candidates from 2026-07-02 scan
    "RDDT", "MRNA", "HOOD", "COIN", "RIVN",
    # Watch context names with options interest
    "SPY", "NFLX", "DDOG", "CRWD", "REGN",
]


# ---------------------------------------------------------------------------
# Core check
# ---------------------------------------------------------------------------

def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return default
    return result if math.isfinite(result) else default


def _safe_int(value: Any, default: int = 0) -> int:
    return int(_safe_float(value, float(default)))

def _error_result(sym: str, reason: str) -> dict[str, Any]:
    return {
        "symbol": sym,
        "status": "error",
        "error": reason,
        "has_0dte": False,
        "has_weekly": False,
        "atm_oi_min": 0,
        "atm_volume_min": 0,
        "atm_price": None,
        "atm_spread_pct": None,
        "score": 0,
        "verdict": "not_qualified",
        "flip_shadow_eligible": False,
        "criteria": {
            "0dte_available": False,
            "weekly_available": False,
            "oi_ok": False,
            "volume_ok": False,
            "spread_ok": False,
            "price_ok": False,
        },
    }


def check_symbol(sym: str, today: date | None = None) -> dict[str, Any]:
    """Return feasibility dict for one symbol. Never raises."""
    today = today or date.today()
    today_str = today.strftime("%Y-%m-%d")
    weekly_cutoff = (today + timedelta(days=WEEKLY_DAYS)).strftime("%Y-%m-%d")

    try:
        t = yf.Ticker(sym)
        expirations: tuple[str, ...] = t.options or ()
    except Exception as exc:
        return _error_result(sym, f"ticker_fetch_failed: {str(exc)[:160]}")

    if not expirations:
        return _error_result(sym, "no_option_chain")

    has_0dte = today_str in expirations
    weekly_exps = [e for e in expirations if today_str <= e <= weekly_cutoff]
    has_weekly = bool(weekly_exps)

    # Use nearest expiry for chain analysis
    use_exp = today_str if has_0dte else (weekly_exps[0] if weekly_exps else expirations[0])

    try:
        chain = t.option_chain(use_exp)
        calls = chain.calls
        puts = chain.puts
        fi = t.fast_info
        spot = float(getattr(fi, "last_price", None) or getattr(fi, "previous_close", None) or 0)
    except Exception as exc:
        base = _error_result(sym, f"chain_fetch_failed: {str(exc)[:160]}")
        base["has_0dte"] = has_0dte
        base["has_weekly"] = has_weekly
        base["criteria"]["0dte_available"] = has_0dte
        base["criteria"]["weekly_available"] = has_weekly
        return base

    if spot <= 0 or calls.empty or puts.empty:
        return _error_result(sym, "no_chain_data_or_spot")

    # ATM rows
    call_row = calls.iloc[(calls["strike"] - spot).abs().argsort()[:1]]
    put_row  = puts.iloc[(puts["strike"]  - spot).abs().argsort()[:1]]

    call_oi = _safe_int(call_row["openInterest"].values[0])
    put_oi  = _safe_int(put_row["openInterest"].values[0])
    atm_oi_min = min(call_oi, put_oi)
    oi_ok = atm_oi_min >= OI_MIN

    call_volume = _safe_int(call_row["volume"].values[0]) if "volume" in call_row else 0
    put_volume = _safe_int(put_row["volume"].values[0]) if "volume" in put_row else 0
    atm_volume_min = min(call_volume, put_volume)
    volume_ok = atm_volume_min >= VOLUME_MIN

    # Require both directional sides to be executable. A liquid call does not
    # make the corresponding put liquid, and the bot may need either side.
    call_bid = _safe_float(call_row["bid"].values[0])
    call_ask = _safe_float(call_row["ask"].values[0])
    put_bid = _safe_float(put_row["bid"].values[0])
    put_ask = _safe_float(put_row["ask"].values[0])

    def _spread_pct(bid: float, ask: float) -> float:
        mid = (bid + ask) / 2
        return round((ask - bid) / mid * 100, 1) if bid > 0 and ask > 0 and mid > 0 else 999.0

    call_spread_pct = _spread_pct(call_bid, call_ask)
    put_spread_pct = _spread_pct(put_bid, put_ask)
    spread_pct = max(call_spread_pct, put_spread_pct)
    spread_ok = spread_pct <= SPREAD_MAX_PCT

    # Use the current ask rather than a potentially stale last trade. Use the
    # more expensive side so affordability is valid for calls and puts.
    atm_price = max(call_ask, put_ask)
    price_ok = 0 < atm_price <= PRICE_MAX

    depth_ok = oi_ok and volume_ok
    score = sum([has_0dte, has_weekly, depth_ok, spread_ok, price_ok])
    verdict = "qualified" if score >= QUALIFY_SCORE else "borderline" if score == QUALIFY_SCORE - 1 else "not_qualified"

    return {
        "symbol": sym,
        "status": "ok",
        "spot": round(spot, 2),
        "chain_expiry_used": use_exp,
        "has_0dte": has_0dte,
        "has_weekly": has_weekly,
        "atm_oi_calls": call_oi,
        "atm_oi_puts": put_oi,
        "atm_oi_min": atm_oi_min,
        "oi_ok": oi_ok,
        "atm_volume_calls": call_volume,
        "atm_volume_puts": put_volume,
        "atm_volume_min": atm_volume_min,
        "volume_ok": volume_ok,
        "atm_price": round(atm_price, 2),
        "atm_price_per_contract": round(atm_price * 100, 2),
        "price_ok": price_ok,
        "atm_spread_pct": spread_pct,
        "atm_call_spread_pct": call_spread_pct,
        "atm_put_spread_pct": put_spread_pct,
        "spread_ok": spread_ok,
        "score": score,
        "verdict": verdict,
        "flip_shadow_eligible": score >= QUALIFY_SCORE,
        "criteria": {
            "0dte_available": has_0dte,
            "weekly_available": has_weekly,
            "oi_ok": oi_ok,
            "volume_ok": volume_ok,
            "spread_ok": spread_ok,
            "price_ok": price_ok,
        },
    }


# ---------------------------------------------------------------------------
# Report assembly
# ---------------------------------------------------------------------------

def build_report(symbols: list[str], today: date | None = None) -> dict[str, Any]:
    today = today or date.today()
    results = [check_symbol(sym, today) for sym in symbols]
    qualified   = [r["symbol"] for r in results if r.get("flip_shadow_eligible")]
    borderline  = [r["symbol"] for r in results if r.get("verdict") == "borderline"]
    disqualified = [r["symbol"] for r in results if not r.get("flip_shadow_eligible") and r.get("verdict") != "borderline"]
    return {
        "date": today.isoformat(),
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "execution_mode": "read_only",
        "params": {
            "oi_min": OI_MIN,
            "volume_min": VOLUME_MIN,
            "spread_max_pct": SPREAD_MAX_PCT,
            "price_max_per_share": PRICE_MAX,
            "qualify_score": QUALIFY_SCORE,
            "weekly_days": WEEKLY_DAYS,
        },
        "summary": {
            "total": len(results),
            "qualified": len(qualified),
            "borderline": len(borderline),
            "not_qualified": len(disqualified),
        },
        "qualified_symbols": qualified,
        "borderline_symbols": borderline,
        "results": results,
    }


# ---------------------------------------------------------------------------
# Persistence
# ---------------------------------------------------------------------------

def log_report(report: dict, log_path: Path = LOG_PATH) -> None:
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

    today_str = report.get("date", "")
    deduped = [r for r in rows if r.get("date") != today_str]
    deduped.append(report)
    log_path.write_text("".join(json.dumps(r) + "\n" for r in deduped), encoding="utf-8")


def write_report(report: dict, path: Path = REPORT_PATH) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def load_last_report(log_path: Path = LOG_PATH) -> dict | None:
    if not log_path.exists():
        return None
    for line in reversed(log_path.read_text(encoding="utf-8").splitlines()):
        line = line.strip()
        if line:
            try:
                return json.loads(line)
            except json.JSONDecodeError:
                continue
    return None


# ---------------------------------------------------------------------------
# Print
# ---------------------------------------------------------------------------

def print_report(report: dict) -> None:
    s = report["summary"]
    print(f"\nOptions Liquidity Feasibility | {report['date']}")
    print("=" * 68)
    print(f"Qualified={s['qualified']}  Borderline={s['borderline']}  Not_Qualified={s['not_qualified']}")
    if report.get("qualified_symbols"):
        print(f"Flip-shadow eligible: {', '.join(report['qualified_symbols'])}")
    print()
    header = f"{'Symbol':<8} {'Score':>5}  {'Verdict':<14}  0DTE  Wkly  OI     Sprd%   Price"
    print(header)
    print("-" * len(header))
    for r in report["results"]:
        c = r.get("criteria", {})
        oi_str   = str(r.get("atm_oi_min", "?")).rjust(6) if r.get("status") == "ok" else "  n/a "
        sprd_str = f"{r['atm_spread_pct']:>5.1f}%" if r.get("atm_spread_pct") is not None and r["atm_spread_pct"] != 999.0 else "   n/a"
        px_str   = f"${r['atm_price']:.2f}" if r.get("atm_price") else "  n/a"
        print(
            f"{r['symbol']:<8} {r['score']:>5}  {r.get('verdict','?'):<14}  "
            f"{'Y' if c.get('0dte_available') else 'N':>4}  "
            f"{'Y' if c.get('weekly_available') else 'N':>4}  "
            f"{oi_str}  {sprd_str}  {px_str}"
        )
        if r.get("status") == "error":
            print(f"         error: {r.get('error', '')}")
    print(f"\nGate: score >= {QUALIFY_SCORE}/5 = flip_shadow_eligible")
    print(f"JSON: {REPORT_PATH}\n")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser(description="Options liquidity feasibility gate. Read-only.")
    parser.add_argument("symbols", nargs="*", help="Symbols to check (default: DEFAULT_SYMBOLS)")
    parser.add_argument("--no-write", action="store_true", help="Skip writing log/report files")
    args = parser.parse_args()

    symbols = args.symbols if args.symbols else DEFAULT_SYMBOLS
    print(f"Checking {len(symbols)} symbols: {', '.join(symbols)}")
    report = build_report(symbols)
    print_report(report)
    if not args.no_write:
        log_report(report)
        write_report(report)
        print(f"Logged to {LOG_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

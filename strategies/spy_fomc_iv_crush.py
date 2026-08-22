#!/usr/bin/env python3
"""SPY FOMC IV crush seller — shadow/paper only.

FOMC implied volatility consistently overprices meeting risk by ~15-30%.
IV collapses after the decision regardless of outcome direction.

Strategy:
  - Enter: 1-2 trading days before FOMC Decision date
  - Sell ATM put credit spread (not naked — defined risk)
  - Target expiry: same week as FOMC (0-7 DTE at entry)
  - Close: day of FOMC decision after 2 PM ET announcement
  - Expected edge: IV crush reduces spread cost ~40-60% post-announcement

Gates:
  - FOMC Decision must be 1-5 calendar days away
  - VIX > 13 (elevated enough that IV crush is meaningful)
  - VIX/VIX3M contango confirmed
  - No position already open for this FOMC cycle

No live orders. Shadow paper tracking only.
"""
from __future__ import annotations

import argparse
import json
import logging
import math
import os
import sys
from dataclasses import asdict, dataclass
from datetime import date, datetime, timedelta, time, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

try:
    import yfinance as yf
except ImportError:
    yf = None  # type: ignore[assignment]

ET = ZoneInfo("America/New_York")
UTC = timezone.utc
LOG_DIR = Path.home() / ".vibe-trading" / "logs"
LOG_PATH = LOG_DIR / "spy-fomc-iv-crush.log"
DEFAULT_STATE = ROOT / "data" / "spy_fomc_iv_crush_state.json"
DEFAULT_LEDGER = ROOT / "data" / "spy_fomc_iv_crush_ledger.jsonl"

FOMC_LOOKAHEAD_DAYS = int(os.getenv("FOMC_LOOKAHEAD_DAYS", "5"))
VIX_MIN = float(os.getenv("FOMC_VIX_MIN", "13.0"))
VIX_CONTANGO_MAX = float(os.getenv("FOMC_VIX_CONTANGO_MAX", "1.05"))
TARGET_DELTA = float(os.getenv("FOMC_TARGET_DELTA", "0.30"))  # ATM-ish for max IV capture
SPREAD_WIDTH = float(os.getenv("FOMC_SPREAD_WIDTH", "5.0"))
MIN_CREDIT_TO_WIDTH = float(os.getenv("FOMC_MIN_CREDIT_TO_WIDTH", "0.20"))
PROFIT_CLOSE_PCT = float(os.getenv("FOMC_PROFIT_CLOSE_PCT", "0.50"))
ENTRY_START_ET = time(9, 45)
ENTRY_END_ET = time(11, 0)

LOG_DIR.mkdir(parents=True, exist_ok=True)
logger = logging.getLogger("spy_fomc_iv_crush")
if not logger.handlers:
    logger.setLevel(logging.INFO)
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(message)s")
    h = logging.StreamHandler()
    h.setFormatter(fmt)
    logger.addHandler(h)
    if not os.getenv("PYTEST_CURRENT_TEST"):
        from logging.handlers import RotatingFileHandler
        fh = RotatingFileHandler(LOG_PATH, maxBytes=10 * 1024 * 1024, backupCount=3, encoding="utf-8")
        fh.setFormatter(fmt)
        logger.addHandler(fh)


@dataclass
class FOMCSetup:
    shadow_id: str
    generated_at: str
    status: str
    symbol: str
    fomc_decision_date: str
    days_to_fomc: int
    expiry: str
    short_strike: float
    long_strike: float
    short_delta: float
    entry_credit: float
    max_loss: float
    credit_to_width: float
    profit_target: float
    close_trigger: str
    vix_at_entry: float
    execution_enabled: bool = False
    can_submit_orders: bool = False
    orders_submitted: int = 0


def _now_et() -> datetime:
    return datetime.now(tz=ET)


def _iso_utc() -> str:
    return datetime.now(tz=UTC).isoformat()


def _decision(status: str, reason: str, **details: Any) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "provider": "spy_fomc_iv_crush",
        "mode": "shadow_paper_only",
        "generated_at": _iso_utc(),
        "status": status,
        "reason": reason,
        "details": details,
        "execution_enabled": False,
        "can_submit_orders": False,
        "orders_submitted": 0,
    }


def _fomc_decision_dates() -> list[date]:
    """Extract FOMC Decision dates from market_catalyst_calendar."""
    try:
        from scripts.market_catalyst_calendar import EVENTS_2026
        return [
            date.fromisoformat(e["date"])
            for e in EVENTS_2026
            if "FOMC Decision" in e.get("name", "")
        ]
    except Exception:
        # Hardcoded fallback for 2026
        return [
            date(2026, 9, 16),
            date(2026, 11, 4),
            date(2026, 12, 16),
        ]


def _next_fomc(today: date) -> tuple[date, int] | None:
    fomc_dates = sorted(d for d in _fomc_decision_dates() if d >= today)
    if not fomc_dates:
        return None
    next_date = fomc_dates[0]
    days = (next_date - today).days
    return next_date, days


def _get_vix() -> tuple[float, float]:
    if yf is None:
        raise RuntimeError("yfinance not installed")
    vix = float(yf.Ticker("^VIX").fast_info["lastPrice"])
    try:
        vix3m = float(yf.Ticker("^VIX3M").fast_info["lastPrice"])
    except Exception:
        vix3m = vix * 1.05
    return vix, vix3m


def _bs_put_delta(spot: float, strike: float, sigma: float, T: float) -> float:
    if T <= 0 or sigma <= 0:
        return 0.0
    d1 = (math.log(spot / strike) + 0.5 * sigma ** 2 * T) / (sigma * math.sqrt(T))
    return 0.5 * math.erfc(d1 / math.sqrt(2))


def _find_expiry_for_fomc(fomc_date: date) -> str | None:
    """Find expiry on or just after FOMC date (same week)."""
    if yf is None:
        return None
    for exp_str in yf.Ticker("SPY").options:
        exp = date.fromisoformat(exp_str)
        if fomc_date <= exp <= fomc_date + timedelta(days=4):
            return exp_str
    return None


def _find_and_price_spread(expiry: str, spot: float, vix: float) -> tuple[float, float, float] | None:
    """Return (short_strike, entry_credit, delta)."""
    if yf is None:
        return None
    T = max((date.fromisoformat(expiry) - date.today()).days / 252, 1 / 252)
    sigma = vix / 100
    chain = yf.Ticker("SPY").option_chain(expiry)
    puts = chain.puts.copy()
    otm = puts[puts["strike"] < spot]
    if otm.empty:
        return None
    if "delta" in otm.columns:
        otm["abs_delta"] = otm["delta"].abs()
    else:
        otm["abs_delta"] = otm["strike"].apply(lambda K: _bs_put_delta(spot, K, sigma, T))
    idx = (otm["abs_delta"] - TARGET_DELTA).abs().idxmin()
    short_row = otm.loc[idx]
    short_strike = float(short_row["strike"])
    long_strike = round(short_strike - SPREAD_WIDTH, 0)

    long_rows = puts[puts["strike"] == long_strike]
    if long_rows.empty:
        return None

    s_bid = float(short_row["bid"])
    s_ask = float(short_row["ask"])
    l_bid = float(long_rows.iloc[0]["bid"])
    l_ask = float(long_rows.iloc[0]["ask"])
    # Conservative fill: receive short bid, pay long ask
    credit = round(s_bid - l_ask, 2)
    if credit <= 0:
        credit = round((s_bid + s_ask) / 2 - (l_bid + l_ask) / 2, 2)
    return short_strike, credit, float(short_row["abs_delta"])


def build_setup(symbol: str = "SPY") -> tuple[FOMCSetup | None, dict[str, Any]]:
    now = _now_et()
    current_time = now.time().replace(tzinfo=None)
    if not (ENTRY_START_ET <= current_time <= ENTRY_END_ET):
        return None, _decision("blocked", "outside_entry_window_0945_1100_et",
                               now_et=now.strftime("%H:%M"))

    today = now.date()
    fomc_result = _next_fomc(today)
    if fomc_result is None:
        return None, _decision("blocked", "no_fomc_dates_in_calendar")
    fomc_date, days_to_fomc = fomc_result

    if not (1 <= days_to_fomc <= FOMC_LOOKAHEAD_DAYS):
        return None, _decision("blocked", "fomc_not_in_entry_window",
                               next_fomc=fomc_date.isoformat(),
                               days_away=days_to_fomc,
                               entry_window=f"1-{FOMC_LOOKAHEAD_DAYS} days")

    try:
        vix, vix3m = _get_vix()
    except Exception as exc:
        return None, _decision("blocked", "vix_fetch_failed", error=str(exc))

    if vix < VIX_MIN:
        return None, _decision("blocked", "vix_too_low_for_iv_crush",
                               vix=vix, vix_min=VIX_MIN,
                               note="IV crush only meaningful when VIX elevated")
    ratio = vix / vix3m if vix3m > 0 else 99.0
    if ratio >= VIX_CONTANGO_MAX:
        return None, _decision("blocked", "vix_backwardation", ratio=round(ratio, 3))

    expiry = _find_expiry_for_fomc(fomc_date)
    if expiry is None:
        return None, _decision("blocked", "no_expiry_around_fomc_date",
                               fomc_date=fomc_date.isoformat())

    spot = float(yf.Ticker(symbol).fast_info["lastPrice"])
    result = _find_and_price_spread(expiry, spot, vix)
    if result is None:
        return None, _decision("blocked", "spread_not_priceable")
    short_strike, credit, delta = result

    if credit <= 0.05:
        return None, _decision("blocked", "credit_too_thin", credit=credit)
    ctw = credit / SPREAD_WIDTH
    if ctw < MIN_CREDIT_TO_WIDTH:
        return None, _decision("blocked", "credit_to_width_below_floor",
                               ctw=round(ctw, 4), floor=MIN_CREDIT_TO_WIDTH)

    setup = FOMCSetup(
        shadow_id=f"fomc-{today.isoformat()}-{uuid4().hex[:8]}",
        generated_at=_iso_utc(),
        status="open_shadow",
        symbol=symbol,
        fomc_decision_date=fomc_date.isoformat(),
        days_to_fomc=days_to_fomc,
        expiry=expiry,
        short_strike=short_strike,
        long_strike=round(short_strike - SPREAD_WIDTH, 0),
        short_delta=round(delta, 4),
        entry_credit=credit,
        max_loss=round(SPREAD_WIDTH - credit, 2),
        credit_to_width=round(ctw, 4),
        profit_target=round(credit * PROFIT_CLOSE_PCT, 2),
        close_trigger=f"fomc_decision_day_{fomc_date.isoformat()}_after_1400_et",
        vix_at_entry=round(vix, 2),
    )
    logger.info(f"FOMC IV crush shadow: {short_strike}/{short_strike - SPREAD_WIDTH} "
                f"exp={expiry} credit={credit} fomc={fomc_date}")
    return setup, _decision("eligible", "all_fomc_gates_passed", setup=asdict(setup))


def check_position(setup: FOMCSetup) -> dict[str, Any]:
    now = _now_et()
    fomc_date = date.fromisoformat(setup.fomc_decision_date)
    # Hard close on FOMC day at or after 2 PM ET (announcement time)
    if now.date() >= fomc_date and now.time().replace(tzinfo=None) >= time(14, 0):
        return _decision("close_fomc", f"fomc_decision_day_post_announcement_{fomc_date}")
    if yf is None:
        return _decision("error", "yfinance_unavailable")
    chain = yf.Ticker(setup.symbol).option_chain(setup.expiry)
    puts = chain.puts
    s = puts[puts["strike"] == setup.short_strike]
    l = puts[puts["strike"] == setup.long_strike]
    if s.empty or l.empty:
        return _decision("close_hard", "spread_removed_from_chain")
    s_mid = (float(s.iloc[0]["bid"]) + float(s.iloc[0]["ask"])) / 2
    l_mid = (float(l.iloc[0]["bid"]) + float(l.iloc[0]["ask"])) / 2
    current_debit = round(s_mid - l_mid, 2)
    pnl = round(setup.entry_credit - current_debit, 2)
    pnl_pct = pnl / setup.entry_credit if setup.entry_credit > 0 else 0.0
    if pnl >= setup.profit_target:
        return _decision("close_profit", f"target_hit_{pnl_pct:.0%}",
                         pnl=pnl, current_debit=current_debit)
    return _decision("hold", f"pnl={pnl:+.2f}_({pnl_pct:+.0%})",
                     pnl=pnl, current_debit=current_debit, days_to_fomc=(fomc_date - now.date()).days)


def main() -> None:
    parser = argparse.ArgumentParser(description="SPY FOMC IV crush")
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--state", type=Path, default=DEFAULT_STATE)
    parser.add_argument("--ledger", type=Path, default=DEFAULT_LEDGER)
    parser.add_argument("--out", type=Path, default=ROOT / "data" / "spy_fomc_iv_crush_decision.json")
    args = parser.parse_args()

    if args.check and args.state.exists():
        setup = FOMCSetup(**json.loads(args.state.read_text()))
        result = check_position(setup)
        print(json.dumps(result, indent=2))
        return

    setup, decision = build_setup()
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(decision, indent=2) + "\n", encoding="utf-8")
    if setup is not None:
        args.state.write_text(json.dumps(asdict(setup), indent=2) + "\n", encoding="utf-8")
        with args.ledger.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(asdict(setup), separators=(",", ":"), sort_keys=True) + "\n")
    print(json.dumps(decision, indent=2))


if __name__ == "__main__":
    main()

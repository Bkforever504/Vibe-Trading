#!/usr/bin/env python3
"""Pre-earnings IV capture — shadow/paper only.

Buys ATM straddle 7-10 days before earnings, closes day before announcement.
IV rises into earnings; capturing that expansion is the LONG vol play
(opposite of IV crush sellers).

Targets liquid large-caps: SPY constituents with high-volume options.
Default watchlist: AAPL, NVDA, TSLA, MSFT, AMZN, GOOGL, META.

Gates:
  - Earnings 7-10 calendar days away
  - IV Rank < 50 at entry (room for IV to expand; don't buy already-elevated IV)
  - Stock options have volume > 1000 on ATM strike (liquidity)
  - Bid-ask spread < 10% of mid on ATM straddle

Close rules:
  - Day before earnings (hard exit)
  - 25% loss (stop — IV compressed unexpectedly early)

No live orders. Shadow paper tracking only.
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from dataclasses import asdict, dataclass
from datetime import date, datetime, timedelta, timezone
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
LOG_PATH = LOG_DIR / "spy-earnings-iv-capture.log"
DEFAULT_STATE = ROOT / "data" / "spy_earnings_iv_capture_state.json"
DEFAULT_LEDGER = ROOT / "data" / "spy_earnings_iv_capture_ledger.jsonl"

WATCHLIST = os.getenv("EARNINGS_WATCHLIST", "AAPL,NVDA,TSLA,MSFT,AMZN,GOOGL,META").split(",")
EARNINGS_MIN_DAYS = int(os.getenv("EARNINGS_MIN_DAYS", "7"))
EARNINGS_MAX_DAYS = int(os.getenv("EARNINGS_MAX_DAYS", "10"))
IVR_MAX_ENTRY = float(os.getenv("EARNINGS_IVR_MAX", "50.0"))
MIN_OPTION_VOLUME = int(os.getenv("EARNINGS_MIN_OPTION_VOLUME", "500"))
MAX_SPREAD_PCT = float(os.getenv("EARNINGS_MAX_SPREAD_PCT", "0.12"))
STOP_LOSS_PCT = float(os.getenv("EARNINGS_STOP_LOSS_PCT", "0.25"))

LOG_DIR.mkdir(parents=True, exist_ok=True)
logger = logging.getLogger("spy_earnings_iv_capture")
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
class EarningsSetup:
    shadow_id: str
    generated_at: str
    status: str
    symbol: str
    earnings_date: str
    days_to_earnings: int
    expiry: str
    strike: float
    call_mid: float
    put_mid: float
    straddle_cost: float
    stop_loss_value: float
    close_trigger: str
    spot_at_entry: float
    execution_enabled: bool = False
    can_submit_orders: bool = False
    orders_submitted: int = 0


def _iso_utc() -> str:
    return datetime.now(tz=UTC).isoformat()


def _decision(status: str, reason: str, **details: Any) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "provider": "spy_earnings_iv_capture",
        "mode": "shadow_paper_only",
        "generated_at": _iso_utc(),
        "status": status,
        "reason": reason,
        "details": details,
        "execution_enabled": False,
        "can_submit_orders": False,
        "orders_submitted": 0,
    }


def _get_earnings_date(symbol: str) -> date | None:
    try:
        cal = yf.Ticker(symbol).calendar
        if cal is None:
            return None
        dates = cal.get("Earnings Date", [])
        if not dates:
            return None
        d = dates[0]
        return d if isinstance(d, date) else date.fromisoformat(str(d))
    except Exception:
        return None


def _find_expiry_after(symbol: str, target: date) -> str | None:
    for exp_str in yf.Ticker(symbol).options:
        exp = date.fromisoformat(exp_str)
        if target <= exp <= target + timedelta(days=7):
            return exp_str
    return None


def _price_straddle(symbol: str, expiry: str, spot: float) -> tuple[float, float, float, float] | None:
    """Return (strike, call_mid, put_mid, straddle_cost)."""
    chain = yf.Ticker(symbol).option_chain(expiry)
    # Find ATM strike
    strikes = chain.calls["strike"].values
    atm_strike = min(strikes, key=lambda k: abs(k - spot))
    call_rows = chain.calls[chain.calls["strike"] == atm_strike]
    put_rows = chain.puts[chain.puts["strike"] == atm_strike]
    if call_rows.empty or put_rows.empty:
        return None
    c = call_rows.iloc[0]
    p = put_rows.iloc[0]
    # Liquidity check
    c_vol = float(c.get("volume", 0) or 0)
    p_vol = float(p.get("volume", 0) or 0)
    if min(c_vol, p_vol) < MIN_OPTION_VOLUME:
        return None
    c_mid = (float(c["bid"]) + float(c["ask"])) / 2
    p_mid = (float(p["bid"]) + float(p["ask"])) / 2
    # Spread check on call side
    c_spread_pct = (float(c["ask"]) - float(c["bid"])) / c_mid if c_mid > 0 else 99.0
    if c_spread_pct > MAX_SPREAD_PCT:
        return None
    return float(atm_strike), round(c_mid, 2), round(p_mid, 2), round(c_mid + p_mid, 2)


def scan_candidates() -> list[tuple[str, date, int]]:
    """Return list of (symbol, earnings_date, days_away) within window."""
    today = date.today()
    candidates = []
    for sym in WATCHLIST:
        try:
            earn_date = _get_earnings_date(sym)
            if earn_date is None:
                continue
            days = (earn_date - today).days
            if EARNINGS_MIN_DAYS <= days <= EARNINGS_MAX_DAYS:
                candidates.append((sym, earn_date, days))
        except Exception:
            continue
    return sorted(candidates, key=lambda x: x[2])


def build_setup() -> tuple[EarningsSetup | None, dict[str, Any]]:
    if yf is None:
        return None, _decision("blocked", "yfinance_not_installed")

    candidates = scan_candidates()
    if not candidates:
        return None, _decision("blocked", "no_earnings_in_7_10_day_window",
                               watchlist=WATCHLIST)

    symbol, earn_date, days = candidates[0]
    logger.info(f"Earnings candidate: {symbol} on {earn_date} ({days} days away)")

    spot = float(yf.Ticker(symbol).fast_info["lastPrice"])

    # IVR check — skip if already elevated (IV expansion already priced)
    ivr = None
    try:
        from scripts.options_confluence import latest_iv_rank_context
        ctx = latest_iv_rank_context(symbol, as_of=date.today())
        ivr = ctx.get("ivr")
        if ivr is not None and float(ivr) > IVR_MAX_ENTRY:
            return None, _decision("blocked", "ivr_too_high_iv_already_elevated",
                                   symbol=symbol, ivr=ivr, ivr_max=IVR_MAX_ENTRY)
    except Exception:
        pass  # IVR unavailable — proceed without gate

    expiry = _find_expiry_after(symbol, earn_date)
    if expiry is None:
        return None, _decision("blocked", "no_expiry_around_earnings",
                               symbol=symbol, earnings_date=earn_date.isoformat())

    pricing = _price_straddle(symbol, expiry, spot)
    if pricing is None:
        return None, _decision("blocked", "straddle_not_priceable_or_illiquid",
                               symbol=symbol, expiry=expiry)
    strike, call_mid, put_mid, straddle_cost = pricing

    close_date = earn_date - timedelta(days=1)
    setup = EarningsSetup(
        shadow_id=f"earn-{date.today().isoformat()}-{symbol}-{uuid4().hex[:6]}",
        generated_at=_iso_utc(),
        status="open_shadow",
        symbol=symbol,
        earnings_date=earn_date.isoformat(),
        days_to_earnings=days,
        expiry=expiry,
        strike=strike,
        call_mid=call_mid,
        put_mid=put_mid,
        straddle_cost=straddle_cost,
        stop_loss_value=round(straddle_cost * (1 - STOP_LOSS_PCT), 2),
        close_trigger=f"close_day_before_earnings_{close_date.isoformat()}",
        spot_at_entry=round(spot, 2),
    )
    logger.info(f"Earnings IV capture shadow: {symbol} {strike} straddle={straddle_cost} "
                f"close={close_date} earn={earn_date}")
    return setup, _decision("eligible", "earnings_iv_capture_gates_passed",
                            setup=asdict(setup), ivr_at_entry=ivr)


def check_position(setup: EarningsSetup) -> dict[str, Any]:
    if yf is None:
        return _decision("error", "yfinance_unavailable")
    today = date.today()
    earn_date = date.fromisoformat(setup.earnings_date)
    close_date = earn_date - timedelta(days=1)
    if today >= close_date:
        return _decision("close_hard", f"day_before_earnings_{close_date}_exit")

    chain = yf.Ticker(setup.symbol).option_chain(setup.expiry)
    c = chain.calls[chain.calls["strike"] == setup.strike]
    p = chain.puts[chain.puts["strike"] == setup.strike]
    if c.empty or p.empty:
        return _decision("close_hard", "chain_removed")
    c_mid = (float(c.iloc[0]["bid"]) + float(c.iloc[0]["ask"])) / 2
    p_mid = (float(p.iloc[0]["bid"]) + float(p.iloc[0]["ask"])) / 2
    current_value = round(c_mid + p_mid, 2)
    pnl = round(current_value - setup.straddle_cost, 2)
    pnl_pct = pnl / setup.straddle_cost if setup.straddle_cost > 0 else 0.0

    if current_value <= setup.stop_loss_value:
        return _decision("close_stop", f"stop_loss_hit_{pnl_pct:.0%}",
                         pnl=pnl, current_value=current_value)
    days_left = (close_date - today).days
    return _decision("hold", f"pnl={pnl:+.2f}_({pnl_pct:+.0%})_close_in_{days_left}d",
                     pnl=pnl, pnl_pct=round(pnl_pct, 4), current_value=current_value)


def main() -> None:
    parser = argparse.ArgumentParser(description="Pre-earnings IV capture")
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--state", type=Path, default=DEFAULT_STATE)
    parser.add_argument("--ledger", type=Path, default=DEFAULT_LEDGER)
    parser.add_argument("--out", type=Path, default=ROOT / "data" / "spy_earnings_iv_capture_decision.json")
    parser.add_argument("--scan", action="store_true", help="Print upcoming earnings candidates")
    args = parser.parse_args()

    if args.scan:
        candidates = scan_candidates()
        print(json.dumps([{"symbol": s, "earnings": str(d), "days": n} for s, d, n in candidates], indent=2))
        return

    if args.check and args.state.exists():
        setup = EarningsSetup(**json.loads(args.state.read_text()))
        print(json.dumps(check_position(setup), indent=2))
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

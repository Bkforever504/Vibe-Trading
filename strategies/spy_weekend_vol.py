#!/usr/bin/env python3
"""SPY weekend vol premium — shadow/paper only.

People overpay for portfolio protection over the weekend.
Front-run: buy ATM SPY straddle Thursday afternoon,
sell Friday afternoon (or Monday open if gap validates it).

Research hypothesis only. No validated forward edge has been established.
Source: r/algotrading / OnlyQuants 2026 — "small and dumb edges"

Entry: Thursday 14:30-15:30 ET
Close: Friday 14:00-15:30 ET (primary) OR Monday 09:45-10:15 ET (gap play)
Stop: -25% of straddle cost (IV compressed early unexpectedly)

Gates:
  - VIX contango (people paying up for weekend protection)
  - VIX 12-22 (too low = no premium available; too high = spike already happened)
  - ATM straddle bid-ask spread < 8% of mid (liquidity)

No live orders. Shadow paper tracking only.
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from dataclasses import asdict, dataclass
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.options_observation_journal import append_observation

try:
    import yfinance as yf
except ImportError:
    yf = None  # type: ignore[assignment]

ET = ZoneInfo("America/New_York")
UTC = timezone.utc
LOG_DIR = Path.home() / ".vibe-trading" / "logs"
LOG_PATH = LOG_DIR / "spy-weekend-vol.log"
DEFAULT_STATE = ROOT / "data" / "spy_weekend_vol_state.json"
DEFAULT_LEDGER = ROOT / "data" / "spy_weekend_vol_ledger.jsonl"

ENTRY_START_ET = time(14, 30)
ENTRY_END_ET = time(15, 30)
CLOSE_START_ET = time(14, 0)
CLOSE_END_ET = time(15, 30)
MONDAY_CLOSE_START_ET = time(9, 45)
MONDAY_CLOSE_END_ET = time(10, 15)

VIX_MIN = float(os.getenv("WVOL_VIX_MIN", "12.0"))
VIX_MAX = float(os.getenv("WVOL_VIX_MAX", "22.0"))
VIX_CONTANGO_MAX = float(os.getenv("WVOL_CONTANGO_MAX", "1.0"))
MAX_SPREAD_PCT = float(os.getenv("WVOL_MAX_SPREAD_PCT", "0.08"))
STOP_LOSS_PCT = float(os.getenv("WVOL_STOP_LOSS_PCT", "0.25"))

LOG_DIR.mkdir(parents=True, exist_ok=True)
logger = logging.getLogger("spy_weekend_vol")
if not logger.handlers:
    logger.setLevel(logging.INFO)
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(message)s")
    h = logging.StreamHandler()
    h.setFormatter(fmt)
    logger.addHandler(h)
    if not os.getenv("PYTEST_CURRENT_TEST"):
        from logging.handlers import RotatingFileHandler
        fh = RotatingFileHandler(LOG_PATH, maxBytes=5 * 1024 * 1024, backupCount=3, encoding="utf-8")
        fh.setFormatter(fmt)
        logger.addHandler(fh)


@dataclass
class WeekendVolSetup:
    shadow_id: str
    generated_at: str
    status: str
    symbol: str
    expiry: str
    strike: float
    call_mid: float
    put_mid: float
    straddle_cost: float
    stop_loss_value: float
    entry_date: str
    close_target_date: str
    vix_at_entry: float
    spot_at_entry: float
    pricing_method: str = "entry_asks_exit_bids"
    execution_enabled: bool = False
    can_submit_orders: bool = False
    orders_submitted: int = 0


def _iso_utc() -> str:
    return datetime.now(tz=UTC).isoformat()


def _decision(status: str, reason: str, **details: Any) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "provider": "spy_weekend_vol",
        "mode": "shadow_paper_only",
        "generated_at": _iso_utc(),
        "status": status,
        "reason": reason,
        "details": details,
        "execution_enabled": False,
        "can_submit_orders": False,
        "orders_submitted": 0,
    }


def _next_friday(today: date) -> date:
    days_ahead = (4 - today.weekday()) % 7
    if days_ahead == 0:
        days_ahead = 7
    return today + timedelta(days=days_ahead)


def _price_straddle(expiry: str, spot: float) -> tuple[float, float, float] | None:
    """Return an executable long-straddle entry: strike, call ask, put ask."""
    chain = yf.Ticker("SPY").option_chain(expiry)
    strikes = chain.calls["strike"].values
    atm = min(strikes, key=lambda k: abs(k - spot))
    c_rows = chain.calls[chain.calls["strike"] == atm]
    p_rows = chain.puts[chain.puts["strike"] == atm]
    if c_rows.empty or p_rows.empty:
        return None
    c = c_rows.iloc[0]
    p = p_rows.iloc[0]
    c_bid, c_ask = float(c["bid"]), float(c["ask"])
    p_bid, p_ask = float(p["bid"]), float(p["ask"])
    c_mid = (c_bid + c_ask) / 2
    p_mid = (p_bid + p_ask) / 2
    if min(c_bid, c_ask, p_bid, p_ask) < 0 or c_ask < c_bid or p_ask < p_bid:
        return None
    if c_mid <= 0 or p_mid <= 0:
        return None
    if (c_ask - c_bid) / c_mid > MAX_SPREAD_PCT:
        return None
    if (p_ask - p_bid) / p_mid > MAX_SPREAD_PCT:
        return None
    return float(atm), round(c_ask, 2), round(p_ask, 2)


def build_setup() -> tuple[WeekendVolSetup | None, dict[str, Any]]:
    if yf is None:
        return None, _decision("blocked", "yfinance_unavailable")

    now = datetime.now(tz=ET)
    weekday = now.weekday()
    current_time = now.time().replace(tzinfo=None)

    # Must be Thursday in entry window
    if weekday != 3:
        day_names = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
        return None, _decision("blocked", "not_thursday",
                               today=day_names[weekday],
                               note="Weekend vol entry only Thursday 14:30-15:30 ET")
    if not (ENTRY_START_ET <= current_time <= ENTRY_END_ET):
        return None, _decision("blocked", "outside_entry_window_1430_1530_et",
                               now_et=now.strftime("%H:%M"))

    try:
        vix = float(yf.Ticker("^VIX").fast_info["lastPrice"])
        try:
            vix3m = float(yf.Ticker("^VIX3M").fast_info["lastPrice"])
        except Exception:
            vix3m = vix * 1.05
    except Exception as exc:
        return None, _decision("blocked", "vix_fetch_failed", error=str(exc))

    if not (VIX_MIN <= vix <= VIX_MAX):
        return None, _decision("blocked", "vix_out_of_range", vix=vix,
                               range=f"{VIX_MIN}-{VIX_MAX}")
    ratio = vix / vix3m if vix3m > 0 else 99.0
    if ratio > VIX_CONTANGO_MAX:
        return None, _decision("blocked", "vix_backwardation_no_weekend_premium",
                               ratio=round(ratio, 3),
                               note="Weekend premium only elevated in contango")

    today = now.date()
    friday = _next_friday(today)
    friday_str = friday.isoformat()

    # Find Friday expiry
    spy_opts = yf.Ticker("SPY").options
    if friday_str not in spy_opts:
        # Try next available
        expiry = next((e for e in spy_opts
                       if date.fromisoformat(e) >= friday
                       and (date.fromisoformat(e) - friday).days <= 3), None)
        if expiry is None:
            return None, _decision("blocked", "no_friday_expiry", next_friday=friday_str)
    else:
        expiry = friday_str

    spot = float(yf.Ticker("SPY").fast_info["lastPrice"])
    pricing = _price_straddle(expiry, spot)
    if pricing is None:
        return None, _decision("blocked", "straddle_not_priceable_or_illiquid", expiry=expiry)
    strike, call_entry_price, put_entry_price = pricing
    straddle_cost = round(call_entry_price + put_entry_price, 2)

    setup = WeekendVolSetup(
        shadow_id=f"wvol-{today.isoformat()}-{uuid4().hex[:6]}",
        generated_at=_iso_utc(),
        status="open_shadow",
        symbol="SPY",
        expiry=expiry,
        strike=strike,
        call_mid=call_entry_price,
        put_mid=put_entry_price,
        straddle_cost=straddle_cost,
        stop_loss_value=round(straddle_cost * (1 - STOP_LOSS_PCT), 2),
        entry_date=today.isoformat(),
        close_target_date=friday_str,
        vix_at_entry=round(vix, 2),
        spot_at_entry=round(spot, 2),
    )
    logger.info(f"Weekend vol shadow: {strike} straddle={straddle_cost} "
                f"exp={expiry} vix={vix:.1f}")
    return setup, _decision("eligible", "weekend_vol_gates_passed", setup=asdict(setup))


def check_position(setup: WeekendVolSetup) -> dict[str, Any]:
    if yf is None:
        return _decision("error", "yfinance_unavailable")
    now = datetime.now(tz=ET)
    weekday = now.weekday()
    current_time = now.time().replace(tzinfo=None)

    # Expired
    if date.fromisoformat(setup.expiry) < date.today():
        return _decision("expired", "expiry_passed")

    chain = yf.Ticker(setup.symbol).option_chain(setup.expiry)
    c = chain.calls[chain.calls["strike"] == setup.strike]
    p = chain.puts[chain.puts["strike"] == setup.strike]
    if c.empty or p.empty:
        return _decision("close_hard", "chain_removed")

    current = round(float(c.iloc[0]["bid"]) + float(p.iloc[0]["bid"]), 2)
    pnl = round(current - setup.straddle_cost, 2)
    pnl_pct = pnl / setup.straddle_cost if setup.straddle_cost > 0 else 0.0

    if weekday == 0 and (MONDAY_CLOSE_START_ET <= current_time <= MONDAY_CLOSE_END_ET):
        return _decision(
            "close_monday", "monday_gap_play_close_window_0945_1015",
            pnl=pnl, pnl_pct=round(pnl_pct, 4), executable_close_value=current,
        )

    if weekday == 4 and (CLOSE_START_ET <= current_time <= CLOSE_END_ET):
        return _decision(
            "close_friday", "friday_primary_close_window_1400_1530",
            pnl=pnl, pnl_pct=round(pnl_pct, 4), executable_close_value=current,
        )

    if current <= setup.stop_loss_value:
        return _decision("close_stop", f"stop_hit_{pnl_pct:.0%}",
                         pnl=pnl, current=current)
    return _decision("hold", f"pnl={pnl:+.2f}_({pnl_pct:+.0%})",
                     pnl=pnl, pnl_pct=round(pnl_pct, 4), current=current)


def main() -> None:
    parser = argparse.ArgumentParser(description="SPY weekend vol premium")
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--state", type=Path, default=DEFAULT_STATE)
    parser.add_argument("--ledger", type=Path, default=DEFAULT_LEDGER)
    parser.add_argument("--out", type=Path, default=ROOT / "data" / "spy_weekend_vol_decision.json")
    args = parser.parse_args()

    existing: WeekendVolSetup | None = None
    if args.state.exists():
        try:
            existing = WeekendVolSetup(**json.loads(args.state.read_text(encoding="utf-8")))
        except (OSError, json.JSONDecodeError, TypeError, ValueError) as exc:
            decision = _decision("blocked", "existing_weekend_state_unreadable", error=type(exc).__name__)
            args.out.parent.mkdir(parents=True, exist_ok=True)
            args.out.write_text(json.dumps(decision, indent=2) + "\n", encoding="utf-8")
            print(json.dumps(decision, indent=2))
            return

    if args.check and existing is None:
        setup = None
        decision = _decision("skipped", "no_open_weekend_vol_state")
    elif existing is not None and existing.status == "open_shadow":
        setup = None
        decision = check_position(existing)
        if decision["status"].startswith("close_") or decision["status"] == "expired":
            details = decision.get("details", {})
            existing.status = "closed_shadow"
            args.state.write_text(json.dumps(asdict(existing), indent=2) + "\n", encoding="utf-8")
            args.ledger.parent.mkdir(parents=True, exist_ok=True)
            with args.ledger.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps({
                    "type": "close_shadow",
                    "shadow_id": existing.shadow_id,
                    "generated_at": decision["generated_at"],
                    "reason": decision["reason"],
                    "pnl": details.get("pnl"),
                    "executable_close_value": details.get("executable_close_value"),
                    "execution_enabled": False,
                    "can_submit_orders": False,
                }, separators=(",", ":"), sort_keys=True) + "\n")
    elif args.check:
        setup = None
        decision = _decision("skipped", "no_open_weekend_vol_position", state_status=existing.status)
    else:
        setup, decision = build_setup()

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(decision, indent=2) + "\n", encoding="utf-8")
    if setup is not None:
        args.state.parent.mkdir(parents=True, exist_ok=True)
        args.ledger.parent.mkdir(parents=True, exist_ok=True)
        args.state.write_text(json.dumps(asdict(setup), indent=2) + "\n", encoding="utf-8")
        with args.ledger.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(asdict(setup), separators=(",", ":"), sort_keys=True) + "\n")
    append_observation(
        decision,
        provider="spy_weekend_vol",
        setup=asdict(setup or existing) if (setup or existing) is not None else None,
    )
    print(json.dumps(decision, indent=2))


if __name__ == "__main__":
    main()

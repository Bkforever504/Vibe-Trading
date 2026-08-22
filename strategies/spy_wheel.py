#!/usr/bin/env python3
"""SPY/QQQ Wheel Strategy — shadow/paper only.

State machine: IDLE → CSP_OPEN → ASSIGNED → CC_OPEN → IDLE
Sells cash-secured puts. On assignment, sells covered calls at or above cost basis.
Most documented retail options income system. Structural edge: VRP + cost basis reduction.

Gates:
  - VIX 13-25 (too low = no premium; too high = assignment risk)
  - IVR > 20 (some elevation needed)
  - CSP delta: 0.25-0.35 (higher than theta harvester — wheel expects occasional assignment)
  - CC strike >= cost basis (never sell below what you paid)
  - DTE 21-35 for both legs

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
from datetime import date, datetime, timedelta, timezone
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
LOG_PATH = LOG_DIR / "spy-wheel.log"
DEFAULT_STATE = ROOT / "data" / "spy_wheel_state.json"
DEFAULT_LEDGER = ROOT / "data" / "spy_wheel_ledger.jsonl"

SYMBOLS = os.getenv("WHEEL_SYMBOLS", "SPY,QQQ").split(",")
VIX_MIN = float(os.getenv("WHEEL_VIX_MIN", "13.0"))
VIX_MAX = float(os.getenv("WHEEL_VIX_MAX", "25.0"))
IVR_MIN = float(os.getenv("WHEEL_IVR_MIN", "20.0"))
CSP_DELTA = float(os.getenv("WHEEL_CSP_DELTA", "0.30"))
DTE_MIN = int(os.getenv("WHEEL_DTE_MIN", "21"))
DTE_MAX = int(os.getenv("WHEEL_DTE_MAX", "35"))
PROFIT_CLOSE_PCT = float(os.getenv("WHEEL_PROFIT_CLOSE_PCT", "0.50"))
PAPER_ACCOUNT_SIZE = float(os.getenv("PAPER_ACCOUNT_SIZE", "10000.0"))

LOG_DIR.mkdir(parents=True, exist_ok=True)
logger = logging.getLogger("spy_wheel")
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
class WheelState:
    shadow_id: str
    generated_at: str
    phase: str          # idle | csp_open | assigned | cc_open
    symbol: str
    cost_basis: float   # 0 if no assignment yet
    shares_held: int    # 0 or 100
    # Current open leg
    leg_type: str | None        # "put" | "call" | None
    leg_expiry: str | None
    leg_strike: float | None
    leg_entry_credit: float | None
    leg_profit_target: float | None
    leg_opened_at: str | None
    # Cycle tracking
    total_premium_collected: float
    cycles_completed: int
    execution_enabled: bool = False
    can_submit_orders: bool = False
    orders_submitted: int = 0


def _iso_utc() -> str:
    return datetime.now(tz=UTC).isoformat()


def _decision(status: str, reason: str, **details: Any) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "provider": "spy_wheel",
        "mode": "shadow_paper_only",
        "generated_at": _iso_utc(),
        "status": status,
        "reason": reason,
        "details": details,
        "execution_enabled": False,
        "can_submit_orders": False,
        "orders_submitted": 0,
    }


def _get_vix() -> float:
    return float(yf.Ticker("^VIX").fast_info["lastPrice"]) if yf else 0.0


def _get_ivr(symbol: str) -> float | None:
    try:
        from scripts.options_confluence import latest_iv_rank_context
        return latest_iv_rank_context(symbol, as_of=date.today()).get("ivr")
    except Exception:
        return None


def _bs_put_delta(spot: float, strike: float, sigma: float, T: float) -> float:
    if T <= 0 or sigma <= 0:
        return 0.0
    d1 = (math.log(spot / strike) + 0.5 * sigma ** 2 * T) / (sigma * math.sqrt(T))
    return 0.5 * math.erfc(d1 / math.sqrt(2))


def _find_expiry(symbol: str) -> str | None:
    today = date.today()
    for exp_str in yf.Ticker(symbol).options:
        dte = (date.fromisoformat(exp_str) - today).days
        if DTE_MIN <= dte <= DTE_MAX:
            return exp_str
    return None


def _find_put_strike(symbol: str, expiry: str, spot: float, vix: float) -> tuple[float, float, float] | None:
    """Return (strike, credit, delta)."""
    T = max((date.fromisoformat(expiry) - date.today()).days / 252, 1 / 252)
    sigma = vix / 100
    chain = yf.Ticker(symbol).option_chain(expiry)
    puts = chain.puts.copy()
    otm = puts[puts["strike"] < spot]
    if otm.empty:
        return None
    if "delta" in otm.columns:
        otm["abs_delta"] = otm["delta"].abs()
    else:
        otm["abs_delta"] = otm["strike"].apply(lambda K: _bs_put_delta(spot, K, sigma, T))
    idx = (otm["abs_delta"] - CSP_DELTA).abs().idxmin()
    row = otm.loc[idx]
    strike = float(row["strike"])
    bid = float(row["bid"])
    ask = float(row["ask"])
    if not math.isfinite(bid) or not math.isfinite(ask) or bid <= 0 or ask < bid:
        return None
    return strike, round(bid, 2), float(row["abs_delta"])


def _find_call_strike(symbol: str, expiry: str, cost_basis: float) -> tuple[float, float] | None:
    """Return (strike, credit) for CC at or above cost basis."""
    chain = yf.Ticker(symbol).option_chain(expiry)
    calls = chain.calls.copy()
    otm = calls[calls["strike"] >= cost_basis]
    if otm.empty:
        return None
    # Nearest OTM call at or above cost basis
    row = otm.iloc[0]
    bid = float(row["bid"])
    ask = float(row["ask"])
    if not math.isfinite(bid) or not math.isfinite(ask) or bid <= 0 or ask < bid:
        return None
    return float(row["strike"]), round(bid, 2)


def sell_put(symbol: str, state: WheelState) -> tuple[WheelState | None, dict[str, Any]]:
    if yf is None:
        return None, _decision("blocked", "yfinance_unavailable")
    vix = _get_vix()
    if not (VIX_MIN <= vix <= VIX_MAX):
        return None, _decision("blocked", "vix_out_of_wheel_range", vix=vix, range=f"{VIX_MIN}-{VIX_MAX}")
    ivr = _get_ivr(symbol)
    if ivr is not None and float(ivr) < IVR_MIN:
        return None, _decision("blocked", "ivr_below_min", ivr=ivr, ivr_min=IVR_MIN)

    spot = float(yf.Ticker(symbol).fast_info["lastPrice"])
    expiry = _find_expiry(symbol)
    if expiry is None:
        return None, _decision("blocked", "no_expiry_in_dte_window", symbol=symbol)

    result = _find_put_strike(symbol, expiry, spot, vix)
    if result is None:
        return None, _decision("blocked", "put_strike_not_found")
    strike, credit, delta = result
    if credit < 0.10:
        return None, _decision("blocked", "credit_too_thin", credit=credit)
    cash_requirement = strike * 100.0
    if cash_requirement > PAPER_ACCOUNT_SIZE:
        return None, _decision(
            "blocked",
            "insufficient_cash_for_cash_secured_put",
            strike=strike,
            cash_requirement=round(cash_requirement, 2),
            paper_account_size=PAPER_ACCOUNT_SIZE,
        )

    state.phase = "csp_open"
    state.leg_type = "put"
    state.leg_expiry = expiry
    state.leg_strike = strike
    state.leg_entry_credit = credit
    state.leg_profit_target = round(credit * PROFIT_CLOSE_PCT, 2)
    state.leg_opened_at = _iso_utc()
    state.total_premium_collected = round(state.total_premium_collected + credit, 2)
    logger.info(f"WHEEL [{symbol}]: sell put {strike} exp={expiry} credit={credit} vix={vix:.1f}")
    return state, _decision("put_sold", f"csp_open_{symbol}_{strike}P_{expiry}",
                            strike=strike, credit=credit, delta=round(delta, 4),
                            expiry=expiry, vix=vix)


def handle_assignment(symbol: str, state: WheelState) -> tuple[WheelState, dict[str, Any]]:
    """Record assignment — we now hold 100 shares at strike price as cost basis."""
    cost_basis = state.leg_strike or 0.0
    # Cost basis reduced by premium already collected
    adjusted_basis = round(cost_basis - (state.leg_entry_credit or 0.0), 2)
    state.phase = "assigned"
    state.shares_held = 100
    state.cost_basis = adjusted_basis
    state.leg_type = None
    state.leg_expiry = None
    state.leg_strike = None
    state.leg_entry_credit = None
    logger.info(f"WHEEL [{symbol}]: ASSIGNED at {cost_basis} adjusted_basis={adjusted_basis}")
    return state, _decision("assigned", f"shares_acquired_{symbol}_basis_{adjusted_basis}",
                            cost_basis=adjusted_basis, shares=100)


def sell_call(symbol: str, state: WheelState) -> tuple[WheelState | None, dict[str, Any]]:
    if yf is None or state.cost_basis <= 0:
        return None, _decision("blocked", "no_cost_basis_for_cc")
    vix = _get_vix()
    spot = float(yf.Ticker(symbol).fast_info["lastPrice"])
    expiry = _find_expiry(symbol)
    if expiry is None:
        return None, _decision("blocked", "no_expiry_for_cc")

    result = _find_call_strike(symbol, expiry, state.cost_basis)
    if result is None:
        return None, _decision("blocked", "no_call_at_or_above_basis",
                               cost_basis=state.cost_basis, spot=spot)
    strike, credit = result
    if credit < 0.05:
        return None, _decision("blocked", "cc_credit_too_thin", credit=credit)

    state.phase = "cc_open"
    state.leg_type = "call"
    state.leg_expiry = expiry
    state.leg_strike = strike
    state.leg_entry_credit = credit
    state.leg_profit_target = round(credit * PROFIT_CLOSE_PCT, 2)
    state.leg_opened_at = _iso_utc()
    state.total_premium_collected = round(state.total_premium_collected + credit, 2)
    logger.info(f"WHEEL [{symbol}]: sell call {strike} exp={expiry} credit={credit}")
    return state, _decision("call_sold", f"cc_open_{symbol}_{strike}C_{expiry}",
                            strike=strike, credit=credit, cost_basis=state.cost_basis)


def check_and_advance(symbol: str, state: WheelState) -> tuple[WheelState, dict[str, Any]]:
    """Check current leg P&L and advance state machine if needed."""
    if state.phase == "idle":
        return state, _decision("idle", "ready_to_sell_put")

    if state.leg_strike is None or state.leg_expiry is None:
        return state, _decision("error", "corrupt_state_missing_leg")

    if yf is None:
        return state, _decision("error", "yfinance_unavailable")

    expiry_date = date.fromisoformat(state.leg_expiry)
    today = date.today()
    dte_remaining = (expiry_date - today).days

    ticker = yf.Ticker(symbol)
    spot = float(ticker.fast_info["lastPrice"])

    if dte_remaining <= 0:
        # Expired worthless or removed — cycle complete
        if state.phase == "csp_open":
            if spot < state.leg_strike:
                return handle_assignment(symbol, state)
            state.phase = "idle"
            state.leg_type = None
            state.leg_strike = None
            state.leg_expiry = None
            state.leg_entry_credit = None
            state.leg_profit_target = None
            state.cycles_completed += 1
            return state, _decision("expired_worthless", "put_expired_keep_premium_cycle_complete",
                                    spot=spot, cycles=state.cycles_completed,
                                    total_premium=state.total_premium_collected)
        elif state.phase == "cc_open":
            if spot > state.leg_strike:
                called_strike = state.leg_strike
                state.phase = "idle"
                state.shares_held = 0
                state.cost_basis = 0.0
                state.leg_type = None
                state.leg_strike = None
                state.leg_expiry = None
                state.leg_entry_credit = None
                state.leg_profit_target = None
                state.cycles_completed += 1
                return state, _decision(
                    "called_away", "covered_call_assigned_cycle_complete",
                    spot=spot, called_strike=called_strike,
                    cycles=state.cycles_completed,
                )
            # Call expired — shares still held, start new CC
            state.phase = "assigned"
            state.leg_type = None
            state.leg_strike = None
            state.leg_expiry = None
            state.leg_entry_credit = None
            state.leg_profit_target = None
            state.cycles_completed += 1
            return state, _decision("cc_expired", "covered_call_expired_sell_next_cc",
                                    cycles=state.cycles_completed)

    chain = ticker.option_chain(state.leg_expiry)
    df = chain.puts if state.leg_type == "put" else chain.calls
    if "strike" not in df.columns:
        return state, _decision(
            "blocked", "open_leg_quote_unavailable",
            strike=state.leg_strike, expiry=state.leg_expiry,
            dte_remaining=dte_remaining,
        )
    rows = df[df["strike"] == state.leg_strike]
    if rows.empty:
        return state, _decision(
            "blocked", "open_leg_quote_unavailable",
            strike=state.leg_strike, expiry=state.leg_expiry,
            dte_remaining=dte_remaining,
        )

    row = rows.iloc[0]
    current_ask = float(row["ask"])
    if not math.isfinite(current_ask) or current_ask < 0:
        return state, _decision("blocked", "invalid_executable_close_quote")
    entry = state.leg_entry_credit or 0.01
    pnl = round(entry - current_ask, 2)
    pnl_pct = pnl / entry

    if pnl >= (state.leg_profit_target or 0):
        closed_phase = state.phase
        state.phase = "idle" if closed_phase == "csp_open" else "assigned"
        state.leg_type = None
        state.leg_strike = None
        state.leg_expiry = None
        state.leg_entry_credit = None
        state.leg_profit_target = None
        state.cycles_completed += 1
        return state, _decision("close_profit", f"target_hit_{pnl_pct:.0%}",
                                pnl=pnl, executable_close_debit=current_ask,
                                next_phase=state.phase, dte_remaining=dte_remaining)

    return state, _decision("hold", f"pnl={pnl:+.2f}_({pnl_pct:+.0%})_dte={dte_remaining}",
                            pnl=pnl, executable_close_debit=current_ask,
                            dte_remaining=dte_remaining)


def _load_state(path: Path, symbol: str) -> WheelState:
    if path.exists():
        return WheelState(**json.loads(path.read_text()))
    return WheelState(
        shadow_id=f"wheel-{symbol}-{uuid4().hex[:8]}",
        generated_at=_iso_utc(),
        phase="idle",
        symbol=symbol,
        cost_basis=0.0,
        shares_held=0,
        leg_type=None,
        leg_expiry=None,
        leg_strike=None,
        leg_entry_credit=None,
        leg_profit_target=None,
        leg_opened_at=None,
        total_premium_collected=0.0,
        cycles_completed=0,
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="SPY/QQQ Wheel Strategy")
    parser.add_argument("--symbol", default="SPY", choices=SYMBOLS + ["SPY", "QQQ"])
    parser.add_argument("--assign", action="store_true", help="Mark current CSP as assigned")
    parser.add_argument("--state", type=Path, default=DEFAULT_STATE)
    parser.add_argument("--ledger", type=Path, default=DEFAULT_LEDGER)
    parser.add_argument("--out", type=Path, default=ROOT / "data" / "spy_wheel_decision.json")
    args = parser.parse_args()

    state = _load_state(args.state, args.symbol)

    invalid_collateral = (
        state.phase == "csp_open"
        and state.leg_strike is not None
        and state.leg_strike * 100.0 > PAPER_ACCOUNT_SIZE
    )
    if invalid_collateral:
        decision = _decision(
            "blocked",
            "existing_shadow_exceeds_cash_secured_collateral",
            cash_requirement=round(float(state.leg_strike) * 100.0, 2),
            paper_account_size=PAPER_ACCOUNT_SIZE,
            note="Preserved for audit but excluded from portfolio metrics",
        )
    elif args.assign and state.phase == "csp_open":
        state, decision = handle_assignment(args.symbol, state)
    elif state.phase == "idle":
        next_state, decision = sell_put(args.symbol, state)
        state = next_state or state
    elif state.phase == "csp_open":
        state, decision = check_and_advance(args.symbol, state)
    elif state.phase == "assigned":
        next_state, decision = sell_call(args.symbol, state)
        state = next_state or state
    elif state.phase == "cc_open":
        state, decision = check_and_advance(args.symbol, state)
    else:
        decision = _decision("error", f"unknown_phase_{state.phase}")

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(decision, indent=2) + "\n", encoding="utf-8")
    args.state.write_text(json.dumps(asdict(state), indent=2) + "\n", encoding="utf-8")
    with args.ledger.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps({"ts": _iso_utc(), "phase": state.phase,
                              "decision": decision["status"], "reason": decision["reason"],
                              "symbol": args.symbol}, separators=(",", ":")) + "\n")
    append_observation(decision, provider="spy_wheel", setup=asdict(state))
    print(json.dumps(decision, indent=2))


if __name__ == "__main__":
    main()

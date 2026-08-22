#!/usr/bin/env python3
"""VIX call hedge — shadow/paper only.

Buys OTM VIX calls as portfolio tail-risk protection when running
short-premium positions. Modeled after ThetaGang's VIX Tail Hedge.

Logic:
  - Size: 1 VIX call per $10K notional short-premium exposure
  - Strike: VIX spot × 1.5 (30% OTM) or nearest liquid strike above
  - DTE: 45-60 days (rolls before 21 DTE)
  - Entry: only when VIX contango (cheap vol insurance)
  - Exit: VIX spikes to strike × 0.8 OR rolls at 21 DTE

Payoff: VIX call pays when market crashes and vol spikes.
During normal markets the hedge expires worthless (cost of insurance).

No live orders. Shadow tracking only.
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

from scripts.options_observation_journal import append_observation

try:
    import yfinance as yf
except ImportError:
    yf = None  # type: ignore[assignment]

UTC = timezone.utc
LOG_DIR = Path.home() / ".vibe-trading" / "logs"
LOG_PATH = LOG_DIR / "vix-call-hedge.log"
DEFAULT_STATE = ROOT / "data" / "vix_call_hedge_state.json"
DEFAULT_LEDGER = ROOT / "data" / "vix_call_hedge_ledger.jsonl"

HEDGE_NOTIONAL_PER_CONTRACT = float(os.getenv("VIX_HEDGE_NOTIONAL", "10000.0"))
STRIKE_MULTIPLIER = float(os.getenv("VIX_HEDGE_STRIKE_MULT", "1.5"))
DTE_MIN = int(os.getenv("VIX_HEDGE_DTE_MIN", "45"))
DTE_MAX = int(os.getenv("VIX_HEDGE_DTE_MAX", "60"))
ROLL_DTE = int(os.getenv("VIX_HEDGE_ROLL_DTE", "21"))
CONTANGO_MAX = float(os.getenv("VIX_HEDGE_CONTANGO_MAX", "1.0"))  # VIX < VIX3M = buy insurance cheap
MAX_CALL_COST = float(os.getenv("VIX_HEDGE_MAX_CALL_COST", "2.00"))  # per contract
PAPER_ACCOUNT_SIZE = float(os.getenv("PAPER_ACCOUNT_SIZE", "10000.0"))
MAX_HEDGE_COST_PCT = float(os.getenv("VIX_HEDGE_MAX_COST_PCT", "0.005"))

LOG_DIR.mkdir(parents=True, exist_ok=True)
logger = logging.getLogger("vix_call_hedge")
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
class HedgeSetup:
    shadow_id: str
    generated_at: str
    status: str
    vix_at_entry: float
    vix3m_at_entry: float
    target_strike: float
    actual_strike: float
    expiry: str
    dte: int
    call_mid: float
    contracts: int
    total_cost: float
    notional_protected: float
    roll_at_dte: int
    execution_enabled: bool = False
    can_submit_orders: bool = False
    orders_submitted: int = 0


def _iso_utc() -> str:
    return datetime.now(tz=UTC).isoformat()


def _decision(status: str, reason: str, **details: Any) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "provider": "vix_call_hedge",
        "mode": "shadow_paper_only",
        "generated_at": _iso_utc(),
        "status": status,
        "reason": reason,
        "details": details,
        "execution_enabled": False,
        "can_submit_orders": False,
        "orders_submitted": 0,
    }


def _get_vix_term() -> tuple[float, float]:
    if yf is None:
        raise RuntimeError("yfinance unavailable")
    vix = float(yf.Ticker("^VIX").fast_info["lastPrice"])
    try:
        vix3m = float(yf.Ticker("^VIX3M").fast_info["lastPrice"])
    except Exception:
        vix3m = vix * 1.05
    return vix, vix3m


def _current_short_premium_notional() -> float:
    """Sum notional of all open shadow theta positions."""
    total = 0.0
    state_files = [
        ROOT / "data" / "theta_harvester_state.json",
        ROOT / "data" / "spy_0dte_pm_state.json",
        ROOT / "data" / "spy_iron_condor_state.json",
        ROOT / "data" / "spy_fomc_iv_crush_state.json",
        ROOT / "data" / "spy_wheel_state.json",
    ]
    for path in state_files:
        if not path.exists():
            continue
        try:
            s = json.loads(path.read_text())
            if s.get("status") in ("open_shadow", "csp_open", "cc_open"):
                credit = s.get("entry_credit") or s.get("total_credit") or s.get("leg_entry_credit") or 0
                total += float(credit) * 100  # per contract notional
        except Exception:
            continue
    return max(total, HEDGE_NOTIONAL_PER_CONTRACT)  # always hedge at least 1 unit


def build_hedge(contracts_override: int | None = None) -> tuple[HedgeSetup | None, dict[str, Any]]:
    if yf is None:
        return None, _decision("blocked", "yfinance_unavailable")
    try:
        vix, vix3m = _get_vix_term()
    except Exception as exc:
        return None, _decision("blocked", "vix_fetch_failed", error=str(exc))

    ratio = vix / vix3m if vix3m > 0 else 99.0
    if ratio > CONTANGO_MAX:
        return None, _decision("blocked", "vix_not_contango_hedge_expensive",
                               ratio=round(ratio, 3), max=CONTANGO_MAX,
                               note="Only buy VIX calls when vol curve is in contango")

    target_strike = round(vix * STRIKE_MULTIPLIER, 0)
    today = date.today()

    # Find VIX expiry in DTE window
    vix_ticker = yf.Ticker("^VIX")
    expiry = None
    for exp_str in vix_ticker.options:
        dte = (date.fromisoformat(exp_str) - today).days
        if DTE_MIN <= dte <= DTE_MAX:
            expiry = exp_str
            break
    if expiry is None:
        return None, _decision("blocked", "no_vix_expiry_in_dte_window",
                               dte_range=f"{DTE_MIN}-{DTE_MAX}")

    dte = (date.fromisoformat(expiry) - today).days
    chain = vix_ticker.option_chain(expiry)
    calls = chain.calls[chain.calls["strike"] >= target_strike]
    if calls.empty:
        return None, _decision("blocked", "no_vix_call_at_or_above_target_strike",
                               target=target_strike)

    row = calls.iloc[0]
    actual_strike = float(row["strike"])
    call_bid = float(row["bid"])
    call_ask = float(row["ask"])
    if call_bid < 0 or call_ask <= 0 or call_ask < call_bid:
        return None, _decision("blocked", "invalid_vix_call_quote")
    call_mid = round(call_ask, 2)

    if call_mid > MAX_CALL_COST:
        return None, _decision("blocked", "vix_call_too_expensive",
                               cost=call_mid, max=MAX_CALL_COST)

    notional = _current_short_premium_notional()
    contracts = contracts_override or max(1, int(notional / HEDGE_NOTIONAL_PER_CONTRACT))
    total_cost = round(call_mid * 100 * contracts, 2)
    max_total_cost = round(PAPER_ACCOUNT_SIZE * MAX_HEDGE_COST_PCT, 2)
    if total_cost > max_total_cost:
        return None, _decision(
            "blocked", "vix_hedge_exceeds_portfolio_cost_budget",
            total_cost=total_cost, max_total_cost=max_total_cost,
            max_cost_pct=MAX_HEDGE_COST_PCT,
        )

    setup = HedgeSetup(
        shadow_id=f"vix-hedge-{today.isoformat()}-{uuid4().hex[:6]}",
        generated_at=_iso_utc(),
        status="open_shadow",
        vix_at_entry=round(vix, 2),
        vix3m_at_entry=round(vix3m, 2),
        target_strike=target_strike,
        actual_strike=actual_strike,
        expiry=expiry,
        dte=dte,
        call_mid=call_mid,
        contracts=contracts,
        total_cost=total_cost,
        notional_protected=round(notional, 2),
        roll_at_dte=ROLL_DTE,
    )
    logger.info(f"VIX hedge shadow: {contracts}x {actual_strike}C exp={expiry} "
                f"cost={call_mid} total=${total_cost} vix={vix:.1f}")
    return setup, _decision("eligible", "vix_hedge_gates_passed", setup=asdict(setup))


def check_hedge(setup: HedgeSetup) -> dict[str, Any]:
    if yf is None:
        return _decision("error", "yfinance_unavailable")
    today = date.today()
    dte_remaining = (date.fromisoformat(setup.expiry) - today).days

    if dte_remaining <= setup.roll_at_dte:
        return _decision("roll", f"dte_{dte_remaining}_at_roll_threshold_{setup.roll_at_dte}",
                         action="close_and_reopen_new_expiry")

    try:
        vix = float(yf.Ticker("^VIX").fast_info["lastPrice"])
    except Exception:
        return _decision("hold", "vix_fetch_failed_hold", dte=dte_remaining)

    # Spike check: if VIX approaches strike, hedge is paying off
    pct_of_strike = vix / setup.actual_strike
    if pct_of_strike >= 0.85:
        return _decision("evaluate_close", f"vix_{vix:.1f}_at_{pct_of_strike:.0%}_of_strike",
                         vix=vix, strike=setup.actual_strike,
                         note="VIX near strike — evaluate closing hedge for profit")

    chain = yf.Ticker("^VIX").option_chain(setup.expiry)
    calls = chain.calls[chain.calls["strike"] == setup.actual_strike]
    if calls.empty:
        return _decision("hold", f"dte={dte_remaining} vix={vix:.1f} strike_not_in_chain")
    current_mid = round(float(calls.iloc[0]["bid"]), 2)
    pnl = round((current_mid - setup.call_mid) * 100 * setup.contracts, 2)
    return _decision("hold", f"dte={dte_remaining} vix={vix:.1f} pnl=${pnl:+.0f}",
                     dte=dte_remaining, vix=vix, current_mid=current_mid, pnl=pnl)


def main() -> None:
    parser = argparse.ArgumentParser(description="VIX call hedge")
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--contracts", type=int)
    parser.add_argument("--state", type=Path, default=DEFAULT_STATE)
    parser.add_argument("--ledger", type=Path, default=DEFAULT_LEDGER)
    parser.add_argument("--out", type=Path, default=ROOT / "data" / "vix_call_hedge_decision.json")
    args = parser.parse_args()

    existing: HedgeSetup | None = None
    if args.state.exists():
        try:
            existing = HedgeSetup(**json.loads(args.state.read_text(encoding="utf-8")))
        except (OSError, json.JSONDecodeError, TypeError, ValueError) as exc:
            decision = _decision("blocked", "existing_hedge_state_unreadable", error=type(exc).__name__)
            args.out.parent.mkdir(parents=True, exist_ok=True)
            args.out.write_text(json.dumps(decision, indent=2) + "\n", encoding="utf-8")
            print(json.dumps(decision, indent=2))
            return

    if args.check and existing is None:
        decision = _decision("skipped", "no_open_vix_hedge_state")
        setup = None
    elif existing is not None and existing.status == "open_shadow":
        decision = check_hedge(existing)
        setup = None
        if decision["status"] == "roll":
            existing.status = "closed_shadow"
            args.state.write_text(json.dumps(asdict(existing), indent=2) + "\n", encoding="utf-8")
            args.ledger.parent.mkdir(parents=True, exist_ok=True)
            with args.ledger.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps({
                    "type": "close_shadow",
                    "shadow_id": existing.shadow_id,
                    "generated_at": decision["generated_at"],
                    "reason": decision["reason"],
                    "execution_enabled": False,
                    "can_submit_orders": False,
                }, separators=(",", ":"), sort_keys=True) + "\n")
    elif args.check:
        setup = None
        decision = _decision(
            "skipped", "no_open_vix_hedge_position",
            state_status=existing.status if existing is not None else "absent",
        )
    else:
        setup, decision = build_hedge(args.contracts)

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
        provider="vix_call_hedge",
        setup=asdict(setup or existing) if (setup or existing) is not None else None,
    )
    print(json.dumps(decision, indent=2))


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""SPY 21-30 DTE iron condor — shadow/paper only.

Sells one iron condor per week when IVP > 60. Collects premium on both
sides (put spread + call spread) when the market is expected to stay
within a range. Best in choppy/low-trend environments.

Gates (all must pass):
  - IVP > 60 (elevated premium on both sides — 56.8% WR documented at this threshold)
  - IVR > 30
  - VIX/VIX3M contango (< 1.05)
  - No major events within expiry window
  - DTE 21-30 (decay accelerating; gamma still manageable)

Structure:
  - Short put: 16-delta OTM put
  - Long put:  5 strikes lower
  - Short call: 16-delta OTM call
  - Long call:  5 strikes higher
  - Total credit = put spread credit + call spread credit

Close rules:
  - 50% of total credit collected OR 21 DTE — whichever first
  - If one wing breached: close entire condor, do not leg

No live orders. Shadow paper tracking only.
"""
from __future__ import annotations

import argparse
import json
import logging
import math
import os
import sys
from dataclasses import asdict, dataclass, field
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.options_evidence_factory import record_matched_setup
from scripts.options_observation_journal import append_observation
from scripts.liquidity_sweep_scanner import latest_research_context as liquidity_sweep_context

try:
    import yfinance as yf
except ImportError:
    yf = None  # type: ignore[assignment]

ET = ZoneInfo("America/New_York")
UTC = timezone.utc

LOG_DIR = Path.home() / ".vibe-trading" / "logs"
LOG_PATH = LOG_DIR / "spy-iron-condor.log"
DEFAULT_STATE = ROOT / "data" / "spy_iron_condor_state.json"
DEFAULT_LEDGER = ROOT / "data" / "spy_iron_condor_ledger.jsonl"

ENTRY_START_ET = time(9, 45)
ENTRY_END_ET = time(10, 30)

IVP_MIN = float(os.getenv("IC_IVP_MIN", "60.0"))
IVR_MIN = float(os.getenv("IC_IVR_MIN", "30.0"))
VIX_CONTANGO_MAX = float(os.getenv("IC_VIX_CONTANGO_MAX", "1.05"))
TARGET_DELTA = float(os.getenv("IC_TARGET_DELTA", "0.16"))
SPREAD_WIDTH = float(os.getenv("IC_SPREAD_WIDTH", "5.0"))
TARGET_DTE_MIN = int(os.getenv("IC_DTE_MIN", "21"))
TARGET_DTE_MAX = int(os.getenv("IC_DTE_MAX", "30"))
MIN_TOTAL_CREDIT = float(os.getenv("IC_MIN_TOTAL_CREDIT", "0.50"))
MIN_CREDIT_TO_WIDTH = float(os.getenv("IC_MIN_CREDIT_TO_WIDTH", "0.10"))  # per wing
PROFIT_CLOSE_PCT = float(os.getenv("IC_PROFIT_CLOSE_PCT", "0.50"))
CLOSE_AT_DTE = int(os.getenv("IC_CLOSE_DTE", "21"))

LOG_DIR.mkdir(parents=True, exist_ok=True)
logger = logging.getLogger("spy_iron_condor")
if not logger.handlers:
    logger.setLevel(logging.INFO)
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(message)s")
    h = logging.StreamHandler()
    h.setFormatter(fmt)
    logger.addHandler(h)
    if not os.getenv("PYTEST_CURRENT_TEST"):
        from logging.handlers import RotatingFileHandler
        fh = RotatingFileHandler(LOG_PATH, maxBytes=20 * 1024 * 1024, backupCount=3, encoding="utf-8")
        fh.setFormatter(fmt)
        logger.addHandler(fh)


@dataclass
class IronCondorSetup:
    shadow_id: str
    generated_at: str
    status: str
    symbol: str
    expiry: str
    dte: int
    short_put_symbol: str
    long_put_symbol: str
    short_call_symbol: str
    long_call_symbol: str
    short_put: float
    long_put: float
    short_call: float
    long_call: float
    put_delta: float
    call_delta: float
    put_credit: float
    call_credit: float
    total_credit: float
    midpoint_credit: float
    short_put_bid: float
    short_put_ask: float
    long_put_bid: float
    long_put_ask: float
    short_call_bid: float
    short_call_ask: float
    long_call_bid: float
    long_call_ask: float
    quote_captured_at: str
    max_loss_put_wing: float
    max_loss_call_wing: float
    max_loss_total: float
    profit_target: float
    close_at_dte: int
    vix_at_entry: float
    vix3m_at_entry: float
    ivr_at_entry: float | None
    ivp_at_entry: float | None
    gates_passed: dict[str, bool]
    liquidity_sweep_context: dict[str, Any] = field(default_factory=dict)
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
        "provider": "spy_iron_condor",
        "mode": "shadow_paper_only",
        "generated_at": _iso_utc(),
        "status": status,
        "reason": reason,
        "details": details,
        "execution_enabled": False,
        "can_submit_orders": False,
        "orders_submitted": 0,
    }


def _get_vix() -> tuple[float, float]:
    if yf is None:
        raise RuntimeError("yfinance not installed")
    vix = float(yf.Ticker("^VIX").fast_info["lastPrice"])
    try:
        vix3m = float(yf.Ticker("^VIX3M").fast_info["lastPrice"])
    except Exception:
        vix3m = vix * 1.05
    return vix, vix3m


def _get_ivr_ivp(symbol: str) -> tuple[float | None, float | None]:
    try:
        from scripts.options_confluence import latest_iv_rank_context
        ctx = latest_iv_rank_context(symbol, as_of=date.today())
        return ctx.get("ivr"), ctx.get("ivp")
    except Exception:
        return None, None


def _bs_delta(spot: float, strike: float, sigma: float, T: float, right: str) -> float:
    if T <= 0 or sigma <= 0:
        return 0.0
    d1 = (math.log(spot / strike) + 0.5 * sigma ** 2 * T) / (sigma * math.sqrt(T))
    normal_cdf = 0.5 * math.erfc(-d1 / math.sqrt(2))
    return (normal_cdf - 1.0) if right == "put" else normal_cdf  # put: negative, call: positive


def _find_expiry(symbol: str) -> str | None:
    if yf is None:
        return None
    today = date.today()
    for exp_str in yf.Ticker(symbol).options:
        dte = (date.fromisoformat(exp_str) - today).days
        if TARGET_DTE_MIN <= dte <= TARGET_DTE_MAX:
            return exp_str
    return None


def _find_wing(puts_or_calls: Any, spot: float, sigma: float, T: float, right: str) -> tuple[float, float] | None:
    df = puts_or_calls.copy()
    if right == "put":
        df = df[df["strike"] < spot]
    else:
        df = df[df["strike"] > spot]
    if df.empty:
        return None
    if "delta" in df.columns:
        df["abs_delta"] = df["delta"].abs()
    else:
        df["abs_delta"] = df["strike"].apply(
            lambda K: abs(_bs_delta(spot, K, sigma, T, right))
        )
    idx = (df["abs_delta"] - TARGET_DELTA).abs().idxmin()
    row = df.loc[idx]
    return float(row["strike"]), float(row["abs_delta"])


def select_priceable_wing(
    chain_df: Any,
    *,
    spot: float,
    sigma: float,
    T: float,
    right: str,
) -> tuple[dict[str, Any] | None, dict[str, Any]]:
    """Select the nearest target-delta wing executable on one chain snapshot."""
    required = {"strike", "bid", "ask"}
    if not required.issubset(set(getattr(chain_df, "columns", []))):
        return None, {"reason": "chain_columns_missing", "candidate_count": 0}
    df = chain_df.copy()
    df = df[df["strike"] < spot] if right == "put" else df[df["strike"] > spot]
    if df.empty:
        return None, {"reason": f"no_otm_{right}s", "candidate_count": 0}
    if "delta" in df.columns:
        df["abs_delta"] = df["delta"].abs()
    else:
        df["abs_delta"] = df["strike"].apply(
            lambda strike: abs(_bs_delta(spot, strike, sigma, T, right))
        )
    candidates = df[df["abs_delta"].between(0.10, 0.22)].copy()
    if candidates.empty:
        candidates = df.copy()
    candidates["delta_distance"] = (candidates["abs_delta"] - TARGET_DELTA).abs()
    candidates = candidates.sort_values(
        ["delta_distance", "strike"], ascending=[True, right == "call"]
    )
    missing_long = 0
    unpriceable = 0
    for _, row in candidates.iterrows():
        short_strike = float(row["strike"])
        direction = -1.0 if right == "put" else 1.0
        long_strike = round(short_strike + direction * SPREAD_WIDTH, 3)
        if chain_df[chain_df["strike"] == long_strike].empty:
            missing_long += 1
            continue
        market = spread_market_from_chain(chain_df, short_strike, long_strike)
        if market is None:
            unpriceable += 1
            continue
        return {
            "short_strike": short_strike,
            "long_strike": long_strike,
            "short_delta": float(row["abs_delta"]),
            "market": market,
        }, {
            "reason": "priceable_candidate_found",
            "candidate_count": int(len(candidates)),
            "missing_long_count": missing_long,
            "unpriceable_count": unpriceable,
        }
    return None, {
        "reason": "no_priceable_candidate",
        "candidate_count": int(len(candidates)),
        "missing_long_count": missing_long,
        "unpriceable_count": unpriceable,
    }


def spread_market_from_chain(chain_df: Any, short_strike: float, long_strike: float) -> dict[str, Any] | None:
    required = {"strike", "bid", "ask"}
    if not required.issubset(set(getattr(chain_df, "columns", []))):
        return None
    s = chain_df[chain_df["strike"] == short_strike]
    l = chain_df[chain_df["strike"] == long_strike]
    if s.empty or l.empty:
        return None
    short = s.iloc[0]
    long = l.iloc[0]
    short_bid = float(short["bid"])
    short_ask = float(short["ask"])
    long_bid = float(long["bid"])
    long_ask = float(long["ask"])
    quotes = (short_bid, short_ask, long_bid, long_ask)
    if (
        not all(math.isfinite(value) for value in quotes)
        or min(quotes) < 0
        or short_ask < short_bid
        or long_ask < long_bid
    ):
        return None
    midpoint_credit = ((short_bid + short_ask) - (long_bid + long_ask)) / 2.0
    entry_credit = short_bid - long_ask
    if entry_credit <= 0:
        return None
    return {
        "short_symbol": str(short.get("contractSymbol") or ""),
        "long_symbol": str(long.get("contractSymbol") or ""),
        "short_bid": round(short_bid, 4),
        "short_ask": round(short_ask, 4),
        "long_bid": round(long_bid, 4),
        "long_ask": round(long_ask, 4),
        "midpoint_credit": round(midpoint_credit, 4),
        "executable_entry_credit": round(entry_credit, 4),
        "executable_close_debit": round(max(0.0, short_ask - long_bid), 4),
        "captured_at": _iso_utc(),
    }


def combined_max_loss(width: float, total_credit: float) -> float:
    """Only one equal-width wing can be fully breached at expiration."""
    return round(max(0.0, width - total_credit), 4)


def build_setup(
    symbol: str = "SPY", *, observe_blocked: bool = False
) -> tuple[IronCondorSetup | None, dict[str, Any]]:
    now = _now_et()
    current_time = now.time().replace(tzinfo=None)
    if not (ENTRY_START_ET <= current_time <= ENTRY_END_ET):
        return None, _decision("blocked", "outside_entry_window_0945_1030_et",
                               now_et=now.strftime("%H:%M"))

    try:
        vix, vix3m = _get_vix()
    except Exception as exc:
        return None, _decision("blocked", "vix_fetch_failed", error=str(exc))

    gates: dict[str, bool] = {}
    production_blockers: list[str] = []
    ratio = vix / vix3m if vix3m > 0 else 99.0
    gates["contango"] = ratio < VIX_CONTANGO_MAX
    if not gates["contango"]:
        production_blockers.append("vix_backwardation")
        if not observe_blocked:
            return None, _decision("blocked", "vix_backwardation", ratio=round(ratio, 3))

    ivr, ivp = _get_ivr_ivp(symbol)
    gates["ivr_above_min"] = ivr is not None and float(ivr) >= IVR_MIN
    gates["ivp_above_min"] = ivp is not None and float(ivp) >= IVP_MIN
    if not gates["ivr_above_min"]:
        production_blockers.append("ivr_below_threshold")
        if not observe_blocked:
            return None, _decision("blocked", "ivr_below_threshold", ivr=ivr, ivr_min=IVR_MIN)
    if not gates["ivp_above_min"]:
        production_blockers.append("ivp_below_threshold_60")
        if not observe_blocked:
            return None, _decision("blocked", "ivp_below_threshold_60", ivp=ivp, ivp_min=IVP_MIN)

    expiry = _find_expiry(symbol)
    if expiry is None:
        return None, _decision("blocked", "no_expiry_in_21_30_dte_window")

    # A candle reclaim cannot prove stop orders or institutional intent. Record
    # the point-in-time proxy for cohort analysis, but do not let it veto trades.
    sweep_context = liquidity_sweep_context(symbol, as_of=now)

    today = date.today()
    dte = (date.fromisoformat(expiry) - today).days
    T = dte / 252
    sigma = vix / 100

    try:
        ticker = yf.Ticker(symbol)
        spot = float(ticker.fast_info["lastPrice"])
        chain = ticker.option_chain(expiry)
    except Exception as exc:
        return None, _decision("blocked", "option_chain_fetch_failed", error=type(exc).__name__)

    put_wing, put_selection = select_priceable_wing(
        chain.puts, spot=spot, sigma=sigma, T=T, right="put"
    )
    call_wing, call_selection = select_priceable_wing(
        chain.calls, spot=spot, sigma=sigma, T=T, right="call"
    )
    if put_wing is None or call_wing is None:
        return None, _decision(
            "blocked", "spread_not_priceable",
            put_selection=put_selection, call_selection=call_selection,
            liquidity_sweep_context=sweep_context,
        )

    short_put = float(put_wing["short_strike"])
    long_put = float(put_wing["long_strike"])
    put_delta = float(put_wing["short_delta"])
    put_market = put_wing["market"]
    short_call = float(call_wing["short_strike"])
    long_call = float(call_wing["long_strike"])
    call_delta = float(call_wing["short_delta"])
    call_market = call_wing["market"]
    if not all((
        put_market["short_symbol"], put_market["long_symbol"],
        call_market["short_symbol"], call_market["long_symbol"],
    )):
        return None, _decision("blocked", "contract_symbols_unavailable")

    put_credit = float(put_market["executable_entry_credit"])
    call_credit = float(call_market["executable_entry_credit"])

    total_credit = round(put_credit + call_credit, 2)
    gates["min_total_credit"] = total_credit >= MIN_TOTAL_CREDIT
    gates["put_ctw"] = put_credit / SPREAD_WIDTH >= MIN_CREDIT_TO_WIDTH
    gates["call_ctw"] = call_credit / SPREAD_WIDTH >= MIN_CREDIT_TO_WIDTH
    if not gates["min_total_credit"]:
        production_blockers.append("total_credit_below_floor")
    if not gates["put_ctw"]:
        production_blockers.append("put_credit_to_width_below_floor")
    if not gates["call_ctw"]:
        production_blockers.append("call_credit_to_width_below_floor")
    if production_blockers and not observe_blocked:
        return None, _decision(
            "blocked", production_blockers[0], gates=gates,
            blockers=production_blockers, put_credit=put_credit,
            call_credit=call_credit, total=total_credit,
        )

    profit_target = round(total_credit * PROFIT_CLOSE_PCT, 2)
    max_loss_put = combined_max_loss(SPREAD_WIDTH, total_credit)
    max_loss_call = combined_max_loss(SPREAD_WIDTH, total_credit)

    setup = IronCondorSetup(
        shadow_id=f"ic-{now.date().isoformat()}-{uuid4().hex[:8]}",
        generated_at=_iso_utc(),
        status="counterfactual_shadow" if production_blockers else "open_shadow",
        symbol=symbol,
        expiry=expiry,
        dte=dte,
        short_put_symbol=put_market["short_symbol"],
        long_put_symbol=put_market["long_symbol"],
        short_call_symbol=call_market["short_symbol"],
        long_call_symbol=call_market["long_symbol"],
        short_put=short_put,
        long_put=long_put,
        short_call=short_call,
        long_call=long_call,
        put_delta=round(put_delta, 4),
        call_delta=round(call_delta, 4),
        put_credit=put_credit,
        call_credit=call_credit,
        total_credit=total_credit,
        midpoint_credit=round(float(put_market["midpoint_credit"]) + float(call_market["midpoint_credit"]), 4),
        short_put_bid=float(put_market["short_bid"]),
        short_put_ask=float(put_market["short_ask"]),
        long_put_bid=float(put_market["long_bid"]),
        long_put_ask=float(put_market["long_ask"]),
        short_call_bid=float(call_market["short_bid"]),
        short_call_ask=float(call_market["short_ask"]),
        long_call_bid=float(call_market["long_bid"]),
        long_call_ask=float(call_market["long_ask"]),
        quote_captured_at=str(put_market["captured_at"]),
        max_loss_put_wing=max_loss_put,
        max_loss_call_wing=max_loss_call,
        max_loss_total=combined_max_loss(SPREAD_WIDTH, total_credit),
        profit_target=profit_target,
        close_at_dte=CLOSE_AT_DTE,
        vix_at_entry=round(vix, 2),
        vix3m_at_entry=round(vix3m, 2),
        ivr_at_entry=float(ivr) if ivr is not None else None,
        ivp_at_entry=float(ivp) if ivp is not None else None,
        gates_passed=gates,
        liquidity_sweep_context=sweep_context,
    )
    if production_blockers:
        return setup, _decision(
            "blocked", "counterfactual_setup_recorded",
            blockers=production_blockers, gates=gates, setup=asdict(setup),
        )
    return setup, _decision("eligible", "all_iron_condor_gates_passed", setup=asdict(setup))


def check_position(setup: IronCondorSetup, *, now_et: datetime | None = None) -> dict[str, Any]:
    if yf is None:
        return _decision("error", "yfinance_unavailable")

    today = (now_et or _now_et()).date()
    dte_remaining = (date.fromisoformat(setup.expiry) - today).days
    try:
        chain = yf.Ticker(setup.symbol).option_chain(setup.expiry)
    except Exception as exc:
        return _decision(
            "blocked",
            "monitor_spread_quote_fetch_failed",
            error=type(exc).__name__,
            dte_remaining=dte_remaining,
        )
    put_market = spread_market_from_chain(chain.puts, setup.short_put, setup.long_put)
    call_market = spread_market_from_chain(chain.calls, setup.short_call, setup.long_call)

    if put_market is None or call_market is None:
        return _decision("blocked", "monitor_spread_quote_unavailable", dte_remaining=dte_remaining)

    put_cost = float(put_market["executable_close_debit"])
    call_cost = float(call_market["executable_close_debit"])
    current_debit = round(put_cost + call_cost, 4)
    pnl = round(setup.total_credit - current_debit, 2)
    pnl_pct = pnl / setup.total_credit if setup.total_credit > 0 else 0.0

    if dte_remaining <= setup.close_at_dte:
        return _decision("close_dte", f"dte_{dte_remaining}_reached_close_threshold_{setup.close_at_dte}",
                         pnl=pnl, pnl_pct=round(pnl_pct, 4),
                         current_debit=current_debit, dte_remaining=dte_remaining,
                         put_cost=put_cost, call_cost=call_cost)

    if pnl >= setup.profit_target:
        return _decision("close_profit", f"target_hit_{pnl_pct:.0%}",
                         pnl=pnl, pnl_pct=round(pnl_pct, 4),
                         current_debit=current_debit, dte_remaining=dte_remaining)

    return _decision("hold", f"pnl={pnl:+.2f}_({pnl_pct:+.0%})",
                     pnl=pnl, pnl_pct=round(pnl_pct, 4),
                     current_debit=current_debit, dte_remaining=dte_remaining,
                     put_cost=put_cost, call_cost=call_cost)


def record_evidence(setup: IronCondorSetup) -> dict[str, Any]:
    try:
        decision_at = datetime.fromisoformat(setup.generated_at.replace("Z", "+00:00"))
        close_date = date.fromisoformat(setup.expiry) - timedelta(days=setup.close_at_dte)
        evaluation_end = datetime.combine(close_date, time(15, 45), tzinfo=ET).astimezone(UTC)
        snapshots = [
            {"symbol": setup.long_put_symbol, "expiry": setup.expiry, "strike": setup.long_put, "right": "P", "bid": setup.long_put_bid, "ask": setup.long_put_ask},
            {"symbol": setup.short_put_symbol, "expiry": setup.expiry, "strike": setup.short_put, "right": "P", "delta": -abs(setup.put_delta), "bid": setup.short_put_bid, "ask": setup.short_put_ask},
            {"symbol": setup.short_call_symbol, "expiry": setup.expiry, "strike": setup.short_call, "right": "C", "delta": abs(setup.call_delta), "bid": setup.short_call_bid, "ask": setup.short_call_ask},
            {"symbol": setup.long_call_symbol, "expiry": setup.expiry, "strike": setup.long_call, "right": "C", "bid": setup.long_call_bid, "ask": setup.long_call_ask},
        ]
        for snapshot in snapshots:
            snapshot.update({
                "captured_at": setup.quote_captured_at,
                "quote_provider": "yfinance_chain_snapshot",
                "quote_scope": "public_snapshot_not_opra_nbbo",
            })
        trade_meta = {
            "strategy": "iron_condor",
            "underlying": setup.symbol,
            "expiry": setup.expiry,
            "qty": 1,
            "net_credit": setup.midpoint_credit,
            "max_risk_per_contract": setup.max_loss_total * 100.0,
            "profit_close_pct": PROFIT_CLOSE_PCT,
            "stop_policy": "none_time_exit_only",
            "evaluation_end_at": evaluation_end.isoformat(),
            "vix_at_entry": setup.vix_at_entry,
            "vix_term_ratio": setup.vix_at_entry / setup.vix3m_at_entry if setup.vix3m_at_entry > 0 else None,
            "iv_rank_at_entry": setup.ivr_at_entry,
            "leg_market_snapshots": snapshots,
        }
        return record_matched_setup(
            {
                "source_strategy": "vrp_defined_risk",
                "underlying": setup.symbol,
                "decision_at": decision_at.isoformat(),
                "gate_states": setup.gates_passed,
                "regime_context": {
                    "vix": setup.vix_at_entry,
                    "vix3m": setup.vix3m_at_entry,
                    "liquidity_sweep": setup.liquidity_sweep_context,
                },
            },
            trade_meta,
            [
                {"symbol": setup.long_put_symbol, "side": "buy", "ratio_qty": 1},
                {"symbol": setup.short_put_symbol, "side": "sell", "ratio_qty": 1},
                {"symbol": setup.short_call_symbol, "side": "sell", "ratio_qty": 1},
                {"symbol": setup.long_call_symbol, "side": "buy", "ratio_qty": 1},
            ],
            effective_qty=1,
            now=decision_at,
        )
    except Exception as exc:
        logger.warning(f"Iron-condor evidence capture failed: {exc}")
        return {"status": "capture_failed", "error": type(exc).__name__, "execution_enabled": False}


def _number_or_none(value: Any) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if math.isfinite(parsed) else None


def record_run_observation(result: dict[str, Any], setup: IronCondorSetup | None = None) -> dict[str, Any]:
    try:
        return append_observation(
            result,
            provider="spy_iron_condor",
            setup=asdict(setup) if setup is not None else None,
        )
    except Exception as exc:
        logger.warning(f"Iron-condor observation capture failed: {type(exc).__name__}")
        return {"status": "capture_failed", "execution_enabled": False}


def setup_from_state(state: dict[str, Any]) -> tuple[IronCondorSetup | None, dict[str, Any] | None]:
    required = {
        name for name, field in IronCondorSetup.__dataclass_fields__.items()
        if field.default is field.default_factory
    }
    missing = sorted(required - set(state))
    if missing:
        return None, _decision(
            "blocked",
            "legacy_state_missing_execution_fields",
            missing_fields=missing,
        )
    try:
        setup = IronCondorSetup(**{
            key: value for key, value in state.items()
            if key in IronCondorSetup.__dataclass_fields__
        })
    except (TypeError, ValueError) as exc:
        return None, _decision("blocked", "invalid_shadow_state", error=type(exc).__name__)
    return setup, None


def apply_monitor_decision(
    state: dict[str, Any],
    decision: dict[str, Any],
    *,
    state_path: Path,
    ledger_path: Path,
) -> dict[str, Any]:
    details = decision.get("details") if isinstance(decision.get("details"), dict) else {}
    status = str(decision.get("status") or "")
    mark = {
        "type": "mark_shadow",
        "shadow_id": state.get("shadow_id"),
        "as_of": decision.get("generated_at"),
        "status": status,
        "reason": decision.get("reason"),
        "current_debit": details.get("current_debit"),
        "pnl": details.get("pnl"),
        "pnl_pct": details.get("pnl_pct"),
        "dte_remaining": details.get("dte_remaining"),
        "put_cost": details.get("put_cost"),
        "call_cost": details.get("call_cost"),
        "execution_enabled": False,
        "can_submit_orders": False,
    }
    if status.startswith("close_") and _number_or_none(details.get("current_debit")) is not None:
        state.update({
            "status": "closed_shadow",
            "closed_at": decision.get("generated_at"),
            "close_reason": decision.get("reason"),
            "closing_debit": details.get("current_debit"),
            "realized_shadow_pnl": details.get("pnl"),
        })
        mark["type"] = "close_shadow"
    state["last_monitor_decision"] = mark
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state_path.write_text(json.dumps(state, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    ledger_path.parent.mkdir(parents=True, exist_ok=True)
    with ledger_path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(mark, sort_keys=True, separators=(",", ":")) + "\n")
    return state


def main() -> None:
    parser = argparse.ArgumentParser(description="SPY 21-30 DTE iron condor")
    parser.add_argument("--check", action="store_true")
    parser.add_argument(
        "--observe-only",
        action="store_true",
        help="Record a counterfactual candidate without creating open shadow state",
    )
    parser.add_argument("--state", type=Path, default=DEFAULT_STATE)
    parser.add_argument("--ledger", type=Path, default=DEFAULT_LEDGER)
    parser.add_argument("--out", type=Path, default=ROOT / "data" / "spy_iron_condor_decision.json")
    args = parser.parse_args()

    if args.check:
        if not args.state.exists():
            result = _decision("skipped", "no_shadow_state_file")
            args.out.parent.mkdir(parents=True, exist_ok=True)
            args.out.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
            record_run_observation(result)
            print(json.dumps(result, indent=2))
            return
        try:
            saved = json.loads(args.state.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            result = _decision("blocked", "shadow_state_unreadable", error=type(exc).__name__)
            args.out.parent.mkdir(parents=True, exist_ok=True)
            args.out.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
            record_run_observation(result)
            print(json.dumps(result, indent=2))
            return
        if saved.get("status") != "open_shadow":
            result = _decision("skipped", "no_open_shadow_position", state_status=saved.get("status"))
        else:
            setup, state_error = setup_from_state(saved)
            result = state_error or check_position(setup)  # type: ignore[arg-type]
            if setup is not None:
                apply_monitor_decision(saved, result, state_path=args.state, ledger_path=args.ledger)
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
        record_run_observation(result, setup if saved.get("status") == "open_shadow" else None)
        print(json.dumps(result, indent=2))
        return

    setup, decision = build_setup(observe_blocked=True)
    observed_setup = setup
    production_eligible = decision.get("status") == "eligible"
    if args.observe_only and setup is not None:
        setup.status = "counterfactual_shadow"
        if production_eligible:
            decision = _decision(
                "blocked",
                "counterfactual_observation_only",
                original_reason="all_iron_condor_gates_passed",
                setup=asdict(setup),
            )
        production_eligible = False
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(decision, indent=2) + "\n", encoding="utf-8")

    existing = {}
    if args.state.exists():
        try:
            existing = json.loads(args.state.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            existing = {"status": "unreadable"}
    if production_eligible and setup is not None and existing.get("status") == "open_shadow":
        decision = _decision("blocked", "open_shadow_position_already_exists",
                             shadow_id=existing.get("shadow_id"))
        args.out.write_text(json.dumps(decision, indent=2) + "\n", encoding="utf-8")
        setup = None
    elif production_eligible and setup is not None and existing.get("status") == "unreadable":
        decision = _decision("blocked", "existing_shadow_state_unreadable")
        args.out.write_text(json.dumps(decision, indent=2) + "\n", encoding="utf-8")
        setup = None

    if setup is not None:
        record_evidence(setup)
    if production_eligible and setup is not None:
        args.state.parent.mkdir(parents=True, exist_ok=True)
        args.ledger.parent.mkdir(parents=True, exist_ok=True)
        args.state.write_text(json.dumps(asdict(setup), indent=2) + "\n", encoding="utf-8")
        with args.ledger.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(asdict(setup), separators=(",", ":"), sort_keys=True) + "\n")
        logger.info(
            f"IC shadow entry: {setup.short_put}P/{setup.short_call}C {setup.expiry} "
            f"credit={setup.total_credit} dte={setup.dte} ivp={setup.ivp_at_entry}"
        )
    else:
        logger.info(f"IC shadow blocked: {decision['reason']}")

    record_run_observation(decision, observed_setup)
    print(json.dumps(decision, indent=2))


if __name__ == "__main__":
    main()

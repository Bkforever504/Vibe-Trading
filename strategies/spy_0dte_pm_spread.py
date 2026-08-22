#!/usr/bin/env python3
"""SPY 0DTE afternoon put credit spread — shadow/paper only.

Entry window: 12:00-14:00 ET. Research: theta/gamma ratio peaks in
afternoon vs open where gamma wipes collected premium on any 1-sigma move.

Gates (all must pass):
  - Time: 12:00-14:00 ET weekdays
  - VIX < 20, VIX/VIX3M contango (< 1.05)
  - IVR > 30 (selling into elevated premium only)
  - SPY above its 20-day SMA (sell puts only in uptrend)
  - Credit-to-width >= 15% (minimum reward for 0DTE gamma risk)

Close rules:
  - 50% of credit OR hard close at 15:45 ET
  - Never hold through close — 0DTE gamma at expiry is unlimited for spreads

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
from datetime import date, datetime, time, timezone
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
from scripts.vwap_context import vwap_context
from scripts.iv_term_structure import iv_term_structure_context

try:
    import yfinance as yf
except ImportError:
    yf = None  # type: ignore[assignment]

ET = ZoneInfo("America/New_York")
UTC = timezone.utc

LOG_DIR = Path.home() / ".vibe-trading" / "logs"
LOG_PATH = LOG_DIR / "spy-0dte-pm-spread.log"
DEFAULT_STATE = ROOT / "data" / "spy_0dte_pm_state.json"
DEFAULT_LEDGER = ROOT / "data" / "spy_0dte_pm_ledger.jsonl"

ENTRY_START_ET = time(12, 0)
ENTRY_END_ET = time(14, 0)
HARD_CLOSE_ET = time(15, 45)

VIX_MAX = float(os.getenv("PM0DTE_VIX_MAX", "20.0"))
VIX_CONTANGO_MAX = float(os.getenv("PM0DTE_VIX_CONTANGO_MAX", "1.05"))
IVR_MIN = float(os.getenv("PM0DTE_IVR_MIN", "30.0"))
TARGET_DELTA = float(os.getenv("PM0DTE_TARGET_DELTA", "0.16"))
SPREAD_WIDTH = float(os.getenv("PM0DTE_SPREAD_WIDTH", "5.0"))
MIN_CREDIT_TO_WIDTH = float(os.getenv("PM0DTE_MIN_CREDIT_TO_WIDTH", "0.15"))
PROFIT_CLOSE_PCT = float(os.getenv("PM0DTE_PROFIT_CLOSE_PCT", "0.50"))
SMA_PERIOD = int(os.getenv("PM0DTE_SMA_PERIOD", "20"))

LOG_DIR.mkdir(parents=True, exist_ok=True)
logger = logging.getLogger("spy_0dte_pm_spread")
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
class PMSpreadSetup:
    shadow_id: str
    generated_at: str
    status: str
    symbol: str
    expiry: str
    short_symbol: str
    long_symbol: str
    short_strike: float
    long_strike: float
    short_delta: float
    entry_credit: float
    midpoint_credit: float
    short_bid: float
    short_ask: float
    long_bid: float
    long_ask: float
    quote_captured_at: str
    max_loss: float
    credit_to_width: float
    profit_target: float
    hard_close_et: str
    vix_at_entry: float
    spy_vs_sma: dict[str, float]
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
        "provider": "spy_0dte_pm_spread",
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


def _spy_vs_sma(period: int = SMA_PERIOD) -> dict[str, float]:
    if yf is None:
        return {"spot": 0.0, "sma": 0.0, "above_sma": False}
    hist = yf.Ticker("SPY").history(period=f"{period + 5}d")
    if hist.empty or len(hist) < period:
        return {"spot": 0.0, "sma": 0.0, "above_sma": False}
    spot = float(hist["Close"].iloc[-1])
    sma = float(hist["Close"].tail(period).mean())
    return {"spot": round(spot, 2), "sma": round(sma, 2), "above_sma": spot > sma}


def _bs_put_delta(spot: float, strike: float, sigma: float, T: float) -> float:
    if T <= 0 or sigma <= 0:
        return 0.0
    d1 = (math.log(spot / strike) + 0.5 * sigma ** 2 * T) / (sigma * math.sqrt(T))
    return 0.5 * math.erfc(d1 / math.sqrt(2))


def _find_today_expiry() -> str | None:
    if yf is None:
        return None
    today = date.today().isoformat()
    opts = yf.Ticker("SPY").options
    return today if today in opts else None


def select_priceable_put_spread(
    puts: Any,
    *,
    expiry: str,
    spot: float,
    vix: float,
) -> tuple[dict[str, Any] | None, dict[str, Any]]:
    required = {"strike", "bid", "ask"}
    if not required.issubset(set(getattr(puts, "columns", []))):
        return None, {"reason": "chain_columns_missing", "candidate_count": 0}
    T = max((date.fromisoformat(expiry) - date.today()).days / 252, 1 / 252)
    sigma = vix / 100
    otm = puts[puts["strike"] < spot].copy()
    if otm.empty:
        return None, {"reason": "no_otm_puts", "candidate_count": 0}
    if "delta" in otm.columns:
        otm["abs_delta"] = otm["delta"].abs()
    else:
        otm["abs_delta"] = otm["strike"].apply(lambda K: _bs_put_delta(spot, K, sigma, T))
    candidates = otm[otm["abs_delta"].between(0.10, 0.22)].copy()
    if candidates.empty:
        candidates = otm.copy()
    candidates["delta_distance"] = (candidates["abs_delta"] - TARGET_DELTA).abs()
    candidates = candidates.sort_values(["delta_distance", "strike"], ascending=[True, False])
    missing_long = 0
    unpriceable = 0
    for _, row in candidates.iterrows():
        short_strike = float(row["strike"])
        long_strike = round(short_strike - SPREAD_WIDTH, 3)
        if puts[puts["strike"] == long_strike].empty:
            missing_long += 1
            continue
        market = spread_market_from_chain(puts, short_strike, long_strike)
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


def spread_market_from_chain(puts: Any, short_strike: float, long_strike: float) -> dict[str, Any] | None:
    required = {"strike", "bid", "ask"}
    if not required.issubset(set(getattr(puts, "columns", []))):
        return None
    s_row = puts[puts["strike"] == short_strike]
    l_row = puts[puts["strike"] == long_strike]
    if s_row.empty or l_row.empty:
        return None
    short = s_row.iloc[0]
    long = l_row.iloc[0]
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
    executable_entry_credit = short_bid - long_ask
    executable_close_debit = max(0.0, short_ask - long_bid)
    if executable_entry_credit <= 0:
        return None
    return {
        "short_symbol": str(short.get("contractSymbol") or ""),
        "long_symbol": str(long.get("contractSymbol") or ""),
        "short_bid": round(short_bid, 4),
        "short_ask": round(short_ask, 4),
        "long_bid": round(long_bid, 4),
        "long_ask": round(long_ask, 4),
        "midpoint_credit": round(midpoint_credit, 4),
        "executable_entry_credit": round(executable_entry_credit, 4),
        "executable_close_debit": round(executable_close_debit, 4),
        "captured_at": _iso_utc(),
    }


def _spread_market(expiry: str, short_strike: float, long_strike: float) -> dict[str, Any] | None:
    puts = yf.Ticker("SPY").option_chain(expiry).puts
    return spread_market_from_chain(puts, short_strike, long_strike)


def build_setup(symbol: str = "SPY", *, observe_blocked: bool = False) -> tuple[PMSpreadSetup | None, dict[str, Any]]:
    now = _now_et()
    current_time = now.time().replace(tzinfo=None)

    if not (ENTRY_START_ET <= current_time <= ENTRY_END_ET):
        return None, _decision("blocked", "outside_entry_window_1200_1400_et",
                               window_start="12:00", window_end="14:00", now_et=now.strftime("%H:%M"))

    try:
        vix, vix3m = _get_vix()
    except Exception as exc:
        return None, _decision("blocked", "vix_fetch_failed", error=str(exc))

    gates: dict[str, bool] = {}
    production_blockers: list[str] = []
    gates["vix_below_max"] = vix < VIX_MAX
    gates["contango"] = vix / vix3m < VIX_CONTANGO_MAX if vix3m > 0 else False

    if not gates["vix_below_max"]:
        production_blockers.append("vix_too_high")
    if not gates["contango"]:
        production_blockers.append("vix_backwardation")
    if production_blockers and not observe_blocked:
        return None, _decision("blocked", production_blockers[0], gates=gates, blockers=production_blockers)

    spy_sma = _spy_vs_sma()
    gates["spy_above_sma"] = spy_sma["above_sma"]
    if not gates["spy_above_sma"]:
        production_blockers.append("spy_below_sma_no_put_selling")
        if not observe_blocked:
            return None, _decision("blocked", "spy_below_sma_no_put_selling",
                                   spot=spy_sma["spot"], sma=spy_sma["sma"])

    expiry = _find_today_expiry()
    if expiry is None:
        return None, _decision("blocked", "no_0dte_expiry_available")

    spot = spy_sma["spot"]
    try:
        puts = yf.Ticker(symbol).option_chain(expiry).puts
    except Exception as exc:
        return None, _decision("blocked", "option_chain_fetch_failed", error=type(exc).__name__)
    selected, selection_diagnostics = select_priceable_put_spread(
        puts, expiry=expiry, spot=spot, vix=vix
    )
    if selected is None:
        return None, _decision("blocked", "spread_not_priceable", selection=selection_diagnostics)
    short_strike = float(selected["short_strike"])
    long_strike = float(selected["long_strike"])
    short_delta = float(selected["short_delta"])
    market = selected["market"]
    if not market["short_symbol"] or not market["long_symbol"]:
        return None, _decision("blocked", "contract_symbols_unavailable", selection=selection_diagnostics)

    entry_credit = float(market["executable_entry_credit"])
    gates["credit_positive"] = entry_credit > 0.02
    if not gates["credit_positive"]:
        production_blockers.append("credit_too_thin")

    ctw = entry_credit / SPREAD_WIDTH
    gates["credit_to_width"] = ctw >= MIN_CREDIT_TO_WIDTH
    if not gates["credit_to_width"]:
        production_blockers.append("credit_to_width_below_floor")
    if production_blockers and not observe_blocked:
        return None, _decision("blocked", production_blockers[0], gates=gates,
                               blockers=production_blockers, selection=selection_diagnostics)

    # Soft-gate annotations — observed but not blocking (30-day shadow period)
    vwap_ctx = vwap_context()
    iv_slope_ctx = iv_term_structure_context()
    sweep_ctx = liquidity_sweep_context(symbol, as_of=now)
    gates["vwap_near_fair_value"] = bool(vwap_ctx.get("ok_to_sell"))
    gates["iv_0dte_elevated"] = bool(iv_slope_ctx.get("ok_to_sell"))

    profit_target = round(entry_credit * PROFIT_CLOSE_PCT, 2)
    setup = PMSpreadSetup(
        shadow_id=f"0dte-pm-{now.date().isoformat()}-{uuid4().hex[:8]}",
        generated_at=_iso_utc(),
        status="counterfactual_shadow" if production_blockers else "open_shadow",
        symbol=symbol,
        expiry=expiry,
        short_symbol=market["short_symbol"],
        long_symbol=market["long_symbol"],
        short_strike=short_strike,
        long_strike=long_strike,
        short_delta=round(short_delta, 4),
        entry_credit=entry_credit,
        midpoint_credit=float(market["midpoint_credit"]),
        short_bid=float(market["short_bid"]),
        short_ask=float(market["short_ask"]),
        long_bid=float(market["long_bid"]),
        long_ask=float(market["long_ask"]),
        quote_captured_at=str(market["captured_at"]),
        max_loss=round(SPREAD_WIDTH - entry_credit, 2),
        credit_to_width=round(ctw, 4),
        profit_target=profit_target,
        hard_close_et=HARD_CLOSE_ET.strftime("%H:%M") + " ET",
        vix_at_entry=round(vix, 2),
        spy_vs_sma=spy_sma,
        gates_passed=gates,
        liquidity_sweep_context=sweep_ctx,
    )
    if production_blockers:
        return setup, _decision(
            "blocked",
            "counterfactual_setup_recorded",
            blockers=production_blockers,
            gates=gates,
            setup=asdict(setup),
        )
    return setup, _decision("eligible", "all_0dte_pm_gates_passed",
                            setup=asdict(setup),
                            vwap_context=vwap_ctx,
                            iv_term_structure=iv_slope_ctx,
                            liquidity_sweep_context=sweep_ctx)


def check_position(setup: PMSpreadSetup) -> dict[str, Any]:
    now = _now_et()
    hard_close_due = now.time().replace(tzinfo=None) >= HARD_CLOSE_ET
    if yf is None:
        return _decision("error", "yfinance_unavailable")
    try:
        market = _spread_market(setup.expiry, setup.short_strike, setup.long_strike)
    except Exception as exc:
        return _decision("blocked", "monitor_spread_quote_fetch_failed", error=type(exc).__name__)
    if market is None:
        return _decision("blocked", "monitor_spread_quote_unavailable")
    current_cost = float(market["executable_close_debit"])
    pnl = round(setup.entry_credit - current_cost, 2)
    pnl_pct = pnl / setup.entry_credit if setup.entry_credit > 0 else 0.0
    if hard_close_due:
        return _decision("close_hard", "hard_close_15:45_et",
                         pnl=pnl, pnl_pct=round(pnl_pct, 4), current_debit=current_cost)
    if pnl >= setup.profit_target:
        return _decision("close_profit", f"target_hit_{pnl_pct:.0%}",
                         pnl=pnl, pnl_pct=round(pnl_pct, 4), current_debit=current_cost)
    return _decision("hold", f"pnl={pnl:+.2f}_({pnl_pct:+.0%})",
                     pnl=pnl, pnl_pct=round(pnl_pct, 4), current_debit=current_cost)


def record_evidence(setup: PMSpreadSetup) -> dict[str, Any]:
    try:
        decision_at = datetime.fromisoformat(setup.generated_at.replace("Z", "+00:00"))
        evaluation_end = datetime.combine(
            date.fromisoformat(setup.expiry), HARD_CLOSE_ET, tzinfo=ET
        ).astimezone(UTC)
        trade_meta = {
            "strategy": "put_spread",
            "underlying": setup.symbol,
            "expiry": setup.expiry,
            "qty": 1,
            "net_credit": setup.midpoint_credit,
            "max_risk_per_contract": setup.max_loss * 100.0,
            "profit_close_pct": PROFIT_CLOSE_PCT,
            "stop_policy": "none_time_exit_only",
            "evaluation_end_at": evaluation_end.isoformat(),
            "vix_at_entry": setup.vix_at_entry,
            "strategy_context": {"spy_vs_sma": setup.spy_vs_sma},
            "leg_market_snapshots": [
                {
                    "symbol": setup.short_symbol,
                    "expiry": setup.expiry,
                    "strike": setup.short_strike,
                    "right": "P",
                    "delta": -abs(setup.short_delta),
                    "bid": setup.short_bid,
                    "ask": setup.short_ask,
                    "captured_at": setup.quote_captured_at,
                    "quote_provider": "yfinance_chain_snapshot",
                    "quote_scope": "public_snapshot_not_opra_nbbo",
                },
                {
                    "symbol": setup.long_symbol,
                    "expiry": setup.expiry,
                    "strike": setup.long_strike,
                    "right": "P",
                    "delta": None,
                    "bid": setup.long_bid,
                    "ask": setup.long_ask,
                    "captured_at": setup.quote_captured_at,
                    "quote_provider": "yfinance_chain_snapshot",
                    "quote_scope": "public_snapshot_not_opra_nbbo",
                },
            ],
        }
        return record_matched_setup(
            {
                "source_strategy": "spy_0dte_pm_spread",
                "underlying": setup.symbol,
                "decision_at": decision_at.isoformat(),
                "gate_states": setup.gates_passed,
                "spot_at_entry": setup.spy_vs_sma.get("spot"),
                "regime_context": {
                    "vix": setup.vix_at_entry,
                    "above_sma": setup.spy_vs_sma.get("above_sma"),
                    "liquidity_sweep": setup.liquidity_sweep_context,
                },
            },
            trade_meta,
            [
                {"symbol": setup.short_symbol, "side": "sell", "ratio_qty": 1},
                {"symbol": setup.long_symbol, "side": "buy", "ratio_qty": 1},
            ],
            effective_qty=1,
            now=decision_at,
        )
    except Exception as exc:
        logger.warning(f"0DTE PM evidence capture failed: {exc}")
        return {"status": "capture_failed", "error": type(exc).__name__, "execution_enabled": False}


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


def _number_or_none(value: Any) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if math.isfinite(parsed) else None


def record_run_observation(result: dict[str, Any], setup: PMSpreadSetup | None = None) -> dict[str, Any]:
    try:
        return append_observation(
            result,
            provider="spy_0dte_pm_spread",
            setup=asdict(setup) if setup is not None else None,
        )
    except Exception as exc:
        logger.warning(f"0DTE PM observation capture failed: {type(exc).__name__}")
        return {"status": "capture_failed", "execution_enabled": False}


def setup_from_state(state: dict[str, Any]) -> tuple[PMSpreadSetup | None, dict[str, Any] | None]:
    required = {
        name for name, field in PMSpreadSetup.__dataclass_fields__.items()
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
        setup = PMSpreadSetup(**{
            key: value for key, value in state.items()
            if key in PMSpreadSetup.__dataclass_fields__
        })
    except (TypeError, ValueError) as exc:
        return None, _decision(
            "blocked",
            "invalid_shadow_state",
            error=type(exc).__name__,
        )
    return setup, None


def main() -> None:
    parser = argparse.ArgumentParser(description="SPY 0DTE PM put credit spread")
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--state", type=Path, default=DEFAULT_STATE)
    parser.add_argument("--ledger", type=Path, default=DEFAULT_LEDGER)
    parser.add_argument("--out", type=Path, default=ROOT / "data" / "spy_0dte_pm_decision.json")
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
        ledger_line = json.dumps(asdict(setup), separators=(",", ":"), sort_keys=True)
        with args.ledger.open("a", encoding="utf-8") as fh:
            fh.write(ledger_line + "\n")
        logger.info(f"0DTE PM spread shadow entry: {setup.short_strike}/{setup.long_strike} "
                    f"credit={setup.entry_credit} ctw={setup.credit_to_width:.1%}")
    else:
        logger.info(f"0DTE PM spread blocked: {decision['reason']}")

    record_run_observation(decision, observed_setup)
    print(json.dumps(decision, indent=2))


if __name__ == "__main__":
    main()

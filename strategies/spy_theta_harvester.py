#!/usr/bin/env python3
"""Fail-closed SPY put-credit-spread shadow harvester.

This module records conservative shadow fills from executable bid/ask quotes.
It has no order-submission path. A volatility risk premium is treated as
compensation for downside and event risk, not as a guaranteed return.
"""
from __future__ import annotations

import argparse
import json
import logging
import math
import os
import sys
from dataclasses import asdict, dataclass
from datetime import date, datetime, time, timedelta, timezone
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Any, Iterable
from uuid import uuid4
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv

try:
    import yfinance as yf
except ImportError:
    yf = None  # type: ignore[assignment]

try:
    from alpaca.data.historical.option import OptionHistoricalDataClient
    from alpaca.data.requests import OptionChainRequest, OptionLatestQuoteRequest
except ImportError:
    OptionHistoricalDataClient = None  # type: ignore[assignment,misc]
    OptionChainRequest = None  # type: ignore[assignment,misc]
    OptionLatestQuoteRequest = None  # type: ignore[assignment,misc]

from scripts.alpaca_resilience import configure_sdk_client, read_with_retry
from scripts.market_catalyst_calendar import (
    CALENDAR_COVERAGE_END,
    EVENTS_2026,
    risk_window_for_date,
)
from scripts.market_data import fetch_vix_term_structure_context
from scripts.options_confluence import candidate_dimensions, latest_iv_rank_context
from scripts.options_evidence_factory import record_matched_setup
from scripts.options_observation_journal import append_observation
from scripts.options_vol_premium_report import capture_entry_snapshot


load_dotenv(ROOT / "agent" / ".env")

ET = ZoneInfo("America/New_York")
UTC = timezone.utc
VIBE_HOME = Path.home() / ".vibe-trading"
LOG_DIR = VIBE_HOME / "logs"
LOG_PATH = LOG_DIR / "spy-theta-harvester.log"
DEFAULT_STATE_PATH = ROOT / "data" / "theta_harvester_state.json"
DEFAULT_DECISION_PATH = ROOT / "data" / "theta_harvester_latest_decision.json"
DEFAULT_LEDGER_PATH = ROOT / "data" / "theta_harvester_ledger.jsonl"
IV_HISTORY_PATH = ROOT / "data" / "iv_history_log.jsonl"

VIX_MAX = float(os.getenv("THETA_VIX_MAX", "20.0"))
VIX_CONTANGO_MAX = float(os.getenv("THETA_VIX_CONTANGO_MAX", "1.02"))
IVR_MIN = float(os.getenv("THETA_IVR_MIN", "30.0"))
IVP_MIN = float(os.getenv("THETA_IVP_MIN", "50.0"))
TARGET_DELTA = float(os.getenv("THETA_TARGET_DELTA", "0.16"))
SPREAD_WIDTH = float(os.getenv("THETA_SPREAD_WIDTH", "5.0"))
TARGET_DTE_MIN = int(os.getenv("THETA_DTE_MIN", "28"))
TARGET_DTE_MAX = int(os.getenv("THETA_DTE_MAX", "45"))
TARGET_DTE = int(os.getenv("THETA_TARGET_DTE", "35"))
CLOSE_AT_DTE = int(os.getenv("THETA_CLOSE_DTE", "21"))
PROFIT_CLOSE_PCT = float(os.getenv("THETA_PROFIT_CLOSE_PCT", "0.50"))
STOP_DEBIT_MULT = float(os.getenv("THETA_STOP_DEBIT_MULT", "2.0"))
MAX_SPREAD_LOSS_DOLLARS = float(os.getenv("THETA_MAX_SPREAD_LOSS", "500"))
MIN_CREDIT_TO_WIDTH = float(os.getenv("THETA_MIN_CREDIT_TO_WIDTH", "0.33"))
MAX_QUOTE_FRICTION_PCT = float(os.getenv("THETA_MAX_QUOTE_FRICTION_PCT", "0.25"))
MIN_IV_OVER_RV = float(os.getenv("THETA_MIN_IV_OVER_RV", "1.05"))
MIN_NET_VOL_PREMIUM_PCT = float(os.getenv("THETA_MIN_NET_VOL_PREMIUM_PCT", "0.0"))
MAX_QUOTE_AGE_SECONDS = int(os.getenv("THETA_MAX_QUOTE_AGE_SECONDS", "180"))
MAX_TERM_DATA_AGE_DAYS = int(os.getenv("THETA_MAX_TERM_DATA_AGE_DAYS", "4"))
EXPIRY_EVENT_BUFFER_DAYS = int(os.getenv("THETA_EXPIRY_EVENT_BUFFER_DAYS", "2"))
ENTRY_START_ET = time(9, 40)
ENTRY_END_ET = time(10, 15)


LOG_DIR.mkdir(parents=True, exist_ok=True)
logger = logging.getLogger("spy_theta_harvester")
if not logger.handlers:
    logger.setLevel(logging.INFO)
    formatter = logging.Formatter("%(asctime)s %(levelname)s %(message)s")
    stream = logging.StreamHandler()
    stream.setFormatter(formatter)
    logger.addHandler(stream)
    if not os.getenv("PYTEST_CURRENT_TEST"):
        rotating = RotatingFileHandler(LOG_PATH, maxBytes=50 * 1024 * 1024, backupCount=3, encoding="utf-8")
        rotating.setFormatter(formatter)
        logger.addHandler(rotating)


@dataclass(frozen=True)
class OptionLegQuote:
    symbol: str
    expiry: str
    strike: float
    right: str
    delta: float
    bid: float
    ask: float
    implied_volatility: float | None
    quote_timestamp: str | None
    quote_provider: str = "alpaca_options_snapshot_v1beta1"
    quote_scope: str = "indicative_modified_not_opra_nbbo"

    @property
    def mid(self) -> float:
        return (self.bid + self.ask) / 2.0

    @property
    def width(self) -> float:
        return self.ask - self.bid


@dataclass(frozen=True)
class SpreadSetup:
    schema_version: int
    status: str
    shadow_id: str
    generated_at: str
    symbol: str
    expiry: str
    dte: int
    short_symbol: str
    long_symbol: str
    short_strike: float
    long_strike: float
    short_delta: float
    width: float
    entry_credit: float
    midpoint_credit: float
    short_bid: float
    short_ask: float
    long_bid: float
    long_ask: float
    max_loss: float
    credit_to_width: float
    entry_quote_friction: float
    entry_quote_friction_pct: float
    profit_target_debit: float
    stop_debit: float
    profit_target_dollars: float
    stop_loss_dollars: float
    required_win_rate: float
    close_at_dte: int
    vix_at_entry: float
    vix3m_at_entry: float
    vix_over_vix3m: float
    quote_provider: str
    quote_scope: str
    short_quote_timestamp: str | None
    long_quote_timestamp: str | None
    volatility_edge: dict[str, Any]
    event_context: dict[str, Any]
    timeframe_confluence: dict[str, Any]
    execution_enabled: bool = False
    can_submit_orders: bool = False
    orders_submitted: int = 0


def _now_et() -> datetime:
    return datetime.now(tz=ET)


def _iso_utc(value: datetime | None = None) -> str:
    current = value or datetime.now(tz=UTC)
    if current.tzinfo is None:
        current = current.replace(tzinfo=UTC)
    return current.astimezone(UTC).isoformat()


def _atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(path)


def _append_jsonl(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, separators=(",", ":"), sort_keys=True) + "\n")


def _decision(status: str, reason: str, *, now_et: datetime, **details: Any) -> dict[str, Any]:
    return {
        "schema_version": 2,
        "provider": "spy_theta_harvester",
        "mode": "shadow_paper_only",
        "generated_at": _iso_utc(now_et),
        "status": status,
        "reason": reason,
        "details": details,
        "execution_enabled": False,
        "can_submit_orders": False,
        "orders_submitted": 0,
    }


def _parse_timestamp(value: Any) -> datetime | None:
    if value in (None, ""):
        return None
    if isinstance(value, datetime):
        parsed = value
    else:
        try:
            parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except ValueError:
            return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def quote_is_fresh(leg: OptionLegQuote, *, now_et: datetime, max_age_seconds: int = MAX_QUOTE_AGE_SECONDS) -> bool:
    timestamp = _parse_timestamp(leg.quote_timestamp)
    if timestamp is None or not (0 <= leg.bid <= leg.ask) or leg.ask <= 0:
        return False
    age = (now_et.astimezone(UTC) - timestamp).total_seconds()
    return -5 <= age <= max_age_seconds


def entry_window_gate(now_et: datetime) -> tuple[bool, str]:
    local = now_et.astimezone(ET)
    if local.weekday() != 0:
        return False, "entry_day_not_monday"
    if not ENTRY_START_ET <= local.time().replace(tzinfo=None) <= ENTRY_END_ET:
        return False, "outside_entry_window_0940_1015_et"
    return True, "entry_window_ok"


def _monitor_window_gate(now_et: datetime) -> tuple[bool, str]:
    local = now_et.astimezone(ET)
    if local.weekday() >= 5 or not time(9, 30) <= local.time().replace(tzinfo=None) <= time(16, 0):
        return False, "market_monitor_window_closed"
    return True, "monitor_window_ok"


def term_structure_gate(context: dict[str, Any], *, now_et: datetime) -> tuple[bool, str]:
    if context.get("available") is False:
        return False, "vix_term_structure_unavailable"
    try:
        vix = float(context["vix"])
        vix3m = float(context["vix3m"])
        ratio = vix / vix3m
        date_text = str(context["date"])
        try:
            stamp = date.fromisoformat(date_text)
        except ValueError:
            stamp = datetime.strptime(date_text, "%m/%d/%Y").date()
    except (KeyError, TypeError, ValueError, ZeroDivisionError):
        return False, "vix_term_structure_invalid"
    age_days = (now_et.date() - stamp).days
    if age_days < 0 or age_days > MAX_TERM_DATA_AGE_DAYS:
        return False, "vix_term_structure_stale"
    if vix >= VIX_MAX:
        return False, "vix_above_theta_limit"
    if ratio >= VIX_CONTANGO_MAX:
        return False, "vix_curve_not_contango"
    return True, "vix_term_structure_ok"


def _build_option_client() -> Any:
    if OptionHistoricalDataClient is None:
        raise RuntimeError("alpaca option data SDK unavailable")
    key = os.getenv("ALPACA_API_KEY", "").strip()
    secret = os.getenv("ALPACA_SECRET_KEY", "").strip()
    if not key or not secret:
        raise RuntimeError("ALPACA_API_KEY / ALPACA_SECRET_KEY missing")
    return configure_sdk_client(OptionHistoricalDataClient(key, secret))


def _occ_fields(symbol: str, underlying: str) -> tuple[str, float, str]:
    offset = len(underlying)
    expiry = datetime.strptime(symbol[offset : offset + 6], "%y%m%d").date().isoformat()
    right = symbol[offset + 6]
    strike = int(symbol[offset + 7 :]) / 1000.0
    return expiry, strike, right


def _fetch_chain(client: Any, *, symbol: str, now_et: datetime) -> list[OptionLegQuote]:
    if OptionChainRequest is None:
        raise RuntimeError("alpaca OptionChainRequest unavailable")
    request = OptionChainRequest(
        underlying_symbol=symbol,
        expiration_date_gte=now_et.date() + timedelta(days=TARGET_DTE_MIN),
        expiration_date_lte=now_et.date() + timedelta(days=TARGET_DTE_MAX),
        type="put",
    )
    snapshots = read_with_retry(
        lambda: client.get_option_chain(request),
        component="spy_theta_harvester",
        operation="option_chain",
        attempts=3,
        backoff_seconds=0.25,
    )
    legs: list[OptionLegQuote] = []
    for occ, snapshot in snapshots.items():
        quote = getattr(snapshot, "latest_quote", None)
        greeks = getattr(snapshot, "greeks", None)
        if quote is None or greeks is None:
            continue
        try:
            expiry, strike, right = _occ_fields(str(occ), symbol)
            delta = abs(float(getattr(greeks, "delta", 0.0) or 0.0))
            bid = float(getattr(quote, "bid_price", 0.0) or 0.0)
            ask = float(getattr(quote, "ask_price", 0.0) or 0.0)
            iv_raw = getattr(snapshot, "implied_volatility", None)
            iv = float(iv_raw) if iv_raw is not None else None
            quote_timestamp = str(getattr(quote, "timestamp", "") or "") or None
        except (TypeError, ValueError, IndexError):
            continue
        legs.append(OptionLegQuote(
            symbol=str(occ),
            expiry=expiry,
            strike=strike,
            right=right,
            delta=delta,
            bid=bid,
            ask=ask,
            implied_volatility=iv,
            quote_timestamp=quote_timestamp,
        ))
    return legs


def select_candidate(legs: Iterable[OptionLegQuote], *, as_of: date) -> tuple[OptionLegQuote, OptionLegQuote] | None:
    valid = [
        leg for leg in legs
        if leg.right.upper() == "P" and TARGET_DTE_MIN <= (date.fromisoformat(leg.expiry) - as_of).days <= TARGET_DTE_MAX
    ]
    if not valid:
        return None
    expiries = sorted({date.fromisoformat(leg.expiry) for leg in valid})
    expiry = min(expiries, key=lambda value: (abs((value - as_of).days - TARGET_DTE), value))
    same_expiry = [leg for leg in valid if leg.expiry == expiry.isoformat()]
    short = min(same_expiry, key=lambda leg: (abs(leg.delta - TARGET_DELTA), -leg.strike))
    desired_long = short.strike - SPREAD_WIDTH
    wings = [leg for leg in same_expiry if math.isclose(leg.strike, desired_long, abs_tol=0.001)]
    if not wings:
        return None
    return short, wings[0]


def spread_economics(short: OptionLegQuote, long: OptionLegQuote) -> dict[str, float]:
    width = short.strike - long.strike
    executable_credit = short.bid - long.ask
    midpoint_credit = short.mid - long.mid
    quote_friction = short.width + long.width
    max_loss = width - executable_credit
    return {
        "width": width,
        "entry_credit": executable_credit,
        "midpoint_credit": midpoint_credit,
        "max_loss": max_loss,
        "credit_to_width": executable_credit / width if width > 0 else 0.0,
        "entry_quote_friction": quote_friction,
        "entry_quote_friction_pct": quote_friction / executable_credit if executable_credit > 0 else math.inf,
    }


def management_math(entry_credit: float) -> dict[str, float]:
    target_debit = entry_credit * (1.0 - PROFIT_CLOSE_PCT)
    stop_debit = entry_credit * STOP_DEBIT_MULT
    gain = entry_credit - target_debit
    loss = stop_debit - entry_credit
    required = loss / (gain + loss) if gain > 0 and loss > 0 else 1.0
    return {
        "profit_target_debit": target_debit,
        "stop_debit": stop_debit,
        "profit_target_dollars": gain * 100.0,
        "stop_loss_dollars": loss * 100.0,
        "required_win_rate": required,
    }


def _spread_quality_gates(economics: dict[str, float]) -> dict[str, bool]:
    return {
        "positive_executable_credit": economics["entry_credit"] > 0.05,
        "defined_width": math.isclose(economics["width"], SPREAD_WIDTH, abs_tol=0.001),
        "credit_to_width": economics["credit_to_width"] >= MIN_CREDIT_TO_WIDTH,
        "max_loss": economics["max_loss"] * 100.0 <= MAX_SPREAD_LOSS_DOLLARS,
        "quote_friction": economics["entry_quote_friction_pct"] <= MAX_QUOTE_FRICTION_PCT,
    }


def _underlying_closes(symbol: str) -> list[float]:
    if yf is None:
        raise RuntimeError("yfinance unavailable for realized-volatility history")
    history = yf.Ticker(symbol).history(period="6mo", auto_adjust=False)
    closes = [float(value) for value in history["Close"].dropna().tolist()]
    if len(closes) < 60:
        raise RuntimeError("insufficient underlying close history")
    return closes


def _event_context(as_of: date, expiry: date) -> dict[str, Any]:
    within = [
        event for event in EVENTS_2026
        if as_of <= date.fromisoformat(str(event["date"])) <= expiry
    ]
    expiry_conflicts = [
        event for event in within
        if event.get("impact") == "high"
        and 0 <= (expiry - date.fromisoformat(str(event["date"]))).days <= EXPIRY_EVENT_BUFFER_DAYS
    ]
    return {
        "calendar_coverage_end": CALENDAR_COVERAGE_END.isoformat(),
        "calendar_complete_through_expiry": CALENDAR_COVERAGE_END >= expiry,
        "events_within_horizon": [
            {"date": event["date"], "name": event["name"], "impact": event["impact"]}
            for event in within
        ],
        "expiry_event_conflicts": [
            {"date": event["date"], "name": event["name"], "impact": event["impact"]}
            for event in expiry_conflicts
        ],
    }


def build_setup(
    symbol: str = "SPY",
    *,
    now_et: datetime | None = None,
    client: Any = None,
    legs: list[OptionLegQuote] | None = None,
    closes: list[float] | None = None,
    term_context: dict[str, Any] | None = None,
    iv_rank_context: dict[str, Any] | None = None,
) -> tuple[SpreadSetup | None, dict[str, Any]]:
    now_et = (now_et or _now_et()).astimezone(ET)
    window_ok, window_reason = entry_window_gate(now_et)
    if not window_ok:
        return None, _decision("blocked", window_reason, now_et=now_et)

    daily_risk = risk_window_for_date(now_et.date())
    if "short_premium" not in daily_risk.get("allowed_playbooks", []):
        return None, _decision("blocked", "entry_day_event_veto", now_et=now_et, event_risk=daily_risk)

    term_context = term_context if term_context is not None else fetch_vix_term_structure_context()
    term_ok, term_reason = term_structure_gate(term_context, now_et=now_et)
    if not term_ok:
        return None, _decision("blocked", term_reason, now_et=now_et, term_structure=term_context)

    if legs is None:
        client = client or _build_option_client()
        legs = _fetch_chain(client, symbol=symbol, now_et=now_et)
    if not legs:
        return None, _decision("blocked", "option_chain_unavailable", now_et=now_et)

    selected = select_candidate(legs, as_of=now_et.date())
    if selected is None:
        return None, _decision("blocked", "target_spread_not_found", now_et=now_et)
    short, long = selected
    freshness = {
        short.symbol: quote_is_fresh(short, now_et=now_et),
        long.symbol: quote_is_fresh(long, now_et=now_et),
    }
    if not all(freshness.values()):
        return None, _decision("blocked", "option_quotes_stale_or_invalid", now_et=now_et, quote_freshness=freshness)
    if not 0.10 <= short.delta <= 0.22:
        return None, _decision(
            "blocked",
            "target_delta_unavailable",
            now_et=now_et,
            selected_delta=short.delta,
        )

    economics = spread_economics(short, long)
    quality_gates = _spread_quality_gates(economics)
    if not all(quality_gates.values()):
        return None, _decision(
            "blocked",
            "spread_quality_failed",
            now_et=now_et,
            spread={key: round(value, 6) if math.isfinite(value) else None for key, value in economics.items()},
            gates=quality_gates,
        )

    expiry = date.fromisoformat(short.expiry)
    event_context = _event_context(now_et.date(), expiry)
    if not event_context["calendar_complete_through_expiry"]:
        return None, _decision("blocked", "macro_calendar_incomplete", now_et=now_et, event_context=event_context)
    if event_context["expiry_event_conflicts"]:
        return None, _decision("blocked", "high_impact_event_near_expiry", now_et=now_et, event_context=event_context)

    closes = closes if closes is not None else _underlying_closes(symbol)
    selected_legs = [
        {"bid": short.bid, "ask": short.ask, "ratio_qty": 1},
        {"bid": long.bid, "ask": long.ask, "ratio_qty": 1},
    ]
    chain_legs = [
        {
            "symbol": leg.symbol,
            "expiry": leg.expiry,
            "right": leg.right,
            "delta": -abs(leg.delta) if leg.right.upper() == "P" else abs(leg.delta),
            "implied_volatility": leg.implied_volatility,
        }
        for leg in legs
    ]
    volatility_edge = capture_entry_snapshot(
        symbol=symbol,
        expiry=expiry,
        selected_legs=selected_legs,
        chain_legs=chain_legs,
        vix_at_entry=term_context["vix"],
        as_of=now_et.date(),
        closes=closes,
        macro_events=EVENTS_2026,
        macro_coverage_end=CALENDAR_COVERAGE_END,
        earnings_dates=[],
    )
    atm_iv = volatility_edge.get("atm_iv_annualized_pct")
    rv = volatility_edge.get("rv_forecast_annualized_pct")
    net_premium = volatility_edge.get("net_vol_premium_ex_event_pct")
    iv_over_rv = float(atm_iv) / float(rv) if atm_iv is not None and rv not in (None, 0) else None
    volatility_gates = {
        "measurement_complete": volatility_edge.get("status") == "complete_ex_event",
        "iv_over_realized": iv_over_rv is not None and iv_over_rv >= MIN_IV_OVER_RV,
        "net_premium_positive": net_premium is not None and float(net_premium) > MIN_NET_VOL_PREMIUM_PCT,
        "event_data_complete": volatility_edge.get("event_data_complete") is True,
    }
    volatility_edge["iv_over_realized_ratio"] = round(iv_over_rv, 6) if iv_over_rv is not None else None
    volatility_edge["execution_gates"] = volatility_gates
    if not all(volatility_gates.values()):
        return None, _decision(
            "blocked",
            "volatility_edge_failed",
            now_et=now_et,
            volatility_edge=volatility_edge,
        )

    management = management_math(economics["entry_credit"])
    ratio = float(term_context["vix"]) / float(term_context["vix3m"])
    iv_rank_context = iv_rank_context if iv_rank_context is not None else latest_iv_rank_context(
        symbol,
        as_of=now_et.date(),
        log_path=IV_HISTORY_PATH,
    )
    _ivr = iv_rank_context.get("ivr")
    _ivp = iv_rank_context.get("ivp")
    ivr_gates = {
        "ivr_above_min": _ivr is not None and float(_ivr) >= IVR_MIN,
        "ivp_above_min": _ivp is not None and float(_ivp) >= IVP_MIN,
    }
    if not all(ivr_gates.values()):
        return None, _decision(
            "blocked",
            "iv_rank_below_threshold",
            now_et=now_et,
            ivr=_ivr,
            ivp=_ivp,
            ivr_min=IVR_MIN,
            ivp_min=IVP_MIN,
            iv_rank_context=iv_rank_context,
        )
    confluence_dimensions = candidate_dimensions({
        "strategy": "put_spread",
        "created_at": _iso_utc(now_et),
        "expiry": short.expiry,
        "iv_rank_at_entry": iv_rank_context.get("ivr"),
        "vix_term_ratio": ratio,
        "quoted_mid_credit": economics["midpoint_credit"],
        "executable_entry_credit": economics["entry_credit"],
        "volatility_edge": volatility_edge,
    })
    timeframe_confluence = {
        "authority": "shadow_attribution_only_no_execution",
        "execution_effect": "none",
        "dimensions": confluence_dimensions,
        "iv_rank_context": iv_rank_context,
        "warnings": [
            "IVR and IVP remain descriptive and do not replace maturity-matched IV versus realized volatility.",
            "Trend alignment is unavailable until a point-in-time trend snapshot is frozen at entry.",
        ],
    }
    setup = SpreadSetup(
        schema_version=2,
        status="open_shadow",
        shadow_id=f"theta-{now_et.date().isoformat()}-{uuid4().hex[:10]}",
        generated_at=_iso_utc(now_et),
        symbol=symbol,
        expiry=short.expiry,
        dte=(expiry - now_et.date()).days,
        short_symbol=short.symbol,
        long_symbol=long.symbol,
        short_strike=short.strike,
        long_strike=long.strike,
        short_delta=short.delta,
        width=economics["width"],
        entry_credit=round(economics["entry_credit"], 4),
        midpoint_credit=round(economics["midpoint_credit"], 4),
        short_bid=round(short.bid, 4),
        short_ask=round(short.ask, 4),
        long_bid=round(long.bid, 4),
        long_ask=round(long.ask, 4),
        max_loss=round(economics["max_loss"], 4),
        credit_to_width=round(economics["credit_to_width"], 6),
        entry_quote_friction=round(economics["entry_quote_friction"], 4),
        entry_quote_friction_pct=round(economics["entry_quote_friction_pct"], 6),
        profit_target_debit=round(management["profit_target_debit"], 4),
        stop_debit=round(management["stop_debit"], 4),
        profit_target_dollars=round(management["profit_target_dollars"], 2),
        stop_loss_dollars=round(management["stop_loss_dollars"], 2),
        required_win_rate=round(management["required_win_rate"], 6),
        close_at_dte=CLOSE_AT_DTE,
        vix_at_entry=float(term_context["vix"]),
        vix3m_at_entry=float(term_context["vix3m"]),
        vix_over_vix3m=round(ratio, 6),
        quote_provider=short.quote_provider,
        quote_scope=short.quote_scope,
        short_quote_timestamp=short.quote_timestamp,
        long_quote_timestamp=long.quote_timestamp,
        volatility_edge=volatility_edge,
        event_context=event_context,
        timeframe_confluence=timeframe_confluence,
    )
    return setup, _decision("eligible", "all_shadow_entry_gates_passed", now_et=now_et, setup=asdict(setup))


def _latest_leg_quotes(client: Any, symbols: list[str]) -> dict[str, OptionLegQuote]:
    if OptionLatestQuoteRequest is None:
        raise RuntimeError("alpaca OptionLatestQuoteRequest unavailable")
    request = OptionLatestQuoteRequest(symbol_or_symbols=symbols)
    payload = read_with_retry(
        lambda: client.get_option_latest_quote(request),
        component="spy_theta_harvester",
        operation="latest_option_quotes",
        attempts=3,
        backoff_seconds=0.25,
    )
    output: dict[str, OptionLegQuote] = {}
    for symbol, quote in payload.items():
        expiry, strike, right = _occ_fields(str(symbol), "SPY")
        output[str(symbol)] = OptionLegQuote(
            symbol=str(symbol),
            expiry=expiry,
            strike=strike,
            right=right,
            delta=0.0,
            bid=float(getattr(quote, "bid_price", 0.0) or 0.0),
            ask=float(getattr(quote, "ask_price", 0.0) or 0.0),
            implied_volatility=None,
            quote_timestamp=str(getattr(quote, "timestamp", "") or "") or None,
        )
    return output


def load_shadow_state(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {"status": "absent"}
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"theta shadow state unreadable: {exc}") from exc
    if payload.get("schema_version") != 2 or "status" not in payload:
        return {"status": "legacy_unconfirmed", "reason": "legacy setup is not an open shadow position"}
    return payload


def record_shadow_open(setup: SpreadSetup, *, state_path: Path, ledger_path: Path) -> dict[str, Any]:
    existing = load_shadow_state(state_path)
    if existing.get("status") == "open_shadow":
        return _decision("blocked", "open_shadow_position_already_exists", now_et=_now_et(), shadow_id=existing.get("shadow_id"))
    payload = asdict(setup)
    _atomic_write_json(state_path, payload)
    _append_jsonl(ledger_path, {"type": "open_shadow", **payload})
    record_evidence(setup)
    return _decision("opened_shadow", "executable_quote_shadow_fill_recorded", now_et=_now_et(), setup=payload)


def record_evidence(setup: SpreadSetup) -> dict[str, Any]:
    try:
        decision_at = datetime.fromisoformat(setup.generated_at.replace("Z", "+00:00"))
        close_date = date.fromisoformat(setup.expiry) - timedelta(days=setup.close_at_dte)
        evaluation_end = datetime.combine(close_date, time(15, 45), tzinfo=ET).astimezone(UTC)
        snapshots = [
            {
                "symbol": setup.short_symbol,
                "expiry": setup.expiry,
                "strike": setup.short_strike,
                "right": "P",
                "delta": -abs(setup.short_delta),
                "bid": setup.short_bid,
                "ask": setup.short_ask,
                "quote_timestamp": setup.short_quote_timestamp,
                "captured_at": setup.generated_at,
                "quote_provider": setup.quote_provider,
                "quote_scope": setup.quote_scope,
            },
            {
                "symbol": setup.long_symbol,
                "expiry": setup.expiry,
                "strike": setup.long_strike,
                "right": "P",
                "delta": None,
                "bid": setup.long_bid,
                "ask": setup.long_ask,
                "quote_timestamp": setup.long_quote_timestamp,
                "captured_at": setup.generated_at,
                "quote_provider": setup.quote_provider,
                "quote_scope": setup.quote_scope,
            },
        ]
        trade_meta = {
            "strategy": "put_spread",
            "underlying": setup.symbol,
            "expiry": setup.expiry,
            "qty": 1,
            "net_credit": setup.midpoint_credit,
            "max_risk_per_contract": setup.max_loss * 100.0,
            "profit_close_pct": PROFIT_CLOSE_PCT,
            "stop_loss_pct": -1.0,
            "stop_policy": "credit_multiple",
            "evaluation_end_at": evaluation_end.isoformat(),
            "vix_at_entry": setup.vix_at_entry,
            "vix_term_ratio": setup.vix_over_vix3m,
            "volatility_edge": setup.volatility_edge,
            "event_context": setup.event_context,
            "strategy_context": {"timeframe_confluence": setup.timeframe_confluence},
            "leg_market_snapshots": snapshots,
        }
        return record_matched_setup(
            {
                "source_strategy": "vrp_defined_risk",
                "underlying": setup.symbol,
                "decision_at": decision_at.isoformat(),
                "gate_states": {
                    "volatility_edge": True,
                    "entry_quote": True,
                    "term_structure": setup.vix_over_vix3m < VIX_CONTANGO_MAX,
                },
                "event_context": setup.event_context,
                "regime_context": {"vix": setup.vix_at_entry, "vix3m": setup.vix3m_at_entry},
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
        logger.warning(f"Theta evidence capture failed: {exc}")
        return {"status": "capture_failed", "error": type(exc).__name__, "execution_enabled": False}


def monitor_shadow(
    *,
    state_path: Path,
    ledger_path: Path,
    now_et: datetime | None = None,
    client: Any = None,
    quotes: dict[str, OptionLegQuote] | None = None,
) -> dict[str, Any]:
    now_et = (now_et or _now_et()).astimezone(ET)
    window_ok, window_reason = _monitor_window_gate(now_et)
    if not window_ok:
        return _decision("skipped", window_reason, now_et=now_et)
    state = load_shadow_state(state_path)
    if state.get("status") != "open_shadow":
        return _decision("skipped", "no_confirmed_open_shadow_position", now_et=now_et, state_status=state.get("status"))
    symbols = [str(state["short_symbol"]), str(state["long_symbol"])]
    if quotes is None:
        client = client or _build_option_client()
        quotes = _latest_leg_quotes(client, symbols)
    if any(symbol not in quotes for symbol in symbols):
        return _decision("blocked", "monitor_quotes_missing", now_et=now_et, symbols=symbols)
    short = quotes[symbols[0]]
    long = quotes[symbols[1]]
    if not quote_is_fresh(short, now_et=now_et) or not quote_is_fresh(long, now_et=now_et):
        return _decision("blocked", "monitor_quotes_stale_or_invalid", now_et=now_et)

    close_debit = max(0.0, short.ask - long.bid)
    entry_credit = float(state["entry_credit"])
    pnl_per_share = entry_credit - close_debit
    action = "hold"
    dte_remaining = (date.fromisoformat(str(state["expiry"])) - now_et.date()).days
    if dte_remaining <= int(state.get("close_at_dte", CLOSE_AT_DTE)):
        action = "close_time_shadow"
    elif close_debit <= float(state["profit_target_debit"]):
        action = "close_profit_shadow"
    elif close_debit >= float(state["stop_debit"]):
        action = "close_stop_shadow"
    mark = {
        "as_of": _iso_utc(now_et),
        "executable_close_debit": round(close_debit, 4),
        "pnl_per_share": round(pnl_per_share, 4),
        "pnl_dollars": round(pnl_per_share * 100.0, 2),
        "action": action,
        "dte_remaining": dte_remaining,
        "short_ask": short.ask,
        "long_bid": long.bid,
        "quote_scope": short.quote_scope,
    }
    state["last_mark"] = mark
    if action.startswith("close_"):
        state["status"] = "closed_shadow"
        state["closed_at"] = mark["as_of"]
        state["close_reason"] = action
        state["realized_shadow_pnl_dollars"] = mark["pnl_dollars"]
        _append_jsonl(ledger_path, {"type": "close_shadow", "shadow_id": state["shadow_id"], **mark})
    else:
        _append_jsonl(ledger_path, {"type": "mark_shadow", "shadow_id": state["shadow_id"], **mark})
    _atomic_write_json(state_path, state)
    return _decision("ok", action, now_et=now_et, mark=mark, shadow_id=state["shadow_id"])


def _print_result(result: dict[str, Any]) -> None:
    print(json.dumps(result, indent=2, sort_keys=True))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--symbol", default="SPY")
    parser.add_argument("--check", action="store_true", help="Monitor the confirmed shadow state")
    parser.add_argument("--state", type=Path, default=DEFAULT_STATE_PATH)
    parser.add_argument("--out", type=Path, default=DEFAULT_DECISION_PATH)
    parser.add_argument("--ledger", type=Path, default=DEFAULT_LEDGER_PATH)
    args = parser.parse_args()

    if os.getenv("THETA_LIVE_EXECUTION", "").strip():
        result = _decision("error", "live_execution_is_not_supported", now_et=_now_et())
        _atomic_write_json(args.out, result)
        append_observation(result, provider="spy_theta_harvester")
        _print_result(result)
        return 2

    setup: SpreadSetup | None = None
    try:
        if args.check:
            result = monitor_shadow(state_path=args.state, ledger_path=args.ledger)
        else:
            existing = load_shadow_state(args.state)
            if existing.get("status") == "open_shadow":
                result = _decision(
                    "blocked",
                    "open_shadow_position_already_exists",
                    now_et=_now_et(),
                    shadow_id=existing.get("shadow_id"),
                )
            else:
                setup, result = build_setup(args.symbol)
                if setup is not None:
                    result = record_shadow_open(setup, state_path=args.state, ledger_path=args.ledger)
        _atomic_write_json(args.out, result)
        append_observation(
            result,
            provider="spy_theta_harvester",
            setup=asdict(setup) if setup is not None else None,
        )
        _print_result(result)
        return 0
    except Exception as exc:
        logger.exception("theta harvester failed")
        result = _decision("error", "unhandled_exception", now_et=_now_et(), error=str(exc)[:300])
        _atomic_write_json(args.out, result)
        try:
            append_observation(result, provider="spy_theta_harvester")
        except Exception:
            logger.exception("theta observation capture failed")
        _print_result(result)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

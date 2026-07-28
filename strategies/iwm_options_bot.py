#!/usr/bin/env python3
"""
Options Bot - Iron Condor + Put Spread + Wheel Automation
Symbols: IWM (ic+ps), SPY (ps), QQQ (ps), NVDA (ps+wheel), PLTR (ps), TSLA (ic+ps), AAPL (ps+wheel)
Broker: Alpaca Markets (paper by default, flip ALPACA_PAPER=false for live)

Strategy 1 - Iron Condor:      16-delta, 30-45 DTE, close at 50% profit
Strategy 2 - Put Spread:       25-delta,  7-14 DTE, close at 50% profit
Strategy 3 - Wheel (NVDA):     sell CSP â†’ if assigned sell covered call, repeat

Run daily after 9:45am ET (gives opening range time to form).
"""
from __future__ import annotations

import logging
import math
import os
import re
import sys
import json
import time
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Optional
from uuid import uuid4
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import numpy as np
import yfinance as yf
from dotenv import load_dotenv

from alpaca.data.historical.option import OptionHistoricalDataClient
from alpaca.data.requests import OptionChainRequest, OptionLatestQuoteRequest
from alpaca.trading.client import TradingClient
from alpaca.trading.requests import GetOrdersRequest
from alpaca.trading.enums import QueryOrderStatus

try:
    from risk_kill_switch import DEFAULT_BLOCK_FILE, manual_reset_required
    from execution_guard import evaluate_execution
    from shadow_consensus import entry_advice as shadow_entry_advice
    from shadow_consensus import exit_advice as shadow_exit_advice
    import options_state
    from scripts.market_data import fetch_vix_term_structure_context
except ModuleNotFoundError:
    from strategies.risk_kill_switch import DEFAULT_BLOCK_FILE, manual_reset_required
    from strategies.execution_guard import evaluate_execution
    from strategies.shadow_consensus import entry_advice as shadow_entry_advice
    from strategies.shadow_consensus import exit_advice as shadow_exit_advice
    from strategies import options_state
    from scripts.market_data import fetch_vix_term_structure_context

load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), "..", "agent", ".env"))

# â”€â”€ Logging â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
LOG_DIR  = os.path.expanduser(r"~\.vibe-trading\logs")
LOG_FILE = os.path.join(LOG_DIR, "options-bot.log")
DECISION_LOG_FILE = os.path.join(LOG_DIR, "options-decisions.jsonl")
os.makedirs(LOG_DIR, exist_ok=True)

_fmt = logging.Formatter("%(asctime)s  %(levelname)-8s  %(message)s", datefmt="%Y-%m-%d %H:%M:%S")
_sh  = logging.StreamHandler()
_sh.setFormatter(_fmt)

_handlers: list[logging.Handler] = [_sh]
try:
    _fh = logging.FileHandler(LOG_FILE, encoding="utf-8")
except OSError:
    fallback_log = os.path.join(LOG_DIR, f"options-bot-{os.getpid()}-{int(time.time())}.log")
    try:
        _fh = logging.FileHandler(fallback_log, encoding="utf-8")
    except OSError:
        _fh = logging.NullHandler()
_fh.setFormatter(_fmt)
_handlers.insert(0, _fh)

logging.basicConfig(level=logging.INFO, handlers=_handlers)
log = logging.getLogger("options-bot")

# â”€â”€ Safety Caps â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
MAX_ACCOUNT_RISK_PCT = float(os.getenv("MAX_ACCOUNT_RISK_PCT", "0.02"))  # per-trade max loss budget
MAX_OPEN_TRADES      = int(os.getenv("MAX_OPEN_TRADES", "8"))             # max concurrent option positions
MAX_TRADES_PER_DAY   = int(os.getenv("MAX_TRADES_PER_DAY", "5"))          # entries per calendar day
MAX_CONTRACTS_PER_ORDER = int(os.getenv("MAX_CONTRACTS_PER_ORDER", "5"))  # hard order-size cap
IV_RANK_MIN          = float(os.getenv("IV_RANK_MIN", "30.0"))            # skip new entries if vol rank below this
EARNINGS_SKIP_DAYS   = int(os.getenv("EARNINGS_SKIP_DAYS", "5"))          # skip entry if earnings within this many days
MIN_CREDIT_TO_RISK   = float(os.getenv("MIN_CREDIT_TO_RISK", "0.20"))     # avoid tiny-credit steamroller trades
MIN_NET_CREDIT       = float(os.getenv("MIN_NET_CREDIT", "0.10"))         # ignore pennies after bid/ask friction
MAX_WHEEL_ALLOC_PCT  = float(os.getenv("MAX_WHEEL_ALLOC_PCT", "0.20"))    # cash reserved for CSP entries
ACCOUNT_SIZE_OVERRIDE = float(os.getenv("ACCOUNT_SIZE_OVERRIDE", "0") or 0)  # paper-test a smaller real account
FAIL_OPEN_MARKET_CHECK = os.getenv("FAIL_OPEN_MARKET_CHECK", "false").lower() == "true"
MAX_DAILY_LOSS_PCT   = float(os.getenv("MAX_DAILY_LOSS_PCT", "0.03"))       # kill switch for new entries
CLOSE_ON_DAILY_LOSS  = os.getenv("CLOSE_ON_DAILY_LOSS", "false").lower() == "true"
MAX_BID_ASK_PCT      = float(os.getenv("MAX_BID_ASK_PCT", "0.35"))          # skip illiquid options
MIN_CANDIDATE_CONFIDENCE = int(os.getenv("MIN_CANDIDATE_CONFIDENCE", "8"))  # paper entry floor; use 9+ before live capital
REQUIRE_MANUAL_APPROVAL = os.getenv(
    "REQUIRE_MANUAL_APPROVAL",
    "false" if os.getenv("ALPACA_PAPER", "true").lower() == "true" else "true",
).lower() == "true"
MAX_OPEN_TRADES_PER_UNDERLYING = int(os.getenv("MAX_OPEN_TRADES_PER_UNDERLYING", "1"))
MAX_NEW_TRADES_PER_SYMBOL_PER_RUN = int(os.getenv("MAX_NEW_TRADES_PER_SYMBOL_PER_RUN", "1"))

# â”€â”€ Multi-Symbol Config â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
# Maps symbol â†’ list of strategies to run
# ETFs (IWM/SPY/QQQ): lower IV, good for IC + spreads
# Individual stocks (NVDA/PLTR): high IV, put spreads + wheel
SYMBOLS: dict[str, list[str]] = {
    "IWM":  ["ic", "ps", "cs"],  # ETF: IC + put spread (up) + call spread (down)
    "SPY":  ["ps", "cs"],        # ETF: put spread (up) + call spread (down)
    "QQQ":  ["ps", "cs"],        # ETF: put spread (up) + call spread (down)
    "TSLA": ["ic", "ps", "cs"],  # High IV: all three
    "NVDA": ["ps", "cs", "wheel"],  # High IV: both directions + wheel
    "AAPL": ["ps", "cs", "wheel"],  # Liquid: both directions + wheel
    "PLTR": ["ps", "cs"],        # High IV: both directions
}

# Per-symbol put spread width override (higher-priced stocks need wider spreads)
PS_WIDTH_OVERRIDE: dict[str, float] = {
    "SPY":  5.0,
    "QQQ":  5.0,
    "TSLA": 5.0,
    "AAPL": 5.0,
}

# â”€â”€ Strategy Parameters â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
IC_DTE_MIN          = 30
IC_DTE_MAX          = 45
IC_DELTA_TARGET     = 0.16    # short leg delta (~84% probability of profit)
IC_WING_WIDTH       = 3       # $3 wings on each side
IC_PROFIT_CLOSE_PCT = 0.50    # close at 50% of max credit (82% win rate per tastytrade research)

PS_DTE_MIN          = 7
PS_DTE_MAX          = 14
PS_DELTA_TARGET     = 0.25    # short put delta
PS_WIDTH            = 3       # $3 default spread width (override per symbol above)
PS_PROFIT_CLOSE_PCT = 0.50

# Wheel strategy (cash-secured put â†’ covered call loop)
WHEEL_DTE_MIN       = 21
WHEEL_DTE_MAX       = 35
WHEEL_DELTA         = 0.30    # slightly more aggressive delta for more premium
WHEEL_CC_DELTA      = 0.30    # covered call delta after assignment
WHEEL_PROFIT_PCT    = 0.50

STOP_LOSS_PCT       = -2.0    # close if loss reaches 200% of credit (short premium needs room)
IC_DTE_MANAGE_DAYS  = int(os.getenv("IC_DTE_MANAGE_DAYS", "21"))
PS_DTE_MANAGE_DAYS  = int(os.getenv("PS_DTE_MANAGE_DAYS", "2"))
CREDIT_NEAR_TARGET_CLOSE_PCT = float(os.getenv("CREDIT_NEAR_TARGET_CLOSE_PCT", "0.45"))
CREDIT_NEAR_TARGET_AFTER_ET = os.getenv("CREDIT_NEAR_TARGET_AFTER_ET", "12:00")
CREDIT_PROFIT_PROTECT_ARM_PCT = float(os.getenv("CREDIT_PROFIT_PROTECT_ARM_PCT", "0.20"))
CREDIT_PROFIT_PROTECT_FLOOR_PCT = float(os.getenv("CREDIT_PROFIT_PROTECT_FLOOR_PCT", "0.20"))
CREDIT_PROFIT_PROTECT_GIVEBACK_PCT = float(os.getenv("CREDIT_PROFIT_PROTECT_GIVEBACK_PCT", "0.15"))
CREDIT_SHADOW_DEFENSIVE_EXIT_LOSS_PCT = float(os.getenv("CREDIT_SHADOW_DEFENSIVE_EXIT_LOSS_PCT", "0.0"))
SHADOW_DEFENSIVE_EXIT_BLOCKERS = {
    "shadow_direction_flip",
    "options_liquidity_blocked",
    "options_liquidity_unknown",
    "options_liquidity_borderline",
    "market_force_unclear",
    "mixed_higher_timeframes",
    "htf_mixed_higher_timeframes",
    "adaptive_market_regime_is_unclear_or_mixed",
    "adaptive_stand_aside",
}

PAPER = os.getenv("ALPACA_PAPER", "true").lower() == "true"
BASE  = "https://paper-api.alpaca.markets" if PAPER else "https://api.alpaca.markets"
LIVE_EXECUTION_ENABLED = os.getenv("OPTIONS_LIVE_EXECUTION_ENABLED", "false").lower() == "true"
VIBE_HOME = Path.home() / ".vibe-trading"
GARCH_RISK_REPORT = Path(os.path.expanduser(os.getenv(
    "GARCH_RISK_REPORT", str(VIBE_HOME / "reports" / "garch-volatility-risk.json"),
)))
ENABLE_GARCH_RISK_GATE = os.getenv("ENABLE_GARCH_RISK_GATE", "true").lower() == "true"
OPTIONS_GARCH_STORM_BLOCK = os.getenv("OPTIONS_GARCH_STORM_BLOCK", "true").lower() == "true"
OPTIONS_REQUIRE_GARCH_REPORT = os.getenv("OPTIONS_REQUIRE_GARCH_REPORT", "false").lower() == "true"
OPTIONS_GARCH_MIN_ENTRY_MULTIPLIER = float(
    os.getenv("OPTIONS_GARCH_MIN_ENTRY_MULTIPLIER", "0.50")
)
OPTIONS_STRICT_SHADOW_CAUTION_GATE = os.getenv(
    "OPTIONS_STRICT_SHADOW_CAUTION_GATE", "true"
).lower() == "true"
OPTIONS_STRICT_CAUTION_MIN_WARNINGS = max(
    2, int(os.getenv("OPTIONS_STRICT_CAUTION_MIN_WARNINGS", "2"))
)
AUTO_CLOSE_GROUPS = os.getenv("AUTO_CLOSE_GROUPS", "true" if PAPER else "false").lower() == "true"
TRADE_STATE_FILE = Path(os.path.expanduser(r"~\.vibe-trading\options-trades.json"))
ORDER_RETRY_ATTEMPTS = int(os.getenv("ORDER_RETRY_ATTEMPTS", "3"))
ORDER_RETRY_BASE_SECONDS = float(os.getenv("ORDER_RETRY_BASE_SECONDS", "1.5"))
RETRY_STATUS_CODES = {429, 500, 502, 503, 504}


def _now_et() -> datetime:
    return datetime.now(ZoneInfo("America/New_York"))


def _utc_timestamp() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _garch_meta(row: dict | None, reason: str) -> dict:
    row = row if isinstance(row, dict) else {}
    return {
        "enabled": ENABLE_GARCH_RISK_GATE,
        "reason": reason,
        "report_path": str(GARCH_RISK_REPORT),
        "symbol": str(row.get("symbol") or "").upper() or None,
        "status": row.get("status"),
        "regime": row.get("regime"),
        "position_size_multiplier": row.get("position_size_multiplier"),
        "forecast_vol_annualized_pct": row.get("forecast_vol_annualized_pct"),
        "vol_percentile_1y": row.get("vol_percentile_1y"),
    }


def _garch_symbol_row(symbol: str) -> tuple[dict | None, str]:
    """Read one symbol's GARCH row without turning a report outage into a crash."""
    if not ENABLE_GARCH_RISK_GATE:
        return None, "garch_gate_disabled"
    try:
        with GARCH_RISK_REPORT.open("r", encoding="utf-8") as fh:
            report = json.load(fh)
    except FileNotFoundError:
        return None, "garch_report_missing"
    except (OSError, json.JSONDecodeError) as exc:
        log.warning(f"GARCH report unreadable at {GARCH_RISK_REPORT}: {exc}")
        return None, "garch_report_unreadable"
    rows = report.get("symbols") if isinstance(report, dict) else None
    if not isinstance(rows, list):
        return None, "garch_report_invalid"
    normalized = str(symbol or "").upper()
    row = next(
        (item for item in rows if isinstance(item, dict) and str(item.get("symbol") or "").upper() == normalized),
        None,
    )
    return row, "garch_ok" if row else "garch_symbol_missing"


def _garch_entry_adjustment(symbol: str, qty: int) -> tuple[int, dict, bool]:
    """Return a non-increasing entry quantity and whether a new entry may proceed."""
    row, reason = _garch_symbol_row(symbol)
    meta = _garch_meta(row, reason)
    if not ENABLE_GARCH_RISK_GATE:
        return qty, meta, True
    if row is None:
        return qty, meta, not OPTIONS_REQUIRE_GARCH_REPORT
    if str(row.get("status") or "").lower() != "ok":
        meta["reason"] = "garch_symbol_not_ok"
        return qty, meta, not OPTIONS_REQUIRE_GARCH_REPORT
    if str(row.get("regime") or "").lower() == "storm" and OPTIONS_GARCH_STORM_BLOCK:
        meta["reason"] = "garch_storm_regime"
        return 0, meta, False
    try:
        multiplier = float(row.get("position_size_multiplier"))
    except (TypeError, ValueError):
        meta["reason"] = "garch_invalid_multiplier"
        return qty, meta, not OPTIONS_REQUIRE_GARCH_REPORT
    if not math.isfinite(multiplier) or multiplier <= 0:
        meta["reason"] = "garch_invalid_multiplier"
        return qty, meta, not OPTIONS_REQUIRE_GARCH_REPORT
    multiplier = min(1.0, multiplier)
    meta["position_size_multiplier"] = multiplier
    if multiplier < OPTIONS_GARCH_MIN_ENTRY_MULTIPLIER:
        meta["reason"] = "garch_multiplier_below_entry_floor"
        return 0, meta, False
    adjusted_qty = min(qty, max(1, int(qty * multiplier)))
    meta["reason"] = "garch_size_down" if adjusted_qty < qty else "garch_normal"
    return adjusted_qty, meta, True


def _credit_near_target_cutoff_reached(now_et: datetime | None = None) -> bool:
    now_et = now_et or _now_et()
    try:
        cutoff = datetime.strptime(CREDIT_NEAR_TARGET_AFTER_ET, "%H:%M").time()
    except ValueError:
        cutoff = datetime.strptime("12:00", "%H:%M").time()
    return now_et.time() >= cutoff


def _credit_near_target_reason(trade: dict, pnl_pct: float, basis_src: str) -> str:
    """Protect late-day credit wins that are close enough to target."""
    if basis_src != "credit":
        return ""
    target = float(trade.get("profit_close_pct", PS_PROFIT_CLOSE_PCT))
    near_target = min(CREDIT_NEAR_TARGET_CLOSE_PCT, target)
    best_pnl_pct = float(trade.get("best_pnl_pct", pnl_pct))
    lock_floor = max(
        CREDIT_PROFIT_PROTECT_FLOOR_PCT,
        best_pnl_pct - CREDIT_PROFIT_PROTECT_GIVEBACK_PCT,
    )
    if pnl_pct >= target:
        return f"profit target hit: {pnl_pct:+.1%} of {basis_src}"
    if (
        best_pnl_pct >= CREDIT_PROFIT_PROTECT_ARM_PCT
        and pnl_pct <= lock_floor
    ):
        return (
            f"profit protect: {pnl_pct:+.1%} of {basis_src} "
            f"(best {best_pnl_pct:+.1%}, lock {lock_floor:+.1%})"
        )
    if pnl_pct >= near_target and _credit_near_target_cutoff_reached():
        cutoff = CREDIT_NEAR_TARGET_AFTER_ET
        return (
            f"near-target protection: {pnl_pct:+.1%} of {basis_src} "
            f">= {near_target:.0%} after {cutoff} ET"
        )
    return ""


def _shadow_defensive_exit_reason(
    trade: dict,
    consensus_exit: dict,
    pnl_pct: float,
    basis_src: str,
) -> str:
    if consensus_exit.get("action") != "review_exit":
        return ""
    blockers = {str(item) for item in (consensus_exit.get("blockers") or [])}
    severe = sorted(blockers.intersection(SHADOW_DEFENSIVE_EXIT_BLOCKERS))
    if not severe:
        return ""
    if pnl_pct > CREDIT_SHADOW_DEFENSIVE_EXIT_LOSS_PCT:
        return ""
    blocker_text = ",".join(severe[:4])
    return f"shadow defensive exit: {pnl_pct:+.1%} of {basis_src} with {blocker_text}"


# â”€â”€ Clients â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
def _build_clients() -> tuple[TradingClient, OptionHistoricalDataClient]:
    key    = os.getenv("ALPACA_API_KEY", "")
    secret = os.getenv("ALPACA_SECRET_KEY", "")
    if not key or not secret:
        log.error("ALPACA_API_KEY / ALPACA_SECRET_KEY missing in .env â€” aborting")
        sys.exit(1)
    if not PAPER and os.getenv("CONFIRM_LIVE_TRADING", "") != "I_UNDERSTAND_THE_RISK":
        log.error("Live trading requested but CONFIRM_LIVE_TRADING is not set to I_UNDERSTAND_THE_RISK")
        sys.exit(1)
    trade = TradingClient(key, secret, paper=PAPER)
    data  = OptionHistoricalDataClient(key, secret)
    return trade, data


# â”€â”€ IV Rank (30-day HV as proxy over 252-day rolling window) â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
def _hv_proxy_iv_rank(symbol: str) -> float:
    ticker = yf.Ticker(symbol)
    hist   = ticker.history(period="1y")
    if len(hist) < 30:
        log.warning(f"Not enough price history for {symbol} â€” defaulting IV Rank to 50")
        return 50.0
    hist["log_ret"] = np.log(hist["Close"] / hist["Close"].shift(1))
    hist["hv30"]    = hist["log_ret"].rolling(21).std() * math.sqrt(252) * 100
    hist            = hist.dropna()
    current         = hist["hv30"].iloc[-1]
    lo, hi          = hist["hv30"].min(), hist["hv30"].max()
    rank            = (current - lo) / (hi - lo) * 100 if hi > lo else 50.0
    log.info(f"IV Rank {symbol}: {rank:.1f}  (HV30={current:.1f}, 52wk range {lo:.1f}-{hi:.1f})")
    return rank


def iv_rank(symbol: str) -> float:
    try:
        from scripts.ivr_scanner import scan_symbol

        scan = scan_symbol(symbol)
        if scan.get("status") == "ok":
            ivr = scan.get("ivr")
            atm_iv = scan.get("current_iv_pct")
            if ivr is not None:
                log.info(
                    f"IVR {symbol}: {float(ivr):.1f} "
                    f"(ATM IV={atm_iv}%, source=alpaca_options_chain)"
                )
                return float(ivr)
            log.info(
                f"IVR {symbol}: accumulating history "
                f"({scan.get('history_days')} readings); falling back to HV proxy"
            )
        else:
            log.warning(f"IVR {symbol}: scanner unavailable ({scan.get('error')}); falling back to HV proxy")
    except Exception as exc:
        log.warning(f"IVR {symbol}: scanner failed ({exc}); falling back to HV proxy")
    return _hv_proxy_iv_rank(symbol)

# â”€â”€ Earnings check â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
def _has_earnings_soon(symbol: str, days: int = EARNINGS_SKIP_DAYS) -> bool:
    """Return True if earnings are within `days` calendar days â€” skip entry if so."""
    try:
        ticker   = yf.Ticker(symbol)
        cal      = ticker.calendar
        if cal is None or cal.empty:
            return False
        # calendar has columns like 'Earnings Date'
        if "Earnings Date" in cal.columns:
            dates = cal["Earnings Date"].dropna()
        elif "Earnings High" in cal.index or "Earnings Low" in cal.index:
            return False
        else:
            return False
        today = date.today()
        for d in dates:
            try:
                earn = d.date() if hasattr(d, "date") else d
                if 0 <= (earn - today).days <= days:
                    log.warning(f"{symbol}: earnings on {earn} ({(earn - today).days}d away) â€” skipping")
                    return True
            except Exception:
                continue
    except Exception as exc:
        log.debug(f"Earnings check failed for {symbol}: {exc}")
    return False


# â”€â”€ Option leg data class â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
@dataclass
class Leg:
    symbol: str    # OCC symbol e.g. IWM260620P00195000
    expiry: date
    strike: float
    right:  str    # "C" or "P"
    delta:  float
    bid:    float
    ask:    float

    @property
    def mid(self) -> float:
        return round((self.bid + self.ask) / 2, 2)


# â”€â”€ Chain fetch â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
def _fetch_chain(
    data_client: OptionHistoricalDataClient,
    symbol: str,
    dte_min: int,
    dte_max: int,
    right: str,  # "call" or "put"
) -> list[Leg]:
    today   = date.today()
    date_lo = today + timedelta(days=dte_min)
    date_hi = today + timedelta(days=dte_max)
    req     = OptionChainRequest(
        underlying_symbol   = symbol,
        expiration_date_gte = date_lo,
        expiration_date_lte = date_hi,
        type                = right,
    )
    try:
        snapshots = data_client.get_option_chain(req)
    except Exception as exc:
        log.error(f"{symbol} chain fetch ({right}, DTE {dte_min}-{dte_max}) failed: {exc}")
        return []

    legs: list[Leg] = []
    sym_len = len(symbol)
    for occ, snap in snapshots.items():
        greeks = getattr(snap, "greeks", None)
        if not greeks:
            continue
        delta = abs(greeks.delta or 0.0)
        quote = snap.latest_quote
        if not quote:
            continue
        try:
            expiry     = datetime.strptime(occ[sym_len:sym_len + 6], "%y%m%d").date()
            right_char = occ[sym_len + 6]
            strike     = int(occ[sym_len + 7:]) / 1000
        except Exception:
            continue
        legs.append(Leg(
            symbol=occ,
            expiry=expiry,
            strike=strike,
            right=right_char,
            delta=delta,
            bid=quote.bid_price or 0.0,
            ask=quote.ask_price or 0.0,
        ))
    return legs


def _closest_delta(legs: list[Leg], target: float) -> Optional[Leg]:
    return min(legs, key=lambda l: abs(l.delta - target)) if legs else None


def _find_wing(legs: list[Leg], anchor: float, width: float, right: str) -> Optional[Leg]:
    target = (anchor - width) if right == "P" else (anchor + width)
    # Search within 1.5 strikes of target to handle non-standard increments
    candidates = [l for l in legs if abs(l.strike - target) < 1.51]
    if not candidates:
        available = sorted(set(l.strike for l in legs))
        log.debug(f"Wing search: anchor={anchor} target={target} available strikes={available[:10]}")
    return min(candidates, key=lambda l: abs(l.strike - target)) if candidates else None


def _dte(expiry: date) -> int:
    return (expiry - date.today()).days


# â”€â”€ Discord alerts â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
def _alert(message: str) -> None:
    webhook = os.getenv("DISCORD_WEBHOOK_URL", "")
    if not webhook:
        return
    try:
        import requests as r
        r.post(webhook, json={
            "content": f"@everyone ðŸ¤– **Options Bot**\n{message}",
            "allowed_mentions": {"parse": ["everyone"]},
        }, timeout=5)
    except Exception as exc:
        log.warning(f"Discord alert failed: {exc}")


# â”€â”€ Put/Call Ratio sentiment filter â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
PCR_MAX = 2.0   # skip if put volume > 2x call volume (panic buying of puts)

def _pcr_ok(symbol: str) -> bool:
    """Return False if options flow is extremely bearish (PCR > PCR_MAX)."""
    try:
        ticker  = yf.Ticker(symbol)
        expiries = ticker.options
        if not expiries:
            return True
        opts     = ticker.option_chain(expiries[0])
        put_vol  = opts.puts["volume"].sum()
        call_vol = opts.calls["volume"].sum()
        if call_vol == 0:
            return True
        pcr = put_vol / call_vol
        log.info(f"{symbol}: PCR={pcr:.2f}  (puts={put_vol:,.0f}  calls={call_vol:,.0f})")
        if pcr > PCR_MAX:
            log.info(f"{symbol}: PCR {pcr:.2f} > {PCR_MAX} â€” heavy put buying, bearish flow â€” skipping")
            return False
        return True
    except Exception as exc:
        log.warning(f"PCR check failed for {symbol}: {exc} â€” proceeding")
        return True


# â”€â”€ VIX macro filter â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
VIX_MIN = 15.0   # below = not enough premium to sell
VIX_MAX = 40.0   # above = market panic, spreads can blow through

# Module-level journal state â€” populated once per run_entries() call, read by IC/PS trade_meta.
_JOURNAL_VIX: float | None = None
_JOURNAL_VIX_TERM_RATIO: float | None = None
_JOURNAL_IV_RANK: dict[str, float] = {}


def _vix_in_range() -> bool:
    global _JOURNAL_VIX, _JOURNAL_VIX_TERM_RATIO
    try:
        context = fetch_vix_term_structure_context()
        if context.get("available") is False:
            raise ValueError(context.get("error", "CBOE VIX/VIX3M unavailable"))
        vix_val = float(context["vix"])
        _JOURNAL_VIX = vix_val
        log.info(f"VIX: {vix_val:.1f}  (range {VIX_MIN}-{VIX_MAX})")
        if vix_val < VIX_MIN:
            log.info(f"VIX {vix_val:.1f} < {VIX_MIN} - insufficient premium environment, skipping entries")
            return False
        if vix_val > VIX_MAX:
            log.info(f"VIX {vix_val:.1f} > {VIX_MAX} - market panic mode, too risky to sell premium")
            return False

        ratio = float(context.get("vix_over_vix3m", 0.0) or 0.0)
        _JOURNAL_VIX_TERM_RATIO = ratio
        regime = "backwardation - skipping" if ratio > 1.0 else "contango - premium OK"
        log.info(
            f"VIX/VIX3M term ratio: {ratio:.3f}  ({regime}) "
            f"source={context.get('source')}"
        )
        if ratio > 1.0:
            return False

        return True
    except Exception as exc:
        log.warning(f"VIX check failed: {exc} - proceeding without filter")
        return True

# â”€â”€ 20-day SMA trend filter â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
def _above_20sma(symbol: str) -> bool:
    """Return True if symbol is above its 20-day SMA (bullish bias = safer for put spreads/CSPs)."""
    try:
        hist  = yf.Ticker(symbol).history(period="35d")
        if len(hist) < 20:
            return True
        sma20 = hist["Close"].rolling(20).mean().iloc[-1]
        price = hist["Close"].iloc[-1]
        above = price > sma20
        log.info(f"{symbol}: price={price:.2f}  20SMA={sma20:.2f}  {'ABOVE âœ“' if above else 'BELOW â€” skip put spread'}")
        return above
    except Exception as exc:
        log.warning(f"SMA check failed for {symbol}: {exc} â€” proceeding")
        return True


# â”€â”€ Market hours check â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
def _market_is_open() -> bool:
    import requests as r
    key    = os.getenv("ALPACA_API_KEY", "")
    secret = os.getenv("ALPACA_SECRET_KEY", "")
    try:
        resp = r.get(
            f"{BASE}/v2/clock",
            headers={"APCA-API-KEY-ID": key, "APCA-API-SECRET-KEY": secret},
            timeout=5,
        )
        resp.raise_for_status()
        data = resp.json()
        is_open   = data.get("is_open", False)
        next_open = data.get("next_open", "unknown")
        next_close = data.get("next_close", "unknown")
        if is_open:
            log.info(f"Market OPEN  (closes {next_close})")
        else:
            log.info(f"Market CLOSED  (opens {next_open})")
        return is_open
    except Exception as exc:
        if FAIL_OPEN_MARKET_CHECK:
            log.warning(f"Clock check failed: {exc} â€” FAIL_OPEN_MARKET_CHECK=true, assuming market open")
            return True
        log.warning(f"Clock check failed: {exc} â€” failing closed, no new entries")
        return False


# â”€â”€ Account helpers â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
def _equity(trade_client: TradingClient) -> float:
    actual_equity = float(trade_client.get_account().equity)
    if ACCOUNT_SIZE_OVERRIDE > 0:
        log.info(
            f"Account equity override active: sizing from ${ACCOUNT_SIZE_OVERRIDE:,.2f} "
            f"instead of broker equity ${actual_equity:,.2f}"
        )
        return ACCOUNT_SIZE_OVERRIDE
    return actual_equity


def _open_option_count(trade_client: TradingClient) -> int:
    return sum(
        1 for p in trade_client.get_all_positions()
        if getattr(p, "asset_class", "") == "us_option"
    )


def _trades_today(trade_client: TradingClient) -> int:
    since = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    orders = trade_client.get_orders(
        GetOrdersRequest(status=QueryOrderStatus.ALL, after=since, limit=50)
    )
    return sum(1 for o in orders if getattr(o, "order_class", "") == "mleg"
               and o.status in ("filled", "partially_filled"))


def _decision(symbol: str, strategy: str, action: str, reason: str, **details) -> None:
    event = {
        "ts": _utc_timestamp(),
        "symbol": symbol,
        "strategy": strategy,
        "action": action,
        "reason": reason,
        "paper": PAPER,
        **details,
    }
    try:
        with open(DECISION_LOG_FILE, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(event, sort_keys=True) + "\n")
    except Exception as exc:
        log.warning(f"Decision log write failed: {exc}")


def _strategy_skip(symbol: str, strategy: str, reason: str, **details) -> None:
    _decision(symbol, strategy, "skip", reason, **details)


def _load_trade_state() -> dict:
    if not TRADE_STATE_FILE.exists():
        return {"trades": []}
    try:
        with TRADE_STATE_FILE.open("r", encoding="utf-8") as fh:
            state = json.load(fh)
        if not isinstance(state, dict) or not isinstance(state.get("trades"), list):
            raise ValueError("bad state shape")
        return state
    except Exception as exc:
        log.error(f"Could not read trade state {TRADE_STATE_FILE}: {exc}")
        return {"trades": []}


def _save_trade_state(state: dict) -> None:
    """Durable-state write: atomic temp+replace under an exclusive lock.

    A crash mid-write can never truncate options-trades.json, and concurrent
    writers (bot run overlapping a monitor run) cannot interleave.
    """
    options_state.atomic_save_json(TRADE_STATE_FILE, state)


def _occ_underlying(symbol: str) -> str:
    match = re.match(r"^([A-Z]+)\d{6}[CP]\d{8}$", str(symbol))
    return match.group(1) if match else str(symbol)


def _order_leg_cashflow(leg: dict) -> float:
    qty = float(leg.get("filled_qty") or leg.get("qty") or 0)
    price = float(leg.get("filled_avg_price") or leg.get("limit_price") or 0)
    cashflow = qty * price * 100
    return cashflow if leg.get("side") == "sell" else -cashflow


def _recent_filled_mleg_orders(days: int = 45) -> list[dict]:
    import requests as r

    key = os.getenv("ALPACA_API_KEY", "")
    secret = os.getenv("ALPACA_SECRET_KEY", "")
    since = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat(timespec="seconds").replace("+00:00", "Z")
    try:
        resp = r.get(
            f"{BASE}/v2/orders",
            headers={"APCA-API-KEY-ID": key, "APCA-API-SECRET-KEY": secret},
            params={"status": "closed", "after": since, "limit": 500, "nested": "true", "direction": "desc"},
            timeout=10,
        )
        resp.raise_for_status()
        orders = resp.json()
    except Exception as exc:
        log.warning(f"Could not fetch recent multi-leg orders for state recovery: {exc}")
        return []

    return [
        order for order in orders
        if order.get("order_class") == "mleg"
        and order.get("status") == "filled"
        and order.get("legs")
    ]


def _order_snapshot(order_id: str) -> Optional[dict]:
    """Fetch one broker order without changing broker state."""
    import requests as r

    key = os.getenv("ALPACA_API_KEY", "")
    secret = os.getenv("ALPACA_SECRET_KEY", "")
    if not order_id or not key or not secret:
        return None
    try:
        resp = r.get(
            f"{BASE}/v2/orders/{order_id}",
            headers={"APCA-API-KEY-ID": key, "APCA-API-SECRET-KEY": secret},
            timeout=10,
        )
        resp.raise_for_status()
        payload = resp.json()
        return payload if isinstance(payload, dict) else None
    except Exception as exc:
        log.warning(f"Could not refresh closing order {order_id}: {exc}")
        return None


def _apply_closing_fill(trade: dict, order: dict) -> bool:
    """Apply broker-confirmed close economics without inventing a P/L estimate."""
    try:
        filled_qty = int(float(order.get("filled_qty") or 0))
        closing_debit = max(0.0, float(order.get("filled_avg_price") or 0.0))
        entry_credit = float(trade.get("net_credit") or 0.0)
    except (TypeError, ValueError):
        return False
    if filled_qty < 1 or entry_credit < 0:
        return False
    trade["closing_filled_avg_price"] = round(closing_debit, 4)
    trade["closing_filled_qty"] = filled_qty
    trade["realized_pnl_dollars"] = round(
        (entry_credit - closing_debit) * filled_qty * 100.0,
        2,
    )
    trade["pnl_source"] = "fill_derived"
    return True


def _refresh_filled_group_closes(state: dict) -> bool:
    """Retire economic groups only after their exact MLEG close is filled."""
    changed = False
    for trade in state.get("trades", []):
        if trade.get("status") != "closing" or not trade.get("closing_order_id"):
            continue
        order = _order_snapshot(str(trade["closing_order_id"]))
        if not order or order.get("status") != "filled":
            continue
        order_legs = [
            str(leg.get("symbol"))
            for leg in (order.get("legs") or [])
            if isinstance(leg, dict) and leg.get("symbol")
        ]
        tracked_legs = [str(symbol) for symbol in (trade.get("legs") or [])]
        try:
            filled_qty = float(order.get("filled_qty") or 0)
            required_qty = float(trade.get("qty") or 1)
        except (TypeError, ValueError):
            continue
        if (
            order.get("order_class") != "mleg"
            or len(order_legs) != len(tracked_legs)
            or set(order_legs) != set(tracked_legs)
            or filled_qty < required_qty
        ):
            log.error(
                f"{trade.get('label', 'trade')}: filled closing order does not exactly "
                "match the tracked group; leaving state closing for manual review"
            )
            continue
        if not _apply_closing_fill(trade, order):
            log.error(
                f"{trade.get('label', 'trade')}: close fill has invalid economics; "
                "leaving state closing for manual review"
            )
            continue
        trade["status"] = "closed"
        trade["closed_at"] = order.get("filled_at") or _utc_timestamp()
        trade["closing_order_status"] = "filled"
        trade["close_verified_by"] = "alpaca_filled_mleg_order"
        _clear_flat_observation(trade)
        log.info(
            f"{trade.get('label', 'trade')}: close order {trade['closing_order_id']} "
            f"filled; economic group marked closed"
        )
        changed = True
    return changed


def _recover_untracked_mleg_groups(trade_client: TradingClient, state: dict) -> bool:
    """Rebuild missing trade groups only when broker orders and positions agree."""
    try:
        positions = [
            p for p in trade_client.get_all_positions()
            if getattr(p, "asset_class", "") == "us_option"
        ]
    except Exception as exc:
        log.warning(f"Could not inspect positions for state recovery: {exc}")
        return False

    open_symbols = {p.symbol for p in positions}
    if not open_symbols:
        return False

    tracked_symbols = {
        symbol
        for trade in state.get("trades", [])
        if trade.get("status") in ("pending", "open", "closing")
        for symbol in trade.get("legs", [])
    }
    untracked_open = open_symbols - tracked_symbols
    if not untracked_open:
        return False

    recovered = False
    known_order_ids = {
        str(order_id)
        for trade in state.get("trades", [])
        for order_id in (trade.get("order_id"), trade.get("closing_order_id"))
        if order_id
    }
    for order in _recent_filled_mleg_orders():
        if str(order.get("id") or order.get("client_order_id")) in known_order_ids:
            continue
        legs = order.get("legs") or []
        leg_symbols = [leg.get("symbol", "") for leg in legs if leg.get("symbol")]
        if not leg_symbols:
            continue
        if not set(leg_symbols).issubset(untracked_open):
            overlap = set(leg_symbols) & untracked_open
            if overlap:
                # Partial match usually means one or more legs net to zero
                # against another group at the broker. Never auto-recover
                # from inference here; surface it for read-only reconciliation.
                log.warning(
                    f"State recovery: filled MLEG order {order.get('id')} matches "
                    f"untracked legs {sorted(overlap)} but not all of "
                    f"{sorted(leg_symbols)}; possible netted legs - run "
                    "scripts/options_position_reconciler.py (read-only)"
                )
            continue

        qty_values = [abs(float(leg.get("filled_qty") or leg.get("qty") or 0)) for leg in legs]
        qty = int(min(qty_values)) if qty_values else 1
        if qty < 1:
            continue

        underlyings = sorted({_occ_underlying(symbol) for symbol in leg_symbols})
        underlying = underlyings[0] if len(underlyings) == 1 else "MULTI"
        net_cashflow = sum(_order_leg_cashflow(leg) for leg in legs)
        net_credit = round(net_cashflow / (100 * qty), 2)
        expiries = []
        for symbol in leg_symbols:
            match = re.match(r"^[A-Z]+(\d{6})[CP]\d{8}$", symbol)
            if match:
                try:
                    expiries.append(datetime.strptime(match.group(1), "%y%m%d").date())
                except ValueError:
                    pass

        trade = {
            "id": f"recovered-{order.get('id') or order.get('client_order_id')}",
            "order_id": order.get("id") or order.get("client_order_id"),
            "status": "open",
            "opened_at": order.get("filled_at") or order.get("submitted_at") or datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
            "recovered_at": datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
            "recovered_from": "alpaca_filled_mleg_order",
            "label": f"Recovered MLEG [{underlying}]",
            "strategy": "recovered_mleg",
            "underlying": underlying,
            "legs": leg_symbols,
            "net_credit": net_credit,
            "qty": qty,
            "profit_close_pct": PS_PROFIT_CLOSE_PCT,
            "stop_loss_pct": STOP_LOSS_PCT,
        }
        if expiries:
            trade["expiry"] = str(min(expiries))
        state.setdefault("trades", []).append(trade)
        tracked_symbols.update(leg_symbols)
        untracked_open -= set(leg_symbols)
        log.warning(
            f"Recovered missing trade group {trade['label']} from Alpaca order "
            f"{trade['order_id']} legs={len(leg_symbols)} credit={net_credit:.2f}"
        )
        recovered = True

    return recovered


def _apply_entry_fill(trade: dict, order: dict) -> bool:
    """Apply broker-confirmed entry economics to one tracked credit group."""
    status = str(order.get("status") or "").lower()
    try:
        filled_qty = float(order.get("filled_qty") or 0)
        signed_fill = float(order.get("filled_avg_price"))
    except (TypeError, ValueError):
        return False
    # Accept broker-reported fill economics whenever contracts actually
    # filled. This includes canceled/expired orders with partial fills, whose
    # exposure is real even though the order is terminal.
    if filled_qty <= 0:
        return False
    # Alpaca reports MLEG credits as negative filled_avg_price. A positive
    # value means the group filled as a net DEBIT; abs() must never turn that
    # into fake credit. Refuse and hold for manual review.
    if signed_fill >= 0:
        log.error(
            f"{trade.get('label', 'trade')}: filled_avg_price={signed_fill} is not a "
            "net credit; refusing to apply credit economics (manual review)"
        )
        trade["entry_fill_review"] = "non_credit_filled_avg_price"
        trade["entry_filled_avg_price_signed"] = signed_fill
        return False

    tracked_legs = {str(symbol) for symbol in (trade.get("legs") or [])}
    order_legs = {
        str(leg.get("symbol"))
        for leg in (order.get("legs") or [])
        if isinstance(leg, dict) and leg.get("symbol")
    }
    if order_legs and tracked_legs and order_legs != tracked_legs:
        log.error(
            f"{trade.get('label', 'trade')}: entry fill legs do not match tracked group; "
            "leaving order pending for manual review"
        )
        return False
    trade["entry_fill_leg_verification"] = (
        "verified" if order_legs and tracked_legs else "unavailable"
    )

    submitted_credit = float(
        trade.get("submitted_limit_credit")
        or trade.get("net_credit")
        or 0.0
    )
    actual_credit = abs(signed_fill)
    trade["submitted_limit_credit"] = submitted_credit
    trade["entry_filled_avg_price"] = actual_credit
    trade["entry_filled_avg_price_signed"] = signed_fill
    trade["entry_fill_source"] = "alpaca_filled_avg_price"
    trade["entry_order_status"] = status
    trade["entry_filled_qty"] = filled_qty
    trade["qty"] = max(1, int(filled_qty))
    trade["net_credit"] = actual_credit
    trade["status"] = "open"
    trade["opened_at"] = order.get("filled_at") or trade.get("opened_at") or _utc_timestamp()

    if trade.get("max_risk_per_contract") is not None and submitted_credit > 0:
        submitted_risk = float(
            trade.get("submitted_max_risk_per_contract")
            or trade["max_risk_per_contract"]
        )
        trade["submitted_max_risk_per_contract"] = submitted_risk
        trade["max_risk_per_contract"] = round(
            submitted_risk + ((submitted_credit - actual_credit) * 100.0),
            2,
        )
    return True


def _refresh_entry_order_fills(state: dict) -> bool:
    """Promote pending entries only when Alpaca reports a real fill."""
    changed = False
    terminal_unfilled = {"canceled", "expired", "rejected", "replaced"}
    for trade in state.get("trades", []):
        entry_status = str(trade.get("entry_order_status") or "").lower()
        if trade.get("status") not in {"pending", "open"}:
            continue
        if (
            trade.get("status") == "open"
            and entry_status in {"filled", "canceled", "expired", "rejected", "replaced"}
            and trade.get("entry_fill_source") == "alpaca_filled_avg_price"
        ):
            # Fill economics already applied and the order can no longer change.
            continue
        order = _order_snapshot(str(trade.get("order_id") or ""))
        if not order:
            continue
        if _apply_entry_fill(trade, order):
            changed = True
            continue
        broker_status = str(order.get("status") or "").lower()
        try:
            filled_qty = float(order.get("filled_qty") or 0)
        except (TypeError, ValueError):
            filled_qty = 0.0
        if broker_status in terminal_unfilled and filled_qty <= 0:
            trade["status"] = "entry_canceled"
            trade["entry_order_status"] = broker_status
            trade["entry_closed_at"] = order.get("canceled_at") or _utc_timestamp()
            changed = True
        elif broker_status and broker_status != entry_status:
            trade["entry_order_status"] = broker_status
            changed = True
    return changed


def _record_trade_group(meta: dict, order: dict) -> None:
    if not meta:
        return
    state = _load_trade_state()
    trade = {
        **meta,
        "id": str(uuid4()),
        "order_id": str(order.get("id") or "?"),
        "status": "pending",
        "submitted_at": order.get("submitted_at") or _utc_timestamp(),
        "entry_order_status": str(order.get("status") or "pending").lower(),
    }
    trade["submitted_limit_credit"] = float(meta.get("net_credit") or 0.0)
    _apply_entry_fill(trade, order)
    state["trades"].append(trade)
    _save_trade_state(state)
    log.info(
        f"Recorded trade group {trade['id']} for {trade.get('label', 'trade')} "
        f"status={trade['status']} credit_source="
        f"{trade.get('entry_fill_source', 'submitted_limit')}"
    )


def _sized_qty(equity: float, max_risk: float, max_qty: int, label: str) -> int:
    if max_risk <= 0:
        log.warning(f"{label}: invalid max risk {max_risk:.2f}, skipping")
        return 0
    risk_budget = equity * MAX_ACCOUNT_RISK_PCT
    qty = int(risk_budget // max_risk)
    if qty < 1:
        log.warning(
            f"{label}: risk ${max_risk:.2f}/contract exceeds per-trade budget "
            f"${risk_budget:.2f} ({MAX_ACCOUNT_RISK_PCT:.1%} of equity), skipping"
        )
        return 0
    return min(max_qty, qty)


def _open_underlying_trade_count(trade_client: TradingClient, underlying: str) -> int:
    state = _load_trade_state()
    tracked = sum(
        1 for trade in state.get("trades", [])
        if trade.get("status") in ("pending", "open", "closing") and trade.get("underlying") == underlying
    )
    try:
        untracked = {
            p.symbol for p in trade_client.get_all_positions()
            if getattr(p, "asset_class", "") == "us_option" and str(p.symbol).startswith(underlying)
        }
    except Exception as exc:
        log.warning(f"{underlying}: could not inspect open option positions for exposure cap: {exc}")
        untracked = set()
    return tracked + (1 if untracked else 0)


def _credit_quality_ok(label: str, net_credit: float, max_risk: float) -> bool:
    if net_credit < MIN_NET_CREDIT:
        log.warning(f"{label}: credit ${net_credit:.2f} below MIN_NET_CREDIT ${MIN_NET_CREDIT:.2f}, skipping")
        return False
    ratio = (net_credit * 100) / max_risk if max_risk else 0
    if ratio < MIN_CREDIT_TO_RISK:
        log.warning(
            f"{label}: credit/risk {ratio:.1%} below minimum {MIN_CREDIT_TO_RISK:.1%}, skipping"
        )
        return False
    return True


def _legs_liquid(label: str, legs: list[Leg]) -> bool:
    for leg in legs:
        spread = leg.ask - leg.bid
        if leg.bid <= 0 or leg.ask <= 0 or leg.mid <= 0:
            log.warning(
                f"{label}: illiquid {leg.symbol} bid={leg.bid:.2f} ask={leg.ask:.2f}, skipping"
            )
            return False
        spread_pct = spread / leg.mid
        if spread_pct > MAX_BID_ASK_PCT:
            log.warning(
                f"{label}: wide market on {leg.symbol} bid={leg.bid:.2f} ask={leg.ask:.2f} "
                f"spread={spread_pct:.1%} > {MAX_BID_ASK_PCT:.1%}, skipping"
            )
            return False
    return True


def _leg_market_snapshot(leg: Leg) -> dict:
    """Persist the entry quote used in a candidate decision for later review."""
    return {
        "symbol": leg.symbol,
        "expiry": str(leg.expiry),
        "strike": leg.strike,
        "right": leg.right,
        "delta": leg.delta,
        "bid": leg.bid,
        "ask": leg.ask,
        "mid": leg.mid,
    }


def _candidate_confidence(
    *,
    strategy: str,
    symbol: str,
    legs: list[Leg],
    net_credit: float,
    max_risk: float,
    dte: int,
    trend_ok: bool = True,
) -> dict:
    score = 5
    reasons: list[str] = []
    ratio = (net_credit * 100) / max_risk if max_risk > 0 else 0.0

    if strategy in ("wheel_csp", "wheel_cc"):
        if ratio >= 0.015:
            score += 2
            reasons.append("strong premium yield")
        elif ratio >= 0.008:
            score += 1
            reasons.append("acceptable premium yield")
        else:
            score -= 2
            reasons.append("premium yield too thin")
    elif ratio >= max(MIN_CREDIT_TO_RISK * 1.5, 0.30):
        score += 2
        reasons.append("strong credit/risk")
    elif ratio >= MIN_CREDIT_TO_RISK:
        score += 1
        reasons.append("acceptable credit/risk")
    else:
        score -= 3
        reasons.append("credit/risk too thin")

    widest_spread_pct = 0.0
    for leg in legs:
        if leg.mid > 0:
            widest_spread_pct = max(widest_spread_pct, (leg.ask - leg.bid) / leg.mid)
    if widest_spread_pct <= MAX_BID_ASK_PCT * 0.5:
        score += 1
        reasons.append("tight option markets")
    elif widest_spread_pct <= MAX_BID_ASK_PCT:
        reasons.append("acceptable option markets")
    else:
        score -= 2
        reasons.append("wide option markets")

    if strategy == "iron_condor":
        if IC_DTE_MIN <= dte <= IC_DTE_MAX:
            score += 1
            reasons.append("DTE in iron-condor window")
        else:
            score -= 1
            reasons.append("DTE outside iron-condor window")
    elif strategy == "put_spread":
        if PS_DTE_MIN <= dte <= PS_DTE_MAX:
            score += 1
            reasons.append("DTE in put-spread window")
        else:
            score -= 1
            reasons.append("DTE outside put-spread window")
        if trend_ok:
            score += 1
            reasons.append("underlying above trend filter")
        else:
            score -= 2
            reasons.append("underlying below trend filter")
    elif strategy in ("wheel_csp", "wheel_cc"):
        if WHEEL_DTE_MIN <= dte <= WHEEL_DTE_MAX:
            score += 1
            reasons.append("DTE in wheel window")
        else:
            score -= 1
            reasons.append("DTE outside wheel window")
        if strategy == "wheel_csp" and trend_ok:
            score += 1
            reasons.append("cash-secured put trend filter passed")
        elif strategy == "wheel_csp":
            score -= 2
            reasons.append("cash-secured put trend filter failed")

    score = max(0, min(10, score))
    allowed = score >= MIN_CANDIDATE_CONFIDENCE
    if not allowed:
        reasons.append(f"confidence {score}/10 below minimum {MIN_CANDIDATE_CONFIDENCE}/10")

    return {
        "allowed": allowed,
        "score": score,
        "minimum": MIN_CANDIDATE_CONFIDENCE,
        "strategy": strategy,
        "symbol": symbol,
        "credit_to_risk": round(ratio, 4),
        "widest_spread_pct": round(widest_spread_pct, 4),
        "dte": dte,
        "reasons": reasons,
    }


def _candidate_confidence_ok(label: str, decision: dict) -> bool:
    details = "; ".join(decision.get("reasons", []))
    log.info(
        f"{label}: confidence={decision.get('score')}/10 "
        f"min={decision.get('minimum')}/10  {details}"
    )
    if decision.get("allowed") is True:
        return True
    _decision(
        str(decision.get("symbol", "")),
        str(decision.get("strategy", "")),
        "skip",
        "candidate_confidence_below_minimum",
        candidate_confidence=decision,
    )
    return False


def _daily_loss_guard(trade_client: TradingClient, sizing_equity: float) -> bool:
    today_key = date.today().isoformat()
    actual_equity = float(trade_client.get_account().equity)
    state = _load_trade_state()
    daily = state.setdefault("daily_risk", {})

    if daily.get("date") != today_key:
        daily.clear()
        daily.update({
            "date": today_key,
            "start_equity": actual_equity,
            "kill_switch_triggered": False,
        })
        _save_trade_state(state)

    start_equity = float(daily.get("start_equity", actual_equity))
    loss_pct = (start_equity - actual_equity) / start_equity if start_equity else 0
    log.info(
        f"Daily risk: start=${start_equity:,.2f} actual=${actual_equity:,.2f} "
        f"loss={loss_pct:.2%} limit={MAX_DAILY_LOSS_PCT:.2%}"
    )

    if loss_pct < MAX_DAILY_LOSS_PCT:
        return True

    if not daily.get("kill_switch_triggered"):
        daily["kill_switch_triggered"] = True
        daily["triggered_at"] = _utc_timestamp()
        daily["trigger_equity"] = actual_equity
        daily["sizing_equity"] = sizing_equity
        _save_trade_state(state)
        _alert(
            f"DAILY LOSS KILL SWITCH\nloss={loss_pct:.2%} "
            f"limit={MAX_DAILY_LOSS_PCT:.2%}; new entries disabled"
        )

    if CLOSE_ON_DAILY_LOSS:
        log.warning("CLOSE_ON_DAILY_LOSS=true; attempting to close tracked option groups")
        for trade in state.get("trades", []):
            if trade.get("status") == "open":
                _close_trade_group(trade_client, trade, "daily loss kill switch")

    log.warning("Daily loss limit reached; skipping all new entries")
    return False


def _record_wheel_assignment(symbol: str, shares: int) -> None:
    state = _load_trade_state()
    wheel = state.setdefault("wheel", {})
    current = wheel.get(symbol, {})
    today_key = date.today().isoformat()
    if current.get("shares") == shares and current.get("detected_date") == today_key:
        return
    wheel[symbol] = {
        "phase": "covered_call",
        "shares": shares,
        "detected_date": today_key,
        "detected_at": _utc_timestamp(),
    }
    _save_trade_state(state)
    log.warning(f"Wheel [{symbol}]: detected {shares} shares; phase is now covered_call")
    _alert(f"WHEEL ASSIGNMENT DETECTED: **{symbol}**\nshares={shares}; switching to covered-call phase")


def _record_wheel_cash_secured_phase(symbol: str) -> None:
    state = _load_trade_state()
    wheel = state.setdefault("wheel", {})
    current = wheel.get(symbol, {})
    if current.get("phase") == "cash_secured_put" and current.get("shares", 0) == 0:
        return
    wheel[symbol] = {
        "phase": "cash_secured_put",
        "shares": 0,
        "detected_at": _utc_timestamp(),
    }
    _save_trade_state(state)


def _latest_option_quotes(
    data_client: OptionHistoricalDataClient,
    symbols: list[str],
) -> dict[str, dict]:
    """Fetch one coherent latest-quote set for an economic option group."""
    if not symbols:
        return {}
    try:
        request = OptionLatestQuoteRequest(symbol_or_symbols=sorted(set(symbols)))
        payload = data_client.get_option_latest_quote(request)
    except Exception as exc:
        log.error(f"Option group quote fetch failed for {symbols}: {exc}")
        return {}
    quotes: dict[str, dict] = {}
    for symbol, quote in (payload or {}).items():
        quotes[str(symbol)] = {
            "bid": float(getattr(quote, "bid_price", 0.0) or 0.0),
            "ask": float(getattr(quote, "ask_price", 0.0) or 0.0),
            "timestamp": str(getattr(quote, "timestamp", "") or ""),
        }
    return quotes


def _quote_mark_is_fresh(mark: dict, max_age_seconds: int = 300) -> bool:
    if not isinstance(mark, dict) or mark.get("status") != "ok":
        return False
    try:
        marked_at = datetime.fromisoformat(str(mark["marked_at"]).replace("Z", "+00:00"))
    except (KeyError, TypeError, ValueError):
        return False
    return (datetime.now(timezone.utc) - marked_at).total_seconds() <= max_age_seconds


def _close_trade_group(trade_client: TradingClient, trade: dict, reason: str) -> bool:
    legs = trade.get("legs", [])
    if not legs:
        log.error(f"{trade.get('label', 'trade')}: no legs in state; cannot close")
        return False

    mark = trade.get("quote_mark") if isinstance(trade.get("quote_mark"), dict) else {}
    netted_legs = mark.get("netted_legs") if isinstance(mark, dict) else []
    if len(legs) >= 2 and _quote_mark_is_fresh(mark):
        close_plan = mark.get("close_plan") if isinstance(mark.get("close_plan"), dict) else {}
        if netted_legs:
            if close_plan.get("status") != "ok":
                log.error(
                    f"{trade.get('label', 'trade')}: netted close plan unavailable "
                    f"reason={close_plan.get('reason', 'missing_plan')}; refusing exit"
                )
                return False
            if sorted(close_plan.get("transition_legs") or []) != sorted(netted_legs):
                log.error(
                    f"{trade.get('label', 'trade')}: netted close plan does not match "
                    "the reconciled netted legs; refusing exit"
                )
                return False
            close_legs = [
                {
                    "symbol": leg["symbol"],
                    "side": leg["side"],
                    "ratio_qty": str(leg["ratio_qty"]),
                    "position_intent": leg["position_intent"],
                }
                for leg in close_plan.get("legs", [])
                if leg.get("position_intent") in {
                    "buy_to_open", "buy_to_close", "sell_to_open", "sell_to_close",
                }
            ]
        else:
            close_legs = [
                {
                    "symbol": leg["symbol"],
                    "side": leg["close_side"],
                    "ratio_qty": str(int(leg.get("ratio_qty") or 1)),
                    "position_intent": f"{leg['close_side']}_to_close",
                }
                for leg in mark.get("legs", [])
                if leg.get("symbol") and leg.get("close_side") in {"buy", "sell"}
            ]
        if len(close_legs) != len(legs):
            log.error(f"{trade.get('label', 'trade')}: incomplete quote-mark close legs; refusing exit")
            return False
        natural_debit = float(mark.get("natural_close_debit") or 0.0)
        net_credit = float(trade.get("net_credit") or 0.0)
        max_risk = float(trade.get("max_risk_per_contract") or 0.0)
        max_debit = (max_risk / 100.0) + net_credit if max_risk > 0 else natural_debit
        limit_debit = max(0.01, min(natural_debit, max_debit))
        body = {
            "type": "limit",
            "limit_price": str(round(limit_debit, 2)),
            "time_in_force": "day",
            "order_class": "mleg",
            "qty": str(max(1, int(trade.get("qty") or 1))),
            "client_order_id": f"vibe-close-{str(trade.get('id') or 'group')[:8]}-{int(time.time())}",
            "legs": close_legs,
        }
        order = _post_order_with_retry(
            body,
            f"{trade.get('label', 'trade')} group close",
            risk_reducing_close=True,
        )
        if not order:
            return False
        trade["closing_order_id"] = order.get("id") or order.get("client_order_id")
        trade["closing_limit_debit"] = round(limit_debit, 2)
        trade["closing_order_class"] = "mleg"
        log.info(
            f"{trade.get('label', 'trade')}: reversed MLEG close submitted "
            f"order={trade['closing_order_id']} debit={limit_debit:.2f}"
        )
        _alert(
            f"GROUP EXIT submitted: **{trade.get('label', 'trade')}**\n"
            f"reason={reason}\nMLEG debit limit=${limit_debit:.2f}"
        )
        return True

    if netted_legs:
        log.error(
            f"{trade.get('label', 'trade')}: netted legs {netted_legs} require a fresh "
            "all-leg quote mark; refusing symbol-by-symbol close"
        )
        return False

    ok = True
    for symbol in legs:
        try:
            trade_client.close_position(symbol)
            log.info(f"{trade.get('label', 'trade')}: close submitted for {symbol}")
        except Exception as exc:
            ok = False
            log.error(f"{trade.get('label', 'trade')}: close failed for {symbol}: {exc}")
    if ok:
        _alert(f"GROUP EXIT submitted: **{trade.get('label', 'trade')}**\nreason={reason}")
    return ok


def _can_submit_option_close_orders() -> bool:
    """Return True only when Alpaca will accept option close orders."""
    return _market_is_open()


# â”€â”€ Multi-leg order submission via raw REST â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
def _trade_stop_loss_pct(trade: dict) -> float:
    raw_stop = float(trade.get("stop_loss_pct", STOP_LOSS_PCT))
    if str(trade.get("strategy", "")).startswith("recovered") and raw_stop < STOP_LOSS_PCT:
        return STOP_LOSS_PCT
    return raw_stop


FLAT_CONFIRM_MIN_SECONDS = int(os.getenv("OPTIONS_FLAT_CONFIRM_MIN_SECONDS", "600"))


def _confirm_flat_trade(trade: dict, now: datetime | None = None) -> bool:
    """Require two flat observations separated by real time before closing state.

    Two transient empty broker responses seconds apart (API glitch, retry
    burst) must not be able to advance durable state. The 2026-07-07 incident
    was a single flat snapshot closing every tracked group at 09:45:03.
    """
    now = now or datetime.now(timezone.utc)
    now_txt = now.isoformat(timespec="seconds").replace("+00:00", "Z")
    observations = int(trade.get("flat_observation_count") or 0) + 1
    trade["flat_observation_count"] = observations
    trade["flat_observed_at"] = now_txt
    first_txt = trade.get("flat_first_observed_at")
    if not first_txt:
        trade["flat_first_observed_at"] = now_txt
        return False
    if observations < 2:
        return False
    try:
        first_dt = datetime.fromisoformat(str(first_txt).replace("Z", "+00:00"))
    except ValueError:
        # Unparseable clock evidence: restart the confirmation window.
        trade["flat_first_observed_at"] = now_txt
        trade["flat_observation_count"] = 1
        return False
    if (now - first_dt).total_seconds() < FLAT_CONFIRM_MIN_SECONDS:
        return False
    trade["status"] = "closed"
    trade["closed_at"] = now_txt
    trade.pop("flat_observation_count", None)
    trade.pop("flat_observed_at", None)
    trade.pop("flat_first_observed_at", None)
    return True


def _clear_flat_observation(trade: dict) -> bool:
    changed = False
    for key in ("flat_observation_count", "flat_observed_at", "flat_first_observed_at"):
        if key in trade:
            trade.pop(key, None)
            changed = True
    return changed


def _post_order_with_retry(
    body: dict,
    label: str,
    *,
    risk_reducing_close: bool = False,
) -> Optional[dict]:
    import requests as r

    if manual_reset_required() and not risk_reducing_close:
        msg = f"{label}: MANUAL RESET REQUIRED - order blocked by {DEFAULT_BLOCK_FILE}"
        log.error(msg)
        _alert(f"ORDER BLOCKED: **{label}**\nManual reset required before any new orders.")
        return None

    key = os.getenv("ALPACA_API_KEY", "")
    secret = os.getenv("ALPACA_SECRET_KEY", "")
    last_error = ""

    for attempt in range(1, ORDER_RETRY_ATTEMPTS + 1):
        try:
            resp = r.post(
                f"{BASE}/v2/orders",
                json=body,
                headers={"APCA-API-KEY-ID": key, "APCA-API-SECRET-KEY": secret},
                timeout=10,
            )
            if resp.status_code in RETRY_STATUS_CODES and attempt < ORDER_RETRY_ATTEMPTS:
                delay = ORDER_RETRY_BASE_SECONDS * (2 ** (attempt - 1))
                log.warning(
                    f"{label}: Alpaca order attempt {attempt}/{ORDER_RETRY_ATTEMPTS} "
                    f"returned {resp.status_code}; retrying in {delay:.1f}s"
                )
                time.sleep(delay)
                continue
            if not resp.ok:
                response_detail = (resp.text or "").strip().replace("\n", " ")[:1000]
                log.error(
                    f"{label}: Alpaca returned {resp.status_code}: "
                    f"{response_detail or '<empty response>'}"
                )
            resp.raise_for_status()
            if attempt > 1:
                log.info(f"{label}: Alpaca order succeeded after {attempt} attempts")
            return resp.json()
        except Exception as exc:
            last_error = str(exc)
            if attempt < ORDER_RETRY_ATTEMPTS:
                delay = ORDER_RETRY_BASE_SECONDS * (2 ** (attempt - 1))
                log.warning(
                    f"{label}: Alpaca order attempt {attempt}/{ORDER_RETRY_ATTEMPTS} "
                    f"failed: {exc}; retrying in {delay:.1f}s"
                )
                time.sleep(delay)
            else:
                break

    log.error(f"{label}: submission failed after {ORDER_RETRY_ATTEMPTS} attempt(s): {last_error}")
    _alert(f"ORDER SUBMISSION FAILED: **{label}**\nafter {ORDER_RETRY_ATTEMPTS} attempts\n{last_error}")
    return None


def _confidence_score(meta: Optional[dict]) -> float | None:
    candidate = (meta or {}).get("candidate_confidence")
    if isinstance(candidate, dict):
        value = candidate.get("score")
    else:
        value = candidate
    return float(value) if value is not None else None


def _broker_open_underlying_symbols() -> set[str]:
    """Fetch open positions from Alpaca broker and return underlying tickers (truth source)."""
    try:
        import requests as r
        key = os.getenv("ALPACA_API_KEY", "")
        secret = os.getenv("ALPACA_SECRET_KEY", "")
        if not key or not secret:
            return set()
        hdrs = {"APCA-API-KEY-ID": key, "APCA-API-SECRET-KEY": secret}
        resp = r.get(f"{BASE}/v2/positions", headers=hdrs, timeout=10)
        if resp.status_code == 200:
            positions = resp.json()
            if isinstance(positions, list):
                syms: set[str] = set()
                for pos in positions:
                    sym = str(pos.get("symbol", ""))
                    for i, ch in enumerate(sym):
                        if ch.isdigit():
                            syms.add(sym[:i])
                            break
                    else:
                        if sym:
                            syms.add(sym)
                syms.discard("")
                log.debug(f"Broker open underlying symbols: {sorted(syms)}")
                return syms
    except Exception as exc:
        log.warning(f"Broker positions fetch failed: {exc}")
    return set()


def _guard_submission(label: str, qty: int, trade_meta: Optional[dict]) -> bool:
    meta = trade_meta or {}
    estimated_risk = float(meta.get("max_risk_per_contract", 0.0) or 0.0) * qty
    if estimated_risk <= 0:
        estimated_risk = abs(float(meta.get("net_credit", 0.0) or 0.0)) * qty * 100
    broker_symbols = _broker_open_underlying_symbols()
    decision = evaluate_execution(
        bot="options",
        symbol=str(meta.get("underlying") or label),
        action="entry",
        paper=PAPER,
        live_enabled=LIVE_EXECUTION_ENABLED,
        confidence=_confidence_score(meta),
        estimated_notional=estimated_risk,
        max_notional=float("inf"),
        contracts=qty,
        max_contracts=MAX_CONTRACTS_PER_ORDER,
        block_file=DEFAULT_BLOCK_FILE,
        open_symbols=broker_symbols,
    )
    if decision.allowed:
        return True
    log.warning(f"{label}: EXECUTION BLOCKED reason={decision.reason} details={decision.details}")
    _alert(f"ORDER BLOCKED: **{label}**\nreason={decision.reason}")
    return False


def _place_mleg(
    legs_payload: list[dict],
    limit_price: float,
    qty: int,
    label: str,
    trade_meta: Optional[dict] = None,
) -> bool:
    trade_meta = dict(trade_meta or {})
    underlying = str(trade_meta.get("underlying") or label)
    qty, garch_meta, garch_allowed = _garch_entry_adjustment(underlying, qty)
    trade_meta["garch_volatility_risk"] = garch_meta
    trade_meta["qty"] = qty
    if not garch_allowed:
        strategy = str(trade_meta.get("strategy") or "mleg")
        _decision(underlying, strategy, "skip", garch_meta["reason"], garch_volatility_risk=garch_meta)
        log.warning(f"{label}: GARCH ENTRY BLOCKED {underlying}: {garch_meta['reason']}")
        _alert(f"GARCH ENTRY BLOCKED: **{label}**\nreason={garch_meta['reason']}")
        return False
    consensus = shadow_entry_advice(underlying, qty)
    if consensus.get("enabled"):
        warning_list = sorted(
            {str(item) for item in (consensus.get("blockers") or []) if str(item)}
        )
        blockers = ", ".join(warning_list) or consensus.get("recommendation", "needs_review")
        if not consensus.get("allowed"):
            log.warning(f"{label}: SHADOW CONSENSUS BLOCKED {underlying}: {blockers}")
            _alert(f"SHADOW CONSENSUS BLOCKED: **{label}**\nreason={blockers}")
            return False
        bot_assist = (consensus.get("decision") or {}).get("bot_assist") or {}
        if bot_assist.get("options_bot") is False:
            strategy = str(trade_meta.get("strategy") or "mleg")
            _decision(
                underlying,
                strategy,
                "skip",
                "shadow_options_assist_disabled",
                blockers=warning_list,
                candidate_confidence=trade_meta.get("candidate_confidence"),
            )
            log.warning(f"{label}: SHADOW OPTIONS ASSIST DISABLED {underlying}: {blockers}")
            _alert(f"SHADOW OPTIONS ASSIST DISABLED: **{label}**\nreason={blockers}")
            return False
        if str(consensus.get("recommendation") or "").lower() == "stand_aside":
            strategy = str(trade_meta.get("strategy") or "mleg")
            _decision(
                underlying,
                strategy,
                "skip",
                "shadow_consensus_stand_aside",
                blockers=warning_list,
                warning_count=len(warning_list),
                recommendation=consensus.get("recommendation"),
                options_playbook=consensus.get("options_playbook"),
                candidate_confidence=trade_meta.get("candidate_confidence"),
            )
            log.warning(
                f"{label}: SHADOW CONSENSUS STAND ASIDE {underlying}: {blockers}"
            )
            _alert(
                f"SHADOW CONSENSUS STAND ASIDE: **{label}**\n"
                f"warnings={len(warning_list)} reason={blockers}"
            )
            return False
        adjusted_qty = int(consensus.get("adjusted_contracts", qty) or 0)
        if 0 < adjusted_qty < qty:
            log.info(
                f"{label}: SHADOW CONSENSUS SIZE DOWN {underlying}: "
                f"{qty} -> {adjusted_qty} recommendation={consensus.get('recommendation')}"
            )
            _alert(f"SHADOW CONSENSUS SIZE DOWN: **{label}**\nqty {qty} -> {adjusted_qty}")
            qty = adjusted_qty
        trade_meta["qty"] = qty
        trade_meta["shadow_consensus"] = {
            "recommendation": consensus.get("recommendation"),
            "options_playbook": consensus.get("options_playbook"),
            "blockers": consensus.get("blockers", []),
            "reasons": consensus.get("reasons", []),
        }
    # Durable per-leg intent (side + ratio) so reconciliation can build a
    # signed book later. Symbol lists alone cannot see opposite-side netting.
    trade_meta["leg_details"] = [
        {
            "symbol": str(leg.get("symbol")),
            "side": str(leg.get("side", "")).lower(),
            "ratio_qty": int(leg.get("ratio_qty") or 1),
        }
        for leg in legs_payload
        if leg.get("symbol")
    ]
    if not _guard_submission(label, qty, trade_meta):
        return False
    if REQUIRE_MANUAL_APPROVAL:
        log.warning(
            f"{label}: manual approval required; candidate NOT submitted "
            f"credit={limit_price:.2f} qty={qty}"
        )
        _alert(f"MANUAL APPROVAL REQUIRED: **{label}**\ncredit=${limit_price:.2f} qty={qty}")
        return False
    body   = {
        "type":          "limit",
        "limit_price":   str(round(limit_price, 2)),
        "time_in_force": "day",
        "order_class":   "mleg",
        "qty":           str(qty),
        "legs":          legs_payload,
    }
    order = _post_order_with_retry(body, label)
    if not order:
        return False
    oid = order.get("id", "?")
    log.info(f"{label}: submitted  order_id={oid}  credit={limit_price:.2f}  qty={qty}")
    _alert(f"ðŸ“¥ **{label}** submitted\ncredit=${limit_price:.2f}  qty={qty}  order={oid}")
    _record_trade_group(trade_meta or {}, order)
    return True


# â”€â”€ Profit-close monitor â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
def monitor_and_close(
    trade_client: TradingClient,
    data_client: OptionHistoricalDataClient | None = None,
) -> bool:
    """Monitor exits and return whether broker/state integrity permits entries."""
    positions = [
        p for p in trade_client.get_all_positions()
        if getattr(p, "asset_class", "") == "us_option"
    ]
    state = _load_trade_state()
    state_changed = _refresh_entry_order_fills(state)
    state_changed = _refresh_filled_group_closes(state) or state_changed
    if not positions:
        pending = [
            trade for trade in state.get("trades", [])
            if trade.get("status") == "pending"
        ]
        if pending:
            if state_changed:
                _save_trade_state(state)
            log.warning(
                f"{len(pending)} option entry order(s) remain pending; "
                "new entries blocked until broker status resolves"
            )
            return False
        active = [
            trade for trade in state.get("trades", [])
            if trade.get("status") in ("open", "closing")
        ]
        if active:
            confirmed = 0
            for trade in active:
                if _confirm_flat_trade(trade):
                    confirmed += 1
            _save_trade_state(state)
            if confirmed == len(active):
                log.info("No option positions confirmed twice; marked tracked groups closed")
                return True
            log.warning(
                "Broker returned no option positions while tracked groups remain; "
                "entry blocked until a later flat snapshot confirms broker state"
            )
            return False
        log.info("No open option positions to monitor")
        if state_changed:
            _save_trade_state(state)
        return True
    log.info(f"Monitoring {len(positions)} option position(s)...")
    position_by_symbol = {p.symbol: p for p in positions}
    state_changed = _recover_untracked_mleg_groups(trade_client, state) or state_changed
    monitored_symbols: set[str] = set()
    integrity_ok = True
    reconciliation: dict = {"group_states": {}}

    # Quantity/direction-aware reconciliation (read-only). Symbol-set checks
    # cannot see two groups netting the same OCC contract to zero, or a
    # closed-state group whose legs are still open at the broker.
    try:
        reconciliation = options_state.reconcile(
            state.get("trades", []),
            [{"symbol": p.symbol, "qty": float(p.qty)} for p in positions],
        )
        for finding in reconciliation.get("findings", []):
            log.warning(f"POSITION INTEGRITY: {finding}")
        if not reconciliation.get("entries_allowed", False):
            integrity_ok = False
    except Exception as exc:
        # Fail closed: if we cannot prove integrity, do not allow entries.
        log.error(f"POSITION INTEGRITY: reconciliation failed: {exc}")
        integrity_ok = False

    for trade in state.get("trades", []):
        if trade.get("status") not in ("open", "closing"):
            continue
        legs = trade.get("legs", [])
        monitored_symbols.update(legs)
        found = [position_by_symbol[s] for s in legs if s in position_by_symbol]
        missing = [s for s in legs if s not in position_by_symbol]
        trade_id = str(trade.get("id") or trade.get("label") or "?")
        group_state = (reconciliation.get("group_states") or {}).get(trade_id, {})
        netted_missing = set(group_state.get("legs_netted") or [])
        quote_mark_allowed = bool(
            missing
            and set(missing).issubset(netted_missing)
            and data_client is not None
        )

        if not found and not quote_mark_allowed:
            if _confirm_flat_trade(trade):
                log.info(
                    f"{trade.get('label', 'trade')}: no legs remain open on two snapshots; "
                    "marking closed"
                )
            else:
                log.warning(
                    f"{trade.get('label', 'trade')}: no tracked legs found on first snapshot; "
                    "entry blocked pending confirmation"
                )
                integrity_ok = False
            state_changed = True
            continue
        if _clear_flat_observation(trade):
            state_changed = True
        if missing and not quote_mark_allowed:
            log.warning(
                f"{trade.get('label', 'trade')}: missing tracked legs {missing}; "
                "manual review required before auto-close"
            )
            integrity_ok = False
            continue

        try:
            credit_received = float(trade.get("net_credit", 0)) * 100 * int(trade.get("qty", 1))
            mark_source = "broker_positions"
            if quote_mark_allowed:
                quotes = _latest_option_quotes(data_client, list(legs))
                quote_mark = options_state.quote_mark(trade, quotes)
                quote_mark["netted_legs"] = sorted(netted_missing)
                quote_mark["close_plan"] = options_state.close_transition_plan(
                    trade,
                    state.get("trades", []),
                    [{"symbol": p.symbol, "qty": float(p.qty)} for p in positions],
                )
                trade["quote_mark"] = quote_mark
                state_changed = True
                if quote_mark.get("status") != "ok" or credit_received <= 0:
                    log.warning(
                        f"{trade.get('label', 'trade')}: netted group quote mark unavailable "
                        f"reason={quote_mark.get('reason', 'credit_basis_missing')} "
                        f"missing={quote_mark.get('missing_quotes', [])}; auto-close remains blocked"
                    )
                    integrity_ok = False
                    continue
                if quote_mark["close_plan"].get("status") != "ok":
                    log.warning(
                        f"{trade.get('label', 'trade')}: signed-book close plan unavailable "
                        f"reason={quote_mark['close_plan'].get('reason', 'unknown')}; "
                        "auto-close remains blocked"
                    )
                    integrity_ok = False
                pnl = float(quote_mark["pnl_dollars"])
                pnl_pct = float(quote_mark["pnl_pct_of_credit"])
                basis_src = "credit"
                mark_source = "all_leg_quotes"
            else:
                pnl = sum(float(p.unrealized_pl) for p in found)

                # Fallback when net_credit was 0/missing (recovered trades, fill-data gaps).
                # Use cost basis from position data so stop loss always has a denominator.
                if credit_received <= 0:
                    cost_basis = sum(
                        abs(float(p.avg_entry_price)) * abs(float(p.qty)) * 100
                        for p in found
                    )
                    pnl_pct = pnl / cost_basis if cost_basis else 0.0
                    basis_src = "cost_basis"
                else:
                    pnl_pct = pnl / credit_received
                    basis_src = "credit"

            if basis_src == "credit":
                old_best = float(trade.get("best_pnl_pct", pnl_pct))
                best_pnl_pct = max(old_best, pnl_pct)
                if best_pnl_pct != trade.get("best_pnl_pct"):
                    trade["best_pnl_pct"] = round(best_pnl_pct, 4)
                    state_changed = True

            log.info(
                f"  {trade.get('label', 'trade'):<28} legs={len(legs) if quote_mark_allowed else len(found)} "
                f"credit=${credit_received:.2f} P&L={pnl:+.2f} "
                f"({pnl_pct:+.1%} of {basis_src}, source={mark_source})"
            )
            reason = ""
            consensus_exit = shadow_exit_advice(str(trade.get("underlying") or ""), None)
            if consensus_exit.get("enabled") and consensus_exit.get("action") == "review_exit":
                exit_key = "|".join(
                    [
                        str(consensus_exit.get("recommendation", "")),
                        str(consensus_exit.get("options_playbook", "")),
                        ",".join(consensus_exit.get("blockers") or []),
                    ]
                )
                trade["shadow_exit_advice"] = {
                    "action": consensus_exit.get("action"),
                    "recommendation": consensus_exit.get("recommendation"),
                    "options_playbook": consensus_exit.get("options_playbook"),
                    "blockers": consensus_exit.get("blockers", []),
                    "reasons": consensus_exit.get("reasons", []),
                    "can_submit_orders": False,
                }
                if trade.get("shadow_exit_advice_key") != exit_key:
                    trade["shadow_exit_advice_key"] = exit_key
                    state_changed = True
                    blockers = ", ".join(consensus_exit.get("blockers") or []) or "shadow regime review"
                    log.warning(f"{trade.get('label', 'trade')}: SHADOW EXIT REVIEW {blockers}")
                    _alert(
                        f"SHADOW EXIT REVIEW: **{trade.get('label', 'trade')}**\n"
                        f"reason={blockers}\n"
                        "No shadow auto-close submitted."
                    )
            reason = _credit_near_target_reason(trade, pnl_pct, basis_src)
            if not reason:
                reason = _shadow_defensive_exit_reason(trade, consensus_exit, pnl_pct, basis_src)
            if not reason and pnl_pct <= _trade_stop_loss_pct(trade):
                reason = f"stop loss hit: {pnl_pct:+.1%} of {basis_src}"
            if not reason:
                expiry_text = trade.get("expiry")
                if expiry_text:
                    dte = (datetime.strptime(expiry_text, "%Y-%m-%d").date() - date.today()).days
                    strategy_name = trade.get("strategy", "")
                    if strategy_name == "iron_condor" and dte <= IC_DTE_MANAGE_DAYS:
                        reason = f"time exit: iron condor reached {dte} DTE"
                    elif strategy_name == "put_spread" and dte <= PS_DTE_MANAGE_DAYS:
                        reason = f"time exit: put spread reached {dte} DTE"

            if reason:
                if AUTO_CLOSE_GROUPS:
                    if not _can_submit_option_close_orders():
                        already_pending = trade.get("exit_pending_reason") == reason
                        trade["exit_pending_reason"] = reason
                        trade["exit_pending_at"] = _utc_timestamp()
                        state_changed = True
                        log.warning(
                            f"  -> {reason}; option market closed, exit marked pending for "
                            f"{trade.get('label', 'trade')}"
                        )
                        if not already_pending:
                            _alert(
                                f"EXIT PENDING: **{trade.get('label', 'trade')}**\n"
                                f"{reason}\nOption market is closed; monitor will retry next market session."
                            )
                        continue
                    log.info(f"  -> {reason}; closing all tracked legs for {trade.get('label', 'trade')}")
                    if _close_trade_group(trade_client, trade, reason):
                        trade["status"] = "closing"
                        trade["closing_reason"] = reason
                        trade["closing_started_at"] = _utc_timestamp()
                        state_changed = True
                else:
                    log.warning(f"  -> {reason}; AUTO_CLOSE_GROUPS=false, alerting only")
                    _alert(f"EXIT SIGNAL: **{trade.get('label', 'trade')}**\n{reason}\nAUTO_CLOSE_GROUPS=false")
            elif trade.get("exit_pending_reason") or trade.get("exit_pending_at"):
                log.info(
                    f"{trade.get('label', 'trade')}: clearing stale pending exit; "
                    f"current P&L no longer triggers an exit"
                )
                trade.pop("exit_pending_reason", None)
                trade.pop("exit_pending_at", None)
                state_changed = True
        except Exception as exc:
            log.error(f"  Error monitoring {trade.get('label', 'trade')}: {exc}")

    legacy = [p for p in positions if p.symbol not in monitored_symbols]
    if legacy:
        integrity_ok = False
    for pos in legacy:
        try:
            log.warning(
                f"  UNTRACKED {pos.symbol:<35} qty={pos.qty:>4} "
                f"P&L={float(pos.unrealized_pl):+.2f}; no leg-by-leg auto-close"
            )
        except Exception as exc:
            log.error(f"  Error logging legacy position {pos.symbol}: {exc}")

    if state_changed:
        _save_trade_state(state)
    # Safety bypass: old per-leg auto-close code remains below, but must not run for spreads/condors.
    return integrity_ok
    for pos in positions:
        try:
            cost_basis = abs(float(pos.avg_entry_price)) * abs(float(pos.qty)) * 100
            pnl        = float(pos.unrealized_pl)
            pnl_pct    = pnl / cost_basis if cost_basis else 0
            log.info(f"  {pos.symbol:<35} qty={pos.qty:>4}  "
                     f"entry={float(pos.avg_entry_price):.2f}  "
                     f"P&L={pnl:+.2f} ({pnl_pct:+.1%})")
            if pnl_pct >= PS_PROFIT_CLOSE_PCT:
                log.info(f"  â†’ PROFIT TARGET HIT â€” closing {pos.symbol}")
                trade_client.close_position(pos.symbol)
                _alert(f"âœ… **PROFIT TARGET** hit on `{pos.symbol}`\nP&L={pnl:+.2f} ({pnl_pct:+.1%})")
            elif pnl_pct <= STOP_LOSS_PCT:
                log.info(f"  â†’ STOP LOSS HIT â€” closing {pos.symbol}")
                trade_client.close_position(pos.symbol)
                _alert(f"ðŸ›‘ **STOP LOSS** hit on `{pos.symbol}`\nP&L={pnl:+.2f} ({pnl_pct:+.1%})")
        except Exception as exc:
            log.error(f"  Error monitoring {pos.symbol}: {exc}")


# â”€â”€ Strategy: Iron Condor â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
def run_iron_condor(
    trade_client: TradingClient,
    data_client: OptionHistoricalDataClient,
    symbol: str,
    equity: float,
) -> bool:
    log.info(f"--- Iron Condor scan [{symbol}] ---")
    puts  = _fetch_chain(data_client, symbol, IC_DTE_MIN, IC_DTE_MAX, "put")
    calls = _fetch_chain(data_client, symbol, IC_DTE_MIN, IC_DTE_MAX, "call")
    if not puts or not calls:
        log.warning(f"IC [{symbol}]: no chain data")
        return False

    short_put = _closest_delta(puts, IC_DELTA_TARGET)
    if not short_put:
        log.warning(f"IC [{symbol}]: could not find 16-delta put")
        return False

    # Fix: filter calls to same expiry as short_put before finding short_call
    same_exp_calls = [l for l in calls if l.expiry == short_put.expiry]
    short_call = _closest_delta(same_exp_calls, IC_DELTA_TARGET)
    if not short_call:
        log.warning(f"IC [{symbol}]: could not find 16-delta call on expiry {short_put.expiry}")
        return False

    log.info(f"IC [{symbol}]: short put  strike={short_put.strike}  delta={short_put.delta:.3f}  mid={short_put.mid:.2f}  expiry={short_put.expiry}")
    log.info(f"IC [{symbol}]: short call strike={short_call.strike}  delta={short_call.delta:.3f}  mid={short_call.mid:.2f}  expiry={short_call.expiry}")

    ep = [l for l in puts  if l.expiry == short_put.expiry]
    ec = [l for l in calls if l.expiry == short_call.expiry]
    log.info(f"IC [{symbol}]: same-expiry puts={len(ep)}  calls={len(ec)}")

    long_put  = _find_wing(ep, short_put.strike,  IC_WING_WIDTH, "P")
    long_call = _find_wing(ec, short_call.strike, IC_WING_WIDTH, "C")
    if not long_put or not long_call:
        log.warning(f"IC [{symbol}]: could not find wing legs")
        available_p = sorted(set(l.strike for l in ep))
        available_c = sorted(set(l.strike for l in ec))
        log.info(f"IC [{symbol}]: available put strikes (first 15): {available_p[:15]}")
        log.info(f"IC [{symbol}]: available call strikes (first 15): {available_c[:15]}")
        return False
    if not _legs_liquid(f"IC [{symbol}]", [short_put, long_put, short_call, long_call]):
        return False

    net_credit = (short_put.mid - long_put.mid) + (short_call.mid - long_call.mid)
    max_risk   = (IC_WING_WIDTH - net_credit) * 100
    if max_risk <= 0 or net_credit <= 0:
        log.warning(f"IC [{symbol}]: bad credit/risk ({net_credit:.2f} / {max_risk:.2f})")
        return False

    if not _credit_quality_ok(f"IC [{symbol}]", net_credit, max_risk):
        return False

    candidate_confidence = _candidate_confidence(
        strategy="iron_condor",
        symbol=symbol,
        legs=[short_put, long_put, short_call, long_call],
        net_credit=net_credit,
        max_risk=max_risk,
        dte=_dte(short_put.expiry),
    )
    if not _candidate_confidence_ok(f"IC [{symbol}]", candidate_confidence):
        return False

    qty = _sized_qty(equity, max_risk, 2, f"IC [{symbol}]")
    if qty < 1:
        return False
    log.info(
        f"IC [{symbol}]: expiry={short_put.expiry}  DTE={_dte(short_put.expiry)}  "
        f"P{short_put.strike:.0f}/{long_put.strike:.0f}  "
        f"C{short_call.strike:.0f}/{long_call.strike:.0f}  "
        f"credit={net_credit:.2f}  risk={max_risk:.2f}/contract  qty={qty}"
    )

    return _place_mleg(
        legs_payload=[
            {"symbol": short_put.symbol,  "side": "sell", "ratio_qty": "1", "position_intent": "sell_to_open"},
            {"symbol": long_put.symbol,   "side": "buy",  "ratio_qty": "1", "position_intent": "buy_to_open"},
            {"symbol": short_call.symbol, "side": "sell", "ratio_qty": "1", "position_intent": "sell_to_open"},
            {"symbol": long_call.symbol,  "side": "buy",  "ratio_qty": "1", "position_intent": "buy_to_open"},
        ],
        limit_price=net_credit,
        qty=qty,
        label=f"Iron Condor [{symbol}]",
        trade_meta={
            "label": f"Iron Condor [{symbol}]",
            "strategy": "iron_condor",
            "underlying": symbol,
            "legs": [short_put.symbol, long_put.symbol, short_call.symbol, long_call.symbol],
            "net_credit": net_credit,
            "max_risk_per_contract": max_risk,
            "qty": qty,
            "profit_close_pct": IC_PROFIT_CLOSE_PCT,
            "stop_loss_pct": STOP_LOSS_PCT,
            "expiry": str(short_put.expiry),
            "candidate_confidence": candidate_confidence,
            "vix_at_entry": _JOURNAL_VIX,
            "vix_term_ratio": _JOURNAL_VIX_TERM_RATIO,
            "iv_rank_at_entry": _JOURNAL_IV_RANK.get(symbol),
        },
    )


# â”€â”€ Strategy: Put Spread â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
def run_put_spread(
    trade_client: TradingClient,
    data_client: OptionHistoricalDataClient,
    symbol: str,
    equity: float,
) -> bool:
    log.info(f"--- Put Spread scan [{symbol}] ---")
    # Only sell puts when stock is in uptrend â€” reduces chance put goes ITM
    trend_ok = _above_20sma(symbol)
    if not trend_ok:
        log.info(f"PS [{symbol}]: below 20 SMA â€” skipping put spread")
        _strategy_skip(symbol, "ps", "trend_filter_below_20sma")
        return False
    puts = _fetch_chain(data_client, symbol, PS_DTE_MIN, PS_DTE_MAX, "put")
    if not puts:
        log.warning(f"PS [{symbol}]: no chain data")
        _strategy_skip(symbol, "ps", "no_chain_data", dte_min=PS_DTE_MIN, dte_max=PS_DTE_MAX)
        return False

    short_put = _closest_delta(puts, PS_DELTA_TARGET)
    if not short_put:
        log.warning(f"PS [{symbol}]: could not find 25-delta put")
        _strategy_skip(symbol, "ps", "missing_short_put_delta", target_delta=PS_DELTA_TARGET)
        return False

    width    = PS_WIDTH_OVERRIDE.get(symbol, PS_WIDTH)
    same_exp = [l for l in puts if l.expiry == short_put.expiry]
    long_put  = _find_wing(same_exp, short_put.strike, width, "P")
    if not long_put:
        log.warning(f"PS [{symbol}]: could not find long put wing")
        _strategy_skip(
            symbol,
            "ps",
            "missing_long_put_wing",
            expiry=str(short_put.expiry),
            short_strike=short_put.strike,
            width=width,
        )
        return False
    if not _legs_liquid(f"PS [{symbol}]", [short_put, long_put]):
        _strategy_skip(
            symbol,
            "ps",
            "illiquid_legs",
            legs=[short_put.symbol, long_put.symbol],
        )
        return False

    net_credit = short_put.mid - long_put.mid
    max_risk   = (width - net_credit) * 100
    if max_risk <= 0 or net_credit <= 0:
        log.warning(f"PS [{symbol}]: bad credit/risk ({net_credit:.2f} / {max_risk:.2f})")
        _strategy_skip(
            symbol,
            "ps",
            "invalid_credit_risk",
            net_credit=round(net_credit, 4),
            max_risk=round(max_risk, 4),
        )
        return False

    if not _credit_quality_ok(f"PS [{symbol}]", net_credit, max_risk):
        ratio = (net_credit * 100) / max_risk if max_risk else 0.0
        reason = "net_credit_below_minimum" if net_credit < MIN_NET_CREDIT else "credit_to_risk_below_minimum"
        _strategy_skip(
            symbol,
            "ps",
            reason,
            net_credit=round(net_credit, 4),
            max_risk=round(max_risk, 4),
            credit_to_risk=round(ratio, 4),
            minimum_credit_to_risk=MIN_CREDIT_TO_RISK,
            minimum_net_credit=MIN_NET_CREDIT,
        )
        return False

    candidate_confidence = _candidate_confidence(
        strategy="put_spread",
        symbol=symbol,
        legs=[short_put, long_put],
        net_credit=net_credit,
        max_risk=max_risk,
        dte=_dte(short_put.expiry),
        trend_ok=trend_ok,
    )
    if not _candidate_confidence_ok(f"PS [{symbol}]", candidate_confidence):
        return False

    qty = _sized_qty(equity, max_risk, 3, f"PS [{symbol}]")
    if qty < 1:
        _strategy_skip(
            symbol,
            "ps",
            "sized_quantity_below_one",
            max_risk=round(max_risk, 4),
            equity=round(equity, 2),
        )
        return False
    log.info(
        f"PS [{symbol}]: expiry={short_put.expiry}  DTE={_dte(short_put.expiry)}  "
        f"strikes={short_put.strike:.0f}/{long_put.strike:.0f}  "
        f"credit={net_credit:.2f}  risk={max_risk:.2f}/contract  qty={qty}"
    )

    return _place_mleg(
        legs_payload=[
            {"symbol": short_put.symbol, "side": "sell", "ratio_qty": "1", "position_intent": "sell_to_open"},
            {"symbol": long_put.symbol,  "side": "buy",  "ratio_qty": "1", "position_intent": "buy_to_open"},
        ],
        limit_price=net_credit,
        qty=qty,
        label=f"Put Spread [{symbol}]",
        trade_meta={
            "label": f"Put Spread [{symbol}]",
            "strategy": "put_spread",
            "underlying": symbol,
            "legs": [short_put.symbol, long_put.symbol],
            "net_credit": net_credit,
            "max_risk_per_contract": max_risk,
            "qty": qty,
            "profit_close_pct": PS_PROFIT_CLOSE_PCT,
            "stop_loss_pct": STOP_LOSS_PCT,
            "expiry": str(short_put.expiry),
            "candidate_confidence": candidate_confidence,
            "vix_at_entry": _JOURNAL_VIX,
            "vix_term_ratio": _JOURNAL_VIX_TERM_RATIO,
            "iv_rank_at_entry": _JOURNAL_IV_RANK.get(symbol),
        },
    )


# â”€â”€ Single-leg order (for CSP and covered call) â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

# -- Strategy: Call Spread (bearish -- sell OTM call spread when below 20 SMA) --
def run_call_spread(
    trade_client: "TradingClient",
    data_client: "OptionHistoricalDataClient",
    symbol: str,
    equity: float,
) -> bool:
    log.info(f"--- Call Spread scan [{symbol}] ---")
    if _above_20sma(symbol):
        log.info(f"CS [{symbol}]: above 20 SMA -- skipping (use put spread instead)")
        _strategy_skip(symbol, "cs", "trend_filter_above_20sma_use_ps")
        return False
    calls = _fetch_chain(data_client, symbol, PS_DTE_MIN, PS_DTE_MAX, "call")
    if not calls:
        log.warning(f"CS [{symbol}]: no call chain data")
        _strategy_skip(symbol, "cs", "no_chain_data", dte_min=PS_DTE_MIN, dte_max=PS_DTE_MAX)
        return False
    short_call = _closest_delta(calls, PS_DELTA_TARGET)
    if not short_call:
        _strategy_skip(symbol, "cs", "missing_short_call_delta", target_delta=PS_DELTA_TARGET)
        return False
    width = PS_WIDTH_OVERRIDE.get(symbol, PS_WIDTH)
    same_exp = [l for l in calls if l.expiry == short_call.expiry]
    long_call = _find_wing(same_exp, short_call.strike, width, "C")
    if not long_call:
        _strategy_skip(symbol, "cs", "missing_long_call_wing",
                       expiry=str(short_call.expiry), short_strike=short_call.strike, width=width)
        return False
    if not _legs_liquid(f"CS [{symbol}]", [short_call, long_call]):
        _strategy_skip(symbol, "cs", "illiquid_legs", legs=[short_call.symbol, long_call.symbol])
        return False
    net_credit = short_call.mid - long_call.mid
    max_risk = (width - net_credit) * 100
    if max_risk <= 0 or net_credit <= 0:
        _strategy_skip(symbol, "cs", "invalid_credit_risk",
                       net_credit=round(net_credit, 4), max_risk=round(max_risk, 4))
        return False
    if not _credit_quality_ok(f"CS [{symbol}]", net_credit, max_risk):
        ratio = (net_credit * 100) / max_risk if max_risk else 0.0
        reason = "net_credit_below_minimum" if net_credit < MIN_NET_CREDIT else "credit_to_risk_below_minimum"
        _strategy_skip(symbol, "cs", reason, net_credit=round(net_credit, 4),
                       max_risk=round(max_risk, 4), credit_to_risk=round(ratio, 4))
        return False
    candidate_confidence = _candidate_confidence(
        strategy="call_spread", symbol=symbol, legs=[short_call, long_call],
        net_credit=net_credit, max_risk=max_risk, dte=_dte(short_call.expiry), trend_ok=True,
    )
    if not _candidate_confidence_ok(f"CS [{symbol}]", candidate_confidence):
        return False
    qty = _sized_qty(equity, max_risk, 3, f"CS [{symbol}]")
    if qty < 1:
        _strategy_skip(symbol, "cs", "sized_quantity_below_one",
                       max_risk=round(max_risk, 4), equity=round(equity, 2))
        return False
    log.info(
        f"CS [{symbol}]: expiry={short_call.expiry}  DTE={_dte(short_call.expiry)}  "
        f"strikes={short_call.strike:.0f}/{long_call.strike:.0f}  "
        f"credit={net_credit:.2f}  risk={max_risk:.2f}/contract  qty={qty}"
    )
    return _place_mleg(
        legs_payload=[
            {"symbol": short_call.symbol, "side": "sell", "ratio_qty": "1", "position_intent": "sell_to_open"},
            {"symbol": long_call.symbol,  "side": "buy",  "ratio_qty": "1", "position_intent": "buy_to_open"},
        ],
        limit_price=net_credit, qty=qty, label=f"Call Spread [{symbol}]",
        trade_meta={
            "label": f"Call Spread [{symbol}]", "strategy": "call_spread",
            "underlying": symbol, "legs": [short_call.symbol, long_call.symbol],
            "net_credit": net_credit, "max_risk_per_contract": max_risk, "qty": qty,
            "profit_close_pct": PS_PROFIT_CLOSE_PCT, "stop_loss_pct": STOP_LOSS_PCT,
            "expiry": str(short_call.expiry), "candidate_confidence": candidate_confidence,
            "leg_market_snapshots": [_leg_market_snapshot(short_call), _leg_market_snapshot(long_call)],
            "vix_at_entry": _JOURNAL_VIX, "vix_term_ratio": _JOURNAL_VIX_TERM_RATIO,
            "iv_rank_at_entry": _JOURNAL_IV_RANK.get(symbol),
        },
    )


def _place_single_leg(
    occ_symbol: str,
    side: str,
    limit_price: float,
    qty: int,
    label: str,
    trade_meta: Optional[dict] = None,
) -> bool:
    trade_meta = dict(trade_meta or {})
    underlying = str(trade_meta.get("underlying") or label)
    qty, garch_meta, garch_allowed = _garch_entry_adjustment(underlying, qty)
    trade_meta["garch_volatility_risk"] = garch_meta
    trade_meta["qty"] = qty
    if not garch_allowed:
        strategy = str(trade_meta.get("strategy") or "single_leg")
        _decision(underlying, strategy, "skip", garch_meta["reason"], garch_volatility_risk=garch_meta)
        log.warning(f"{label}: GARCH ENTRY BLOCKED {underlying}: {garch_meta['reason']}")
        _alert(f"GARCH ENTRY BLOCKED: **{label}**\nreason={garch_meta['reason']}")
        return False
    if not _guard_submission(label, qty, trade_meta):
        return False
    if REQUIRE_MANUAL_APPROVAL:
        log.warning(
            f"{label}: manual approval required; candidate NOT submitted "
            f"{side} {occ_symbol} credit={limit_price:.2f} qty={qty}"
        )
        _alert(f"MANUAL APPROVAL REQUIRED: **{label}**\n{side} {occ_symbol}\ncredit=${limit_price:.2f} qty={qty}")
        return False
    body   = {
        "symbol":        occ_symbol,
        "side":          side,
        "type":          "limit",
        "limit_price":   str(round(limit_price, 2)),
        "time_in_force": "day",
        "qty":           str(qty),
    }
    order = _post_order_with_retry(body, label)
    if not order:
        return False
    oid = order.get("id", "?")
    log.info(f"{label}: submitted  order_id={oid}  credit={limit_price:.2f}  qty={qty}")
    _alert(f"ðŸ“¥ **{label}** submitted\ncredit=${limit_price:.2f}  qty={qty}  order={oid}")
    return True
    try:
        resp = r.post(
            f"{BASE}/v2/orders",
            json=body,
            headers={"APCA-API-KEY-ID": key, "APCA-API-SECRET-KEY": secret},
            timeout=10,
        )
        resp.raise_for_status()
        oid = resp.json().get("id", "?")
        log.info(f"{label}: submitted  order_id={oid}  credit={limit_price:.2f}  qty={qty}")
        _alert(f"ðŸ“¥ **{label}** submitted\ncredit=${limit_price:.2f}  qty={qty}  order={oid}")
        return True
    except Exception as exc:
        log.error(f"{label}: submission failed â€” {exc}")
        return False


# â”€â”€ Strategy: Wheel â€” Cash-Secured Put leg â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
def run_cash_secured_put(
    trade_client: TradingClient,
    data_client: OptionHistoricalDataClient,
    symbol: str,
    equity: float,
) -> bool:
    log.info(f"--- Wheel CSP scan [{symbol}] ---")
    trend_ok = _above_20sma(symbol)
    if not trend_ok:
        log.info(f"Wheel CSP [{symbol}]: below 20 SMA â€” skipping cash-secured put")
        return False
    puts = _fetch_chain(data_client, symbol, WHEEL_DTE_MIN, WHEEL_DTE_MAX, "put")
    if not puts:
        log.warning(f"Wheel CSP [{symbol}]: no chain data")
        return False

    short_put = _closest_delta(puts, WHEEL_DELTA)
    if not short_put:
        log.warning(f"Wheel CSP [{symbol}]: could not find {WHEEL_DELTA}-delta put")
        return False
    if not _legs_liquid(f"Wheel CSP [{symbol}]", [short_put]):
        return False

    # Cash needed to secure 100 shares at strike price
    cash_required = short_put.strike * 100
    if cash_required > equity * MAX_WHEEL_ALLOC_PCT:
        log.warning(f"Wheel CSP [{symbol}]: strike ${short_put.strike} requires ${cash_required:,.0f} â€” too large for account")
        return False

    qty = min(2, int((equity * MAX_WHEEL_ALLOC_PCT) // cash_required))
    if qty < 1:
        log.warning(
            f"Wheel CSP [{symbol}]: cash required ${cash_required:,.0f} exceeds "
            f"wheel allocation ${equity * MAX_WHEEL_ALLOC_PCT:,.0f}, skipping"
        )
        return False
    candidate_confidence = _candidate_confidence(
        strategy="wheel_csp",
        symbol=symbol,
        legs=[short_put],
        net_credit=short_put.mid,
        max_risk=cash_required,
        dte=_dte(short_put.expiry),
        trend_ok=trend_ok,
    )
    if not _candidate_confidence_ok(f"Wheel CSP [{symbol}]", candidate_confidence):
        return False
    log.info(
        f"Wheel CSP [{symbol}]: expiry={short_put.expiry}  DTE={_dte(short_put.expiry)}  "
        f"strike={short_put.strike}  delta={short_put.delta:.3f}  "
        f"premium={short_put.mid:.2f}  qty={qty}"
    )
    return _place_single_leg(
        short_put.symbol,
        "sell",
        short_put.mid,
        qty,
        f"Wheel CSP [{symbol}]",
        trade_meta={
            "strategy": "wheel_csp",
            "underlying": symbol,
            "net_credit": short_put.mid,
            "max_risk_per_contract": cash_required,
            "candidate_confidence": candidate_confidence,
        },
    )


# â”€â”€ Strategy: Wheel â€” Covered Call leg â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
def run_covered_call(
    trade_client: TradingClient,
    data_client: OptionHistoricalDataClient,
    symbol: str,
    equity: float,
    shares_held: int,
) -> bool:
    log.info(f"--- Wheel Covered Call scan [{symbol}] ({shares_held} shares held) ---")
    contracts = shares_held // 100
    if contracts < 1:
        log.warning(f"Wheel CC [{symbol}]: need 100+ shares, have {shares_held}")
        return False

    calls = _fetch_chain(data_client, symbol, WHEEL_DTE_MIN, WHEEL_DTE_MAX, "call")
    if not calls:
        log.warning(f"Wheel CC [{symbol}]: no chain data")
        return False

    short_call = _closest_delta(calls, WHEEL_CC_DELTA)
    if not short_call:
        log.warning(f"Wheel CC [{symbol}]: could not find {WHEEL_CC_DELTA}-delta call")
        return False
    if not _legs_liquid(f"Wheel CC [{symbol}]", [short_call]):
        return False

    candidate_confidence = _candidate_confidence(
        strategy="wheel_cc",
        symbol=symbol,
        legs=[short_call],
        net_credit=short_call.mid,
        max_risk=short_call.mid * 100,
        dte=_dte(short_call.expiry),
    )
    if not _candidate_confidence_ok(f"Wheel CC [{symbol}]", candidate_confidence):
        return False

    log.info(
        f"Wheel CC [{symbol}]: expiry={short_call.expiry}  DTE={_dte(short_call.expiry)}  "
        f"strike={short_call.strike}  delta={short_call.delta:.3f}  "
        f"premium={short_call.mid:.2f}  contracts={contracts}"
    )
    return _place_single_leg(
        short_call.symbol,
        "sell",
        short_call.mid,
        contracts,
        f"Wheel CC [{symbol}]",
        trade_meta={
            "strategy": "wheel_cc",
            "underlying": symbol,
            "net_credit": short_call.mid,
            "max_risk_per_contract": short_call.mid * 100,
            "candidate_confidence": candidate_confidence,
        },
    )


# â”€â”€ Strategy: Wheel â€” Orchestrator â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
def run_wheel(
    trade_client: TradingClient,
    data_client: OptionHistoricalDataClient,
    symbol: str,
    equity: float,
) -> bool:
    # Check if we hold shares of the underlying
    try:
        positions = trade_client.get_all_positions()
        stock_pos = next(
            (p for p in positions
             if p.symbol == symbol and getattr(p, "asset_class", "") == "us_equity"),
            None,
        )
    except Exception as exc:
        log.error(f"Wheel [{symbol}]: could not fetch positions â€” {exc}")
        return False

    shares = int(float(stock_pos.qty)) if stock_pos else 0

    if shares >= 100:
        _record_wheel_assignment(symbol, shares)
        log.info(f"Wheel [{symbol}]: holding {shares} shares â†’ selling covered call")
        return run_covered_call(trade_client, data_client, symbol, equity, shares)
    else:
        _record_wheel_cash_secured_phase(symbol)
        log.info(f"Wheel [{symbol}]: no shares held â†’ selling cash-secured put")
        return run_cash_secured_put(trade_client, data_client, symbol, equity)


# â”€â”€ Main â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
def main(strategy: str = "both", symbols: Optional[list[str]] = None) -> None:
    log.info(f"Options Bot  mode={'PAPER' if PAPER else '*** LIVE ***'}  strategy={strategy}")
    trade_client, data_client = _build_clients()

    # Always monitor open positions first (runs even when market closed)
    position_integrity_ok = monitor_and_close(trade_client, data_client)
    if not position_integrity_ok:
        log.warning(
            "Option position integrity is unresolved; blocking all new entries for this run"
        )
        return

    # No new entries outside market hours
    if not _market_is_open():
        log.info("Market closed â€” skipping new entries")
        return

    # VIX macro filter â€” one check covers all symbols
    if not _vix_in_range():
        return

    # Safety gates (shared across all symbols)
    equity = _equity(trade_client)
    log.info(f"Equity: ${equity:,.2f}")

    if not _daily_loss_guard(trade_client, equity):
        return

    if _open_option_count(trade_client) >= MAX_OPEN_TRADES:
        log.info(f"Max open trades ({MAX_OPEN_TRADES}) reached â€” no new entries")
        return

    if _trades_today(trade_client) >= MAX_TRADES_PER_DAY:
        log.info(f"Max trades/day ({MAX_TRADES_PER_DAY}) reached â€” done for today")
        return

    # Determine which symbols to run
    target_symbols = symbols if symbols else list(SYMBOLS.keys())

    for sym in target_symbols:
        sym_strategies = SYMBOLS.get(sym, [])
        if not sym_strategies:
            log.warning(f"{sym} not in SYMBOLS config â€” skipping")
            continue

        log.info(f"=== Processing {sym} ===")

        open_underlying_trades = _open_underlying_trade_count(trade_client, sym)
        if open_underlying_trades >= MAX_OPEN_TRADES_PER_UNDERLYING:
            log.info(
                f"{sym}: existing option exposure count {open_underlying_trades} >= "
                f"{MAX_OPEN_TRADES_PER_UNDERLYING}; not stacking trades"
            )
            _decision(
                sym,
                strategy,
                "skip",
                "underlying_exposure_cap",
                open_underlying_trades=open_underlying_trades,
                max_open_trades_per_underlying=MAX_OPEN_TRADES_PER_UNDERLYING,
            )
            continue

        # IV Rank gate per symbol â€” also stored for trade journal
        rank = iv_rank(sym)
        _JOURNAL_IV_RANK[sym] = rank
        if rank < IV_RANK_MIN:
            log.info(f"{sym}: IV Rank {rank:.1f} < {IV_RANK_MIN} â€” skipping (low vol, bad for premium selling)")
            continue

        # Earnings gate â€” skip individual stocks near earnings
        if _has_earnings_soon(sym):
            continue

        # Put/call ratio sentiment gate
        if not _pcr_ok(sym):
            continue

        # Per-symbol strategy runs
        ran_ic = ran_ps = False
        new_trades_this_symbol = 0

        if strategy in ("both", "ic") and "ic" in sym_strategies:
            ran_ic = run_iron_condor(trade_client, data_client, sym, equity)
            if ran_ic:
                new_trades_this_symbol += 1
                _decision(sym, "ic", "submitted", "candidate_passed_all_filters")

        if (
            strategy in ("both", "ps")
            and "ps" in sym_strategies
            and new_trades_this_symbol < MAX_NEW_TRADES_PER_SYMBOL_PER_RUN
        ):
            ran_ps = run_put_spread(trade_client, data_client, sym, equity)
            if ran_ps:
                new_trades_this_symbol += 1
                _decision(sym, "ps", "submitted", "candidate_passed_all_filters")
        if (
            strategy in ("both", "cs")
            and "cs" in sym_strategies
            and new_trades_this_symbol < MAX_NEW_TRADES_PER_SYMBOL_PER_RUN
        ):
            ran_cs = run_call_spread(trade_client, data_client, sym, equity)
            if ran_cs:
                new_trades_this_symbol += 1
                _decision(sym, "cs", "submitted", "candidate_passed_all_filters")

        elif strategy in ("both", "ps") and "ps" in sym_strategies:
            log.info(f"{sym}: per-run symbol trade cap reached; skipping put spread")
            _decision(sym, "ps", "skip", "per_run_symbol_trade_cap")

        if (
            strategy in ("both", "wheel")
            and "wheel" in sym_strategies
            and new_trades_this_symbol < MAX_NEW_TRADES_PER_SYMBOL_PER_RUN
        ):
            if run_wheel(trade_client, data_client, sym, equity):
                new_trades_this_symbol += 1
                _decision(sym, "wheel", "submitted", "candidate_passed_all_filters")
        elif strategy in ("both", "wheel") and "wheel" in sym_strategies:
            log.info(f"{sym}: per-run symbol trade cap reached; skipping wheel")
            _decision(sym, "wheel", "skip", "per_run_symbol_trade_cap")

        if not ran_ic and not ran_ps:
            log.info(f"{sym}: no trades placed")

        # Re-check daily limit after each symbol
        if _trades_today(trade_client) >= MAX_TRADES_PER_DAY:
            log.info(f"Max trades/day ({MAX_TRADES_PER_DAY}) reached â€” stopping")
            break

    log.info("Run complete.")


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser(description="Options Bot â€” Iron Condor + Put Spread + Wheel (IWM, SPY, QQQ, NVDA, PLTR)")
    ap.add_argument(
        "--strategy", choices=["both", "ic", "ps", "cs", "wheel"], default="both",
        help="ic=iron condor ps=put spread cs=call spread wheel=wheel only both=all (default)",
    )
    ap.add_argument(
        "--symbol", type=str, default=None,
        help="Run for a single symbol only (e.g. --symbol NVDA). Default: all configured symbols.",
    )
    ap.add_argument(
        "--monitor-only", action="store_true",
        help="Only check profit-close/stop-loss on existing positions, no new entries",
    )
    args = ap.parse_args()

    if args.monitor_only:
        tc, dc = _build_clients()
        monitor_and_close(tc, dc)
    else:
        sym_list = [args.symbol.upper()] if args.symbol else None
        main(strategy=args.strategy, symbols=sym_list)
# end of file


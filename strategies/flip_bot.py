#!/usr/bin/env python3
"""
Flip Bot â€” automated small-account directional options trading.

Two modes:
  --entry    Find catalyst setups and submit buy orders (run at 9:15am ET)
  --monitor  Check open trades, close at +75% profit or -50% stop (run every 15min)

Three strategies:
  0DTE   â€” buy ATM SPY call/put on FOMC/CPI/gap days, exit by 1:45pm
  Lotto  â€” buy OTM call 2-4 days before earnings, exit day before print
  Break  â€” buy OTM weekly call on momentum breakout + volume spike

State file: ~/.vibe-trading/flip-trades.json

Usage:
    python strategies/flip_bot.py --entry --account 500
    python strategies/flip_bot.py --monitor
    python strategies/flip_bot.py --status
    python strategies/flip_bot.py --close-all

Task Scheduler:
    Entry:   9:15am ET Mon-Fri
    Monitor: every 15min 9:30am-3:45pm Mon-Fri
"""
from __future__ import annotations

import argparse
import json
import logging
import math
import os
import sys
import time
from datetime import date, datetime, time as dtime, timedelta, timezone
from pathlib import Path
from uuid import uuid4

import socket
import pandas as pd
import requests as req
from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
socket.setdefaulttimeout(25)  # prevent yfinance from hanging Task Scheduler

from strategies.flip_shadow_setup_challengers import (
    evaluate_15m_orb_retest,
    evaluate_level_sweep_reversal,
    evaluate_orb_extension_reversal,
)
from strategies.flip_contract_ranker import rank_contracts
from strategies.flip_day_type_router import classify_intraday_day_type
from strategies.flip_retest_quality import score_retest_quality
from strategies.spy_noise_area import evaluate_noise_area
from scripts.alpaca_resilience import AlpacaReadUnavailable, get_json as alpaca_get_json

try:
    from risk_kill_switch import DEFAULT_BLOCK_FILE, manual_reset_required
    from execution_guard import ExecutionGuardConfig, evaluate_execution
    from shadow_consensus import entry_advice as shadow_entry_advice
    from shadow_consensus import exit_advice as shadow_exit_advice
    from scripts.market_data import fetch_vix_term_structure_context
except ModuleNotFoundError:
    from strategies.risk_kill_switch import DEFAULT_BLOCK_FILE, manual_reset_required
    from strategies.execution_guard import ExecutionGuardConfig, evaluate_execution
    from strategies.shadow_consensus import entry_advice as shadow_entry_advice
    from strategies.shadow_consensus import exit_advice as shadow_exit_advice
    from scripts.market_data import fetch_vix_term_structure_context

load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), "..", "agent", ".env"))

try:
    import yfinance as yf
except ImportError:
    print("ERROR: pip install yfinance")
    sys.exit(1)

# â”€â”€ Logging â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
LOG_DIR = Path(os.path.expanduser(r"~\.vibe-trading\logs"))
LOG_DIR.mkdir(parents=True, exist_ok=True)
_fmt = logging.Formatter("%(asctime)s  %(levelname)-8s  %(message)s", datefmt="%Y-%m-%d %H:%M:%S")
_fh  = logging.FileHandler(LOG_DIR / "flip-bot.log", encoding="utf-8")
_fh.setFormatter(_fmt)
_sh  = logging.StreamHandler()
_sh.setFormatter(_fmt)
logging.basicConfig(level=logging.INFO, handlers=[_fh, _sh])
log = logging.getLogger("flip-bot")

# â”€â”€ Alpaca â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
KEY    = os.getenv("ALPACA_API_KEY", "")
SECRET = os.getenv("ALPACA_SECRET_KEY", "")
PAPER  = os.getenv("ALPACA_PAPER", "true").lower() == "true"
BASE   = "https://paper-api.alpaca.markets" if PAPER else "https://api.alpaca.markets"
HDR    = {"APCA-API-KEY-ID": KEY, "APCA-API-SECRET-KEY": SECRET, "Content-Type": "application/json"}
DISCORD_WEBHOOK = os.getenv("DISCORD_WEBHOOK_URL", "")
LIVE_EXECUTION_ENABLED = os.getenv("FLIP_LIVE_EXECUTION_ENABLED", "false").lower() == "true"
LIVE_APPROVAL_ACK_VALUE = os.getenv("FLIP_LIVE_APPROVAL_ACK", "")
RH_MIMIC_MODE = os.getenv("RH_MIMIC_MODE", "false").lower() == "true"
RH_ACCOUNT_SIZE = float(os.getenv("RH_ACCOUNT_SIZE", "0") or 0)

# â”€â”€ State â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
STATE_FILE = Path(os.path.expanduser(r"~\.vibe-trading\flip-trades.json"))
DECISION_LOG_FILE = Path(os.getenv("FLIP_DECISION_LOG_FILE", str(LOG_DIR / "flip-decisions.jsonl")))
SHADOW_CANDIDATE_LOG_PATH = Path(__file__).resolve().parent.parent / "data" / "flip_shadow_candidates_log.jsonl"
IV_HISTORY_LOG_PATH = Path(__file__).resolve().parent.parent / "data" / "iv_history_log.jsonl"
SHADOW_CANDIDATE_SCHEMA_VERSION = 4
OPTIONS_LIQUIDITY_REPORT_PATH = Path.home() / ".vibe-trading" / "reports" / "options-liquidity-feasibility.json"
OPTION_PREMIUM_LEVEL_REPORT_PATH = Path.home() / ".vibe-trading" / "reports" / "option-premium-levels.json"
MARKET_FORCE_REPORT_PATH = Path.home() / ".vibe-trading" / "reports" / "market-force-score.json"
MARKET_FORCE_SHADOW_MAX_AGE_SECONDS = 30 * 60
MARKET_CONTEXT_REPORT_DIR = Path.home() / ".vibe-trading" / "reports"
MARKET_CONTEXT_SHADOW_MAX_AGE_SECONDS = 45 * 60
ACCELERATED_SHADOW_LEARNING = os.getenv("ACCELERATED_SHADOW_LEARNING", "false").lower() == "true"
SHADOW_EPISODE_INTERVAL_MINUTES = max(15, int(os.getenv("SHADOW_EPISODE_INTERVAL_MINUTES", "30")))
SHADOW_EPISODE_HORIZON_MINUTES = max(15, int(os.getenv("SHADOW_EPISODE_HORIZON_MINUTES", "60")))
SHADOW_MAX_ACTIVE_PER_SYMBOL = max(4, int(os.getenv("SHADOW_MAX_ACTIVE_PER_SYMBOL", "6")))
SHADOW_MAX_ACTIVE_PER_SYMBOL_STRATEGY = 1
SHADOW_CONTINUE_AFTER_TARGET = os.getenv("SHADOW_CONTINUE_AFTER_TARGET", "true").strip().lower() in {"1", "true", "yes", "on"}
NOISE_AREA_PAPER_ENABLED = os.getenv("FLIP_NOISE_AREA_PAPER_ENABLED", "false").strip().lower() in {"1", "true", "yes", "on"}
NOISE_AREA_LOOKBACK_SESSIONS = max(14, int(os.getenv("FLIP_NOISE_AREA_LOOKBACK_SESSIONS", "14")))
GEX_WALL_PROXIMITY_PCT = float(os.getenv("FLIP_GEX_WALL_PROXIMITY_PCT", "0.003"))  # 0.3% of spot
MOMENTUM_ORB_MIN_ATR_RATIO = float(os.getenv("FLIP_MOMENTUM_ORB_MIN_ATR_RATIO", "1.8"))
MOMENTUM_ORB_MIN_CLV       = float(os.getenv("FLIP_MOMENTUM_ORB_MIN_CLV", "0.70"))

# â”€â”€ Config â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
ACCOUNT_OVERRIDE  = float(os.getenv("FLIP_ACCOUNT_SIZE_OVERRIDE") or os.getenv("ACCOUNT_SIZE_OVERRIDE", "0") or 0)
MAX_RISK_PCT      = 0.02   # 2% account risk per trade (was 0.25 â€” caused 69-contract blowup)
MAX_CONTRACTS     = 5      # hard ceiling regardless of account size or option price
MAX_ENTRY_SPREAD_CENTS = int(os.getenv("FLIP_MAX_ENTRY_SPREAD_CENTS", "10"))
MAX_ENTRY_SLIPPAGE_PCT = float(os.getenv("FLIP_MAX_ENTRY_SLIPPAGE_PCT", "3.0"))
MAX_ENTRY_QUOTE_AGE_SECONDS = float(os.getenv("FLIP_MAX_ENTRY_QUOTE_AGE_SECONDS", "15.0"))
PROFIT_MULT       = 1.75   # entry * 1.75 = target (+75%)
STOP_MULT         = 0.70   # entry * 0.70 = stop   (-30%)
PROFIT_PROTECT_ARM_PCT = 40.0   # once a long option reaches +40%, protect the win
PROFIT_PROTECT_FLOOR_PCT = 25.0 # minimum win to protect after a 0DTE runner arms
PROFIT_PROTECT_GIVEBACK_PCT = 15.0 # ratchet: close if a winner gives back 15 pts from best
PROFIT_PROTECT_TIER_FLOORS = (
    (60.0, 45.0),
    (50.0, 35.0),
)
# Closed trades showed stops filling at -62% to -66% against the -30% design and
# ratchet floors leaking ~28 points because the 15-minute scheduler gap is longer
# than a 0DTE option's adverse move. While positions are open, the monitor loops
# in-process at this cadence instead of sleeping until the next scheduled run.
MONITOR_PROTECT_LOOP_SECONDS = max(15, int(os.getenv("FLIP_MONITOR_PROTECT_LOOP_SECONDS", "60")))
MONITOR_PROTECT_WINDOW_MINUTES = float(os.getenv("FLIP_MONITOR_PROTECT_WINDOW_MINUTES", "12"))
SHADOW_DEFENSIVE_EXIT_LOSS_PCT = float(os.getenv("FLIP_SHADOW_DEFENSIVE_EXIT_LOSS_PCT", "0.0"))
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
PRIMARY_STAND_ASIDE_BLOCKERS = {
    "adaptive_market_regime_is_unclear_or_mixed",
    "adaptive_stand_aside",
    "catalyst_dynamic_geopolitical_caution",
    "catalyst_size_down_required",
    "htf_intraday_not_aligned",
    "htf_mixed_higher_timeframes",
    "market_force_unclear",
    "mixed_higher_timeframes",
    "weak_shadow_pnl_evidence",
}
GAP_THRESHOLD     = 0.0075
VOLUME_SPIKE      = 2.5
MAX_OPEN_FLIPS    = 2
SAME_DAY_REENTRY_MIN_CONFIDENCE = 10.0
BEAR_TREND_MIN_CONFIDENCE = 8.5  # matches ExecutionGuardConfig.min_confidence default
BULL_TREND_MIN_CONFIDENCE = 8.5  # require genuine guard-grade confirmation; never pad confidence
BEAR_TREND_MAX_VWAP_EXT   = 0.015
BEAR_TREND_MIN_BARS       = 55
ORB_OPENING_RANGE_MINUTES = 5
ORB_RETEST_ENTRY_WINDOW_MINUTES = 60
ORB_RETEST_MAX_AGE_BARS = 15
ORB_RETEST_RANGE_FRACTION = 0.10
ORB_RETEST_MIN_TOLERANCE_BPS = 2.0
ORB_RETEST_MAX_TOLERANCE_BPS = 10.0
TREND_PULLBACK_LOOKBACK_BARS = 8
TREND_PULLBACK_TOLERANCE_BPS = 8.0
TREND_MAX_ORB_EXTENSION_FRACTION = 1.5
NOISE_AREA_PAPER_CONTRACT_CAP = 1

CATALYST_DAYS = [
    (date(2026, 7, 14),  "CPI",  "straddle"),
    (date(2026, 7, 29),  "FOMC", "directional"),
    (date(2026, 8, 12),  "CPI",  "straddle"),
    (date(2026, 9, 11),  "CPI",  "straddle"),
    (date(2026, 9, 16),  "FOMC", "directional"),
    (date(2026, 10, 14), "CPI",  "straddle"),
    (date(2026, 10, 28), "FOMC", "directional"),
]

DEFAULT_SYMBOLS = ["TSLA", "NVDA", "AAPL", "META", "AMZN", "AMD", "PLTR", "COIN"]
SHADOW_CANDIDATES = ["SPY", "QQQ", "IWM", "NVDA", "TSLA", "AAPL", "GOOGL", "META"]
SHADOW_LIQUIDITY_ALLOWLIST = {"SPY", "QQQ", "IWM", "NVDA", "TSLA", "AAPL", "GOOGL", "META", "HOOD", "RIVN", "NFLX", "COIN"}
MAX_DYNAMIC_SHADOW_SYMBOLS = 3
EXECUTION_SYMBOLS = {
    symbol.strip().upper()
    for symbol in os.getenv("FLIP_EXECUTION_SYMBOLS", "SPY").split(",")
    if symbol.strip()
}
PAPER_CHALLENGER_SYMBOL_ORDER = [
    symbol.strip().upper()
    for symbol in os.getenv("FLIP_PAPER_CHALLENGER_SYMBOLS", "").split(",")
    if symbol.strip()
]
PAPER_CHALLENGER_SYMBOLS = set(PAPER_CHALLENGER_SYMBOL_ORDER)
_OPTION_QUOTE_TELEMETRY: dict[str, dict] = {}
_INTRADAY_DATA_ISSUES: dict[str, str] = {}


def _execution_authorization(symbol: str, contracts: int) -> dict:
    normalized = str(symbol or "").upper()
    requested = max(0, int(contracts or 0))
    if normalized in EXECUTION_SYMBOLS:
        return {"allowed": True, "lane": "primary", "contracts": requested, "reason": "execution_symbol"}
    if PAPER and normalized in PAPER_CHALLENGER_SYMBOLS:
        return {
            "allowed": True,
            "lane": "paper_challenger",
            "contracts": min(requested, 1),
            "reason": "paper_challenger_one_contract_cap",
        }
    return {"allowed": False, "lane": "blocked", "contracts": 0, "reason": "symbol_not_promoted"}


def _decision(symbol: str, strategy: str, action: str, reason: str, **details) -> None:
    """Append one durable attribution event without changing a decision."""
    event = {
        "ts": _utc_now_text(),
        "symbol": str(symbol or "").upper(),
        "strategy": str(strategy or "unknown"),
        "action": action,
        "reason": reason,
        "paper": PAPER,
        "details": details,
    }
    try:
        DECISION_LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
        with DECISION_LOG_FILE.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(event, sort_keys=True) + "\n")
    except Exception as exc:
        log.warning(f"Decision log write failed: {exc}")


def _strategy_skip(symbol: str, strategy: str, reason: str, **details) -> None:
    _decision(symbol, strategy, "skip", reason, **details)


def _primary_consensus_caution_blocker(setup: dict, consensus: dict) -> str | None:
    """Promote stacked advisory warnings to a primary-entry veto.

    Shadow consensus remains advisory for research/paper lanes, but primary
    Flip entries should not fire when multiple regime/catalyst tools say the
    setup is a stand-aside. This prevents "good trend score, bad context" trades.
    """
    if setup.get("execution_lane", "primary") != "primary":
        return None
    if str(consensus.get("recommendation") or "").lower() != "stand_aside":
        return None
    blockers = {str(item) for item in (consensus.get("blockers") or [])}
    caution = sorted(blockers & PRIMARY_STAND_ASIDE_BLOCKERS)
    if len(caution) >= 2:
        return "primary_consensus_caution:" + ",".join(caution)
    return None


def _max_entry_limit_price(
    setup: dict,
    *,
    max_slippage_pct: float | None = None,
) -> float | None:
    """Return the highest acceptable entry limit for a long-option buy."""
    max_slippage_pct = (
        MAX_ENTRY_SLIPPAGE_PCT
        if max_slippage_pct is None
        else max_slippage_pct
    )
    candidates = []
    for key in ("selection_ask", "entry_price_est"):
        try:
            value = float(setup.get(key) or 0.0)
        except (TypeError, ValueError):
            value = 0.0
        if value > 0:
            candidates.append(value)
    if not candidates:
        return None
    anchor = min(candidates)
    return round(anchor * (1.0 + max_slippage_pct / 100.0), 2)


def _entry_slippage_blocker(setup: dict) -> dict | None:
    """Block stale/expensive 0DTE entries before submitting the order."""
    if setup.get("short_option_symbol"):
        return None
    limit_price = _max_entry_limit_price(setup)
    if limit_price is None:
        return {
            "reason": "entry_reference_price_unavailable",
            "limit_price": None,
            "current_ask": None,
            "max_slippage_pct": MAX_ENTRY_SLIPPAGE_PCT,
        }
    # Force a new broker-data snapshot here. The selection quote can be several
    # decision steps old and must not be treated as executable evidence.
    _option_mid(setup.get("option_symbol", ""))
    quote = _selection_quote_fields(setup.get("option_symbol", ""))
    try:
        current_ask = float(quote.get("selection_ask") or 0.0)
    except (TypeError, ValueError):
        current_ask = 0.0
    if current_ask <= 0:
        return {
            "reason": "entry_current_ask_unavailable",
            "limit_price": limit_price,
            "current_ask": None,
            "max_slippage_pct": MAX_ENTRY_SLIPPAGE_PCT,
        }
    try:
        quote_age = float(quote.get("quote_age_seconds"))
    except (TypeError, ValueError):
        quote_age = None
    if quote_age is None or quote_age > MAX_ENTRY_QUOTE_AGE_SECONDS:
        return {
            "reason": "entry_quote_stale_or_unverifiable",
            "limit_price": limit_price,
            "current_ask": round(current_ask, 3),
            "quote_age_seconds": quote_age,
            "max_quote_age_seconds": MAX_ENTRY_QUOTE_AGE_SECONDS,
        }
    if current_ask > limit_price:
        return {
            "reason": "entry_slippage_above_limit",
            "limit_price": limit_price,
            "current_ask": round(current_ask, 3),
            "selection_ask": setup.get("selection_ask"),
            "entry_price_est": setup.get("entry_price_est"),
            "max_slippage_pct": MAX_ENTRY_SLIPPAGE_PCT,
            "quote_age_seconds": quote.get("quote_age_seconds"),
        }
    setup["entry_limit_price"] = limit_price
    setup["entry_live_ask_at_submit"] = round(current_ask, 3)
    setup["entry_quote_timestamp_at_submit"] = quote.get("quote_timestamp")
    setup["entry_quote_age_seconds_at_submit"] = quote_age
    setup["entry_slippage_guard_max_pct"] = MAX_ENTRY_SLIPPAGE_PCT
    return None


def _entry_evidence_blocker(setup: dict) -> dict | None:
    """Fail closed when research-only or unconfirmed ORB evidence reaches execution."""
    if setup.get("execution_mode") == "shadow_only" or setup.get("live_execution_allowed") is False:
        return {"reason": "research_only_setup_reached_execution"}

    confidence_basis = str(setup.get("confidence_basis") or "")
    pattern = str(setup.get("orb_entry_pattern") or "")
    status = str(setup.get("orb_retest_status") or "")
    if confidence_basis.endswith("shadow_only") or pattern == "raw_breakout":
        return {
            "reason": "unconfirmed_orb_setup_reached_execution",
            "confidence_basis": confidence_basis or None,
            "orb_entry_pattern": pattern or None,
            "orb_retest_status": status or None,
        }

    if pattern != "breakout_retest":
        setup["entry_evidence_gate"] = "passed_non_orb_strategy"
        return None

    try:
        age_bars = int(setup.get("orb_retest_age_bars"))
    except (TypeError, ValueError):
        age_bars = None
    if status != "retest_confirmed_fresh" or age_bars is None or not 0 <= age_bars <= 15:
        return {
            "reason": "fresh_orb_retest_evidence_required",
            "orb_entry_pattern": pattern,
            "orb_retest_status": status or None,
            "orb_retest_age_bars": age_bars,
            "maximum_retest_age_bars": 15,
        }

    setup["entry_evidence_gate"] = "passed_fresh_orb_retest"
    return None


# ---------------------------------------------------------------------------
# Alpaca helpers
# ---------------------------------------------------------------------------

def _get(path: str, params: dict | None = None) -> dict | list:
    return alpaca_get_json(
        f"{BASE}{path}",
        headers=HDR,
        params=params,
        component="flip_bot",
        operation=f"GET {path}",
        requester=req,
    )


def _post(path: str, body: dict) -> dict:
    r = req.post(f"{BASE}{path}", headers=HDR, json=body, timeout=10)
    r.raise_for_status()
    return r.json()


def _delete(path: str) -> None:
    r = req.delete(f"{BASE}{path}", headers=HDR, timeout=10)
    r.raise_for_status()


def _market_open() -> bool:
    try:
        return bool(_get("/v2/clock").get("is_open", False))
    except Exception:
        return False


def _alert(msg: str) -> None:
    if not DISCORD_WEBHOOK:
        return
    try:
        req.post(DISCORD_WEBHOOK, json={
            "content": f"@everyone FLIP BOT\n{msg}",
            "allowed_mentions": {"parse": ["everyone"]},
        }, timeout=5)
    except Exception as exc:
        log.warning(f"Discord failed: {exc}")


# ---------------------------------------------------------------------------
# OCC symbol
# ---------------------------------------------------------------------------

def _occ(sym: str, expiry: str, right: str, strike: float) -> str:
    d   = datetime.strptime(expiry, "%Y-%m-%d")
    stk = f"{int(round(strike * 1000)):08d}"
    return f"{sym}{d.strftime('%y%m%d')}{'C' if right=='CALL' else 'P'}{stk}"


# ---------------------------------------------------------------------------
# State helpers
# ---------------------------------------------------------------------------

def _load() -> list[dict]:
    if not STATE_FILE.exists():
        return []
    try:
        return json.loads(STATE_FILE.read_text(encoding="utf-8-sig"))
    except Exception as exc:
        raise RuntimeError(f"Could not read Flip Bot state file {STATE_FILE}: {exc}") from exc


def _save(trades: list[dict]) -> None:
    """Durable-state write: atomic temp+replace under an exclusive lock."""
    try:
        from options_state import atomic_save_json
    except ModuleNotFoundError:
        from strategies.options_state import atomic_save_json
    atomic_save_json(STATE_FILE, trades)


# ---------------------------------------------------------------------------
# Account helpers
# ---------------------------------------------------------------------------

def _fetch_alpaca_equity() -> float:
    """Fetch paper-account equity; unresolved broker state returns 0.0."""
    try:
        payload = _get("/v2/account")
        if isinstance(payload, dict):
            eq = float(payload.get("equity", 0) or 0)
        else:
            eq = 0.0
        if eq > 0:
            log.info(f"Alpaca equity fetched: ${eq:,.2f}")
            return eq
    except AlpacaReadUnavailable as exc:
        log.warning(f"Could not fetch Alpaca equity: {exc}")
    return 0.0


def resolve_account_size(
    cli_override: float | None = None,
    *,
    allow_research_fallback: bool = False,
) -> float:
    """Resolve sizing equity; execution never uses an invented broker balance."""
    if cli_override is not None and cli_override > 0:
        return cli_override
    if ACCOUNT_OVERRIDE > 0:
        log.info(f"Using ACCOUNT_OVERRIDE: ${ACCOUNT_OVERRIDE:,.2f}")
        return ACCOUNT_OVERRIDE
    live = _fetch_alpaca_equity()
    if live > 0:
        return live
    if not allow_research_fallback:
        raise AlpacaReadUnavailable(
            "Alpaca equity is unresolved; execution sizing is blocked instead of using a fallback balance"
        )
    log.warning("Could not resolve account size â€” falling back to $5,000")
    return 5_000.0


def _today_realized_loss_pct(trades: list[dict], account: float, today: date | None = None) -> float:
    """Return today's realized loss as a positive fraction of account equity."""
    if account <= 0:
        return 0.0
    today_s = str(today or date.today())
    realized = sum(
        float(trade.get("pnl", 0.0) or 0.0)
        for trade in trades
        if trade.get("status") == "closed"
        and str(trade.get("exit_date") or trade.get("entry_date") or "")[:10] == today_s
    )
    return max(0.0, -realized / account)


# ---------------------------------------------------------------------------
# Price helpers
# ---------------------------------------------------------------------------

def _spot(sym: str) -> float:
    try:
        return float(yf.Ticker(sym).fast_info["last_price"])
    except Exception:
        try:
            return float(yf.Ticker(sym).info.get("regularMarketPrice") or 0)
        except Exception:
            return 0.0


def _prev_close(sym: str) -> float:
    try:
        h = yf.Ticker(sym).history(period="2d", auto_adjust=True)
        return float(h["Close"].iloc[-2]) if len(h) >= 2 else 0.0
    except Exception:
        return 0.0


def _prior_reference_levels(sym: str, now_et: datetime | None = None) -> dict:
    """Return completed prior-day and prior-week levels for shadow research."""
    now_et = now_et or _now_et()
    try:
        history = yf.Ticker(sym).history(period="1mo", interval="1d", auto_adjust=True)
        if history.empty:
            raise ValueError("daily history unavailable")
        index = pd.to_datetime(history.index)
        if index.tz is not None:
            dates = index.tz_convert("America/New_York").date
        else:
            dates = index.date
        completed = history.loc[[day < now_et.date() for day in dates]].copy()
        completed_dates = [day for day in dates if day < now_et.date()]
        if completed.empty:
            raise ValueError("no completed daily bars")
        previous = completed.iloc[-1]
        current_monday = now_et.date() - timedelta(days=now_et.weekday())
        previous_monday = current_monday - timedelta(days=7)
        prior_week_mask = [previous_monday <= day < current_monday for day in completed_dates]
        prior_week = completed.loc[prior_week_mask]
        if prior_week.empty:
            prior_week = completed.iloc[-5:]
        return {
            "status": "observed_completed_bars",
            "prior_day_high": float(previous["High"]),
            "prior_day_low": float(previous["Low"]),
            "prior_week_high": float(prior_week["High"].max()),
            "prior_week_low": float(prior_week["Low"].min()),
        }
    except Exception as exc:
        return {
            "status": "unavailable",
            "error": str(exc)[:160],
            "prior_day_high": None,
            "prior_day_low": None,
            "prior_week_high": None,
            "prior_week_low": None,
        }


def _vix_term_structure_regime(vix: float, vix3m: float) -> dict:
    if vix <= 0 or vix3m <= 0:
        return {"regime": "unknown", "ratio": 0.0}
    ratio = round(vix3m / vix, 4)
    if vix > vix3m:
        regime = "backwardation"
    elif ratio >= 1.03:
        regime = "contango"
    else:
        regime = "flat"
    return {"regime": regime, "ratio": ratio, "vix": vix, "vix3m": vix3m}


def _vix_term_structure_direction_ok(direction: str, regime: dict) -> bool:
    name = str(regime.get("regime") or "unknown")
    if direction == "bull" and name == "backwardation":
        return False
    return True


def _shadow_defensive_exit_reason(consensus_exit: dict, pnl_pct: float) -> str:
    if consensus_exit.get("action") != "review_exit":
        return ""
    blockers = {str(item) for item in (consensus_exit.get("blockers") or [])}
    severe = sorted(blockers.intersection(SHADOW_DEFENSIVE_EXIT_BLOCKERS))
    if not severe:
        return ""
    if pnl_pct > SHADOW_DEFENSIVE_EXIT_LOSS_PCT:
        return ""
    blocker_text = ",".join(severe[:4])
    return f"SHADOW DEFENSIVE EXIT {pnl_pct:+.1f}% ({blocker_text})"


def _noise_area_structural_exit_reason(trade: dict, now_et: datetime | None = None) -> str:
    """Exit a paper Noise Area trade when SPY loses its band/VWAP support."""
    if not PAPER or trade.get("strategy") != "noise_area_vwap":
        return ""
    context = _noise_area_context("SPY", now_et=now_et, for_exit=True)
    close = float(context.get("close") or 0.0)
    vwap = float(context.get("vwap") or 0.0)
    upper = float(context.get("upper_band") or 0.0)
    lower = float(context.get("lower_band") or 0.0)
    if min(close, vwap, upper, lower) <= 0:
        return ""
    if trade.get("right") == "CALL":
        stop = max(upper, vwap)
        if close < stop:
            return f"NOISE AREA STRUCTURE EXIT close={close:.2f} stop={stop:.2f}"
    if trade.get("right") == "PUT":
        stop = min(lower, vwap)
        if close > stop:
            return f"NOISE AREA STRUCTURE EXIT close={close:.2f} stop={stop:.2f}"
    return ""


def _fetch_vix_term_structure() -> dict:
    try:
        context = fetch_vix_term_structure_context()
        if context.get("available") is False:
            raise ValueError(context.get("error", "CBOE VIX/VIX3M unavailable"))
        regime = {
            "regime": context["regime"],
            "ratio": context["vix3m_over_vix"],
            "vix": context["vix"],
            "vix3m": context["vix3m"],
            "source": context["source"],
            "date": context["date"],
        }
        log.info(
            f"VIX term structure: VIX={regime['vix']:.2f} VIX3M={regime['vix3m']:.2f} "
            f"ratio={regime['ratio']:.3f} regime={regime['regime']} source={regime['source']}"
        )
        return regime
    except Exception as exc:
        log.warning(f"VIX term structure fetch failed: {exc} - proceeding without filter")
        return {"regime": "unknown", "ratio": 0.0}


def _intraday_bars(sym: str):
    try:
        bars = yf.Ticker(sym).history(period="1d", interval="1m", auto_adjust=True)
        if bars is None or bars.empty:
            _INTRADAY_DATA_ISSUES[sym] = "insufficient_bars"
            return None
        if isinstance(bars.index, pd.DatetimeIndex):
            last_bar = pd.Timestamp(bars.index[-1])
            if last_bar.tzinfo is not None:
                last_bar = last_bar.tz_convert("America/New_York")
            if last_bar.date() != date.today():
                _INTRADAY_DATA_ISSUES[sym] = "stale_session"
                log.warning(
                    f"Intraday [{sym}]: stale session {last_bar.date()} != {date.today()} - skip"
                )
                return None
        _INTRADAY_DATA_ISSUES.pop(sym, None)
        return bars
    except Exception:
        _INTRADAY_DATA_ISSUES[sym] = "intraday_fetch_failed"
        return None


def _day_type_snapshot(sym: str, *, now_et: datetime | None = None) -> dict:
    """Classify the session point in time; advisory until forward validation."""
    now_et = now_et or _now_et()
    if now_et.time() < dtime(10, 0):
        return {
            "day_type": "unknown",
            "recommended_strategy": "observe",
            "confidence": "low",
            "signals_supporting": ["waiting_for_10_et"],
            "authority": "advisory_shadow_router",
            "execution_enabled": False,
            "can_submit_orders": False,
        }
    bars = _intraday_bars(sym)
    if bars is None:
        return {
            "day_type": "unknown",
            "recommended_strategy": "observe",
            "confidence": "low",
            "signals_supporting": ["market_data_unavailable"],
            "authority": "advisory_shadow_router",
            "execution_enabled": False,
            "can_submit_orders": False,
        }
    high_impact = any(day == date.today() for day, _name, _mode in CATALYST_DAYS)
    try:
        result = classify_intraday_day_type(
            _completed_intraday_bars(bars, now_et=now_et),
            prior_close=_prev_close(sym),
            econ_calendar_high_impact=high_impact,
            now_et=now_et,
        )
        return result.to_dict()
    except Exception as exc:
        log.warning(f"Day type [{sym}] failed: {exc}")
        return {
            "day_type": "unknown",
            "recommended_strategy": "observe",
            "confidence": "low",
            "signals_supporting": ["classification_failed"],
            "error": str(exc)[:160],
            "authority": "advisory_shadow_router",
            "execution_enabled": False,
            "can_submit_orders": False,
        }


def _underlying_mark_snapshot(sym: str, *, now_et: datetime | None = None) -> dict:
    """Capture forward underlying structure for the shadow exit tournament."""
    bars = _intraday_bars(sym)
    if bars is None:
        return {"underlying_mark_status": "unavailable"}
    frame = _completed_intraday_bars(bars, now_et=now_et).copy()
    frame.columns = [str(column).lower() for column in frame.columns]
    frame = frame.dropna(subset=["high", "low", "close"])
    if frame.empty:
        return {"underlying_mark_status": "unavailable"}
    volume = frame.get("volume")
    vwap = None
    if volume is not None and float(volume.fillna(0).sum()) > 0:
        typical = (frame["high"] + frame["low"] + frame["close"]) / 3.0
        vwap_series = (typical * volume).cumsum() / volume.cumsum().replace(0, pd.NA)
        if pd.notna(vwap_series.iloc[-1]):
            vwap = float(vwap_series.iloc[-1])
    prior_5m = None
    if isinstance(frame.index, pd.DatetimeIndex):
        five_minute = frame["close"].resample("5min").last().dropna()
        if len(five_minute) >= 2:
            prior_5m = float(five_minute.iloc[-2])
    complete = vwap is not None and prior_5m is not None
    return {
        "underlying_mark_status": "observed_forward" if complete else "incomplete_forward",
        "underlying_close": round(float(frame["close"].iloc[-1]), 4),
        "underlying_vwap": round(vwap, 4) if vwap is not None else None,
        "underlying_prior_5m_close": round(prior_5m, 4) if prior_5m is not None else None,
        "underlying_timestamp": (
            pd.Timestamp(frame.index[-1]).isoformat()
            if isinstance(frame.index, pd.DatetimeIndex) else None
        ),
    }


def _fresh_vwap_ema_pullback(
    df: pd.DataFrame,
    direction: str,
    *,
    lookback_bars: int = TREND_PULLBACK_LOOKBACK_BARS,
    tolerance_bps: float = TREND_PULLBACK_TOLERANCE_BPS,
) -> bool:
    """Require an actual recent support/resistance test and confirming close."""
    if len(df) < 4 or not {"High", "Low", "Close", "vwap", "ema50"}.issubset(df.columns):
        return False
    prior = df.iloc[max(0, len(df) - lookback_bars - 1):-1]
    if prior.empty:
        return False
    tolerance = max(0.0, float(tolerance_bps)) / 10_000.0
    current = df.iloc[-1]
    previous = df.iloc[-2]
    current_close = float(current["Close"])
    previous_close = float(previous["Close"])
    current_open = float(current.get("Open", current_close))
    current_vwap = float(current["vwap"])
    current_ema = float(current["ema50"])

    if direction == "bull":
        support = prior[["vwap", "ema50"]].max(axis=1)
        touched = (
            (prior["Low"] <= support * (1.0 + tolerance))
            & (prior["High"] >= support * (1.0 - tolerance))
        ).any()
        confirmed = (
            current_close > current_vwap
            and current_close > current_ema
            and current_close > previous_close
            and current_close >= current_open
        )
    elif direction == "bear":
        resistance = prior[["vwap", "ema50"]].min(axis=1)
        touched = (
            (prior["High"] >= resistance * (1.0 - tolerance))
            & (prior["Low"] <= resistance * (1.0 + tolerance))
        ).any()
        confirmed = (
            current_close < current_vwap
            and current_close < current_ema
            and current_close < previous_close
            and current_close <= current_open
        )
    else:
        return False
    return bool(touched and confirmed)


def _vwap_50ema_signal(hist, sym: str = "?") -> dict | None:
    if hist is None or len(hist) < BEAR_TREND_MIN_BARS:
        bars = len(hist) if hist is not None else 0
        log.info(f"Bear trend [{sym}]: insufficient bars {bars} < {BEAR_TREND_MIN_BARS} â€” skip")
        return None
    required = {"High", "Low", "Close", "Volume"}
    if not required.issubset(set(hist.columns)):
        log.info(f"Bear trend [{sym}]: missing columns {required - set(hist.columns)} â€” skip")
        return None

    df = _completed_intraday_bars(hist).dropna(subset=["High", "Low", "Close", "Volume"]).copy()
    if len(df) < BEAR_TREND_MIN_BARS:
        log.info(f"Bear trend [{sym}]: bars after dropna {len(df)} < {BEAR_TREND_MIN_BARS} â€” skip")
        return None

    typical = (df["High"] + df["Low"] + df["Close"]) / 3
    cumulative_volume = df["Volume"].cumsum()
    if float(cumulative_volume.iloc[-1]) <= 0:
        log.info(f"Bear trend [{sym}]: zero cumulative volume â€” skip")
        return None

    df["vwap"] = (typical * df["Volume"]).cumsum() / cumulative_volume
    df["ema50"] = df["Close"].ewm(span=50, adjust=False).mean()

    close = float(df["Close"].iloc[-1])
    prev_close = float(df["Close"].iloc[-2])
    vwap = float(df["vwap"].iloc[-1])
    ema50 = float(df["ema50"].iloc[-1])
    ema50_prev = float(df["ema50"].iloc[-6]) if len(df) >= 6 else float(df["ema50"].iloc[0])
    session_open = float(df["Open"].iloc[0]) if "Open" in df.columns else float(df["Close"].iloc[0])
    vwap_distance = (vwap - close) / vwap if vwap > 0 else 0.0

    below_vwap = close < vwap
    below_ema = close < ema50
    ema_down = ema50 < ema50_prev
    red_session = close < session_open
    not_chasing = 0 <= vwap_distance <= BEAR_TREND_MAX_VWAP_EXT
    lower_high_pullback = _fresh_vwap_ema_pullback(df, "bear")

    checks = [
        (below_vwap,        2, "below VWAP"),
        (below_ema,         2, "below 50EMA"),
        (ema_down,          1, "50EMA sloping down"),
        (red_session,       1, "red session"),
        (not_chasing,       2, "not extended from VWAP"),
        (lower_high_pullback, 1, "pullback failed near trend"),
    ]
    score = 0
    reasons = []
    for ok, points, reason in checks:
        if ok:
            score += points
            reasons.append(reason)

    log.info(
        f"Bear trend [{sym}]: close={close:.2f} VWAP={vwap:.2f} EMA50={ema50:.2f} "
        f"vwap_dist={vwap_distance*100:.2f}% score={min(10,score)}/10 "
        f"[below_vwap={below_vwap} below_ema={below_ema} ema_down={ema_down} "
        f"red={red_session} not_chasing={not_chasing} pullback={lower_high_pullback}] "
        f"reasons={reasons}"
    )

    return {
        "score": min(10, score),
        "close": close,
        "vwap": vwap,
        "ema50": ema50,
        "vwap_distance": vwap_distance,
        "fresh_pullback_confirmed": lower_high_pullback,
        "reasons": reasons,
    }


def _option_mid(occ_symbol: str) -> float:
    try:
        r = req.get(
            "https://data.alpaca.markets/v1beta1/options/snapshots",
            headers=HDR, params={"symbols": occ_symbol}, timeout=10,
        )
        if r.status_code != 200:
            return 0.0
        snap  = r.json().get("snapshots", {}).get(occ_symbol, {})
        quote = snap.get("latestQuote", {})
        bid   = float(quote.get("bp", 0) or 0)
        ask   = float(quote.get("ap", 0) or 0)
        quote_ts = quote.get("t")
        quote_age = None
        if quote_ts:
            try:
                parsed = datetime.fromisoformat(str(quote_ts).replace("Z", "+00:00"))
                quote_age = max(0.0, (datetime.now(timezone.utc) - parsed.astimezone(timezone.utc)).total_seconds())
            except (TypeError, ValueError):
                quote_age = None
        _OPTION_QUOTE_TELEMETRY[occ_symbol] = {
            "selection_bid": bid or None,
            "selection_ask": ask or None,
            "quote_timestamp": quote_ts,
            "quote_age_seconds": round(quote_age, 3) if quote_age is not None else None,
        }
        if bid > 0 and ask > 0:
            return round((bid + ask) / 2, 3)
        return float(snap.get("latestTrade", {}).get("p", 0) or 0)
    except Exception:
        return 0.0


def _option_snapshot_map(occ_symbols: list[str]) -> dict[str, dict]:
    """Fetch quote and Greek snapshots in one research-only batch."""
    symbols = [str(symbol) for symbol in occ_symbols if symbol]
    if not symbols:
        return {}
    try:
        response = req.get(
            "https://data.alpaca.markets/v1beta1/options/snapshots",
            headers=HDR,
            params={"symbols": ",".join(symbols)},
            timeout=10,
        )
        if response.status_code != 200:
            return {}
        return response.json().get("snapshots", {}) or {}
    except Exception:
        return {}


def _snapshot_quote_and_delta(snapshot: dict) -> dict:
    quote = snapshot.get("latestQuote", {}) if isinstance(snapshot, dict) else {}
    greeks = snapshot.get("greeks", {}) if isinstance(snapshot, dict) else {}
    bid = float(quote.get("bp", 0.0) or 0.0)
    ask = float(quote.get("ap", 0.0) or 0.0)
    delta = greeks.get("delta")
    return {
        "bid": bid or None,
        "ask": ask or None,
        "quote_timestamp": quote.get("t"),
        "delta": float(delta) if delta is not None else None,
        "mid": round((bid + ask) / 2.0, 3) if bid > 0 and ask >= bid else None,
    }


def _selection_quote_fields(occ_symbol: str) -> dict:
    cached = _OPTION_QUOTE_TELEMETRY.get(occ_symbol) or {}
    return {
        "selection_bid": cached.get("selection_bid"),
        "selection_ask": cached.get("selection_ask"),
        "quote_timestamp": cached.get("quote_timestamp"),
        "quote_age_seconds": cached.get("quote_age_seconds"),
    }


def _option_bid_ask_spread_cents(occ_symbol: str) -> int | None:
    """Return bid-ask spread in cents, or None if unavailable."""
    try:
        r = req.get(
            "https://data.alpaca.markets/v1beta1/options/snapshots",
            headers=HDR, params={"symbols": occ_symbol}, timeout=10,
        )
        if r.status_code != 200:
            return None
        snap  = r.json().get("snapshots", {}).get(occ_symbol, {})
        quote = snap.get("latestQuote", {})
        bid   = float(quote.get("bp", 0) or 0)
        ask   = float(quote.get("ap", 0) or 0)
        if bid > 0 and ask > 0:
            return int(round((ask - bid) * 100))
        return None
    except Exception:
        return None


def _extract_underlying(sym: str) -> str:
    """Return underlying ticker from OCC option symbol or equity symbol as-is."""
    for i, ch in enumerate(sym):
        if ch.isdigit():
            return sym[:i]
    return sym


def _fetch_broker_open_symbols() -> set[str] | None:
    """Fetch open positions from Alpaca and return underlying tickers (broker truth)."""
    try:
        positions = _get("/v2/positions")
        if not isinstance(positions, list):
            raise ValueError("positions response was not a list")
        syms = {_extract_underlying(str(p.get("symbol", ""))) for p in positions if p.get("symbol")}
        syms.discard("")
        log.info(f"Broker open position underlyings: {sorted(syms)}")
        return syms
    except (AlpacaReadUnavailable, ValueError) as exc:
        log.error(f"Broker positions unresolved; entries fail closed: {exc}")
        return None


def _vwap_50ema_bull_signal(hist, sym: str = "?") -> dict | None:
    if hist is None or len(hist) < BEAR_TREND_MIN_BARS:
        return None
    required = {"High", "Low", "Close", "Volume"}
    if not required.issubset(set(hist.columns)):
        return None
    df = _completed_intraday_bars(hist).dropna(subset=["High", "Low", "Close", "Volume"]).copy()
    if len(df) < BEAR_TREND_MIN_BARS:
        return None

    typical = (df["High"] + df["Low"] + df["Close"]) / 3
    cumulative_volume = df["Volume"].cumsum()
    if float(cumulative_volume.iloc[-1]) <= 0:
        return None
    df["vwap"] = (typical * df["Volume"]).cumsum() / cumulative_volume
    df["ema50"] = df["Close"].ewm(span=50, adjust=False).mean()

    close = float(df["Close"].iloc[-1])
    prev_close = float(df["Close"].iloc[-2])
    vwap = float(df["vwap"].iloc[-1])
    ema50 = float(df["ema50"].iloc[-1])
    ema50_prev = float(df["ema50"].iloc[-6]) if len(df) >= 6 else float(df["ema50"].iloc[0])
    session_open = float(df["Open"].iloc[0]) if "Open" in df.columns else float(df["Close"].iloc[0])
    vwap_distance = (close - vwap) / vwap if vwap > 0 else 0.0
    fresh_pullback = _fresh_vwap_ema_pullback(df, "bull")

    checks = [
        (close > vwap, 2, "above VWAP"),
        (close > ema50, 2, "above 50EMA"),
        (ema50 > ema50_prev, 1, "50EMA sloping up"),
        (close > session_open, 1, "green session"),
        (0 <= vwap_distance <= BEAR_TREND_MAX_VWAP_EXT, 2, "not extended from VWAP"),
        (fresh_pullback, 1, "fresh pullback held trend"),
    ]
    score = 0
    reasons = []
    for ok, points, reason in checks:
        if ok:
            score += points
            reasons.append(reason)
    log.info(
        f"Bull trend [{sym}]: close={close:.2f} VWAP={vwap:.2f} EMA50={ema50:.2f} "
        f"vwap_dist={vwap_distance*100:.2f}% score={min(10, score)}/10 reasons={reasons}"
    )
    return {
        "score": min(10, score),
        "close": close,
        "vwap": vwap,
        "ema50": ema50,
        "vwap_distance": vwap_distance,
        "fresh_pullback_confirmed": fresh_pullback,
        "reasons": reasons,
    }


# ---------------------------------------------------------------------------
# Setup finders
# ---------------------------------------------------------------------------

def _atm_option(sym: str, right: str) -> tuple[str, float, float, str]:
    """(occ, strike, price, expiry)"""
    try:
        t       = yf.Ticker(sym)
        price   = _spot(sym)
        if price <= 0:
            return "", 0.0, 0.0, ""
        today_s = date.today().strftime("%Y-%m-%d")
        exp     = next((e for e in t.options if e >= today_s), None)
        if not exp:
            return "", 0.0, 0.0, ""
        chain = t.option_chain(exp)
        df    = chain.calls if right == "CALL" else chain.puts
        if df.empty:
            return "", 0.0, 0.0, ""
        row    = df.iloc[(df['strike'] - price).abs().argsort()[:1]]
        strike = float(row['strike'].values[0])
        occ = _occ(sym, exp, right, strike)
        live_mid = _option_mid(occ)
        px = live_mid if live_mid > 0 else float(row['lastPrice'].values[0])
        return occ, strike, px, exp
    except Exception:
        return "", 0.0, 0.0, ""


def _noise_area_history(sym: str) -> pd.DataFrame | None:
    """Fetch enough regular-session 5-minute history for 14 prior sessions."""
    try:
        bars = yf.Ticker(sym).history(
            period="30d",
            interval="5m",
            auto_adjust=True,
            prepost=False,
        )
        return bars if bars is not None and not bars.empty else None
    except Exception as exc:
        log.warning(f"Noise Area [{sym}] history unavailable: {exc}")
        return None


def _noise_area_context(
    sym: str = "SPY",
    now_et: datetime | None = None,
    *,
    for_exit: bool = False,
) -> dict:
    """Evaluate the research model point in time without granting authority."""
    now_et = now_et or _now_et()
    current = _intraday_bars(sym)
    history = _noise_area_history(sym)
    if current is None or history is None:
        return {
            "strategy": "noise_area_vwap",
            "status": "market_data_unavailable",
            "entry_ready": False,
            "direction": "neutral",
            "can_submit_orders": False,
        }
    try:
        return evaluate_noise_area(
            current,
            history,
            previous_close=_prev_close(sym),
            now_et=now_et,
            lookback_sessions=NOISE_AREA_LOOKBACK_SESSIONS,
            checkpoint_minutes=tuple(range(60)) if for_exit else (0, 30),
            entry_start=dtime(9, 30) if for_exit else dtime(10, 0),
            entry_end=dtime(15, 55) if for_exit else dtime(13, 0),
        )
    except Exception as exc:
        log.warning(f"Noise Area [{sym}] evaluation failed: {exc}")
        return {
            "strategy": "noise_area_vwap",
            "status": "evaluation_failed",
            "error": str(exc)[:160],
            "entry_ready": False,
            "direction": "neutral",
            "can_submit_orders": False,
        }


def _shadow_contract_challengers(setup: dict, max_otm_steps: int = 2) -> list[dict]:
    """Capture ATM, delta-targeted ITM, and OTM alternatives for research."""
    symbol = str(setup.get("symbol") or "").upper()
    right = str(setup.get("right") or "").upper()
    expiry = str(setup.get("expiry") or "")
    base_strike = float(setup.get("strike") or 0.0)
    base_occ = str(setup.get("option_symbol") or "")
    if not symbol or right not in {"CALL", "PUT"} or not expiry or base_strike <= 0 or not base_occ:
        return []
    try:
        chain = yf.Ticker(symbol).option_chain(expiry)
        frame = chain.calls if right == "CALL" else chain.puts
        strikes = sorted({float(value) for value in frame["strike"].tolist()})
    except Exception:
        return []
    otm = (
        [strike for strike in strikes if strike > base_strike]
        if right == "CALL"
        else sorted((strike for strike in strikes if strike < base_strike), reverse=True)
    )
    itm = (
        sorted((strike for strike in strikes if strike < base_strike), reverse=True)
        if right == "CALL"
        else [strike for strike in strikes if strike > base_strike]
    )
    itm_symbols = [_occ(symbol, expiry, right, strike) for strike in itm[:6]]
    itm_snapshots = _option_snapshot_map(itm_symbols)
    delta_choices: list[tuple[float, float, str]] = []
    for strike, occ in zip(itm[:6], itm_symbols):
        details = _snapshot_quote_and_delta(itm_snapshots.get(occ, {}))
        absolute_delta = abs(float(details.get("delta") or 0.0))
        if 0.55 <= absolute_delta <= 0.70:
            delta_choices.append((abs(absolute_delta - 0.60), strike, occ))

    candidates = [("atm", 0, base_strike, base_occ, None)]
    if delta_choices:
        _, strike, occ = min(delta_choices, key=lambda item: item[0])
        delta = _snapshot_quote_and_delta(itm_snapshots.get(occ, {})).get("delta")
        candidates.append(("itm_delta_60", -1, strike, occ, delta))
    for step, strike in enumerate(otm[:max(0, max_otm_steps)], start=1):
        candidates.append((f"otm_{step}", step, strike, _occ(symbol, expiry, right, strike), None))

    rows: list[dict] = []
    for variant, step, strike, occ, observed_delta in candidates:
        if variant == "atm":
            mid = float(setup.get("entry_price_est") or 0.0)
        else:
            mid = _option_mid(occ)
        quote = _selection_quote_fields(occ)
        if mid <= 0:
            continue
        bid = float(quote.get("selection_bid") or 0.0)
        ask = float(quote.get("selection_ask") or 0.0)
        passive_mid = round((bid + ask) / 2.0, 2) if bid > 0 and ask >= bid else None
        passive_plus_tick = min(ask, passive_mid + 0.01) if passive_mid is not None else None
        rows.append({
            "variant": variant,
            "otm_steps": step,
            "option_symbol": occ,
            "strike": strike,
            "selection_delta": round(float(observed_delta), 4) if observed_delta is not None else None,
            "entry_mid": round(mid, 3),
            "entry_bid": quote.get("selection_bid"),
            "entry_ask": quote.get("selection_ask"),
            "entry_quote_timestamp": quote.get("quote_timestamp"),
            "entry_quote_age_seconds": quote.get("quote_age_seconds"),
            "passive_limit_mid": passive_mid,
            "passive_limit_mid_plus_tick": round(passive_plus_tick, 2) if passive_plus_tick is not None else None,
            "marketable_limit_ask": round(ask, 2) if ask > 0 else None,
            "passive_fill_model": "future_observed_ask_at_or_below_limit",
            "execution_mode": "shadow_only",
            "live_execution_allowed": False,
        })
    snapshots = _option_snapshot_map([str(row["option_symbol"]) for row in rows])
    expected_move = float(setup.get("expected_move_points") or 0.0)
    spot = float(setup.get("underlying_spot_at_selection") or _spot(symbol) or 0.0)
    rank_inputs = []
    for row in rows:
        details = _snapshot_quote_and_delta(snapshots.get(str(row["option_symbol"]), {}))
        bid = float(row.get("entry_bid") or details.get("bid") or 0.0)
        ask = float(row.get("entry_ask") or details.get("ask") or 0.0)
        mid = (bid + ask) / 2.0 if bid > 0 and ask >= bid else 0.0
        rank_inputs.append({
            **row,
            "right": right,
            "delta": row.get("selection_delta") if row.get("selection_delta") is not None else details.get("delta"),
            "spread_pct": ((ask - bid) / mid * 100.0) if mid > 0 else None,
            "quote_age_seconds": row.get("entry_quote_age_seconds"),
            "expected_move_room": abs(float(row["strike"]) - spot) / expected_move if expected_move > 0 else None,
            "premium_expansion_pct": setup.get("premium_expansion_pct"),
        })
    return rank_contracts(rank_inputs)


def _selected_contract_rank_snapshot(setup: dict, spot: float) -> dict:
    """Score the selected contract without changing which contract is traded."""
    occ = str(setup.get("option_symbol") or "")
    bid = float(setup.get("selection_bid") or 0.0)
    ask = float(setup.get("selection_ask") or 0.0)
    if not occ or bid <= 0 or ask < bid:
        return {"contract_rank_status": "unavailable"}
    mid = (bid + ask) / 2.0 if bid > 0 and ask >= bid else 0.0
    snapshot = _option_snapshot_map([occ]).get(occ, {})
    delta = _snapshot_quote_and_delta(snapshot).get("delta")
    expected_move = float(setup.get("expected_move_points") or 0.0)
    ranked = rank_contracts([{
        "option_symbol": occ,
        "strike": setup.get("strike"),
        "right": setup.get("right"),
        "delta": delta,
        "spread_pct": ((ask - bid) / mid * 100.0) if mid > 0 else None,
        "quote_age_seconds": setup.get("quote_age_seconds"),
        "expected_move_room": abs(float(setup.get("strike") or 0.0) - spot) / expected_move if expected_move > 0 else None,
        "premium_expansion_pct": setup.get("premium_expansion_pct"),
    }])
    if not ranked:
        return {"contract_rank_status": "unavailable"}
    contract_rank = ranked[0]["contract_rank"]
    return {
        "contract_rank_status": "observed_research_only",
        "contract_rank": contract_rank,
        "contract_rank_score": contract_rank["composite_score"],
        "contract_rank_disqualified": contract_rank["disqualified"],
        "contract_rank_authority": "research_only_no_selection_change",
    }


def _mark_shadow_contract_challengers(first: dict) -> list[dict]:
    """Mark shadow contract alternatives using bid exits; never submits orders."""
    marked: list[dict] = []
    for challenger in first.get("contract_selection_challengers") or []:
        if not isinstance(challenger, dict):
            continue
        occ = str(challenger.get("option_symbol") or "")
        if not occ:
            continue
        mid = _option_mid(occ)
        quote = _selection_quote_fields(occ)
        entry_mid = float(challenger.get("entry_mid") or 0.0)
        entry_ask = float(challenger.get("entry_ask") or 0.0)
        current_bid = float(quote.get("selection_bid") or 0.0)
        current_ask = float(quote.get("selection_ask") or 0.0)
        row = dict(challenger)
        row.update({
            "current_mid": round(mid, 3) if mid > 0 else None,
            "current_bid": current_bid or None,
            "current_ask": quote.get("selection_ask"),
            "mark_quote_timestamp": quote.get("quote_timestamp"),
            "mark_quote_age_seconds": quote.get("quote_age_seconds"),
            "gross_mid_return_pct": (
                round((mid - entry_mid) / entry_mid * 100, 2)
                if mid > 0 and entry_mid > 0 else None
            ),
            "executable_return_pct": (
                round((current_bid - entry_ask) / entry_ask * 100, 2)
                if current_bid > 0 and entry_ask > 0 else None
            ),
            "passive_mid_fill_observed": bool(
                current_ask > 0
                and float(challenger.get("passive_limit_mid") or 0.0) > 0
                and current_ask <= float(challenger["passive_limit_mid"])
            ),
            "passive_plus_tick_fill_observed": bool(
                current_ask > 0
                and float(challenger.get("passive_limit_mid_plus_tick") or 0.0) > 0
                and current_ask <= float(challenger["passive_limit_mid_plus_tick"])
            ),
        })
        marked.append(row)
    return marked


def _orb_signal(sym: str) -> dict | None:
    """5-min opening range breakout (first 5 bars 9:30â€“9:35 ET). Returns direction + key levels."""
    try:
        bars = _intraday_bars(sym)
        if bars is None or len(bars) < 10:
            return None
        orb_bars = bars.iloc[:5]
        orb_high = float(orb_bars["High"].max())
        orb_low  = float(orb_bars["Low"].min())
        close    = float(bars["Close"].iloc[-1])
        if orb_high <= orb_low:
            return None
        range_pct = round((orb_high - orb_low) / orb_low * 100, 3)
        direction = "bear" if close < orb_low else "bull" if close > orb_high else "neutral"
        previous_close = bars["Close"].shift(1)
        true_range = pd.concat(
            [
                bars["High"] - bars["Low"],
                (bars["High"] - previous_close).abs(),
                (bars["Low"] - previous_close).abs(),
            ],
            axis=1,
        ).max(axis=1)
        baseline_atr5 = float(true_range.iloc[-6:-1].mean()) if len(true_range) >= 6 else 0.0
        breakout_candle_range = float(bars["High"].iloc[-1] - bars["Low"].iloc[-1])
        breakout_candle_atr_ratio = (
            round(breakout_candle_range / baseline_atr5, 3)
            if baseline_atr5 > 0
            else None
        )
        log.info(
            f"ORB [{sym}]: high={orb_high:.2f} low={orb_low:.2f} "
            f"close={close:.2f} range={range_pct:.2f}% direction={direction} "
            f"breakout_atr_ratio={breakout_candle_atr_ratio}"
        )
        return {"orb_high": orb_high, "orb_low": orb_low, "close": close,
                "direction": direction, "range_pct": range_pct,
                "breakout_candle_range": round(breakout_candle_range, 4),
                "baseline_atr5": round(baseline_atr5, 4) if baseline_atr5 > 0 else None,
                "breakout_candle_atr_ratio": breakout_candle_atr_ratio}
    except Exception as exc:
        log.warning(f"ORB [{sym}] failed: {exc}")
        return None


def _completed_intraday_bars(bars: pd.DataFrame, now_et: datetime | None = None) -> pd.DataFrame:
    """Exclude an in-progress one-minute bar before evaluating a close."""
    if not isinstance(bars.index, pd.DatetimeIndex) or bars.empty:
        return bars
    now_et = now_et or _now_et()
    index = bars.index
    if index.tz is None:
        comparable_now = pd.Timestamp(now_et).tz_localize(None)
    else:
        comparable_now = pd.Timestamp(now_et).tz_convert(index.tz)
    return bars.loc[index + pd.Timedelta(minutes=1) <= comparable_now]


def _orb_retest_tolerance(level: float, opening_range: float) -> float:
    raw = opening_range * ORB_RETEST_RANGE_FRACTION
    minimum = level * ORB_RETEST_MIN_TOLERANCE_BPS / 10_000.0
    maximum = level * ORB_RETEST_MAX_TOLERANCE_BPS / 10_000.0
    return max(minimum, min(raw, maximum))


def _trend_orb_context_blocker(direction: str, signal: dict, orb: dict | None) -> dict | None:
    """Prevent trend entries from chasing a mature or conflicting ORB move."""
    if not orb:
        return {"reason": "trend_orb_context_unavailable"}
    orb_direction = str(orb.get("direction") or "neutral")
    expected_direction = "bull" if direction == "bull" else "bear"
    if orb_direction not in {"neutral", expected_direction}:
        return {
            "reason": "trend_orb_direction_conflict",
            "trend_direction": expected_direction,
            "orb_direction": orb_direction,
        }
    try:
        orb_high = float(orb.get("orb_high") or 0.0)
        orb_low = float(orb.get("orb_low") or 0.0)
        close = float(signal.get("close") or 0.0)
    except (TypeError, ValueError):
        return {"reason": "trend_orb_context_invalid"}
    orb_range = orb_high - orb_low
    if orb_range <= 0 or close <= 0:
        return {"reason": "trend_orb_context_invalid"}
    extension = (close - orb_high) / orb_range if direction == "bull" else (orb_low - close) / orb_range
    if (
        orb_direction == expected_direction
        and extension > TREND_MAX_ORB_EXTENSION_FRACTION
        and not bool(orb.get("entry_ready"))
    ):
        return {
            "reason": "trend_orb_extension_without_fresh_retest",
            "trend_direction": expected_direction,
            "orb_direction": orb_direction,
            "orb_retest_status": orb.get("retest_status"),
            "orb_extension_fraction": round(extension, 3),
            "maximum_extension_fraction": TREND_MAX_ORB_EXTENSION_FRACTION,
        }
    return None


def _orb_dislocation_features(bars: pd.DataFrame, breakout_pos: int, direction: str) -> dict:
    """Measure breakout true-range dislocation and close location point in time."""
    previous_close = bars["Close"].shift(1)
    true_range = pd.concat(
        [
            bars["High"] - bars["Low"],
            (bars["High"] - previous_close).abs(),
            (bars["Low"] - previous_close).abs(),
        ],
        axis=1,
    ).max(axis=1)
    breakout = bars.iloc[breakout_pos]
    candle_range = float(breakout["High"] - breakout["Low"])
    clv = 0.0 if candle_range <= 0 else (
        (2.0 * float(breakout["Close"]) - float(breakout["High"]) - float(breakout["Low"]))
        / candle_range
    )
    baseline = true_range.iloc[:breakout_pos].dropna()
    result = {
        "orb_breakout_candle_range": round(candle_range, 4),
        "orb_breakout_close_location_value": round(clv, 4),
        "orb_breakout_directional_close_location_value": round(clv if direction == "bull" else -clv, 4),
        "orb_dislocation_measure": "true_range_vs_prior_ewma",
        "orb_dislocation_history_bars": int(len(baseline)),
        "orb_dislocation_status": "insufficient_history",
        "orb_dislocation_velocity_zscore": None,
    }
    if len(baseline) < ORB_OPENING_RANGE_MINUTES:
        return result
    ewma_mean = float(baseline.ewm(span=20, adjust=False).mean().iloc[-1])
    ewma_std_value = baseline.ewm(span=20, adjust=False).std(bias=False).iloc[-1]
    ewma_std = float(ewma_std_value) if pd.notna(ewma_std_value) else 0.0
    result["orb_dislocation_ewma_range"] = round(ewma_mean, 6)
    result["orb_dislocation_ewma_std"] = round(ewma_std, 6) if ewma_std > 0 else None
    if ewma_std > 0 and math.isfinite(ewma_std):
        result["orb_dislocation_velocity_zscore"] = round(
            (float(true_range.iloc[breakout_pos]) - ewma_mean) / ewma_std,
            4,
        )
        result["orb_dislocation_status"] = "observed_at_breakout"
    else:
        result["orb_dislocation_status"] = "zero_variance"
    return result


def _orb_breakout_retest_signal(sym: str) -> dict | None:
    """Return a fresh first-five-minute ORB breakout-retest confirmation."""
    try:
        raw_bars = _intraday_bars(sym)
        if raw_bars is None:
            return None
        bars = _completed_intraday_bars(raw_bars).dropna(subset=["High", "Low", "Close"]).copy()
        if len(bars) < ORB_OPENING_RANGE_MINUTES + 2:
            return None
        opening = bars.iloc[:ORB_OPENING_RANGE_MINUTES]
        orb_high = float(opening["High"].max())
        orb_low = float(opening["Low"].min())
        close = float(bars["Close"].iloc[-1])
        if orb_high <= orb_low:
            return None
        direction = "bear" if close < orb_low else "bull" if close > orb_high else "neutral"
        window_end = min(len(bars), ORB_RETEST_ENTRY_WINDOW_MINUTES)
        if direction == "bull":
            matches = [
                pos for pos in range(ORB_OPENING_RANGE_MINUTES, window_end)
                if float(bars["Close"].iloc[pos]) > orb_high
            ]
            level = orb_high
        elif direction == "bear":
            matches = [
                pos for pos in range(ORB_OPENING_RANGE_MINUTES, window_end)
                if float(bars["Close"].iloc[pos]) < orb_low
            ]
            level = orb_low
        else:
            matches = []
            level = (orb_high + orb_low) / 2.0
        breakout_pos = matches[0] if matches else None
        tolerance = _orb_retest_tolerance(level, orb_high - orb_low)
        retest_pos = None
        invalidated = False
        if breakout_pos is not None:
            for pos in range(breakout_pos + 1, window_end):
                row = bars.iloc[pos]
                if direction == "bull":
                    if float(row["Close"]) < orb_high - tolerance:
                        invalidated = True
                        break
                    touched = orb_high - tolerance <= float(row["Low"]) <= orb_high + tolerance
                    held = float(row["Close"]) > orb_high
                else:
                    if float(row["Close"]) > orb_low + tolerance:
                        invalidated = True
                        break
                    touched = orb_low - tolerance <= float(row["High"]) <= orb_low + tolerance
                    held = float(row["Close"]) < orb_low
                if touched and held:
                    retest_pos = pos
                    break
        if retest_pos is not None:
            for pos in range(retest_pos + 1, len(bars)):
                later_close = float(bars["Close"].iloc[pos])
                if (direction == "bull" and later_close < orb_high - tolerance) or (
                    direction == "bear" and later_close > orb_low + tolerance
                ):
                    invalidated = True
                    break
        retest_age_bars = len(bars) - 1 - retest_pos if retest_pos is not None else None
        retest_fresh = retest_age_bars is not None and retest_age_bars <= ORB_RETEST_MAX_AGE_BARS
        entry_ready = bool(retest_pos is not None and retest_fresh and not invalidated and direction != "neutral")
        if retest_pos is None:
            retest_status = "breakout_invalidated" if invalidated else "awaiting_retest" if breakout_pos is not None else "no_breakout"
        elif invalidated:
            retest_status = "retest_invalidated"
        elif not retest_fresh:
            retest_status = "retest_stale"
        else:
            retest_status = "retest_confirmed_fresh"

        measured_pos = breakout_pos if breakout_pos is not None else len(bars) - 1
        previous_close = bars["Close"].shift(1)
        true_range = pd.concat(
            [
                bars["High"] - bars["Low"],
                (bars["High"] - previous_close).abs(),
                (bars["Low"] - previous_close).abs(),
            ],
            axis=1,
        ).max(axis=1)
        baseline_start = max(0, measured_pos - 5)
        baseline_atr5 = float(true_range.iloc[baseline_start:measured_pos].mean()) if measured_pos > 0 else 0.0
        breakout_candle_range = float(bars["High"].iloc[measured_pos] - bars["Low"].iloc[measured_pos])
        breakout_candle_atr_ratio = (
            round(breakout_candle_range / baseline_atr5, 3)
            if baseline_atr5 > 0 else None
        )
        dislocation = _orb_dislocation_features(
            bars,
            measured_pos,
            direction if direction != "neutral" else "bull",
        )
        retest_quality = None
        if breakout_pos is not None and retest_pos is not None and direction in {"bull", "bear"}:
            retest_quality = score_retest_quality(
                bars,
                breakout_pos=breakout_pos,
                retest_pos=retest_pos,
                direction=direction,
                orb_high=orb_high,
                orb_low=orb_low,
            ).to_dict()

        def _time_text(pos: int | None) -> str | None:
            if pos is None or not isinstance(bars.index, pd.DatetimeIndex):
                return None
            return pd.Timestamp(bars.index[pos]).isoformat()

        log.info(
            f"ORB retest [{sym}]: high={orb_high:.2f} low={orb_low:.2f} close={close:.2f} "
            f"direction={direction} status={retest_status} entry_ready={entry_ready}"
        )
        return {
            "orb_high": orb_high,
            "orb_low": orb_low,
            "close": close,
            "direction": direction,
            "range_pct": round((orb_high - orb_low) / orb_low * 100, 3),
            "breakout_candle_range": round(breakout_candle_range, 4),
            "baseline_atr5": round(baseline_atr5, 4) if baseline_atr5 > 0 else None,
            "breakout_candle_atr_ratio": breakout_candle_atr_ratio,
            "breakout_at": _time_text(breakout_pos),
            "retest_at": _time_text(retest_pos),
            "retest_confirmed": retest_pos is not None,
            "retest_fresh": retest_fresh,
            "retest_age_bars": retest_age_bars,
            "retest_status": retest_status,
            "retest_tolerance": round(tolerance, 4),
            "entry_ready": entry_ready,
            "retest_quality_score": retest_quality.get("raw_score") if retest_quality else None,
            "retest_grade": retest_quality.get("grade") if retest_quality else None,
            "pre_retest_extension_pct": retest_quality.get("pre_retest_extension_pct") if retest_quality else None,
            "minutes_since_breakout": retest_quality.get("minutes_since_breakout") if retest_quality else None,
            "retest_volume_ratio": retest_quality.get("volume_on_test_vs_breakout") if retest_quality else None,
            "retest_quality_details": retest_quality.get("details") if retest_quality else None,
            "retest_quality_authority": "telemetry_only_until_30_forward_entries",
            **dislocation,
        }
    except Exception as exc:
        log.warning(f"ORB retest [{sym}] failed: {exc}")
        return None


def _latest_atm_iv(symbol: str, day: str, path: Path | None = None) -> float | None:
    """Return same-day ATM IV only; stale rows are never reused."""
    path = path or IV_HISTORY_LOG_PATH
    if not path.exists():
        return None
    for raw in reversed(path.read_text(encoding="utf-8-sig").splitlines()):
        try:
            row = json.loads(raw)
        except json.JSONDecodeError:
            continue
        if str(row.get("date") or "")[:10] != day:
            continue
        for scan in row.get("scans") or []:
            if not isinstance(scan, dict) or str(scan.get("symbol") or "").upper() != symbol.upper():
                continue
            try:
                value = float(scan.get("atm_iv") or 0.0)
            except (TypeError, ValueError):
                return None
            return value if math.isfinite(value) and value > 0 else None
        return None
    return None


def _expected_move_entry_snapshot(symbol: str, spot: float, orb: dict | None, *, day: str | None = None) -> dict:
    """Point-in-time expected-move telemetry; never changes entry behavior."""
    day = day or date.today().isoformat()
    atm_iv = _latest_atm_iv(symbol, day)
    if atm_iv is None or spot <= 0 or not orb:
        return {"expected_move_telemetry_status": "unavailable"}
    expected_move = spot * atm_iv / math.sqrt(252.0)
    high = float(orb.get("orb_high") or 0.0)
    low = float(orb.get("orb_low") or 0.0)
    current = float(orb.get("close") or spot)
    if expected_move <= 0 or high <= low:
        return {"expected_move_telemetry_status": "unavailable"}
    opening_fraction = (high - low) / expected_move
    if opening_fraction < 0.20:
        opening_bucket = "compressed_under_20pct"
    elif opening_fraction <= 0.45:
        opening_bucket = "balanced_20_to_45pct"
    else:
        opening_bucket = "expanded_over_45pct"
    midpoint = (high + low) / 2.0
    consumed = abs(current - midpoint) / expected_move
    overshoot = max(current - high, low - current, 0.0) / expected_move
    return {
        "expected_move_telemetry_status": "observed_at_entry",
        "atm_iv_at_entry": round(atm_iv, 6),
        "expected_move_points": round(expected_move, 4),
        "opening_range_fraction": round(opening_fraction, 4),
        "opening_range_bucket": opening_bucket,
        "expected_move_consumed_fraction": round(consumed, 4),
        "breakout_overshoot_fraction": round(overshoot, 4),
    }


def _premium_level_entry_snapshot(
    symbol: str,
    spot: float,
    *,
    day: str | None = None,
    path: Path | None = None,
) -> dict:
    """Read contemporaneous premium-by-strike context without granting gate authority."""
    day = day or date.today().isoformat()
    path = path or OPTION_PREMIUM_LEVEL_REPORT_PATH
    unavailable = {"premium_level_telemetry_status": "unavailable"}
    if spot <= 0 or not path.exists():
        return unavailable
    try:
        report = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        return unavailable
    if str(report.get("date") or "")[:10] != day:
        return {"premium_level_telemetry_status": "stale"}
    symbol_row = (report.get("symbols") or {}).get(symbol.upper()) or {}
    if symbol_row.get("status") != "ok":
        return unavailable
    levels = symbol_row.get("levels") if isinstance(symbol_row.get("levels"), dict) else {}
    calls = [row for row in levels.get("CALL") or [] if isinstance(row, dict)]
    puts = [row for row in levels.get("PUT") or [] if isinstance(row, dict)]

    def _nearest(rows: list[dict]) -> dict | None:
        valid = [row for row in rows if float(row.get("underlying_level") or 0.0) > 0]
        return min(valid, key=lambda row: abs(float(row["underlying_level"]) - spot)) if valid else None

    nearest_call = _nearest(calls)
    nearest_put = _nearest(puts)
    top_call = calls[0] if calls else None
    top_put = puts[0] if puts else None
    call_premium = float(top_call.get("total_premium_dollars") or 0.0) if top_call else 0.0
    put_premium = float(top_put.get("total_premium_dollars") or 0.0) if top_put else 0.0
    qualified = bool(report.get("provenance_qualified"))
    return {
        "premium_level_telemetry_status": "observed_opra" if qualified else "observed_unqualified",
        "premium_level_feed_provenance": report.get("feed_provenance"),
        "premium_level_provenance_qualified": qualified,
        "premium_level_trade_history_complete": bool(symbol_row.get("trade_history_complete")),
        "premium_level_dominant_right": "CALL" if call_premium > put_premium else "PUT" if put_premium > call_premium else None,
        "premium_level_top_call": float(top_call["underlying_level"]) if top_call else None,
        "premium_level_top_put": float(top_put["underlying_level"]) if top_put else None,
        "premium_level_nearest_call": float(nearest_call["underlying_level"]) if nearest_call else None,
        "premium_level_nearest_put": float(nearest_put["underlying_level"]) if nearest_put else None,
        "premium_level_nearest_call_distance_pct": (
            round((float(nearest_call["underlying_level"]) - spot) / spot * 100, 4) if nearest_call else None
        ),
        "premium_level_nearest_put_distance_pct": (
            round((float(nearest_put["underlying_level"]) - spot) / spot * 100, 4) if nearest_put else None
        ),
    }


def _gex_wall_blocker(sym: str, spot: float) -> dict | None:
    """Block 0DTE entry when spot is pinned at a positive GEX wall.

    Positive net GEX = dealers long gamma = buy dips, sell rips = price pinned.
    Negative net GEX = dealers short gamma = amplify moves = favorable for directional.
    Only blocks when BOTH conditions true: net_gex > 0 AND spot within GEX_WALL_PROXIMITY_PCT.
    Missing GEX data → no block (fail open, not fail closed).
    """
    try:
        from scripts.market_conviction import _latest_gex
        gex = _latest_gex()
        scans = gex.get("scans") or []
        sym_gex = next((s for s in scans if s.get("symbol") == sym), {})
        if sym_gex.get("status") != "ok":
            return None
        net_gex = sym_gex.get("net_gex")
        if net_gex is None or float(net_gex) <= 0:
            return None  # negative GEX = move amplification = good for 0DTE directional
        wall = sym_gex.get("gex_wall") or {}
        wall_strike = wall.get("strike")
        if not wall_strike or spot <= 0:
            return None
        proximity_pct = abs(float(spot) - float(wall_strike)) / float(spot)
        if proximity_pct <= GEX_WALL_PROXIMITY_PCT:
            return {
                "reason": "gex_wall_pin",
                "net_gex": net_gex,
                "gex_wall_strike": wall_strike,
                "gex_wall_bias": wall.get("bias"),
                "spot": spot,
                "proximity_pct": round(proximity_pct * 100, 3),
                "threshold_pct": round(GEX_WALL_PROXIMITY_PCT * 100, 2),
                "interpretation": "positive_net_gex_spot_at_wall_range_bound_expected",
            }
    except Exception as exc:
        log.debug(f"GEX wall check [{sym}] skipped: {exc}")
    return None


def _find_0dte_for_symbol(
    account: float,
    sym: str,
    *,
    allow_calendar_catalyst: bool = False,
    require_orb_retest: bool = True,
) -> dict | None:
    today    = date.today()
    catalyst = next(((d, t, mode) for d, t, mode in CATALYST_DAYS if d == today), None) if allow_calendar_catalyst else None
    price    = _spot(sym)
    prev     = _prev_close(sym)
    day_type = _day_type_snapshot(sym)
    gap      = abs(price - prev) / prev if prev > 0 else 0.0
    up       = price > prev
    is_monday = today.weekday() == 0

    orb = _orb_breakout_retest_signal(sym) if not catalyst else None
    orb_break = orb is not None and orb["direction"] != "neutral"
    orb_retest_ready = bool(orb and orb.get("entry_ready"))
    use_orb = orb_break and (orb_retest_ready or not require_orb_retest)

    # Momentum continuation: retest invalidated (price ripped, never pulled back) but
    # breakout velocity confirms real move — enter 1 contract without waiting for retest.
    # Requires ATR ratio >= MOMENTUM_ORB_MIN_ATR_RATIO and directional CLV >= MOMENTUM_ORB_MIN_CLV.
    momentum_continuation = False
    if not use_orb and not catalyst and orb_break and not orb_retest_ready and orb is not None:
        if str(orb.get("retest_status") or "") == "retest_invalidated":
            _atr_ratio = float(orb.get("breakout_candle_atr_ratio") or 0.0)
            _clv = float(orb.get("orb_breakout_directional_close_location_value") or 0.0)
            if _atr_ratio >= MOMENTUM_ORB_MIN_ATR_RATIO and _clv >= MOMENTUM_ORB_MIN_CLV:
                momentum_continuation = True
                use_orb = True
                log.info(
                    f"0DTE [{sym}]: momentum continuation — retest_invalidated but "
                    f"ATR_ratio={_atr_ratio:.2f} CLV={_clv:.2f} → enter 1 contract"
                )

    if not catalyst and gap < GAP_THRESHOLD and not use_orb:
        reason = "orb_retest_not_confirmed" if orb_break and require_orb_retest else "no_catalyst_confirmation"
        _strategy_skip(
            sym,
            "0dte",
            reason,
            gap_pct=round(gap * 100, 3),
            orb_direction=orb.get("direction") if orb else None,
            orb_retest_status=orb.get("retest_status") if orb else None,
        )
        log.info(f"0DTE [{sym}]: no catalyst, no gap, no execution-ready ORB retest")
        return None

    # GEX wall pin — skip when positive net GEX traps price at dealer wall
    if not catalyst:
        _gex_block = _gex_wall_blocker(sym, price)
        if _gex_block:
            _strategy_skip(sym, "0dte", "gex_wall_pin", **_gex_block)
            log.info(
                f"0DTE [{sym}]: GEX wall pin — ${price:.2f} within "
                f"{_gex_block['proximity_pct']:.2f}% of ${_gex_block['gex_wall_strike']:.2f} wall, "
                f"net_gex={_gex_block['net_gex']:+.0f} (range-bound)"
            )
            return None

    if use_orb and not catalyst:
        right    = "PUT" if orb["direction"] == "bear" else "CALL"
        retest_text = " RETEST" if orb_retest_ready else ""
        _trigger = (f"ORB{retest_text} {'BEAR' if right == 'PUT' else 'BULL'}"
                    f"{' MONDAY' if is_monday else ''} range={orb['range_pct']:.1f}%")
    elif not catalyst:
        right    = "PUT" if not up else "CALL"
        _trigger = f"GAP {'UP' if up else 'DOWN'} {gap*100:.1f}%"
    else:
        right    = "CALL"
        _trigger = None

    if use_orb:
        confidence = 9.0 if orb_retest_ready else 7.5
        confidence_basis = "fresh_orb_breakout_retest" if orb_retest_ready else "raw_orb_shadow_only"
        directional_clv = float(orb.get("orb_breakout_directional_close_location_value") or 0.0)
        dislocation_z = float(orb.get("orb_dislocation_velocity_zscore") or 0.0)
        if orb_retest_ready and directional_clv >= 0.6:
            confidence += 0.25
        if orb_retest_ready and dislocation_z >= 1.5:
            confidence += 0.25
    elif gap >= GAP_THRESHOLD:
        # A gap identifies a catalyst day, not an executable direction. Keep
        # gap-only candidates below the live guard until price confirms via
        # the ORB breakout-and-retest path above.
        confidence = 7.5
        confidence_basis = "qualifying_gap_shadow_only"
    else:
        confidence = 8.5
        confidence_basis = "scheduled_catalyst"
    confidence = round(min(10.0, confidence), 2)

    occ, strike, px, exp = _atm_option(sym, right)
    if not occ or px <= 0:
        _strategy_skip(sym, "0dte", "atm_option_unavailable", right=right)
        return None

    max_risk  = account * MAX_RISK_PCT
    contracts = min(int(max_risk // (px * 100)), MAX_CONTRACTS)
    if momentum_continuation:
        contracts = min(contracts, 1)  # hard 1-contract cap — no retest = lower conviction
    if contracts < 1:
        _strategy_skip(sym, "0dte", "budget_insufficient", option_price=px, max_risk=max_risk)
        log.info(f"0DTE [{sym}]: can't afford 1 contract at ${px:.2f} (budget ${max_risk:.0f})")
        return None

    setup = {
        "strategy": "0dte", "symbol": sym, "right": right,
        "option_symbol": occ, "strike": strike, "expiry": exp,
        "contracts": contracts, "entry_price_est": px,
        "confidence": confidence,
        "confidence_basis": confidence_basis,
        "catalyst": catalyst[1] if catalyst else _trigger,
        "hard_close_date": str(today), "hard_close_time": "13:45",
        "spread_cents": _option_bid_ask_spread_cents(occ),
        "orb_direction": orb["direction"] if use_orb else None,
        "momentum_continuation": momentum_continuation,
        "execution_lane": "momentum_continuation" if momentum_continuation else None,
        "orb_entry_pattern": "momentum_continuation" if momentum_continuation else "breakout_retest" if use_orb and orb_retest_ready else "raw_breakout" if use_orb else None,
        "orb_breakout_at": orb.get("breakout_at") if use_orb else None,
        "orb_retest_at": orb.get("retest_at") if use_orb else None,
        "orb_retest_status": orb.get("retest_status") if use_orb else None,
        "orb_retest_age_bars": orb.get("retest_age_bars") if use_orb else None,
        "orb_retest_tolerance": orb.get("retest_tolerance") if use_orb else None,
        "retest_quality_score": orb.get("retest_quality_score") if use_orb else None,
        "retest_grade": orb.get("retest_grade") if use_orb else None,
        "pre_retest_extension_pct": orb.get("pre_retest_extension_pct") if use_orb else None,
        "minutes_since_breakout": orb.get("minutes_since_breakout") if use_orb else None,
        "retest_volume_ratio": orb.get("retest_volume_ratio") if use_orb else None,
        "retest_quality_details": orb.get("retest_quality_details") if use_orb else None,
        "retest_quality_authority": orb.get("retest_quality_authority") if use_orb else None,
        "orb_breakout_candle_atr_ratio": orb.get("breakout_candle_atr_ratio") if use_orb else None,
        "orb_dislocation_velocity_zscore": orb.get("orb_dislocation_velocity_zscore") if use_orb else None,
        "orb_breakout_close_location_value": orb.get("orb_breakout_close_location_value") if use_orb else None,
        "orb_breakout_directional_close_location_value": orb.get("orb_breakout_directional_close_location_value") if use_orb else None,
        "orb_dislocation_status": orb.get("orb_dislocation_status") if use_orb else None,
        "day_type_classification": day_type,
        "day_type": day_type.get("day_type"),
        "day_type_recommended_strategy": day_type.get("recommended_strategy"),
        "day_type_router_authority": day_type.get("authority"),
        "underlying_spot_at_selection": price,
        **_expected_move_entry_snapshot(sym, price, orb),
        **_premium_level_entry_snapshot(sym, price),
        **_selection_quote_fields(occ),
    }
    setup.update(_selected_contract_rank_snapshot(setup, price))
    return setup


def find_0dte(account: float) -> dict | None:
    return _find_0dte_for_symbol(account, "SPY", allow_calendar_catalyst=True)


def find_noise_area_0dte(account: float, *, now_et: datetime | None = None) -> dict | None:
    """Build a one-contract SPY setup for Alpaca paper execution only."""
    if not PAPER or not NOISE_AREA_PAPER_ENABLED:
        return None
    context = _noise_area_context("SPY", now_et=now_et)
    if not context.get("entry_ready"):
        _strategy_skip(
            "SPY",
            "noise_area_vwap",
            str(context.get("status") or "not_ready"),
            direction=context.get("direction"),
            upper_band=context.get("upper_band"),
            lower_band=context.get("lower_band"),
            vwap=context.get("vwap"),
        )
        return None

    direction = str(context.get("direction") or "neutral")
    right = "CALL" if direction == "bull" else "PUT" if direction == "bear" else ""
    if not right:
        return None
    occ, strike, option_mid, expiry = _atm_option("SPY", right)
    if not occ or option_mid <= 0:
        _strategy_skip("SPY", "noise_area_vwap", "atm_option_unavailable", right=right)
        return None
    max_risk = account * MAX_RISK_PCT
    if option_mid * 100 > max_risk:
        _strategy_skip(
            "SPY",
            "noise_area_vwap",
            "budget_insufficient",
            option_price=option_mid,
            max_risk=max_risk,
        )
        return None
    quote = _selection_quote_fields(occ)
    return {
        "strategy": "noise_area_vwap",
        "symbol": "SPY",
        "right": right,
        "option_symbol": occ,
        "strike": strike,
        "expiry": expiry,
        "contracts": NOISE_AREA_PAPER_CONTRACT_CAP,
        "entry_price_est": option_mid,
        "confidence": float(context.get("signal_score") or 9.0),
        "catalyst": (
            f"NOISE AREA {direction.upper()} close={float(context['close']):.2f} "
            f"band={float(context['upper_band'] if direction == 'bull' else context['lower_band']):.2f} "
            f"VWAP={float(context['vwap']):.2f}"
        ),
        "hard_close_date": str(date.today()),
        "hard_close_time": "13:45",
        "spread_cents": _option_bid_ask_spread_cents(occ),
        "paper_only": True,
        "paper_research_lane": "noise_area_vwap",
        "noise_area_status": context.get("status"),
        "noise_area_formula_version": context.get("formula_version"),
        "noise_area_direction": direction,
        "noise_area_upper_band": context.get("upper_band"),
        "noise_area_lower_band": context.get("lower_band"),
        "noise_area_vwap": context.get("vwap"),
        "noise_area_fraction": context.get("noise_fraction"),
        "noise_area_structural_stop": context.get("structural_stop"),
        "noise_area_lookback_sessions": context.get("lookback_sessions_observed"),
        "noise_area_current_bars": context.get("current_bars_observed"),
        "signal_snapshot": dict(context),
        **quote,
    }


def find_paper_challenger_0dte(account: float) -> list[dict]:
    """Scan promoted paper challengers through the same 0DTE setup builder.

    This is intentionally unavailable outside paper mode. Promotion here means
    the symbol may reach the existing risk/consensus gates with a one-contract
    cap; it does not bypass execution authorization or live readiness.
    """
    if not PAPER:
        return []
    symbols = [
        symbol
        for symbol in PAPER_CHALLENGER_SYMBOL_ORDER
        if symbol not in EXECUTION_SYMBOLS and symbol in SHADOW_LIQUIDITY_ALLOWLIST
    ]
    setups: list[dict] = []
    for symbol in symbols:
        setup = _find_0dte_for_symbol(account, symbol, allow_calendar_catalyst=False)
        if setup:
            setup["execution_lane"] = "paper_challenger"
            setup["promotion_source"] = "paper_challenger_0dte"
            setups.append(setup)
    return setups


def _read_shadow_candidate_rows(path: Path = SHADOW_CANDIDATE_LOG_PATH) -> list[dict]:
    if not path.exists():
        return []
    rows: list[dict] = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        try:
            row = json.loads(raw)
        except json.JSONDecodeError:
            continue
        if isinstance(row, dict):
            rows.append(row)
    return rows


def _resolve_shadow_candidate_symbols(
    report_path: Path = OPTIONS_LIQUIDITY_REPORT_PATH,
    *,
    today: date | None = None,
) -> list[str]:
    """Add recent, qualified option chains to shadow tracking only."""
    symbols = list(dict.fromkeys(["SPY", *SHADOW_CANDIDATES]))
    today = today or date.today()
    try:
        payload = json.loads(report_path.read_text(encoding="utf-8-sig"))
        report_day = date.fromisoformat(str(payload.get("date") or "")[:10])
    except (OSError, ValueError, json.JSONDecodeError):
        return symbols
    age_days = (today - report_day).days
    if age_days < 0 or age_days > 3:
        return symbols

    added = 0
    for raw_symbol in payload.get("qualified_symbols") or []:
        symbol = str(raw_symbol or "").upper()
        if symbol in symbols or symbol not in SHADOW_LIQUIDITY_ALLOWLIST:
            continue
        symbols.append(symbol)
        added += 1
        if added >= MAX_DYNAMIC_SHADOW_SYMBOLS:
            break
    return symbols


def _shadow_episode_bucket(now_et: datetime) -> str:
    minute = (now_et.minute // SHADOW_EPISODE_INTERVAL_MINUTES) * SHADOW_EPISODE_INTERVAL_MINUTES
    return f"{now_et.hour:02d}:{minute:02d}"


def _shadow_episode_id(day: str, setup: dict, bucket: str) -> str:
    return "|".join([
        day,
        str(setup.get("symbol") or ""),
        str(setup.get("right") or ""),
        str(setup.get("strategy") or "0dte"),
        str(setup.get("shadow_signal_id") or bucket),
    ])


def _build_shadow_challenger_setup(account: float, sym: str, signal: dict) -> dict | None:
    """Attach an executable option contract to a pure shadow signal."""
    if not signal.get("shadow_signal") or signal.get("live_execution_allowed") is not False:
        return None
    right = "CALL" if str(signal.get("shadow_direction")) == "call" else "PUT"
    occ, strike, px, exp = _atm_option(sym, right)
    if not occ or px <= 0:
        return None
    max_risk = account * MAX_RISK_PCT
    contracts = min(int(max_risk // (px * 100)), MAX_CONTRACTS)
    if contracts < 1:
        return None
    strategy = str(signal.get("strategy") or "shadow_challenger")
    trigger_at = signal.get("retest_at") or signal.get("confirmation_at") or signal.get("breakout_at")
    return {
        "strategy": strategy,
        "symbol": sym,
        "right": right,
        "option_symbol": occ,
        "strike": strike,
        "expiry": exp,
        "contracts": contracts,
        "entry_price_est": px,
        "catalyst": f"SHADOW {strategy} {right}",
        "hard_close_date": str(date.today()),
        "hard_close_time": "13:45",
        "spread_cents": _option_bid_ask_spread_cents(occ),
        "shadow_signal_id": f"{strategy}|{trigger_at or 'unknown'}|{right}",
        "shadow_setup_authority": "shadow_challenger_only",
        "shadow_setup_grade_context": signal.get("setup_grade_context"),
        "shadow_prior_day_aligned": signal.get("prior_day_aligned"),
        "shadow_prior_day_high": signal.get("prior_day_high"),
        "shadow_prior_day_low": signal.get("prior_day_low"),
        "shadow_opening_15m_high": signal.get("opening_15m_high"),
        "shadow_opening_15m_low": signal.get("opening_15m_low"),
        "shadow_breakout_at": signal.get("breakout_at"),
        "shadow_retest_at": signal.get("retest_at"),
        "retest_quality_score": signal.get("retest_quality_score"),
        "retest_grade": signal.get("retest_grade"),
        "pre_retest_extension_pct": signal.get("pre_retest_extension_pct"),
        "minutes_since_breakout": signal.get("minutes_since_breakout"),
        "retest_volume_ratio": signal.get("retest_volume_ratio"),
        "retest_quality_details": signal.get("retest_quality_details"),
        "retest_quality_authority": signal.get("retest_quality_authority"),
        "shadow_swept_level_name": signal.get("swept_level_name"),
        "shadow_swept_level": signal.get("swept_level"),
        "shadow_sweep_at": signal.get("sweep_at"),
        "shadow_confirmation_at": signal.get("confirmation_at"),
        "shadow_target_level_name": signal.get("target_level_name"),
        "shadow_orb_extension_fraction": signal.get("orb_extension_fraction"),
        "shadow_orb_extension_extreme": signal.get("orb_extension_extreme"),
        "shadow_reversal_confirmation": signal.get("reversal_confirmation"),
        "shadow_social_claim_status": signal.get("claim_status"),
        "shadow_underlying_counterfactual": signal.get("counterfactual"),
        "live_execution_allowed": False,
        "execution_enabled": False,
        "can_submit_orders": False,
        **_selection_quote_fields(occ),
    }


def _shadow_setup_challenger_candidates(account: float, sym: str) -> list[dict]:
    """Build independent research setups; never called by live entry selection."""
    raw = _intraday_bars(sym)
    if raw is None:
        return []
    bars = _completed_intraday_bars(raw)
    levels = _prior_reference_levels(sym)
    day_type = _day_type_snapshot(sym)
    signals = [
        evaluate_15m_orb_retest(
            bars,
            prior_day_high=levels.get("prior_day_high"),
            prior_day_low=levels.get("prior_day_low"),
        ),
        evaluate_level_sweep_reversal(
            bars,
            levels={
                "prior_day_high": levels.get("prior_day_high"),
                "prior_day_low": levels.get("prior_day_low"),
                "prior_week_high": levels.get("prior_week_high"),
                "prior_week_low": levels.get("prior_week_low"),
            },
        ),
        evaluate_orb_extension_reversal(bars),
    ]
    recommended = str(day_type.get("recommended_strategy") or "observe")
    if recommended == "orb_extension_reversal":
        signals.sort(key=lambda signal: 0 if signal.get("strategy") == "orb_extension_reversal" else 1)
    elif recommended == "orb_continuation":
        signals.sort(key=lambda signal: 0 if signal.get("strategy") == "orb_15m_retest" else 1)
    setups = []
    for signal in signals:
        setup = _build_shadow_challenger_setup(account, sym, signal)
        if setup:
            setup["shadow_reference_levels_status"] = levels.get("status")
            setup["day_type_classification"] = day_type
            setup["day_type"] = day_type.get("day_type")
            setup["day_type_recommended_strategy"] = recommended
            setup["day_type_route_match"] = (
                recommended == "orb_extension_reversal" and setup.get("strategy") == "orb_extension_reversal"
            ) or (
                recommended == "orb_continuation" and setup.get("strategy") == "orb_15m_retest"
            )
            setups.append(setup)
    return setups


def _market_force_shadow_snapshot(
    observed_at: datetime | None = None,
    path: Path | None = None,
) -> dict:
    """Capture point-in-time market force for shadow analysis only."""
    observed = observed_at or datetime.now(timezone.utc)
    if observed.tzinfo is None:
        observed = observed.replace(tzinfo=timezone.utc)
    source_path = path or MARKET_FORCE_REPORT_PATH
    base = {
        "market_force_classification": None,
        "market_force_timestamp": None,
        "market_force_age_seconds": None,
        "market_force_snapshot_status": "unavailable",
        "market_force_shadow_only": True,
    }
    try:
        payload = json.loads(source_path.read_text(encoding="utf-8-sig"))
        timestamp = str(payload.get("timestamp") or "")
        captured = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
        if captured.tzinfo is None:
            captured = captured.replace(tzinfo=timezone.utc)
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        return base

    age_seconds = (observed.astimezone(timezone.utc) - captured.astimezone(timezone.utc)).total_seconds()
    result = {
        **base,
        "market_force_classification": str(payload.get("classification") or "") or None,
        "market_force_timestamp": timestamp or None,
        "market_force_age_seconds": round(age_seconds, 1),
    }
    if payload.get("execution_enabled") is not False:
        result["market_force_snapshot_status"] = "authority_not_read_only"
    elif age_seconds < -60:
        result["market_force_snapshot_status"] = "future_timestamp"
    elif age_seconds > MARKET_FORCE_SHADOW_MAX_AGE_SECONDS:
        result["market_force_snapshot_status"] = "stale"
    else:
        result["market_force_snapshot_status"] = "current"
    return result


def _point_in_time_report(
    path: Path,
    observed_at: datetime,
    *,
    max_age_seconds: float = MARKET_CONTEXT_SHADOW_MAX_AGE_SECONDS,
) -> tuple[dict, str, float | None]:
    """Read a report only when its timestamp existed at the observation time."""
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
        timestamp = str(payload.get("generated_at") or payload.get("timestamp") or "")
        captured = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
        if captured.tzinfo is None:
            captured = captured.replace(tzinfo=timezone.utc)
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        return {}, "unavailable", None
    observed = observed_at if observed_at.tzinfo else observed_at.replace(tzinfo=timezone.utc)
    age_seconds = (observed.astimezone(timezone.utc) - captured.astimezone(timezone.utc)).total_seconds()
    if payload.get("execution_enabled") is not False:
        return {}, "authority_not_read_only", round(age_seconds, 1)
    if age_seconds < -60:
        return {}, "future_timestamp", round(age_seconds, 1)
    if age_seconds > max_age_seconds:
        return {}, "stale", round(age_seconds, 1)
    return payload, "current", round(age_seconds, 1)


def _market_context_shadow_snapshot(
    symbol: str,
    observed_at: datetime,
    *,
    report_dir: Path | None = None,
) -> dict:
    """Freeze candle, HTF, and catalyst context for later outcome attribution."""
    directory = report_dir or MARKET_CONTEXT_REPORT_DIR
    candle_report, candle_status, candle_age = _point_in_time_report(
        directory / "candlestick-context.json", observed_at
    )
    htf_report, htf_status, htf_age = _point_in_time_report(
        directory / "higher-timeframe-market-map.json", observed_at
    )
    catalyst_report, catalyst_status, catalyst_age = _point_in_time_report(
        directory / "market-catalyst-calendar.json", observed_at
    )

    def _symbol_item(report: dict) -> dict:
        return next(
            (
                row for row in report.get("items") or []
                if isinstance(row, dict) and str(row.get("symbol") or "").upper() == symbol.upper()
            ),
            {},
        )

    candle = _symbol_item(candle_report) if candle_status == "current" else {}
    htf = _symbol_item(htf_report) if htf_status == "current" else {}
    catalyst = catalyst_report.get("today") if catalyst_status == "current" else {}
    catalyst = catalyst if isinstance(catalyst, dict) else {}
    statuses = (candle_status, htf_status, catalyst_status)
    return {
        "market_context_snapshot_status": (
            "current" if all(status == "current" for status in statuses) else "incomplete"
        ),
        "candlestick_context_status": candle_status,
        "candlestick_context_age_seconds": candle_age,
        "candlestick_bias": candle.get("bias"),
        "candlestick_primary_signal": candle.get("primary_signal"),
        "candlestick_features": candle.get("features") or [],
        "candlestick_veto_reasons": candle.get("veto_reasons") or [],
        "candlestick_volume_expansion": candle.get("volume_expansion"),
        "htf_context_status": htf_status,
        "htf_context_age_seconds": htf_age,
        "htf_primary_bias": htf.get("primary_bias"),
        "htf_intraday_alignment": htf.get("intraday_alignment"),
        "htf_veto_reasons": htf.get("veto_reasons") or [],
        "catalyst_context_status": catalyst_status,
        "catalyst_context_age_seconds": catalyst_age,
        "catalyst_max_impact": catalyst.get("max_impact"),
        "catalyst_vetoes": catalyst.get("vetoes") or [],
        "catalyst_event_names": [
            str(event.get("name")) for event in catalyst.get("events") or []
            if isinstance(event, dict) and event.get("name")
        ],
    }


def _shadow_lifecycle_key(row: dict) -> tuple[str, ...]:
    lifecycle_id = str(row.get("lifecycle_id") or "")
    if lifecycle_id:
        return ("episode", lifecycle_id)
    return (
        "legacy",
        str(row.get("date") or "")[:10],
        str(row.get("symbol") or ""),
        str(row.get("right") or ""),
        str(row.get("strategy") or "0dte"),
    )


def _parse_shadow_time(value: object) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def _shadow_exit_reason(rows: list[dict], mark_price: float, now_et: datetime) -> tuple[str, float, float]:
    first = rows[0]
    entry = float(first.get("entry_price_est") or 0.0)
    prices = [float(row.get("entry_price_est") or 0.0) for row in rows if float(row.get("entry_price_est") or 0.0) > 0]
    if entry <= 0:
        return "", 0.0, 0.0
    current_return = (mark_price - entry) / entry * 100
    prior_returns = [(price - entry) / entry * 100 for price in prices]
    best_return = max([current_return, *prior_returns])
    if current_return <= -30.0:
        return "stop_30_hit", current_return, best_return
    if current_return >= 75.0 and not SHADOW_CONTINUE_AFTER_TARGET:
        return "target_75_hit", current_return, best_return
    ratchet_floor = max(25.0, best_return - 15.0)
    if best_return >= 40.0 and 0 < current_return <= ratchet_floor:
        return f"ratchet_lock_{ratchet_floor:.1f}", current_return, best_return
    expires_at = _parse_shadow_time(first.get("episode_expires_at"))
    now_utc = now_et.astimezone(timezone.utc) if now_et.tzinfo else now_et.replace(tzinfo=timezone.utc)
    if expires_at and now_utc >= expires_at:
        return "episode_horizon", current_return, best_return
    try:
        hard_close = datetime.strptime(str(first.get("hard_close_time") or "13:45"), "%H:%M").time()
    except ValueError:
        hard_close = dtime(13, 45)
    if now_et.time() >= hard_close:
        return "hard_close", current_return, best_return
    return "", current_return, best_return


def _log_shadow_0dte_candidates_unlocked(account: float, symbols: list[str] | None = None) -> list[dict]:
    """Track time-bucketed, shadow-only option episodes with full outcomes."""
    if symbols is None:
        symbols = _resolve_shadow_candidate_symbols()
    now_et = _now_et()
    today_s = str(now_et.date())
    scanned_dt = datetime.now(timezone.utc)
    scanned_at = scanned_dt.isoformat(timespec="seconds").replace("+00:00", "Z")
    market_force_snapshot = _market_force_shadow_snapshot(scanned_dt)
    bucket = _shadow_episode_bucket(now_et)
    prior_rows = [
        row for row in _read_shadow_candidate_rows(SHADOW_CANDIDATE_LOG_PATH)
        if str(row.get("date") or "")[:10] == today_s
        and int(row.get("schema_version") or 0) == SHADOW_CANDIDATE_SCHEMA_VERSION
    ]
    first_by_key: dict[tuple[str, ...], dict] = {}
    latest_by_key: dict[tuple[str, ...], dict] = {}
    rows_by_key: dict[tuple[str, ...], list[dict]] = {}
    for row in prior_rows:
        key = _shadow_lifecycle_key(row)
        first_by_key.setdefault(key, row)
        latest_by_key[key] = row
        rows_by_key.setdefault(key, []).append(row)

    observations: list[dict] = []
    underlying_marks: dict[str, dict] = {}

    def _underlying_for(symbol: str) -> dict:
        if symbol not in underlying_marks:
            underlying_marks[symbol] = _underlying_mark_snapshot(symbol, now_et=now_et)
        return underlying_marks[symbol]

    for key, latest in latest_by_key.items():
        if latest.get("event_type") == "shadow_exit":
            continue
        first = first_by_key[key]
        underlying_symbol = str(first.get("symbol") or "")
        option_symbol = str(first.get("option_symbol") or "")
        mark_price = _option_mid(option_symbol)
        if mark_price <= 0:
            continue
        exit_reason, return_pct, best_return_pct = _shadow_exit_reason(
            rows_by_key.get(key, [first]), mark_price, now_et
        )
        prior_target_hit = any(
            float(row.get("return_pct_at_mark") or 0.0) >= 75.0
            for row in rows_by_key.get(key, [first])
        )
        target_hit = prior_target_hit or return_pct >= 75.0
        quote_fields = _selection_quote_fields(option_symbol)
        spread_cents = _option_bid_ask_spread_cents(option_symbol)
        observations.append({
            **first,
            **market_force_snapshot,
            "scanned_at": scanned_at,
            "entry_price_est": mark_price,
            "mark_price": mark_price,
            "spread_cents": spread_cents,
            **quote_fields,
            "event_type": "shadow_exit" if exit_reason else "shadow_mark",
            "action": "exit_shadow" if exit_reason else "hold_shadow",
            "mark_reason": exit_reason or "lifecycle_mark",
            "return_pct_at_mark": round(return_pct, 2),
            "best_return_pct_at_mark": round(best_return_pct, 2),
            "target_75_hit_at_or_before_mark": target_hit,
            "post_target_observation": prior_target_hit,
            "contract_selection_challengers": _mark_shadow_contract_challengers(first),
            **_underlying_for(underlying_symbol),
        })

    active_by_symbol: dict[str, int] = {}
    active_by_symbol_strategy: dict[tuple[str, str], int] = {}
    for key, latest in latest_by_key.items():
        if latest.get("event_type") != "shadow_exit":
            first = first_by_key[key]
            symbol = str(first.get("symbol") or "")
            strategy = str(first.get("strategy") or "unknown")
            active_by_symbol[symbol] = active_by_symbol.get(symbol, 0) + 1
            strategy_key = (symbol, strategy)
            active_by_symbol_strategy[strategy_key] = active_by_symbol_strategy.get(strategy_key, 0) + 1
    seen_ids = {str(row.get("lifecycle_id") or "") for row in prior_rows}
    for sym in symbols:
        if now_et.time() >= dtime(13, 45):
            break
        if active_by_symbol.get(sym, 0) >= SHADOW_MAX_ACTIVE_PER_SYMBOL:
            continue
        setup = _find_0dte_for_symbol(
            account,
            sym,
            allow_calendar_catalyst=False,
            require_orb_retest=False,
        )
        # Give independent challenger strategies first access to research
        # capacity. Generic 0DTE episodes must not starve a reversal signal.
        candidate_setups = _shadow_setup_challenger_candidates(account, sym) + ([setup] if setup else [])
        for candidate_setup in candidate_setups:
            if active_by_symbol.get(sym, 0) >= SHADOW_MAX_ACTIVE_PER_SYMBOL:
                break
            strategy = str(candidate_setup.get("strategy") or "unknown")
            strategy_key = (sym, strategy)
            if active_by_symbol_strategy.get(strategy_key, 0) >= SHADOW_MAX_ACTIVE_PER_SYMBOL_STRATEGY:
                continue
            lifecycle_id = _shadow_episode_id(today_s, candidate_setup, bucket)
            if lifecycle_id in seen_ids:
                continue
            expires_et = now_et + timedelta(minutes=SHADOW_EPISODE_HORIZON_MINUTES)
            expires_at = expires_et.astimezone(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
            candidate_setup.update(market_force_snapshot)
            candidate_setup.update(_market_context_shadow_snapshot(sym, scanned_dt))
            feature_snapshot = _entry_feature_snapshot(candidate_setup)
            contract_selection_challengers = _shadow_contract_challengers(candidate_setup)
            entry = {
                "scanned_at": scanned_at,
                "date": today_s,
                "provider": "flip_shadow_candidates",
                "execution_mode": "shadow_only",
                "live_execution_allowed": False,
                "schema_version": SHADOW_CANDIDATE_SCHEMA_VERSION,
                "data_quality": "current_session_lifecycle",
                "learning_mode": "accelerated_time_bucketed_shadow",
                "lifecycle_id": lifecycle_id,
                "episode_bucket_et": bucket,
                "episode_horizon_minutes": SHADOW_EPISODE_HORIZON_MINUTES,
                "episode_expires_at": expires_at,
                "event_type": "shadow_entry",
                "action": "enter_shadow",
                "learner_tracks": ["flip_entry_exit", "options_directional_contract_selection"],
                "contract_selection_challengers": contract_selection_challengers,
                "contract_challenger_evidence_use": "research_only_excluded_from_promotion_counts",
                "options_playbook": "directional_long_call" if candidate_setup.get("right") == "CALL" else "directional_long_put",
                "entry_reasoning": {
                    "catalyst": candidate_setup.get("catalyst"),
                    "signal_snapshot": candidate_setup.get("signal_snapshot"),
                    "feature_snapshot": feature_snapshot,
                    "spread_cents": candidate_setup.get("spread_cents"),
                    "quote_age_seconds": candidate_setup.get("quote_age_seconds"),
                },
                "feature_snapshot": feature_snapshot,
                **market_force_snapshot,
                "promotion_required": "accelerated gate: 100 completed episodes, 10 trading days, 30 chronological holdout episodes, human approval",
                **candidate_setup,
                **_underlying_for(sym),
            }
            observations.append(entry)
            seen_ids.add(lifecycle_id)
            active_by_symbol[sym] = active_by_symbol.get(sym, 0) + 1
            active_by_symbol_strategy[strategy_key] = active_by_symbol_strategy.get(strategy_key, 0) + 1

    if observations:
        SHADOW_CANDIDATE_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        with SHADOW_CANDIDATE_LOG_PATH.open("a", encoding="utf-8") as f:
            for observation in observations:
                f.write(json.dumps(observation, sort_keys=True) + "\n")
        entry_count = sum(1 for row in observations if row.get("event_type") == "shadow_entry")
        mark_count = len(observations) - entry_count
        log.info(
            f"Logged shadow lifecycles: entries={entry_count} marks={mark_count} "
            f"to {SHADOW_CANDIDATE_LOG_PATH}"
        )
    return observations


def log_shadow_0dte_candidates(account: float, symbols: list[str] | None = None) -> list[dict]:
    """Serialize the accelerated shadow writer across overlapping scheduled runs."""
    lock_path = SHADOW_CANDIDATE_LOG_PATH.with_suffix(SHADOW_CANDIDATE_LOG_PATH.suffix + ".lock")
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        if lock_path.exists() and time.time() - lock_path.stat().st_mtime > 600:
            lock_path.unlink(missing_ok=True)
        fd = os.open(str(lock_path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        log.info("Shadow lifecycle logger already running; skipping overlapping invocation")
        return []
    except OSError as exc:
        log.warning("Shadow lifecycle lock unavailable; telemetry skipped: %s", exc)
        return []
    try:
        os.write(fd, str(os.getpid()).encode("ascii", "ignore"))
        return _log_shadow_0dte_candidates_unlocked(account, symbols=symbols)
    finally:
        os.close(fd)
        lock_path.unlink(missing_ok=True)


BEAR_TREND_ENTRY_CUTOFF_ET = dtime(14, 0)  # no new entries after 2:00pm ET (1:00pm CT)


def _bear_put_spread(sym: str, exp: str, atm_strike: float, max_risk: float) -> tuple[float, float, float] | None:
    """Find narrowest bear put spread (buy ATM, sell OTM) whose net debit fits max_risk per contract.
    Returns (net_debit, long_strike, short_strike) or None."""
    try:
        t = yf.Ticker(sym)
        chain = t.option_chain(exp)
        puts = chain.puts
        if puts.empty:
            return None
        for width in [2, 3, 5, 7, 10]:
            short_target = atm_strike - width
            long_rows  = puts[abs(puts["strike"] - atm_strike)   < 0.6]
            short_rows = puts[abs(puts["strike"] - short_target) < 0.6]
            if long_rows.empty or short_rows.empty:
                continue
            long_ask  = float(long_rows["ask"].iloc[0])
            short_bid = float(short_rows["bid"].iloc[0])
            if long_ask <= 0 or short_bid < 0:
                continue
            net_debit = round(long_ask - short_bid, 3)
            if net_debit <= 0:
                continue
            if net_debit * 100 <= max_risk:
                return (net_debit, float(long_rows["strike"].iloc[0]), float(short_rows["strike"].iloc[0]))
        return None
    except Exception as exc:
        log.warning(f"Bear put spread lookup failed: {exc}")
        return None


def _now_et():
    from zoneinfo import ZoneInfo
    return datetime.now(ZoneInfo("America/New_York"))


def _same_day_reentry_blocker(setup: dict, trades: list[dict]) -> str | None:
    """Avoid chasing the same 0DTE direction after a same-day SPY exit.

    A second same-symbol/same-direction entry is only allowed when the new setup
    is clearly stronger than the first entry. This protects against the pattern
    where a first trend trade works, exits, then the bot re-enters after the move
    has already matured.
    """
    symbol = setup.get("symbol")
    right = setup.get("right")
    if not symbol or not right:
        return None

    today_s = str(date.today())
    prior = [
        trade for trade in trades
        if trade.get("status") == "closed"
        and str(trade.get("entry_date") or "")[:10] == today_s
        and trade.get("symbol") == symbol
        and trade.get("right") == right
    ]
    if not prior:
        return None

    confidence = float(setup.get("confidence") or setup.get("score") or 0.0)
    catalyst = str(setup.get("catalyst") or "")
    ttm = setup.get("ttm_squeeze") if isinstance(setup.get("ttm_squeeze"), dict) else {}
    stronger_bull = (
        right == "CALL"
        and confidence >= SAME_DAY_REENTRY_MIN_CONFIDENCE
        and bool(ttm.get("first_release"))
        and bool(ttm.get("momentum_rising"))
    )
    stronger_bear = (
        right == "PUT"
        and confidence >= SAME_DAY_REENTRY_MIN_CONFIDENCE
        and "ORB=bear" in catalyst
    )
    if stronger_bull or stronger_bear:
        log.info(
            f"Same-day re-entry allowed for {symbol} {right}: "
            f"confidence={confidence} catalyst={catalyst}"
        )
        return None

    last = prior[-1]
    return (
        f"same_day_reentry_blocked after {last.get('exit_reason', 'prior exit')} "
        f"on {symbol} {right}; need confidence>={SAME_DAY_REENTRY_MIN_CONFIDENCE:g} "
        "plus fresh release/ORB confirmation"
    )


def find_bear_trend_day(account: float) -> dict | None:
    now_et = _now_et()
    if now_et.time() >= BEAR_TREND_ENTRY_CUTOFF_ET:
        _strategy_skip("SPY", "bear_trend", "entry_cutoff", cutoff_et=BEAR_TREND_ENTRY_CUTOFF_ET.isoformat())
        log.info("Bear trend: past 2pm ET entry cutoff â€” skip")
        return None

    if not _vix_term_structure_direction_ok("bear", _fetch_vix_term_structure()):
        _strategy_skip("SPY", "bear_trend", "vix_term_structure_direction_block")
        log.info("Bear trend: VIX term structure filter blocked entry")
        return None

    leaders = ["SPY", "QQQ", "IWM"]
    bars = {sym: _intraday_bars(sym) for sym in leaders}
    signals = {sym: _vwap_50ema_signal(bars.get(sym), sym) for sym in leaders}
    valid = {sym: sig for sym, sig in signals.items() if sig and sig["score"] >= BEAR_TREND_MIN_CONFIDENCE}

    scores_str = " | ".join(
        f"{sym}={sig['score']}/10" if sig else f"{sym}=no_data"
        for sym, sig in signals.items()
    )
    log.info(f"Bear trend breadth: {scores_str} | confirmed={list(valid.keys())} needâ‰¥2")

    if len(valid) < 2 or "SPY" not in valid:
        spy_signal = signals.get("SPY")
        primary_reason = (
            _INTRADAY_DATA_ISSUES.get("SPY")
            or ("insufficient_bars" if bars.get("SPY") is None or len(bars["SPY"]) < BEAR_TREND_MIN_BARS else "insufficient_intraday_data")
        ) if spy_signal is None else (
            "score_below_minimum" if float(spy_signal.get("score", 0)) < BEAR_TREND_MIN_CONFIDENCE
            else "breadth_not_confirmed"
        )
        _strategy_skip(
            "SPY", "bear_trend", primary_reason,
            required_breadth=2, confirmed=sorted(valid),
            scores={symbol: sig.get("score") if sig else None for symbol, sig in signals.items()},
        )
        failing = {sym: sig for sym, sig in signals.items() if sig and sig["score"] < BEAR_TREND_MIN_CONFIDENCE}
        for sym, sig in failing.items():
            gap = BEAR_TREND_MIN_CONFIDENCE - sig["score"]
            log.info(
                f"Bear trend [{sym}]: score {sig['score']}/10 â€” needs {gap} more pts "
                f"(vwap_dist={sig['vwap_distance']*100:.2f}% reasons={sig['reasons']})"
            )
        log.info(f"Bear trend: only {len(valid)}/3 symbols confirm â€” need 2 â€” skip")
        return None

    signal = valid["SPY"]
    if signal["score"] < BEAR_TREND_MIN_CONFIDENCE:
        _strategy_skip("SPY", "bear_trend", "score_below_minimum", score=signal["score"], minimum=BEAR_TREND_MIN_CONFIDENCE)
        log.info(f"Bear trend: SPY score {signal['score']}/10 < min {BEAR_TREND_MIN_CONFIDENCE} â€” skip")
        return None

    orb = _orb_breakout_retest_signal("SPY")
    orb_dir = orb["direction"] if orb else "unavail"
    orb_retest_status = orb.get("retest_status") if orb else None
    log.info(
        f"Bear trend ORB [{orb_dir}]: status={orb_retest_status or 'unavailable'} "
        f"fresh_pullback={signal.get('fresh_pullback_confirmed')}"
    )
    orb_block = _trend_orb_context_blocker("bear", signal, orb)
    if orb_block:
        _strategy_skip(
            "SPY", "bear_trend", orb_block["reason"],
            **{key: value for key, value in orb_block.items() if key != "reason"},
        )
        log.info(f"Bear trend: ORB context blocked entry: {orb_block}")
        return None

    occ, strike, px, exp = _atm_option("SPY", "PUT")
    if not occ or px <= 0:
        _strategy_skip("SPY", "bear_trend", "atm_option_unavailable", right="PUT")
        log.info("Bear trend: could not find SPY ATM put â€” skip")
        return None

    max_risk = account * MAX_RISK_PCT
    contracts = min(int(max_risk // (px * 100)), MAX_CONTRACTS)
    reason_text = ", ".join(signal["reasons"])

    if contracts >= 1:
        return {
            "strategy": "bear_trend",
            "symbol": "SPY",
            "right": "PUT",
            "option_symbol": occ,
            "strike": strike,
            "expiry": exp,
            "contracts": contracts,
            "entry_price_est": px,
            "confidence": signal["score"],
            "hard_close_date": str(date.today()),
            "hard_close_time": "13:45",
            "catalyst": f"VWAP/50EMA bear trend {signal['score']}/10: {reason_text} | ORB={orb_dir}",
            "spread_cents": _option_bid_ask_spread_cents(occ),
            **_selection_quote_fields(occ),
            "orb_direction": orb_dir,
            "orb_entry_pattern": "fresh_vwap_ema_pullback",
            "orb_retest_status": orb_retest_status,
            "orb_retest_age_bars": orb.get("retest_age_bars") if orb else None,
            "signal_snapshot": {
                "score": signal["score"],
                "close": signal["close"],
                "vwap": signal["vwap"],
                "ema50": signal["ema50"],
                "vwap_distance_pct": round(signal["vwap_distance"] * 100, 3),
                "reasons": signal["reasons"],
            },
        }

    # ATM put too expensive for budget â€” try bear put debit spread
    log.info(f"Bear trend: SPY put ${px:.2f} exceeds budget ${max_risk:.0f} â€” trying bear put spread")
    spread = _bear_put_spread("SPY", exp, strike, max_risk)
    if spread:
        net_debit, long_strike, short_strike = spread
        spread_contracts = min(int(max_risk // (net_debit * 100)), MAX_CONTRACTS)
        if spread_contracts >= 1:
            long_occ  = _occ("SPY", exp, "PUT", long_strike)
            short_occ = _occ("SPY", exp, "PUT", short_strike)
            log.info(
                f"Bear trend: spread {long_strike:.0f}/{short_strike:.0f}P "
                f"net_debit=${net_debit:.2f} x{spread_contracts}"
            )
            return {
                "strategy": "bear_trend_spread",
                "symbol": "SPY",
                "right": "PUT",
                "option_symbol": long_occ,
                "short_option_symbol": short_occ,
                "strike": long_strike,
                "short_strike": short_strike,
                "expiry": exp,
                "contracts": spread_contracts,
                "entry_price_est": net_debit,
                "max_loss": round(net_debit * spread_contracts * 100, 2),
                "max_gain": round((long_strike - short_strike - net_debit) * spread_contracts * 100, 2),
                "confidence": signal["score"],
                "hard_close_date": str(date.today()),
                "hard_close_time": "13:45",
                "catalyst": f"VWAP/50EMA bear spread {signal['score']}/10: {reason_text} | ORB={orb_dir}",
                "orb_direction": orb_dir,
                "orb_entry_pattern": "fresh_vwap_ema_pullback",
                "orb_retest_status": orb_retest_status,
                "orb_retest_age_bars": orb.get("retest_age_bars") if orb else None,
                "signal_snapshot": {
                    "score": signal["score"],
                    "close": signal["close"],
                    "vwap": signal["vwap"],
                    "ema50": signal["ema50"],
                    "vwap_distance_pct": round(signal["vwap_distance"] * 100, 3),
                    "reasons": signal["reasons"],
                },
            }

    log.info(f"Bear trend: no spread fits budget ${max_risk:.0f} â€” skip")
    _strategy_skip("SPY", "bear_trend", "budget_or_spread_unavailable", option_price=px, max_risk=max_risk)
    return None


def _bull_call_spread(sym: str, exp: str, atm_strike: float, max_risk: float) -> tuple[float, float, float] | None:
    """Find narrowest bull call spread (buy ATM, sell OTM) whose net debit fits max_risk per contract.
    Returns (net_debit, long_strike, short_strike) or None."""
    try:
        t = yf.Ticker(sym)
        chain = t.option_chain(exp)
        calls = chain.calls
        if calls.empty:
            return None
        for width in [2, 3, 5, 7, 10]:
            short_target = atm_strike + width
            long_rows  = calls[abs(calls["strike"] - atm_strike)   < 0.6]
            short_rows = calls[abs(calls["strike"] - short_target) < 0.6]
            if long_rows.empty or short_rows.empty:
                continue
            long_ask  = float(long_rows["ask"].iloc[0])
            short_bid = float(short_rows["bid"].iloc[0])
            if long_ask <= 0 or short_bid < 0:
                continue
            net_debit = round(long_ask - short_bid, 3)
            if net_debit <= 0:
                continue
            if net_debit * 100 <= max_risk:
                return (net_debit, float(long_rows["strike"].iloc[0]), float(short_rows["strike"].iloc[0]))
        return None
    except Exception as exc:
        log.warning(f"Bull call spread lookup failed: {exc}")
        return None


def _ttm_squeeze_context(hist) -> dict:
    """Compute TTM Squeeze context for logging only. It never gates entries."""
    if hist is None or len(hist) < 25:
        return {"available": False, "reason": "insufficient_bars"}
    try:
        from scripts.ttm_squeeze_shadow_logger import compute_squeeze

        df = hist.rename(columns={c: str(c).lower() for c in hist.columns}).copy()
        required = {"high", "low", "close"}
        if not required.issubset(set(df.columns)):
            return {"available": False, "reason": "missing_ohlc"}
        sqz = compute_squeeze(df)
        row = sqz.iloc[-1]
        prev = sqz.iloc[-2]
        if bool(row.get("sqz_on")):
            state = "on"
        elif bool(row.get("sqz_off")):
            state = "off"
        else:
            state = "none"
        momentum = row.get("momentum")
        prev_momentum = prev.get("momentum")
        first_release = bool(prev.get("sqz_on")) and bool(row.get("sqz_off"))
        return {
            "available": True,
            "state": state,
            "first_release": first_release,
            "momentum": round(float(momentum), 4) if not pd.isna(momentum) else None,
            "momentum_rising": (
                not pd.isna(momentum)
                and not pd.isna(prev_momentum)
                and float(momentum) > float(prev_momentum)
            ),
        }
    except Exception as exc:
        return {"available": False, "reason": str(exc)[:120]}


def find_bull_trend_day(account: float) -> dict | None:
    now_et = _now_et()
    if now_et.time() >= BEAR_TREND_ENTRY_CUTOFF_ET:
        _strategy_skip("SPY", "bull_trend", "entry_cutoff", cutoff_et=BEAR_TREND_ENTRY_CUTOFF_ET.isoformat())
        log.info("Bull trend: past 2pm ET entry cutoff - skip")
        return None

    if not _vix_term_structure_direction_ok("bull", _fetch_vix_term_structure()):
        _strategy_skip("SPY", "bull_trend", "vix_term_structure_direction_block")
        log.info("Bull trend: VIX term structure filter blocked entry")
        return None

    leaders = ["SPY", "QQQ", "IWM"]
    bars = {sym: _intraday_bars(sym) for sym in leaders}
    signals = {sym: _vwap_50ema_bull_signal(bars.get(sym), sym) for sym in leaders}
    valid = {sym: sig for sym, sig in signals.items() if sig and sig["score"] >= BULL_TREND_MIN_CONFIDENCE}
    scores_str = " | ".join(
        f"{sym}={sig['score']}/10" if sig else f"{sym}=no_data"
        for sym, sig in signals.items()
    )
    log.info(
        f"Bull trend breadth: {scores_str} | confirmed={list(valid.keys())} "
        f"need>=3 at {BULL_TREND_MIN_CONFIDENCE:g}+"
    )
    if len(valid) < 3 or "SPY" not in valid:
        spy_signal = signals.get("SPY")
        primary_reason = (
            _INTRADAY_DATA_ISSUES.get("SPY")
            or ("insufficient_bars" if bars.get("SPY") is None or len(bars["SPY"]) < BEAR_TREND_MIN_BARS else "insufficient_intraday_data")
        ) if spy_signal is None else (
            "score_below_minimum" if float(spy_signal.get("score", 0)) < BULL_TREND_MIN_CONFIDENCE
            else "breadth_not_confirmed"
        )
        _strategy_skip(
            "SPY", "bull_trend", primary_reason,
            required_breadth=3, confirmed=sorted(valid),
            scores={symbol: sig.get("score") if sig else None for symbol, sig in signals.items()},
        )
        return None

    signal = valid["SPY"]
    execution_confidence = float(signal["score"])
    reason_text = ", ".join(signal["reasons"])
    squeeze = _ttm_squeeze_context(bars.get("SPY"))
    log.info(
        "Bull trend TTM context: "
        f"state={squeeze.get('state', 'unavailable')} "
        f"release={squeeze.get('first_release')} "
        f"momentum={squeeze.get('momentum')}"
    )

    orb = _orb_breakout_retest_signal("SPY")
    orb_dir = orb.get("direction") if orb else "unavail"
    orb_retest_status = orb.get("retest_status") if orb else None
    log.info(
        f"Bull trend ORB [{orb_dir}]: status={orb_retest_status or 'unavailable'} "
        f"fresh_pullback={signal.get('fresh_pullback_confirmed')}"
    )
    orb_block = _trend_orb_context_blocker("bull", signal, orb)
    if orb_block:
        _strategy_skip(
            "SPY", "bull_trend", orb_block["reason"],
            **{key: value for key, value in orb_block.items() if key != "reason"},
        )
        log.info(f"Bull trend: ORB context blocked entry: {orb_block}")
        return None

    occ, strike, px, exp = _atm_option("SPY", "CALL")
    if not occ or px <= 0:
        _strategy_skip("SPY", "bull_trend", "atm_option_unavailable", right="CALL")
        log.info("Bull trend: could not find SPY ATM call - skip")
        return None

    max_risk = account * MAX_RISK_PCT
    contracts = min(int(max_risk // (px * 100)), MAX_CONTRACTS)

    if contracts >= 1:
        return {
            "strategy": "bull_trend",
            "symbol": "SPY",
            "right": "CALL",
            "option_symbol": occ,
            "strike": strike,
            "expiry": exp,
            "contracts": contracts,
            "entry_price_est": px,
            "confidence": execution_confidence,
            "raw_signal_score": signal["score"],
            "breadth_confirmed": sorted(valid.keys()),
            "hard_close_date": str(date.today()),
            "hard_close_time": "13:45",
            "catalyst": (
                f"VWAP/50EMA bull trend {signal['score']}/10, breadth {len(valid)}/3: {reason_text} | "
                f"TTM={squeeze.get('state', 'unavailable')}"
            ),
            "spread_cents": _option_bid_ask_spread_cents(occ),
            **_selection_quote_fields(occ),
            "ttm_squeeze": squeeze,
            "orb_direction": orb_dir,
            "orb_entry_pattern": "fresh_vwap_ema_pullback",
            "orb_retest_status": orb_retest_status,
            "orb_retest_age_bars": orb.get("retest_age_bars") if orb else None,
            "signal_snapshot": {
                "score": signal["score"],
                "close": signal["close"],
                "vwap": signal["vwap"],
                "ema50": signal["ema50"],
                "vwap_distance_pct": round(signal["vwap_distance"] * 100, 3),
                "reasons": signal["reasons"],
            },
        }

    # ATM call too expensive for budget â€” try bull call debit spread
    log.info(f"Bull trend: SPY call ${px:.2f} exceeds budget ${max_risk:.0f} â€” trying bull call spread")
    spread = _bull_call_spread("SPY", exp, strike, max_risk)
    if spread:
        net_debit, long_strike, short_strike = spread
        spread_contracts = min(int(max_risk // (net_debit * 100)), MAX_CONTRACTS)
        if spread_contracts >= 1:
            long_occ  = _occ("SPY", exp, "CALL", long_strike)
            short_occ = _occ("SPY", exp, "CALL", short_strike)
            log.info(
                f"Bull trend: spread {long_strike:.0f}/{short_strike:.0f}C "
                f"net_debit=${net_debit:.2f} x{spread_contracts}"
            )
            return {
                "strategy": "bull_trend_spread",
                "symbol": "SPY",
                "right": "CALL",
                "option_symbol": long_occ,
                "short_option_symbol": short_occ,
                "strike": long_strike,
                "short_strike": short_strike,
                "expiry": exp,
                "contracts": spread_contracts,
                "entry_price_est": net_debit,
                "max_loss": round(net_debit * spread_contracts * 100, 2),
                "max_gain": round((short_strike - long_strike - net_debit) * spread_contracts * 100, 2),
                "confidence": execution_confidence,
                "raw_signal_score": signal["score"],
                "breadth_confirmed": sorted(valid.keys()),
                "hard_close_date": str(date.today()),
                "hard_close_time": "13:45",
                "catalyst": (
                    f"VWAP/50EMA bull spread {signal['score']}/10, breadth {len(valid)}/3: {reason_text} | "
                    f"TTM={squeeze.get('state', 'unavailable')}"
                ),
                "ttm_squeeze": squeeze,
                "orb_direction": orb_dir,
                "orb_entry_pattern": "fresh_vwap_ema_pullback",
                "orb_retest_status": orb_retest_status,
                "orb_retest_age_bars": orb.get("retest_age_bars") if orb else None,
                "signal_snapshot": {
                    "score": signal["score"],
                    "close": signal["close"],
                    "vwap": signal["vwap"],
                    "ema50": signal["ema50"],
                    "vwap_distance_pct": round(signal["vwap_distance"] * 100, 3),
                    "reasons": signal["reasons"],
                },
            }

    log.info(f"Bull trend: no spread fits budget ${max_risk:.0f} â€” skip")
    _strategy_skip("SPY", "bull_trend", "budget_or_spread_unavailable", option_price=px, max_risk=max_risk)
    return None


def find_earnings(account: float) -> list[dict]:
    today, cutoff = date.today(), date.today() + timedelta(days=5)
    max_risk = account * MAX_RISK_PCT
    results  = []

    for sym in DEFAULT_SYMBOLS:
        try:
            cal = yf.Ticker(sym).calendar
            if not cal:
                continue
            ed = None
            if isinstance(cal, dict):
                raw = cal.get("Earnings Date")
                if raw:
                    if hasattr(raw, '__iter__') and not isinstance(raw, str):
                        raw = list(raw)[0]
                    ed = raw.date() if hasattr(raw, 'date') else raw
            if not ed or not (today < ed <= cutoff):
                continue

            t        = yf.Ticker(sym)
            price    = _spot(sym)
            if price <= 0:
                continue
            exp      = next((e for e in t.options if datetime.strptime(e, "%Y-%m-%d").date() >= ed), None)
            if not exp:
                continue
            chain    = t.option_chain(exp)
            calls, puts = chain.calls, chain.puts
            if calls.empty or puts.empty:
                continue

            atm   = calls.iloc[(calls['strike'] - price).abs().argsort()[:1]]['strike'].values[0]
            c_row = calls[calls['strike'] == atm]
            p_row = puts[puts['strike'] == atm]
            if c_row.empty or p_row.empty:
                continue

            straddle  = float(c_row['lastPrice'].values[0]) + float(p_row['lastPrice'].values[0])
            impl_move = straddle / price

            # Historical move
            edf, hist_moves = t.earnings_dates, []
            if edf is not None and not edf.empty:
                h    = t.history(period="3y", auto_adjust=True)
                hmap = {d.date(): float(p) for d, p in h["Close"].items()}
                sd   = sorted(hmap.keys())
                for i, ts in enumerate(edf.index[:6]):
                    ed2 = ts.date() if hasattr(ts, 'date') else ts
                    for j, d in enumerate(sd):
                        if d >= ed2 and j > 0:
                            prev = hmap[sd[j-1]]
                            curr = hmap[d]
                            if prev > 0:
                                hist_moves.append(abs(curr - prev) / prev)
                            break
            hist_avg = sum(hist_moves) / len(hist_moves) if hist_moves else 0.0

            if hist_avg == 0 or impl_move == 0 or (hist_avg / impl_move) < 1.1:
                log.info(f"Earnings {sym}: no buyer edge")
                continue

            otm_calls = calls[calls['strike'] > atm]
            if otm_calls.empty:
                continue
            row       = otm_calls.iloc[0]
            call_px   = float(row['lastPrice'])
            call_str  = float(row['strike'])
            contracts = min(int(max_risk // (call_px * 100)), MAX_CONTRACTS)
            if contracts < 1:
                continue

            results.append({
                "strategy": "lotto", "symbol": sym, "right": "CALL",
                "option_symbol": _occ(sym, exp, "CALL", call_str),
                "strike": call_str, "expiry": exp,
                "contracts": contracts, "entry_price_est": call_px,
                "earnings_date": str(ed),
                "hard_close_date": str(ed - timedelta(days=1)),
                "hard_close_time": None,
                "catalyst": f"earnings {ed}",
            })
        except Exception as exc:
            log.warning(f"Earnings scan {sym}: {exc}")

    return results


def find_breakouts(account: float) -> list[dict]:
    max_risk = account * MAX_RISK_PCT
    results  = []
    for sym in DEFAULT_SYMBOLS:
        try:
            t    = yf.Ticker(sym)
            hist = t.history(period="30d", auto_adjust=True)
            if len(hist) < 22:
                continue
            closes    = hist["Close"].values
            volumes   = hist["Volume"].values
            price     = float(closes[-1])
            high_20   = float(max(closes[-21:-1]))
            avg_vol   = float(sum(volumes[-21:-1]) / 20)
            today_vol = float(volumes[-1])
            if not (price >= high_20 * 0.99 and today_vol >= avg_vol * VOLUME_SPIKE):
                continue
            available = t.options
            if not available or len(available) < 2:
                continue
            exp       = available[1]
            tgt_str   = round(price * 1.02 / 0.5) * 0.5
            chain     = t.option_chain(exp)
            if chain.calls.empty:
                continue
            row       = chain.calls.iloc[(chain.calls['strike'] - tgt_str).abs().argsort()[:1]]
            call_px   = float(row['lastPrice'].values[0])
            call_str  = float(row['strike'].values[0])
            contracts = min(int(max_risk // (call_px * 100)), MAX_CONTRACTS)
            if contracts < 1:
                continue
            results.append({
                "strategy": "breakout", "symbol": sym, "right": "CALL",
                "option_symbol": _occ(sym, exp, "CALL", call_str),
                "strike": call_str, "expiry": exp,
                "contracts": contracts, "entry_price_est": call_px,
                "hard_close_date": str(date.today() + timedelta(days=3)),
                "hard_close_time": None, "catalyst": f"breakout vol {round(today_vol/avg_vol,1)}x",
            })
        except Exception as exc:
            log.warning(f"Breakout scan {sym}: {exc}")
    return results


# ---------------------------------------------------------------------------
# Order submission with retry
# ---------------------------------------------------------------------------

def _utc_now_text() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _entry_quality_snapshot(
    setup: dict,
    filled_price: float,
    fill_price_source: str,
    now_et: datetime | None = None,
) -> dict:
    """Durable entry-quality telemetry. Pure function; no behavior change.

    Records what Phase 1 auditing needs and the old records lacked: entry
    minute, estimate-vs-fill slippage, whether the fill price is broker truth
    or an estimate fallback, spread at signal time, and the structured signal
    snapshot instead of only a flattened catalyst string.
    """
    now_et = now_et or _now_et()
    est = float(setup.get("entry_price_est", 0.0) or 0.0)
    slippage = round(filled_price - est, 4) if est > 0 else None
    slippage_pct = round((filled_price - est) / est * 100, 2) if est > 0 else None
    return {
        "entry_minute_et": now_et.strftime("%H:%M"),
        "entry_price_est": est or None,
        "filled_price": filled_price,
        "fill_price_source": fill_price_source,
        "slippage_per_contract": slippage,
        "slippage_pct": slippage_pct,
        "spread_cents_at_signal": setup.get("spread_cents"),
        "selection_bid": setup.get("selection_bid"),
        "selection_ask": setup.get("selection_ask"),
        "entry_limit_price": setup.get("entry_limit_price"),
        "entry_live_ask_at_submit": setup.get("entry_live_ask_at_submit"),
        "entry_quote_timestamp_at_submit": setup.get("entry_quote_timestamp_at_submit"),
        "entry_quote_age_seconds_at_submit": setup.get("entry_quote_age_seconds_at_submit"),
        "entry_slippage_guard_max_pct": setup.get("entry_slippage_guard_max_pct"),
        "quote_timestamp": setup.get("quote_timestamp"),
        "quote_age_seconds": setup.get("quote_age_seconds"),
        "orb_direction": setup.get("orb_direction"),
        "orb_entry_pattern": setup.get("orb_entry_pattern"),
        "orb_retest_status": setup.get("orb_retest_status"),
        "orb_retest_age_bars": setup.get("orb_retest_age_bars"),
        "entry_evidence_gate": setup.get("entry_evidence_gate"),
        "signal_snapshot": setup.get("signal_snapshot"),
        "feature_snapshot": _entry_feature_snapshot(setup),
    }


def _entry_feature_snapshot(setup: dict) -> dict:
    """Normalize entry context for forward ablation without changing behavior."""
    signal = setup.get("signal_snapshot") if isinstance(setup.get("signal_snapshot"), dict) else {}
    reasons = {str(reason).strip().lower() for reason in signal.get("reasons") or []}
    breadth = [str(symbol).upper() for symbol in setup.get("breadth_confirmed") or []]
    squeeze = setup.get("ttm_squeeze") if isinstance(setup.get("ttm_squeeze"), dict) else {}
    consensus = setup.get("shadow_consensus") if isinstance(setup.get("shadow_consensus"), dict) else {}
    return {
        "schema_version": 1,
        "strategy": setup.get("strategy"),
        "right": setup.get("right"),
        "confidence": setup.get("confidence", setup.get("score")),
        "above_vwap": "above vwap" in reasons,
        "below_vwap": "below vwap" in reasons,
        "above_ema50": "above 50ema" in reasons,
        "below_ema50": "below 50ema" in reasons,
        "ema50_sloping_up": "50ema sloping up" in reasons,
        "ema50_sloping_down": "50ema sloping down" in reasons,
        "green_session": "green session" in reasons,
        "red_session": "red session" in reasons,
        "not_extended_from_vwap": "not extended from vwap" in reasons,
        "pullback_held_trend": "pullback held trend" in reasons,
        "pullback_failed_near_trend": "pullback failed near trend" in reasons,
        "breadth_count": len(breadth),
        "breadth_spy": "SPY" in breadth,
        "breadth_qqq": "QQQ" in breadth,
        "breadth_iwm": "IWM" in breadth,
        "orb_direction": setup.get("orb_direction"),
        "orb_entry_pattern": setup.get("orb_entry_pattern"),
        "orb_breakout_at": setup.get("orb_breakout_at"),
        "orb_retest_at": setup.get("orb_retest_at"),
        "orb_retest_status": setup.get("orb_retest_status"),
        "orb_retest_age_bars": setup.get("orb_retest_age_bars"),
        "orb_retest_tolerance": setup.get("orb_retest_tolerance"),
        "retest_quality_score": setup.get("retest_quality_score"),
        "retest_grade": setup.get("retest_grade"),
        "pre_retest_extension_pct": setup.get("pre_retest_extension_pct"),
        "minutes_since_breakout": setup.get("minutes_since_breakout"),
        "retest_volume_ratio": setup.get("retest_volume_ratio"),
        "retest_quality_authority": setup.get("retest_quality_authority"),
        "orb_breakout_candle_atr_ratio": setup.get("orb_breakout_candle_atr_ratio"),
        "orb_dislocation_velocity_zscore": setup.get("orb_dislocation_velocity_zscore"),
        "orb_breakout_close_location_value": setup.get("orb_breakout_close_location_value"),
        "orb_breakout_directional_close_location_value": setup.get("orb_breakout_directional_close_location_value"),
        "orb_dislocation_status": setup.get("orb_dislocation_status"),
        "expected_move_telemetry_status": setup.get("expected_move_telemetry_status"),
        "atm_iv_at_entry": setup.get("atm_iv_at_entry"),
        "expected_move_points": setup.get("expected_move_points"),
        "opening_range_fraction": setup.get("opening_range_fraction"),
        "opening_range_bucket": setup.get("opening_range_bucket"),
        "expected_move_consumed_fraction": setup.get("expected_move_consumed_fraction"),
        "breakout_overshoot_fraction": setup.get("breakout_overshoot_fraction"),
        "premium_level_telemetry_status": setup.get("premium_level_telemetry_status"),
        "premium_level_feed_provenance": setup.get("premium_level_feed_provenance"),
        "premium_level_provenance_qualified": setup.get("premium_level_provenance_qualified"),
        "premium_level_trade_history_complete": setup.get("premium_level_trade_history_complete"),
        "premium_level_dominant_right": setup.get("premium_level_dominant_right"),
        "premium_level_top_call": setup.get("premium_level_top_call"),
        "premium_level_top_put": setup.get("premium_level_top_put"),
        "premium_level_nearest_call": setup.get("premium_level_nearest_call"),
        "premium_level_nearest_put": setup.get("premium_level_nearest_put"),
        "premium_level_nearest_call_distance_pct": setup.get("premium_level_nearest_call_distance_pct"),
        "premium_level_nearest_put_distance_pct": setup.get("premium_level_nearest_put_distance_pct"),
        "shadow_setup_authority": setup.get("shadow_setup_authority"),
        "shadow_setup_grade_context": setup.get("shadow_setup_grade_context"),
        "shadow_prior_day_aligned": setup.get("shadow_prior_day_aligned"),
        "shadow_prior_day_high": setup.get("shadow_prior_day_high"),
        "shadow_prior_day_low": setup.get("shadow_prior_day_low"),
        "shadow_opening_15m_high": setup.get("shadow_opening_15m_high"),
        "shadow_opening_15m_low": setup.get("shadow_opening_15m_low"),
        "shadow_swept_level_name": setup.get("shadow_swept_level_name"),
        "shadow_swept_level": setup.get("shadow_swept_level"),
        "shadow_target_level_name": setup.get("shadow_target_level_name"),
        "shadow_social_claim_status": setup.get("shadow_social_claim_status"),
        "shadow_underlying_counterfactual": setup.get("shadow_underlying_counterfactual"),
        "noise_area_status": setup.get("noise_area_status"),
        "noise_area_formula_version": setup.get("noise_area_formula_version"),
        "noise_area_direction": setup.get("noise_area_direction"),
        "noise_area_upper_band": setup.get("noise_area_upper_band"),
        "noise_area_lower_band": setup.get("noise_area_lower_band"),
        "noise_area_vwap": setup.get("noise_area_vwap"),
        "noise_area_fraction": setup.get("noise_area_fraction"),
        "noise_area_structural_stop": setup.get("noise_area_structural_stop"),
        "noise_area_lookback_sessions": setup.get("noise_area_lookback_sessions"),
        "ttm_state": squeeze.get("state"),
        "ttm_first_release": bool(squeeze.get("first_release")),
        "ttm_momentum_rising": bool(squeeze.get("momentum_rising")),
        "shadow_consensus_recommendation": consensus.get("recommendation"),
        "market_force_snapshot_status": setup.get("market_force_snapshot_status"),
        "market_force_classification": setup.get("market_force_classification"),
        "market_context_snapshot_status": setup.get("market_context_snapshot_status"),
        "candlestick_context_status": setup.get("candlestick_context_status"),
        "candlestick_bias": setup.get("candlestick_bias"),
        "candlestick_primary_signal": setup.get("candlestick_primary_signal"),
        "candlestick_features": setup.get("candlestick_features") or [],
        "candlestick_veto_reasons": setup.get("candlestick_veto_reasons") or [],
        "candlestick_volume_expansion": setup.get("candlestick_volume_expansion"),
        "htf_context_status": setup.get("htf_context_status"),
        "htf_primary_bias": setup.get("htf_primary_bias"),
        "htf_intraday_alignment": setup.get("htf_intraday_alignment"),
        "htf_veto_reasons": setup.get("htf_veto_reasons") or [],
        "catalyst_context_status": setup.get("catalyst_context_status"),
        "catalyst_max_impact": setup.get("catalyst_max_impact"),
        "catalyst_vetoes": setup.get("catalyst_vetoes") or [],
        "spread_cents_at_signal": setup.get("spread_cents"),
        "quote_age_seconds": setup.get("quote_age_seconds"),
        "day_type": setup.get("day_type"),
        "day_type_recommended_strategy": setup.get("day_type_recommended_strategy"),
        "day_type_router_authority": setup.get("day_type_router_authority") or (
            setup.get("day_type_classification") or {}
        ).get("authority"),
        "contract_rank_status": setup.get("contract_rank_status"),
        "contract_rank_score": setup.get("contract_rank_score"),
        "contract_rank_disqualified": setup.get("contract_rank_disqualified"),
        "contract_rank_authority": setup.get("contract_rank_authority"),
    }


def _update_pnl_extremes(trade: dict, pnl_pct: float) -> bool:
    """Track MFE (best) and MAE (worst) P&L percent. Returns True if changed."""
    changed = False
    if trade.get("best_pnl_pct") is None:
        trade["best_pnl_pct"] = 0.0
        changed = True
    if trade.get("worst_pnl_pct") is None:
        trade["worst_pnl_pct"] = 0.0
        changed = True
    best = max(float(trade.get("best_pnl_pct", 0.0)), pnl_pct)
    if best != trade.get("best_pnl_pct"):
        trade["best_pnl_pct"] = round(best, 2)
        changed = True
    worst = min(float(trade.get("worst_pnl_pct", 0.0)), pnl_pct)
    if worst != trade.get("worst_pnl_pct"):
        trade["worst_pnl_pct"] = round(worst, 2)
        changed = True
    return changed


def _path_telemetry_baseline() -> dict:
    """Entry-time path baseline for forward trades; prevents restart gaps."""
    return {
        "best_pnl_pct": 0.0,
        "worst_pnl_pct": 0.0,
        "path_telemetry_schema_version": 1,
        "path_telemetry_source": "forward_observed_lifecycle",
        "path_telemetry_observed": True,
        "telemetry_quality": "forward_observed",
        "telemetry_provenance": {
            "entry_at": "observed_entry_fill_lifecycle",
            "exit_at": "observed_exit_fill_lifecycle",
            "best_pnl_pct": "observed_monitor_and_exit_quotes",
            "worst_pnl_pct": "observed_monitor_and_exit_quotes",
        },
    }


def _profit_protect_lock_floor(best_pnl_pct: float) -> float:
    """Return the protected P&L floor after the runner ratchet is armed."""
    floor = max(PROFIT_PROTECT_FLOOR_PCT, best_pnl_pct - PROFIT_PROTECT_GIVEBACK_PCT)
    for threshold, tier_floor in PROFIT_PROTECT_TIER_FLOORS:
        if best_pnl_pct >= threshold:
            floor = max(floor, tier_floor)
            break
    return floor


def _stamp_exit(
    trade: dict,
    mid: float,
    reason: str,
    exit_order_id: str | None = None,
    *,
    exit_price_source: str = "quote_mid_at_order_submission",
) -> None:
    """Write the exit fields consistently (single close path for records)."""
    entry = float(trade.get("entry_price", 0.0) or 0.0)
    qty = int(trade.get("contracts", 0) or 0)
    trade["status"] = "closed"
    trade["exit_price"] = mid
    trade["exit_reason"] = reason
    trade["exit_date"] = str(date.today())
    trade["exit_at"] = _utc_now_text()
    trade["pnl"] = round((mid - entry) * qty * 100, 2)
    if entry > 0:
        _update_pnl_extremes(trade, (mid - entry) / entry * 100)
    trade["path_telemetry_observed"] = True
    trade["exit_price_source"] = exit_price_source
    if exit_order_id:
        trade["exit_order_id"] = exit_order_id


_FAILED_EXIT_ORDER_STATUSES = {"canceled", "expired", "rejected", "replaced", "stopped", "suspended"}


def _clear_pending_exit(trade: dict) -> None:
    for key in (
        "exit_pending_order_id",
        "exit_pending_reason",
        "exit_pending_trigger_price",
        "exit_pending_submitted_at",
        "exit_order_status",
    ):
        trade.pop(key, None)


def _filled_order_price(order: dict) -> float:
    try:
        return float(order.get("filled_avg_price") or 0.0)
    except (TypeError, ValueError):
        return 0.0


def _finalize_exit_fill(trade: dict, order: dict) -> bool:
    """Finalize an exit only after the broker reports a real fill."""
    order_id = str(order.get("id") or trade.get("exit_pending_order_id") or "")
    status = str(order.get("status") or "").strip().lower()
    trade["exit_order_status"] = status or "unknown"
    if status != "filled":
        return False
    fill_price = _filled_order_price(order)
    if fill_price <= 0:
        log.warning(f"Exit order {order_id} reports filled without filled_avg_price; keep monitoring")
        return False
    reason = str(trade.get("exit_pending_reason") or trade.get("exit_reason") or "broker exit fill")
    _stamp_exit(
        trade,
        fill_price,
        reason,
        order_id or None,
        exit_price_source="broker_filled_avg_price",
    )
    _clear_pending_exit(trade)
    trade["exit_order_status"] = "filled"
    return True


def _stage_exit_order(trade: dict, response: dict, reason: str, trigger_price: float) -> str:
    """Record a close submission without pretending acceptance is a fill."""
    order_id = str(response.get("id") or "")
    if not order_id:
        return "invalid"
    trade["exit_pending_order_id"] = order_id
    trade["exit_pending_reason"] = reason
    trade["exit_pending_trigger_price"] = trigger_price
    trade["exit_pending_submitted_at"] = _utc_now_text()
    trade["exit_order_status"] = str(response.get("status") or "submitted").strip().lower()
    if _finalize_exit_fill(trade, response):
        return "filled"
    return "pending"


def _refresh_pending_exit(trade: dict) -> str:
    """Poll one pending close. Pending orders remain protected and are never duplicated."""
    order_id = str(trade.get("exit_pending_order_id") or "")
    if not order_id:
        return "none"
    try:
        detail = _get(f"/v2/orders/{order_id}")
    except Exception as exc:
        log.warning(f"Unable to refresh pending exit {order_id}: {exc}")
        return "pending"
    status = str(detail.get("status") or "").strip().lower()
    if _finalize_exit_fill(trade, detail):
        return "filled"
    if status in _FAILED_EXIT_ORDER_STATUSES:
        trade["last_exit_order_failure"] = {
            "order_id": order_id,
            "status": status,
            "observed_at": _utc_now_text(),
        }
        _clear_pending_exit(trade)
        return "failed"
    return "pending"


def _retire_resting_take_profit(trade: dict, status: str, order_id: str) -> None:
    trade["resting_tp_last_terminal"] = {
        "order_id": order_id,
        "status": status,
        "observed_at": _utc_now_text(),
    }
    trade.pop("resting_tp_order_id", None)
    trade.pop("resting_tp_submitted_at", None)
    trade["resting_tp_status"] = status


def _finalize_resting_take_profit(trade: dict, order: dict) -> bool:
    """Close durable state only after the resting target is broker-filled."""
    status = str(order.get("status") or "").strip().lower()
    if status != "filled":
        return False
    fill_price = _filled_order_price(order)
    if fill_price <= 0:
        return False
    order_id = str(order.get("id") or trade.get("resting_tp_order_id") or "")
    _stamp_exit(
        trade,
        fill_price,
        "PROFIT TARGET (resting limit)",
        order_id or None,
        exit_price_source="broker_filled_avg_price",
    )
    trade["exit_order_status"] = "filled"
    trade["resting_tp_order_id"] = order_id
    trade["resting_tp_status"] = "filled"
    trade["resting_tp_fill_price"] = fill_price
    return True


def _submit_resting_take_profit(trade: dict) -> str:
    """Place one DAY target order for a confirmed, single-leg long-option fill."""
    if trade.get("status") != "open" or trade.get("short_option_symbol"):
        return "ineligible"
    if trade.get("entry_price_source") != "broker_fill" or trade.get("entry_fill_confirmed") is not True:
        trade["resting_tp_status"] = "skipped_unconfirmed_entry_fill"
        return "ineligible"
    if trade.get("resting_tp_order_id"):
        return "existing"
    qty = int(trade.get("contracts") or 0)
    target = float(trade.get("target_price") or 0.0)
    if qty < 1 or target <= 0:
        trade["resting_tp_status"] = "skipped_invalid_target"
        return "ineligible"
    resting_price = round(target, 2)
    response = _submit(
        str(trade.get("option_symbol") or ""),
        qty,
        "sell",
        limit_price=resting_price,
    )
    if not response or not response.get("id"):
        trade["resting_tp_status"] = "submission_failed"
        return "failed"
    trade["resting_tp_order_id"] = str(response["id"])
    trade["resting_tp_status"] = str(response.get("status") or "submitted").strip().lower()
    trade["resting_tp_price"] = resting_price
    trade["resting_tp_submitted_at"] = _utc_now_text()
    if _finalize_resting_take_profit(trade, response):
        return "filled"
    return "submitted"


def _refresh_resting_take_profit(trade: dict) -> str:
    """Refresh an active resting target without blocking software protection."""
    order_id = str(trade.get("resting_tp_order_id") or "")
    if not order_id:
        return "none"
    try:
        detail = _get(f"/v2/orders/{order_id}")
    except Exception as exc:
        log.warning(f"Unable to refresh resting take-profit {order_id}: {exc}")
        return "pending"
    status = str(detail.get("status") or "").strip().lower()
    trade["resting_tp_status"] = status or "unknown"
    if _finalize_resting_take_profit(trade, detail):
        return "filled"
    if status in _FAILED_EXIT_ORDER_STATUSES:
        _retire_resting_take_profit(trade, status, order_id)
        log.warning(f"Resting take-profit {order_id} became {status}; software exits remain active")
        return "terminal"
    return "pending"


def _cancel_resting_take_profit(trade: dict) -> str:
    """Cancel and confirm a resting target before any competing software sell."""
    order_id = str(trade.get("resting_tp_order_id") or "")
    if not order_id:
        return "none"
    try:
        _delete(f"/v2/orders/{order_id}")
    except Exception as exc:
        # A cancel can lose the race to a fill. Poll before deciding it failed.
        log.warning(f"Cancel request for resting take-profit {order_id} returned: {exc}")
    for attempt in range(3):
        try:
            detail = _get(f"/v2/orders/{order_id}")
        except Exception as exc:
            log.warning(f"Cancel confirmation {attempt + 1}/3 failed for {order_id}: {exc}")
        else:
            status = str(detail.get("status") or "").strip().lower()
            trade["resting_tp_status"] = status or "unknown"
            if _finalize_resting_take_profit(trade, detail):
                return "filled"
            if status in _FAILED_EXIT_ORDER_STATUSES:
                _retire_resting_take_profit(trade, status, order_id)
                return "canceled"
        if attempt < 2:
            time.sleep(1)
    trade["resting_tp_status"] = "cancel_unconfirmed"
    return "pending"


_ACTIVE_ENTRY_ORDER_STATUSES = {
    "accepted",
    "accepted_for_bidding",
    "calculated",
    "new",
    "partially_filled",
    "pending_new",
    "pending_replace",
}


def _parse_filled_qty(order: dict) -> float:
    try:
        return float(order.get("filled_qty") or 0.0)
    except (TypeError, ValueError):
        return 0.0


def _cancel_entry_order(order_id: str) -> dict:
    """Cancel an unfilled entry and return the latest broker view."""
    latest: dict = {"id": order_id, "status": "cancel_unknown"}
    try:
        _delete(f"/v2/orders/{order_id}")
    except Exception as exc:
        log.warning(f"Entry cancel request for {order_id} returned: {exc}")
    for attempt in range(3):
        try:
            detail = _get(f"/v2/orders/{order_id}")
            if isinstance(detail, dict):
                latest = detail
        except Exception as exc:
            log.warning(f"Entry cancel confirmation {attempt + 1}/3 failed for {order_id}: {exc}")
        status = str(latest.get("status") or "").strip().lower()
        if status in _FAILED_EXIT_ORDER_STATUSES or status == "filled":
            return latest
        if attempt < 2:
            time.sleep(1)
    return latest


def _resolve_entry_fill(resp: dict, setup: dict) -> dict:
    """Return the exact broker-confirmed entry state before writing a trade."""
    order_id = str(resp.get("id") or "")
    requested_qty = int(setup.get("contracts") or 0)
    detail = dict(resp)
    if order_id:
        try:
            broker_detail = _get(f"/v2/orders/{order_id}")
            if isinstance(broker_detail, dict):
                detail = broker_detail
        except Exception as exc:
            log.warning(f"Entry fill check failed for {order_id}: {exc}")

    status = str(detail.get("status") or resp.get("status") or "").strip().lower()
    filled_qty = _parse_filled_qty(detail)
    raw_fill = detail.get("filled_avg_price")
    fill_price = 0.0
    fill_price_source = "unavailable"
    if raw_fill:
        try:
            fill_price = float(raw_fill)
            fill_price_source = "broker_fill"
        except (TypeError, ValueError):
            fill_price = 0.0
            fill_price_source = "unavailable"

    latest_after_cancel = detail
    if filled_qty < requested_qty and status in _ACTIVE_ENTRY_ORDER_STATUSES and order_id:
        latest_after_cancel = _cancel_entry_order(order_id)
        status = str(latest_after_cancel.get("status") or status).strip().lower()
        filled_qty = _parse_filled_qty(latest_after_cancel)
        raw_fill = latest_after_cancel.get("filled_avg_price") or raw_fill
        if raw_fill:
            try:
                fill_price = float(raw_fill)
                fill_price_source = "broker_fill"
            except (TypeError, ValueError):
                pass

    confirmed_qty = int(filled_qty)
    if confirmed_qty < 1:
        return {
            "track": False,
            "order_status": status or "unknown",
            "filled_qty": filled_qty,
            "cancel_status": str(latest_after_cancel.get("status") or status or "unknown"),
            "reason": "entry_not_filled_confirmed",
        }

    if fill_price <= 0:
        fill_price = float(setup.get("entry_price_est") or 0.0)
        fill_price_source = "broker_qty_estimate_price"

    return {
        "track": True,
        "contracts": min(confirmed_qty, requested_qty),
        "requested_contracts": requested_qty,
        "entry_price": fill_price,
        "entry_price_source": fill_price_source,
        "entry_order_status": status or "unknown",
        "entry_filled_qty": filled_qty,
        "entry_fill_confirmed": fill_price_source == "broker_fill",
        "entry_partial_fill": confirmed_qty < requested_qty,
        "entry_remainder_status": str(latest_after_cancel.get("status") or status or "unknown"),
        "broker_submitted_at": latest_after_cancel.get("submitted_at") or detail.get("submitted_at") or resp.get("submitted_at"),
        "broker_filled_at": latest_after_cancel.get("filled_at") or detail.get("filled_at") or resp.get("filled_at"),
    }


def _parse_timestamp(value: object) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _entry_execution_snapshot(setup: dict, entry_fill: dict, submitted_at: str) -> dict:
    """Normalize broker execution evidence for chronological forward review."""
    broker_submitted_at = entry_fill.get("broker_submitted_at") or submitted_at
    broker_filled_at = entry_fill.get("broker_filled_at")
    submitted_ts = _parse_timestamp(broker_submitted_at)
    filled_ts = _parse_timestamp(broker_filled_at)
    delay_seconds = None
    if submitted_ts and filled_ts:
        delay_seconds = round(max(0.0, (filled_ts - submitted_ts).total_seconds()), 3)

    signal_ask = float(setup.get("selection_ask") or 0.0)
    submit_ask = float(setup.get("entry_live_ask_at_submit") or 0.0)
    filled_price = float(entry_fill.get("entry_price") or 0.0)
    fill_vs_signal_ask_pct = (
        round((filled_price - signal_ask) / signal_ask * 100.0, 3)
        if signal_ask > 0 and filled_price > 0 else None
    )
    fill_vs_submit_ask_pct = (
        round((filled_price - submit_ask) / submit_ask * 100.0, 3)
        if submit_ask > 0 and filled_price > 0 else None
    )
    return {
        "schema_version": 1,
        "entry_evidence_gate": setup.get("entry_evidence_gate"),
        "signal_quote_ask": signal_ask or None,
        "submit_quote_ask": submit_ask or None,
        "submit_quote_timestamp": setup.get("entry_quote_timestamp_at_submit"),
        "submit_quote_age_seconds": setup.get("entry_quote_age_seconds_at_submit"),
        "local_submitted_at": submitted_at,
        "broker_submitted_at": broker_submitted_at,
        "broker_filled_at": broker_filled_at,
        "submit_to_fill_seconds": delay_seconds,
        "filled_price": filled_price or None,
        "fill_vs_signal_ask_pct": fill_vs_signal_ask_pct,
        "fill_vs_submit_ask_pct": fill_vs_submit_ask_pct,
        "orb_entry_pattern": setup.get("orb_entry_pattern"),
        "orb_retest_status": setup.get("orb_retest_status"),
        "orb_retest_age_bars": setup.get("orb_retest_age_bars"),
    }


def _capture_point_in_time(
    event: str,
    trade: dict,
    context: dict | None = None,
    *,
    blocking: bool = False,
) -> list:
    """Capture point-in-time quotes/Greeks without blocking trading decisions.

    Production calls run on non-daemon threads, so network latency cannot
    delay an order but Python still waits for durable telemetry before the
    task process exits. ``blocking`` exists for deterministic unit tests.
    """
    import threading

    workers = []
    try:
        try:
            from scripts.point_in_time_quotes import capture_lifecycle_sample
        except ModuleNotFoundError:
            sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
            from point_in_time_quotes import capture_lifecycle_sample  # type: ignore
        legs = [
            ("long", trade.get("option_symbol")),
            ("short", trade.get("short_option_symbol")),
        ]
        capture_args = {
            "bot": "flip",
            "headers": dict(HDR),
            "trade_id": trade.get("id") or trade.get("telemetry_trade_id"),
            "order_id": trade.get("alpaca_order_id"),
            "underlying_symbol": trade.get("symbol"),
        }
        for leg_role, occ in [(role, leg) for role, leg in legs if leg]:
            leg_args = dict(capture_args)
            leg_args["context"] = {**dict(context or {}), "leg_role": leg_role}
            if blocking:
                capture_lifecycle_sample(event, occ, **leg_args)
                continue
            worker = threading.Thread(
                target=capture_lifecycle_sample,
                args=(event, occ),
                kwargs=leg_args,
                name=f"pit-{event}-{occ}",
                daemon=False,
            )
            worker.start()
            workers.append(worker)
    except Exception as exc:
        log.warning(f"point-in-time telemetry skipped ({event}): {exc}")
    return workers


def _submit(
    occ_symbol: str,
    qty: int,
    side: str,
    max_notional: float = 0.0,
    *,
    limit_price: float | None = None,
) -> dict | None:
    if qty > MAX_CONTRACTS:
        log.error(f"ORDER BLOCKED: {qty} contracts exceeds MAX_CONTRACTS={MAX_CONTRACTS}")
        _alert(f"ORDER BLOCKED {occ_symbol}: {qty} contracts > hard cap {MAX_CONTRACTS}")
        return None
    if max_notional > 0 and side == "buy":
        live_mid = _option_mid(occ_symbol)
        if live_mid > 0:
            notional = live_mid * qty * 100
            if notional > max_notional:
                log.error(f"ORDER BLOCKED: notional ${notional:.0f} > budget ${max_notional:.0f} (live mid ${live_mid:.3f} vs stale est)")
                _alert(f"ORDER BLOCKED {occ_symbol} x{qty}: live cost ${notional:.0f} > risk budget ${max_notional:.0f}")
                return None
    if side == "buy" and manual_reset_required():
        msg = f"MANUAL RESET REQUIRED - order blocked by {DEFAULT_BLOCK_FILE}"
        log.error(msg)
        _alert(f"ORDER BLOCKED {occ_symbol} x{qty} {side}\nManual reset required before any new orders.")
        return None

    body = {"symbol": occ_symbol, "qty": str(qty), "side": side, "time_in_force": "day"}
    if limit_price is not None:
        body["type"] = "limit"
        body["limit_price"] = str(round(float(limit_price), 2))
    else:
        body["type"] = "market"
    for attempt in range(3):
        try:
            resp = _post("/v2/orders", body)
            limit_note = f" limit=${float(limit_price):.2f}" if limit_price is not None else ""
            log.info(f"Order OK: {resp.get('id')} {side} {occ_symbol} x{qty}{limit_note}")
            return resp
        except Exception as exc:
            status = getattr(getattr(exc, 'response', None), 'status_code', 0)
            if status in (429, 500, 502, 503) and attempt < 2:
                wait = 2 ** attempt * 3
                log.warning(f"Attempt {attempt+1} failed ({status}), retry in {wait}s")
                time.sleep(wait)
            else:
                log.error(f"Order failed: {exc}")
                _alert(f"ORDER FAILED {occ_symbol} x{qty} {side}\n{exc}")
                return None
    return None


def _submit_spread(setup: dict, max_notional: float = 0.0) -> dict | None:
    qty = int(setup.get("contracts", 0))
    if qty > MAX_CONTRACTS:
        log.error(f"ORDER BLOCKED: {qty} spread contracts exceeds MAX_CONTRACTS={MAX_CONTRACTS}")
        return None
    if qty < 1:
        return None

    debit = float(setup.get("entry_price_est", 0.0) or 0.0)
    notional = debit * qty * 100
    if max_notional > 0 and notional > max_notional:
        log.error(f"ORDER BLOCKED: spread notional ${notional:.0f} > budget ${max_notional:.0f}")
        _alert(f"ORDER BLOCKED spread {setup.get('symbol')} x{qty}: cost ${notional:.0f} > risk budget ${max_notional:.0f}")
        return None
    if manual_reset_required():
        msg = f"MANUAL RESET REQUIRED - spread order blocked by {DEFAULT_BLOCK_FILE}"
        log.error(msg)
        _alert(f"ORDER BLOCKED spread {setup.get('symbol')} x{qty}\nManual reset required before any new orders.")
        return None

    body = {
        "order_class": "mleg",
        "qty": str(qty),
        "type": "limit",
        "limit_price": str(round(debit, 2)),
        "time_in_force": "day",
        "legs": [
            {"symbol": setup["option_symbol"], "side": "buy", "ratio_qty": "1"},
            {"symbol": setup["short_option_symbol"], "side": "sell", "ratio_qty": "1"},
        ],
    }
    try:
        resp = _post("/v2/orders", body)
        log.info(
            f"Spread order OK: {resp.get('id')} buy {setup['option_symbol']} / "
            f"sell {setup['short_option_symbol']} x{qty} debit=${debit:.2f}"
        )
        return resp
    except Exception as exc:
        log.error(f"Spread order failed: {exc}")
        _alert(f"SPREAD ORDER FAILED {setup.get('symbol')} x{qty}\n{exc}")
        return None


def _spread_mid(long_symbol: str, short_symbol: str) -> float:
    long_mid = _option_mid(long_symbol)
    short_mid = _option_mid(short_symbol)
    if long_mid <= 0 or short_mid < 0:
        return 0.0
    return round(max(0.0, long_mid - short_mid), 3)


def _close_spread(trade: dict) -> dict | None:
    qty = int(trade.get("contracts", 0))
    if qty < 1:
        return None
    body = {
        "order_class": "mleg",
        "qty": str(qty),
        "type": "market",
        "time_in_force": "day",
        "legs": [
            {"symbol": trade["option_symbol"], "side": "sell", "ratio_qty": "1"},
            {"symbol": trade["short_option_symbol"], "side": "buy", "ratio_qty": "1"},
        ],
    }
    try:
        resp = _post("/v2/orders", body)
        log.info(
            f"Spread close OK: {resp.get('id')} sell {trade['option_symbol']} / "
            f"buy {trade['short_option_symbol']} x{qty}"
        )
        return resp
    except Exception as exc:
        log.error(f"Spread close failed: {exc}")
        _alert(f"SPREAD CLOSE FAILED {trade.get('symbol')} x{qty}\n{exc}")
        return None


# ---------------------------------------------------------------------------
# Entry run
# ---------------------------------------------------------------------------

def run_entry(account: float, *, intraday_only: bool = False) -> None:
    lane = "INTRADAY SPY" if intraday_only else "FULL"
    log.info(f"=== FLIP ENTRY {lane}  ${account:.0f}  {'PAPER' if PAPER else 'LIVE'} ===")
    if intraday_only and not PAPER:
        log.error("INTRADAY SPY ENTRY BLOCKED: this recurring lane is Alpaca paper-only")
        _decision("SPY", "intraday_entry", "blocked", "paper_only_intraday_lane")
        return
    if not PAPER:
        from strategies.flip_live_readiness import evaluate_live_readiness

        try:
            live_account = _get("/v2/account")
        except Exception as exc:
            live_account = {}
            log.error(f"LIVE ENTRY BLOCKED: account preflight failed: {exc}")
        readiness = evaluate_live_readiness(
            live_account if isinstance(live_account, dict) else {},
            live_enabled=LIVE_EXECUTION_ENABLED,
            approval_ack=LIVE_APPROVAL_ACK_VALUE,
        )
        if not readiness.ready:
            reason = ",".join(readiness.blockers)
            log.error(f"LIVE ENTRY BLOCKED: {reason}")
            _alert(f"LIVE FLIP ENTRY BLOCKED\nreason={reason}")
            _decision("SPY", "entry_run", "blocked", "live_readiness_failed", blockers=list(readiness.blockers), readiness=readiness.details)
            return
    if not _market_open():
        _strategy_skip("SPY", "entry_run", "market_closed")
        log.info("Market is closed - skip flip entry")
        return

    all_trades = _load()
    open_trades = [t for t in all_trades if t.get(“status”) == “open”]
    if len(open_trades) >= MAX_OPEN_FLIPS:
        _strategy_skip(“SPY”, “entry_run”, “max_open_positions”, open_count=len(open_trades), maximum=MAX_OPEN_FLIPS)
        log.info(f”Max open ({MAX_OPEN_FLIPS}) reached – skip”)
        return

    if RH_MIMIC_MODE and RH_ACCOUNT_SIZE > 0:
        from strategies.robinhood_mimic import pdt_blocker, pdt_remaining
        pdt_block = pdt_blocker(all_trades, RH_ACCOUNT_SIZE)
        if pdt_block:
            log.warning(f”RH MIMIC PDT BLOCKED: {pdt_block['day_trades_used']}/{pdt_block['day_trades_max']} day trades used in rolling window”)
            _decision(“SPY”, “entry_run”, “blocked”, “rh_mimic_pdt_limit”, **pdt_block)
            _alert(f”RH MIMIC — PDT LIMIT\n{pdt_block['day_trades_used']}/{pdt_block['day_trades_max']} day trades used\nWindow: {pdt_block['rolling_window_start']} to {pdt_block['rolling_window_end']}\nEntry blocked to protect RH account.”)
            return
        capacity = pdt_remaining(all_trades, RH_ACCOUNT_SIZE)
        log.info(f”RH MIMIC PDT: {capacity['day_trades_used']}/{capacity['day_trades_max']} used, {capacity['day_trades_remaining']} remaining”)

    slots      = MAX_OPEN_FLIPS - len(open_trades)
    candidates = []

    if intraday_only:
        # ORB receives first priority. Noise Area is a separate fallback setup,
        # never a second simultaneous SPY trade.
        s = find_0dte(account)
        if s:
            candidates.append(s)
        elif len(candidates) < slots:
            s = find_noise_area_0dte(account)
            if s:
                candidates.append(s)
    else:
        s = find_bear_trend_day(account)
        if s:
            candidates.append(s)

        if len(candidates) < slots:
            s = find_bull_trend_day(account)
            if s:
                candidates.append(s)

        s = find_0dte(account)
        if s and len(candidates) < slots:
            candidates.append(s)

        if PAPER and NOISE_AREA_PAPER_ENABLED and len(candidates) < slots:
            if not any(item.get("symbol") == "SPY" for item in candidates + open_trades):
                s = find_noise_area_0dte(account)
                if s:
                    candidates.append(s)

        if PAPER and len(candidates) < slots:
            for s in find_paper_challenger_0dte(account):
                if len(candidates) >= slots:
                    break
                if not any(t.get("symbol") == s["symbol"] for t in open_trades + candidates):
                    candidates.append(s)

        if len(candidates) < slots:
            for s in find_earnings(account):
                if len(candidates) >= slots:
                    break
                if not any(t.get("symbol") == s["symbol"] for t in open_trades + candidates):
                    candidates.append(s)

        if len(candidates) < slots:
            for s in find_breakouts(account):
                if len(candidates) >= slots:
                    break
                if not any(t.get("symbol") == s["symbol"] for t in open_trades + candidates):
                    candidates.append(s)

    if not candidates:
        log.info("No flip setup today â€” waiting")
        return

    broker_symbols = _fetch_broker_open_symbols()
    if broker_symbols is None:
        log.error("ENTRY BLOCKED: broker positions are unknown; refusing duplicate-position risk")
        _decision("PORTFOLIO", "all", "blocked", "broker_positions_unknown")
        return
    trades = _load()
    daily_loss_pct = _today_realized_loss_pct(trades, account)
    for setup in candidates:
        setup_symbol = str(setup.get("symbol") or "").upper()
        if setup.get("paper_only") and not PAPER:
            log.error(f"EXECUTION BLOCKED {setup_symbol} {setup.get('strategy')}: paper_only_strategy")
            _decision(setup_symbol, setup.get("strategy", "unknown"), "blocked", "paper_only_strategy")
            continue
        authorization = _execution_authorization(setup_symbol, int(setup.get("contracts", 0) or 0))
        if not authorization["allowed"]:
            log.warning(
                f"EXECUTION BLOCKED {setup_symbol} {setup.get('strategy')}: "
                f"symbol_not_promoted execution_symbols={sorted(EXECUTION_SYMBOLS)} "
                f"paper_challengers={sorted(PAPER_CHALLENGER_SYMBOLS) if PAPER else []}"
            )
            _decision(
                setup_symbol,
                setup.get("strategy", "unknown"),
                "blocked",
                "symbol_not_promoted",
                execution_symbols=sorted(EXECUTION_SYMBOLS),
                paper_challengers=sorted(PAPER_CHALLENGER_SYMBOLS) if PAPER else [],
            )
            continue
        if authorization["lane"] == "paper_challenger":
            original_contracts = int(setup.get("contracts", 0) or 0)
            setup["contracts"] = authorization["contracts"]
            setup["execution_lane"] = "paper_challenger"
            setup["paper_challenger_original_contracts"] = original_contracts
            log.info(
                f"PAPER CHALLENGER {setup_symbol} {setup.get('strategy')}: "
                f"contracts {original_contracts} -> {setup['contracts']}"
            )
        if setup.get("paper_research_lane"):
            original_contracts = int(setup.get("contracts", 0) or 0)
            setup["contracts"] = min(original_contracts, NOISE_AREA_PAPER_CONTRACT_CAP)
            setup["execution_lane"] = "paper_research"
            log.info(
                f"PAPER RESEARCH {setup_symbol} {setup.get('strategy')}: "
                f"contracts {original_contracts} -> {setup['contracts']}"
            )
        reentry_block = _same_day_reentry_blocker(setup, trades)
        if reentry_block:
            log.warning(f"EXECUTION BLOCKED {setup.get('symbol')} {setup.get('strategy')}: {reentry_block}")
            _alert(
                f"ORDER BLOCKED {setup.get('symbol')} {setup.get('strategy')}\n"
                f"reason={reentry_block}"
            )
            _decision(setup_symbol, setup.get("strategy", "unknown"), "blocked", "same_day_reentry", blocker=reentry_block)
            continue

        max_notional = account * MAX_RISK_PCT
        is_spread = bool(setup.get("short_option_symbol"))
        setup_playbook = (
            "directional_long_call" if str(setup.get("right") or "").upper() == "CALL"
            else "directional_long_put" if str(setup.get("right") or "").upper() == "PUT"
            else None
        )
        try:
            consensus = shadow_entry_advice(
                setup.get("symbol", ""),
                int(setup.get("contracts", 0) or 0),
                requested_playbook=setup_playbook,
            )
        except TypeError as exc:
            # Preserve compatibility with injected legacy/test advisors while
            # keeping the production advisor playbook-aware.
            if "requested_playbook" not in str(exc):
                raise
            consensus = shadow_entry_advice(
                setup.get("symbol", ""),
                int(setup.get("contracts", 0) or 0),
            )
        if consensus.get("enabled"):
            blockers = ", ".join(consensus.get("blockers") or []) or consensus.get("recommendation", "needs_review")
            if not consensus.get("allowed") and not setup.get("momentum_continuation"):
                log.warning(
                    f"SHADOW CONSENSUS BLOCKED {setup.get('symbol')} {setup.get('strategy')}: "
                    f"{blockers}"
                )
                _alert(
                    f"SHADOW CONSENSUS BLOCKED {setup.get('symbol')} {setup.get('strategy')}\n"
                    f"reason={blockers}"
                )
                _decision(
                    setup_symbol,
                    setup.get("strategy", "unknown"),
                    "blocked",
                    "shadow_consensus_block",
                    blockers=consensus.get("blockers", []),
                    hard_blockers=consensus.get("hard_blockers", []),
                    alpha_advisory_only=consensus.get("alpha_advisory_only", False),
                    recommendation=consensus.get("recommendation"),
                    right=setup.get("right"),
                    orb_direction=setup.get("orb_direction"),
                    catalyst=setup.get("catalyst"),
                    setup_score=setup.get("score"),
                )
                continue
            if not consensus.get("allowed") and setup.get("momentum_continuation"):
                log.info(
                    f"MOMENTUM CONTINUATION {setup.get('symbol')}: shadow consensus advisory "
                    f"({blockers}) — proceeding with 1-contract momentum entry"
                )
            primary_caution = _primary_consensus_caution_blocker(setup, consensus)
            if primary_caution:
                log.warning(
                    f"PRIMARY CONSENSUS CAUTION BLOCKED {setup.get('symbol')} {setup.get('strategy')}: "
                    f"{primary_caution}"
                )
                _alert(
                    f"PRIMARY CONSENSUS CAUTION BLOCKED {setup.get('symbol')} {setup.get('strategy')}\n"
                    f"reason={primary_caution}"
                )
                _decision(
                    setup_symbol,
                    setup.get("strategy", "unknown"),
                    "blocked",
                    "primary_consensus_caution",
                    blocker=primary_caution,
                    blockers=consensus.get("blockers", []),
                    recommendation=consensus.get("recommendation"),
                    right=setup.get("right"),
                    orb_direction=setup.get("orb_direction"),
                    catalyst=setup.get("catalyst"),
                    setup_score=setup.get("score"),
                )
                continue
            adjusted_contracts = int(consensus.get("adjusted_contracts", setup.get("contracts", 0)) or 0)
            if 0 < adjusted_contracts < int(setup.get("contracts", 0) or 0):
                log.info(
                    f"SHADOW CONSENSUS SIZE DOWN {setup.get('symbol')} {setup.get('strategy')}: "
                    f"{setup.get('contracts')} -> {adjusted_contracts} "
                    f"recommendation={consensus.get('recommendation')}"
                )
                _alert(
                    f"SHADOW CONSENSUS SIZE DOWN {setup.get('symbol')} {setup.get('strategy')}\n"
                    f"contracts {setup.get('contracts')} -> {adjusted_contracts}"
                )
                setup["contracts"] = adjusted_contracts
            setup["shadow_consensus"] = {
                "recommendation": consensus.get("recommendation"),
                "options_playbook": consensus.get("options_playbook"),
                "blockers": consensus.get("blockers", []),
                "hard_blockers": consensus.get("hard_blockers", []),
                "alpha_advisory_only": consensus.get("alpha_advisory_only", False),
                "reasons": consensus.get("reasons", []),
            }
        estimated_notional = float(setup.get("entry_price_est", 0.0) or 0.0) * int(setup.get("contracts", 0) or 0) * 100
        confidence = setup.get("confidence", setup.get("score"))
        local_open_symbols = {t.get("symbol", "") for t in open_trades + trades if t.get("status") == "open"}
        decision = evaluate_execution(
            bot="flip",
            symbol=setup.get("symbol", ""),
            action="entry",
            paper=PAPER,
            live_enabled=LIVE_EXECUTION_ENABLED,
            confidence=float(confidence) if confidence is not None else None,
            estimated_notional=estimated_notional,
            max_notional=max_notional,
            contracts=int(setup.get("contracts", 0) or 0),
            max_contracts=MAX_CONTRACTS,
            block_file=DEFAULT_BLOCK_FILE,
            spread_cents=setup.get("spread_cents"),
            daily_loss_pct=daily_loss_pct,
            open_symbols=local_open_symbols | broker_symbols,
            config=ExecutionGuardConfig(max_spread_cents=MAX_ENTRY_SPREAD_CENTS),
        )
        if not decision.allowed:
            log.warning(
                f"EXECUTION BLOCKED {setup.get('symbol')} {setup.get('strategy')}: "
                f"{decision.reason} details={decision.details}"
            )
            _alert(
                f"ORDER BLOCKED {setup.get('symbol')} {setup.get('strategy')}\n"
                f"reason={decision.reason}"
            )
            _decision(
                setup_symbol,
                setup.get("strategy", "unknown"),
                "blocked",
                "execution_guard_block",
                guard_reason=decision.reason,
                guard_details=decision.details,
                right=setup.get("right"),
                catalyst=setup.get("catalyst"),
                confidence=confidence,
                confidence_basis=setup.get("confidence_basis"),
                orb_direction=setup.get("orb_direction"),
                orb_entry_pattern=setup.get("orb_entry_pattern"),
                orb_retest_status=setup.get("orb_retest_status"),
            )
            continue
        setup["telemetry_trade_id"] = setup.get("telemetry_trade_id") or str(uuid4())
        slippage_block = _entry_slippage_blocker(setup)
        if slippage_block:
            log.warning(
                f"EXECUTION BLOCKED {setup.get('symbol')} {setup.get('strategy')}: "
                f"{slippage_block['reason']} details={slippage_block}"
            )
            _alert(
                f"ORDER BLOCKED {setup.get('symbol')} {setup.get('strategy')}\n"
                f"reason={slippage_block['reason']}"
            )
            _decision(
                setup_symbol,
                setup.get("strategy", "unknown"),
                "blocked",
                slippage_block["reason"],
                slippage_guard=slippage_block,
            )
            continue
        evidence_block = _entry_evidence_blocker(setup)
        if evidence_block:
            log.error(
                f"EXECUTION BLOCKED {setup.get('symbol')} {setup.get('strategy')}: "
                f"{evidence_block['reason']} details={evidence_block}"
            )
            _decision(
                setup_symbol,
                setup.get("strategy", "unknown"),
                "blocked",
                evidence_block["reason"],
                entry_evidence=evidence_block,
            )
            continue
        _capture_point_in_time(
            "signal",
            setup,
            context={
                "strategy": setup.get("strategy"),
                "confidence": setup.get("confidence", setup.get("score")),
                "entry_price_est": setup.get("entry_price_est"),
                "spread_cents_at_signal": setup.get("spread_cents"),
                "entry_evidence_gate": setup.get("entry_evidence_gate"),
            },
        )
        entry_order_submitted_at = _utc_now_text()
        setup["entry_order_submitted_at"] = entry_order_submitted_at
        if is_spread:
            resp = _submit_spread(setup, max_notional=max_notional)
        else:
            resp = _submit(
                setup["option_symbol"],
                setup["contracts"],
                "buy",
                max_notional=max_notional,
                limit_price=setup.get("entry_limit_price"),
            )
        if not resp:
            _decision(setup_symbol, setup.get("strategy", "unknown"), "blocked", "order_submission_failed")
            continue

        time.sleep(6)
        entry_fill = _resolve_entry_fill(resp, setup)
        if not entry_fill.get("track"):
            log.warning(
                f"ENTRY NOT TRACKED {setup['symbol']} {setup['right']}: "
                f"order={resp.get('id')} status={entry_fill.get('order_status')} "
                f"filled_qty={entry_fill.get('filled_qty')} cancel_status={entry_fill.get('cancel_status')}"
            )
            _alert(
                f"ENTRY NOT TRACKED {setup['symbol']} {setup['right']}\n"
                f"Order {resp.get('id')} was not broker-filled; no open trade recorded."
            )
            _decision(
                setup_symbol,
                setup.get("strategy", "unknown"),
                "blocked",
                str(entry_fill.get("reason") or "entry_not_filled_confirmed"),
                order_id=resp.get("id"),
                order_status=entry_fill.get("order_status"),
                filled_qty=entry_fill.get("filled_qty"),
                cancel_status=entry_fill.get("cancel_status"),
            )
            continue

        filled_price = float(entry_fill["entry_price"])
        fill_price_source = str(entry_fill["entry_price_source"])
        tracked_contracts = int(entry_fill["contracts"])
        execution_evidence = _entry_execution_snapshot(setup, entry_fill, entry_order_submitted_at)

        trade = {
            "id":              setup["telemetry_trade_id"],
            "alpaca_order_id": resp.get("id"),
            "strategy":        setup["strategy"],
            "symbol":          setup["symbol"],
            "right":           setup["right"],
            "option_symbol":   setup["option_symbol"],
            "short_option_symbol": setup.get("short_option_symbol"),
            "strike":          setup["strike"],
            "short_strike":    setup.get("short_strike"),
            "expiry":          setup["expiry"],
            "contracts":       tracked_contracts,
            "requested_contracts": entry_fill.get("requested_contracts", setup.get("contracts")),
            "entry_price":     filled_price,
            "entry_price_source": fill_price_source,
            "entry_order_status": entry_fill.get("entry_order_status") or "unknown",
            "entry_filled_qty": entry_fill.get("entry_filled_qty", 0.0),
            "entry_fill_confirmed": bool(entry_fill.get("entry_fill_confirmed")),
            "entry_partial_fill": bool(entry_fill.get("entry_partial_fill")),
            "entry_remainder_status": entry_fill.get("entry_remainder_status"),
            "entry_execution_evidence": execution_evidence,
            "target_price":    round(filled_price * PROFIT_MULT, 3),
            "stop_price":      round(filled_price * STOP_MULT, 3),
            "max_loss":        setup.get("max_loss"),
            "max_gain":        setup.get("max_gain"),
            "hard_close_date": setup.get("hard_close_date"),
            "hard_close_time": setup.get("hard_close_time"),
            "entry_date":      str(date.today()),
            "entry_at":        _utc_now_text(),
            "status":          "open",
            "catalyst":        setup.get("catalyst", ""),
            "execution_lane":  setup.get("execution_lane", "primary"),
            "paper_only":      bool(setup.get("paper_only")),
            "noise_area_direction": setup.get("noise_area_direction"),
            "noise_area_upper_band": setup.get("noise_area_upper_band"),
            "noise_area_lower_band": setup.get("noise_area_lower_band"),
            "noise_area_vwap": setup.get("noise_area_vwap"),
            "noise_area_fraction": setup.get("noise_area_fraction"),
            "noise_area_structural_stop": setup.get("noise_area_structural_stop"),
            "noise_area_formula_version": setup.get("noise_area_formula_version"),
            "shadow_consensus": setup.get("shadow_consensus"),
            "entry_quality":   _entry_quality_snapshot(setup, filled_price, fill_price_source),
            **_path_telemetry_baseline(),
        }
        trades.append(trade)
        _save(trades)
        _capture_point_in_time(
            "fill",
            trade,
            context={
                "filled_price": filled_price,
                "fill_price_source": fill_price_source,
                "tracked_contracts": tracked_contracts,
                "requested_contracts": entry_fill.get("requested_contracts", setup.get("contracts")),
                "entry_price_est": setup.get("entry_price_est"),
                "strategy": setup.get("strategy"),
                "confidence": setup.get("confidence", setup.get("score")),
                "entry_execution_evidence": execution_evidence,
            },
        )
        resting_tp_result = _submit_resting_take_profit(trade)
        _save(trades)
        _decision(
            setup_symbol,
            setup.get("strategy", "unknown"),
            "submitted",
            "candidate_passed_all_filters",
            order_id=resp.get("id"),
            contracts=setup.get("contracts"),
            day_type_classification=setup.get("day_type_classification"),
            retest_quality_score=setup.get("retest_quality_score"),
            retest_grade=setup.get("retest_grade"),
            contract_rank=setup.get("contract_rank"),
        )

        msg = (f"ENTRY {setup['strategy'].upper()} {setup['symbol']} {setup['right']}\n"
               f"Option: {setup['option_symbol']}\n"
               f"Qty: {tracked_contracts}/{setup['contracts']}  Fill: ${filled_price:.3f}\n"
               f"Target: ${trade['target_price']:.3f} (+75%)  Stop: ${trade['stop_price']:.3f} (-30%)\n"
               f"Resting target: {resting_tp_result}\n"
               f"Close by: {setup.get('hard_close_date','')} {setup.get('hard_close_time','') or ''}\n"
               f"Catalyst: {setup.get('catalyst','')}")
        log.info(msg)
        _alert(msg)

    # Live candidate evaluation gets priority over research quote collection.
    if ACCELERATED_SHADOW_LEARNING:
        try:
            log_shadow_0dte_candidates(account)
        except Exception as exc:
            log.warning(f"Shadow lifecycle collection failed after entry scan: {exc}")


# ---------------------------------------------------------------------------
# Monitor run
# ---------------------------------------------------------------------------

def _monitor_pass() -> bool:
    """One protective scan over open trades. Returns True if any remain open."""
    trades  = _load()
    now_et  = _now_et()
    today   = now_et.date()
    changed = False

    for trade in trades:
        if trade.get("status") != "open":
            continue

        resting_result = _refresh_resting_take_profit(trade)
        if resting_result != "none":
            changed = True
            if resting_result == "filled":
                _capture_point_in_time(
                    "exit",
                    trade,
                    context={
                        "exit_reason": trade.get("exit_reason"),
                        "exit_price": trade.get("exit_price"),
                        "exit_price_source": trade.get("exit_price_source"),
                        "pnl": trade.get("pnl"),
                        "resting_take_profit": True,
                    },
                )
                msg = (
                    f"RESTING TARGET FILLED {trade['strategy'].upper()} {trade['symbol']}\n"
                    f"Option: {trade['option_symbol']}\n"
                    f"Fill: ${float(trade.get('exit_price') or 0):.3f}  "
                    f"P&L: ${float(trade.get('pnl') or 0):+.2f}"
                )
                log.info(msg)
                _alert(msg)
                continue

        pending_result = _refresh_pending_exit(trade)
        if pending_result != "none":
            changed = True
            if pending_result == "filled":
                _capture_point_in_time(
                    "exit_fill",
                    trade,
                    context={
                        "exit_reason": trade.get("exit_reason"),
                        "exit_price": trade.get("exit_price"),
                        "exit_price_source": trade.get("exit_price_source"),
                        "pnl": trade.get("pnl"),
                    },
                )
                msg = (
                    f"EXIT FILLED {trade['strategy'].upper()} {trade['symbol']}\n"
                    f"Option: {trade['option_symbol']}\n"
                    f"Entry: ${float(trade.get('entry_price') or 0):.3f}  "
                    f"Fill: ${float(trade.get('exit_price') or 0):.3f}  "
                    f"P&L: ${float(trade.get('pnl') or 0):+.2f}\n"
                    f"Reason: {trade.get('exit_reason', '')}"
                )
                log.info(msg)
                _alert(msg)
                continue
            if pending_result == "pending":
                log.info(
                    f"Exit pending {trade.get('exit_pending_order_id')} "
                    f"for {trade.get('option_symbol')}; no duplicate close submitted"
                )
                continue
            _alert(
                f"EXIT ORDER {trade.get('last_exit_order_failure', {}).get('status', 'failed').upper()} "
                f"{trade.get('option_symbol')} - retrying protection"
            )

        occ    = trade["option_symbol"]
        is_spread = bool(trade.get("short_option_symbol"))
        mid    = _spread_mid(occ, trade["short_option_symbol"]) if is_spread else _option_mid(occ)
        entry  = trade["entry_price"]
        target = trade["target_price"]
        stop   = trade["stop_price"]
        qty    = trade["contracts"]

        if mid <= 0:
            log.warning(f"No price for {occ}")
            continue

        pnl_pct = (mid - entry) / entry * 100
        if _update_pnl_extremes(trade, pnl_pct):
            changed = True
        best_pnl_pct = float(trade.get("best_pnl_pct", pnl_pct))
        _capture_point_in_time(
            "monitor",
            trade,
            context={"mid": mid, "pnl_pct": round(pnl_pct, 2)},
        )
        log.info(f"{occ}  mid=${mid:.3f}  P&L={pnl_pct:+.1f}%  target=${target:.3f}  stop=${stop:.3f}")

        reason = None
        consensus_exit = shadow_exit_advice(trade.get("symbol", ""), trade.get("right"))
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
                changed = True
                blockers = ", ".join(consensus_exit.get("blockers") or []) or "shadow regime review"
                log.warning(f"SHADOW EXIT REVIEW {trade.get('symbol')} {occ}: {blockers}")
                _alert(
                    f"SHADOW EXIT REVIEW {trade.get('symbol')} {trade.get('right')}\n"
                    f"Option: {occ}\n"
                    f"reason={blockers}\n"
                    "No shadow auto-close submitted."
                )
        if mid >= target:
            reason = f"PROFIT TARGET +{pnl_pct:.1f}%"
        elif mid <= stop:
            reason = f"STOP LOSS {pnl_pct:.1f}%"
        else:
            reason = _noise_area_structural_exit_reason(trade, now_et=now_et)
            if not reason:
                lock_floor = _profit_protect_lock_floor(best_pnl_pct)
                if (
                    best_pnl_pct >= PROFIT_PROTECT_ARM_PCT
                    and pnl_pct <= lock_floor
                ):
                    reason = (
                        f"PROFIT PROTECT {pnl_pct:+.1f}% "
                        f"(best +{best_pnl_pct:.1f}%, lock +{lock_floor:.1f}%)"
                    )
        if not reason:
            reason = _shadow_defensive_exit_reason(consensus_exit, pnl_pct)
        if not reason and trade.get("hard_close_time"):
            cutoff = datetime.strptime(str(trade["hard_close_time"]), "%H:%M").time()
            if now_et.time() >= cutoff:
                reason = f"TIME EXIT {trade['hard_close_time']}"
        if not reason and trade.get("hard_close_date"):
            hard = datetime.strptime(trade["hard_close_date"], "%Y-%m-%d").date()
            if today > hard or (today == hard and not trade.get("hard_close_time")):
                reason = f"DATE EXIT (before {trade.get('catalyst','')})"
        if not reason and trade.get("strategy") == "breakout":
            entry_d = datetime.strptime(trade["entry_date"], "%Y-%m-%d").date()
            if (today - entry_d).days >= 3:
                reason = "MAX HOLD 3 DAYS"

        if reason:
            if not is_spread and trade.get("resting_tp_order_id"):
                if reason.startswith("PROFIT TARGET"):
                    log.info(
                        f"Target reached for {occ}; resting order "
                        f"{trade.get('resting_tp_order_id')} remains responsible for the fill"
                    )
                    continue
                cancel_result = _cancel_resting_take_profit(trade)
                changed = True
                if cancel_result == "filled":
                    _capture_point_in_time(
                        "exit",
                        trade,
                        context={
                            "exit_reason": trade.get("exit_reason"),
                            "exit_price": trade.get("exit_price"),
                            "exit_price_source": trade.get("exit_price_source"),
                            "pnl": trade.get("pnl"),
                            "resting_take_profit_race": True,
                        },
                    )
                    msg = (
                        f"RESTING TARGET WON CANCEL RACE {trade['symbol']}\n"
                        f"Option: {occ}\n"
                        f"Fill: ${float(trade.get('exit_price') or 0):.3f}  "
                        f"P&L: ${float(trade.get('pnl') or 0):+.2f}\n"
                        "No second sell submitted."
                    )
                    log.info(msg)
                    _alert(msg)
                    continue
                if cancel_result == "pending":
                    msg = (
                        f"RESTING TARGET CANCEL UNCONFIRMED {trade['symbol']} {occ}\n"
                        f"Software exit held to prevent a double-sell. Reason: {reason}"
                    )
                    log.error(msg)
                    _alert(msg)
                    continue
            resp = _close_spread(trade) if is_spread else _submit(occ, qty, "sell")
            if resp:
                exit_state = _stage_exit_order(trade, resp, reason, mid)
                changed = True
                _capture_point_in_time(
                    "exit",
                    trade,
                    context={
                        "exit_reason": reason,
                        "exit_price": mid,
                        "pnl": trade.get("pnl"),
                    },
                )
                if exit_state == "filled":
                    _capture_point_in_time(
                        "exit_fill",
                        trade,
                        context={
                            "exit_reason": reason,
                            "exit_price": trade.get("exit_price"),
                            "exit_price_source": trade.get("exit_price_source"),
                            "pnl": trade.get("pnl"),
                        },
                    )
                    msg = (
                        f"EXIT FILLED {trade['strategy'].upper()} {trade['symbol']}\n"
                        f"Option: {occ}\n"
                        f"Entry: ${entry:.3f}  Fill: ${float(trade.get('exit_price') or 0):.3f}  "
                        f"P&L: ${float(trade.get('pnl') or 0):+.2f}\n"
                        f"Reason: {reason}"
                    )
                elif exit_state == "pending":
                    msg = (
                        f"EXIT SUBMITTED {trade['strategy'].upper()} {trade['symbol']}\n"
                        f"Option: {occ}\n"
                        f"Trigger quote: ${mid:.3f}  Order: {trade.get('exit_pending_order_id')}\n"
                        f"Reason: {reason}\n"
                        "Position remains monitored until broker fill confirmation."
                    )
                else:
                    msg = f"CLOSE RESPONSE INVALID {occ} - CLOSE MANUALLY NOW"
                log.info(msg)
                _alert(msg)
            else:
                _alert(f"CLOSE FAILED {occ} â€” CLOSE MANUALLY NOW")

    if changed:
        _save(trades)
    return any(t.get("status") == "open" for t in trades)


def run_monitor(protect_loop: bool = False) -> None:
    log.info("=== FLIP MONITOR (protect loop) ===" if protect_loop else "=== FLIP MONITOR ===")
    if not _market_open():
        log.info("Market is closed - skip flip monitor")
        return

    open_remaining = _monitor_pass()

    # Research collection must never delay or block protection of open trades.
    if ACCELERATED_SHADOW_LEARNING and not protect_loop:
        try:
            log_shadow_0dte_candidates(resolve_account_size(allow_research_fallback=True))
        except Exception as exc:
            log.warning(f"Shadow lifecycle collection failed after monitor: {exc}")

    if not protect_loop:
        return

    deadline = time.monotonic() + MONITOR_PROTECT_WINDOW_MINUTES * 60
    while open_remaining and time.monotonic() < deadline and _market_open():
        time.sleep(MONITOR_PROTECT_LOOP_SECONDS)
        open_remaining = _monitor_pass()
    if not open_remaining:
        log.info("Protect loop released: no open trades remain")


# ---------------------------------------------------------------------------
# Status / close-all
# ---------------------------------------------------------------------------

def print_status() -> None:
    trades = _load()
    open_t = [t for t in trades if t.get("status") == "open"]
    closed = [t for t in trades if t.get("status") == "closed"]
    total  = sum(t.get("pnl", 0) for t in closed)
    print(f"\n{'='*60}\n  FLIP BOT STATUS  ({'PAPER' if PAPER else 'LIVE'})\n{'='*60}")
    print(f"  Open: {len(open_t)}  Closed: {len(closed)}  Total P&L: ${total:+.2f}")
    if open_t:
        print("\n  OPEN TRADES:")
        for t in open_t:
            mid     = _option_mid(t["option_symbol"])
            pct     = (mid - t["entry_price"]) / t["entry_price"] * 100 if mid > 0 else 0
            print(f"    {t['option_symbol']}  entry=${t['entry_price']:.3f}  mid=${mid:.3f}  {pct:+.1f}%")
    if closed:
        print("\n  RECENT CLOSED (last 5):")
        for t in closed[-5:]:
            print(f"    {t['option_symbol']}  {t.get('exit_reason','?')}  P&L=${t.get('pnl',0):+.2f}")
    print()


def close_all() -> None:
    trades = _load()
    for t in [x for x in trades if x.get("status") == "open"]:
        pending_result = _refresh_pending_exit(t)
        if pending_result in {"pending", "filled"}:
            continue
        if not t.get("short_option_symbol") and t.get("resting_tp_order_id"):
            resting_result = _cancel_resting_take_profit(t)
            if resting_result == "filled":
                log.info(f"Resting target filled before close-all for {t['option_symbol']}")
                continue
            if resting_result == "pending":
                _alert(
                    f"CLOSE-ALL HELD {t['option_symbol']}: resting target cancel is unconfirmed; "
                    "manual review required to avoid a double-sell."
                )
                continue
        resp = _close_spread(t) if t.get("short_option_symbol") else _submit(
            t["option_symbol"], t["contracts"], "sell"
        )
        if resp:
            mid = _option_mid(t["option_symbol"])
            exit_state = _stage_exit_order(t, resp, "manual close-all", mid)
            if exit_state == "filled":
                log.info(f"Closed {t['option_symbol']}  P&L ${t['pnl']:+.2f}")
            else:
                log.info(f"Close submitted for {t['option_symbol']}; awaiting broker fill")
    _save(trades)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    ap = argparse.ArgumentParser(description="Flip Bot â€” automated directional options for small accounts")
    ap.add_argument("--entry",     action="store_true")
    ap.add_argument("--intraday-entry", action="store_true",
                    help="Scan only SPY ORB first, then the paper-only Noise Area fallback.")
    ap.add_argument("--monitor",   action="store_true")
    ap.add_argument("--protect-loop", action="store_true",
                    help="With --monitor: keep scanning open trades in-process every "
                         f"{MONITOR_PROTECT_LOOP_SECONDS}s for up to {MONITOR_PROTECT_WINDOW_MINUTES:g} "
                         "minutes so exits fire near their designed levels.")
    ap.add_argument("--status",    action="store_true")
    ap.add_argument("--close-all", action="store_true")
    ap.add_argument("--account",   type=float, default=None,
                    help="Account size to simulate for this run. Overrides FLIP_ACCOUNT_SIZE_OVERRIDE / ACCOUNT_SIZE_OVERRIDE.")
    args = ap.parse_args()

    if not KEY or not SECRET:
        log.error("Alpaca keys missing in agent/.env")
        sys.exit(1)

    try:
        if args.status:
            print_status()
        elif args.close_all:
            close_all()
        elif args.entry:
            run_entry(resolve_account_size(args.account))
        elif args.intraday_entry:
            run_entry(resolve_account_size(args.account), intraday_only=True)
        elif args.monitor:
            run_monitor(protect_loop=args.protect_loop)
        else:
            ap.print_help()
    except Exception as exc:
        log.exception(f"FATAL unhandled exception: {exc}")
        sys.exit(1)


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""
Options Bot - Iron Condor + Put Spread + Wheel Automation
Symbols: IWM (ic+ps), SPY (ps), QQQ (ps), NVDA (ps+wheel), PLTR (ps), TSLA (ic+ps), AAPL (ps+wheel)
Broker: Alpaca Markets (paper by default, flip ALPACA_PAPER=false for live)

Strategy 1 - Iron Condor:      16-delta, 30-45 DTE, close at 50% profit
Strategy 2 - Put Spread:       25-delta,  7-14 DTE, close at 50% profit
Strategy 3 - Wheel (NVDA):     sell CSP → if assigned sell covered call, repeat

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

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import numpy as np
import yfinance as yf
from dotenv import load_dotenv

from alpaca.data.historical.option import OptionHistoricalDataClient
from alpaca.data.requests import OptionChainRequest
from alpaca.trading.client import TradingClient
from alpaca.trading.requests import GetOrdersRequest
from alpaca.trading.enums import QueryOrderStatus

try:
    from risk_kill_switch import DEFAULT_BLOCK_FILE, manual_reset_required
    from execution_guard import evaluate_execution
except ModuleNotFoundError:
    from strategies.risk_kill_switch import DEFAULT_BLOCK_FILE, manual_reset_required
    from strategies.execution_guard import evaluate_execution

load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), "..", "agent", ".env"))

# ── Logging ──────────────────────────────────────────────────────────────────
LOG_DIR  = os.path.expanduser(r"~\.vibe-trading\logs")
LOG_FILE = os.path.join(LOG_DIR, "options-bot.log")
DECISION_LOG_FILE = os.path.join(LOG_DIR, "options-decisions.jsonl")
os.makedirs(LOG_DIR, exist_ok=True)

_fmt = logging.Formatter("%(asctime)s  %(levelname)-8s  %(message)s", datefmt="%Y-%m-%d %H:%M:%S")
_fh  = logging.FileHandler(LOG_FILE, encoding="utf-8")
_fh.setFormatter(_fmt)
_sh  = logging.StreamHandler()
_sh.setFormatter(_fmt)

logging.basicConfig(level=logging.INFO, handlers=[_fh, _sh])
log = logging.getLogger("options-bot")

# ── Safety Caps ───────────────────────────────────────────────────────────────
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

# ── Multi-Symbol Config ───────────────────────────────────────────────────────
# Maps symbol → list of strategies to run
# ETFs (IWM/SPY/QQQ): lower IV, good for IC + spreads
# Individual stocks (NVDA/PLTR): high IV, put spreads + wheel
SYMBOLS: dict[str, list[str]] = {
    "IWM":  ["ic", "ps"],        # ETF, lower IV, both strategies
    "SPY":  ["ps"],              # ETF, deep liquidity, put spread
    "QQQ":  ["ps"],              # ETF, tech exposure, put spread
    "TSLA": ["ic", "ps"],        # highest retail volume, very high IV
    "NVDA": ["ps", "wheel"],     # AI stock, high IV, wheel income
    "AAPL": ["ps", "wheel"],     # most liquid options market, stable for wheel
    "PLTR": ["ps"],              # high IV, put spread
}

# Per-symbol put spread width override (higher-priced stocks need wider spreads)
PS_WIDTH_OVERRIDE: dict[str, float] = {
    "SPY":  5.0,
    "QQQ":  5.0,
    "TSLA": 5.0,
    "AAPL": 5.0,
}

# ── Strategy Parameters ───────────────────────────────────────────────────────
IC_DTE_MIN          = 30
IC_DTE_MAX          = 45
IC_DELTA_TARGET     = 0.16    # short leg delta (~84% probability of profit)
IC_WING_WIDTH       = 2       # $2 wings on each side
IC_PROFIT_CLOSE_PCT = 0.50    # close at 50% of max credit (82% win rate per tastytrade research)

PS_DTE_MIN          = 7
PS_DTE_MAX          = 14
PS_DELTA_TARGET     = 0.25    # short put delta
PS_WIDTH            = 3       # $3 default spread width (override per symbol above)
PS_PROFIT_CLOSE_PCT = 0.50

# Wheel strategy (cash-secured put → covered call loop)
WHEEL_DTE_MIN       = 21
WHEEL_DTE_MAX       = 35
WHEEL_DELTA         = 0.30    # slightly more aggressive delta for more premium
WHEEL_CC_DELTA      = 0.30    # covered call delta after assignment
WHEEL_PROFIT_PCT    = 0.50

STOP_LOSS_PCT       = -1.0    # close if loss reaches 100% of credit received
IC_DTE_MANAGE_DAYS  = int(os.getenv("IC_DTE_MANAGE_DAYS", "21"))
PS_DTE_MANAGE_DAYS  = int(os.getenv("PS_DTE_MANAGE_DAYS", "2"))

PAPER = os.getenv("ALPACA_PAPER", "true").lower() == "true"
BASE  = "https://paper-api.alpaca.markets" if PAPER else "https://api.alpaca.markets"
LIVE_EXECUTION_ENABLED = os.getenv("OPTIONS_LIVE_EXECUTION_ENABLED", "false").lower() == "true"
AUTO_CLOSE_GROUPS = os.getenv("AUTO_CLOSE_GROUPS", "true" if PAPER else "false").lower() == "true"
TRADE_STATE_FILE = Path(os.path.expanduser(r"~\.vibe-trading\options-trades.json"))
ORDER_RETRY_ATTEMPTS = int(os.getenv("ORDER_RETRY_ATTEMPTS", "3"))
ORDER_RETRY_BASE_SECONDS = float(os.getenv("ORDER_RETRY_BASE_SECONDS", "1.5"))
RETRY_STATUS_CODES = {429, 500, 502, 503, 504}


# ── Clients ───────────────────────────────────────────────────────────────────
def _build_clients() -> tuple[TradingClient, OptionHistoricalDataClient]:
    key    = os.getenv("ALPACA_API_KEY", "")
    secret = os.getenv("ALPACA_SECRET_KEY", "")
    if not key or not secret:
        log.error("ALPACA_API_KEY / ALPACA_SECRET_KEY missing in .env — aborting")
        sys.exit(1)
    if not PAPER and os.getenv("CONFIRM_LIVE_TRADING", "") != "I_UNDERSTAND_THE_RISK":
        log.error("Live trading requested but CONFIRM_LIVE_TRADING is not set to I_UNDERSTAND_THE_RISK")
        sys.exit(1)
    trade = TradingClient(key, secret, paper=PAPER)
    data  = OptionHistoricalDataClient(key, secret)
    return trade, data


# ── IV Rank (30-day HV as proxy over 252-day rolling window) ─────────────────
def iv_rank(symbol: str) -> float:
    ticker = yf.Ticker(symbol)
    hist   = ticker.history(period="1y")
    if len(hist) < 30:
        log.warning(f"Not enough price history for {symbol} — defaulting IV Rank to 50")
        return 50.0
    hist["log_ret"] = np.log(hist["Close"] / hist["Close"].shift(1))
    hist["hv30"]    = hist["log_ret"].rolling(21).std() * math.sqrt(252) * 100
    hist            = hist.dropna()
    current         = hist["hv30"].iloc[-1]
    lo, hi          = hist["hv30"].min(), hist["hv30"].max()
    rank            = (current - lo) / (hi - lo) * 100 if hi > lo else 50.0
    log.info(f"IV Rank {symbol}: {rank:.1f}  (HV30={current:.1f}, 52wk range {lo:.1f}-{hi:.1f})")
    return rank


# ── Earnings check ────────────────────────────────────────────────────────────
def _has_earnings_soon(symbol: str, days: int = EARNINGS_SKIP_DAYS) -> bool:
    """Return True if earnings are within `days` calendar days — skip entry if so."""
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
                    log.warning(f"{symbol}: earnings on {earn} ({(earn - today).days}d away) — skipping")
                    return True
            except Exception:
                continue
    except Exception as exc:
        log.debug(f"Earnings check failed for {symbol}: {exc}")
    return False


# ── Option leg data class ─────────────────────────────────────────────────────
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


# ── Chain fetch ───────────────────────────────────────────────────────────────
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


# ── Discord alerts ───────────────────────────────────────────────────────────
def _alert(message: str) -> None:
    webhook = os.getenv("DISCORD_WEBHOOK_URL", "")
    if not webhook:
        return
    try:
        import requests as r
        r.post(webhook, json={
            "content": f"@everyone 🤖 **Options Bot**\n{message}",
            "allowed_mentions": {"parse": ["everyone"]},
        }, timeout=5)
    except Exception as exc:
        log.warning(f"Discord alert failed: {exc}")


# ── Put/Call Ratio sentiment filter ──────────────────────────────────────────
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
            log.info(f"{symbol}: PCR {pcr:.2f} > {PCR_MAX} — heavy put buying, bearish flow — skipping")
            return False
        return True
    except Exception as exc:
        log.warning(f"PCR check failed for {symbol}: {exc} — proceeding")
        return True


# ── VIX macro filter ─────────────────────────────────────────────────────────
VIX_MIN = 15.0   # below = not enough premium to sell
VIX_MAX = 40.0   # above = market panic, spreads can blow through

# Module-level journal state — populated once per run_entries() call, read by IC/PS trade_meta.
_JOURNAL_VIX: float | None = None
_JOURNAL_VIX_TERM_RATIO: float | None = None
_JOURNAL_IV_RANK: dict[str, float] = {}


def _vix_in_range() -> bool:
    global _JOURNAL_VIX, _JOURNAL_VIX_TERM_RATIO
    try:
        hist    = yf.Ticker("^VIX").history(period="2d")
        vix_val = float(hist["Close"].iloc[-1])
        _JOURNAL_VIX = vix_val
        log.info(f"VIX: {vix_val:.1f}  (range {VIX_MIN}-{VIX_MAX})")
        if vix_val < VIX_MIN:
            log.info(f"VIX {vix_val:.1f} < {VIX_MIN} — insufficient premium environment, skipping entries")
            return False
        if vix_val > VIX_MAX:
            log.info(f"VIX {vix_val:.1f} > {VIX_MAX} — market panic mode, too risky to sell premium")
            return False

        # VIX term structure: VIX/VXV > 1.0 = backwardation = don't sell premium
        try:
            vxv_hist = yf.Ticker("^VXV").history(period="2d")
            vxv_val  = float(vxv_hist["Close"].iloc[-1])
            ratio    = round(vix_val / vxv_val, 3) if vxv_val > 0 else None
            _JOURNAL_VIX_TERM_RATIO = ratio
            if ratio is not None:
                regime = "backwardation — skipping" if ratio > 1.0 else "contango — premium OK"
                log.info(f"VIX/VXV term ratio: {ratio:.3f}  ({regime})")
                if ratio > 1.0:
                    return False
        except Exception as exc:
            log.warning(f"VIX/VXV term ratio check failed: {exc} — skipping term filter")

        return True
    except Exception as exc:
        log.warning(f"VIX check failed: {exc} — proceeding without filter")
        return True


# ── 20-day SMA trend filter ───────────────────────────────────────────────────
def _above_20sma(symbol: str) -> bool:
    """Return True if symbol is above its 20-day SMA (bullish bias = safer for put spreads/CSPs)."""
    try:
        hist  = yf.Ticker(symbol).history(period="35d")
        if len(hist) < 20:
            return True
        sma20 = hist["Close"].rolling(20).mean().iloc[-1]
        price = hist["Close"].iloc[-1]
        above = price > sma20
        log.info(f"{symbol}: price={price:.2f}  20SMA={sma20:.2f}  {'ABOVE ✓' if above else 'BELOW — skip put spread'}")
        return above
    except Exception as exc:
        log.warning(f"SMA check failed for {symbol}: {exc} — proceeding")
        return True


# ── Market hours check ───────────────────────────────────────────────────────
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
            log.warning(f"Clock check failed: {exc} — FAIL_OPEN_MARKET_CHECK=true, assuming market open")
            return True
        log.warning(f"Clock check failed: {exc} — failing closed, no new entries")
        return False


# ── Account helpers ───────────────────────────────────────────────────────────
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
    since = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
    orders = trade_client.get_orders(
        GetOrdersRequest(status=QueryOrderStatus.ALL, after=since, limit=50)
    )
    return sum(1 for o in orders if getattr(o, "order_class", "") == "mleg"
               and o.status in ("filled", "partially_filled"))


def _decision(symbol: str, strategy: str, action: str, reason: str, **details) -> None:
    event = {
        "ts": datetime.utcnow().isoformat(timespec="seconds") + "Z",
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
    TRADE_STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    with TRADE_STATE_FILE.open("w", encoding="utf-8") as fh:
        json.dump(state, fh, indent=2, sort_keys=True)


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
        if trade.get("status") in ("open", "closing")
        for symbol in trade.get("legs", [])
    }
    untracked_open = open_symbols - tracked_symbols
    if not untracked_open:
        return False

    recovered = False
    for order in _recent_filled_mleg_orders():
        legs = order.get("legs") or []
        leg_symbols = [leg.get("symbol", "") for leg in legs if leg.get("symbol")]
        if not leg_symbols or not set(leg_symbols).issubset(untracked_open):
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


def _record_trade_group(meta: dict, order_id: str) -> None:
    if not meta:
        return
    state = _load_trade_state()
    trade = {
        "id": str(uuid4()),
        "order_id": order_id,
        "status": "open",
        "opened_at": datetime.utcnow().isoformat(timespec="seconds") + "Z",
        **meta,
    }
    state["trades"].append(trade)
    _save_trade_state(state)
    log.info(f"Recorded trade group {trade['id']} for {trade.get('label', 'trade')}")


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
        if trade.get("status") in ("open", "closing") and trade.get("underlying") == underlying
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
        daily["triggered_at"] = datetime.utcnow().isoformat(timespec="seconds") + "Z"
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
        "detected_at": datetime.utcnow().isoformat(timespec="seconds") + "Z",
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
        "detected_at": datetime.utcnow().isoformat(timespec="seconds") + "Z",
    }
    _save_trade_state(state)


def _close_trade_group(trade_client: TradingClient, trade: dict, reason: str) -> bool:
    legs = trade.get("legs", [])
    if not legs:
        log.error(f"{trade.get('label', 'trade')}: no legs in state; cannot close")
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


# ── Multi-leg order submission via raw REST ───────────────────────────────────
def _trade_stop_loss_pct(trade: dict) -> float:
    raw_stop = float(trade.get("stop_loss_pct", STOP_LOSS_PCT))
    if str(trade.get("strategy", "")).startswith("recovered") and raw_stop < STOP_LOSS_PCT:
        return STOP_LOSS_PCT
    return raw_stop


def _mark_all_open_groups_closed_when_flat() -> bool:
    state = _load_trade_state()
    changed = False
    for trade in state.get("trades", []):
        if trade.get("status") in ("open", "closing"):
            trade["status"] = "closed"
            trade["closed_at"] = datetime.utcnow().isoformat(timespec="seconds") + "Z"
            changed = True
    if changed:
        _save_trade_state(state)
    return changed


def _post_order_with_retry(body: dict, label: str) -> Optional[dict]:
    import requests as r

    if manual_reset_required():
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
    _alert(f"📥 **{label}** submitted\ncredit=${limit_price:.2f}  qty={qty}  order={oid}")
    _record_trade_group(trade_meta or {}, oid)
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
        _alert(f"📥 **{label}** submitted\ncredit=${limit_price:.2f}  qty={qty}  order={oid}")
        _record_trade_group(trade_meta or {}, oid)
        return True
    except Exception as exc:
        log.error(f"{label}: submission failed — {exc}")
        return False


# ── Profit-close monitor ──────────────────────────────────────────────────────
def monitor_and_close(trade_client: TradingClient) -> None:
    positions = [
        p for p in trade_client.get_all_positions()
        if getattr(p, "asset_class", "") == "us_option"
    ]
    if not positions:
        if _mark_all_open_groups_closed_when_flat():
            log.info("No open option positions remain; marked tracked groups closed")
        log.info("No open option positions to monitor")
        return
    log.info(f"Monitoring {len(positions)} option position(s)...")
    position_by_symbol = {p.symbol: p for p in positions}
    state = _load_trade_state()
    state_changed = _recover_untracked_mleg_groups(trade_client, state)
    monitored_symbols: set[str] = set()

    for trade in state.get("trades", []):
        if trade.get("status") not in ("open", "closing"):
            continue
        legs = trade.get("legs", [])
        monitored_symbols.update(legs)
        found = [position_by_symbol[s] for s in legs if s in position_by_symbol]
        missing = [s for s in legs if s not in position_by_symbol]

        if not found:
            log.info(f"{trade.get('label', 'trade')}: no legs remain open; marking closed")
            trade["status"] = "closed"
            trade["closed_at"] = datetime.utcnow().isoformat(timespec="seconds") + "Z"
            state_changed = True
            continue
        if missing:
            log.warning(
                f"{trade.get('label', 'trade')}: missing tracked legs {missing}; "
                "manual review required before auto-close"
            )
            continue

        try:
            credit_received = float(trade.get("net_credit", 0)) * 100 * int(trade.get("qty", 1))
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

            log.info(
                f"  {trade.get('label', 'trade'):<28} legs={len(found)} "
                f"credit=${credit_received:.2f} P&L={pnl:+.2f} ({pnl_pct:+.1%} of {basis_src})"
            )
            reason = ""
            if pnl_pct >= float(trade.get("profit_close_pct", PS_PROFIT_CLOSE_PCT)):
                reason = f"profit target hit: {pnl_pct:+.1%} of {basis_src}"
            elif pnl_pct <= _trade_stop_loss_pct(trade):
                reason = f"stop loss hit: {pnl_pct:+.1%} of {basis_src}"
            else:
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
                    log.info(f"  -> {reason}; closing all tracked legs for {trade.get('label', 'trade')}")
                    if _close_trade_group(trade_client, trade, reason):
                        trade["status"] = "closing"
                        trade["closing_reason"] = reason
                        trade["closing_started_at"] = datetime.utcnow().isoformat(timespec="seconds") + "Z"
                        state_changed = True
                else:
                    log.warning(f"  -> {reason}; AUTO_CLOSE_GROUPS=false, alerting only")
                    _alert(f"EXIT SIGNAL: **{trade.get('label', 'trade')}**\n{reason}\nAUTO_CLOSE_GROUPS=false")
        except Exception as exc:
            log.error(f"  Error monitoring {trade.get('label', 'trade')}: {exc}")

    legacy = [p for p in positions if p.symbol not in monitored_symbols]
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
    return
    for pos in positions:
        try:
            cost_basis = abs(float(pos.avg_entry_price)) * abs(float(pos.qty)) * 100
            pnl        = float(pos.unrealized_pl)
            pnl_pct    = pnl / cost_basis if cost_basis else 0
            log.info(f"  {pos.symbol:<35} qty={pos.qty:>4}  "
                     f"entry={float(pos.avg_entry_price):.2f}  "
                     f"P&L={pnl:+.2f} ({pnl_pct:+.1%})")
            if pnl_pct >= PS_PROFIT_CLOSE_PCT:
                log.info(f"  → PROFIT TARGET HIT — closing {pos.symbol}")
                trade_client.close_position(pos.symbol)
                _alert(f"✅ **PROFIT TARGET** hit on `{pos.symbol}`\nP&L={pnl:+.2f} ({pnl_pct:+.1%})")
            elif pnl_pct <= STOP_LOSS_PCT:
                log.info(f"  → STOP LOSS HIT — closing {pos.symbol}")
                trade_client.close_position(pos.symbol)
                _alert(f"🛑 **STOP LOSS** hit on `{pos.symbol}`\nP&L={pnl:+.2f} ({pnl_pct:+.1%})")
        except Exception as exc:
            log.error(f"  Error monitoring {pos.symbol}: {exc}")


# ── Strategy: Iron Condor ─────────────────────────────────────────────────────
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
            {"symbol": short_put.symbol,  "side": "sell", "ratio_qty": "1"},
            {"symbol": long_put.symbol,   "side": "buy",  "ratio_qty": "1"},
            {"symbol": short_call.symbol, "side": "sell", "ratio_qty": "1"},
            {"symbol": long_call.symbol,  "side": "buy",  "ratio_qty": "1"},
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


# ── Strategy: Put Spread ──────────────────────────────────────────────────────
def run_put_spread(
    trade_client: TradingClient,
    data_client: OptionHistoricalDataClient,
    symbol: str,
    equity: float,
) -> bool:
    log.info(f"--- Put Spread scan [{symbol}] ---")
    # Only sell puts when stock is in uptrend — reduces chance put goes ITM
    trend_ok = _above_20sma(symbol)
    if not trend_ok:
        log.info(f"PS [{symbol}]: below 20 SMA — skipping put spread")
        return False
    puts = _fetch_chain(data_client, symbol, PS_DTE_MIN, PS_DTE_MAX, "put")
    if not puts:
        log.warning(f"PS [{symbol}]: no chain data")
        return False

    short_put = _closest_delta(puts, PS_DELTA_TARGET)
    if not short_put:
        log.warning(f"PS [{symbol}]: could not find 25-delta put")
        return False

    width    = PS_WIDTH_OVERRIDE.get(symbol, PS_WIDTH)
    same_exp = [l for l in puts if l.expiry == short_put.expiry]
    long_put  = _find_wing(same_exp, short_put.strike, width, "P")
    if not long_put:
        log.warning(f"PS [{symbol}]: could not find long put wing")
        return False
    if not _legs_liquid(f"PS [{symbol}]", [short_put, long_put]):
        return False

    net_credit = short_put.mid - long_put.mid
    max_risk   = (width - net_credit) * 100
    if max_risk <= 0 or net_credit <= 0:
        log.warning(f"PS [{symbol}]: bad credit/risk ({net_credit:.2f} / {max_risk:.2f})")
        return False

    if not _credit_quality_ok(f"PS [{symbol}]", net_credit, max_risk):
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
        return False
    log.info(
        f"PS [{symbol}]: expiry={short_put.expiry}  DTE={_dte(short_put.expiry)}  "
        f"strikes={short_put.strike:.0f}/{long_put.strike:.0f}  "
        f"credit={net_credit:.2f}  risk={max_risk:.2f}/contract  qty={qty}"
    )

    return _place_mleg(
        legs_payload=[
            {"symbol": short_put.symbol, "side": "sell", "ratio_qty": "1"},
            {"symbol": long_put.symbol,  "side": "buy",  "ratio_qty": "1"},
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


# ── Single-leg order (for CSP and covered call) ───────────────────────────────
def _place_single_leg(
    occ_symbol: str,
    side: str,
    limit_price: float,
    qty: int,
    label: str,
    trade_meta: Optional[dict] = None,
) -> bool:
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
    _alert(f"📥 **{label}** submitted\ncredit=${limit_price:.2f}  qty={qty}  order={oid}")
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
        _alert(f"📥 **{label}** submitted\ncredit=${limit_price:.2f}  qty={qty}  order={oid}")
        return True
    except Exception as exc:
        log.error(f"{label}: submission failed — {exc}")
        return False


# ── Strategy: Wheel — Cash-Secured Put leg ───────────────────────────────────
def run_cash_secured_put(
    trade_client: TradingClient,
    data_client: OptionHistoricalDataClient,
    symbol: str,
    equity: float,
) -> bool:
    log.info(f"--- Wheel CSP scan [{symbol}] ---")
    trend_ok = _above_20sma(symbol)
    if not trend_ok:
        log.info(f"Wheel CSP [{symbol}]: below 20 SMA — skipping cash-secured put")
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
        log.warning(f"Wheel CSP [{symbol}]: strike ${short_put.strike} requires ${cash_required:,.0f} — too large for account")
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


# ── Strategy: Wheel — Covered Call leg ───────────────────────────────────────
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


# ── Strategy: Wheel — Orchestrator ───────────────────────────────────────────
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
        log.error(f"Wheel [{symbol}]: could not fetch positions — {exc}")
        return False

    shares = int(float(stock_pos.qty)) if stock_pos else 0

    if shares >= 100:
        _record_wheel_assignment(symbol, shares)
        log.info(f"Wheel [{symbol}]: holding {shares} shares → selling covered call")
        return run_covered_call(trade_client, data_client, symbol, equity, shares)
    else:
        _record_wheel_cash_secured_phase(symbol)
        log.info(f"Wheel [{symbol}]: no shares held → selling cash-secured put")
        return run_cash_secured_put(trade_client, data_client, symbol, equity)


# ── Main ──────────────────────────────────────────────────────────────────────
def main(strategy: str = "both", symbols: Optional[list[str]] = None) -> None:
    log.info(f"Options Bot  mode={'PAPER' if PAPER else '*** LIVE ***'}  strategy={strategy}")
    trade_client, data_client = _build_clients()

    # Always monitor open positions first (runs even when market closed)
    monitor_and_close(trade_client)

    # No new entries outside market hours
    if not _market_is_open():
        log.info("Market closed — skipping new entries")
        return

    # VIX macro filter — one check covers all symbols
    if not _vix_in_range():
        return

    # Safety gates (shared across all symbols)
    equity = _equity(trade_client)
    log.info(f"Equity: ${equity:,.2f}")

    if not _daily_loss_guard(trade_client, equity):
        return

    if _open_option_count(trade_client) >= MAX_OPEN_TRADES:
        log.info(f"Max open trades ({MAX_OPEN_TRADES}) reached — no new entries")
        return

    if _trades_today(trade_client) >= MAX_TRADES_PER_DAY:
        log.info(f"Max trades/day ({MAX_TRADES_PER_DAY}) reached — done for today")
        return

    # Determine which symbols to run
    target_symbols = symbols if symbols else list(SYMBOLS.keys())

    for sym in target_symbols:
        sym_strategies = SYMBOLS.get(sym, [])
        if not sym_strategies:
            log.warning(f"{sym} not in SYMBOLS config — skipping")
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

        # IV Rank gate per symbol — also stored for trade journal
        rank = iv_rank(sym)
        _JOURNAL_IV_RANK[sym] = rank
        if rank < IV_RANK_MIN:
            log.info(f"{sym}: IV Rank {rank:.1f} < {IV_RANK_MIN} — skipping (low vol, bad for premium selling)")
            continue

        # Earnings gate — skip individual stocks near earnings
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
            log.info(f"Max trades/day ({MAX_TRADES_PER_DAY}) reached — stopping")
            break

    log.info("Run complete.")


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser(description="Options Bot — Iron Condor + Put Spread + Wheel (IWM, SPY, QQQ, NVDA, PLTR)")
    ap.add_argument(
        "--strategy", choices=["both", "ic", "ps", "wheel"], default="both",
        help="ic=iron condor  ps=put spread  wheel=wheel only  both=all (default)",
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
        tc, _ = _build_clients()
        monitor_and_close(tc)
    else:
        sym_list = [args.symbol.upper()] if args.symbol else None
        main(strategy=args.strategy, symbols=sym_list)

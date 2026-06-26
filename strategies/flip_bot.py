#!/usr/bin/env python3
"""
Flip Bot — automated small-account directional options trading.

Two modes:
  --entry    Find catalyst setups and submit buy orders (run at 9:15am ET)
  --monitor  Check open trades, close at +75% profit or -50% stop (run every 15min)

Three strategies:
  0DTE   — buy ATM SPY call/put on FOMC/CPI/gap days, exit by 1:45pm
  Lotto  — buy OTM call 2-4 days before earnings, exit day before print
  Break  — buy OTM weekly call on momentum breakout + volume spike

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
import os
import sys
import time
from datetime import date, datetime, time as dtime, timedelta
from pathlib import Path
from uuid import uuid4

import requests as req
from dotenv import load_dotenv

try:
    from risk_kill_switch import DEFAULT_BLOCK_FILE, manual_reset_required
except ModuleNotFoundError:
    from strategies.risk_kill_switch import DEFAULT_BLOCK_FILE, manual_reset_required

load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), "..", "agent", ".env"))

try:
    import yfinance as yf
except ImportError:
    print("ERROR: pip install yfinance")
    sys.exit(1)

# ── Logging ───────────────────────────────────────────────────────────────────
LOG_DIR = Path(os.path.expanduser(r"~\.vibe-trading\logs"))
LOG_DIR.mkdir(parents=True, exist_ok=True)
_fmt = logging.Formatter("%(asctime)s  %(levelname)-8s  %(message)s", datefmt="%Y-%m-%d %H:%M:%S")
_fh  = logging.FileHandler(LOG_DIR / "flip-bot.log", encoding="utf-8")
_fh.setFormatter(_fmt)
_sh  = logging.StreamHandler()
_sh.setFormatter(_fmt)
logging.basicConfig(level=logging.INFO, handlers=[_fh, _sh])
log = logging.getLogger("flip-bot")

# ── Alpaca ────────────────────────────────────────────────────────────────────
KEY    = os.getenv("ALPACA_API_KEY", "")
SECRET = os.getenv("ALPACA_SECRET_KEY", "")
PAPER  = os.getenv("ALPACA_PAPER", "true").lower() == "true"
BASE   = "https://paper-api.alpaca.markets" if PAPER else "https://api.alpaca.markets"
HDR    = {"APCA-API-KEY-ID": KEY, "APCA-API-SECRET-KEY": SECRET, "Content-Type": "application/json"}
DISCORD_WEBHOOK = os.getenv("DISCORD_WEBHOOK_URL", "")

# ── State ─────────────────────────────────────────────────────────────────────
STATE_FILE = Path(os.path.expanduser(r"~\.vibe-trading\flip-trades.json"))

# ── Config ────────────────────────────────────────────────────────────────────
ACCOUNT_OVERRIDE  = float(os.getenv("FLIP_ACCOUNT_SIZE_OVERRIDE") or os.getenv("ACCOUNT_SIZE_OVERRIDE", "0") or 0)
MAX_RISK_PCT      = 0.02   # 2% account risk per trade (was 0.25 — caused 69-contract blowup)
MAX_CONTRACTS     = 5      # hard ceiling regardless of account size or option price
PROFIT_MULT       = 1.75   # entry * 1.75 = target (+75%)
STOP_MULT         = 0.50   # entry * 0.50 = stop   (-50%)
GAP_THRESHOLD     = 0.0075
VOLUME_SPIKE      = 2.5
MAX_OPEN_FLIPS    = 2
BEAR_TREND_MIN_CONFIDENCE = 8
BEAR_TREND_MAX_VWAP_EXT   = 0.015
BEAR_TREND_MIN_BARS       = 55

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


# ---------------------------------------------------------------------------
# Alpaca helpers
# ---------------------------------------------------------------------------

def _get(path: str, params: dict = {}) -> dict | list:
    r = req.get(f"{BASE}{path}", headers=HDR, params=params, timeout=10)
    r.raise_for_status()
    return r.json()


def _post(path: str, body: dict) -> dict:
    r = req.post(f"{BASE}{path}", headers=HDR, json=body, timeout=10)
    r.raise_for_status()
    return r.json()


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
        return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except Exception:
        return []


def _save(trades: list[dict]) -> None:
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps(trades, indent=2), encoding="utf-8")


# ---------------------------------------------------------------------------
# Account helpers
# ---------------------------------------------------------------------------

def _fetch_alpaca_equity() -> float:
    """Fetch live equity from Alpaca paper account. Returns 0.0 on failure."""
    try:
        r = req.get(f"{BASE}/v2/account", headers=HDR, timeout=10)
        if r.status_code == 200:
            eq = float(r.json().get("equity", 0) or 0)
            log.info(f"Alpaca equity fetched: ${eq:,.2f}")
            return eq
    except Exception as exc:
        log.warning(f"Could not fetch Alpaca equity: {exc}")
    return 0.0


def resolve_account_size(cli_override: float | None = None) -> float:
    """Priority: CLI arg > FLIP_ACCOUNT_SIZE_OVERRIDE env var > live Alpaca equity > $5000 fallback."""
    if cli_override is not None and cli_override > 0:
        return cli_override
    if ACCOUNT_OVERRIDE > 0:
        log.info(f"Using ACCOUNT_OVERRIDE: ${ACCOUNT_OVERRIDE:,.2f}")
        return ACCOUNT_OVERRIDE
    live = _fetch_alpaca_equity()
    if live > 0:
        return live
    log.warning("Could not resolve account size — falling back to $5,000")
    return 5_000.0


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


def _intraday_bars(sym: str):
    try:
        return yf.Ticker(sym).history(period="1d", interval="1m", auto_adjust=True)
    except Exception:
        return None


def _vwap_50ema_signal(hist, sym: str = "?") -> dict | None:
    if hist is None or len(hist) < BEAR_TREND_MIN_BARS:
        bars = len(hist) if hist is not None else 0
        log.info(f"Bear trend [{sym}]: insufficient bars {bars} < {BEAR_TREND_MIN_BARS} — skip")
        return None
    required = {"High", "Low", "Close", "Volume"}
    if not required.issubset(set(hist.columns)):
        log.info(f"Bear trend [{sym}]: missing columns {required - set(hist.columns)} — skip")
        return None

    df = hist.dropna(subset=["High", "Low", "Close", "Volume"]).copy()
    if len(df) < BEAR_TREND_MIN_BARS:
        log.info(f"Bear trend [{sym}]: bars after dropna {len(df)} < {BEAR_TREND_MIN_BARS} — skip")
        return None

    typical = (df["High"] + df["Low"] + df["Close"]) / 3
    cumulative_volume = df["Volume"].cumsum()
    if float(cumulative_volume.iloc[-1]) <= 0:
        log.info(f"Bear trend [{sym}]: zero cumulative volume — skip")
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
    lower_high_pullback = prev_close <= ema50 * 1.002

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
        if bid > 0 and ask > 0:
            return round((bid + ask) / 2, 3)
        return float(snap.get("latestTrade", {}).get("p", 0) or 0)
    except Exception:
        return 0.0


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
        px     = float(row['lastPrice'].values[0])
        return _occ(sym, exp, right, strike), strike, px, exp
    except Exception:
        return "", 0.0, 0.0, ""


def find_0dte(account: float) -> dict | None:
    today    = date.today()
    catalyst = next(((d, t, mode) for d, t, mode in CATALYST_DAYS if d == today), None)
    price    = _spot("SPY")
    prev     = _prev_close("SPY")
    gap      = abs(price - prev) / prev if prev > 0 else 0.0
    up       = price > prev

    if not catalyst and gap < GAP_THRESHOLD:
        log.info("0DTE: no catalyst, no gap")
        return None

    right = "PUT" if (not catalyst and not up) else "CALL"
    occ, strike, px, exp = _atm_option("SPY", right)
    if not occ or px <= 0:
        return None

    max_risk  = account * MAX_RISK_PCT
    contracts = min(int(max_risk // (px * 100)), MAX_CONTRACTS)
    if contracts < 1:
        log.info(f"0DTE: can't afford 1 contract at ${px:.2f} (budget ${max_risk:.0f})")
        return None

    return {
        "strategy": "0dte", "symbol": "SPY", "right": right,
        "option_symbol": occ, "strike": strike, "expiry": exp,
        "contracts": contracts, "entry_price_est": px,
        "catalyst": catalyst[1] if catalyst else f"GAP {'UP' if up else 'DOWN'} {gap*100:.1f}%",
        "hard_close_date": str(today), "hard_close_time": "13:45",
    }


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


def find_bear_trend_day(account: float) -> dict | None:
    now_et = _now_et()
    if now_et.time() >= BEAR_TREND_ENTRY_CUTOFF_ET:
        log.info("Bear trend: past 2pm ET entry cutoff — skip")
        return None

    leaders = ["SPY", "QQQ", "IWM"]
    signals = {sym: _vwap_50ema_signal(_intraday_bars(sym), sym) for sym in leaders}
    valid = {sym: sig for sym, sig in signals.items() if sig and sig["score"] >= BEAR_TREND_MIN_CONFIDENCE}

    scores_str = " | ".join(
        f"{sym}={sig['score']}/10" if sig else f"{sym}=no_data"
        for sym, sig in signals.items()
    )
    log.info(f"Bear trend breadth: {scores_str} | confirmed={list(valid.keys())} need≥2")

    if len(valid) < 2:
        failing = {sym: sig for sym, sig in signals.items() if sig and sig["score"] < BEAR_TREND_MIN_CONFIDENCE}
        for sym, sig in failing.items():
            gap = BEAR_TREND_MIN_CONFIDENCE - sig["score"]
            log.info(
                f"Bear trend [{sym}]: score {sig['score']}/10 — needs {gap} more pts "
                f"(vwap_dist={sig['vwap_distance']*100:.2f}% reasons={sig['reasons']})"
            )
        log.info(f"Bear trend: only {len(valid)}/3 symbols confirm — need 2 — skip")
        return None

    signal = valid.get("SPY") or next(iter(valid.values()))
    if signal["score"] < BEAR_TREND_MIN_CONFIDENCE:
        log.info(f"Bear trend: SPY score {signal['score']}/10 < min {BEAR_TREND_MIN_CONFIDENCE} — skip")
        return None

    occ, strike, px, exp = _atm_option("SPY", "PUT")
    if not occ or px <= 0:
        log.info("Bear trend: could not find SPY ATM put — skip")
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
            "catalyst": f"VWAP/50EMA bear trend {signal['score']}/10: {reason_text}",
        }

    # ATM put too expensive for budget — try bear put debit spread
    log.info(f"Bear trend: SPY put ${px:.2f} exceeds budget ${max_risk:.0f} — trying bear put spread")
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
                "catalyst": f"VWAP/50EMA bear spread {signal['score']}/10: {reason_text}",
            }

    log.info(f"Bear trend: no spread fits budget ${max_risk:.0f} — skip")
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

def _submit(occ_symbol: str, qty: int, side: str, max_notional: float = 0.0) -> dict | None:
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
    if manual_reset_required():
        msg = f"MANUAL RESET REQUIRED - order blocked by {DEFAULT_BLOCK_FILE}"
        log.error(msg)
        _alert(f"ORDER BLOCKED {occ_symbol} x{qty} {side}\nManual reset required before any new orders.")
        return None

    body = {"symbol": occ_symbol, "qty": str(qty), "side": side,
            "type": "market", "time_in_force": "day"}
    for attempt in range(3):
        try:
            resp = _post("/v2/orders", body)
            log.info(f"Order OK: {resp.get('id')} {side} {occ_symbol} x{qty}")
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


# ---------------------------------------------------------------------------
# Entry run
# ---------------------------------------------------------------------------

def run_entry(account: float) -> None:
    log.info(f"=== FLIP ENTRY  ${account:.0f}  {'PAPER' if PAPER else 'LIVE'} ===")
    if not _market_open():
        log.info("Market is closed - skip flip entry")
        return

    open_trades = [t for t in _load() if t.get("status") == "open"]
    if len(open_trades) >= MAX_OPEN_FLIPS:
        log.info(f"Max open ({MAX_OPEN_FLIPS}) reached — skip")
        return

    slots      = MAX_OPEN_FLIPS - len(open_trades)
    candidates = []

    s = find_bear_trend_day(account)
    if s:
        candidates.append(s)

    s = find_0dte(account)
    if s and len(candidates) < slots:
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
        log.info("No flip setup today — waiting")
        return

    trades = _load()
    for setup in candidates:
        max_notional = account * MAX_RISK_PCT
        resp = _submit(setup["option_symbol"], setup["contracts"], "buy", max_notional=max_notional)
        if not resp:
            continue

        time.sleep(6)
        try:
            detail       = _get(f"/v2/orders/{resp['id']}")
            filled_price = float(detail.get("filled_avg_price") or setup["entry_price_est"])
        except Exception:
            filled_price = setup["entry_price_est"]

        trade = {
            "id":              str(uuid4()),
            "alpaca_order_id": resp.get("id"),
            "strategy":        setup["strategy"],
            "symbol":          setup["symbol"],
            "right":           setup["right"],
            "option_symbol":   setup["option_symbol"],
            "strike":          setup["strike"],
            "expiry":          setup["expiry"],
            "contracts":       setup["contracts"],
            "entry_price":     filled_price,
            "target_price":    round(filled_price * PROFIT_MULT, 3),
            "stop_price":      round(filled_price * STOP_MULT, 3),
            "hard_close_date": setup.get("hard_close_date"),
            "hard_close_time": setup.get("hard_close_time"),
            "entry_date":      str(date.today()),
            "status":          "open",
            "catalyst":        setup.get("catalyst", ""),
        }
        trades.append(trade)
        _save(trades)

        msg = (f"ENTRY {setup['strategy'].upper()} {setup['symbol']} {setup['right']}\n"
               f"Option: {setup['option_symbol']}\n"
               f"Qty: {setup['contracts']}  Fill: ${filled_price:.3f}\n"
               f"Target: ${trade['target_price']:.3f} (+75%)  Stop: ${trade['stop_price']:.3f} (-50%)\n"
               f"Close by: {setup.get('hard_close_date','')} {setup.get('hard_close_time','') or ''}\n"
               f"Catalyst: {setup.get('catalyst','')}")
        log.info(msg)
        _alert(msg)


# ---------------------------------------------------------------------------
# Monitor run
# ---------------------------------------------------------------------------

def run_monitor() -> None:
    log.info("=== FLIP MONITOR ===")
    if not _market_open():
        log.info("Market is closed - skip flip monitor")
        return

    trades  = _load()
    now     = datetime.now()
    today   = date.today()
    changed = False

    for trade in trades:
        if trade.get("status") != "open":
            continue

        occ    = trade["option_symbol"]
        mid    = _option_mid(occ)
        entry  = trade["entry_price"]
        target = trade["target_price"]
        stop   = trade["stop_price"]
        qty    = trade["contracts"]

        if mid <= 0:
            log.warning(f"No price for {occ}")
            continue

        pnl_pct = (mid - entry) / entry * 100
        log.info(f"{occ}  mid=${mid:.3f}  P&L={pnl_pct:+.1f}%  target=${target:.3f}  stop=${stop:.3f}")

        reason = None
        if mid >= target:
            reason = f"PROFIT TARGET +{pnl_pct:.1f}%"
        elif mid <= stop:
            reason = f"STOP LOSS {pnl_pct:.1f}%"
        elif trade.get("hard_close_time"):
            cutoff = datetime.strptime(f"{today} {trade['hard_close_time']}", "%Y-%m-%d %H:%M")
            if now >= cutoff:
                reason = f"TIME EXIT {trade['hard_close_time']}"
        elif trade.get("hard_close_date"):
            hard = datetime.strptime(trade["hard_close_date"], "%Y-%m-%d").date()
            if today >= hard:
                reason = f"DATE EXIT (before {trade.get('catalyst','')})"
        elif trade.get("strategy") == "breakout":
            entry_d = datetime.strptime(trade["entry_date"], "%Y-%m-%d").date()
            if (today - entry_d).days >= 3:
                reason = "MAX HOLD 3 DAYS"

        if reason:
            resp = _submit(occ, qty, "sell")
            if resp:
                trade["status"]      = "closed"
                trade["exit_price"]  = mid
                trade["exit_reason"] = reason
                trade["exit_date"]   = str(today)
                trade["pnl"]         = round((mid - entry) * qty * 100, 2)
                changed = True
                msg = (f"EXIT {trade['strategy'].upper()} {trade['symbol']}\n"
                       f"Option: {occ}\n"
                       f"Entry: ${entry:.3f}  Exit: ${mid:.3f}  P&L: ${trade['pnl']:+.2f}\n"
                       f"Reason: {reason}")
                log.info(msg)
                _alert(msg)
            else:
                _alert(f"CLOSE FAILED {occ} — CLOSE MANUALLY NOW")

    if changed:
        _save(trades)


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
        resp = _submit(t["option_symbol"], t["contracts"], "sell")
        if resp:
            mid          = _option_mid(t["option_symbol"])
            t["status"]      = "closed"
            t["exit_price"]  = mid
            t["exit_reason"] = "manual close-all"
            t["exit_date"]   = str(date.today())
            t["pnl"]         = round((mid - t["entry_price"]) * t["contracts"] * 100, 2)
            log.info(f"Closed {t['option_symbol']}  P&L ${t['pnl']:+.2f}")
    _save(trades)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    ap = argparse.ArgumentParser(description="Flip Bot — automated directional options for small accounts")
    ap.add_argument("--entry",     action="store_true")
    ap.add_argument("--monitor",   action="store_true")
    ap.add_argument("--status",    action="store_true")
    ap.add_argument("--close-all", action="store_true")
    ap.add_argument("--account",   type=float, default=None,
                    help="Account size to simulate for this run. Overrides FLIP_ACCOUNT_SIZE_OVERRIDE / ACCOUNT_SIZE_OVERRIDE.")
    args = ap.parse_args()

    if not KEY or not SECRET:
        log.error("Alpaca keys missing in agent/.env")
        sys.exit(1)

    account = resolve_account_size(args.account)

    if args.status:
        print_status()
    elif args.close_all:
        close_all()
    elif args.entry:
        run_entry(account)
    elif args.monitor:
        run_monitor()
    else:
        ap.print_help()


if __name__ == "__main__":
    main()

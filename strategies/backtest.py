#!/usr/bin/env python3
"""
Backtest / replay engine — simulates put spread and iron condor entries
on historical OHLCV+IV data using the same filters as the live bot.

Usage:
    python strategies/backtest.py                         # IWM, ps, 252 days
    python strategies/backtest.py --days 504 --symbol IWM --strategy ic
    python strategies/backtest.py --days 252 --symbol SPY --strategy ps --report
    python strategies/backtest.py --days 252 --symbol all --strategy ps
"""
from __future__ import annotations

import argparse
import json
import math
import os
import sys
from dataclasses import asdict, dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv

load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), "..", "agent", ".env"))

try:
    import yfinance as yf
except ImportError:
    print("ERROR: yfinance not installed. Run: pip install yfinance")
    sys.exit(1)

LOG_DIR = Path(os.path.expanduser(r"~\.vibe-trading\logs"))
LOG_DIR.mkdir(parents=True, exist_ok=True)
BACKTEST_LOG = LOG_DIR / "backtest.jsonl"
SIM_SKIP_COUNTS: dict[str, int] = {}

RISK_FREE_RATE = 0.05
PROFIT_TARGET_PCT = 0.50
STOP_LOSS_PCT = 2.00
MAX_ACCOUNT_RISK_PCT = float(os.getenv("MAX_ACCOUNT_RISK_PCT", "0.02"))
BACKTEST_ACCOUNT_SIZE = float(
    os.getenv("BACKTEST_ACCOUNT_SIZE")
    or os.getenv("ACCOUNT_SIZE_OVERRIDE")
    or "10000"
)
MIN_CREDIT_TO_RISK = float(os.getenv("MIN_CREDIT_TO_RISK", "0.20"))
MIN_NET_CREDIT = float(os.getenv("MIN_NET_CREDIT", "0.10"))
SLIPPAGE_PCT_OF_CREDIT = float(os.getenv("BACKTEST_SLIPPAGE_PCT_OF_CREDIT", "0.05"))
COMMISSION_PER_CONTRACT = float(os.getenv("BACKTEST_COMMISSION_PER_CONTRACT", "0.65"))

PS_DTE = 10
IC_DTE = 37
PS_WIDTH_DEFAULT = 3.0
PS_WIDTH_OVERRIDE = {"SPY": 5.0, "QQQ": 5.0, "TSLA": 5.0, "AAPL": 5.0}
IC_WING_WIDTH = 2.0
PS_TARGET_DELTA = 0.25
IC_CALL_DELTA = 0.16
IC_PUT_DELTA = 0.16

IV_RANK_MIN = 30.0
VIX_MIN = 15.0
VIX_MAX = 40.0
SMA_PERIOD = 20
WARMUP_DAYS = 280
IC_DTE_MANAGE_DAYS = int(os.getenv("IC_DTE_MANAGE_DAYS", "21"))
PS_DTE_MANAGE_DAYS = int(os.getenv("PS_DTE_MANAGE_DAYS", "2"))


# ---------------------------------------------------------------------------
# Black-Scholes (no scipy — pure math.erf)
# ---------------------------------------------------------------------------

def _ncdf(x: float) -> float:
    return (1.0 + math.erf(x / math.sqrt(2.0))) / 2.0


def bs_price(S: float, K: float, T: float, r: float, sigma: float, right: str) -> float:
    if T <= 0 or sigma <= 0:
        intrinsic = max(S - K, 0) if right == "C" else max(K - S, 0)
        return intrinsic
    d1 = (math.log(S / K) + (r + 0.5 * sigma ** 2) * T) / (sigma * math.sqrt(T))
    d2 = d1 - sigma * math.sqrt(T)
    if right == "C":
        return S * _ncdf(d1) - K * math.exp(-r * T) * _ncdf(d2)
    return K * math.exp(-r * T) * _ncdf(-d2) - S * _ncdf(-d1)


def bs_delta(S: float, K: float, T: float, r: float, sigma: float, right: str) -> float:
    if T <= 0 or sigma <= 0:
        if right == "C":
            return 1.0 if S > K else 0.0
        return -1.0 if S < K else 0.0
    d1 = (math.log(S / K) + (r + 0.5 * sigma ** 2) * T) / (sigma * math.sqrt(T))
    if right == "C":
        return _ncdf(d1)
    return _ncdf(d1) - 1.0


def find_delta_strike(S: float, T: float, r: float, sigma: float, target_delta: float, right: str) -> float:
    lo, hi = S * 0.5, S * 1.5
    for _ in range(60):
        mid = (lo + hi) / 2.0
        d = bs_delta(S, mid, T, r, sigma, right)
        if right == "P":
            if d > target_delta:
                lo = mid
            else:
                hi = mid
        else:
            if d > target_delta:
                hi = mid
            else:
                lo = mid
    return round((lo + hi) / 2.0, 2)


# ---------------------------------------------------------------------------
# Historical data helpers
# ---------------------------------------------------------------------------

def _iv_estimate(hist, idx: int, window: int = 20) -> float:
    closes = hist["Close"].values
    if idx < window + 1:
        return 0.0
    log_rets = [math.log(closes[i] / closes[i - 1]) for i in range(idx - window, idx)]
    mean = sum(log_rets) / len(log_rets)
    variance = sum((r - mean) ** 2 for r in log_rets) / (len(log_rets) - 1)
    return math.sqrt(variance * 252)


def _iv_rank(hist, idx: int, lookback: int = 252) -> float:
    ivs = [_iv_estimate(hist, i) for i in range(max(1, idx - lookback), idx)]
    if not ivs:
        return 0.0
    iv_now = _iv_estimate(hist, idx)
    iv_min, iv_max = min(ivs), max(ivs)
    if iv_max == iv_min:
        return 50.0
    return (iv_now - iv_min) / (iv_max - iv_min) * 100.0


def _sma(hist, idx: int, period: int = 20) -> float:
    closes = hist["Close"].values
    if idx < period:
        return 0.0
    return sum(closes[idx - period:idx]) / period


def _qty_for_risk(max_risk_per_contract: float, account_size: float) -> int:
    risk_budget = account_size * MAX_ACCOUNT_RISK_PCT
    if max_risk_per_contract <= 0:
        return 0
    return int(risk_budget // max_risk_per_contract)


def _credit_quality_ok(credit: float, max_risk_per_contract: float) -> bool:
    if credit < MIN_NET_CREDIT:
        return False
    return (credit * 100 / max_risk_per_contract) >= MIN_CREDIT_TO_RISK


def _entry_slippage(credit: float) -> float:
    return max(0.0, credit * SLIPPAGE_PCT_OF_CREDIT)


def _round_trip_commission(legs: int, qty: int) -> float:
    return legs * qty * COMMISSION_PER_CONTRACT * 2


def _note_sim_skip(reason: str) -> None:
    SIM_SKIP_COUNTS[reason] = SIM_SKIP_COUNTS.get(reason, 0) + 1


def passes_filters(hist, vix_hist, idx: int, symbol: str) -> tuple[bool, str]:
    closes = hist["Close"].values
    if idx < SMA_PERIOD + 1:
        return False, "insufficient history"

    iv_r = _iv_rank(hist, idx)
    if iv_r < IV_RANK_MIN:
        return False, f"IV rank {iv_r:.1f} < {IV_RANK_MIN}"

    vix_dates = list(vix_hist.index)
    hist_dates = list(hist.index)
    if idx >= len(hist_dates):
        return False, "index out of range"
    target_date = hist_dates[idx]
    vix_idx = None
    for vi, vd in enumerate(vix_dates):
        if hasattr(vd, "date"):
            vd = vd.date()
        if hasattr(target_date, "date"):
            target_date_cmp = target_date.date()
        else:
            target_date_cmp = target_date
        if vd == target_date_cmp:
            vix_idx = vi
            break
    if vix_idx is None:
        return False, "VIX data not aligned"

    vix_close = vix_hist["Close"].values[vix_idx]
    if vix_close < VIX_MIN or vix_close > VIX_MAX:
        return False, f"VIX {vix_close:.1f} out of range"

    sma = _sma(hist, idx)
    price = float(closes[idx])
    if price < sma:
        return False, f"price {price:.2f} below 20-SMA {sma:.2f}"

    return True, "ok"


# ---------------------------------------------------------------------------
# Trade result
# ---------------------------------------------------------------------------

@dataclass
class TradeResult:
    symbol: str
    strategy: str
    entry_date: str
    exit_date: str
    entry_credit: float
    exit_cost: float
    pnl: float
    pnl_pct: float
    days_held: int
    exit_reason: str
    short_strike: float
    long_strike: float
    dte_at_entry: int
    qty: int = 1
    max_risk_per_contract: float = 0.0
    account_size: float = 0.0
    short_call_strike: float = 0.0
    long_call_strike: float = 0.0


@dataclass
class BacktestMetrics:
    total_pnl: float
    return_pct: float
    profit_factor: float
    expectancy: float
    max_drawdown: float
    max_drawdown_pct: float
    max_consecutive_losses: int


def _parse_result_date(value: str) -> datetime:
    return datetime.strptime(value[:10], "%Y-%m-%d")


def _metrics(results: list[TradeResult], account_size: float) -> BacktestMetrics:
    ordered = sorted(results, key=lambda r: (_parse_result_date(r.exit_date), _parse_result_date(r.entry_date)))
    gross_profit = sum(r.pnl for r in ordered if r.pnl > 0)
    gross_loss = abs(sum(r.pnl for r in ordered if r.pnl < 0))
    total_pnl = gross_profit - gross_loss
    profit_factor = gross_profit / gross_loss if gross_loss else float("inf")
    expectancy = total_pnl / len(ordered) if ordered else 0.0

    equity = account_size
    peak = account_size
    max_drawdown = 0.0
    max_drawdown_pct = 0.0
    consecutive_losses = 0
    max_consecutive_losses = 0

    for result in ordered:
        equity += result.pnl
        peak = max(peak, equity)
        drawdown = peak - equity
        if drawdown > max_drawdown:
            max_drawdown = drawdown
            max_drawdown_pct = drawdown / peak * 100 if peak else 0.0

        if result.pnl <= 0:
            consecutive_losses += 1
            max_consecutive_losses = max(max_consecutive_losses, consecutive_losses)
        else:
            consecutive_losses = 0

    return BacktestMetrics(
        total_pnl=round(total_pnl, 2),
        return_pct=round(total_pnl / account_size * 100, 2) if account_size else 0.0,
        profit_factor=profit_factor,
        expectancy=round(expectancy, 2),
        max_drawdown=round(max_drawdown, 2),
        max_drawdown_pct=round(max_drawdown_pct, 2),
        max_consecutive_losses=max_consecutive_losses,
    )


# ---------------------------------------------------------------------------
# Put spread simulator
# ---------------------------------------------------------------------------

def sim_put_spread(symbol: str, hist, vix_hist, entry_idx: int) -> Optional[TradeResult]:
    closes = hist["Close"].values
    dates = list(hist.index)
    if entry_idx + PS_DTE >= len(closes):
        _note_sim_skip("insufficient_forward_data")
        return None
    S = float(closes[entry_idx])
    T_years = PS_DTE / 365.0
    sigma = _iv_estimate(hist, entry_idx) or 0.20

    width = PS_WIDTH_OVERRIDE.get(symbol, PS_WIDTH_DEFAULT)

    short_strike = find_delta_strike(S, T_years, RISK_FREE_RATE, sigma, -PS_TARGET_DELTA, "P")
    long_strike = short_strike - width
    long_strike = round(long_strike, 2)

    short_price = bs_price(S, short_strike, T_years, RISK_FREE_RATE, sigma, "P")
    long_price = bs_price(S, long_strike, T_years, RISK_FREE_RATE, sigma, "P")
    theoretical_credit = short_price - long_price
    credit = theoretical_credit - _entry_slippage(theoretical_credit)

    max_risk_per_contract = (width - credit) * 100
    if not _credit_quality_ok(credit, max_risk_per_contract):
        _note_sim_skip("pricing_credit_quality")
        return None

    qty = _qty_for_risk(max_risk_per_contract, BACKTEST_ACCOUNT_SIZE)
    if qty < 1:
        _note_sim_skip("sizing_risk_budget")
        return None

    profit_target = credit * PROFIT_TARGET_PCT
    stop_loss_cost = credit * (1 + STOP_LOSS_PCT)

    entry_date_str = str(dates[entry_idx].date() if hasattr(dates[entry_idx], "date") else dates[entry_idx])

    for days_held in range(1, PS_DTE + 5):
        future_idx = entry_idx + days_held
        if future_idx >= len(closes):
            break
        S_now = float(closes[future_idx])
        T_rem = max((PS_DTE - days_held) / 365.0, 1e-6)
        sigma_now = _iv_estimate(hist, future_idx) or sigma

        short_now = bs_price(S_now, short_strike, T_rem, RISK_FREE_RATE, sigma_now, "P")
        long_now = bs_price(S_now, long_strike, T_rem, RISK_FREE_RATE, sigma_now, "P")
        cost_to_close = short_now - long_now

        exit_date_str = str(dates[future_idx].date() if hasattr(dates[future_idx], "date") else dates[future_idx])

        if cost_to_close <= profit_target:
            pnl = ((credit - cost_to_close) * 100 * qty) - _round_trip_commission(2, qty)
            return TradeResult(
                symbol=symbol, strategy="ps",
                entry_date=entry_date_str, exit_date=exit_date_str,
                entry_credit=round(credit, 4), exit_cost=round(cost_to_close, 4),
                pnl=round(pnl, 2), pnl_pct=round((pnl / (max_risk_per_contract * qty)) * 100, 2),
                days_held=days_held, exit_reason="profit_target",
                short_strike=short_strike, long_strike=long_strike,
                dte_at_entry=PS_DTE, qty=qty,
                max_risk_per_contract=round(max_risk_per_contract, 2),
                account_size=BACKTEST_ACCOUNT_SIZE,
            )

        if cost_to_close >= stop_loss_cost:
            pnl = ((credit - cost_to_close) * 100 * qty) - _round_trip_commission(2, qty)
            return TradeResult(
                symbol=symbol, strategy="ps",
                entry_date=entry_date_str, exit_date=exit_date_str,
                entry_credit=round(credit, 4), exit_cost=round(cost_to_close, 4),
                pnl=round(pnl, 2), pnl_pct=round((pnl / (max_risk_per_contract * qty)) * 100, 2),
                days_held=days_held, exit_reason="stop_loss",
                short_strike=short_strike, long_strike=long_strike,
                dte_at_entry=PS_DTE, qty=qty,
                max_risk_per_contract=round(max_risk_per_contract, 2),
                account_size=BACKTEST_ACCOUNT_SIZE,
            )

        if PS_DTE - days_held <= PS_DTE_MANAGE_DAYS:
            pnl = ((credit - cost_to_close) * 100 * qty) - _round_trip_commission(2, qty)
            return TradeResult(
                symbol=symbol, strategy="ps",
                entry_date=entry_date_str, exit_date=exit_date_str,
                entry_credit=round(credit, 4), exit_cost=round(cost_to_close, 4),
                pnl=round(pnl, 2), pnl_pct=round((pnl / (max_risk_per_contract * qty)) * 100, 2),
                days_held=days_held, exit_reason="time_exit",
                short_strike=short_strike, long_strike=long_strike,
                dte_at_entry=PS_DTE, qty=qty,
                max_risk_per_contract=round(max_risk_per_contract, 2),
                account_size=BACKTEST_ACCOUNT_SIZE,
            )

    # expiry — mark to intrinsic
    expire_idx = min(entry_idx + PS_DTE, len(closes) - 1)
    S_exp = float(closes[expire_idx])
    intrinsic_short = max(short_strike - S_exp, 0)
    intrinsic_long = max(long_strike - S_exp, 0)
    cost_at_exp = intrinsic_short - intrinsic_long
    pnl = ((credit - cost_at_exp) * 100 * qty) - _round_trip_commission(2, qty)
    exit_date_str = str(dates[expire_idx].date() if hasattr(dates[expire_idx], "date") else dates[expire_idx])
    return TradeResult(
        symbol=symbol, strategy="ps",
        entry_date=entry_date_str, exit_date=exit_date_str,
        entry_credit=round(credit, 4), exit_cost=round(cost_at_exp, 4),
        pnl=round(pnl, 2), pnl_pct=round((pnl / (max_risk_per_contract * qty)) * 100, 2),
        days_held=PS_DTE, exit_reason="expiry",
        short_strike=short_strike, long_strike=long_strike,
        dte_at_entry=PS_DTE, qty=qty,
        max_risk_per_contract=round(max_risk_per_contract, 2),
        account_size=BACKTEST_ACCOUNT_SIZE,
    )


# ---------------------------------------------------------------------------
# Iron condor simulator
# ---------------------------------------------------------------------------

def sim_iron_condor(symbol: str, hist, vix_hist, entry_idx: int) -> Optional[TradeResult]:
    closes = hist["Close"].values
    dates = list(hist.index)
    if entry_idx + IC_DTE >= len(closes):
        _note_sim_skip("insufficient_forward_data")
        return None
    S = float(closes[entry_idx])
    T_years = IC_DTE / 365.0
    sigma = _iv_estimate(hist, entry_idx) or 0.20

    short_put = find_delta_strike(S, T_years, RISK_FREE_RATE, sigma, -IC_PUT_DELTA, "P")
    long_put = round(short_put - IC_WING_WIDTH, 2)
    short_call = find_delta_strike(S, T_years, RISK_FREE_RATE, sigma, IC_CALL_DELTA, "C")
    long_call = round(short_call + IC_WING_WIDTH, 2)

    sp_price = bs_price(S, short_put, T_years, RISK_FREE_RATE, sigma, "P")
    lp_price = bs_price(S, long_put, T_years, RISK_FREE_RATE, sigma, "P")
    sc_price = bs_price(S, short_call, T_years, RISK_FREE_RATE, sigma, "C")
    lc_price = bs_price(S, long_call, T_years, RISK_FREE_RATE, sigma, "C")

    theoretical_credit = (sp_price - lp_price) + (sc_price - lc_price)
    credit = theoretical_credit - _entry_slippage(theoretical_credit)
    max_risk_per_contract = (IC_WING_WIDTH - credit) * 100
    if not _credit_quality_ok(credit, max_risk_per_contract):
        _note_sim_skip("pricing_credit_quality")
        return None

    qty = _qty_for_risk(max_risk_per_contract, BACKTEST_ACCOUNT_SIZE)
    if qty < 1:
        _note_sim_skip("sizing_risk_budget")
        return None

    profit_target = credit * PROFIT_TARGET_PCT
    stop_loss_cost = credit * (1 + STOP_LOSS_PCT)

    entry_date_str = str(dates[entry_idx].date() if hasattr(dates[entry_idx], "date") else dates[entry_idx])

    for days_held in range(1, IC_DTE + 10):
        future_idx = entry_idx + days_held
        if future_idx >= len(closes):
            break
        S_now = float(closes[future_idx])
        T_rem = max((IC_DTE - days_held) / 365.0, 1e-6)
        sigma_now = _iv_estimate(hist, future_idx) or sigma

        sp_now = bs_price(S_now, short_put, T_rem, RISK_FREE_RATE, sigma_now, "P")
        lp_now = bs_price(S_now, long_put, T_rem, RISK_FREE_RATE, sigma_now, "P")
        sc_now = bs_price(S_now, short_call, T_rem, RISK_FREE_RATE, sigma_now, "C")
        lc_now = bs_price(S_now, long_call, T_rem, RISK_FREE_RATE, sigma_now, "C")
        cost_to_close = (sp_now - lp_now) + (sc_now - lc_now)

        exit_date_str = str(dates[future_idx].date() if hasattr(dates[future_idx], "date") else dates[future_idx])

        if cost_to_close <= profit_target:
            pnl = ((credit - cost_to_close) * 100 * qty) - _round_trip_commission(4, qty)
            return TradeResult(
                symbol=symbol, strategy="ic",
                entry_date=entry_date_str, exit_date=exit_date_str,
                entry_credit=round(credit, 4), exit_cost=round(cost_to_close, 4),
                pnl=round(pnl, 2), pnl_pct=round((pnl / (max_risk_per_contract * qty)) * 100, 2),
                days_held=days_held, exit_reason="profit_target",
                short_strike=short_put, long_strike=long_put,
                short_call_strike=short_call, long_call_strike=long_call,
                dte_at_entry=IC_DTE, qty=qty,
                max_risk_per_contract=round(max_risk_per_contract, 2),
                account_size=BACKTEST_ACCOUNT_SIZE,
            )

        if cost_to_close >= stop_loss_cost:
            pnl = ((credit - cost_to_close) * 100 * qty) - _round_trip_commission(4, qty)
            return TradeResult(
                symbol=symbol, strategy="ic",
                entry_date=entry_date_str, exit_date=exit_date_str,
                entry_credit=round(credit, 4), exit_cost=round(cost_to_close, 4),
                pnl=round(pnl, 2), pnl_pct=round((pnl / (max_risk_per_contract * qty)) * 100, 2),
                days_held=days_held, exit_reason="stop_loss",
                short_strike=short_put, long_strike=long_put,
                short_call_strike=short_call, long_call_strike=long_call,
                dte_at_entry=IC_DTE, qty=qty,
                max_risk_per_contract=round(max_risk_per_contract, 2),
                account_size=BACKTEST_ACCOUNT_SIZE,
            )

        if IC_DTE - days_held <= IC_DTE_MANAGE_DAYS:
            pnl = ((credit - cost_to_close) * 100 * qty) - _round_trip_commission(4, qty)
            return TradeResult(
                symbol=symbol, strategy="ic",
                entry_date=entry_date_str, exit_date=exit_date_str,
                entry_credit=round(credit, 4), exit_cost=round(cost_to_close, 4),
                pnl=round(pnl, 2), pnl_pct=round((pnl / (max_risk_per_contract * qty)) * 100, 2),
                days_held=days_held, exit_reason="time_exit",
                short_strike=short_put, long_strike=long_put,
                short_call_strike=short_call, long_call_strike=long_call,
                dte_at_entry=IC_DTE, qty=qty,
                max_risk_per_contract=round(max_risk_per_contract, 2),
                account_size=BACKTEST_ACCOUNT_SIZE,
            )

    expire_idx = min(entry_idx + IC_DTE, len(closes) - 1)
    S_exp = float(closes[expire_idx])
    put_loss = max(short_put - S_exp, 0) - max(long_put - S_exp, 0)
    call_loss = max(S_exp - short_call, 0) - max(S_exp - long_call, 0)
    cost_at_exp = put_loss + call_loss
    pnl = ((credit - cost_at_exp) * 100 * qty) - _round_trip_commission(4, qty)
    exit_date_str = str(dates[expire_idx].date() if hasattr(dates[expire_idx], "date") else dates[expire_idx])
    return TradeResult(
        symbol=symbol, strategy="ic",
        entry_date=entry_date_str, exit_date=exit_date_str,
        entry_credit=round(credit, 4), exit_cost=round(cost_at_exp, 4),
        pnl=round(pnl, 2), pnl_pct=round((pnl / (max_risk_per_contract * qty)) * 100, 2),
        days_held=IC_DTE, exit_reason="expiry",
        short_strike=short_put, long_strike=long_put,
        short_call_strike=short_call, long_call_strike=long_call,
        dte_at_entry=IC_DTE, qty=qty,
        max_risk_per_contract=round(max_risk_per_contract, 2),
        account_size=BACKTEST_ACCOUNT_SIZE,
    )


# ---------------------------------------------------------------------------
# Run backtest for one symbol + strategy
# ---------------------------------------------------------------------------

ALL_SYMBOLS = ["IWM", "SPY", "QQQ", "TSLA", "NVDA", "AAPL", "PLTR"]

def run_backtest(symbol: str, strategy: str, days: int) -> list[TradeResult]:
    print(f"Downloading {symbol} ({days} trading days)...")
    SIM_SKIP_COUNTS.clear()
    end = datetime.today()
    start = end - timedelta(days=int((days + WARMUP_DAYS) * 1.7))

    try:
        hist = yf.download(symbol, start=start.strftime("%Y-%m-%d"),
                           end=end.strftime("%Y-%m-%d"), auto_adjust=True, progress=False)
        vix_hist = yf.download("^VIX", start=start.strftime("%Y-%m-%d"),
                               end=end.strftime("%Y-%m-%d"), auto_adjust=True, progress=False)
    except Exception as exc:
        print(f"ERROR: data download failed for {symbol}: {exc}")
        return []

    if hist.empty or vix_hist.empty:
        print(f"ERROR: no data returned for {symbol}")
        return []

    # If columns are MultiIndex (yfinance 0.2+), flatten
    if hasattr(hist.columns, "levels"):
        hist.columns = [c[0] for c in hist.columns]
    if hasattr(vix_hist.columns, "levels"):
        vix_hist.columns = [c[0] for c in vix_hist.columns]

    hist = hist.tail(days + WARMUP_DAYS)
    vix_hist = vix_hist.tail(days + WARMUP_DAYS)

    results: list[TradeResult] = []
    skip_counts: dict[str, int] = {}
    step = PS_DTE if strategy == "ps" else IC_DTE

    i = max(SMA_PERIOD + 252 + 1, len(hist) - days)
    entry_dates_used: set[str] = set()

    while i < len(hist):
        ok, reason = passes_filters(hist, vix_hist, i, symbol)
        if not ok:
            skip_counts[reason] = skip_counts.get(reason, 0) + 1
            i += 1
            continue

        dates = list(hist.index)
        entry_str = str(dates[i].date() if hasattr(dates[i], "date") else dates[i])
        if entry_str in entry_dates_used:
            skip_counts["entry_date_already_used"] = skip_counts.get("entry_date_already_used", 0) + 1
            i += 1
            continue

        result = None
        if strategy == "ps":
            result = sim_put_spread(symbol, hist, vix_hist, i)
        elif strategy == "ic":
            result = sim_iron_condor(symbol, hist, vix_hist, i)

        if result:
            results.append(result)
            entry_dates_used.add(entry_str)
            i += step
        else:
            skip_counts["candidate_failed_pricing_or_sizing"] = skip_counts.get("candidate_failed_pricing_or_sizing", 0) + 1
            i += 1

    for reason, count in SIM_SKIP_COUNTS.items():
        skip_counts[reason] = skip_counts.get(reason, 0) + count
    run_backtest.last_skip_counts = skip_counts
    return results


# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------

def print_report(results: list[TradeResult], symbol: str, strategy: str, days: int, skip_counts: Optional[dict[str, int]] = None) -> None:
    if not results:
        print(f"\nNo trades generated for {symbol} / {strategy} over {days} days.\n")
        if skip_counts:
            print("Top skip reasons:")
            for reason, count in sorted(skip_counts.items(), key=lambda item: item[1], reverse=True)[:10]:
                print(f"  {count:>4}  {reason}")
            print()
        return

    wins = [r for r in results if r.pnl > 0]
    losses = [r for r in results if r.pnl <= 0]
    total_pnl = sum(r.pnl for r in results)
    win_rate = len(wins) / len(results) * 100
    avg_win = sum(r.pnl for r in wins) / len(wins) if wins else 0
    avg_loss = sum(r.pnl for r in losses) / len(losses) if losses else 0
    avg_hold = sum(r.days_held for r in results) / len(results)
    worst_trade = min(r.pnl for r in results)
    metrics = _metrics(results, BACKTEST_ACCOUNT_SIZE)

    by_exit: dict[str, int] = {}
    for r in results:
        by_exit[r.exit_reason] = by_exit.get(r.exit_reason, 0) + 1

    print("\n" + "=" * 65)
    print(f"  BACKTEST REPORT  |  {symbol}  |  {strategy.upper()}  |  last {days} days")
    print("=" * 65)
    print(f"  Total trades:     {len(results)}")
    print(f"  Account size:     ${BACKTEST_ACCOUNT_SIZE:,.2f}")
    print(f"  Risk/trade cap:   {MAX_ACCOUNT_RISK_PCT:.1%}")
    print(f"  Slippage model:   {SLIPPAGE_PCT_OF_CREDIT:.1%} of entry credit")
    print(f"  Commission:       ${COMMISSION_PER_CONTRACT:.2f}/contract/side")
    print(f"  Wins / Losses:    {len(wins)} / {len(losses)}")
    print(f"  Win rate:         {win_rate:.1f}%")
    print(f"  Total P&L:        ${total_pnl:>+,.2f}")
    print(f"  Return:           {metrics.return_pct:>+.2f}%")
    print(f"  Profit factor:    {'inf' if math.isinf(metrics.profit_factor) else f'{metrics.profit_factor:.2f}'}")
    print(f"  Expectancy:       ${metrics.expectancy:>+,.2f}/trade")
    print(f"  Max drawdown:     ${metrics.max_drawdown:>-,.2f} ({metrics.max_drawdown_pct:.2f}%)")
    print(f"  Avg win:          ${avg_win:>+,.2f}")
    print(f"  Avg loss:         ${avg_loss:>+,.2f}")
    print(f"  Avg hold:         {avg_hold:.1f} days")
    print(f"  Worst trade:      ${worst_trade:>+,.2f}")
    print(f"  Max loss streak:  {metrics.max_consecutive_losses}")
    print(f"  Exit reasons:     {by_exit}")
    if skip_counts:
        top_skips = sorted(skip_counts.items(), key=lambda item: item[1], reverse=True)[:5]
        print(f"  Top skips:        {dict(top_skips)}")
    print("=" * 65)

    print("\n  SAMPLE TRADES (last 10):")
    for r in results[-10:]:
        print(f"    {r.entry_date} -> {r.exit_date}  "
              f"qty={r.qty}  credit={r.entry_credit:.3f}  close={r.exit_cost:.3f}  "
              f"P&L=${r.pnl:>+.2f}  ({r.exit_reason})")
    print()


def save_results(results: list[TradeResult]) -> None:
    with open(BACKTEST_LOG, "a", encoding="utf-8") as f:
        for r in results:
            f.write(json.dumps(asdict(r)) + "\n")
    print(f"Results appended to {BACKTEST_LOG}  ({len(results)} trades)")


def build_edge_trial(
    results: list[TradeResult],
    symbol: str,
    strategy: str,
    days: int,
) -> dict | None:
    """Create an in-sample trial record for immutable research accounting."""
    if not results:
        return None
    metrics = _metrics(results, BACKTEST_ACCOUNT_SIZE)
    profit_factor = None if math.isinf(metrics.profit_factor) else round(metrics.profit_factor, 4)
    return {
        "edge_id": f"options_{strategy}",
        "hypothesis": f"{strategy} on {symbol} has positive expectancy after modeled commissions and slippage.",
        "variant": symbol.upper(),
        "stage": "in_sample",
        "parameters": {
            "lookback_days": days,
            "account_size": BACKTEST_ACCOUNT_SIZE,
            "max_account_risk_pct": MAX_ACCOUNT_RISK_PCT,
            "slippage_pct_of_credit": SLIPPAGE_PCT_OF_CREDIT,
            "commission_per_contract": COMMISSION_PER_CONTRACT,
        },
        "dataset_start": min(result.entry_date[:10] for result in results),
        "dataset_end": max(result.exit_date[:10] for result in results),
        "cost_model": (
            f"commission_per_contract={COMMISSION_PER_CONTRACT};"
            f"slippage_pct_of_credit={SLIPPAGE_PCT_OF_CREDIT}"
        ),
        "metrics": {
            "in_sample_trade_count": len(results),
            "in_sample_total_pnl": metrics.total_pnl,
            "in_sample_expectancy": metrics.expectancy,
            "in_sample_profit_factor": profit_factor,
            "in_sample_max_drawdown": -metrics.max_drawdown,
            "in_sample_max_drawdown_pct": -metrics.max_drawdown_pct,
        },
        "source": "strategies/backtest.py",
        "code_version": os.getenv("VIBE_CODE_VERSION") or "working_tree",
    }


def record_edge_trial(trial: dict | None) -> dict | None:
    if trial is None:
        return None
    root = Path(__file__).resolve().parent.parent
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))
    try:
        from scripts.edge_trial_ledger import record_trial

        return record_trial(trial)
    except Exception as exc:
        print(f"WARNING: edge trial ledger write failed: {exc}")
        return None


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    ap = argparse.ArgumentParser(description="Options Bot Backtest Engine")
    ap.add_argument("--days", type=int, default=252, help="Calendar trading days to look back")
    ap.add_argument("--symbol", default="IWM",
                    help="Ticker symbol or 'all' for all configured symbols")
    ap.add_argument("--strategy", choices=["ps", "ic", "both"], default="ps",
                    help="Strategy to backtest: ps=put spread, ic=iron condor, both=run both")
    ap.add_argument("--report", action="store_true", default=True,
                    help="Print text report (default: on)")
    ap.add_argument("--no-report", dest="report", action="store_false")
    ap.add_argument("--save", action="store_true", default=True,
                    help="Append results to backtest.jsonl (default: on)")
    ap.add_argument("--no-save", dest="save", action="store_false")
    ap.add_argument("--no-ledger", action="store_true", help="Do not record this research trial in the immutable edge ledger")
    ap.add_argument("--account-size", type=float, default=None,
                    help="Override BACKTEST_ACCOUNT_SIZE / ACCOUNT_SIZE_OVERRIDE for this run")
    ap.add_argument("--risk-pct", type=float, default=None,
                    help="Override MAX_ACCOUNT_RISK_PCT for this run, e.g. 0.02")
    ap.add_argument("--slippage-pct", type=float, default=None,
                    help="Override BACKTEST_SLIPPAGE_PCT_OF_CREDIT for this run")
    args = ap.parse_args()

    global BACKTEST_ACCOUNT_SIZE, MAX_ACCOUNT_RISK_PCT, SLIPPAGE_PCT_OF_CREDIT
    if args.account_size is not None:
        BACKTEST_ACCOUNT_SIZE = args.account_size
    if args.risk_pct is not None:
        MAX_ACCOUNT_RISK_PCT = args.risk_pct
    if args.slippage_pct is not None:
        SLIPPAGE_PCT_OF_CREDIT = args.slippage_pct

    symbols = ALL_SYMBOLS if args.symbol.lower() == "all" else [args.symbol.upper()]
    strategies = ["ps", "ic"] if args.strategy == "both" else [args.strategy]

    all_results: list[TradeResult] = []
    for sym in symbols:
        for strat in strategies:
            if strat == "ic" and sym not in ("IWM", "TSLA"):
                continue
            results = run_backtest(sym, strat, args.days)
            all_results.extend(results)
            if not args.no_ledger:
                record_edge_trial(build_edge_trial(results, sym, strat, args.days))
            if args.report:
                print_report(results, sym, strat, args.days, getattr(run_backtest, "last_skip_counts", {}))

    if args.save and all_results:
        save_results(all_results)


if __name__ == "__main__":
    main()

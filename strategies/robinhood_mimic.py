#!/usr/bin/env python3
"""Robinhood execution constraints applied to Alpaca paper trading.

Enables Alpaca paper results to faithfully represent what would happen on a
real Robinhood account. Import in flip_bot.py and gate run_entry with
pdt_blocker() before submitting orders.

Key constraints modeled:
  1. PDT rule — under $25k account: max 3 day trades per rolling 5 business days
  2. Regulatory fee — $0.03 per contract (SEC + FINRA, same as Robinhood)
  3. No pre-market option execution (not modeled here; flip bot already gates on market hours)
  4. No conditional orders — exits managed by monitor loop only (already how bot works)

Day trade definition (FINRA Rule 4210):
  A day trade is the opening and closing of the same options position
  on the same calendar day.
"""
from __future__ import annotations

from datetime import date, timedelta
from typing import Any

PDT_THRESHOLD_DOLLARS = 25_000.0
PDT_MAX_DAY_TRADES = 3
PDT_ROLLING_BUSINESS_DAYS = 5
REGULATORY_FEE_PER_CONTRACT = 0.03  # SEC + FINRA combined


def _business_days_back(ref: date, n: int) -> date:
    """Return the date that is n business days before ref (inclusive window start)."""
    d = ref
    counted = 0
    while counted < n:
        d -= timedelta(days=1)
        if d.weekday() < 5:  # Mon-Fri
            counted += 1
    return d


def count_day_trades_in_window(trades: list[dict[str, Any]], ref: date | None = None) -> list[date]:
    """Return list of calendar dates that were day-trade events within rolling 5 business days.

    A day trade = entry_date and exit_date on same calendar day.
    Window = [window_start, ref] inclusive where window_start is 5 business days back from ref.
    """
    ref = ref or date.today()
    window_start = _business_days_back(ref, PDT_ROLLING_BUSINESS_DAYS)
    day_trade_dates: list[date] = []
    for trade in trades:
        if trade.get("status") != "closed":
            continue
        entry_raw = str(trade.get("entry_date") or "")[:10]
        exit_raw = str(trade.get("exit_date") or "")[:10]
        if not entry_raw or not exit_raw:
            continue
        try:
            entry_d = date.fromisoformat(entry_raw)
            exit_d = date.fromisoformat(exit_raw)
        except ValueError:
            continue
        if entry_d != exit_d:
            continue  # not a day trade (multi-day hold)
        if window_start <= entry_d <= ref:
            day_trade_dates.append(entry_d)
    return day_trade_dates


def pdt_blocker(
    trades: list[dict[str, Any]],
    account_size: float,
    ref: date | None = None,
) -> dict[str, Any] | None:
    """Return a blocker dict if this entry would be the 4th+ day trade for a sub-$25k account.

    Returns None if entry is allowed.
    Returns dict with blocker details if PDT limit would be exceeded.

    Usage in run_entry:
        blocker = pdt_blocker(all_trades, account_size)
        if blocker:
            log.warning(f"PDT BLOCKED: {blocker}")
            return
    """
    if account_size >= PDT_THRESHOLD_DOLLARS:
        return None  # PDT rule does not apply

    ref = ref or date.today()
    day_trade_dates = count_day_trades_in_window(trades, ref)
    used = len(day_trade_dates)

    if used >= PDT_MAX_DAY_TRADES:
        window_start = _business_days_back(ref, PDT_ROLLING_BUSINESS_DAYS)
        return {
            "blocker": "pdt_limit_reached",
            "account_size": account_size,
            "pdt_threshold": PDT_THRESHOLD_DOLLARS,
            "day_trades_used": used,
            "day_trades_max": PDT_MAX_DAY_TRADES,
            "rolling_window_start": window_start.isoformat(),
            "rolling_window_end": ref.isoformat(),
            "day_trade_dates": sorted(d.isoformat() for d in day_trade_dates),
            "note": (
                f"Robinhood mimic: {used}/{PDT_MAX_DAY_TRADES} day trades used "
                f"in rolling 5-business-day window. Entry would be flagged as 4th day trade "
                f"and account restricted. Under ${PDT_THRESHOLD_DOLLARS:,.0f} = PDT applies."
            ),
        }
    return None


def pdt_remaining(
    trades: list[dict[str, Any]],
    account_size: float,
    ref: date | None = None,
) -> dict[str, Any]:
    """Return PDT capacity summary for status/reporting."""
    ref = ref or date.today()
    if account_size >= PDT_THRESHOLD_DOLLARS:
        return {
            "pdt_applies": False,
            "account_size": account_size,
            "note": f"Account >= ${PDT_THRESHOLD_DOLLARS:,.0f}; no PDT restriction.",
        }
    day_trade_dates = count_day_trades_in_window(trades, ref)
    used = len(day_trade_dates)
    remaining = max(0, PDT_MAX_DAY_TRADES - used)
    window_start = _business_days_back(ref, PDT_ROLLING_BUSINESS_DAYS)
    return {
        "pdt_applies": True,
        "account_size": account_size,
        "pdt_threshold": PDT_THRESHOLD_DOLLARS,
        "day_trades_used": used,
        "day_trades_remaining": remaining,
        "day_trades_max": PDT_MAX_DAY_TRADES,
        "rolling_window_start": window_start.isoformat(),
        "rolling_window_end": ref.isoformat(),
        "day_trade_dates": sorted(d.isoformat() for d in day_trade_dates),
        "blocked": remaining == 0,
    }


def regulatory_fee(contracts: int) -> float:
    """Return total SEC + FINRA regulatory fee for a given contract count.

    Robinhood passes this through at $0.03/contract. Not commission — it's
    a pass-through regulatory cost on the closing leg only (standard practice).
    Always rounds up to nearest cent.
    """
    return round(contracts * REGULATORY_FEE_PER_CONTRACT, 2)


def adjusted_pnl(gross_pnl: float, contracts: int) -> float:
    """Return P&L after Robinhood regulatory fee deduction."""
    return round(gross_pnl - regulatory_fee(contracts), 2)

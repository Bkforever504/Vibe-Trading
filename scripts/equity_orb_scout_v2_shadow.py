#!/usr/bin/env python3
"""Frozen Equity ORB Scout v2 shadow scanner (A+ filters).

Observes the exact `equity-orb-scout-v2` candidate specified in
`research/preregistrations/equity_orb_scout_v2.md`. Adds six selectivity
filters and a re-weighted grade formula on top of the v1 scout baseline:
daily 20-EMA trend, relative strength vs SPY, earnings blackout, macro veto,
sector rotation confirmation, time-of-day EV weight. Also adds an alternate
gap-and-go entry path.

Scout v1 continues to shadow-log in parallel for A/B comparison. Both remain
`promotion_eligible=false` on yfinance proxy quotes.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import warnings
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from typing import Any, Mapping
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

STRATEGY_ID = "equity-orb-scout-v2"
FAMILY_ID = "equity-orb-scout"
SPEC_HASH = "sha256:9fc403eecaa1b50b0f8742fa7fad5e90a40d50ffaee7bb7b2ea6d748d130a51e"
SPEC_PATH = "research/preregistrations/equity_orb_scout_v2.md"
UNIVERSE_PATH = ROOT / "data" / "universes" / "equity_scout_v1_membership_2026-08-23.json"
LOG_PATH = ROOT / "data" / "equity_orb_scout_v2_shadow_log.jsonl"

ET = ZoneInfo("America/New_York")

BREAKOUT_BUFFER = 0.001
RVOL_MIN = 1.5
RVOL_LOOKBACK_SESSIONS = 5
TRIGGER_START = time(9, 45)
TRIGGER_END = time(10, 30)
TIME_EXIT = time(15, 55)
BREAK_EVEN_R = 0.5
BREAK_EVEN_MIN_AFTER = timedelta(minutes=15)
COMMISSION_PER_SHARE = 0.005
SLIPPAGE_PER_SIDE = 0.01
QUANTITY = 1
TOP_N_DASHBOARD = 20
DASHBOARD_GRADE_FLOOR = 0.55

EMA_PERIOD_DAILY = 20
RS_LOOKBACK_DAYS = 5
RS_MIN_ABS = 0.005
GAP_GO_MIN_PCT = 0.02
GAP_GO_VOL_MULT = 2.0
EARNINGS_WORKERS = 8
SECTOR_ETFS = {
    "tech": "XLK",
    "consumer_disc": "XLY",
    "communication": "XLC",
    "consumer_staples": "XLP",
    "financials": "XLF",
    "healthcare": "XLV",
    "industrials": "XLI",
    "energy": "XLE",
    "utilities": "XLU",
    "materials": "XLB",
    "real_estate": "XLRE",
}


# ---------------------------------------------------------------------------
# Universe loader (validates hash)
# ---------------------------------------------------------------------------

def load_universe(path: Path = UNIVERSE_PATH) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8-sig"))
    required = ("universe_id", "universe_version", "sha256_membership_hash", "membership_as_of", "symbols")
    for key in required:
        if key not in payload:
            raise ValueError(f"universe_membership_missing_{key}")
    symbols = payload["symbols"]
    if not isinstance(symbols, list) or not symbols:
        raise ValueError("universe_membership_symbols_invalid")
    canonical = "\n".join(sorted(set(str(s).upper() for s in symbols))) + "\n"
    computed = "sha256:" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    if len(symbols) != len(set(symbols)) or payload.get("symbol_count") != len(symbols):
        raise ValueError("universe_membership_count_or_uniqueness_mismatch")
    if payload["sha256_membership_hash"] != computed:
        raise ValueError("universe_membership_hash_mismatch")
    return payload


# ---------------------------------------------------------------------------
# Data loaders (yfinance proxy; executable NBBO required for promotion)
# ---------------------------------------------------------------------------

def _yf_download(symbols: list[str], *, period: str, interval: str, prepost: bool = False) -> Any:
    import yfinance as yf

    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        return yf.download(
            symbols,
            period=period,
            interval=interval,
            auto_adjust=False,
            prepost=prepost,
            progress=False,
            group_by="ticker",
            threads=True,
        )


def download_bars_1m(symbols: list[str], period: str = "5d") -> Any:
    return _yf_download(symbols, period=period, interval="1m")


def download_bars_5m(symbols: list[str], period: str = "10d") -> Any:
    return _yf_download(symbols, period=period, interval="5m")


def download_bars_daily(symbols: list[str], period: str = "90d") -> Any:
    return _yf_download(symbols, period=period, interval="1d")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def utc_now_z(instant: datetime | None = None) -> str:
    return (instant or datetime.now(timezone.utc)).astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _to_et(frame: Any) -> Any:
    import pandas as pd

    frame = frame.sort_index()
    if not isinstance(frame.index, pd.DatetimeIndex):
        raise TypeError("market data must use a DatetimeIndex")
    if frame.index.tz is None:
        frame.index = frame.index.tz_localize("America/New_York")
    else:
        frame.index = frame.index.tz_convert("America/New_York")
    return frame


def _symbol_frame(bundle: Any, symbol: str) -> Any:
    if hasattr(bundle, "columns") and hasattr(bundle.columns, "levels"):
        try:
            return bundle[symbol].dropna(how="all")
        except KeyError:
            return None
    return bundle


def _records(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8-sig").splitlines():
        if line.strip():
            rows.append(json.loads(line))
    return rows


def _append_record(record: dict[str, Any], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(record, separators=(",", ":"), sort_keys=True) + "\n")


def _replace_records(rows: list[dict[str, Any]], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(
        "".join(json.dumps(r, separators=(",", ":"), sort_keys=True) + "\n" for r in rows),
        encoding="utf-8",
    )
    os.replace(tmp, path)


def _base_record(event_type: str, as_of: datetime, universe: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "event_type": event_type,
        "type": event_type,
        "captured_at": utc_now_z(as_of),
        "timestamp": utc_now_z(as_of),
        "preregistration": SPEC_PATH,
        "spec_hash": SPEC_HASH,
        "strategy_id": STRATEGY_ID,
        "candidate_id": STRATEGY_ID,
        "family_id": FAMILY_ID,
        "setup_family": FAMILY_ID,
        "universe_id": universe["universe_id"],
        "universe_version": universe["universe_version"],
        "universe_hash": universe["sha256_membership_hash"],
        "membership_as_of": universe["membership_as_of"],
        "data_source": "yfinance_proxy_multi_symbol_1m_5m_daily",
        "evidence_tier": "proxy_ohlcv_non_executable",
        "promotion_eligible": False,
        "evidence_blockers": [
            "executable_nbbo_quotes_required",
            "kenny_signoff_required",
        ],
        "execution_mode": "shadow_only",
        "execution_enabled": False,
        "can_submit_orders": False,
    }


# ---------------------------------------------------------------------------
# Filter helpers
# ---------------------------------------------------------------------------

def _macro_high_impact_today(day: date) -> tuple[bool, list[str]]:
    try:
        from scripts.market_catalyst_calendar import events_for_date
    except Exception:
        return True, ["macro_calendar_unavailable"]
    events = events_for_date(day) or []
    hits: list[str] = []
    for event in events:
        if str(event.get("impact", "")).lower() != "high":
            continue
        et = str(event.get("time_et", ""))
        try:
            hh, mm = et.split(":")
            release = time(int(hh), int(mm))
        except (ValueError, AttributeError):
            release = time(12, 0)
        if time(9, 30) <= release <= time(15, 30):
            hits.append(str(event.get("name", "")))
    return bool(hits), hits


def _ema(values: list[float], period: int) -> float | None:
    if len(values) < period:
        return None
    k = 2.0 / (period + 1)
    ema = sum(values[:period]) / period
    for v in values[period:]:
        ema = v * k + ema * (1 - k)
    return ema


def _daily_closes(bars_daily_bundle: Any, symbol: str, session_date: date) -> list[float]:
    frame = _symbol_frame(bars_daily_bundle, symbol)
    if frame is None or frame.empty:
        return []
    frame = frame.sort_index()
    closes = []
    for ts, row in frame.iterrows():
        day_val = ts.date() if hasattr(ts, "date") else ts
        if day_val >= session_date:
            continue
        c = row.get("Close")
        if c == c:  # not NaN
            closes.append(float(c))
    return closes


def _ema_trend(bars_daily_bundle: Any, symbol: str, session_date: date) -> dict[str, Any]:
    closes = _daily_closes(bars_daily_bundle, symbol, session_date)
    ema = _ema(closes, EMA_PERIOD_DAILY)
    if ema is None or not closes:
        return {"ema20": None, "prior_close": None, "trend": None}
    prior = closes[-1]
    trend = "up" if prior > ema else ("down" if prior < ema else "flat")
    return {"ema20": round(ema, 4), "prior_close": round(prior, 4), "trend": trend}


def _rel_strength_vs_spy(
    bars_daily_bundle: Any, symbol: str, session_date: date, lookback: int = RS_LOOKBACK_DAYS
) -> float | None:
    sym_closes = _daily_closes(bars_daily_bundle, symbol, session_date)
    spy_closes = _daily_closes(bars_daily_bundle, "SPY", session_date)
    if len(sym_closes) <= lookback or len(spy_closes) <= lookback:
        return None
    sym_ret = sym_closes[-1] / sym_closes[-lookback - 1] - 1.0
    spy_ret = spy_closes[-1] / spy_closes[-lookback - 1] - 1.0
    return sym_ret - spy_ret


def _fetch_earnings_blackout(symbol: str, session_date: date) -> tuple[bool, str]:
    """Check today/tomorrow earnings via yfinance ticker.calendar. Best-effort."""
    try:
        import yfinance as yf

        tk = yf.Ticker(symbol)
        cal = getattr(tk, "calendar", None)
        if cal is None:
            return True, "earnings_calendar_unavailable"
        # calendar may be dict or DataFrame depending on version
        earnings_date = None
        if isinstance(cal, dict):
            earnings_date = cal.get("Earnings Date")
            if isinstance(earnings_date, list) and earnings_date:
                earnings_date = earnings_date[0]
        else:  # DataFrame path
            try:
                earnings_date = cal.loc["Earnings Date"].iloc[0]
            except Exception:
                earnings_date = None
        if earnings_date is None:
            return False, "no_earnings_scheduled"
        if isinstance(earnings_date, str):
            try:
                earnings_date = date.fromisoformat(earnings_date[:10])
            except ValueError:
                return False, "earnings_date_unparseable"
        elif hasattr(earnings_date, "date"):
            earnings_date = earnings_date.date()
        if not isinstance(earnings_date, date):
            return False, "earnings_date_unrecognized"
        delta_days = (earnings_date - session_date).days
        if delta_days in (0, 1):
            return True, f"earnings_in_{delta_days}d"
        return False, "earnings_out_of_window"
    except Exception as exc:
        return True, f"earnings_lookup_error:{str(exc)[:80]}"


_EARNINGS_CACHE: dict[tuple[str, str], tuple[bool, str]] = {}


def _earnings_blackout(symbol: str, session_date: date) -> tuple[bool, str]:
    key = (symbol, session_date.isoformat())
    if key not in _EARNINGS_CACHE:
        _EARNINGS_CACHE[key] = _fetch_earnings_blackout(symbol, session_date)
    return _EARNINGS_CACHE[key]


def _prefetch_earnings(symbols: list[str], session_date: date) -> None:
    """Bound the universe earnings lookup with a small concurrent worker pool."""
    missing = [symbol for symbol in symbols if (symbol, session_date.isoformat()) not in _EARNINGS_CACHE]
    if not missing:
        return
    with ThreadPoolExecutor(max_workers=min(EARNINGS_WORKERS, len(missing))) as pool:
        futures = {pool.submit(_fetch_earnings_blackout, symbol, session_date): symbol for symbol in missing}
        for future in as_completed(futures):
            symbol = futures[future]
            try:
                result = future.result()
            except Exception as exc:
                result = (True, f"earnings_lookup_error:{str(exc)[:80]}")
            _EARNINGS_CACHE[(symbol, session_date.isoformat())] = result


_SECTOR_CACHE: dict[str, dict[str, Any]] | None = None


def _load_sector_ranks() -> dict[str, dict[str, Any]] | None:
    global _SECTOR_CACHE
    if _SECTOR_CACHE is not None:
        return _SECTOR_CACHE
    report_path = Path.home() / ".vibe-trading" / "reports" / "sector-rotation.json"
    try:
        payload = json.loads(report_path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        return None
    ranks = payload.get("sector_ranks") or payload.get("ranks") or {}
    _SECTOR_CACHE = ranks if isinstance(ranks, dict) else None
    return _SECTOR_CACHE


_SYMBOL_TO_SECTOR: dict[str, str] = {
    # ETFs
    "SPY": "index", "QQQ": "index", "IWM": "index",
    # Tech
    "AAPL": "tech", "NVDA": "tech", "MSFT": "tech", "GOOGL": "tech", "GOOG": "tech",
    "META": "tech", "AMD": "tech", "AVGO": "tech", "ORCL": "tech", "CRM": "tech",
    "ADBE": "tech", "CSCO": "tech", "INTC": "tech", "QCOM": "tech", "TXN": "tech",
    "AMAT": "tech", "ADI": "tech", "ANET": "tech", "CDNS": "tech", "APH": "tech",
    "IBM": "tech", "SMCI": "tech", "PLTR": "tech", "PYPL": "tech", "ACN": "tech",
    # Consumer
    "AMZN": "consumer_disc", "TSLA": "consumer_disc", "HD": "consumer_disc",
    "MCD": "consumer_disc", "NKE": "consumer_disc", "SBUX": "consumer_disc",
    "LOW": "consumer_disc", "BKNG": "consumer_disc", "TGT": "consumer_disc",
    "F": "consumer_disc", "GM": "consumer_disc", "UBER": "consumer_disc",
    "NFLX": "communication", "DIS": "communication", "CMCSA": "communication",
    "T": "communication", "VZ": "communication", "TMUS": "communication",
    "CHTR": "communication", "PM": "consumer_staples", "MO": "consumer_staples",
    "KO": "consumer_staples", "PEP": "consumer_staples", "COST": "consumer_staples",
    "WMT": "consumer_staples", "PG": "consumer_staples", "CL": "consumer_staples",
    "MDLZ": "consumer_staples", "KHC": "consumer_staples",
    # Financials
    "JPM": "financials", "BAC": "financials", "WFC": "financials", "C": "financials",
    "GS": "financials", "MS": "financials", "AXP": "financials", "BLK": "financials",
    "SCHW": "financials", "USB": "financials", "V": "financials", "MA": "financials",
    "COIN": "financials", "APO": "financials", "BX": "financials", "BK": "financials",
    "CB": "financials", "MET": "financials", "AIG": "financials", "ALL": "financials",
    "SPG": "financials", "AMT": "financials",
    # Healthcare
    "JNJ": "healthcare", "UNH": "healthcare", "LLY": "healthcare", "PFE": "healthcare",
    "MRK": "healthcare", "ABBV": "healthcare", "BMY": "healthcare", "AMGN": "healthcare",
    "GILD": "healthcare", "MDT": "healthcare", "TMO": "healthcare", "DHR": "healthcare",
    "CVS": "healthcare", "ZTS": "healthcare",
    # Industrials
    "BA": "industrials", "GE": "industrials", "CAT": "industrials", "DE": "industrials",
    "HON": "industrials", "UPS": "industrials", "FDX": "industrials", "MMM": "industrials",
    "RTX": "industrials", "LMT": "industrials", "GD": "industrials", "UNP": "industrials",
    "EMR": "industrials", "ADP": "industrials", "CTAS": "industrials",
    # Energy / Materials
    "XOM": "energy", "CVX": "energy", "COP": "energy", "OXY": "energy", "KMI": "energy",
    "DUK": "utilities", "SO": "utilities", "NEE": "utilities", "EXC": "utilities",
    "DOW": "materials", "LIN": "materials", "APD": "materials",
    # Berkshire / conglomerates
    "BRK-B": "financials",
}


def _sector_component(symbol: str, direction: str) -> float:
    ranks = _load_sector_ranks() or {}
    sector = _SYMBOL_TO_SECTOR.get(symbol, "unknown")
    if sector in ("index", "unknown") or not ranks:
        return 0.5
    entry = ranks.get(sector)
    if not isinstance(entry, dict):
        return 0.5
    rank = entry.get("rank")
    total = entry.get("total") or 11
    if not isinstance(rank, int) or total <= 0:
        return 0.5
    # top-2 = 1.0, bottom-2 = 0.0, else 0.5
    if direction == "long":
        if rank <= 2:
            return 1.0
        if rank >= total - 1:
            return 0.0
        return 0.5
    else:  # short
        if rank >= total - 1:
            return 1.0
        if rank <= 2:
            return 0.0
        return 0.5


def _sector_gate(symbol: str, direction: str) -> bool:
    """Reject if long in bottom-2 sector or short in top-2 sector."""
    ranks = _load_sector_ranks() or {}
    sector = _SYMBOL_TO_SECTOR.get(symbol, "unknown")
    if sector == "index":
        return True
    if sector == "unknown" or not ranks:
        return False
    entry = ranks.get(sector)
    if not isinstance(entry, dict):
        return False
    rank = entry.get("rank")
    total = entry.get("total") or 11
    if not isinstance(rank, int) or total <= 0:
        return True
    if direction == "long" and rank >= total - 1:
        return False
    if direction == "short" and rank <= 2:
        return False
    return True


def _sector_ranks_from_daily(bars_daily_bundle: Any, session_date: date) -> dict[str, dict[str, Any]]:
    returns: list[tuple[str, float]] = []
    for sector, etf in SECTOR_ETFS.items():
        closes = _daily_closes(bars_daily_bundle, etf, session_date)
        if len(closes) < 6 or closes[-6] <= 0:
            continue
        returns.append((sector, closes[-1] / closes[-6] - 1.0))
    if len(returns) != len(SECTOR_ETFS):
        return {}
    returns.sort(key=lambda item: item[1], reverse=True)
    total = len(returns)
    return {
        sector: {
            "rank": index,
            "total": total,
            "return_5d": round(value, 6),
            "source": SECTOR_ETFS[sector],
        }
        for index, (sector, value) in enumerate(returns, 1)
    }


def _time_weight(bar_time: time) -> float:
    if bar_time < time(10, 15):
        return 1.0
    return 0.85


# ---------------------------------------------------------------------------
# Session slicing + opening range
# ---------------------------------------------------------------------------

def _session_slice(frame: Any, session_date: date, start: str, end: str) -> Any:
    frame = _to_et(frame)
    day_rows = frame[frame.index.date == session_date]
    return day_rows.between_time(start, end)


def _opening_range(bars_1m: Any, session_date: date) -> tuple[float, float] | None:
    rows = _session_slice(bars_1m, session_date, "09:30", "09:44")
    if rows.empty or "High" not in rows or "Low" not in rows:
        return None
    return float(rows["High"].max()), float(rows["Low"].min())


def _rvol_baseline(bars_5m: Any, session_date: date, bar_start: time) -> float | None:
    frame = _to_et(bars_5m)
    prior = sorted({d for d in frame.index.date if d < session_date})[-RVOL_LOOKBACK_SESSIONS:]
    if len(prior) < 3:
        return None
    key = bar_start.strftime("%H:%M")
    vols: list[float] = []
    for d in prior:
        window = frame[frame.index.date == d].between_time(key, key)
        if window.empty:
            continue
        vols.append(float(window["Volume"].iloc[0]))
    if not vols:
        return None
    return sum(vols) / len(vols)


def _session_vwap_at(bars_1m: Any, session_date: date, up_to: datetime) -> float | None:
    rth = _session_slice(bars_1m, session_date, "09:30", "16:00")
    rth = rth[rth.index <= up_to]
    if rth.empty:
        return None
    typical = (rth["High"] + rth["Low"] + rth["Close"]) / 3.0
    vol = rth["Volume"].astype(float)
    denom = vol.sum()
    if denom <= 0:
        return None
    return float((typical * vol).sum() / denom)


# ---------------------------------------------------------------------------
# Setup detection (primary ORB + alternate gap-and-go)
# ---------------------------------------------------------------------------

def build_symbol_plan(
    symbol: str,
    bars_1m_bundle: Any,
    bars_5m_bundle: Any,
    bars_daily_bundle: Any,
    session_date: date,
    *,
    macro_blocked: bool,
    macro_events: list[str],
) -> dict[str, Any]:
    bars_1m = _symbol_frame(bars_1m_bundle, symbol)
    bars_5m = _symbol_frame(bars_5m_bundle, symbol)
    if bars_1m is None or bars_5m is None or bars_1m.empty or bars_5m.empty:
        return {"symbol": symbol, "should_enter": False, "reason": "no_data"}

    if macro_blocked:
        return {
            "symbol": symbol,
            "should_enter": False,
            "reason": "macro_high_impact_today",
            "macro_events": macro_events,
        }

    ema_ctx = _ema_trend(bars_daily_bundle, symbol, session_date)
    rs_val = _rel_strength_vs_spy(bars_daily_bundle, symbol, session_date)

    opening = _opening_range(bars_1m, session_date)
    if opening is None:
        return {"symbol": symbol, "should_enter": False, "reason": "opening_range_unavailable"}
    or_high, or_low = opening
    or_width = or_high - or_low
    if or_width <= 0:
        return {"symbol": symbol, "should_enter": False, "reason": "opening_range_zero_width"}

    # ---- Primary ORB path ----
    triggers = _session_slice(bars_5m, session_date, "09:45", "10:29")
    trigger = None
    for ts, row in triggers.iterrows():
        bar_time = ts.time()
        if bar_time < TRIGGER_START or bar_time >= TRIGGER_END:
            continue
        close = float(row["Close"])
        volume = float(row["Volume"])
        long_lvl = or_high * (1 + BREAKOUT_BUFFER)
        short_lvl = or_low * (1 - BREAKOUT_BUFFER)
        direction = "long" if close >= long_lvl else ("short" if close <= short_lvl else None)
        if direction is None:
            continue
        vwap = _session_vwap_at(bars_1m, session_date, ts)
        vwap_pass = bool(vwap is not None and ((direction == "long" and close > vwap) or (direction == "short" and close < vwap)))
        baseline = _rvol_baseline(bars_5m, session_date, bar_time)
        rvol = (volume / baseline) if baseline and baseline > 0 else None
        rvol_pass = bool(rvol is not None and rvol >= RVOL_MIN)
        trigger = {
            "path": "orb",
            "bar_open_et": bar_time.strftime("%H:%M"),
            "trigger_timestamp": ts.isoformat(),
            "close": close,
            "volume": volume,
            "direction": direction,
            "rvol": rvol,
            "rvol_baseline": baseline,
            "rvol_pass": rvol_pass,
            "vwap": vwap,
            "vwap_pass": vwap_pass,
            "time_weight": _time_weight(bar_time),
        }
        break

    # ---- Alternate: gap-and-go ----
    gap_trigger = None
    daily_closes = _daily_closes(bars_daily_bundle, symbol, session_date)
    if daily_closes:
        prior_close = daily_closes[-1]
        open_bar = _session_slice(bars_1m, session_date, "09:30", "09:34")
        if not open_bar.empty and prior_close > 0:
            first_bar_close = float(open_bar["Close"].iloc[-1])
            first_bar_open = float(open_bar["Open"].iloc[0])
            first_bar_low = float(open_bar["Low"].min())
            first_bar_high = float(open_bar["High"].max())
            first_bar_volume = float(open_bar["Volume"].sum())
            gap_pct = (first_bar_open - prior_close) / prior_close
            if abs(gap_pct) >= GAP_GO_MIN_PCT:
                # Volume baseline: prior 20-day 09:30-09:35 5m first-bar average
                frame_5m_et = _to_et(bars_5m)
                prior_first_bars = []
                for d in sorted({dd for dd in frame_5m_et.index.date if dd < session_date})[-20:]:
                    w = frame_5m_et[frame_5m_et.index.date == d].between_time("09:30", "09:30")
                    if not w.empty:
                        prior_first_bars.append(float(w["Volume"].iloc[0]))
                vol_avg = sum(prior_first_bars) / len(prior_first_bars) if prior_first_bars else None
                vol_pass = bool(vol_avg and first_bar_volume >= GAP_GO_VOL_MULT * vol_avg)
                direction = None
                if gap_pct >= GAP_GO_MIN_PCT and first_bar_close >= first_bar_open:
                    direction = "long"
                elif gap_pct <= -GAP_GO_MIN_PCT and first_bar_close <= first_bar_open:
                    direction = "short"
                if direction and vol_pass:
                    gap_trigger = {
                        "path": "gap_and_go",
                        "bar_open_et": "09:30",
                        "trigger_timestamp": open_bar.index[-1].isoformat(),
                        "close": first_bar_close,
                        "volume": first_bar_volume,
                        "direction": direction,
                        "gap_pct": round(gap_pct, 4),
                        "vol_multiple": round(first_bar_volume / vol_avg, 3) if vol_avg else None,
                        "vwap": None,
                        "vwap_pass": True,
                        "rvol": round(first_bar_volume / vol_avg, 3) if vol_avg else None,
                        "rvol_pass": True,
                        "time_weight": 1.10,
                        "first_bar_high": first_bar_high,
                        "first_bar_low": first_bar_low,
                    }

    # Prefer gap-and-go when both exist (bigger displacement day) — earlier fill
    chosen = gap_trigger or trigger
    if chosen is None:
        return {
            "symbol": symbol,
            "should_enter": False,
            "reason": "no_qualifying_trigger",
            "opening_range": {"high": or_high, "low": or_low, "width": or_width},
            "ema_trend": ema_ctx,
            "rel_strength_vs_spy": rs_val,
        }

    direction = chosen["direction"]

    # ---- Filters ----
    reasons: list[str] = []
    if not chosen.get("rvol_pass"):
        reasons.append("rvol_below_min")
    if not chosen.get("vwap_pass"):
        reasons.append("vwap_misaligned")

    ema_pass = False
    if ema_ctx["trend"] is None:
        reasons.append("ema20_unavailable")
    elif direction == "long" and ema_ctx["trend"] != "up":
        reasons.append("ema20_trend_not_up")
    elif direction == "short" and ema_ctx["trend"] != "down":
        reasons.append("ema20_trend_not_down")
    else:
        ema_pass = True

    if rs_val is None:
        reasons.append("rs_vs_spy_unavailable")
    elif direction == "long" and rs_val < RS_MIN_ABS:
        reasons.append(f"rs_vs_spy_weak_{rs_val:.4f}")
    elif direction == "short" and rs_val > -RS_MIN_ABS:
        reasons.append(f"rs_vs_spy_weak_{rs_val:.4f}")

    earn_blocked, earn_reason = _earnings_blackout(symbol, session_date)
    if earn_blocked:
        reasons.append(f"earnings:{earn_reason}")

    if not _sector_gate(symbol, direction):
        reasons.append("sector_rank_gate")

    # ---- Plan geometry ----
    entry_price = float(chosen["close"])
    if chosen["path"] == "gap_and_go":
        if direction == "long":
            stop_price = float(chosen["first_bar_low"]) - 0.01
        else:
            stop_price = float(chosen["first_bar_high"]) + 0.01
        stop_distance = abs(entry_price - stop_price)
        t1_price = entry_price + stop_distance if direction == "long" else entry_price - stop_distance
        t2_price = entry_price + 2 * stop_distance if direction == "long" else entry_price - 2 * stop_distance
    else:
        if direction == "long":
            stop_price = or_low - 0.01
            t1_price = entry_price + or_width
            t2_price = entry_price + 2.0 * or_width
        else:
            stop_price = or_high + 0.01
            t1_price = entry_price - or_width
            t2_price = entry_price - 2.0 * or_width
        stop_distance = abs(entry_price - stop_price)
    max_risk = stop_distance

    # ---- Grade v2 ----
    rvol_component = min(chosen.get("rvol") or 0.0, 5.0) / 5.0
    displacement_pct = abs(entry_price - (or_high if direction == "long" else or_low)) / entry_price if entry_price else 0.0
    displacement_component = min(displacement_pct * 200.0, 1.0)
    vwap_component = 1.0 if chosen.get("vwap_pass") else 0.0
    rs_component = 0.0
    if rs_val is not None:
        raw = rs_val if direction == "long" else -rs_val
        rs_component = max(0.0, min(raw / 0.02, 1.0))
    ema_component = 1.0 if ema_pass else 0.0
    sector_component = _sector_component(symbol, direction)
    time_component = chosen.get("time_weight", 1.0)

    grade = round(
        0.25 * rvol_component
        + 0.20 * displacement_component
        + 0.15 * vwap_component
        + 0.15 * rs_component
        + 0.10 * ema_component
        + 0.10 * sector_component
        + 0.05 * time_component,
        4,
    )

    plan = {
        "path": chosen["path"],
        "direction": direction,
        "entry_price": entry_price,
        "stop_price": stop_price,
        "t1_price": t1_price,
        "t2_price": t2_price,
        "stop_distance_pts": stop_distance,
        "max_risk_per_contract": max_risk,
        "opening_range": {"high": or_high, "low": or_low, "width": or_width},
        "trigger": chosen,
        "grade": grade,
        "grade_components": {
            "rvol": round(rvol_component, 4),
            "displacement": round(displacement_component, 4),
            "vwap": vwap_component,
            "rs": round(rs_component, 4),
            "ema": ema_component,
            "sector": sector_component,
            "time": time_component,
        },
        "ema_trend": ema_ctx,
        "rel_strength_vs_spy": rs_val,
        "sector": _SYMBOL_TO_SECTOR.get(symbol, "unknown"),
    }

    return {
        "symbol": symbol,
        "should_enter": not reasons,
        "reason": ";".join(reasons) or "eligible",
        "plan": plan,
    }


# ---------------------------------------------------------------------------
# Resolver (mirrors v1 logic; single-symbol replay of 1m bars to 15:55 ET)
# ---------------------------------------------------------------------------

def _bar_hit(low: float, high: float, target: float, direction_up: bool) -> bool:
    return (direction_up and high >= target) or ((not direction_up) and low <= target)


def resolve_symbol(bars_1m_bundle: Any, symbol: str, session_date: date, plan: Mapping[str, Any]) -> dict[str, Any]:
    bars_1m = _symbol_frame(bars_1m_bundle, symbol)
    if bars_1m is None or bars_1m.empty:
        raise ValueError("no_intraday_data_for_resolution")
    frame = _session_slice(bars_1m, session_date, "09:30", "15:55")
    trigger_ts = plan["trigger"]["trigger_timestamp"]
    forward = frame[frame.index > trigger_ts]
    if forward.empty:
        raise ValueError("no_post_trigger_bars")

    direction = plan["direction"]
    is_long = direction == "long"
    entry_price = float(plan["entry_price"])
    stop_price = float(plan["stop_price"])
    t1_price = float(plan["t1_price"])
    t2_price = float(plan["t2_price"])
    stop_distance = float(plan["stop_distance_pts"])
    trigger_dt = datetime.fromisoformat(trigger_ts)

    banked = 0.0
    remaining_open = True
    remaining_exit = 0.0
    t1_hit = False
    stop_dyn = stop_price
    exit_reason = "time_stop_15_55_et"
    exit_ts = None
    be_moved = False

    for ts, row in forward.iterrows():
        if not remaining_open:
            break
        low = float(row["Low"])
        high = float(row["High"])
        hit_stop = _bar_hit(low, high, stop_dyn, direction_up=not is_long)
        hit_t1 = (not t1_hit) and _bar_hit(low, high, t1_price, direction_up=is_long)
        hit_t2 = t1_hit and _bar_hit(low, high, t2_price, direction_up=is_long)

        if hit_stop:
            if not t1_hit:
                banked = 0.0
                remaining_exit = (stop_dyn - entry_price) if is_long else (entry_price - stop_dyn)
                exit_reason = "stop_before_t1"
            else:
                remaining_exit = (stop_dyn - entry_price) if is_long else (entry_price - stop_dyn)
                exit_reason = "trail_stop_after_t1"
            remaining_open = False
            exit_ts = ts
            break
        if hit_t1:
            banked = 0.5 * ((t1_price - entry_price) if is_long else (entry_price - t1_price))
            t1_hit = True
            stop_dyn = (entry_price + 0.01) if is_long else (entry_price - 0.01)
            be_moved = True
            if hit_t2:
                remaining_exit = 0.5 * ((t2_price - entry_price) if is_long else (entry_price - t2_price))
                remaining_open = False
                exit_reason = "t2_after_t1"
                exit_ts = ts
                break
            continue
        if hit_t2:
            remaining_exit = 0.5 * ((t2_price - entry_price) if is_long else (entry_price - t2_price))
            remaining_open = False
            exit_reason = "t2_full_exit"
            exit_ts = ts
            break

        mins = (ts - trigger_dt).total_seconds() / 60.0
        if not be_moved and not t1_hit and mins >= BREAK_EVEN_MIN_AFTER.total_seconds() / 60.0:
            unrealized = (high - entry_price) if is_long else (entry_price - low)
            if unrealized >= BREAK_EVEN_R * stop_distance:
                stop_dyn = entry_price
                be_moved = True

    if remaining_open:
        final_row = forward.iloc[-1]
        exit_price = float(final_row["Close"])
        remaining_exit = (exit_price - entry_price) if is_long else (entry_price - exit_price)
        if t1_hit:
            remaining_exit *= 0.5
        exit_reason = "time_stop_15_55_et"
        exit_ts = forward.index[-1]

    total_pts = banked + remaining_exit
    friction = 2 * SLIPPAGE_PER_SIDE + 2 * COMMISSION_PER_SHARE
    gross = total_pts * QUANTITY
    net = gross - friction * QUANTITY
    outcome = "win" if net > 0 else ("loss" if net < 0 else "flat")

    return {
        "exit_reason": exit_reason,
        "exit_timestamp": exit_ts.isoformat() if exit_ts is not None else None,
        "t1_hit": t1_hit,
        "banked_half_pts": round(banked, 4),
        "remaining_exit_pts": round(remaining_exit, 4),
        "total_pts": round(total_pts, 4),
        "gross_dollar": round(gross, 4),
        "friction_round_trip_dollar": round(friction, 4),
        "net_dollar": round(net, 4),
        "outcome": outcome,
    }


# ---------------------------------------------------------------------------
# Entrypoints (mirror v1 structure exactly)
# ---------------------------------------------------------------------------

def _plan_id(symbol: str, session_date: date) -> str:
    return f"{STRATEGY_ID}:{symbol}:{session_date.isoformat()}"


def _unsettled_entries_for_date(path: Path, session_date: date) -> list[dict[str, Any]]:
    return [
        row for row in _records(path)
        if row.get("event_type") == "entry"
        and row.get("session_date") == session_date.isoformat()
        and not row.get("settled")
    ]


def run_entry(*, as_of: datetime | None = None, log_path: Path = LOG_PATH) -> int:
    as_of = as_of or datetime.now(ET)
    session_date = as_of.astimezone(ET).date()
    universe = load_universe()
    macro_blocked, macro_events = _macro_high_impact_today(session_date)

    symbols = list(universe["symbols"])
    try:
        bars_1m = download_bars_1m(symbols)
        bars_5m = download_bars_5m(symbols)
        bars_daily = download_bars_daily(sorted(set(symbols + ["SPY", *SECTOR_ETFS.values()])))
    except Exception as exc:
        record = _base_record("universe_error", as_of, universe) | {
            "session_date": session_date.isoformat(),
            "reason": "market_data_incomplete",
            "error": str(exc)[:240],
        }
        _append_record(record, log_path)
        print(json.dumps(record, separators=(",", ":"), sort_keys=True))
        return 0

    global _SECTOR_CACHE
    _SECTOR_CACHE = _sector_ranks_from_daily(bars_daily, session_date)
    _prefetch_earnings(symbols, session_date)

    setups: list[dict[str, Any]] = []
    existing = {r.get("plan_id") for r in _records(log_path) if r.get("event_type") == "entry"}

    for symbol in symbols:
        pid = _plan_id(symbol, session_date)
        if pid in existing:
            continue
        try:
            decision = build_symbol_plan(
                symbol, bars_1m, bars_5m, bars_daily, session_date,
                macro_blocked=macro_blocked, macro_events=macro_events,
            )
        except Exception as exc:
            decision = {"symbol": symbol, "should_enter": False, "reason": f"error:{str(exc)[:120]}"}
        setups.append(decision)

    eligible = [s for s in setups if s.get("should_enter") and s.get("plan")]
    eligible.sort(key=lambda s: s["plan"]["grade"], reverse=True)

    for setup in setups:
        symbol = setup["symbol"]
        pid = _plan_id(symbol, session_date)
        plan = setup.get("plan")
        rec = _base_record("entry", as_of, universe) | {
            "plan_id": pid,
            "trade_key": pid,
            "symbol": symbol,
            "session_date": session_date.isoformat(),
            "should_enter": bool(setup.get("should_enter")),
            "reason": setup.get("reason", "unknown"),
            "settled": not setup.get("should_enter"),
        }
        if plan:
            rec["plan"] = plan
            rec["direction"] = plan["direction"]
            rec["path"] = plan["path"]
            rec["entry_price"] = plan["entry_price"]
            rec["entry_fill_executable"] = plan["entry_price"]
            rec["entry_ask"] = plan["entry_price"]
            rec["stop_price"] = plan["stop_price"]
            rec["t1_price"] = plan["t1_price"]
            rec["t2_price"] = plan["t2_price"]
            rec["max_risk_per_contract"] = plan["max_risk_per_contract"]
            rec["quantity"] = QUANTITY
            rec["effective_qty"] = QUANTITY
            rec["stop_distance_pts"] = plan["stop_distance_pts"]
            rec["grade"] = plan["grade"]
            rec["grade_below_floor"] = plan["grade"] < DASHBOARD_GRADE_FLOOR
            top_syms = [s["symbol"] for s in eligible[:TOP_N_DASHBOARD] if s["plan"]["grade"] >= DASHBOARD_GRADE_FLOOR]
            rec["dashboard_rank_in_top_n"] = (top_syms.index(symbol) + 1) if symbol in top_syms else None
        _append_record(rec, log_path)

    summary = {
        "event_type": "universe_summary",
        "session_date": session_date.isoformat(),
        "scanned": len(symbols),
        "setups_total": len(setups),
        "setups_eligible": len(eligible),
        "top_symbols": [
            {
                "symbol": s["symbol"],
                "grade": s["plan"]["grade"],
                "direction": s["plan"]["direction"],
                "path": s["plan"]["path"],
            }
            for s in eligible[:TOP_N_DASHBOARD]
            if s["plan"]["grade"] >= DASHBOARD_GRADE_FLOOR
        ],
    }
    print(json.dumps(summary, separators=(",", ":"), sort_keys=True))
    return 0


def run_resolve(*, as_of: datetime | None = None, log_path: Path = LOG_PATH) -> int:
    as_of = as_of or datetime.now(ET)
    session_date = as_of.astimezone(ET).date()
    universe = load_universe()
    open_entries = _unsettled_entries_for_date(log_path, session_date)
    if not open_entries:
        rec = _base_record("resolve_noop", as_of, universe) | {
            "session_date": session_date.isoformat(),
            "reason": "no_unsettled_entries_for_session",
        }
        _append_record(rec, log_path)
        print(json.dumps(rec, separators=(",", ":"), sort_keys=True))
        return 0

    open_symbols = sorted({e["symbol"] for e in open_entries if e.get("symbol")})
    try:
        bars_1m = download_bars_1m(open_symbols)
    except Exception as exc:
        rec = _base_record("resolve_error", as_of, universe) | {
            "session_date": session_date.isoformat(),
            "reason": "market_data_incomplete",
            "error": str(exc)[:240],
        }
        _append_record(rec, log_path)
        print(json.dumps(rec, separators=(",", ":"), sort_keys=True))
        return 0

    rows = _records(log_path)
    resolved: list[str] = []
    for entry in open_entries:
        symbol = entry.get("symbol")
        plan = entry.get("plan") or {}
        pid = entry.get("plan_id")
        if not symbol or not pid or not plan:
            terminal = _base_record("exit", as_of, universe) | {
                "plan_id": pid, "trade_key": pid, "symbol": symbol,
                "session_date": session_date.isoformat(),
                "resolved_at": utc_now_z(as_of), "reason": "no_actionable_plan", "settled": True,
            }
            rows.append(terminal)
            continue
        try:
            s = resolve_symbol(bars_1m, symbol, session_date, plan)
            max_risk = float(entry.get("max_risk_per_contract") or 0.0)
            outcome_r = (s["net_dollar"] / max_risk) if max_risk else None
            terminal = _base_record("exit", as_of, universe) | {
                "plan_id": pid, "trade_key": pid, "symbol": symbol,
                "session_date": session_date.isoformat(),
                "resolved_at": utc_now_z(as_of),
                "entry_price": entry.get("entry_price"),
                "entry_fill_executable": entry.get("entry_fill_executable"),
                "stop_price": entry.get("stop_price"),
                "t1_price": entry.get("t1_price"),
                "t2_price": entry.get("t2_price"),
                "exit_reason": s["exit_reason"], "reason": s["exit_reason"],
                "exit_timestamp": s["exit_timestamp"],
                "exit_fill_executable": None, "exit_price": None, "exit_bid": None,
                "outcome": s["outcome"], "outcome_r": outcome_r,
                "gross_dollar": s["gross_dollar"],
                "friction_round_trip_dollar": s["friction_round_trip_dollar"],
                "net_dollar": s["net_dollar"], "pnl_before_fees": s["gross_dollar"],
                "quantity": QUANTITY, "detail": s, "settled": True,
            }
        except Exception as exc:
            terminal = _base_record("exit", as_of, universe) | {
                "plan_id": pid, "trade_key": pid, "symbol": symbol,
                "session_date": session_date.isoformat(),
                "resolved_at": utc_now_z(as_of),
                "reason": "market_data_incomplete", "error": str(exc)[:240], "settled": True,
            }
        for row in rows:
            if row.get("event_type") == "entry" and row.get("plan_id") == pid:
                row["settled"] = True
        rows.append(terminal)
        resolved.append(symbol)

    _replace_records(rows, log_path)
    summary = {
        "event_type": "resolve_summary",
        "session_date": session_date.isoformat(),
        "resolved": len(resolved),
        "symbols": resolved,
    }
    print(json.dumps(summary, separators=(",", ":"), sort_keys=True))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=("entry", "resolve"), required=True)
    parser.add_argument("--log-path", type=Path, default=LOG_PATH)
    args = parser.parse_args()
    return run_entry(log_path=args.log_path) if args.mode == "entry" else run_resolve(log_path=args.log_path)


if __name__ == "__main__":
    raise SystemExit(main())

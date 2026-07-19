"""
Shared market data fetcher for shadow loggers.

Primary source: Alpaca market data API (official broker, proper SLA).
Fallback: yfinance (unofficial scraper, breaks when Yahoo changes API).

Shadow loggers should import from here. Research/backtest scripts can
continue using yfinance directly — this module is for operational code only.

Keys loaded from agent/.env (ALPACA_API_KEY, ALPACA_SECRET_KEY).
Alpaca free tier covers all needed symbols: QQQ, SPY, GLD, IWM, XLK, etc.
Daily bars use adjustment='all' (split + dividend adjusted) to match yfinance
auto_adjust=True behavior.
"""
from __future__ import annotations

import os
import urllib.request
import warnings
from datetime import date, datetime, timedelta
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
_ENV_PATH = ROOT / "agent" / ".env"

_ALPACA_KEY: str | None = None
_ALPACA_SECRET: str | None = None


def _load_env() -> None:
    global _ALPACA_KEY, _ALPACA_SECRET
    if _ALPACA_KEY and _ALPACA_SECRET:
        return
    # Try environment variables first (Task Scheduler sets these if configured)
    _ALPACA_KEY = os.environ.get("ALPACA_API_KEY")
    _ALPACA_SECRET = os.environ.get("ALPACA_SECRET_KEY")
    if _ALPACA_KEY and _ALPACA_SECRET:
        return
    # Fall back to agent/.env file
    if _ENV_PATH.exists():
        for line in _ENV_PATH.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line.startswith("#") or "=" not in line:
                continue
            key, _, val = line.partition("=")
            key = key.strip()
            val = val.strip()
            if key == "ALPACA_API_KEY":
                _ALPACA_KEY = val
            elif key == "ALPACA_SECRET_KEY":
                _ALPACA_SECRET = val


def _alpaca_available() -> bool:
    _load_env()
    return bool(_ALPACA_KEY and _ALPACA_SECRET)


def fetch_ohlcv(symbol: str, lookback_days: int = 520) -> pd.DataFrame:
    """Fetch daily OHLCV bars. Returns df with open/high/low/close/volume columns."""
    if _alpaca_available():
        return _fetch_ohlcv_alpaca(symbol, lookback_days)
    return _fetch_ohlcv_yfinance(symbol, lookback_days)


def fetch_close(symbols: list[str], lookback_days: int = 520) -> pd.DataFrame:
    """Fetch daily close prices for multiple symbols. Returns df with symbol columns."""
    if _alpaca_available():
        return _fetch_close_alpaca(symbols, lookback_days)
    return _fetch_close_yfinance(symbols, lookback_days)


# ---------------------------------------------------------------------------
# Alpaca implementation
# ---------------------------------------------------------------------------

def _fetch_ohlcv_alpaca(symbol: str, lookback_days: int) -> pd.DataFrame:
    try:
        from alpaca.data.historical import StockHistoricalDataClient
        from alpaca.data.requests import StockBarsRequest
        from alpaca.data.timeframe import TimeFrame
    except ImportError as exc:
        raise ImportError("alpaca-py required: uv add alpaca-py") from exc

    _load_env()
    client = StockHistoricalDataClient(api_key=_ALPACA_KEY, secret_key=_ALPACA_SECRET)

    today = date.today()
    start_dt = datetime.combine(today - timedelta(days=lookback_days), datetime.min.time())
    end_dt = datetime.combine(today, datetime.min.time())

    request = StockBarsRequest(
        symbol_or_symbols=symbol,
        timeframe=TimeFrame.Day,
        start=start_dt,
        end=end_dt,
        adjustment="all",
    )
    bars = client.get_stock_bars(request)
    df = bars.df

    if df.empty:
        raise ValueError(f"No Alpaca price data for {symbol}")

    # Multi-index (symbol, timestamp) -> single timestamp index
    if isinstance(df.index, pd.MultiIndex):
        df = df.xs(symbol, level="symbol")

    df.index = pd.to_datetime(df.index).tz_localize(None)
    df.columns = [c.lower() for c in df.columns]
    cols = [c for c in ["open", "high", "low", "close", "volume"] if c in df.columns]
    return df[cols].dropna().copy()


def _fetch_close_alpaca(symbols: list[str], lookback_days: int) -> pd.DataFrame:
    try:
        from alpaca.data.historical import StockHistoricalDataClient
        from alpaca.data.requests import StockBarsRequest
        from alpaca.data.timeframe import TimeFrame
    except ImportError as exc:
        raise ImportError("alpaca-py required: uv add alpaca-py") from exc

    _load_env()
    client = StockHistoricalDataClient(api_key=_ALPACA_KEY, secret_key=_ALPACA_SECRET)

    today = date.today()
    start_dt = datetime.combine(today - timedelta(days=lookback_days), datetime.min.time())
    end_dt = datetime.combine(today, datetime.min.time())

    request = StockBarsRequest(
        symbol_or_symbols=symbols,
        timeframe=TimeFrame.Day,
        start=start_dt,
        end=end_dt,
        adjustment="all",
    )
    bars = client.get_stock_bars(request)
    df = bars.df

    if df.empty:
        raise ValueError(f"No Alpaca price data for {symbols}")

    # Multi-index (symbol, timestamp) -> pivot to (timestamp, symbol)
    if isinstance(df.index, pd.MultiIndex):
        df = df["close"].unstack(level="symbol")
    else:
        df = df[["close"]].rename(columns={"close": symbols[0]})

    df.index = pd.to_datetime(df.index).tz_localize(None)
    df.columns = [str(c) for c in df.columns]
    return df.dropna().copy()


# ---------------------------------------------------------------------------
# yfinance fallback
# ---------------------------------------------------------------------------

def _fetch_ohlcv_yfinance(symbol: str, lookback_days: int) -> pd.DataFrame:
    try:
        import yfinance as yf
    except ImportError as exc:
        raise ImportError("yfinance required: uv add yfinance") from exc

    today = date.today()
    start = (today - timedelta(days=lookback_days)).strftime("%Y-%m-%d")
    end = (today + timedelta(days=1)).strftime("%Y-%m-%d")
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        df = yf.download(symbol, start=start, end=end, progress=False, auto_adjust=True)
    if df.empty:
        raise ValueError(f"No yfinance price data for {symbol} {start}:{end}")
    df.columns = [c.lower() if isinstance(c, str) else c[0].lower() for c in df.columns]
    return df[["open", "high", "low", "close", "volume"]].dropna().copy()


def _fetch_close_yfinance(symbols: list[str], lookback_days: int) -> pd.DataFrame:
    try:
        import yfinance as yf
    except ImportError as exc:
        raise ImportError("yfinance required: uv add yfinance") from exc

    today = date.today()
    start = (today - timedelta(days=lookback_days * 2)).strftime("%Y-%m-%d")
    end = (today + timedelta(days=1)).strftime("%Y-%m-%d")
    frames: dict[str, pd.Series] = {}
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        for sym in symbols:
            df = yf.download(sym, start=start, end=end, progress=False, auto_adjust=True)
            if df.empty:
                raise ValueError(f"No yfinance price data for {sym} {start}:{end}")
            df.columns = [c.lower() if isinstance(c, str) else c[0].lower() for c in df.columns]
            frames[sym] = df["close"]
    return pd.DataFrame(frames).dropna()


def data_source() -> str:
    """Return which source will be used — useful for logging."""
    return "alpaca" if _alpaca_available() else "yfinance"


def fetch_vix_context() -> dict:
    """Fetch latest VIX close from CBOE's public history CSV.

    This is context only. It does not change strategy signals.
    """
    url = "https://cdn.cboe.com/api/global/us_indices/daily_prices/VIX_History.csv"
    try:
        with urllib.request.urlopen(url, timeout=10) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
        rows = [line.strip().split(",") for line in raw.splitlines() if line.strip()]
        if len(rows) < 2:
            raise ValueError("empty VIX history")
        header = [h.strip().upper() for h in rows[0]]
        date_idx = header.index("DATE")
        close_idx = header.index("CLOSE")
        last = rows[-1]
        vix_close = float(last[close_idx])
        return {
            "source": "cboe_vix_history",
            "date": last[date_idx],
            "close": round(vix_close, 2),
            "above_20": vix_close >= 20.0,
            "regime": _vix_regime(vix_close),
        }
    except Exception as exc:
        return {
            "source": "cboe_vix_history",
            "available": False,
            "error": str(exc)[:160],
        }


def fetch_vix_term_structure_context() -> dict:
    """Fetch VIX and VIX3M directly from CBOE history CSVs.

    Returns both ratio directions because premium-selling code usually thinks
    in VIX/VIX3M terms, while directional code often logs VIX3M/VIX.
    """
    try:
        vix_row = _fetch_cboe_index_last_row("VIX_History.csv")
        vix3m_row = _fetch_cboe_index_last_row("VIX3M_History.csv")
        vix = float(vix_row["close"])
        vix3m = float(vix3m_row["close"])
        vix_over_vix3m = round(vix / vix3m, 4) if vix3m > 0 else 0.0
        vix3m_over_vix = round(vix3m / vix, 4) if vix > 0 else 0.0
        if vix > vix3m:
            regime = "backwardation"
        elif vix3m_over_vix >= 1.03:
            regime = "contango"
        else:
            regime = "flat"
        return {
            "source": "cboe_vix_vix3m_history",
            "date": vix_row["date"],
            "vix": round(vix, 2),
            "vix3m": round(vix3m, 2),
            "vix_over_vix3m": round(vix_over_vix3m, 4),
            "vix3m_over_vix": round(vix3m_over_vix, 4),
            "regime": regime,
        }
    except Exception as exc:
        return {
            "source": "cboe_vix_vix3m_history",
            "available": False,
            "error": str(exc)[:160],
        }


def _fetch_cboe_index_last_row(filename: str) -> dict:
    url = f"https://cdn.cboe.com/api/global/us_indices/daily_prices/{filename}"
    with urllib.request.urlopen(url, timeout=10) as resp:
        raw = resp.read().decode("utf-8", errors="replace")
    rows = [line.strip().split(",") for line in raw.splitlines() if line.strip()]
    if len(rows) < 2:
        raise ValueError(f"empty CBOE history: {filename}")
    header = [h.strip().upper() for h in rows[0]]
    date_idx = header.index("DATE")
    close_idx = header.index("CLOSE")
    last = rows[-1]
    return {
        "date": last[date_idx],
        "close": float(last[close_idx]),
    }


def _vix_regime(vix_close: float) -> str:
    if vix_close < 15:
        return "low_vol"
    if vix_close < 20:
        return "normal"
    if vix_close < 30:
        return "elevated"
    return "panic"

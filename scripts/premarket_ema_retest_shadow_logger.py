"""Shadow-only premarket high/low + EMA retest scanner.

Inspired by public "account flip" chart posts that use premarket high/low,
13/48/200 EMA trend stack, breakout, and retest. This script never places
orders. It logs a hypothesis so we can measure whether the setup actually
improves outcomes before any execution discussion.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


LOG_PATH = ROOT / "data" / "premarket_ema_retest_shadow_log.jsonl"
REPORT_PATH = Path.home() / ".vibe-trading" / "reports" / "premarket-ema-retest-shadow.json"
DEFAULT_SYMBOLS = ["SPY", "QQQ"]


def fetch_intraday_bars_alpaca(symbol: str, trading_day: date | None = None) -> pd.DataFrame:
    """Fetch 04:00-16:00 ET minute bars so premarket levels are available."""
    try:
        from alpaca.data.historical import StockHistoricalDataClient
        from alpaca.data.enums import DataFeed
        from alpaca.data.requests import StockBarsRequest
        from alpaca.data.timeframe import TimeFrame
    except ImportError as exc:
        raise ImportError("alpaca-py required for premarket EMA retest scanner") from exc

    import scripts.market_data as market_data

    market_data._load_env()  # noqa: SLF001 - operational helper shared by local scanners
    if not (market_data._ALPACA_KEY and market_data._ALPACA_SECRET):  # noqa: SLF001
        raise RuntimeError("ALPACA_API_KEY/ALPACA_SECRET_KEY required for intraday bars")

    trading_day = trading_day or date.today()
    eastern = ZoneInfo("America/New_York")
    # Include prior sessions so the four-level playbook can measure previous-day
    # high/low alongside the current premarket range.
    start_dt = datetime.combine(trading_day - timedelta(days=7), time(4, 0), tzinfo=eastern)
    end_dt = datetime.combine(trading_day, time(16, 0), tzinfo=eastern)
    client = StockHistoricalDataClient(api_key=market_data._ALPACA_KEY, secret_key=market_data._ALPACA_SECRET)  # noqa: SLF001
    request = StockBarsRequest(
        symbol_or_symbols=symbol.upper(),
        timeframe=TimeFrame.Minute,
        start=start_dt,
        end=end_dt,
        adjustment="raw",
        feed=DataFeed.IEX,
    )
    bars = client.get_stock_bars(request)
    df = bars.df
    if df.empty:
        raise ValueError(f"No Alpaca intraday bars for {symbol}")
    if isinstance(df.index, pd.MultiIndex):
        df = df.xs(symbol.upper(), level="symbol")
    df.index = pd.to_datetime(df.index)
    if df.index.tz is None:
        df.index = df.index.tz_localize("UTC")
    df.index = df.index.tz_convert("America/New_York")
    df.columns = [str(c).lower() for c in df.columns]
    return df[[c for c in ["open", "high", "low", "close", "volume"] if c in df.columns]].dropna().copy()


def _ema(series: pd.Series, span: int) -> pd.Series:
    return series.ewm(span=span, adjust=False).mean()


def _vwap(df: pd.DataFrame) -> pd.Series:
    typical = (df["high"] + df["low"] + df["close"]) / 3
    vol = df["volume"].replace(0, pd.NA)
    return (typical * vol).cumsum() / vol.cumsum()


def compute_premarket_ema_retest(symbol: str, df: pd.DataFrame) -> dict[str, Any]:
    if df.empty:
        return {"symbol": symbol.upper(), "status": "empty"}
    working = df.copy()
    idx = pd.to_datetime(working.index)
    if idx.tz is None:
        idx = idx.tz_localize("America/New_York")
    else:
        idx = idx.tz_convert("America/New_York")
    working.index = idx

    trading_day = working.index.max().date()
    current_day = working[working.index.date == trading_day]
    premarket = current_day.between_time("04:00", "09:29")
    rth = current_day.between_time("09:30", "16:00")
    if premarket.empty or len(rth) < 20:
        return {
            "symbol": symbol.upper(),
            "status": "insufficient_data",
            "premarket_bars": len(premarket),
            "rth_bars": len(rth),
        }

    pm_high = float(premarket["high"].max())
    pm_low = float(premarket["low"].min())
    prior_rows = working[working.index.date < trading_day].between_time("09:30", "16:00")
    prior_day_high: float | None = None
    prior_day_low: float | None = None
    prior_day_date: str | None = None
    if not prior_rows.empty:
        prior_session_date = prior_rows.index.max().date()
        prior_session = prior_rows[prior_rows.index.date == prior_session_date]
        prior_day_high = float(prior_session["high"].max())
        prior_day_low = float(prior_session["low"].min())
        prior_day_date = prior_session_date.isoformat()
    rth = rth.copy()
    rth["ema13"] = _ema(rth["close"], 13)
    rth["ema48"] = _ema(rth["close"], 48)
    rth["ema200"] = _ema(rth["close"], 200)
    rth["vwap"] = _vwap(rth)
    latest = rth.iloc[-1]
    close = float(latest["close"])
    ema13 = float(latest["ema13"])
    ema48 = float(latest["ema48"])
    ema200 = float(latest["ema200"])
    vwap = float(latest["vwap"])

    broke_pm_high = bool((rth["close"] > pm_high).any())
    broke_pm_low = bool((rth["close"] < pm_low).any())
    broke_prior_day_high = bool(
        prior_day_high is not None and (rth["close"] > prior_day_high).any()
    )
    broke_prior_day_low = bool(
        prior_day_low is not None and (rth["close"] < prior_day_low).any()
    )
    recent = rth.tail(8)
    retested_13 = bool((recent["low"] <= recent["ema13"] * 1.002).any())
    retested_48 = bool((recent["low"] <= recent["ema48"] * 1.002).any())
    rejected_13_short = bool((recent["high"] >= recent["ema13"] * 0.998).any())
    rejected_48_short = bool((recent["high"] >= recent["ema48"] * 0.998).any())

    bull_stack = ema13 > ema48 > ema200
    bear_stack = ema13 < ema48 < ema200
    above_vwap = close > vwap
    below_vwap = close < vwap
    above_pm_high = close > pm_high
    below_pm_low = close < pm_low
    above_prior_day_high = prior_day_high is not None and close > prior_day_high
    below_prior_day_low = prior_day_low is not None and close < prior_day_low

    bull_score = sum([
        2 if broke_pm_high else 0,
        2 if above_pm_high else 0,
        2 if bull_stack else 0,
        1 if above_vwap else 0,
        1 if retested_13 or retested_48 else 0,
        1 if broke_prior_day_high and above_prior_day_high else 0,
    ])
    bear_score = sum([
        2 if broke_pm_low else 0,
        2 if below_pm_low else 0,
        2 if bear_stack else 0,
        1 if below_vwap else 0,
        1 if rejected_13_short or rejected_48_short else 0,
        1 if broke_prior_day_low and below_prior_day_low else 0,
    ])

    if bull_score >= 7 and bull_stack:
        action = "watch_call_retest"
        bias = "bullish_account_flip_setup"
        confidence = min(10.0, 6.0 + bull_score * 0.45)
    elif bear_score >= 7 and bear_stack:
        action = "watch_put_retest"
        bias = "bearish_account_flip_setup"
        confidence = min(10.0, 6.0 + bear_score * 0.45)
    else:
        action = "stand_aside"
        bias = "mixed_or_unconfirmed"
        confidence = max(bull_score, bear_score)

    return {
        "schema_version": 2,
        "symbol": symbol.upper(),
        "status": "ok",
        "date": rth.index[-1].date().isoformat(),
        "as_of": rth.index[-1].isoformat(),
        "action": action,
        "bias": bias,
        "confidence": round(float(confidence), 2),
        "bull_score": bull_score,
        "bear_score": bear_score,
        "premarket_high": round(pm_high, 4),
        "premarket_low": round(pm_low, 4),
        "previous_day_high": round(prior_day_high, 4) if prior_day_high is not None else None,
        "previous_day_low": round(prior_day_low, 4) if prior_day_low is not None else None,
        "previous_day_date": prior_day_date,
        "latest_close": round(close, 4),
        "ema13": round(ema13, 4),
        "ema48": round(ema48, 4),
        "ema200": round(ema200, 4),
        "vwap": round(vwap, 4),
        "features": {
            "broke_pm_high": broke_pm_high,
            "broke_pm_low": broke_pm_low,
            "broke_previous_day_high": broke_prior_day_high,
            "broke_previous_day_low": broke_prior_day_low,
            "held_above_previous_day_high": above_prior_day_high,
            "held_below_previous_day_low": below_prior_day_low,
            "bull_stack_13_48_200": bull_stack,
            "bear_stack_13_48_200": bear_stack,
            "retested_13_or_48": retested_13 or retested_48,
            "rejected_13_or_48_short": rejected_13_short or rejected_48_short,
        },
    }


def scan_symbol(symbol: str, trading_day: date | None = None) -> dict[str, Any]:
    try:
        df = fetch_intraday_bars_alpaca(symbol, trading_day=trading_day)
        return compute_premarket_ema_retest(symbol, df)
    except Exception as exc:
        return {"symbol": symbol.upper(), "status": "error", "error": str(exc)[:200]}


_NYSE_HOLIDAYS = {
    date(2026, 1, 1), date(2026, 1, 19), date(2026, 2, 16), date(2026, 4, 3),
    date(2026, 5, 25), date(2026, 7, 4), date(2026, 9, 7), date(2026, 11, 26),
    date(2026, 11, 27), date(2026, 12, 25),
}


def _is_market_closed(d: date) -> bool:
    return d.weekday() >= 5 or d in _NYSE_HOLIDAYS


def build_report(symbols: list[str] | None = None, trading_day: date | None = None) -> dict[str, Any]:
    symbols = symbols or DEFAULT_SYMBOLS
    trading_day = trading_day or date.today()
    if _is_market_closed(trading_day):
        return {
            "date": trading_day.isoformat(),
            "timestamp": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "provider": "premarket_ema_retest_shadow_logger",
            "status": "market_closed",
            "execution_mode": "shadow_only",
            "execution_enabled": False,
            "symbols": symbols,
            "actionable_count": 0,
            "scans": [],
        }
    scans = [scan_symbol(symbol, trading_day=trading_day) for symbol in symbols]
    actionable = [row for row in scans if row.get("action") in {"watch_call_retest", "watch_put_retest"}]
    return {
        "schema_version": 2,
        "date": trading_day.isoformat(),
        "timestamp": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "provider": "premarket_ema_retest_shadow_logger",
        "source": "alpaca_intraday_bars",
        "execution_mode": "shadow_only",
        "execution_enabled": False,
        "symbols": symbols,
        "actionable_count": len(actionable),
        "scans": scans,
        "paper_rules": {
            "minimum_forward_days": 30,
            "minimum_signals_before_review": 10,
            "live_execution_allowed": False,
            "note": "Account-flip style setup. Shadow-only until verified against forward outcomes.",
        },
    }


def append_log(report: dict[str, Any], log_path: Path = LOG_PATH) -> None:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(report, separators=(",", ":")) + "\n")


def write_report(report: dict[str, Any], report_path: Path = REPORT_PATH) -> Path:
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    return report_path


def print_report(report: dict[str, Any]) -> None:
    print("\nPremarket EMA Retest Shadow | no orders")
    print("=" * 72)
    print(f"actionable={report['actionable_count']} execution_enabled={report['execution_enabled']}")
    for row in report["scans"]:
        if row.get("status") != "ok":
            print(f"{row['symbol']:<5} {row.get('status')} {row.get('error', '')}")
        else:
            print(
                f"{row['symbol']:<5} {row['action']:<17} conf={row['confidence']} "
                f"bull={row['bull_score']} bear={row['bear_score']} close={row['latest_close']}"
            )
    print("No orders placed.\n")


def main() -> int:
    parser = argparse.ArgumentParser(description="Log shadow-only premarket EMA retest setups.")
    parser.add_argument("--symbols", default=",".join(DEFAULT_SYMBOLS))
    parser.add_argument("--date", default=None, help="YYYY-MM-DD, default today")
    parser.add_argument("--log-path", type=Path, default=LOG_PATH)
    parser.add_argument("--report-path", type=Path, default=REPORT_PATH)
    parser.add_argument("--print", action="store_true", dest="print_output")
    args = parser.parse_args()
    symbols = [s.strip().upper() for s in args.symbols.split(",") if s.strip()]
    trading_day = date.fromisoformat(args.date) if args.date else None
    report = build_report(symbols=symbols, trading_day=trading_day)
    append_log(report, args.log_path)
    write_report(report, args.report_path)
    if args.print_output:
        print_report(report)
    else:
        print(f"Premarket EMA retest shadow logged to {args.log_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

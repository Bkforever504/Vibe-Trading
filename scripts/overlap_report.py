"""
Signal overlap analysis for new shadow logger candidates vs existing validated strategies.

Pair 1: Williams %R QQQ (intake-008) vs RSI-2 QQQ (existing candidate)
  Both are oversold mean-reversion on QQQ daily bars.
  High overlap -> redundant. Low overlap -> orthogonal (additive).

Pair 2: QQQ/GLD rotation (intake-007) vs Momentum Rotation top-2 weekly
  Both can hold QQQ. Question: do they agree or diverge?
  High agreement -> redundant. Independent switching -> additive.

Usage:
    uv run --no-project --with yfinance python scripts/overlap_report.py
    uv run --no-project --with yfinance python scripts/overlap_report.py --start 2018-01-01
"""
from __future__ import annotations

import argparse
import importlib.util
import sys
import warnings
from datetime import date, timedelta
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


# ---------------------------------------------------------------------------
# Strategy loaders
# ---------------------------------------------------------------------------

def _load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise ImportError(f"Cannot load {name} from {path}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _get_strategy(rel: str, name: str):
    return _load_module(ROOT / rel, name)


# ---------------------------------------------------------------------------
# Data fetch
# ---------------------------------------------------------------------------

def _fetch_ohlcv(symbol: str, start: str, end: str) -> pd.DataFrame:
    try:
        import yfinance as yf
    except ImportError as exc:
        raise ImportError("yfinance required: uv add yfinance") from exc
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        df = yf.download(symbol, start=start, end=end, progress=False, auto_adjust=True)
    if df.empty:
        raise ValueError(f"No price data for {symbol} {start}:{end}")
    df.columns = [c.lower() if isinstance(c, str) else c[0].lower() for c in df.columns]
    return df[["open", "high", "low", "close", "volume"]].dropna().copy()


def _fetch_close(symbols: list[str], start: str, end: str) -> pd.DataFrame:
    try:
        import yfinance as yf
    except ImportError as exc:
        raise ImportError("yfinance required: uv add yfinance") from exc
    frames: dict[str, pd.Series] = {}
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        for sym in symbols:
            df = yf.download(sym, start=start, end=end, progress=False, auto_adjust=True)
            if df.empty:
                raise ValueError(f"No price data for {sym} {start}:{end}")
            df.columns = [c.lower() if isinstance(c, str) else c[0].lower() for c in df.columns]
            frames[sym] = df["close"]
    return pd.DataFrame(frames).dropna()


# ---------------------------------------------------------------------------
# Pair 1: Williams %R vs RSI-2 (QQQ daily)
# ---------------------------------------------------------------------------

def _wr_signals(ohlcv: pd.DataFrame) -> pd.Series:
    wr_mod = _get_strategy(
        "research/pine_strategy_lab/examples/williams_r_oversold_python.py",
        "williams_r_oversold_python",
    )
    return wr_mod.strategy(
        ohlcv,
        wr_window=2,
        entry_threshold=-90,
        exit_threshold=-50,
        max_hold=5,
        trend_window=0,
    )


def _rsi2_signals(ohlcv: pd.DataFrame) -> pd.Series:
    rsi2_mod = _get_strategy(
        "research/pine_strategy_lab/examples/rsi2_mean_reversion_python.py",
        "rsi2_mean_reversion_python",
    )
    return rsi2_mod.strategy(
        ohlcv,
        rsi_threshold=15,
        trend_window=200,
        exit_sma=5,
        exit_mode="prior_high",
    )


def analyze_wr_vs_rsi2(start: str, end: str) -> dict:
    ohlcv = _fetch_ohlcv("QQQ", start, end)
    wr = _wr_signals(ohlcv).rename("wr")
    rsi2 = _rsi2_signals(ohlcv).rename("rsi2")

    df = pd.concat([wr, rsi2], axis=1).dropna()
    total = len(df)

    both_in = int(((df["wr"] == 1) & (df["rsi2"] == 1)).sum())
    only_wr = int(((df["wr"] == 1) & (df["rsi2"] == 0)).sum())
    only_rsi2 = int(((df["wr"] == 0) & (df["rsi2"] == 1)).sum())
    both_flat = int(((df["wr"] == 0) & (df["rsi2"] == 0)).sum())

    wr_days = int((df["wr"] == 1).sum())
    rsi2_days = int((df["rsi2"] == 1).sum())

    # Overlap = days both in trade / union of in-trade days
    union = wr_days + rsi2_days - both_in
    jaccard = both_in / union if union > 0 else 0.0

    # When WR fires, what % of days is RSI-2 also in?
    wr_given_rsi2 = both_in / rsi2_days if rsi2_days > 0 else 0.0
    rsi2_given_wr = both_in / wr_days if wr_days > 0 else 0.0

    return {
        "pair": "Williams_%R_QQQ vs RSI-2_QQQ",
        "period": f"{start} to {end}",
        "total_bars": total,
        "wr_in_days": wr_days,
        "rsi2_in_days": rsi2_days,
        "both_in": both_in,
        "only_wr": only_wr,
        "only_rsi2": only_rsi2,
        "both_flat": both_flat,
        "jaccard_overlap": round(jaccard, 3),
        "pct_rsi2_days_also_in_wr": round(wr_given_rsi2 * 100, 1),
        "pct_wr_days_also_in_rsi2": round(rsi2_given_wr * 100, 1),
    }


# ---------------------------------------------------------------------------
# Pair 2: QQQ/GLD rotation vs Momentum Rotation (weekly)
# ---------------------------------------------------------------------------

def _qqq_gld_weekly_signal(close: pd.DataFrame, lookback: int = 40) -> pd.Series:
    """1 = hold QQQ, 0 = hold GLD (weekly resampled)."""
    weekly = close.resample("W-FRI").last().dropna()
    qqq_ret = weekly["QQQ"].pct_change(lookback)
    gld_ret = weekly["GLD"].pct_change(lookback)
    return (qqq_ret > gld_ret).astype(int)


def _momentum_rotation_weekly_holds_qqq(close: pd.DataFrame, lookback: int = 252) -> pd.Series:
    """1 = QQQ is in top-2 by 12-month momentum, 0 = not selected (weekly resampled)."""
    symbols = list(close.columns)
    weekly = close.resample("W-FRI").last().dropna()
    signals = pd.Series(0, index=weekly.index, name="mom_qqq", dtype=int)
    for i in range(lookback, len(weekly)):
        window = weekly.iloc[i - lookback : i + 1]
        if len(window) < 2:
            continue
        returns = (window.iloc[-1] / window.iloc[0]) - 1
        ranked = returns.sort_values(ascending=False)
        top2 = [s for s, r in ranked.items() if r > 0][:2]
        signals.iloc[i] = 1 if "QQQ" in top2 else 0
    return signals


def analyze_qqq_gld_vs_momentum(start: str, end: str) -> dict:
    symbols = ["QQQ", "GLD", "SPY", "XLE", "TLT", "IWM", "XLK", "XLV", "XLF", "XLI"]
    close = _fetch_close(symbols, start, end)

    qqq_gld = _qqq_gld_weekly_signal(close[["QQQ", "GLD"]]).rename("qqq_gld")
    mom_qqq = _momentum_rotation_weekly_holds_qqq(close).rename("mom_qqq")

    df = pd.concat([qqq_gld, mom_qqq], axis=1).dropna()
    total = len(df)

    both_qqq = int(((df["qqq_gld"] == 1) & (df["mom_qqq"] == 1)).sum())
    only_qqq_gld_qqq = int(((df["qqq_gld"] == 1) & (df["mom_qqq"] == 0)).sum())
    only_mom_qqq = int(((df["qqq_gld"] == 0) & (df["mom_qqq"] == 1)).sum())
    both_other = int(((df["qqq_gld"] == 0) & (df["mom_qqq"] == 0)).sum())

    qqq_gld_qqq_weeks = int((df["qqq_gld"] == 1).sum())
    mom_qqq_weeks = int((df["mom_qqq"] == 1).sum())

    union = qqq_gld_qqq_weeks + mom_qqq_weeks - both_qqq
    jaccard = both_qqq / union if union > 0 else 0.0
    pct_qqq_gld_agrees_with_mom = both_qqq / qqq_gld_qqq_weeks if qqq_gld_qqq_weeks > 0 else 0.0

    return {
        "pair": "QQQ/GLD_rotation vs Momentum_Rotation_top2",
        "period": f"{start} to {end}",
        "total_weeks": total,
        "qqq_gld_holds_qqq_weeks": qqq_gld_qqq_weeks,
        "momentum_holds_qqq_weeks": mom_qqq_weeks,
        "both_hold_qqq": both_qqq,
        "only_qqq_gld_in_qqq": only_qqq_gld_qqq,
        "only_momentum_in_qqq": only_mom_qqq,
        "both_not_in_qqq": both_other,
        "jaccard_overlap": round(jaccard, 3),
        "pct_qqq_gld_qqq_also_in_momentum": round(pct_qqq_gld_agrees_with_mom * 100, 1),
    }


# ---------------------------------------------------------------------------
# Report printer
# ---------------------------------------------------------------------------

def _interpret_jaccard(j: float) -> str:
    if j >= 0.70:
        return "HIGH OVERLAP - strategies likely redundant"
    if j >= 0.40:
        return "MODERATE OVERLAP - partial redundancy, monitor"
    return "LOW OVERLAP - strategies appear orthogonal"


def print_overlap_report(wr_rsi2: dict, qqq_gld_mom: dict) -> None:
    print("\n" + "=" * 70)
    print("Signal Overlap Analysis")
    print("=" * 70)

    print("\n-- Pair 1: Williams %R QQQ vs RSI-2 QQQ (daily mean-reversion) --")
    r = wr_rsi2
    print(f"  Period:       {r['period']}")
    print(f"  Total bars:   {r['total_bars']}")
    print(f"  WR in-trade days:   {r['wr_in_days']}")
    print(f"  RSI-2 in-trade days:{r['rsi2_in_days']}")
    print(f"  Both in:      {r['both_in']} days")
    print(f"  Only WR:      {r['only_wr']} days")
    print(f"  Only RSI-2:   {r['only_rsi2']} days")
    print(f"  Jaccard:      {r['jaccard_overlap']:.3f}  -> {_interpret_jaccard(r['jaccard_overlap'])}")
    print(f"  When RSI-2 fires, WR also in: {r['pct_rsi2_days_also_in_wr']:.1f}%")
    print(f"  When WR fires, RSI-2 also in: {r['pct_wr_days_also_in_rsi2']:.1f}%")

    print("\n-- Pair 2: QQQ/GLD rotation vs Momentum Rotation (weekly) --")
    q = qqq_gld_mom
    print(f"  Period:       {q['period']}")
    print(f"  Total weeks:  {q['total_weeks']}")
    print(f"  QQQ/GLD holds QQQ:        {q['qqq_gld_holds_qqq_weeks']} weeks")
    print(f"  Momentum holds QQQ:       {q['momentum_holds_qqq_weeks']} weeks")
    print(f"  Both hold QQQ:            {q['both_hold_qqq']} weeks")
    print(f"  Only QQQ/GLD in QQQ:      {q['only_qqq_gld_in_qqq']} weeks")
    print(f"  Only Momentum in QQQ:     {q['only_momentum_in_qqq']} weeks")
    print(f"  Jaccard:      {q['jaccard_overlap']:.3f}  -> {_interpret_jaccard(q['jaccard_overlap'])}")
    print(f"  When QQQ/GLD picks QQQ, Momentum also in QQQ: {q['pct_qqq_gld_qqq_also_in_momentum']:.1f}%")

    print("\n" + "=" * 70)
    print("DECISION GUIDANCE")
    j1 = wr_rsi2["jaccard_overlap"]
    j2 = qqq_gld_mom["jaccard_overlap"]
    if j1 >= 0.70:
        print("  Williams %R vs RSI-2: HIGH overlap. WR may not add diversification.")
        print("  Consider logging WR only as a confirmation signal, not a standalone bot.")
    elif j1 >= 0.40:
        print("  Williams %R vs RSI-2: MODERATE overlap. Worth logging both but track correlation live.")
    else:
        print("  Williams %R vs RSI-2: LOW overlap. WR appears orthogonal to RSI-2. Good candidate.")
    if j2 >= 0.70:
        print("  QQQ/GLD vs Momentum: HIGH overlap. Strategies likely agree most of the time.")
        print("  Running both would double QQQ exposure without diversification benefit.")
    elif j2 >= 0.40:
        print("  QQQ/GLD vs Momentum: MODERATE overlap. Some divergence. Monitor for different regimes.")
    else:
        print("  QQQ/GLD vs Momentum: LOW overlap. Strategies pick QQQ at different times.")
    print()


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Signal overlap analysis for new shadow logger candidates.")
    parser.add_argument("--start", default="2018-01-01", help="Start date YYYY-MM-DD")
    parser.add_argument("--end", default=date.today().isoformat(), help="End date YYYY-MM-DD")
    args = parser.parse_args(argv)

    print(f"Fetching data {args.start} to {args.end}...")
    wr_rsi2 = analyze_wr_vs_rsi2(args.start, args.end)
    qqq_gld_mom = analyze_qqq_gld_vs_momentum(args.start, args.end)
    print_overlap_report(wr_rsi2, qqq_gld_mom)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""
Alt45 independent replication across trustdan's symbol universe.

Usage:
    uv run --no-project --with yfinance --with pandas --with numpy python research/run_alt45_replication.py
"""
from __future__ import annotations

import sys
import warnings
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from research.trustdan_alt45_backtest import Alt45Config, run_alt45_on_ohlcv

SYMBOLS = ["UNH", "XLV", "CAT", "PLD", "XLF", "XLE", "XLP", "SPY", "QQQ", "MSFT", "AMZN", "WMT", "GOOGL"]
WINDOWS = [
    ("2015-01-01", "2024-12-31"),
    ("2022-01-01", "2024-12-31"),
]
CONFIG = Alt45Config()


def fetch(symbol: str, start: str, end: str):
    try:
        import yfinance as yf
    except ImportError as e:
        raise ImportError("uv add yfinance") from e
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        df = yf.download(symbol, start=start, end=end, progress=False, auto_adjust=True)
    if df.empty:
        raise ValueError(f"No data: {symbol} {start}:{end}")
    df.columns = [c.lower() if isinstance(c, str) else c[0].lower() for c in df.columns]
    return df[["open", "high", "low", "close", "volume"]].dropna()


def run_window(label: str, start: str, end: str) -> None:
    print(f"\n{'='*62}")
    print(f"Alt45 Dual-Momentum | {start} to {end}")
    print(f"{'='*62}")
    print(f"{'Symbol':<8} {'Return':>8} {'PF':>6} {'WR%':>6} {'DD':>6} {'Trades':>7} {'Sharpe':>7} {'Status'}")
    print("-" * 62)

    profitable = 0
    total = 0
    rows = []
    for sym in SYMBOLS:
        try:
            df = fetch(sym, start, end)
            result = run_alt45_on_ohlcv(df, CONFIG)
            m = result.metrics
            status = "PROFIT" if m.profit_factor >= 1.0 else "LOSS"
            if m.profit_factor >= 1.0:
                profitable += 1
            total += 1
            rows.append((sym, m.total_return_pct, m.profit_factor, m.win_rate_pct,
                         m.max_drawdown_pct, m.trade_count, m.sharpe_ratio, status))
            print(f"{sym:<8} {m.total_return_pct:>7.2f}% {m.profit_factor:>6.2f} "
                  f"{m.win_rate_pct:>5.1f}% {m.max_drawdown_pct:>5.1f}% "
                  f"{m.trade_count:>7} {m.sharpe_ratio:>7.2f}  {status}")
        except Exception as exc:
            print(f"{sym:<8} ERROR: {exc}")
            total += 1

    print("-" * 62)
    rate = profitable / total * 100 if total else 0
    print(f"Profitable: {profitable}/{total} ({rate:.1f}%)  |  Trustdan claim: 66.67% (14/21)")
    return rows


def main() -> None:
    print("Alt45 Dual-Momentum Replication")
    print("Config: RSI filter=True, rsi_thresh=50, entry_len=55, age-based targets")
    all_rows = {}
    for label, (start, end) in zip(["daily_2015", "daily_2022"], WINDOWS):
        all_rows[label] = run_window(label, start, end)

    # Write markdown report
    out = ROOT / "research" / "pine_strategy_lab" / "trustdan_alt45_replication.md"
    lines = [
        "# Trustdan Alt45 Replication\n",
        f"Date: {date.today().isoformat()}\n",
        "Source: `research/pine_sources/trustdan-trend-following/pine-scripts/seykota_alt45_dual_momentum_confirmation.pine`\n",
        "Python replication: `research/trustdan_alt45_backtest.py`\n\n",
        "## Alt45 vs Alt10\n\n",
        "Alt45 adds RSI(14) > 50 dual-momentum gate to the Alt10 Donchian entry.\n",
        "Age-based targets: Young ≤15 bars → 4N/7N/10N, Mature ≤30 bars → 3N/6N/9N, Aging → 2N/4N/6N.\n\n",
        "## Trustdan Claim\n\n",
        "- 66.67% success rate (14/21 tickers profitable)\n",
        "- Daily data, ~2010-2025\n\n",
    ]

    for label, rows in all_rows.items():
        window_label = "2015-2024" if "2015" in label else "2022-2024"
        lines.append(f"## Independent Daily-Bar Replication ({window_label})\n\n")
        lines.append("| Symbol | Return | PF | WR% | DD | Trades | Sharpe |\n")
        lines.append("|---|---:|---:|---:|---:|---:|---:|\n")
        profitable = 0
        for r in rows:
            sym, ret, pf, wr, dd, tr, sh, st = r
            sign = "+" if ret >= 0 else ""
            lines.append(f"| {sym} | {sign}{ret:.2f}% | {pf:.2f} | {wr:.1f}% | {dd:.1f}% | {tr} | {sh:.2f} |\n")
            if pf >= 1.0:
                profitable += 1
        lines.append(f"\nProfitable: {profitable}/{len(rows)}.\n\n")

    lines.append("## Interpretation\n\n")
    lines.append("See inline output for full analysis. Results compared to Alt10 replication baseline.\n")

    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("".join(lines), encoding="utf-8")
    print(f"\nReport written to {out}")


if __name__ == "__main__":
    main()

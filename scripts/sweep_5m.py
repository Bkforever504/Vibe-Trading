#!/usr/bin/env python3
"""5m bar parameter sweep for MNQ pullback strategy.

Runs the backtester across range/breakout/stop/filter combinations on
5-minute data and prints a ranked results table.

Usage:
    uv run --no-project --with yfinance python scripts/sweep_5m.py
    uv run --no-project --with yfinance python scripts/sweep_5m.py --csv examples/nq_5m_60d.csv
    uv run --no-project --with yfinance python scripts/sweep_5m.py --bos  # include BOS variants
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from itertools import product
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

BACKTESTER = [
    sys.executable,
    str(ROOT / "strategies" / "topstep_replay_backtester.py"),
]

FIXED_ARGS = [
    "--symbol", "MNQ",
    "--signal-type", "pullback",
    "--reward-risk", "2.0",
    "--slippage-ticks", "1",
    "--commission", "4.00",
    "--consistency-penalty", "100",
    "--require-opening-gap-bias",
]

# 5m-appropriate parameter grid
RANGE_MINUTES   = [3, 6, 12]          # 15min / 30min / 60min opening range
MIN_BREAKOUT    = [3.0, 5.0, 7.0]     # NQ points to confirm breakout
STOP_TICKS      = [8, 12, 20]         # 2pt / 3pt / 5pt stop on MNQ
TOLERANCE_TICKS = [8, 12, 16]         # 2pt / 3pt / 4pt pullback tolerance
KEY_LEVEL_TOLS  = [None, 24, 48]      # off / 6pt / 12pt proximity window


def _run(csv: Path, args: list[str]) -> dict | None:
    cmd = BACKTESTER + ["--csv", str(csv)] + FIXED_ARGS + args
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        return None
    try:
        return json.loads(r.stdout)["summary"]
    except (json.JSONDecodeError, KeyError):
        return None


def _row(name: str, d: dict) -> str:
    pf = f"{d['profit_factor']:.2f}" if d["profit_factor"] != "inf" else "inf"
    return (
        f"{name:<38} {d['days_traded']:>4} {d['win_rate']:>6.1%} "
        f"{pf:>6} {d['expectancy']:>8.2f} {d['max_drawdown']:>8.2f} "
        f"{len(d['rule_violations']):>5} {d['consistency_adjusted_score']:>8.2f}"
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="5m MNQ pullback parameter sweep")
    parser.add_argument("--csv", type=Path, default=ROOT / "examples" / "nq_5m_60d.csv")
    parser.add_argument("--bos", action="store_true", help="Also sweep BOS-confirm variants")
    parser.add_argument("--min-trades", type=int, default=2, help="Skip configs with fewer trades")
    args = parser.parse_args()

    if not args.csv.exists():
        sys.exit(f"CSV not found: {args.csv}")

    header = (
        f"{'Config':<38} {'Tr':>4} {'WR':>6} {'PF':>6} {'Exp':>8} "
        f"{'DD':>8} {'Viol':>5} {'Score':>8}"
    )
    print(header)
    print("-" * len(header))

    rows: list[tuple[float, str]] = []

    for rm, mbp, st, tol, klt in product(
        RANGE_MINUTES, MIN_BREAKOUT, STOP_TICKS, TOLERANCE_TICKS, KEY_LEVEL_TOLS
    ):
        for bos in ([False, True] if args.bos else [False]):
            extra: list[str] = [
                "--range-minutes", str(rm),
                "--min-breakout-points", str(mbp),
                "--pullback-stop-ticks", str(st),
                "--pullback-tolerance-ticks", str(tol),
            ]
            label_parts = [f"rm{rm}", f"mbp{mbp:.0f}", f"st{st}", f"tol{tol}"]
            if klt is not None:
                extra += ["--require-key-level-proximity", "--key-level-tolerance-ticks", str(klt)]
                label_parts.append(f"kl{klt}")
            if bos:
                extra.append("--require-bos-confirm")
                label_parts.append("bos")

            name = " ".join(label_parts)
            d = _run(args.csv, extra)
            if d is None or d["days_traded"] < args.min_trades:
                continue
            rows.append((d["consistency_adjusted_score"], _row(name, d)))

    for _, row in sorted(rows, reverse=True):
        print(row)

    print(f"\n{len(rows)} configs with >= {args.min_trades} trades")


if __name__ == "__main__":
    main()

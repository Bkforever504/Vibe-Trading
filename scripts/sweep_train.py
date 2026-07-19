#!/usr/bin/env python3
"""Train-only sweep harness ranked by consistency_adjusted_score.

Sweeps exit model, gap bias, VIX regime, entry window, key-level proximity,
stop ticks, BOS confirm, and 1h vs 5m data. Uses train-split for 1h
(avoids OOS contamination) and full-period for 5m (only 48 days, no
meaningful split).

Usage:
    uv run --no-project --with yfinance python scripts/sweep_train.py
    uv run --no-project --with yfinance python scripts/sweep_train.py --workers 8
    uv run --no-project --with yfinance python scripts/sweep_train.py --min-trades 5 --top 20
    uv run --no-project --with yfinance python scripts/sweep_train.py --include-5m
    uv run --no-project --with yfinance python scripts/sweep_train.py --csv-1h examples/nq_1h_730d.csv
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import dataclass
from itertools import product
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
BACKTESTER = [sys.executable, str(ROOT / "strategies" / "topstep_replay_backtester.py")]

TRAIN_END_1H = "2025-09-05"

# ---------------------------------------------------------------------------
# Grid definitions
# ---------------------------------------------------------------------------

# 1h-specific: range=1 bar = 1-hour opening range; mbp=20 NQ pts confirmed best
GRID_1H = {
    "stop_ticks":  [20, 40, 60, 80],      # 5 / 10 / 15 / 20 NQ pts
    "tol_ticks":   [8, 16],               # 2 / 4 NQ pts
}

# 5m-specific: range in bars (6=30min, 12=60min)
GRID_5M = {
    "range_minutes": [6, 12],
    "mbp":           [3.0, 5.0],
    "stop_ticks":    [8, 12, 20],         # 2 / 3 / 5 NQ pts
    "tol_ticks":     [8, 12],
}

# Shared dimensions
SHARED = {
    "exit_model":  ["full_target_stop", "partial_1r_be_2r"],
    "gap_bias":    [False, True],
    "vix_range":   [None, (15.0, 28.0), (16.0, 24.0)],
    "entry_start": [None, (10, 30)],
    "kl_tol":      [None, 16, 24, 48],   # None = off
    "bos":         [False, True],
}


# ---------------------------------------------------------------------------
# Config runner
# ---------------------------------------------------------------------------

@dataclass
class RunSpec:
    label: str
    dataset: str       # "1h" or "5m"
    csv: str
    args: list[str]


def _start_label(entry_start: tuple[int, int] | None) -> str:
    if entry_start is None:
        return ""
    hour, minute = entry_start
    return f"s{hour:02d}{minute:02d}"


def _vix_label(vix_range: tuple[float, float] | None) -> str:
    if vix_range is None:
        return ""
    vmin, vmax = vix_range
    return f"vix{vmin:g}-{vmax:g}"


def _apply_shared_filters(
    extra: list[str],
    label_parts: list[str],
    *,
    gap: bool,
    vix_range: tuple[float, float] | None,
    entry_start: tuple[int, int] | None,
    klt: int | None,
    bos: bool,
) -> None:
    if gap:
        extra.append("--require-opening-gap-bias")
        label_parts.append("gap")
    if vix_range is not None:
        vmin, vmax = vix_range
        extra += ["--require-vix-range", "--vix-min", str(vmin), "--vix-max", str(vmax)]
        label_parts.append(_vix_label(vix_range))
    if entry_start is not None:
        hour, minute = entry_start
        extra += ["--start-hour", str(hour), "--start-minute", str(minute)]
        label_parts.append(_start_label(entry_start))
    if klt is not None:
        extra += ["--require-key-level-proximity", "--key-level-tolerance-ticks", str(klt)]
        label_parts.append(f"kl{klt}")
    if bos:
        extra.append("--require-bos-confirm")
        label_parts.append("bos")


def _build_1h_specs(csv_1h: str, *, consistency_penalty: float) -> list[RunSpec]:
    specs: list[RunSpec] = []
    fixed = [
        "--symbol", "MNQ",
        "--signal-type", "pullback",
        "--range-minutes", "1",
        "--min-breakout-points", "20.0",
        "--reward-risk", "2.0",
        "--slippage-ticks", "1",
        "--commission", "4.00",
        "--consistency-penalty", str(consistency_penalty),
        "--train-end", TRAIN_END_1H,
    ]
    for stop, tol, em, gap, vix, start, klt, bos in product(
        GRID_1H["stop_ticks"],
        GRID_1H["tol_ticks"],
        SHARED["exit_model"],
        SHARED["gap_bias"],
        SHARED["vix_range"],
        SHARED["entry_start"],
        SHARED["kl_tol"],
        SHARED["bos"],
    ):
        extra: list[str] = list(fixed) + [
            "--pullback-stop-ticks", str(stop),
            "--pullback-tolerance-ticks", str(tol),
            "--exit-model", em,
        ]

        label_parts = [f"st{stop}", f"tol{tol}", em[:4]]
        _apply_shared_filters(
            extra,
            label_parts,
            gap=gap,
            vix_range=vix,
            entry_start=start,
            klt=klt,
            bos=bos,
        )

        specs.append(RunSpec(
            label=" ".join(label_parts),
            dataset="1h",
            csv=csv_1h,
            args=extra,
        ))
    return specs


def _build_5m_specs(csv_5m: str, *, consistency_penalty: float) -> list[RunSpec]:
    specs: list[RunSpec] = []
    fixed = [
        "--symbol", "MNQ",
        "--signal-type", "pullback",
        "--reward-risk", "2.0",
        "--slippage-ticks", "1",
        "--commission", "4.00",
        "--consistency-penalty", str(consistency_penalty),
    ]
    for rm, mbp, stop, tol, em, gap, vix, start, klt, bos in product(
        GRID_5M["range_minutes"],
        GRID_5M["mbp"],
        GRID_5M["stop_ticks"],
        GRID_5M["tol_ticks"],
        SHARED["exit_model"],
        SHARED["gap_bias"],
        SHARED["vix_range"],
        SHARED["entry_start"],
        SHARED["kl_tol"],
        SHARED["bos"],
    ):
        extra: list[str] = list(fixed) + [
            "--range-minutes", str(rm),
            "--min-breakout-points", str(mbp),
            "--pullback-stop-ticks", str(stop),
            "--pullback-tolerance-ticks", str(tol),
            "--exit-model", em,
        ]
        label_parts = [f"rm{rm}", f"mbp{mbp:.0f}", f"st{stop}", f"tol{tol}", em[:4]]
        _apply_shared_filters(
            extra,
            label_parts,
            gap=gap,
            vix_range=vix,
            entry_start=start,
            klt=klt,
            bos=bos,
        )

        specs.append(RunSpec(
            label=" ".join(label_parts),
            dataset="5m",
            csv=csv_5m,
            args=extra,
        ))
    return specs


def _run_spec(spec: RunSpec) -> dict[str, Any] | None:
    cmd = BACKTESTER + ["--csv", spec.csv] + spec.args
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        return None
    try:
        raw = json.loads(r.stdout)
    except json.JSONDecodeError:
        return None

    # 1h with --train-end → parse train sub-result
    if "validation" in raw:
        d = raw["validation"]["train"]
    else:
        d = raw.get("summary", raw)

    return {
        "label":    spec.label,
        "dataset":  spec.dataset,
        "trades":   d.get("days_traded", 0),
        "win_rate": d.get("win_rate", 0.0),
        "pf":       d.get("profit_factor", 0.0),
        "exp":      d.get("expectancy", 0.0),
        "dd":       d.get("max_drawdown", 0.0),
        "viols":    len(d.get("rule_violations", [])),
        "score":    d.get("consistency_adjusted_score", 0.0),
    }


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------

COL_W = 48

def _header() -> str:
    return (
        f"{'Config':<{COL_W}} {'DS':>2} {'Tr':>4} {'WR':>6} {'PF':>6} "
        f"{'Exp':>8} {'DD':>8} {'V':>3} {'Score':>8}"
    )


def _row(d: dict) -> str:
    pf = f"{d['pf']:.2f}" if d["pf"] not in ("inf", float("inf")) else "inf"
    return (
        f"{d['label']:<{COL_W}} {d['dataset']:>2} {d['trades']:>4} "
        f"{d['win_rate']:>6.1%} {pf:>6} {d['exp']:>8.2f} "
        f"{d['dd']:>8.2f} {d['viols']:>3} {d['score']:>8.2f}"
    )


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description="Train-only sweep harness ranked by consistency_adjusted_score")
    parser.add_argument("--csv-1h", type=Path, default=ROOT / "examples" / "nq_1h_730d.csv")
    parser.add_argument("--csv-5m", type=Path, default=ROOT / "examples" / "nq_5m_60d.csv")
    parser.add_argument("--include-5m", action="store_true", help="Also sweep 5m data (slow)")
    parser.add_argument("--workers", type=int, default=4, help="Parallel worker processes")
    parser.add_argument("--min-trades", type=int, default=5, help="Minimum train trades to include")
    parser.add_argument("--top", type=int, default=30, help="Show top N results")
    parser.add_argument("--penalty", type=float, default=25.0, help="Consistency-rule penalty per violation")
    parser.add_argument("--no-violations", action="store_true", help="Only show 0-violation configs")
    parser.add_argument("--out", type=Path, default=None, help="Save full results as JSON")
    args = parser.parse_args()

    specs: list[RunSpec] = []
    if args.csv_1h.exists():
        specs += _build_1h_specs(str(args.csv_1h), consistency_penalty=args.penalty)
        print(f"1h specs: {len([s for s in specs if s.dataset == '1h'])} configs (train through {TRAIN_END_1H})")
    else:
        print(f"[warn] 1h CSV not found: {args.csv_1h}")

    if args.include_5m:
        if args.csv_5m.exists():
            n_before = len(specs)
            specs += _build_5m_specs(str(args.csv_5m), consistency_penalty=args.penalty)
            print(f"5m specs: {len(specs) - n_before} configs (full 48-day period, in-sample only)")
        else:
            print(f"[warn] 5m CSV not found: {args.csv_5m}")

    if not specs:
        sys.exit("No specs to run. Check CSV paths.")

    print(f"Total configs: {len(specs)} — running with {args.workers} workers...\n")

    results: list[dict] = []
    errors = 0

    with ProcessPoolExecutor(max_workers=args.workers) as pool:
        futures = {pool.submit(_run_spec, s): s for s in specs}
        done = 0
        for fut in as_completed(futures):
            done += 1
            r = fut.result()
            if r is None:
                errors += 1
            else:
                results.append(r)
            if done % 50 == 0 or done == len(specs):
                print(f"  {done}/{len(specs)} done ({errors} errors)...", end="\r")

    print()

    # Filter
    filtered = [r for r in results if r["trades"] >= args.min_trades]
    if args.no_violations:
        filtered = [r for r in filtered if r["viols"] == 0]

    # Sort by score descending
    filtered.sort(key=lambda r: r["score"], reverse=True)

    print(_header())
    print("-" * (COL_W + 52))

    shown = filtered[: args.top]
    for r in shown:
        print(_row(r))

    print(f"\n{len(filtered)} configs passed filter (>= {args.min_trades} trades"
          + (", 0 violations" if args.no_violations else "") + ")"
          + f" | showing top {len(shown)}"
          + f" | {errors} errors")

    if args.out:
        args.out.write_text(
            json.dumps({"configs": filtered, "total_run": len(results), "errors": errors}, indent=2),
            encoding="utf-8",
        )
        print(f"Full results → {args.out}")


if __name__ == "__main__":
    main()

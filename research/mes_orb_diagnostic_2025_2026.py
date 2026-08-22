#!/usr/bin/env python3
"""Diagnostic: why did ORB fail in 2025-2026?

Runs the best-known MES candidate on the final test period and breaks
down trades by hour, VIX level, day-of-week, month, gap direction, and
exit reason to reveal which sub-conditions still carry edge.
"""
from __future__ import annotations

import json
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from research.mes_futures_strategy_search import (
    Candidate,
    _by_date,
    _chronological_partitions,
    _configs,
    _slice,
)
from strategies.topstep_prop_bot import load_candles_csv
from strategies.topstep_replay_backtester import run_backtest

# Best candidate from the executable-only full-period search
BEST = Candidate(
    signal_type="pullback",
    breakout_points=1.0,
    reward_risk=2.0,
    stop_ticks=80,
    tolerance_ticks=8,
    exit_model="full_target_stop",
    filter_name="gap",
    range_minutes=5,
)

# Also test the top dev-score candidate
TOP_DEV = Candidate(
    signal_type="pullback",
    breakout_points=1.0,
    reward_risk=2.5,
    stop_ticks=80,
    tolerance_ticks=8,
    exit_model="full_target_stop",
    filter_name="gap",
    range_minutes=5,
)


def _load_vix(path: Path) -> dict[str, float]:
    vix: dict[str, float] = {}
    if not path.exists():
        return vix
    with open(path) as f:
        import csv
        reader = csv.DictReader(f)
        for row in reader:
            date_key = row.get("Date") or row.get("date") or ""
            val = row.get("Close") or row.get("close") or row.get("VIX") or ""
            try:
                vix[date_key.strip()] = float(val)
            except (ValueError, TypeError):
                pass
    return vix


def _vix_bucket(vix: float | None) -> str:
    if vix is None:
        return "unknown"
    if vix < 15:
        return "<15"
    if vix < 20:
        return "15-20"
    if vix < 25:
        return "20-25"
    return "25+"


def analyze(candidate: Candidate, trades: list, vix_map: dict[str, float]) -> dict:
    by_hour: dict[str, list] = defaultdict(list)
    by_vix: dict[str, list] = defaultdict(list)
    by_dow: dict[str, list] = defaultdict(list)
    by_month: dict[str, list] = defaultdict(list)
    by_exit: dict[str, list] = defaultdict(list)
    by_side: dict[str, list] = defaultdict(list)

    for t in trades:
        pnl = t.pnl
        hour = t.entry_time.strftime("%H:00")
        by_hour[hour].append(pnl)
        vix = vix_map.get(t.date)
        by_vix[_vix_bucket(vix)].append(pnl)
        dow = t.entry_time.strftime("%A")
        by_dow[dow].append(pnl)
        month = t.entry_time.strftime("%Y-%m")
        by_month[month].append(pnl)
        by_exit[t.exit_reason].append(pnl)
        by_side[t.side].append(pnl)

    def summarize(d: dict[str, list]) -> dict:
        out = {}
        for k, pnls in sorted(d.items()):
            wins = sum(1 for p in pnls if p > 0)
            out[k] = {
                "n": len(pnls),
                "wins": wins,
                "win_rate": round(wins / len(pnls), 3) if pnls else 0,
                "total": round(sum(pnls), 2),
                "avg": round(sum(pnls) / len(pnls), 2) if pnls else 0,
            }
        return out

    return {
        "candidate": {
            "signal_type": candidate.signal_type,
            "range_minutes": candidate.range_minutes,
            "breakout_points": candidate.breakout_points,
            "reward_risk": candidate.reward_risk,
            "stop_ticks": candidate.stop_ticks,
            "filter_name": candidate.filter_name,
        },
        "total_trades": len(trades),
        "total_pnl": round(sum(t.pnl for t in trades), 2),
        "overall_win_rate": round(sum(1 for t in trades if t.pnl > 0) / len(trades), 3) if trades else 0,
        "by_hour": summarize(by_hour),
        "by_vix_level": summarize(by_vix),
        "by_day_of_week": summarize(by_dow),
        "by_month": summarize(by_month),
        "by_exit_reason": summarize(by_exit),
        "by_side": summarize(by_side),
    }


def main() -> None:
    csv_path = ROOT / "examples" / "mes_v0_1m_2022-01-01_2026-07-19_rth.csv"
    vix_path = ROOT / "examples" / "vix_daily.csv"

    candles = load_candles_csv(csv_path)
    dates, grouped = _by_date(candles)
    _, _, final_dates = _chronological_partitions(dates)
    final_candles = _slice(grouped, final_dates)

    vix_map = _load_vix(vix_path)

    print(f"Final test period: {final_dates[0]} to {final_dates[-1]} ({len(final_dates)} sessions)\n")

    results = []
    for cand in (BEST, TOP_DEV):
        orb, bt = _configs(cand)
        result = run_backtest(final_candles, orb_config=orb, bt_config=bt, symbol="MES")
        breakdown = analyze(cand, result.trades, vix_map)
        results.append(breakdown)
        print(json.dumps(breakdown, indent=2))
        print("-" * 60)

    # Also: scan ALL hours systematically — run no-filter pullback by changing entry cutoff
    print("\n=== Hour-of-entry scan (no filter, vary cutoff) ===")
    from strategies.topstep_replay_backtester import BacktestConfig, run_backtest as rb
    from strategies.topstep_prop_bot import OpeningRangeConfig

    orb_cfg = OpeningRangeConfig(range_minutes=5, min_breakout_points=1.0, reward_risk=2.0)
    hour_results = {}
    for entry_hour in range(9, 14):
        for entry_min in ([30] if entry_hour == 9 else [0]):
            for cutoff_hour in range(entry_hour + 1, 15):
                label = f"{entry_hour:02d}:{entry_min:02d}-{cutoff_hour:02d}:00"
                bt_cfg = BacktestConfig(
                    slippage_ticks=1,
                    commission_per_rt=4.0,
                    max_trades_per_day=1,
                    daily_loss_limit=100.0,
                    session_entry_start_hour=entry_hour,
                    session_entry_start_minute=entry_min,
                    session_entry_cutoff_hour=cutoff_hour,
                    fixed_stop_ticks=80,
                    signal_type="pullback",
                    pullback_tolerance_ticks=8,
                    pullback_stop_ticks=80,
                    exit_model="full_target_stop",
                    require_opening_gap_bias=True,
                    vix_csv_path=str(vix_path),
                )
                r = rb(final_candles, orb_config=orb_cfg, bt_config=bt_cfg, symbol="MES")
                if r.days_traded >= 5:
                    hour_results[label] = {
                        "trades": r.days_traded,
                        "win_rate": r.win_rate,
                        "expectancy": r.expectancy,
                        "profit_factor": r.profit_factor,
                        "total_pnl": r.total_pnl,
                    }

    # Sort by expectancy
    for label, metrics in sorted(hour_results.items(), key=lambda x: x[1]["expectancy"], reverse=True)[:15]:
        print(f"{label:25s}  trades={metrics['trades']:3d}  wr={metrics['win_rate']:.1%}  "
              f"exp={metrics['expectancy']:+7.2f}  pf={metrics['profit_factor']:.3f}  "
              f"pnl={metrics['total_pnl']:+8.2f}")

    out = ROOT / "data" / "mes_orb_diagnostic_2025_2026.json"
    out.parent.mkdir(exist_ok=True)
    out.write_text(json.dumps({"candidates": results, "hour_scan": hour_results}, indent=2))
    print(f"\nFull results: {out}")


if __name__ == "__main__":
    main()

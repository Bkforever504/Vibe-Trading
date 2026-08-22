#!/usr/bin/env python3
"""Retrospective audit of a public liquidity-sweep/MSS/FVG-retest setup.

Research only. The report discloses every chronological split because the
rule was translated from public screenshots before this audit, not formally
preregistered. It cannot submit orders or promote itself.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from strategies.topstep_prop_bot import OpeningRangeConfig, load_candles_csv
from strategies.topstep_replay_backtester import BacktestConfig, TradeResult, run_backtest


DEFAULT_CSV = ROOT / "examples" / "mes_v0_1m_2022-01-01_2026-07-19_rth.csv"
DEFAULT_OUT = ROOT / "data" / "liquidity_sweep_mss_retest_results.json"
SPEC = "research/LIQUIDITY_SWEEP_MSS_RETEST_SPEC_2026-08-18.md"
BASELINE_FRICTION = 4.98


def summarize(trades: list[TradeResult], *, extra_friction: float = 0.0) -> dict:
    pnls = [trade.pnl - extra_friction for trade in trades]
    if not pnls:
        return {
            "trades": 0,
            "total_pnl": 0.0,
            "expectancy": None,
            "win_rate": None,
            "profit_factor": None,
            "max_drawdown": 0.0,
        }
    wins = sum(value for value in pnls if value > 0)
    losses = -sum(value for value in pnls if value <= 0)
    equity = peak = drawdown = 0.0
    for value in pnls:
        equity += value
        peak = max(peak, equity)
        drawdown = max(drawdown, peak - equity)
    return {
        "trades": len(pnls),
        "total_pnl": round(sum(pnls), 2),
        "expectancy": round(sum(pnls) / len(pnls), 2),
        "win_rate": round(sum(value > 0 for value in pnls) / len(pnls), 4),
        "profit_factor": round(wins / losses, 4) if losses > 0 else None,
        "max_drawdown": round(drawdown, 2),
    }


def build_report(csv_path: Path = DEFAULT_CSV) -> dict:
    candles = load_candles_csv(csv_path)
    dates = sorted({candle.timestamp.date().isoformat() for candle in candles})
    development_end = int(len(dates) * 0.70)
    selection_end = int(len(dates) * 0.85)
    splits = {
        "development": set(dates[:development_end]),
        "selection": set(dates[development_end:selection_end]),
        "final": set(dates[selection_end:]),
    }
    result = run_backtest(
        candles,
        orb_config=OpeningRangeConfig(
            reward_risk=2.0,
            max_risk_per_trade=100.0,
            max_contracts=1,
        ),
        bt_config=BacktestConfig(
            signal_type="lsm",
            slippage_ticks=1,
            commission_per_rt=3.73,
            max_trades_per_day=1,
            session_entry_start_hour=9,
            session_entry_start_minute=45,
            session_entry_cutoff_hour=11,
            session_entry_cutoff_minute=0,
        ),
        symbol="MES",
    )
    by_split = {
        name: [trade for trade in result.trades if trade.date in split_dates]
        for name, split_dates in splits.items()
    }
    summaries = {name: summarize(rows) for name, rows in by_split.items()}
    stress = {
        name: summarize(rows, extra_friction=BASELINE_FRICTION)
        for name, rows in by_split.items()
    }
    development_pass = (
        summaries["development"]["trades"] >= 30
        and (summaries["development"]["expectancy"] or 0) > 0
        and (summaries["development"]["profit_factor"] or 0) >= 1.20
        and (stress["development"]["expectancy"] or 0) > 0
    )
    selection_pass = (
        summaries["selection"]["trades"] >= 30
        and (summaries["selection"]["expectancy"] or 0) > 0
        and (summaries["selection"]["profit_factor"] or 0) >= 1.20
        and (stress["selection"]["expectancy"] or 0) > 0
    )
    final_pass = (
        summaries["final"]["trades"] >= 30
        and (summaries["final"]["expectancy"] or 0) > 0
        and (summaries["final"]["profit_factor"] or 0) >= 1.20
        and (stress["final"]["expectancy"] or 0) > 0
    )
    return {
        "experiment": "LIQUIDITY-SWEEP-MSS-RETEST-01",
        "specification": SPEC,
        "audit_type": "retrospective_public_rule_replication",
        "mode": "research_only",
        "execution_enabled": False,
        "can_submit_orders": False,
        "dataset": csv_path.name,
        "dataset_sessions": len(dates),
        "rule": {
            "liquidity": "prior-day or completed 15-minute opening-range high/low",
            "confirmation": "completed 5-minute MSS with >=0.5 recent-range body and classic FVG",
            "entry": "first FVG-midpoint retest that closes back in trade direction, 09:45-11:00 ET",
            "stop": "one tick beyond swept extreme",
            "target": "2R",
            "max_trades_per_day": 1,
        },
        "baseline_friction_dollars": BASELINE_FRICTION,
        "all_periods": summaries,
        "all_periods_2x_friction": stress,
        "gates": {
            "development_pass": development_pass,
            "selection_pass": selection_pass,
            "final_pass": final_pass,
        },
        "promotion_eligible": bool(development_pass and selection_pass and final_pass),
        "verdict": "rejected_out_of_sample" if not (development_pass and selection_pass and final_pass) else "historical_candidate_only",
        "warning": "Selected social-media winners are hypotheses, not a complete cost-adjusted trade ledger.",
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--csv", type=Path, default=DEFAULT_CSV)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--print", action="store_true", dest="print_report")
    args = parser.parse_args()
    report = build_report(args.csv)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    if args.print_report:
        print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()

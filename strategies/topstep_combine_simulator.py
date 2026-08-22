#!/usr/bin/env python3
"""Topstep-rule Trading Combine simulator for MES replay outcomes.

Research only. This module has no broker or Topstep API connection and cannot
submit orders. It applies the current 50K Combine target, consistency objective,
and end-of-day trailing Maximum Loss Limit to historical daily P&L paths.
"""
from __future__ import annotations

import argparse
import json
import math
import random
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from statistics import median

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from research.mes_futures_strategy_search import Candidate, _by_date, _chronological_partitions, _configs, _slice
from strategies.topstep_prop_bot import load_candles_csv
from strategies.topstep_replay_backtester import BacktestResult, run_backtest


DEFAULT_DATASET = ROOT / "examples" / "mes_v0_1m_2022-01-01_2026-07-19_rth.csv"
DEFAULT_OUTPUT = ROOT / "data" / "topstep_combine_simulation.json"

FROZEN_MES_CANDIDATE = Candidate(
    signal_type="orb",
    breakout_points=1.0,
    reward_risk=2.0,
    stop_ticks=40,
    tolerance_ticks=4,
    exit_model="full_target_stop",
    filter_name="gap",
    range_minutes=5,
)


@dataclass(frozen=True)
class CombineRules:
    starting_balance: float = 50_000.0
    profit_target: float = 3_000.0
    maximum_loss: float = 2_000.0
    consistency_pct: float = 0.50
    max_sessions: int = 252


@dataclass(frozen=True)
class CombineRun:
    status: str
    sessions: int
    ending_balance: float
    ending_profit: float
    maximum_loss_limit: float
    best_day_profit: float
    required_profit: float
    failure_reason: str | None = None


def _required_profit(rules: CombineRules, best_day_profit: float) -> float:
    consistency_target = best_day_profit / rules.consistency_pct if best_day_profit > 0 else 0.0
    return max(rules.profit_target, consistency_target)


def simulate_combine(daily_pnls: list[float], rules: CombineRules = CombineRules()) -> CombineRun:
    """Apply Topstep's EOD-trailing MLL and consistency-adjusted target.

    The input must contain one realized P&L value per market session, including
    zero for no-trade days. Intraday unrealized excursions are unavailable in
    bar-level replay, so this is an optimistic lower bound on MLL failures.
    """
    if not 0 < rules.consistency_pct <= 1:
        raise ValueError("consistency_pct must be in (0, 1]")
    if rules.maximum_loss <= 0 or rules.profit_target <= 0 or rules.max_sessions <= 0:
        raise ValueError("Combine limits and session horizon must be positive")

    balance = rules.starting_balance
    maximum_loss_limit = rules.starting_balance - rules.maximum_loss
    best_day_profit = 0.0

    for session, pnl in enumerate(daily_pnls[: rules.max_sessions], start=1):
        if not math.isfinite(pnl):
            raise ValueError("daily P&L values must be finite")
        balance += pnl
        best_day_profit = max(best_day_profit, pnl)
        required_profit = _required_profit(rules, best_day_profit)

        if balance <= maximum_loss_limit:
            return CombineRun(
                status="failed",
                sessions=session,
                ending_balance=round(balance, 2),
                ending_profit=round(balance - rules.starting_balance, 2),
                maximum_loss_limit=round(maximum_loss_limit, 2),
                best_day_profit=round(best_day_profit, 2),
                required_profit=round(required_profit, 2),
                failure_reason="maximum_loss_limit",
            )

        total_profit = balance - rules.starting_balance
        if total_profit >= required_profit:
            return CombineRun(
                status="passed",
                sessions=session,
                ending_balance=round(balance, 2),
                ending_profit=round(total_profit, 2),
                maximum_loss_limit=round(maximum_loss_limit, 2),
                best_day_profit=round(best_day_profit, 2),
                required_profit=round(required_profit, 2),
            )

        maximum_loss_limit = max(
            maximum_loss_limit,
            min(rules.starting_balance, balance - rules.maximum_loss),
        )

    required_profit = _required_profit(rules, best_day_profit)
    return CombineRun(
        status="incomplete",
        sessions=min(len(daily_pnls), rules.max_sessions),
        ending_balance=round(balance, 2),
        ending_profit=round(balance - rules.starting_balance, 2),
        maximum_loss_limit=round(maximum_loss_limit, 2),
        best_day_profit=round(best_day_profit, 2),
        required_profit=round(required_profit, 2),
    )


def _circular_block_sample(values: list[float], *, size: int, block_size: int, rng: random.Random) -> list[float]:
    if not values:
        raise ValueError("At least one historical session is required")
    if size <= 0 or block_size <= 0:
        raise ValueError("Sample and block sizes must be positive")
    sampled: list[float] = []
    while len(sampled) < size:
        start = rng.randrange(len(values))
        sampled.extend(values[(start + offset) % len(values)] for offset in range(block_size))
    return sampled[:size]


def _percentile(values: list[float], pct: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = int(round((len(ordered) - 1) * pct))
    return ordered[index]


def bootstrap_combine(
    daily_pnls: list[float],
    *,
    contracts: int,
    rules: CombineRules,
    simulations: int = 5_000,
    block_size: int = 20,
    seed: int = 20260809,
) -> dict[str, float | int | None]:
    if contracts <= 0 or simulations <= 0:
        raise ValueError("contracts and simulations must be positive")
    rng = random.Random(seed + contracts)
    runs = []
    for _ in range(simulations):
        path = _circular_block_sample(daily_pnls, size=rules.max_sessions, block_size=block_size, rng=rng)
        runs.append(simulate_combine([pnl * contracts for pnl in path], rules))

    passed = [run for run in runs if run.status == "passed"]
    failed = [run for run in runs if run.status == "failed"]
    endings = [run.ending_profit for run in runs]
    return {
        "contracts": contracts,
        "simulations": simulations,
        "pass_rate": round(len(passed) / simulations, 4),
        "mll_failure_rate": round(len(failed) / simulations, 4),
        "incomplete_rate": round(1 - (len(passed) + len(failed)) / simulations, 4),
        "median_sessions_to_pass": int(median(run.sessions for run in passed)) if passed else None,
        "ending_profit_p05": round(_percentile(endings, 0.05), 2),
        "ending_profit_p50": round(_percentile(endings, 0.50), 2),
        "ending_profit_p95": round(_percentile(endings, 0.95), 2),
    }


def _daily_pnls(result: BacktestResult, dates: list[str]) -> list[float]:
    by_date = {trade.date: trade.pnl for trade in result.trades}
    return [float(by_date.get(date, 0.0)) for date in dates]


def _result_summary(result: BacktestResult, session_count: int) -> dict[str, float | int]:
    return {
        "sessions": session_count,
        "trades": len(result.trades),
        "total_pnl": result.total_pnl,
        "expectancy_per_trade": result.expectancy,
        "expectancy_per_session": round(result.total_pnl / session_count, 4) if session_count else 0.0,
        "win_rate": result.win_rate,
        "profit_factor": result.profit_factor,
        "max_drawdown": result.max_drawdown,
    }


def build_report(
    dataset: Path = DEFAULT_DATASET,
    *,
    simulations: int = 5_000,
    max_sessions: int = 252,
) -> dict[str, object]:
    candles = load_candles_csv(dataset)
    dates, grouped = _by_date(candles)
    _, _, final_dates = _chronological_partitions(dates)
    final_candles = _slice(grouped, final_dates)

    orb, base_config = _configs(FROZEN_MES_CANDIDATE)
    base = run_backtest(final_candles, orb_config=orb, bt_config=base_config, symbol="MES")
    _, stress_config = _configs(FROZEN_MES_CANDIDATE, doubled_costs=True)
    stress = run_backtest(final_candles, orb_config=orb, bt_config=stress_config, symbol="MES")

    rules = CombineRules(max_sessions=max_sessions)
    base_daily = _daily_pnls(base, final_dates)
    stress_daily = _daily_pnls(stress, final_dates)
    base_grid = [
        bootstrap_combine(base_daily, contracts=contracts, rules=rules, simulations=simulations)
        for contracts in range(1, 11)
    ]
    stress_grid = [
        bootstrap_combine(stress_daily, contracts=contracts, rules=rules, simulations=simulations)
        for contracts in range(1, 11)
    ]

    safe_contracts = (1, 2)
    safe_stress = [row for row in stress_grid if row["contracts"] in safe_contracts]
    promotion_ready = (
        len(stress.trades) >= 100
        and stress.expectancy > 0
        and stress.profit_factor >= 1.20
        and max(float(row["pass_rate"]) for row in safe_stress) >= 0.60
        and min(float(row["mll_failure_rate"]) for row in safe_stress) <= 0.05
    )

    return {
        "provider": "topstep_combine_simulator",
        "mode": "research_only",
        "can_submit_orders": False,
        "dataset": str(dataset),
        "candidate": asdict(FROZEN_MES_CANDIDATE),
        "rules": asdict(rules),
        "untouched_final_test": {
            "base_cost": _result_summary(base, len(final_dates)),
            "double_cost": _result_summary(stress, len(final_dates)),
        },
        "bootstrap": {
            "method": "circular_block_bootstrap_of_untouched_daily_pnl_including_no_trade_sessions",
            "block_size_sessions": 20,
            "base_cost_contract_grid": base_grid,
            "double_cost_contract_grid": stress_grid,
        },
        "risk_policy": {
            "promotion_contracts": list(safe_contracts),
            "reason": "One MES fixed stop is about $50 before costs; two contracts cap planned loss near 5% of the $2,000 MLL.",
        },
        "promotion": {
            "ready": promotion_ready,
            "decision": "eligible_for_one_combine" if promotion_ready else "do_not_purchase_combine",
            "requirements": {
                "untouched_double_cost_trades": ">=100",
                "untouched_double_cost_expectancy": ">0",
                "untouched_double_cost_profit_factor": ">=1.20",
                "safe_contract_pass_rate": ">=0.60",
                "safe_contract_mll_failure_rate": "<=0.05",
            },
        },
        "limitations": [
            "Bar replay cannot observe every intraday unrealized excursion, so MLL failure rates are optimistic.",
            "Bootstrap paths resample historical outcomes; they do not create evidence or prove future profitability.",
            "The final-test sample is small and the candidate was selected using earlier partitions.",
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--simulations", type=int, default=5_000)
    parser.add_argument("--max-sessions", type=int, default=252)
    args = parser.parse_args()
    report = build_report(args.dataset, simulations=args.simulations, max_sessions=args.max_sessions)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

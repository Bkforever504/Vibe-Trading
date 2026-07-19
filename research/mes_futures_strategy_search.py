#!/usr/bin/env python3
"""Nested MES strategy search with an untouched chronological final test.

The script searches development windows, selects candidates on a later
validation window, and evaluates the selected set once on the final window.
It never routes orders or changes broker state.
"""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict, dataclass, replace
from itertools import product
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from strategies.topstep_prop_bot import OpeningRangeConfig, load_candles_csv
from strategies.topstep_replay_backtester import BacktestConfig, BacktestResult, run_backtest


FILTERS: dict[str, dict[str, Any]] = {
    "none": {},
    "gap": {"require_opening_gap_bias": True},
    "vix16_24": {"require_vix_range": True, "vix_min": 16.0, "vix_max": 24.0},
    "trend20": {"require_daily_trend_confirm": True, "daily_trend_sma_days": 20},
    "ema20": {"require_ema_confirm": True, "ema_period": 20},
    "live_vwap": {"require_live_vwap_confirm": True},
    "volume12": {"require_volume_confirm": True, "volume_lookback": 10, "min_volume_ratio": 1.2},
    "gap_vix": {
        "require_opening_gap_bias": True,
        "require_vix_range": True,
        "vix_min": 16.0,
        "vix_max": 24.0,
    },
    "trend_vix": {
        "require_daily_trend_confirm": True,
        "daily_trend_sma_days": 20,
        "require_vix_range": True,
        "vix_min": 16.0,
        "vix_max": 24.0,
    },
    "ema_volume": {
        "require_ema_confirm": True,
        "ema_period": 20,
        "require_volume_confirm": True,
        "volume_lookback": 10,
        "min_volume_ratio": 1.2,
    },
}


@dataclass(frozen=True)
class Candidate:
    signal_type: str
    breakout_points: float
    reward_risk: float
    stop_ticks: int
    tolerance_ticks: int
    exit_model: str
    filter_name: str
    range_minutes: int = 1


def _by_date(candles: list) -> tuple[list[str], dict[str, list]]:
    grouped: dict[str, list] = {}
    for candle in candles:
        grouped.setdefault(candle.timestamp.date().isoformat(), []).append(candle)
    return sorted(grouped), grouped


def _slice(grouped: dict[str, list], dates: list[str]) -> list:
    return [candle for date in dates for candle in grouped[date]]


def _chronological_partitions(dates: list[str]) -> tuple[list[str], list[str], list[str]]:
    development_end = int(len(dates) * 0.70)
    selection_end = int(len(dates) * 0.85)
    return dates[:development_end], dates[development_end:selection_end], dates[selection_end:]


def _configs(candidate: Candidate, *, doubled_costs: bool = False) -> tuple[OpeningRangeConfig, BacktestConfig]:
    orb = OpeningRangeConfig(
        range_minutes=candidate.range_minutes,
        min_breakout_points=candidate.breakout_points,
        reward_risk=candidate.reward_risk,
    )
    kwargs = FILTERS[candidate.filter_name]
    bt = BacktestConfig(
        slippage_ticks=2 if doubled_costs else 1,
        commission_per_rt=8.0 if doubled_costs else 4.0,
        max_trades_per_day=1,
        daily_loss_limit=100.0,
        session_entry_cutoff_hour=13,
        # Mirror the NinjaTrader ATM bracket for every signal type. Pullback
        # geometry decides whether to enter, never the dollars at risk.
        fixed_stop_ticks=candidate.stop_ticks,
        signal_type=candidate.signal_type,
        pullback_tolerance_ticks=candidate.tolerance_ticks,
        pullback_stop_ticks=candidate.stop_ticks,
        exit_model=candidate.exit_model,
        vix_csv_path=str(ROOT / "examples" / "vix_daily.csv"),
        **kwargs,
    )
    return orb, bt


def _metrics(result: BacktestResult, *, market_days: int) -> dict[str, Any]:
    return {
        "trades": result.days_traded,
        "total_pnl": result.total_pnl,
        "daily_average": round(result.total_pnl / market_days, 4) if market_days else 0.0,
        "expectancy": result.expectancy,
        "win_rate": result.win_rate,
        "profit_factor": result.profit_factor,
        "max_drawdown": result.max_drawdown,
        "violations": len(result.rule_violations),
    }


def _candidate_grid(*, executable_only: bool = False, max_stop_ticks: int | None = None) -> list[Candidate]:
    candidates: list[Candidate] = []
    stop_ticks = tuple(value for value in (20, 40, 60, 80) if max_stop_ticks is None or value <= max_stop_ticks)
    exit_models = ("full_target_stop",) if executable_only else ("full_target_stop", "partial_1r_be_2r")
    for signal_type, range_minutes, breakout, rr, stop, exit_model, filter_name in product(
        ("orb", "pullback"),
        (5, 15, 30),
        (1.0, 3.0, 5.0, 8.0, 12.0),
        (1.0, 1.5, 2.0, 2.5),
        stop_ticks,
        exit_models,
        tuple(FILTERS),
    ):
        tolerances = (4,) if signal_type == "orb" else (4, 8, 16)
        for tolerance in tolerances:
            candidates.append(
                Candidate(
                    signal_type,
                    breakout,
                    rr,
                    stop,
                    tolerance,
                    exit_model,
                    filter_name,
                    range_minutes,
                )
            )
    return candidates


def run_search(
    csv_path: Path,
    *,
    finalist_count: int = 40,
    executable_only: bool = False,
    max_stop_ticks: int | None = None,
) -> dict[str, Any]:
    candles = load_candles_csv(csv_path)
    dates, grouped = _by_date(candles)
    if len(dates) < 200:
        raise ValueError("Deep search requires at least 200 trading dates")

    development_dates, selection_dates, final_test_dates = _chronological_partitions(dates)
    cut1 = len(development_dates) // 3
    cut2 = cut1 * 2
    windows = (
        development_dates[:cut1],
        development_dates[cut1:cut2],
        development_dates[cut2:],
    )
    window_candles = [_slice(grouped, window) for window in windows]

    ranked: list[tuple[float, Candidate, list[dict[str, Any]]]] = []
    candidate_grid = _candidate_grid(executable_only=executable_only, max_stop_ticks=max_stop_ticks)
    for candidate in candidate_grid:
        orb, bt = _configs(candidate)
        metrics: list[dict[str, Any]] = []
        valid = True
        for window, subset in zip(windows, window_candles):
            result = run_backtest(subset, orb_config=orb, bt_config=bt, symbol="MES")
            row = _metrics(result, market_days=len(window))
            metrics.append(row)
            if row["trades"] < 8 or row["expectancy"] <= 0 or row["profit_factor"] < 1.05:
                valid = False
                break
        if not valid:
            continue
        min_expectancy = min(row["expectancy"] for row in metrics)
        worst_drawdown = max(row["max_drawdown"] for row in metrics)
        total_trades = sum(row["trades"] for row in metrics)
        daily_average = min(row["daily_average"] for row in metrics)
        score = min_expectancy + daily_average * 2 + min(total_trades, 100) * 0.03 - worst_drawdown * 0.01
        ranked.append((score, candidate, metrics))

    ranked.sort(key=lambda item: item[0], reverse=True)
    finalists = ranked[:finalist_count]
    selection_candles = _slice(grouped, selection_dates)
    final_test_candles = _slice(grouped, final_test_dates)
    development_candles = _slice(grouped, development_dates)
    results: list[dict[str, Any]] = []
    for score, candidate, regime_metrics in finalists:
        orb, bt = _configs(candidate)
        dev = run_backtest(development_candles, orb_config=orb, bt_config=bt, symbol="MES")
        selection = run_backtest(selection_candles, orb_config=orb, bt_config=bt, symbol="MES")
        _, stress_bt = _configs(candidate, doubled_costs=True)
        selection_stress = run_backtest(
            selection_candles,
            orb_config=orb,
            bt_config=stress_bt,
            symbol="MES",
        )
        results.append({
            "candidate": asdict(candidate),
            "development_score": round(score, 4),
            "development_regimes": regime_metrics,
            "development": _metrics(dev, market_days=len(development_dates)),
            "selection": _metrics(selection, market_days=len(selection_dates)),
            "selection_double_costs": _metrics(selection_stress, market_days=len(selection_dates)),
        })

    selected = [
        row for row in results
        if row["selection"]["trades"] >= 10
        and row["selection"]["expectancy"] > 0
        and row["selection"]["profit_factor"] >= 1.10
        and row["selection_double_costs"]["expectancy"] > 0
        and row["selection_double_costs"]["profit_factor"] >= 1.05
    ]
    selected.sort(
        key=lambda row: (
            min(row["selection"]["expectancy"], row["selection_double_costs"]["expectancy"]),
            -row["selection"]["max_drawdown"],
        ),
        reverse=True,
    )

    # Candidate selection is complete before these bars are touched. Do not
    # reorder or filter this list using final-test performance.
    final_results: list[dict[str, Any]] = []
    for row in selected:
        candidate = Candidate(**row["candidate"])
        orb, bt = _configs(candidate)
        final_test = run_backtest(final_test_candles, orb_config=orb, bt_config=bt, symbol="MES")
        _, stress_bt = _configs(candidate, doubled_costs=True)
        final_stress = run_backtest(
            final_test_candles,
            orb_config=orb,
            bt_config=stress_bt,
            symbol="MES",
        )
        final_results.append({
            **row,
            "final_test": _metrics(final_test, market_days=len(final_test_dates)),
            "final_test_double_costs": _metrics(final_stress, market_days=len(final_test_dates)),
        })

    return {
        "dataset": str(csv_path),
        "trading_dates": len(dates),
        "development_dates": len(development_dates),
        "selection_dates": len(selection_dates),
        "untouched_final_test_dates": len(final_test_dates),
        "grid_candidates": len(candidate_grid),
        "executable_only": executable_only,
        "max_stop_ticks": max_stop_ticks,
        "development_survivors": len(ranked),
        "selection_survivors": len(selected),
        "robust_finalists": final_results,
        "all_finalists": results,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Nested MES strategy search")
    parser.add_argument("--csv", type=Path, default=ROOT / "examples" / "es_1h_730d_fresh.csv")
    parser.add_argument("--finalists", type=int, default=40)
    parser.add_argument("--executable-only", action="store_true")
    parser.add_argument("--max-stop-ticks", type=int)
    parser.add_argument("--out", type=Path, default=ROOT / "data" / "mes_strategy_search_results.json")
    args = parser.parse_args()
    report = run_search(
        args.csv,
        finalist_count=args.finalists,
        executable_only=args.executable_only,
        max_stop_ticks=args.max_stop_ticks,
    )
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=2, default=str) + "\n", encoding="utf-8")
    print(json.dumps({key: value for key, value in report.items() if key not in {"robust_finalists", "all_finalists"}}, indent=2))
    for row in report["robust_finalists"][:10]:
        print(json.dumps(row, default=str))


if __name__ == "__main__":
    main()

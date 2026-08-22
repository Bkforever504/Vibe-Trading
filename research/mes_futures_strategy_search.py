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
from concurrent.futures import ProcessPoolExecutor
from dataclasses import asdict, dataclass, replace
from datetime import date
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
    "gap_vwap": {
        "require_opening_gap_bias": True,
        "require_live_vwap_confirm": True,
    },
    "gap_ema20": {
        "require_opening_gap_bias": True,
        "require_ema_confirm": True,
        "ema_period": 20,
    },
    "gap_vwap_ema": {
        "require_opening_gap_bias": True,
        "require_live_vwap_confirm": True,
        "require_ema_confirm": True,
        "ema_period": 20,
    },
    "trend_vwap": {
        "require_daily_trend_confirm": True,
        "require_live_vwap_confirm": True,
    },
    "gap_trend_vwap": {
        "require_opening_gap_bias": True,
        "require_daily_trend_confirm": True,
        "require_live_vwap_confirm": True,
    },
    "vwap_volume": {
        "require_live_vwap_confirm": True,
        "require_volume_confirm": True,
        "volume_lookback": 10,
        "min_volume_ratio": 1.2,
    },
    "gap_vwap_volume": {
        "require_opening_gap_bias": True,
        "require_live_vwap_confirm": True,
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
    crb_start_hour: int = 9
    crb_start_minute: int = 30


def _by_date(candles: list) -> tuple[list[str], dict[str, list]]:
    grouped: dict[str, list] = {}
    for candle in candles:
        grouped.setdefault(candle.timestamp.date().isoformat(), []).append(candle)
    return sorted(grouped), grouped


def _slice(grouped: dict[str, list], dates: list[str]) -> list:
    return [candle for date in dates for candle in grouped[date]]


def _trim_candles_from_start(candles: list, start_date: str | None) -> tuple[list, str | None]:
    if start_date is None:
        return candles, None
    try:
        parsed = date.fromisoformat(start_date)
    except ValueError as exc:
        raise ValueError("start_date must be an ISO date in YYYY-MM-DD format") from exc
    normalized = parsed.isoformat()
    return [candle for candle in candles if candle.timestamp.date() >= parsed], normalized


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
    cutoff_hour = 15 if candidate.signal_type == "crb" else 13
    # fbf/vdf use natural stops derived from signal geometry; stop_ticks=0 means no override
    natural_stop = candidate.signal_type in ("fbf", "vdf") or candidate.stop_ticks == 0
    bt = BacktestConfig(
        slippage_ticks=2 if doubled_costs else 1,
        commission_per_rt=8.0 if doubled_costs else 4.0,
        max_trades_per_day=1,
        daily_loss_limit=100.0,
        session_entry_cutoff_hour=cutoff_hour,
        fixed_stop_ticks=None if natural_stop else candidate.stop_ticks,
        signal_type=candidate.signal_type,
        pullback_tolerance_ticks=candidate.tolerance_ticks,
        pullback_stop_ticks=candidate.stop_ticks,
        exit_model=candidate.exit_model,
        vix_csv_path=str(ROOT / "examples" / "vix_daily.csv"),
        crb_range_start_hour=candidate.crb_start_hour,
        crb_range_start_minute=candidate.crb_start_minute,
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


def _trade_path_signature(result: BacktestResult) -> tuple[tuple[Any, ...], ...]:
    return tuple(
        (
            trade.date,
            trade.entry_time.isoformat(),
            trade.exit_time.isoformat() if trade.exit_time else None,
            trade.side,
            trade.entry_price,
            trade.exit_price,
            trade.pnl,
            trade.exit_reason,
        )
        for trade in result.trades
    )


def _take_unique_finalists(
    ranked: list[tuple[float, Candidate, list[dict[str, Any]], tuple[tuple[tuple[Any, ...], ...], ...]]],
    finalist_count: int,
) -> tuple[
    list[tuple[float, Candidate, list[dict[str, Any]], tuple[tuple[tuple[Any, ...], ...], ...]]],
    int,
]:
    selected = []
    seen: set[tuple[tuple[tuple[Any, ...], ...], ...]] = set()
    duplicates = 0
    for row in ranked:
        signature = row[3]
        if signature in seen:
            duplicates += 1
            continue
        seen.add(signature)
        selected.append(row)
        if len(selected) >= finalist_count:
            break
    return selected, duplicates


def _candidate_grid(*, executable_only: bool = False, max_stop_ticks: int | None = None) -> list[Candidate]:
    candidates: list[Candidate] = []
    stop_ticks = tuple(value for value in (20, 40, 60, 80) if max_stop_ticks is None or value <= max_stop_ticks)
    exit_models = ("full_target_stop",) if executable_only else ("full_target_stop", "partial_1r_be_2r")

    # ORB / pullback grid (opening session)
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
                    signal_type, breakout, rr, stop, tolerance,
                    exit_model, filter_name, range_minutes,
                )
            )

    # CRB grid — intraday consolidation range breakout at various afternoon windows
    crb_windows = ((10, 30), (11, 0), (11, 30), (12, 0), (13, 0))
    for (crb_h, crb_m), range_minutes, breakout, rr, stop, exit_model, filter_name in product(
        crb_windows,
        (30, 60),
        (1.0, 3.0, 5.0),
        (1.0, 1.5, 2.0, 2.5),
        stop_ticks,
        exit_models,
        tuple(FILTERS),
    ):
        candidates.append(
            Candidate(
                "crb", breakout, rr, stop, 4,
                exit_model, filter_name, range_minutes,
                crb_start_hour=crb_h, crb_start_minute=crb_m,
            )
        )

    # FBF grid — false breakout fade (natural stop from signal geometry)
    # stop_ticks=0 signals "use natural stop" in _configs
    for range_minutes, breakout, rr, exit_model, filter_name in product(
        (5, 15, 30),
        (0.5, 1.0, 2.0, 3.0),
        (1.0, 1.5, 2.0, 2.5),
        exit_models,
        tuple(FILTERS),
    ):
        candidates.append(
            Candidate("fbf", breakout, rr, 0, 4, exit_model, filter_name, range_minutes)
        )

    # VDF grid — VWAP deviation fade (natural stop from signal geometry)
    # breakout_points repurposed as deviation_points threshold
    for deviation, rr, exit_model, filter_name in product(
        (3.0, 4.0, 5.0, 6.0, 8.0),
        (1.0, 1.5, 2.0, 2.5),
        exit_models,
        tuple(FILTERS),
    ):
        candidates.append(
            Candidate("vdf", deviation, rr, 0, 4, exit_model, filter_name, 5)
        )

    # Delta Fingerprint grid — order flow proxy + VWAP entry
    # breakout_points = delta_threshold × 10 (so 1.0→0.10, 2.0→0.20, 3.0→0.30)
    # range_minutes = regime window (how many bars to compute delta over)
    for range_minutes, delta_scaled, rr, exit_model, filter_name in product(
        (15, 30, 45),           # regime window bars
        (1.0, 1.5, 2.0, 3.0),  # delta threshold × 10
        (1.0, 1.5, 2.0, 2.5),
        exit_models,
        tuple(FILTERS),
    ):
        candidates.append(
            Candidate("delta", delta_scaled, rr, 0, 4, exit_model, filter_name, range_minutes)
        )

    return candidates


_WORKER_WINDOWS: tuple[list[str], ...] = ()
_WORKER_CANDLES: tuple[list, ...] = ()


def _initialize_development_worker(windows: tuple[list[str], ...], window_candles: tuple[list, ...]) -> None:
    global _WORKER_WINDOWS, _WORKER_CANDLES
    _WORKER_WINDOWS = windows
    _WORKER_CANDLES = window_candles


def _evaluate_development_candidate(
    candidate: Candidate,
    windows: tuple[list[str], ...],
    window_candles: tuple[list, ...],
) -> tuple[
    float,
    Candidate,
    list[dict[str, Any]],
    tuple[tuple[tuple[Any, ...], ...], ...],
] | None:
    orb, bt = _configs(candidate)
    metrics: list[dict[str, Any]] = []
    signatures: list[tuple[tuple[Any, ...], ...]] = []
    for window, subset in zip(windows, window_candles):
        result = run_backtest(subset, orb_config=orb, bt_config=bt, symbol="MES")
        row = _metrics(result, market_days=len(window))
        metrics.append(row)
        signatures.append(_trade_path_signature(result))
        if row["trades"] < 8 or row["expectancy"] <= 0 or row["profit_factor"] < 1.05:
            return None
    min_expectancy = min(row["expectancy"] for row in metrics)
    worst_drawdown = max(row["max_drawdown"] for row in metrics)
    total_trades = sum(row["trades"] for row in metrics)
    daily_average = min(row["daily_average"] for row in metrics)
    score = min_expectancy + daily_average * 2 + min(total_trades, 100) * 0.03 - worst_drawdown * 0.01
    return score, candidate, metrics, tuple(signatures)


def _evaluate_development_candidate_worker(candidate: Candidate):
    return _evaluate_development_candidate(candidate, _WORKER_WINDOWS, _WORKER_CANDLES)


def run_search(
    csv_path: Path,
    *,
    finalist_count: int = 40,
    executable_only: bool = False,
    max_stop_ticks: int | None = None,
    start_date: str | None = None,
    workers: int = 1,
) -> dict[str, Any]:
    if workers < 1:
        raise ValueError("workers must be positive")
    candles = load_candles_csv(csv_path)
    candles, normalized_start_date = _trim_candles_from_start(candles, start_date)
    dates, grouped = _by_date(candles)
    if len(dates) < 200:
        raise ValueError("Deep search requires at least 200 trading dates")

    development_dates, selection_dates, final_test_dates = _chronological_partitions(dates)
    cut1 = len(development_dates) // 3
    cut2 = cut1 * 2
    windows: tuple[list[str], ...] = (
        development_dates[:cut1],
        development_dates[cut1:cut2],
        development_dates[cut2:],
    )
    window_candles = tuple(_slice(grouped, window) for window in windows)

    ranked: list[
        tuple[
            float,
            Candidate,
            list[dict[str, Any]],
            tuple[tuple[tuple[Any, ...], ...], ...],
        ]
    ] = []
    candidate_grid = _candidate_grid(executable_only=executable_only, max_stop_ticks=max_stop_ticks)
    if workers == 1:
        evaluated = (
            _evaluate_development_candidate(candidate, windows, window_candles)
            for candidate in candidate_grid
        )
        ranked.extend(row for row in evaluated if row is not None)
    else:
        with ProcessPoolExecutor(
            max_workers=workers,
            initializer=_initialize_development_worker,
            initargs=(windows, window_candles),
        ) as executor:
            evaluated = executor.map(_evaluate_development_candidate_worker, candidate_grid, chunksize=16)
            ranked.extend(row for row in evaluated if row is not None)

    ranked.sort(key=lambda item: item[0], reverse=True)
    finalists, duplicate_behaviors_skipped = _take_unique_finalists(ranked, finalist_count)
    selection_candles = _slice(grouped, selection_dates)
    final_test_candles = _slice(grouped, final_test_dates)
    development_candles = _slice(grouped, development_dates)
    results: list[dict[str, Any]] = []
    for score, candidate, regime_metrics, _ in finalists:
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
        "requested_start_date": normalized_start_date,
        "effective_period": [dates[0], dates[-1]],
        "evidence_status": (
            "diagnostic_consumed_period_not_independent_validation"
            if normalized_start_date
            else "historical_nested_backtest"
        ),
        "execution_enabled": False,
        "can_submit_orders": False,
        "trading_dates": len(dates),
        "development_dates": len(development_dates),
        "selection_dates": len(selection_dates),
        "untouched_final_test_dates": len(final_test_dates),
        "grid_candidates": len(candidate_grid),
        "executable_only": executable_only,
        "max_stop_ticks": max_stop_ticks,
        "development_workers": workers,
        "development_survivors": len(ranked),
        "unique_development_finalists": len(finalists),
        "duplicate_development_behaviors_skipped": duplicate_behaviors_skipped,
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
    parser.add_argument("--start-date", type=str, help="ISO date (YYYY-MM-DD) to trim candles before this date")
    parser.add_argument("--workers", type=int, default=1, help="Local development-search worker processes")
    parser.add_argument("--out", type=Path, default=ROOT / "data" / "mes_strategy_search_results.json")
    args = parser.parse_args()
    report = run_search(
        args.csv,
        finalist_count=args.finalists,
        executable_only=args.executable_only,
        max_stop_ticks=args.max_stop_ticks,
        start_date=args.start_date,
        workers=args.workers,
    )
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=2, default=str) + "\n", encoding="utf-8")
    print(json.dumps({key: value for key, value in report.items() if key not in {"robust_finalists", "all_finalists"}}, indent=2))
    for row in report["robust_finalists"][:10]:
        print(json.dumps(row, default=str))


if __name__ == "__main__":
    main()

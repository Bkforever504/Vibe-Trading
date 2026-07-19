#!/usr/bin/env python3
"""Preregistered MES first-30-minute to final-30-minute momentum test."""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict, dataclass
from datetime import time
from itertools import product
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from strategies.topstep_prop_bot import Candle, load_candles_csv

POINT_VALUE = 5.0
TICK_SIZE = 0.25
STANDARD_COST = 4.0 + 2 * 1.25
DOUBLE_COST = 8.0 + 4 * 1.25


@dataclass(frozen=True)
class CloseMomentumConfig:
    opening_threshold_pct: float
    stop_ticks: int


def _by_date(candles: list[Candle]) -> tuple[list[str], dict[str, list[Candle]]]:
    grouped: dict[str, list[Candle]] = {}
    for candle in candles:
        grouped.setdefault(candle.timestamp.date().isoformat(), []).append(candle)
    return sorted(grouped), grouped


def chronological_partitions(dates: list[str]) -> tuple[list[str], list[str], list[str]]:
    development_end = int(len(dates) * 0.70)
    selection_end = int(len(dates) * 0.85)
    return dates[:development_end], dates[development_end:selection_end], dates[selection_end:]


def _daily_setup(bars: list[Candle]) -> dict[str, object] | None:
    ordered = sorted(bars, key=lambda bar: bar.timestamp)
    by_time = {bar.timestamp.time(): bar for bar in ordered}
    open_bar = by_time.get(time(9, 30))
    signal_bar = by_time.get(time(9, 59))
    entry_bar = by_time.get(time(15, 30))
    exit_bar = by_time.get(time(15, 59))
    if not all((open_bar, signal_bar, entry_bar, exit_bar)):
        return None
    final_bars = [bar for bar in ordered if time(15, 30) <= bar.timestamp.time() <= time(15, 59)]
    if len(final_bars) < 28 or open_bar.open <= 0:
        return None
    return {
        "date": open_bar.timestamp.date().isoformat(),
        "opening_return": signal_bar.close / open_bar.open - 1,
        "entry": entry_bar.open,
        "final_bars": final_bars,
    }


def _trade_pnl(
    setup: dict[str, object],
    config: CloseMomentumConfig,
    *,
    doubled_costs: bool,
    direction: str = "momentum",
) -> float | None:
    opening_return = float(setup["opening_return"])
    if abs(opening_return) < config.opening_threshold_pct or opening_return == 0:
        return None
    side = 1 if opening_return > 0 else -1
    if direction == "reversal":
        side *= -1
    elif direction != "momentum":
        raise ValueError(f"Unsupported direction: {direction}")
    entry = float(setup["entry"])
    stop_distance = config.stop_ticks * TICK_SIZE
    stop = entry - side * stop_distance
    exit_price = None
    final_bars = setup["final_bars"]
    assert isinstance(final_bars, list)
    for bar in final_bars:
        if side > 0 and bar.low <= stop:
            exit_price = min(bar.open, stop)
            break
        if side < 0 and bar.high >= stop:
            exit_price = max(bar.open, stop)
            break
    if exit_price is None:
        exit_price = final_bars[-1].close
    costs = DOUBLE_COST if doubled_costs else STANDARD_COST
    return round((exit_price - entry) * side * POINT_VALUE - costs, 2)


def simulate(
    setups: list[dict[str, object]],
    config: CloseMomentumConfig,
    *,
    doubled_costs: bool = False,
    direction: str = "momentum",
) -> dict[str, object]:
    pnls = [
        pnl
        for setup in setups
        if (pnl := _trade_pnl(setup, config, doubled_costs=doubled_costs, direction=direction)) is not None
    ]
    gross_profit = sum(value for value in pnls if value > 0)
    gross_loss = -sum(value for value in pnls if value < 0)
    equity = peak = max_drawdown = 0.0
    for pnl in pnls:
        equity += pnl
        peak = max(peak, equity)
        max_drawdown = max(max_drawdown, peak - equity)
    return {
        "trades": len(pnls),
        "total_pnl": round(sum(pnls), 2),
        "expectancy": round(sum(pnls) / len(pnls), 2) if pnls else 0.0,
        "win_rate": round(sum(value > 0 for value in pnls) / len(pnls), 4) if pnls else 0.0,
        "profit_factor": round(gross_profit / gross_loss, 4) if gross_loss else ("inf" if gross_profit else 0.0),
        "max_drawdown": round(max_drawdown, 2),
        "pnls": pnls,
    }


def _without_pnls(metrics: dict[str, object]) -> dict[str, object]:
    return {key: value for key, value in metrics.items() if key != "pnls"}


def run_lab(csv_path: Path) -> dict[str, object]:
    dates, grouped = _by_date(load_candles_csv(csv_path))
    setups_by_date = {date: setup for date in dates if (setup := _daily_setup(grouped[date])) is not None}
    usable_dates = [date for date in dates if date in setups_by_date]
    development_dates, selection_dates, final_dates = chronological_partitions(usable_dates)
    development = [setups_by_date[date] for date in development_dates]
    selection = [setups_by_date[date] for date in selection_dates]
    final_test = [setups_by_date[date] for date in final_dates]
    third = len(development) // 3
    regimes = (development[:third], development[third:third * 2], development[third * 2:])

    ranked: list[tuple[float, CloseMomentumConfig, list[dict[str, object]]]] = []
    development_results: list[dict[str, object]] = []
    for threshold, stop_ticks in product((0.0, 0.0005, 0.001, 0.002), (20, 40)):
        config = CloseMomentumConfig(threshold, stop_ticks)
        metrics = [simulate(regime, config) for regime in regimes]
        passed = not any(
            row["trades"] < 30
            or row["expectancy"] <= 0
            or row["profit_factor"] == "inf"
            or row["profit_factor"] < 1.05
            for row in metrics
        )
        development_results.append({
            "config": asdict(config),
            "passed": passed,
            "regimes": [_without_pnls(row) for row in metrics],
        })
        if not passed:
            continue
        score = min(float(row["expectancy"]) for row in metrics) - max(float(row["max_drawdown"]) for row in metrics) * 0.01
        ranked.append((score, config, metrics))
    ranked.sort(key=lambda item: item[0], reverse=True)

    selection_rows: list[dict[str, object]] = []
    for score, config, regime_metrics in ranked:
        base = simulate(selection, config)
        stress = simulate(selection, config, doubled_costs=True)
        selection_rows.append({
            "config": asdict(config),
            "development_score": round(score, 4),
            "development_regimes": [_without_pnls(row) for row in regime_metrics],
            "selection": _without_pnls(base),
            "selection_double_costs": _without_pnls(stress),
        })
    selected = [
        row for row in selection_rows
        if row["selection"]["trades"] >= 30  # type: ignore[index]
        and row["selection"]["expectancy"] > 0  # type: ignore[index]
        and row["selection"]["profit_factor"] != "inf"  # type: ignore[index]
        and row["selection"]["profit_factor"] >= 1.10  # type: ignore[index]
        and row["selection_double_costs"]["expectancy"] > 0  # type: ignore[index]
        and row["selection_double_costs"]["profit_factor"] != "inf"  # type: ignore[index]
        and row["selection_double_costs"]["profit_factor"] >= 1.05  # type: ignore[index]
    ]
    selected.sort(
        key=lambda row: (
            row["selection_double_costs"]["expectancy"],  # type: ignore[index]
            -row["selection"]["max_drawdown"],  # type: ignore[index]
        ),
        reverse=True,
    )

    # Selection order is frozen before final-test evaluation.
    final_results: list[dict[str, object]] = []
    for row in selected:
        config = CloseMomentumConfig(**row["config"])  # type: ignore[arg-type]
        base = simulate(final_test, config)
        stress = simulate(final_test, config, doubled_costs=True)
        final_results.append({
            **row,
            "final_test": _without_pnls(base),
            "final_test_double_costs": _without_pnls(stress),
        })

    return {
        "dataset": str(csv_path),
        "usable_sessions": len(usable_dates),
        "development_sessions": len(development),
        "selection_sessions": len(selection),
        "final_test_sessions": len(final_test),
        "grid_candidates": 8,
        "development_survivors": len(ranked),
        "selection_survivors": len(selected),
        "final_results": final_results,
        "development_results": development_results,
        "all_selection_results": selection_rows,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--csv", type=Path, required=True)
    parser.add_argument("--out", type=Path, default=ROOT / "data" / "mes_close_momentum_results.json")
    args = parser.parse_args()
    report = run_lab(args.csv)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({key: value for key, value in report.items() if key not in {"final_results", "development_results", "all_selection_results"}}, indent=2))
    for row in report["final_results"]:
        print(json.dumps(row))


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""Sequential confirmation of the preregistered MES close-reversal setup."""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from research.mes_close_momentum_lab import (
    CloseMomentumConfig,
    _by_date,
    _daily_setup,
    _without_pnls,
    chronological_partitions,
    simulate,
)
from strategies.topstep_prop_bot import load_candles_csv

FROZEN_CONFIG = CloseMomentumConfig(opening_threshold_pct=0.001, stop_ticks=40)


def passes(metrics: dict[str, object], stress: dict[str, object]) -> bool:
    return bool(
        metrics["trades"] >= 30
        and metrics["expectancy"] > 0
        and metrics["profit_factor"] != "inf"
        and metrics["profit_factor"] >= 1.20
        and metrics["max_drawdown"] <= 200
        and stress["expectancy"] > 0
        and stress["profit_factor"] != "inf"
        and stress["profit_factor"] >= 1.10
    )


def run_confirmation(csv_path: Path) -> dict[str, object]:
    dates, grouped = _by_date(load_candles_csv(csv_path))
    setups_by_date = {date: setup for date in dates if (setup := _daily_setup(grouped[date])) is not None}
    usable_dates = [date for date in dates if date in setups_by_date]
    _, selection_dates, final_dates = chronological_partitions(usable_dates)
    selection = [setups_by_date[date] for date in selection_dates]
    final_test = [setups_by_date[date] for date in final_dates]

    selection_base = simulate(selection, FROZEN_CONFIG, direction="reversal")
    selection_stress = simulate(selection, FROZEN_CONFIG, doubled_costs=True, direction="reversal")
    selection_passed = passes(selection_base, selection_stress)
    report: dict[str, object] = {
        "dataset": str(csv_path),
        "config": {**asdict(FROZEN_CONFIG), "direction": "reversal"},
        "selection_sessions": len(selection),
        "final_test_sessions_reserved": len(final_test),
        "selection": _without_pnls(selection_base),
        "selection_double_costs": _without_pnls(selection_stress),
        "selection_passed": selection_passed,
        "final_test_evaluated": False,
    }
    if not selection_passed:
        return report

    final_base = simulate(final_test, FROZEN_CONFIG, direction="reversal")
    final_stress = simulate(final_test, FROZEN_CONFIG, doubled_costs=True, direction="reversal")
    report.update({
        "final_test_evaluated": True,
        "final_test": _without_pnls(final_base),
        "final_test_double_costs": _without_pnls(final_stress),
        "final_test_passed": passes(final_base, final_stress),
        "final_trade_pnls": final_base["pnls"],
    })
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--csv", type=Path, required=True)
    parser.add_argument("--out", type=Path, default=ROOT / "data" / "mes_close_reversal_confirmation.json")
    args = parser.parse_args()
    report = run_confirmation(args.csv)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({key: value for key, value in report.items() if key != "final_trade_pnls"}, indent=2))


if __name__ == "__main__":
    main()

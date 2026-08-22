#!/usr/bin/env python3
"""Consolidate repository evidence across swing, intraday, scalping, and options styles."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "data" / "trading_style_tournament_report.json"


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def build_report() -> dict[str, Any]:
    htf = read_json(ROOT / "data" / "higher_timeframe_volume_screen_lab_rerun_2026-07-25.json")
    monthly = next(row for row in htf["rows"] if row["variant"] == "monthly_price_trend_baseline")
    gap = read_json(ROOT / "data" / "mes_opening_gap_fade_results.json")
    public = read_json(ROOT / "data" / "mes_public_strategy_replication_results.json")
    discovery = read_json(ROOT / "data" / "profitability_discovery_100_results.json")
    scalp = read_json(ROOT / "data" / "mes_ofi_scalping_results.json")
    first_mark = read_json(ROOT / "data" / "first_mark_gate_lab_results.json")["first_mark_green_review"]

    best_public = max(
        public["all_candidates"],
        key=lambda row: float(row["aggregate"]["base_cost"]["expectancy"]),
    )
    scalp_rows = {row["variant"]: row for row in scalp["results"]}
    styles = [
        {
            "style": "monthly_cross_sectional_swing_momentum",
            "horizon": "20 sessions",
            "instrument": "liquid US equity/ETF basket",
            "primary_metric": "final_expectancy_bps",
            "after_cost_expectancy": monthly["final_2024_plus"]["expectancy_bps"],
            "stress_expectancy": monthly["triple_cost_final_2024_plus"]["expectancy_bps"],
            "sample_size": monthly["final_2024_plus"]["periods"],
            "profit_factor": monthly["final_2024_plus"]["profit_factor"],
            "max_drawdown": monthly["final_2024_plus"]["max_drawdown_pct"],
            "top_tail_removed_positive": monthly["final_2024_plus"]["top_one_pct_removed_expectancy_bps"] > 0,
            "promotion_ready": bool(monthly["high_confidence_ready"]),
            "evidence_verdict": "research_leader_not_promotion_ready",
        },
        {
            "style": "mes_opening_gap_fade",
            "horizon": "intraday",
            "instrument": "MES",
            "primary_metric": "aggregate_2x_cost_expectancy_usd",
            "after_cost_expectancy": gap["top_diagnostic_candidate"]["aggregate_2x_cost"]["expectancy"],
            "stress_expectancy": gap["top_diagnostic_candidate"]["aggregate_3x_cost"]["expectancy"],
            "sample_size": gap["top_diagnostic_candidate"]["aggregate"]["trades"],
            "profit_factor": gap["top_diagnostic_candidate"]["aggregate_2x_cost"]["profit_factor"],
            "max_drawdown": gap["top_diagnostic_candidate"]["aggregate_2x_cost"]["max_drawdown"],
            "top_tail_removed_positive": gap["top_diagnostic_candidate"]["aggregate_2x_cost_without_top_1pct"]["expectancy"] > 0,
            "promotion_ready": bool(gap["promotion"]["ready"]),
            "evidence_verdict": "positive_but_only_eight_trades",
        },
        {
            "style": "best_public_mes_intraday_replication",
            "horizon": "intraday",
            "instrument": "MES",
            "primary_metric": "aggregate_base_cost_expectancy_usd",
            "after_cost_expectancy": best_public["aggregate"]["base_cost"]["expectancy"],
            "stress_expectancy": best_public["aggregate"]["double_cost"]["expectancy"],
            "sample_size": best_public["aggregate"]["base_cost"]["trades"],
            "profit_factor": best_public["aggregate"]["base_cost"]["profit_factor"],
            "max_drawdown": best_public["aggregate"]["base_cost"]["max_drawdown"],
            "top_tail_removed_positive": False,
            "promotion_ready": False,
            "evidence_verdict": "rejected_after_costs",
            "strategy": best_public["strategy"],
        },
        {
            "style": "mes_ofi_momentum_scalp",
            "horizon": "30 seconds",
            "instrument": "MES",
            "primary_metric": "final_stress_expectancy_usd",
            "after_cost_expectancy": scalp_rows["ofi_momentum_scalp"]["stages"]["final"]["base"]["expectancy"],
            "stress_expectancy": scalp_rows["ofi_momentum_scalp"]["stages"]["final"]["stress"]["expectancy"],
            "sample_size": scalp_rows["ofi_momentum_scalp"]["trade_count"],
            "profit_factor": scalp_rows["ofi_momentum_scalp"]["stages"]["final"]["stress"]["profit_factor"],
            "max_drawdown": scalp_rows["ofi_momentum_scalp"]["stages"]["final"]["stress"]["max_drawdown"],
            "top_tail_removed_positive": False,
            "promotion_ready": False,
            "evidence_verdict": "rejected_after_costs",
        },
        {
            "style": "mes_ofi_reversal_scalp",
            "horizon": "30 seconds",
            "instrument": "MES",
            "primary_metric": "final_stress_expectancy_usd",
            "after_cost_expectancy": scalp_rows["ofi_reversal_scalp"]["stages"]["final"]["base"]["expectancy"],
            "stress_expectancy": scalp_rows["ofi_reversal_scalp"]["stages"]["final"]["stress"]["expectancy"],
            "sample_size": scalp_rows["ofi_reversal_scalp"]["trade_count"],
            "profit_factor": scalp_rows["ofi_reversal_scalp"]["stages"]["final"]["stress"]["profit_factor"],
            "max_drawdown": scalp_rows["ofi_reversal_scalp"]["stages"]["final"]["stress"]["max_drawdown"],
            "top_tail_removed_positive": False,
            "promotion_ready": False,
            "evidence_verdict": "rejected_after_costs",
        },
        {
            "style": "zero_dte_first_mark_momentum_filter",
            "horizon": "0DTE intraday",
            "instrument": "equity options shadow candidates",
            "primary_metric": "midpoint_post_fee_expectancy_pct",
            "after_cost_expectancy": first_mark["stats"]["post_fee_expectancy_pct"],
            "stress_expectancy": first_mark["stats"]["doubled_cost_expectancy_pct"],
            "sample_size": first_mark["sample_size"],
            "profit_factor": first_mark["stats"]["profit_factor"],
            "max_drawdown": None,
            "top_tail_removed_positive": first_mark["stats"]["top5_removed_expectancy_pct"] > 0,
            "promotion_ready": False,
            "evidence_verdict": "midpoint_promising_executable_gate_failed",
            "unique_dates": first_mark["unique_dates"],
        },
    ]
    return {
        "schema_version": 1,
        "mode": "research_only",
        "execution_enabled": False,
        "can_submit_orders": False,
        "comparison_warning": "Metrics use different units and instruments; rank evidence quality, not raw numeric magnitude.",
        "most_profitable_research_style": "monthly_cross_sectional_swing_momentum",
        "promotion_ready_style": None,
        "scalping_verdict": "No tested retail-speed scalping edge survives executable fills and stress costs.",
        "intraday_search_summary": {
            "discovery_trials": discovery["trial_count"],
            "effective_attempts": discovery["effective_attempt_count"],
            "survivors": discovery["survivor_count"],
            "public_replication_families": public["family_attempts"],
            "public_replication_survivors": public["historical_survivor_count"],
        },
        "styles": styles,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=OUTPUT)
    args = parser.parse_args()
    report = build_report()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Route research attention using executable evidence, never orders."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
DEFAULT_OUTPUT = DATA / "edge_evidence_router_report.json"


def _load(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _call_spread_stats(attribution: dict[str, Any]) -> dict[str, Any]:
    values = []
    dates = set()
    for setup in attribution.get("setups", []):
        for expression in setup.get("expressions", []):
            if (
                expression.get("expression_type") == "component_call_spread"
                and expression.get("status") == "resolved"
                and expression.get("net_pnl_dollars") is not None
            ):
                values.append(float(expression["net_pnl_dollars"]))
                dates.add(str(setup.get("recorded_at", ""))[:10])
    return {
        "resolved_outcomes": len(values),
        "resolved_dates": len(dates - {""}),
        "aggregate_net_pnl_dollars": round(sum(values), 2),
        "win_rate": round(sum(value > 0 for value in values) / len(values), 4) if values else None,
    }


def build_report(data_dir: Path = DATA) -> dict[str, Any]:
    momentum = _load(data_dir / "momentum_edge_ensemble_results.json")
    options_execution = _load(data_dir / "options_limit_execution_lab_results.json")
    mes_ofi = _load(data_dir / "mes_ofi_scalping_results.json")
    atr = _load(data_dir / "spx_weekly_atr_put_spread_underlying_audit.json")
    attribution = _load(data_dir / "options_edge_attribution_report.json")

    aggressive = next(
        (row for row in options_execution.get("policies_ranked", []) if row.get("policy") == "aggressive_ask"),
        {},
    )
    pre_fee = aggressive.get("pre_fee", {}) if isinstance(aggressive.get("pre_fee"), dict) else {}
    mes_rows = mes_ofi.get("results", [])
    mes_survivors = sum(bool(row.get("shadow_candidate")) for row in mes_rows)
    recent_atr = (
        atr.get("summaries", {})
        .get("recent_2025_plus", {})
        .get("credit_2_48", {})
    )
    call_spreads = _call_spread_stats(attribution)
    momentum_passed = bool(momentum.get("gates", {}).get("all_pass"))

    lanes = [
        {
            "rank": 1,
            "lane": "momentum_edge_ensemble",
            "status": "forward_shadow_priority" if momentum_passed else "rejected",
            "evidence": {
                "historical_cagr_pct": momentum.get("overall", {}).get("cagr_pct"),
                "historical_max_drawdown_pct": momentum.get("overall", {}).get("max_drawdown_pct"),
                "double_cost_cagr_pct": momentum.get("double_cost", {}).get("overall", {}).get("cagr_pct"),
                "gate_passed": momentum_passed,
            },
            "next_gate": "12 completed monthly observations and 252 elapsed trading sessions",
            "execution_authority": False,
        },
        {
            "rank": 2,
            "lane": "weekly_minus_1atr_defined_risk_put_premium",
            "status": "historical_quote_collection_priority",
            "evidence": {
                "underlying_proxy_weeks": atr.get("sample", {}).get("proxy_trades"),
                "recent_settled_below_short_rate": recent_atr.get("settled_below_short_rate"),
                "recent_required_average_gross_credit_points": recent_atr.get("required_average_gross_credit_points"),
                "historical_option_quotes_available": False,
            },
            "next_gate": "point-in-time natural SPXW or XSP quotes plus 52 forward shadow weeks",
            "execution_authority": False,
        },
        {
            "rank": 3,
            "lane": "vrp_component_call_spread",
            "status": "paired_forward_collection",
            "evidence": call_spreads,
            "next_gate": "30 resolved outcomes across at least 20 distinct dates after executable friction",
            "execution_authority": False,
        },
        {
            "rank": 4,
            "lane": "mes_intraday_ofi",
            "status": "retired_as_income_candidate",
            "evidence": {
                "tested_variants": len(mes_rows),
                "trades_per_variant": mes_rows[0].get("trade_count") if mes_rows else None,
                "survivors": mes_survivors,
            },
            "reopen_only_if": "new information source and a new preregistered holdout",
            "execution_authority": False,
        },
        {
            "rank": 5,
            "lane": "aggressive_long_0dte_options",
            "status": "retired_as_income_candidate",
            "evidence": {
                "lifecycles": options_execution.get("total_lifecycles"),
                "unique_dates": options_execution.get("unique_dates"),
                "pre_fee_expectancy_pct": pre_fee.get("expectancy_per_attempt_pct"),
                "median_15m_bid_return_pct": options_execution.get("adverse_selection", {})
                .get("15m_bid_return_vs_entry_ask", {})
                .get("median_pct"),
            },
            "reopen_only_if": "a new signal is positive before fees on untouched executable quotes",
            "execution_authority": False,
        },
    ]
    return {
        "schema_version": 1,
        "mode": "read_only_evidence_routing",
        "execution_enabled": False,
        "can_submit_orders": False,
        "finding": (
            "The missing edge is horizon and payoff selection: slower diversified momentum survives costs; "
            "the current intraday long-option and MES signals do not."
        ),
        "lanes": lanes,
        "portfolio_policy": {
            "live_capital_changes_allowed": False,
            "daily_profit_target_supported": False,
            "failed_lanes_may_not_be_reenabled_by_confidence_score": True,
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path, default=DATA)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    report = build_report(args.data_dir)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

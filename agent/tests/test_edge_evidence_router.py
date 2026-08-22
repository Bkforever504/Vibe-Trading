import json

from scripts.edge_evidence_router import build_report


def _write(path, payload):
    path.write_text(json.dumps(payload), encoding="utf-8")


def test_router_retires_failed_intraday_and_never_grants_authority(tmp_path):
    _write(tmp_path / "momentum_edge_ensemble_results.json", {
        "gates": {"all_pass": True},
        "overall": {"cagr_pct": 10.0, "max_drawdown_pct": 20.0},
        "double_cost": {"overall": {"cagr_pct": 9.0}},
    })
    _write(tmp_path / "options_limit_execution_lab_results.json", {
        "total_lifecycles": 100,
        "unique_dates": 10,
        "policies_ranked": [{"policy": "aggressive_ask", "pre_fee": {"expectancy_per_attempt_pct": -2.0}}],
        "adverse_selection": {"15m_bid_return_vs_entry_ask": {"median_pct": -3.0}},
    })
    _write(tmp_path / "mes_ofi_scalping_results.json", {
        "results": [{"trade_count": 200, "shadow_candidate": False}],
    })
    _write(tmp_path / "spx_weekly_atr_put_spread_underlying_audit.json", {})
    _write(tmp_path / "options_edge_attribution_report.json", {"setups": []})

    report = build_report(tmp_path)
    lanes = {row["lane"]: row for row in report["lanes"]}

    assert report["execution_enabled"] is False
    assert report["can_submit_orders"] is False
    assert lanes["momentum_edge_ensemble"]["status"] == "forward_shadow_priority"
    assert lanes["mes_intraday_ofi"]["status"] == "retired_as_income_candidate"
    assert lanes["aggressive_long_0dte_options"]["status"] == "retired_as_income_candidate"
    assert all(row["execution_authority"] is False for row in report["lanes"])


def test_router_counts_only_resolved_component_call_spreads(tmp_path):
    _write(tmp_path / "options_edge_attribution_report.json", {
        "setups": [{
            "recorded_at": "2026-08-12T10:00:00Z",
            "expressions": [
                {"expression_type": "component_call_spread", "status": "resolved", "net_pnl_dollars": 11},
                {"expression_type": "component_put_spread", "status": "resolved", "net_pnl_dollars": 20},
                {"expression_type": "component_call_spread", "status": "open", "net_pnl_dollars": 99},
            ],
        }],
    })

    report = build_report(tmp_path)
    lane = next(row for row in report["lanes"] if row["lane"] == "vrp_component_call_spread")

    assert lane["evidence"]["resolved_outcomes"] == 1
    assert lane["evidence"]["aggregate_net_pnl_dollars"] == 11.0
    assert lane["evidence"]["win_rate"] == 1.0

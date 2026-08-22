#!/usr/bin/env python3
"""Fail-closed Topstep MES operations, evidence, and execution-readiness report."""
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = ROOT / "data" / "topstep_readiness_report.json"
DEFAULT_REPORTS = {
    "frozen_orb_combine": ROOT / "data" / "topstep_combine_simulation.json",
    "opening_gap_fade": ROOT / "data" / "mes_opening_gap_fade_results.json",
    "public_strategy_replication": ROOT / "data" / "mes_public_strategy_replication_results.json",
    "causal_impact_reversal": ROOT / "data" / "mes_causal_impact_reversal_results.json",
}


def _load_json(path: Path) -> dict[str, Any] | None:
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        return None
    return value if isinstance(value, dict) else None


def _env_presence(path: Path) -> dict[str, bool]:
    keys = {
        "TOPSTEPX_USERNAME": False,
        "TOPSTEPX_API_KEY": False,
        "TOPSTEPX_PRACTICE_ACCOUNT_ID": False,
        "TOPSTEPX_PRACTICE_EXECUTION": False,
        "TOPSTEPX_LOCAL_DEVICE": False,
    }
    try:
        lines = path.read_text(encoding="utf-8-sig").splitlines()
    except OSError:
        return keys
    for raw in lines:
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        if key in keys:
            keys[key] = bool(value.strip())
    return keys


def _promotion(report: dict[str, Any] | None) -> dict[str, Any]:
    if report is None:
        return {"ready": False, "decision": "report_missing_or_invalid"}
    promotion = report.get("promotion")
    if not isinstance(promotion, dict):
        return {"ready": False, "decision": "promotion_contract_missing"}
    return {
        "ready": promotion.get("ready") is True,
        "decision": str(promotion.get("decision") or "unspecified"),
        "requirements": promotion.get("requirements") or promotion.get("requirements_before_any_execution_change"),
    }


def build_report(
    *,
    report_paths: dict[str, Path] = DEFAULT_REPORTS,
    env_path: Path = ROOT / "agent" / ".env",
    probe_path: Path = Path.home() / ".vibe-trading" / "reports" / "topstepx-practice-probe.json",
    recorder_path: Path = ROOT / "data" / "topstepx_market_recorder_status.json",
    reconciliation_path: Path = ROOT / "data" / "topstepx_practice_reconciliation.json",
    route_path: Path = ROOT / "data" / "topstep_prior_date_route.json",
) -> dict[str, Any]:
    candidates = {
        name: {"source": str(path), **_promotion(_load_json(path))}
        for name, path in report_paths.items()
    }
    promoted = [name for name, row in candidates.items() if row["ready"]]
    env = _env_presence(env_path)
    probe = _load_json(probe_path) or {"status": "missing"}
    recorder = _load_json(recorder_path) or {"status": "missing"}
    reconciliation = _load_json(reconciliation_path) or {"status": "missing"}
    route = _load_json(route_path) or {"routing_status": "missing"}
    credential_ready = env["TOPSTEPX_USERNAME"] and env["TOPSTEPX_API_KEY"]
    local_device_ready = env["TOPSTEPX_LOCAL_DEVICE"]
    observation_ready = credential_ready and local_device_ready and recorder.get("status") == "ok"
    broker_evidence_ready = reconciliation.get("round_trip_count", 0) > 0

    blockers: list[str] = []
    if not credential_ready:
        blockers.append("topstepx_credentials_missing")
    if not local_device_ready:
        blockers.append("personal_device_confirmation_missing")
    if recorder.get("status") != "ok":
        blockers.append("market_recorder_not_collecting")
    if not broker_evidence_ready:
        blockers.append("no_broker_confirmed_round_trips")
    if not promoted:
        blockers.append("no_strategy_passed_promotion_gate")

    return {
        "schema_version": 1,
        "provider": "topstep_readiness_report",
        "generated_at_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "mode": "read_only_governance",
        "execution_enabled": False,
        "can_submit_orders": False,
        "overall_status": "blocked" if blockers else "eligible_for_separate_practice_review",
        "blockers": blockers,
        "operations": {
            "credential_fields_present": env,
            "practice_probe_status": probe.get("status"),
            "market_recorder_status": recorder.get("status"),
            "reconciliation_status": reconciliation.get("status"),
            "broker_confirmed_round_trips": reconciliation.get("round_trip_count", 0),
            "trade_shape_complete_count": reconciliation.get("trade_shape_complete_count", 0),
        },
        "strategy_evidence": {
            "promoted_candidate_count": len(promoted),
            "promoted_candidates": promoted,
            "candidates": candidates,
            "prior_date_route_status": route.get("routing_status"),
            "selected_shadow_candidate": route.get("selected_shadow_candidate"),
        },
        "current_rule_model": {
            "verified_as_of": "2026-08-17",
            "official_sources": [
                "https://help.topstep.com/en/articles/8284197-trading-combine-parameters",
                "https://help.topstep.com/en/articles/8284204-what-is-the-maximum-loss-limit",
                "https://help.topstep.com/en/articles/8284208-consistency-at-topstep",
                "https://help.topstep.com/en/articles/11187768-topstepx-api-access",
                "https://help.topstep.com/en/articles/10305426-prohibited-trading-strategies-at-topstep",
                "https://help.topstep.com/en/articles/8284213-topstepx-commissions-and-fees",
            ],
            "combine_50k_profit_target": 3000.0,
            "combine_50k_maximum_loss": 2000.0,
            "combine_best_day_target_pct": 0.50,
            "mll_trailing_method": "end_of_day_balance_high_water_mark",
            "mll_enforcement": "real_time_realized_plus_unrealized_pnl",
            "mes_topstepx_round_turn_fees": 1.22,
            "automation_constraints": [
                "personal_device_only",
                "no_vpn_vps_or_remote_server",
                "no_sim_fill_latency_or_queue_exploitation",
                "no_trading_outside_current_best_bid_or_offer",
            ],
        },
        "decision": (
            "Do not buy a Combine or enable Practice routing until credentials and market recording work, "
            "broker-confirmed outcomes exist, and a frozen candidate passes the promotion gate."
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    report = build_report()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

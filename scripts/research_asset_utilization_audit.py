"""Audit whether external research assets reached measurable bot utilization.

This is a read-only integration ledger. Presence of cloned code is never
treated as evidence that a capability is operational.
"""
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
VIBE_HOME = Path.home() / ".vibe-trading"
REPORT_PATH = VIBE_HOME / "reports" / "research-asset-utilization.json"
LOG_PATH = ROOT / "data" / "research_asset_utilization_log.jsonl"

ASSETS: list[dict[str, Any]] = [
    {
        "id": "kronos",
        "priority": 40,
        "capability": "K-line foundation-model forecast context",
        "source": ["research/external_repos/Kronos"],
        "intake": ["scripts/kronos_market_forecaster.py"],
        "adapter": ["scripts/kronos_market_forecaster.py"],
        "consumer": ["scripts/shadow_consensus_gate.py", "scripts/daily_edge_orchestrator.py"],
        "evidence": ["data/kronos_market_forecast_log.jsonl"],
        "next_action": "measure Kronos blocker lift and conflict accuracy by regime",
    },
    {
        "id": "pine_strategy_lab",
        "priority": 50,
        "capability": "strategy translation, leak checks, sweeps, and shadow indicators",
        "source": ["research/pine_sources", "research/pine_strategy_lab"],
        "intake": ["research/pine_strategy_lab/intake_batch_results_2026-06-28.md"],
        "adapter": ["scripts/pine_backtest_runner.py", "scripts/rsi2_shadow_logger.py"],
        "consumer": ["scripts/signal_stack_leaderboard.py", "scripts/overlap_report.py"],
        "evidence": ["data/rsi2_shadow_log.jsonl", "data/kama_shadow_log.jsonl"],
        "next_action": "promote only indicators with forward incremental lift after feature ablation",
    },
    {
        "id": "pmxt",
        "priority": 30,
        "capability": "normalized prediction-market schemas",
        "source": ["tools/pmxt-probe"],
        "intake": ["research/trading_automation_repo_scan_2026-06-30.md"],
        "adapter": ["scripts/pmxt_market_schema_probe.py"],
        "consumer": ["scripts/export_daily_bot_activity_csv.py"],
        "evidence": ["data/pmxt_market_schema_probe_log.jsonl"],
        "next_action": "compare normalized PMXT books with weather-bot CLOB parsing and settlement coverage",
    },
    {
        "id": "tradingview_mcp",
        "priority": 70,
        "capability": "chart, replay, indicator, and Pine validation tooling",
        "source": ["tools/tradingview-mcp"],
        "intake": ["research/claude_tradingview_mcp_trading_deep_dive_2026-06-30.md"],
        "adapter": ["scripts/tradingview_validation_report.py"],
        "consumer": ["strategies/trading_dashboard.py"],
        "evidence": [],
        "next_action": "persist replay-validation outcomes so chart review becomes promotion evidence",
    },
    {
        "id": "ai_trader",
        "priority": 90,
        "capability": "multi-agent debate, memory, and market-intelligence patterns",
        "source": ["research/external_repos/AI-Trader"],
        "intake": ["research/ai_trader_hkuds_deep_dive_2026-06-30.md"],
        "adapter": ["scripts/agent_trade_debate_report.py"],
        "consumer": [],
        "evidence": ["data/agent_trade_debate_log.jsonl"],
        "next_action": "score whether debate disagreement predicts Flip losses before connecting it to selection",
    },
    {
        "id": "investing_algorithm_framework",
        "priority": 60,
        "capability": "algorithm research and multi-asset probe patterns",
        "source": ["tools/investing_algorithm_framework_probe"],
        "intake": ["CODEx_CLAUDE_COLLAB/CLAUDE_HANDOFF_2026-07-01_BOT_EVALS_AND_IAF_PROBE.md"],
        "adapter": ["scripts/iaf_qqq_gld_probe.py"],
        "consumer": [],
        "evidence": [],
        "next_action": "either connect validated regime features to shadow evaluation or explicitly retire the probe",
    },
    {
        "id": "worldquant_alpha_lab",
        "priority": 80,
        "capability": "formulaic alpha generation and cross-sectional testing",
        "source": ["research/worldquant_alpha_lab.py"],
        "intake": ["research/worldquant_alpha_lab/report.md"],
        "adapter": ["scripts/worldquant_alpha_lab_report.py"],
        "consumer": [],
        "evidence": [],
        "next_action": "test top alpha factors as universe-ranking challengers with chronological holdout",
    },
    {
        "id": "mahoraga",
        "priority": 100,
        "capability": "strategy contracts and signal-staleness exits",
        "source": [],
        "intake": ["scripts/mahoraga_repo_intake_audit.py"],
        "adapter": [],
        "consumer": [],
        "evidence": ["data/mahoraga_repo_intake_audit_log.jsonl"],
        "next_action": "build the already-approved social and momentum staleness exit shadow study",
    },
    {
        "id": "openalice",
        "priority": 50,
        "capability": "file-backed research issues and approval packets",
        "source": [],
        "intake": ["scripts/openalice_repo_intake_audit.py"],
        "adapter": [],
        "consumer": [],
        "evidence": ["data/openalice_repo_intake_audit_log.jsonl"],
        "next_action": "connect approved intake items to one durable implementation queue with closure proof",
    },
]


def _present(root: Path, paths: list[str]) -> tuple[bool, list[str]]:
    found = [path for path in paths if (root / path).exists()]
    return bool(found), found


def evaluate_asset(asset: dict[str, Any], root: Path = ROOT) -> dict[str, Any]:
    stages: dict[str, bool] = {}
    evidence_paths: dict[str, list[str]] = {}
    for stage in ("source", "intake", "adapter", "consumer", "evidence"):
        configured = list(asset.get(stage) or [])
        present, found = _present(root, configured)
        stages[stage] = present
        evidence_paths[stage] = found

    # Source can be intentionally absent for architecture-only intake.
    required = ("intake", "adapter", "consumer", "evidence")
    completed = sum(stages[stage] for stage in required)
    if completed == 4:
        status = "operational_measured"
    elif stages["adapter"] and stages["consumer"]:
        status = "connected_missing_outcome_evidence"
    elif stages["adapter"] and stages["evidence"]:
        status = "evidence_only_not_consumed"
    elif stages["adapter"]:
        status = "adapter_only"
    elif stages["intake"]:
        status = "intake_only"
    else:
        status = "untracked"
    return {
        "id": asset["id"],
        "priority": int(asset.get("priority") or 0),
        "capability": asset["capability"],
        "status": status,
        "utilization_score": completed,
        "utilization_max": 4,
        "stages": stages,
        "evidence_paths": evidence_paths,
        "next_action": asset["next_action"],
        "execution_enabled": False,
    }


def build_report(root: Path = ROOT) -> dict[str, Any]:
    assets = [evaluate_asset(asset, root) for asset in ASSETS]
    assets.sort(key=lambda row: (row["utilization_score"], row["id"]))
    gaps = sorted(
        [row for row in assets if row["status"] != "operational_measured"],
        key=lambda row: (row["priority"], -row["utilization_score"]),
        reverse=True,
    )
    return {
        "provider": "research_asset_utilization_audit",
        "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "mode": "read_only_governance",
        "execution_enabled": False,
        "can_submit_orders": False,
        "asset_count": len(assets),
        "operational_measured_count": sum(row["status"] == "operational_measured" for row in assets),
        "gap_count": len(gaps),
        "assets": assets,
        "implementation_queue": [
            {
                "id": row["id"],
                "status": row["status"],
                "next_action": row["next_action"],
                "closure_definition": "adapter + bot consumer + forward evidence + health monitoring",
            }
            for row in gaps
        ],
        "policy": {
            "cloned_repo_counts_as_integrated": False,
            "intake_report_counts_as_integrated": False,
            "consumer_and_outcome_evidence_required": True,
            "automatic_execution_changes_allowed": False,
        },
    }


def write_report(report: dict[str, Any], report_path: Path = REPORT_PATH, log_path: Path = LOG_PATH) -> None:
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(report, separators=(",", ":"), sort_keys=True) + "\n")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--report-path", type=Path, default=REPORT_PATH)
    parser.add_argument("--log-path", type=Path, default=LOG_PATH)
    parser.add_argument("--print", action="store_true", dest="print_report")
    args = parser.parse_args()
    report = build_report(args.root)
    write_report(report, args.report_path, args.log_path)
    if args.print_report:
        print(f"assets={report['asset_count']} operational_measured={report['operational_measured_count']} gaps={report['gap_count']}")
        for row in report["assets"]:
            print(f"{row['id']:32} {row['status']:36} {row['utilization_score']}/4")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

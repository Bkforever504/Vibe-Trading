#!/usr/bin/env python3
"""Audit volume-backtest coverage for every strategy shadow program."""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUTPUT = Path.home() / ".vibe-trading" / "reports" / "shadow-volume-coverage.json"

EXCLUDE_PARTS = (
    "report", "consensus", "alerts", "candidates", "pnl_evaluator", "time_bucket",
    "view_shadow", "update_signal", "assisted_shadow_desk", "audit", "outcome_resolver",
    "checkin", "alert_runner", "shadow_ops", "system_heartbeat", "preflight",
)

CLASSIFICATIONS = {
    "banks_821_control_shadow.py": ("volume_native_forward_only", "The preregistered control-level retest requires completed-bar volume expansion; forward outcomes remain mandatory."),
    "donchian_expansion_forward_shadow.py": ("volume_native_forward_only", "This resolves the volume-gated Donchian candidate with a frozen forward cost model; it does not create a new volume hypothesis."),
    "donchian_expansion_shadow.py": ("volume_native_forward_only", "The frozen Donchian candidate requires relative-volume and true-range expansion on completed bars."),
    "ftfc_continuity_shadow.py": ("context_volume_native_forward_only", "The context lane explicitly records daily volume versus SMA9 and a liquidity floor; it is not an entry signal."),
    "macro_release_30m_orb_shadow.py": ("volume_native_forward_only", "The preregistered macro-release ORB requires release-window volume versus prior release sessions."),
    "spy_level_reaction_shadow.py": ("context_volume_native_forward_only", "Mapped-level reactions retain completed-bar VWAP and volume context for frozen outcome slices without creating a trigger."),
    "adaptive_options_shadow_playbook.py": ("historical_options_data_missing", "Options decisions require point-in-time chains, quotes, IV and spread costs; stock volume is not a valid substitute."),
    "czt_order_flow_shadow.py": ("volume_native_forward_only", "Already gates on RVOL and uses VWAP plus a bar-derived volume-profile proxy; true bid/ask delta is unavailable in IEX OHLCV."),
    "event_gap_continuation_shadow.py": ("volume_native_forward_only", "The frozen event-gap sequence requires completed-bar breakout volume and relative direction; executable forward outcomes remain the promotion evidence."),
    "equity_ignition_continuation_shadow.py": ("volume_native_forward_only", "The frozen continuation challenger requires ignition expansion, pullback contraction, and breakout-volume expansion; forward outcomes remain mandatory before promotion."),
    "equity_orb_scout_v1_shadow.py": ("volume_native_forward_only", "The frozen equity ORB scout requires a same-time relative-volume gate and resolves forward with explicit friction; more independent outcomes remain necessary."),
    "equity_orb_scout_v2_shadow.py": ("volume_native_forward_only", "The v2 equity ORB scout requires same-time relative volume or the frozen gap-and-go volume multiple; forward executable-quality outcomes remain necessary."),
    "gex_level_reaction_shadow.py": ("volume_native_forward_only", "The causal reaction logger requires confirmation-bar volume versus trailing bars; point-in-time GEX provenance and forward outcomes remain mandatory."),
    "resolve_fibonacci_shadow_plans.py": ("volume_overlay_not_preregistered", "The resolver scores a frozen price-structure benchmark; adding a volume gate after the Fibonacci tournament would change the preregistered thesis."),
    "ict_macro_shadow_logger.py": ("native_replay_insufficient_for_overlay", "Historical replay exists, but resolved sample is too small to support a second-stage volume filter."),
    "kama_shadow_logger.py": ("historical_volume_matrix_complete", "Daily SPY and QQQ replayed across 19 volume filters with chronological holdout and cost stress."),
    "liquid_options_edge_shadow.py": ("underlying_volume_tested_option_forward_only", "Both fixed underlying setups include RVOL in historical replay; contract-level bid/ask, IV, Greeks, and lifecycle evidence must accumulate forward."),
    "mfi_shadow_logger.py": ("historical_volume_matrix_complete", "Daily SPY and QQQ event replayed across 19 volume filters; fixed-horizon outcome because the logger has no executable exit."),
    "mes_orb_0932_vix_v2_shadow.py": ("volume_native_proxy_forward_only", "The frozen v2 ORB requires a five-session same-time RVOL gate, but yfinance OHLCV remains non-executable proxy evidence until Databento MBO and quote reconciliation are wired."),
    "mes_reopen_drift_v2_shadow.py": ("volume_native_proxy_forward_only", "The frozen v2 reopen setup requires a five-session ETH-volume gate, but yfinance OHLCV remains non-executable proxy evidence until Databento MBO and quote reconciliation are wired."),
    "mnq_cisd_only_v1_shadow.py": ("volume_native_proxy_forward_only", "The frozen CISD ablation requires completed-bar relative volume; timely discovery remains proxy-only and delayed Databento MBO regrades fail closed."),
    "mnq_pdl_rejection_v1_shadow.py": ("volume_native_proxy_forward_only", "The frozen PDL-rejection ablation includes its preregistered volume context; delayed Databento evidence and natural forward outcomes remain required."),
    "mnq_smt_cisd_fvg_v1_shadow.py": ("volume_native_proxy_forward_only", "The frozen composite uses relative volume within its confirmation sequence; delayed Databento evidence and natural forward outcomes remain required."),
    "mnq_smt_family_shadow.py": ("volume_native_proxy_forward_only", "The shared four-variant MNQ family engine applies the frozen relative-volume gates; live GLBX.MDP3 remains unlicensed and delayed MBO regrades fail closed."),
    "mnq_smt_only_v1_shadow.py": ("volume_native_proxy_forward_only", "The frozen SMT-only ablation retains its preregistered volume context; delayed Databento evidence and natural forward outcomes remain required."),
    "momentum_edge_ensemble_shadow.py": ("volume_overlay_not_preregistered", "The ensemble combines three preregistered price-momentum sleeves; adding a volume condition after the locked ensemble result would create a different strategy."),
    "momentum_shadow_logger.py": ("volume_overlay_not_preregistered", "Weekly cross-asset momentum is a distinct horizon; adding daily volume after seeing results would change the strategy thesis."),
    "nq_late_orb_retest_shadow.py": ("context_volume_native_forward_only", "The NQ late-ORB observer uses session VWAP context; its short development sample requires forward evidence before any volume interaction claim."),
    "nearterm_trend_shadow.py": ("context_volume_native_forward_only", "Near-term debit spreads consume breadth and RVOL context, but option profitability requires forward executable lifecycle evidence."),
    "options_shadow_twin.py": ("historical_options_data_missing", "Counterfactual option structures require point-in-time chains and executable quote paths; underlying volume cannot replace option NBBO evidence."),
    "premarket_ema_retest_shadow_logger.py": ("forward_sample_insufficient", "Existing corrected outcome study has too few signals for a defensible volume interaction test."),
    "qqq_gld_shadow_logger.py": ("volume_overlay_not_preregistered", "Forty-day rotation is already validated as relative momentum; a volume gate needs its own preregistered weekly hypothesis."),
    "qqq_mean_reversion_shadow.py": ("volume_overlay_not_preregistered", "The frozen QQQ mean-reversion variants are price-based; adding a volume condition after replay would define a new preregistered hypothesis."),
    "rsi2_shadow_logger.py": ("historical_volume_matrix_complete", "Daily SPY and QQQ replayed across 19 volume filters; leading QQQ candidates received bootstrap and yearly checks."),
    "smc_shadow_logger.py": ("outcome_definition_missing", "The logger emits zones and structure context, not a single executable entry/exit contract suitable for a fair backtest."),
    "spy_1200_daily_aligned_shadow.py": ("historical_direction_tested_option_forward_only", "The frozen noon daily-aligned signal has an underlying historical replay, but option profitability still requires point-in-time NBBO lifecycle evidence."),
    "spy_orb_rvol_shadow.py": ("historical_volume_matrix_complete", "SPY minute replay tested 168 ORB and volume-filter configurations with holdout and doubled-cost stress."),
    "strat_30m_continuation_shadow.py": ("forward_sample_insufficient", "Forward outcome schema exists, but current resolved episodes are below the 50-signal promotion requirement."),
    "swing_cash_sleeve_shadow.py": ("historical_volume_overlay_tested_forward_sample_insufficient", "Monthly momentum uses a historically tested breadth exposure overlay, but the live shadow decision still requires at least 12 resolved monthly observations."),
    "trend_participation_shadow.py": ("context_volume_native_forward_only", "Opening-range participation is volume-aware through the governed breadth context, but option profitability requires forward executable lifecycle evidence."),
    "ttm_squeeze_shadow_logger.py": ("historical_volume_matrix_complete", "Daily SPY and QQQ event replayed across 19 volume filters; fixed-horizon outcome because the logger has no executable exit."),
    "wavetrend_shadow_logger.py": ("historical_volume_matrix_complete", "Daily SPY and QQQ event replayed across 19 volume filters; fixed-horizon outcome because the logger has no executable exit."),
    "williams_r_shadow_logger.py": ("historical_volume_matrix_complete", "Daily SPY and QQQ replayed across 19 volume filters with chronological holdout and cost stress."),
}

NON_STRATEGY_PROGRAMS = frozenset({
    "daily_level_map_shadow.py", "footprint_evidence_shadow.py",
    "governed_shadow_alert.py", "governed_shadow_decision.py",
    "governed_shadow_lifecycle.py", "governed_shadow_outcome.py",
    "governed_shadow_rule_update.py", "institutional_confluence_shadow.py",
    "intraday_trade_lifecycle_shadow.py", "premarket_thesis_shadow.py",
    "wolves_bbr_shadow.py", "chart_aligned_shadow_learning.py",
    "options_tape_intelligence_shadow.py", "shadow_alert_intelligence.py",
    "ollama_trade_critic_shadow.py",
})

LOGS = {
    "adaptive_options_shadow_playbook.py": "adaptive_options_shadow_playbook_log.jsonl",
    "czt_order_flow_shadow.py": "czt_order_flow_shadow_log.jsonl",
    "event_gap_continuation_shadow.py": "event_gap_continuation_shadow_log.jsonl",
    "equity_ignition_continuation_shadow.py": "equity_ignition_continuation_shadow_log.jsonl",
    "equity_orb_scout_v1_shadow.py": "equity_orb_scout_v1_shadow_log.jsonl",
    "equity_orb_scout_v2_shadow.py": "equity_orb_scout_v2_shadow_log.jsonl",
    "gex_level_reaction_shadow.py": "gex_level_reaction_ledger.jsonl",
    "resolve_fibonacci_shadow_plans.py": "fibonacci_shadow_plans.json",
    "ict_macro_shadow_logger.py": "ict_macro_shadow_log.jsonl",
    "kama_shadow_logger.py": "kama_shadow_log.jsonl",
    "liquid_options_edge_shadow.py": "liquid_options_edge_shadow_log.jsonl",
    "mfi_shadow_logger.py": "mfi_shadow_log.jsonl",
    "mes_orb_0932_vix_v2_shadow.py": "mes_orb_0932_vix_v2_shadow_log.jsonl",
    "mes_reopen_drift_v2_shadow.py": "mes_reopen_drift_v2_shadow_log.jsonl",
    "mnq_cisd_only_v1_shadow.py": "mnq_cisd_only_v1_shadow_log.jsonl",
    "mnq_pdl_rejection_v1_shadow.py": "mnq_pdl_rejection_v1_shadow_log.jsonl",
    "mnq_smt_cisd_fvg_v1_shadow.py": "mnq_smt_cisd_fvg_v1_shadow_log.jsonl",
    "mnq_smt_only_v1_shadow.py": "mnq_smt_only_v1_shadow_log.jsonl",
    "momentum_edge_ensemble_shadow.py": "momentum_edge_ensemble_shadow.jsonl",
    "momentum_shadow_logger.py": "momentum_shadow_log.jsonl",
    "nq_late_orb_retest_shadow.py": "nq_late_orb_retest_shadow_log.jsonl",
    "nearterm_trend_shadow.py": "nearterm_trend_shadow_log.jsonl",
    "options_shadow_twin.py": "options_shadow_twin_log.jsonl",
    "premarket_ema_retest_shadow_logger.py": "premarket_ema_retest_shadow_log.jsonl",
    "qqq_gld_shadow_logger.py": "qqq_gld_shadow_log.jsonl",
    "qqq_mean_reversion_shadow.py": "qqq_mean_reversion_shadow_log.jsonl",
    "rsi2_shadow_logger.py": "rsi2_shadow_log.jsonl",
    "smc_shadow_logger.py": "smc_shadow_log.jsonl",
    "spy_1200_daily_aligned_shadow.py": "spy_1200_daily_aligned_shadow_log.jsonl",
    "spy_orb_rvol_shadow.py": "spy_orb_rvol_shadow.jsonl",
    "strat_30m_continuation_shadow.py": "strat_30m_continuation_shadow_log.jsonl",
    "swing_cash_sleeve_shadow.py": "swing_cash_sleeve_shadow_decision.json",
    "trend_participation_shadow.py": "trend_participation_shadow_log.jsonl",
    "ttm_squeeze_shadow_logger.py": "ttm_squeeze_shadow_log.jsonl",
    "wavetrend_shadow_logger.py": "wavetrend_shadow_log.jsonl",
    "williams_r_shadow_logger.py": "williams_r_shadow_log.jsonl",
}


def discover() -> list[str]:
    names = []
    for path in (ROOT / "scripts").glob("*shadow*.py"):
        if path.name in NON_STRATEGY_PROGRAMS:
            continue
        if any(part in path.stem for part in EXCLUDE_PARTS):
            continue
        names.append(path.name)
    return sorted(names)


def log_counts(name: str) -> dict:
    filename = LOGS.get(name)
    if filename is None:
        return {"records": 0, "signals": 0, "outcomes": 0, "path": None}
    path = ROOT / "data" / filename
    counts = {"records": 0, "signals": 0, "outcomes": 0, "path": str(path)}
    if not path.exists():
        return counts
    text = path.read_text(encoding="utf-8")
    if path.suffix == ".json":
        try:
            payload = json.loads(text)
        except json.JSONDecodeError:
            payload = None
        rows = [payload] if isinstance(payload, dict) else payload if isinstance(payload, list) else []
    else:
        rows = []
        for line in text.splitlines():
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    for row in rows:
        if not isinstance(row, dict):
            continue
        counts["records"] += 1
        record_type = str(row.get("record_type", "")).lower()
        if record_type == "signal" or row.get("type") == "candidate" or row.get("shadow_signal") or row.get("status") == "signal":
            counts["signals"] += 1
        if record_type == "outcome" or row.get("type") == "outcome" or row.get("outcome") not in (None, "pending_external_evaluation"):
            counts["outcomes"] += 1
    return counts


def build_report() -> dict:
    discovered = discover()
    unknown = sorted(set(discovered) - set(CLASSIFICATIONS))
    stale = sorted(set(CLASSIFICATIONS) - set(discovered))
    rows = []
    for name in discovered:
        status, reason = CLASSIFICATIONS.get(name, ("unclassified", "Must be classified before claiming complete coverage."))
        rows.append({"program": name, "status": status, "reason": reason, "log": log_counts(name)})
    return {
        "mode": "research_only",
        "execution_enabled": False,
        "discovered_strategy_shadow_programs": len(discovered),
        "classified_programs": len(discovered) - len(unknown),
        "unknown_programs": unknown,
        "stale_manifest_entries": stale,
        "historically_volume_tested": sum(row["status"] == "historical_volume_matrix_complete" for row in rows),
        "rows": rows,
        "interpretation": "Coverage is complete only when unknown_programs is empty. A classified limitation is not a claimed backtest.",
    }


def main() -> int:
    report = build_report()
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2, sort_keys=True))
    return 1 if report["unknown_programs"] or report["stale_manifest_entries"] else 0


if __name__ == "__main__":
    raise SystemExit(main())

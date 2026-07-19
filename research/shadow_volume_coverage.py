#!/usr/bin/env python3
"""Audit volume-backtest coverage for every strategy shadow program."""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUTPUT = Path.home() / ".vibe-trading" / "reports" / "shadow-volume-coverage.json"

EXCLUDE_PARTS = (
    "report", "consensus", "alerts", "candidates", "pnl_evaluator", "time_bucket",
    "view_shadow", "update_signal",
)

CLASSIFICATIONS = {
    "adaptive_options_shadow_playbook.py": ("historical_options_data_missing", "Options decisions require point-in-time chains, quotes, IV and spread costs; stock volume is not a valid substitute."),
    "czt_order_flow_shadow.py": ("volume_native_forward_only", "Already gates on RVOL and uses VWAP plus a bar-derived volume-profile proxy; true bid/ask delta is unavailable in IEX OHLCV."),
    "ict_macro_shadow_logger.py": ("native_replay_insufficient_for_overlay", "Historical replay exists, but resolved sample is too small to support a second-stage volume filter."),
    "kama_shadow_logger.py": ("historical_volume_matrix_complete", "Daily SPY and QQQ replayed across 19 volume filters with chronological holdout and cost stress."),
    "liquid_options_edge_shadow.py": ("underlying_volume_tested_option_forward_only", "Both fixed underlying setups include RVOL in historical replay; contract-level bid/ask, IV, Greeks, and lifecycle evidence must accumulate forward."),
    "mfi_shadow_logger.py": ("historical_volume_matrix_complete", "Daily SPY and QQQ event replayed across 19 volume filters; fixed-horizon outcome because the logger has no executable exit."),
    "momentum_shadow_logger.py": ("volume_overlay_not_preregistered", "Weekly cross-asset momentum is a distinct horizon; adding daily volume after seeing results would change the strategy thesis."),
    "premarket_ema_retest_shadow_logger.py": ("forward_sample_insufficient", "Existing corrected outcome study has too few signals for a defensible volume interaction test."),
    "qqq_gld_shadow_logger.py": ("volume_overlay_not_preregistered", "Forty-day rotation is already validated as relative momentum; a volume gate needs its own preregistered weekly hypothesis."),
    "rsi2_shadow_logger.py": ("historical_volume_matrix_complete", "Daily SPY and QQQ replayed across 19 volume filters; leading QQQ candidates received bootstrap and yearly checks."),
    "smc_shadow_logger.py": ("outcome_definition_missing", "The logger emits zones and structure context, not a single executable entry/exit contract suitable for a fair backtest."),
    "spy_orb_rvol_shadow.py": ("historical_volume_matrix_complete", "SPY minute replay tested 168 ORB and volume-filter configurations with holdout and doubled-cost stress."),
    "strat_30m_continuation_shadow.py": ("forward_sample_insufficient", "Forward outcome schema exists, but current resolved episodes are below the 50-signal promotion requirement."),
    "ttm_squeeze_shadow_logger.py": ("historical_volume_matrix_complete", "Daily SPY and QQQ event replayed across 19 volume filters; fixed-horizon outcome because the logger has no executable exit."),
    "wavetrend_shadow_logger.py": ("historical_volume_matrix_complete", "Daily SPY and QQQ event replayed across 19 volume filters; fixed-horizon outcome because the logger has no executable exit."),
    "williams_r_shadow_logger.py": ("historical_volume_matrix_complete", "Daily SPY and QQQ replayed across 19 volume filters with chronological holdout and cost stress."),
}

LOGS = {
    "adaptive_options_shadow_playbook.py": "adaptive_options_shadow_playbook_log.jsonl",
    "czt_order_flow_shadow.py": "czt_order_flow_shadow_log.jsonl",
    "ict_macro_shadow_logger.py": "ict_macro_shadow_log.jsonl",
    "kama_shadow_logger.py": "kama_shadow_log.jsonl",
    "liquid_options_edge_shadow.py": "liquid_options_edge_shadow_log.jsonl",
    "mfi_shadow_logger.py": "mfi_shadow_log.jsonl",
    "momentum_shadow_logger.py": "momentum_shadow_log.jsonl",
    "premarket_ema_retest_shadow_logger.py": "premarket_ema_retest_shadow_log.jsonl",
    "qqq_gld_shadow_logger.py": "qqq_gld_shadow_log.jsonl",
    "rsi2_shadow_logger.py": "rsi2_shadow_log.jsonl",
    "smc_shadow_logger.py": "smc_shadow_log.jsonl",
    "spy_orb_rvol_shadow.py": "spy_orb_rvol_shadow.jsonl",
    "strat_30m_continuation_shadow.py": "strat_30m_continuation_shadow_log.jsonl",
    "ttm_squeeze_shadow_logger.py": "ttm_squeeze_shadow_log.jsonl",
    "wavetrend_shadow_logger.py": "wavetrend_shadow_log.jsonl",
    "williams_r_shadow_logger.py": "williams_r_shadow_log.jsonl",
}


def discover() -> list[str]:
    names = []
    for path in (ROOT / "scripts").glob("*shadow*.py"):
        if any(part in path.stem for part in EXCLUDE_PARTS):
            continue
        names.append(path.name)
    return sorted(names)


def log_counts(name: str) -> dict:
    path = ROOT / "data" / LOGS[name]
    counts = {"records": 0, "signals": 0, "outcomes": 0, "path": str(path)}
    if not path.exists():
        return counts
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(row, dict):
            continue
        counts["records"] += 1
        record_type = str(row.get("record_type", "")).lower()
        if record_type == "signal" or row.get("shadow_signal") or row.get("status") == "signal":
            counts["signals"] += 1
        if record_type == "outcome" or row.get("outcome") not in (None, "pending_external_evaluation"):
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

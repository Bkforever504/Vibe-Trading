#!/usr/bin/env python3
"""Evidence-capped readiness scorecard for the autonomous options stack."""
from __future__ import annotations

import argparse
import json
import os
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parent.parent
VIBE_HOME = Path.home() / ".vibe-trading"
REPORT_DIR = VIBE_HOME / "reports"
REPORT_PATH = REPORT_DIR / "elite-bot-readiness-scorecard.json"
LOG_PATH = ROOT / "data" / "elite_bot_readiness_scorecard_log.jsonl"
SOURCE_PATHS = {
    "health": REPORT_DIR / "signal-stack-health.json",
    "schedule": REPORT_DIR / "market-schedule-alignment.json",
    "execution_audit": REPORT_DIR / "execution-gate-audit.json",
    "reconciliation": REPORT_DIR / "options-position-reconciliation.json",
    "learning": REPORT_DIR / "flip-bot-learning-report.json",
    "universe": REPORT_DIR / "daily-options-universe-ranker.json",
    "exit_quality": REPORT_DIR / "flip-exit-quality.json",
    "path_telemetry": REPORT_DIR / "flip-path-telemetry-completeness.json",
    "risk_fail_closed": REPORT_DIR / "risk-fail-closed-proof.json",
    "shadow": REPORT_DIR / "flip-shadow-pnl-evaluator.json",
    "grades": REPORT_DIR / "signal-stack-grades.json",
    "loop_closure": REPORT_DIR / "loop-closure-report.json",
    "surface": REPORT_DIR / "options-surface-intelligence.json",
    "ablation": REPORT_DIR / "flip-feature-ablation.json",
    "trial_ledger": REPORT_DIR / "edge-trial-ledger.json",
    "equity_curve": REPORT_DIR / "flip-equity-curve.json",
}
AUTOMATION_TASKS = {
    r"\VibeTrade\OptionsSurfaceIntelligence",
    r"\VibeTrade\DailyOptionsUniverseRanker",
    r"\VibeTrade\FlipExitQualityReport",
    r"\VibeTrade\FlipFeatureAblationReport",
    r"\VibeTrade\FlipEquityCurveReport",
    r"\VibeTrade\EdgeTrialLedgerReport",
    r"\VibeTrade\EliteBotReadinessScorecard",
}


def _read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def load_sources(paths: dict[str, Path] = SOURCE_PATHS) -> dict[str, dict[str, Any]]:
    return {name: _read_json(path) for name, path in paths.items()}


def _number(value: Any, default: float = 0.0) -> float:
    try:
        return float(value) if value not in (None, "") else default
    except (TypeError, ValueError):
        return default


def _integer(value: Any, default: int = 0) -> int:
    return int(_number(value, default))


def _days_since(value: Any, today: date) -> int:
    try:
        return max(0, (today - date.fromisoformat(str(value)[:10])).days + 1)
    except (TypeError, ValueError):
        return 0


def _category(name: str, raw_score: float, cap: float, evidence: list[str], blockers: list[str]) -> dict[str, Any]:
    score = round(max(0.0, min(10.0, raw_score, cap)), 1)
    return {
        "name": name,
        "score": score,
        "maximum": 10.0,
        "evidence_cap": round(cap, 1),
        "status": "verified_10" if score == 10.0 else "evidence_building",
        "evidence": evidence,
        "blockers_to_10": blockers,
    }


def _operational(s: dict[str, dict[str, Any]]) -> dict[str, Any]:
    health = s["health"].get("summary") if isinstance(s["health"].get("summary"), dict) else {}
    health_ok = bool(health) and sum(_integer(health.get(key)) for key in ("stale", "missing", "error")) == 0
    schedule_ok = bool(s["schedule"].get("passed"))
    audit_ok = bool(s["execution_audit"].get("passed"))
    raw = (5 if health_ok else 0) + (3 if schedule_ok else 0) + (2 if audit_ok else 0)
    blockers = []
    if not health_ok:
        blockers.append("Resolve every stale, missing, or error signal-stack item.")
    if not schedule_ok:
        blockers.append("Restore full market-schedule alignment.")
    if not audit_ok:
        blockers.append("Clear every execution-gate audit issue.")
    return _category("Operational integrity", raw, 10, [f"health={health}", f"schedule_passed={schedule_ok}", f"execution_audit_passed={audit_ok}"], blockers)


def _risk(s: dict[str, dict[str, Any]]) -> dict[str, Any]:
    rec = s["reconciliation"].get("reconciliation") if isinstance(s["reconciliation"].get("reconciliation"), dict) else {}
    residual = rec.get("unexplained_residual") if isinstance(rec.get("unexplained_residual"), dict) else {"unknown": 1}
    closed_open = rec.get("closed_groups_still_open") if isinstance(rec.get("closed_groups_still_open"), list) else ["unknown"]
    exact_book = bool(rec) and not residual and not closed_open
    status = str(rec.get("status") or "missing")
    entries_allowed = rec.get("entries_allowed")
    proof = s["risk_fail_closed"]
    proof_ok = bool(proof.get("passed"))
    fail_closed = proof_ok or status in {"ok", "clean", "balanced"} or entries_allowed is False
    audit_ok = bool(s["execution_audit"].get("passed"))
    analytics = (s["universe"], s["exit_quality"], s["surface"], s["ablation"], s["trial_ledger"])
    reports_read_only = all(report.get("execution_enabled") is False for report in analytics if report)
    raw = (4 if exact_book else 0) + (2 if fail_closed else 0) + (2 if audit_ok else 0) + (2 if reports_read_only else 0)
    blockers = []
    if not exact_book:
        blockers.append("Reconcile all unexplained or closed-state broker positions.")
    if not fail_closed:
        blockers.append("Prove entries fail closed whenever reconciliation is not clean.")
    if proof and not proof_ok:
        blockers.append("Repair the risk fail-closed proof report.")
    if not reports_read_only:
        blockers.append("Keep all analytics unable to submit orders.")
    return _category("Risk controls", raw, 10, [f"reconciliation_status={status}", f"exact_signed_book={exact_book}", f"fail_closed={fail_closed}", f"fail_closed_proof={proof_ok}"], blockers)


def _rolling(s: dict[str, dict[str, Any]]) -> dict[str, Any]:
    value = s["learning"].get("rolling_actual")
    return value if isinstance(value, dict) else {}


def _trade_evidence_cap(count: int, days: int) -> float:
    if count < 10:
        return 4
    if count < 30:
        return 7
    if count < 50:
        return 8
    if count < 100 or days < 60:
        return 9
    return 10


def _entry(s: dict[str, dict[str, Any]], today: date) -> dict[str, Any]:
    rolling = _rolling(s)
    count = _integer(rolling.get("closed_count"))
    days = _days_since(rolling.get("window_start"), today)
    expectancy = _number(rolling.get("expectancy"))
    profit_factor = _number(rolling.get("profit_factor"))
    payoff = _number(rolling.get("payoff_ratio"))
    win_rate = _number(rolling.get("win_rate"))
    capture_samples = _integer(rolling.get("capture_sample_count"))
    raw = (2 if rolling else 0) + min(3, count / 10 * 3)
    raw += 1 if expectancy > 0 else 0
    raw += 1 if profit_factor > 1 else 0
    raw += 1 if payoff > 1 else 0
    raw += 1 if win_rate >= 0.5 else 0
    raw += 1 if capture_samples >= 10 else 0
    cap = _trade_evidence_cap(count, days)
    blockers = []
    if count < 100:
        blockers.append(f"Accumulate at least 100 post-hardening closed trades; current={count}.")
    if days < 60:
        blockers.append(f"Accumulate at least 60 calendar days of forward evidence; current={days}.")
    if capture_samples < 30:
        blockers.append(f"Build complete entry/exit path telemetry on at least 30 trades; current={capture_samples}.")
    return _category("Entry quality", raw, cap, [f"closed={count}", f"days={days}", f"expectancy={expectancy}", f"profit_factor={profit_factor}"], blockers)


def _universe(s: dict[str, dict[str, Any]]) -> dict[str, Any]:
    universe = s["universe"]
    rankings = universe.get("rankings") if isinstance(universe.get("rankings"), list) else []
    promotion_count = _integer(universe.get("promotion_review_count"))
    challengers = _integer(universe.get("shadow_challenger_count"))
    benchmark = universe.get("execution_benchmark") if isinstance(universe.get("execution_benchmark"), dict) else {}
    max_completed = max((_integer(row.get("shadow_completed_count")) for row in rankings if isinstance(row, dict) and row.get("symbol") != "SPY"), default=0)
    max_days = max((_integer(row.get("shadow_trading_day_count")) for row in rankings if isinstance(row, dict) and row.get("symbol") != "SPY"), default=0)
    surface = s["surface"]
    raw = (3 if universe else 0) + (2 if rankings else 0) + (1 if challengers else 0)
    raw += 2 if promotion_count else 0
    raw += 1 if benchmark.get("options_liquidity_ok") else 0
    raw += 1 if universe.get("non_spy_execution_allowed") is False else 0
    raw += 1 if surface.get("institutional_flow_available") is False and surface.get("results") else 0
    cap = 5 if promotion_count == 0 else 8
    if promotion_count and max_completed >= 50 and max_days >= 60:
        cap = 10
    blockers = []
    if promotion_count == 0:
        blockers.append("No non-SPY challenger has passed the full promotion evidence gate.")
    if max_completed < 50:
        blockers.append(f"Best challenger needs 50 completed shadow lifecycles for a 10; current={max_completed}.")
    if max_days < 60:
        blockers.append(f"Best challenger needs 60 shadow trading days for a 10; current={max_days}.")
    if not surface:
        blockers.append("Restore the nightly option-surface and unsigned-flow report.")
    return _category("Daily universe selection", raw, cap, [f"ranked_symbols={len(rankings)}", f"shadow_challengers={challengers}", f"promotion_review={promotion_count}", f"SPY_liquidity_ok={bool(benchmark.get('options_liquidity_ok'))}", f"surface_symbols={_integer(surface.get('ok_count'))}"], blockers)


def _exit(s: dict[str, dict[str, Any]]) -> dict[str, Any]:
    report = s["exit_quality"]
    path_report = s["path_telemetry"]
    closed = _integer(report.get("closed_trade_count"))
    report_complete = _integer(report.get("complete_count"))
    observed_complete = _integer(path_report.get("observed_complete_count"), report_complete) if path_report else report_complete
    complete = min(report_complete, observed_complete)
    rows = report.get("trades") if isinstance(report.get("trades"), list) else []
    captures = [_number(row.get("capture_efficiency")) for row in rows if isinstance(row, dict) and row.get("capture_efficiency") is not None]
    givebacks = [_number(row.get("giveback_pct")) for row in rows if isinstance(row, dict) and row.get("giveback_pct") is not None]
    avg_capture = sum(captures) / len(captures) if captures else 0.0
    avg_giveback = sum(givebacks) / len(givebacks) if givebacks else 0.0
    raw = (2 if report else 0) + (1 if report.get("can_submit_orders") is False else 0) + (1 if closed else 0)
    raw += min(3, complete / 30 * 3)
    raw += 2 if complete >= 10 and avg_capture >= 0.6 else 0
    raw += 1 if complete >= 10 and avg_giveback <= 25 else 0
    cap = 4 if complete < 10 else 7 if complete < 30 else 9 if complete < 50 else 10
    blockers = []
    if complete < 50:
        blockers.append(f"Collect at least 50 complete forward exit-quality paths; current={complete}.")
    if path_report and observed_complete < report_complete:
        blockers.append(f"Exit report complete_count exceeds observed path telemetry; exit={report_complete}, observed={observed_complete}.")
    if complete < 10 or avg_capture < 0.6:
        blockers.append(f"Prove average capture efficiency at or above 0.60 on a meaningful sample; current={avg_capture:.3f}.")
    if complete < 10 or avg_giveback > 25:
        blockers.append(f"Prove average giveback at or below 25% on a meaningful sample; current={avg_giveback:.2f}%.")
    return _category("Exit quality", raw, cap, [f"closed={closed}", f"complete_paths={complete}", f"observed_path_complete={observed_complete}", f"avg_capture={avg_capture:.3f}", f"avg_giveback_pct={avg_giveback:.2f}"], blockers)


def _learning(s: dict[str, dict[str, Any]]) -> dict[str, Any]:
    present = {name: bool(s[name]) for name in ("learning", "shadow", "grades", "loop_closure", "universe", "exit_quality", "path_telemetry", "surface", "ablation", "trial_ledger", "equity_curve", "risk_fail_closed")}
    raw = sum(1.5 for value in present.values() if value)
    learning = s["learning"]
    raw += 0.5 if learning.get("next_learning_actions") else 0
    raw += 0.5 if learning.get("scanner_readiness") else 0
    rolling = _rolling(s)
    count = _integer(rolling.get("closed_count"))
    promotion_count = _integer(s["universe"].get("promotion_review_count"))
    cap = 8 if count < 30 or promotion_count == 0 else 9
    if count >= 100 and promotion_count > 0 and _integer(s["exit_quality"].get("complete_count")) >= 50:
        cap = 10
    blockers = []
    if not all(present.values()):
        blockers.append("Restore every learning-loop report source.")
    if count < 100:
        blockers.append("Verify the learning loop across at least 100 post-hardening outcomes.")
    if promotion_count == 0:
        blockers.append("No challenger has yet graduated through the learning and OOS review loop.")
    return _category("Learning loop", raw, cap, [f"report_sources={present}", f"post_hardening_trades={count}", f"promotion_review={promotion_count}"], blockers)


def _research_validity(s: dict[str, dict[str, Any]]) -> dict[str, Any]:
    ledger = s["trial_ledger"]
    ablation = s["ablation"]
    surface = s["surface"]
    multiple = ledger.get("multiple_testing") if isinstance(ledger.get("multiple_testing"), dict) else {}
    ablation_testing = ablation.get("multiple_testing") if isinstance(ablation.get("multiple_testing"), dict) else {}
    analytics = (ledger, ablation, surface)
    all_read_only = all(item.get("execution_enabled") is False and item.get("can_submit_orders") is False for item in analytics if item)
    trial_count = _integer(ledger.get("trial_count"))
    oos_count = sum(
        1 for row in ledger.get("trials") or []
        if isinstance(row, dict) and row.get("stage") in {"out_of_sample", "forward"}
    )
    feature_trades = _integer(ablation.get("feature_telemetry_trade_count"))
    raw = 0
    raw += 2 if ledger else 0
    raw += 2 if multiple.get("all_attempted_trials_counted") is True else 0
    raw += 2 if ablation and ablation_testing.get("all_observed_features_counted") is True else 0
    raw += 2 if surface.get("institutional_flow_available") is False and surface else 0
    raw += 2 if all_read_only and all(analytics) else 0
    cap = 6 if trial_count < 10 else 8 if trial_count < 30 else 9
    if trial_count >= 30 and oos_count >= 10 and feature_trades >= 30:
        cap = 10
    blockers = []
    if trial_count < 30:
        blockers.append(f"Record at least 30 immutable attempted edge trials, including failures; current={trial_count}.")
    if oos_count < 10:
        blockers.append(f"Complete at least 10 out-of-sample or forward trials; current={oos_count}.")
    if feature_trades < 30:
        blockers.append(f"Collect schema-v1 feature telemetry on at least 30 closed Flip trades; current={feature_trades}.")
    if not all(analytics):
        blockers.append("Restore surface, ablation, and trial-ledger governance reports.")
    return _category(
        "Research validity",
        raw,
        cap,
        [f"immutable_trials={trial_count}", f"oos_or_forward_trials={oos_count}", f"feature_telemetry_trades={feature_trades}", f"analytics_read_only={all_read_only}"],
        blockers,
    )


def _profitability(s: dict[str, dict[str, Any]], today: date) -> dict[str, Any]:
    rolling = _rolling(s)
    count = _integer(rolling.get("closed_count"))
    days = _days_since(rolling.get("window_start"), today)
    expectancy = _number(rolling.get("expectancy"))
    pf = _number(rolling.get("profit_factor"))
    net = _number(rolling.get("net_pnl"))
    equity_summary = s["equity_curve"].get("summary") if isinstance(s["equity_curve"].get("summary"), dict) else {}
    drawdown_recorded = equity_summary.get("max_drawdown_dollars") is not None
    max_drawdown_dollars = _number(equity_summary.get("max_drawdown_dollars")) if drawdown_recorded else None
    raw = 0
    raw += 1 if count >= 1 else 0
    raw += 1 if count >= 10 else 0
    raw += 1 if count >= 30 else 0
    raw += 1 if count >= 50 else 0
    raw += 1 if count >= 100 else 0
    raw += 1 if expectancy > 0 else 0
    raw += 1 if pf > 1 else 0
    raw += 1 if pf >= 1.5 else 0
    raw += 1 if net > 0 else 0
    raw += 1 if days >= 120 else 0
    if count < 10:
        cap = 3
    elif count < 30:
        cap = 4
    elif count < 50:
        cap = 6
    elif count < 100:
        cap = 8
    elif count < 200 or days < 120:
        cap = 9
    else:
        cap = 10 if drawdown_recorded else 9
    blockers = []
    if count < 200:
        blockers.append(f"Accumulate at least 200 post-hardening closed trades; current={count}.")
    if days < 120:
        blockers.append(f"Accumulate at least 120 calendar days; current={days}.")
    if not drawdown_recorded:
        blockers.append("Add and validate a durable post-hardening maximum-drawdown series before profitability can score 10.")
    return _category("Proven profitability", raw, cap, [f"closed={count}", f"days={days}", f"net_pnl={net}", f"expectancy={expectancy}", f"profit_factor={pf}", f"max_drawdown_dollars={max_drawdown_dollars}"], blockers)


def _automation(s: dict[str, dict[str, Any]]) -> dict[str, Any]:
    tasks = s["schedule"].get("tasks") if isinstance(s["schedule"].get("tasks"), list) else []
    aligned = {str(row.get("task")) for row in tasks if isinstance(row, dict) and row.get("aligned")}
    required_aligned = AUTOMATION_TASKS.issubset(aligned)
    health = s["health"].get("summary") if isinstance(s["health"].get("summary"), dict) else {}
    health_ok = bool(health) and sum(_integer(health.get(key)) for key in ("stale", "missing", "error")) == 0
    no_order = all(report.get("execution_enabled") is False and report.get("can_submit_orders") is False for report in (s["universe"], s["exit_quality"], s["path_telemetry"], s["risk_fail_closed"], s["surface"], s["ablation"], s["trial_ledger"], s["equity_curve"]) if report)
    schedule_passed = bool(s["schedule"].get("passed"))
    raw = (4 if schedule_passed else 0) + (2 if required_aligned else 0) + (2 if health_ok else 0) + (2 if no_order else 0)
    blockers = []
    if not schedule_passed:
        blockers.append("Restore full market-schedule alignment.")
    if not required_aligned:
        blockers.append(f"Align all required automation tasks; missing={sorted(AUTOMATION_TASKS - aligned)}.")
    if not health_ok:
        blockers.append("Keep the complete scheduled learning stack healthy.")
    return _category("Autonomous safety", raw, 10, [f"required_tasks_aligned={required_aligned}", f"health_clean={health_ok}", f"analytics_no_order={no_order}"], blockers)


def build_report(sources: dict[str, dict[str, Any]] | None = None, today: date | None = None) -> dict[str, Any]:
    sources = sources or load_sources()
    sources = {name: sources.get(name, {}) for name in SOURCE_PATHS}
    today = today or date.today()
    categories = [
        _operational(sources),
        _risk(sources),
        _entry(sources, today),
        _universe(sources),
        _exit(sources),
        _learning(sources),
        _research_validity(sources),
        _profitability(sources, today),
        _automation(sources),
    ]
    overall = round(sum(item["score"] for item in categories) / len(categories), 1)
    gaps = sorted(
        ({"category": item["name"], "score": item["score"], "evidence_cap": item["evidence_cap"], "next_requirement": item["blockers_to_10"][0] if item["blockers_to_10"] else "none"} for item in categories if item["score"] < 10),
        key=lambda row: (row["score"], row["category"]),
    )
    return {
        "provider": "elite_bot_readiness_scorecard",
        "mode": "read_only_governance",
        "execution_enabled": False,
        "can_submit_orders": False,
        "date": today.isoformat(),
        "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "overall_score": overall,
        "all_categories_verified_10": all(item["score"] == 10 for item in categories),
        "status": "verified_elite" if all(item["score"] == 10 for item in categories) else "evidence_building",
        "categories": categories,
        "priority_gaps": gaps,
        "scoring_policy": {
            "rule": "A category score is the lower of its process score and evidence cap.",
            "no_small_sample_10": True,
            "no_social_override": True,
            "no_automatic_promotion": True,
        },
        "warnings": [
            "A score of 10 means its listed evidence gate is satisfied; it is not a promise of daily profit.",
            "The scorecard cannot submit orders, change thresholds, promote symbols, or reset safety controls.",
            "Profitability remains evidence-capped until sample duration, trade count, and drawdown coverage mature.",
        ],
    }


def write_report(report: dict[str, Any], path: Path = REPORT_PATH) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(temp, path)


def append_log(report: dict[str, Any], path: Path = LOG_PATH) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(report, separators=(",", ":"), sort_keys=True) + "\n")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report-path", type=Path, default=REPORT_PATH)
    parser.add_argument("--log-path", type=Path, default=LOG_PATH)
    parser.add_argument("--print", action="store_true", dest="do_print")
    args = parser.parse_args()
    report = build_report()
    write_report(report, args.report_path)
    append_log(report, args.log_path)
    if args.do_print:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        print(f"Elite bot readiness scorecard wrote {args.report_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

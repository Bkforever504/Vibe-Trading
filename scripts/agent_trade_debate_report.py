#!/usr/bin/env python3
"""Read-only bull/bear/risk-manager debate report.

Turns the daily signal stack into a structured debate:
- Bull agent: what supports risk-on trades?
- Bear agent: what argues against them?
- Risk manager: what can veto?

No LLM is required and no orders are placed. This is a deterministic
orchestration/report layer for review discipline.
"""
from __future__ import annotations

import argparse
import json
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
VIBE_HOME = Path.home() / ".vibe-trading"
LOG_PATH = ROOT / "data" / "agent_trade_debate_log.jsonl"
REPORT_PATH = VIBE_HOME / "reports" / "agent-trade-debate.json"

SOURCE_PATHS = {
    "market_force": ROOT / "data" / "market_force_score_log.jsonl",
    "options_liquidity": ROOT / "data" / "options_liquidity_feasibility_log.jsonl",
    "health": ROOT / "data" / "signal_stack_health_log.jsonl",
    "hmm_regime": ROOT / "data" / "hmm_regime_log.jsonl",
    "pca_forces": ROOT / "data" / "pca_market_forces_log.jsonl",
}


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        if not raw.strip():
            continue
        try:
            item = json.loads(raw)
        except json.JSONDecodeError:
            continue
        if isinstance(item, dict):
            rows.append(item)
    return rows


def _row_date(row: dict[str, Any]) -> str:
    for key in ("date", "timestamp", "generated_at"):
        if row.get(key):
            return str(row[key])[:10]
    return ""


def latest_for_day(path: Path, day: str) -> dict[str, Any] | None:
    rows = [row for row in _read_jsonl(path) if _row_date(row) == day]
    return rows[-1] if rows else None


def bull_case(market_force: dict[str, Any] | None, options_liquidity: dict[str, Any] | None, hmm: dict[str, Any] | None) -> dict[str, Any]:
    points: list[str] = []
    score = 0.0
    if market_force:
        total = float(market_force.get("total_score") or 0.0)
        if total > 0:
            points.append(f"Market Force positive ({total}).")
            score += min(3.0, total)
    if options_liquidity:
        eligible = options_liquidity.get("flip_shadow_eligible") or options_liquidity.get("eligible_symbols") or []
        if not eligible and isinstance(options_liquidity.get("scans"), list):
            eligible = [row.get("symbol") for row in options_liquidity["scans"] if row.get("flip_shadow_eligible")]
        if eligible:
            points.append(f"Liquid option candidates available: {', '.join(map(str, eligible[:6]))}.")
            score += 1.0
    if hmm and isinstance(hmm.get("aggregate"), dict):
        state = hmm["aggregate"].get("state")
        if state == "trend":
            points.append("HMM regime favors trend-following context.")
            score += 1.0
    return {"agent": "bull", "score": round(score, 2), "points": points or ["No strong bull evidence found."]}


def bear_case(market_force: dict[str, Any] | None, pca: dict[str, Any] | None, hmm: dict[str, Any] | None) -> dict[str, Any]:
    points: list[str] = []
    score = 0.0
    if market_force:
        total = float(market_force.get("total_score") or 0.0)
        if total < 0:
            points.append(f"Market Force negative ({total}).")
            score += min(3.0, abs(total))
        if market_force.get("classification") == "mixed":
            points.append("Market Force is mixed; no clean directional tape.")
            score += 0.5
    if pca:
        regime = pca.get("force_regime")
        if regime == "single_market_force_dominant":
            points.append("PCA says broad market force dominates; individual ticker screenshots may be beta echoes.")
            score += 1.0
    if hmm and isinstance(hmm.get("aggregate"), dict):
        state = hmm["aggregate"].get("state")
        probs = hmm["aggregate"].get("probabilities", {})
        if state == "chop":
            points.append("HMM regime is chop; trend entries need extra confirmation.")
            score += 1.0
        if float(probs.get("panic", 0.0) or 0.0) >= 0.35:
            points.append("HMM panic probability elevated.")
            score += 2.0
    return {"agent": "bear", "score": round(score, 2), "points": points or ["No strong bear evidence found."]}


def risk_manager_case(market_force: dict[str, Any] | None, health: dict[str, Any] | None) -> dict[str, Any]:
    points: list[str] = []
    veto = False
    score = 0.0
    kill_files = [
        VIBE_HOME / "PORTFOLIO_KILL_SWITCH.json",
        VIBE_HOME / "MANUAL_RESET_REQUIRED.json",
        VIBE_HOME / "KALSHI_MANUAL_RESET_REQUIRED.json",
    ]
    active = [str(path) for path in kill_files if path.exists()]
    if active:
        veto = True
        score += 10
        points.append(f"Manual/portfolio kill switch active: {active}.")
    if market_force and isinstance(market_force.get("risk_veto"), dict) and market_force["risk_veto"].get("active"):
        veto = True
        score += 10
        points.append("Market Force risk veto is active.")
    if health and isinstance(health.get("summary"), dict):
        missing = int(health["summary"].get("missing", 0) or 0)
        errors = int(health["summary"].get("error", 0) or 0)
        if missing or errors:
            score += missing + 2 * errors
            points.append(f"Signal health has missing={missing}, error={errors}.")
    return {
        "agent": "risk_manager",
        "score": round(score, 2),
        "veto": veto,
        "points": points or ["No hard risk veto found."],
    }


def final_verdict(bull: dict[str, Any], bear: dict[str, Any], risk: dict[str, Any]) -> str:
    if risk.get("veto"):
        return "risk_veto_observe_only"
    if bull["score"] >= bear["score"] + 2:
        return "bull_case_leads_observe_only"
    if bear["score"] >= bull["score"] + 2:
        return "bear_case_leads_observe_only"
    return "no_consensus_observe_only"


def build_report(day: str | None = None, paths: dict[str, Path] | None = None) -> dict[str, Any]:
    day = day or date.today().isoformat()
    paths = paths or SOURCE_PATHS
    rows = {name: latest_for_day(path, day) for name, path in paths.items()}
    bull = bull_case(rows["market_force"], rows["options_liquidity"], rows["hmm_regime"])
    bear = bear_case(rows["market_force"], rows["pca_forces"], rows["hmm_regime"])
    risk = risk_manager_case(rows["market_force"], rows["health"])
    return {
        "date": day,
        "timestamp": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "provider": "agent_trade_debate_report",
        "mode": "read_only",
        "execution_enabled": False,
        "can_submit_orders": False,
        "verdict": final_verdict(bull, bear, risk),
        "agents": [bull, bear, risk],
        "source_availability": {name: rows[name] is not None for name in rows},
        "warnings": [
            "Report only. No orders are placed.",
            "Risk manager veto is informational here; actual order blocking remains in guard code.",
        ],
    }


def append_log(report: dict[str, Any], path: Path = LOG_PATH) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(report, separators=(",", ":"), default=str) + "\n")


def write_report(report: dict[str, Any], path: Path = REPORT_PATH) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    return path


def print_report(report: dict[str, Any]) -> None:
    print("\nAgent Trade Debate | read-only")
    print("=" * 72)
    print(f"verdict={report['verdict']} execution_enabled={report['execution_enabled']}")
    for agent in report["agents"]:
        print(f"{agent['agent']}: score={agent['score']} veto={agent.get('veto', '-')}")
        for point in agent["points"][:3]:
            print(f"  - {point}")
    print("No orders placed.\n")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--date", default=date.today().isoformat())
    parser.add_argument("--log-path", type=Path, default=LOG_PATH)
    parser.add_argument("--report-path", type=Path, default=REPORT_PATH)
    parser.add_argument("--print", action="store_true", dest="print_output")
    args = parser.parse_args()
    report = build_report(day=args.date)
    append_log(report, args.log_path)
    write_report(report, args.report_path)
    if args.print_output:
        print_report(report)
    else:
        print(f"Agent trade debate logged to {args.log_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

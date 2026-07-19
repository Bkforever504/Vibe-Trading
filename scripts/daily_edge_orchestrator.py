#!/usr/bin/env python3
"""Daily read-only edge orchestrator.

This report turns the existing intelligence stack into one operating view:
morning targets, intraday runners, no-trade explanations, exit accountability,
and scanner leadership. It does not call a broker or change bot settings.
"""
from __future__ import annotations

import argparse
import json
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parent.parent
VIBE_HOME = Path.home() / ".vibe-trading"
REPORT_DIR = VIBE_HOME / "reports"
REPORT_PATH = REPORT_DIR / "daily-edge-orchestrator.json"
LOG_PATH = ROOT / "data" / "daily_edge_orchestrator_log.jsonl"


def _read_json(path: Path, fallback: Any) -> Any:
    if not path.exists():
        return fallback
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        return fallback


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        if value in (None, ""):
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        if value in (None, ""):
            return default
        return int(float(value))
    except (TypeError, ValueError):
        return default


def _items_by_symbol(report: dict[str, Any], key: str = "items") -> dict[str, dict[str, Any]]:
    rows = report.get(key) if isinstance(report, dict) else None
    if not isinstance(rows, list):
        return {}
    out: dict[str, dict[str, Any]] = {}
    for row in rows:
        if isinstance(row, dict) and row.get("symbol"):
            out[str(row["symbol"]).upper()] = row
    return out


def _decision_by_symbol(report: dict[str, Any]) -> dict[str, dict[str, Any]]:
    rows = report.get("decisions") if isinstance(report, dict) else None
    if not isinstance(rows, list):
        return {}
    return {
        str(row["symbol"]).upper(): row
        for row in rows
        if isinstance(row, dict) and row.get("symbol")
    }


def _cheap_by_symbol(report: dict[str, Any]) -> dict[str, dict[str, Any]]:
    rows = report.get("top_candidates") if isinstance(report, dict) else None
    if not isinstance(rows, list):
        return {}
    out: dict[str, dict[str, Any]] = {}
    for row in rows:
        if not isinstance(row, dict) or not row.get("symbol"):
            continue
        symbol = str(row["symbol"]).upper()
        current = out.get(symbol)
        if current is None or _safe_float(row.get("quality_score")) > _safe_float(current.get("quality_score")):
            out[symbol] = row
    return out


def _liquidity_by_symbol(report: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return _items_by_symbol(report, key="results")


def _all_symbols(*sources: dict[str, dict[str, Any]]) -> list[str]:
    symbols: set[str] = set()
    for source in sources:
        symbols.update(source.keys())
    return sorted(symbols)


def _global_blockers(catalyst: dict[str, Any], consensus: dict[str, Any]) -> list[str]:
    blockers: list[str] = []
    kill_switch = consensus.get("kill_switch") if isinstance(consensus.get("kill_switch"), dict) else {}
    if kill_switch.get("active"):
        blockers.append("portfolio_kill_switch_active")
    today = catalyst.get("today") if isinstance(catalyst.get("today"), dict) else {}
    if str(today.get("max_impact") or "none") == "high":
        blockers.append("high_impact_catalyst_day")
    for veto in today.get("vetoes") or []:
        blockers.append(f"catalyst_{veto}")
    return sorted(set(blockers))


def _target_row(
    symbol: str,
    candle: dict[str, Any],
    htf: dict[str, Any],
    cheap: dict[str, Any],
    liquidity: dict[str, Any],
    decision: dict[str, Any],
    kronos: dict[str, Any],
    global_blockers: list[str],
) -> dict[str, Any]:
    score = 0.0
    reasons: list[str] = []
    blockers: list[str] = list(global_blockers)
    playbooks: set[str] = set()

    if cheap:
        if cheap.get("goal_match"):
            score += 4
            reasons.append("cheap_goal_match")
        elif _safe_float(cheap.get("best_return_pct")) >= 200:
            score += 2
            reasons.append("cheap_three_x_shadow")
        if cheap.get("right"):
            reasons.append(f"cheap_{str(cheap.get('right')).lower()}")

    candle_bias = str(candle.get("bias") or "neutral")
    candle_signal = str(candle.get("primary_signal") or "none")
    if candle_bias in {"bullish", "bearish"} and candle_signal != "none":
        score += 2
        reasons.append(f"candlestick_{candle_signal}")
    for playbook in candle.get("allowed_playbooks") or []:
        playbooks.add(str(playbook))
    for veto in candle.get("veto_reasons") or []:
        blockers.append(f"candlestick_{veto}")

    htf_bias = str(htf.get("primary_bias") or "mixed")
    htf_alignment = str(htf.get("intraday_alignment") or "unknown")
    if htf_bias in {"bullish", "bearish"} and htf_alignment == "aligned":
        score += 2
        reasons.append(f"htf_{htf_bias}_aligned")
    elif htf:
        blockers.append(f"htf_{htf_alignment}")
    for playbook in htf.get("allowed_playbooks") or []:
        playbooks.add(str(playbook))
    for veto in htf.get("veto_reasons") or []:
        blockers.append(f"htf_{veto}")

    verdict = str(liquidity.get("verdict") or "").lower()
    if liquidity.get("flip_shadow_eligible") or verdict == "qualified" or _safe_int(liquidity.get("score")) >= 4:
        score += 1
        reasons.append("liquidity_qualified")
    elif liquidity:
        blockers.append("liquidity_not_qualified")

    rec = str(decision.get("recommendation") or "")
    if rec in {"approve", "size_down"}:
        score += 1
        reasons.append(f"consensus_{rec}")
    if decision.get("options_playbook") and str(decision.get("options_playbook")) != "none":
        playbooks.add(str(decision.get("options_playbook")))
    for blocker in decision.get("blockers") or []:
        if isinstance(blocker, str) and blocker not in {"shadow_not_promotion_ready"}:
            blockers.append(blocker)

    kronos_context: dict[str, Any] = {}
    if kronos:
        direction = str(kronos.get("forecast_direction") or "unknown")
        status = str(kronos.get("status") or "unknown")
        if status == "ok":
            score += 1
            reasons.append(f"kronos_forecast_{direction}")
            kronos_context = {
                "forecast_direction": direction,
                "forecast_return_pct": kronos.get("forecast_return_pct"),
                "confidence": kronos.get("confidence"),
            }
        else:
            blockers.append("kronos_unavailable")
            kronos_context = {"status": status, "blockers": kronos.get("blockers") or []}

    critical = {
        "portfolio_kill_switch_active",
        "high_impact_catalyst_day",
        "options_liquidity_blocked",
        "liquidity_not_qualified",
    }
    if critical.intersection(blockers):
        lane = "blocked"
    elif score >= 7:
        lane = "precision_watch"
    elif score >= 4:
        lane = "watchlist"
    else:
        lane = "avoid_or_wait"

    return {
        "symbol": symbol,
        "lane": lane,
        "score": round(score, 2),
        "allowed_playbooks": sorted(playbooks) or ["stand_aside"],
        "reasons": sorted(set(reasons)),
        "blockers": sorted(set(blockers)),
        "best_return_pct": cheap.get("best_return_pct"),
        "option_symbol": cheap.get("option_symbol"),
        "kronos_forecast": kronos_context,
    }


def _morning_targets(
    candles: dict[str, dict[str, Any]],
    htfs: dict[str, dict[str, Any]],
    cheap: dict[str, dict[str, Any]],
    liquidity: dict[str, dict[str, Any]],
    decisions: dict[str, dict[str, Any]],
    kronos: dict[str, dict[str, Any]],
    global_blockers: list[str],
) -> list[dict[str, Any]]:
    rows = [
        _target_row(
            symbol,
            candles.get(symbol, {}),
            htfs.get(symbol, {}),
            cheap.get(symbol, {}),
            liquidity.get(symbol, {}),
            decisions.get(symbol, {}),
            kronos.get(symbol, {}),
            global_blockers,
        )
        for symbol in _all_symbols(candles, htfs, cheap, liquidity, decisions, kronos)
    ]
    rows.sort(key=lambda row: (row["lane"] == "precision_watch", row["score"], _safe_float(row.get("best_return_pct"))), reverse=True)
    return rows[:25]


def _runner_detection(
    candles: dict[str, dict[str, Any]],
    htfs: dict[str, dict[str, Any]],
    cheap: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for symbol in _all_symbols(candles, htfs, cheap):
        candle = candles.get(symbol, {})
        htf = htfs.get(symbol, {})
        candidate = cheap.get(symbol, {})
        best_return = _safe_float(candidate.get("best_return_pct"))
        candle_bias = str(candle.get("bias") or "neutral")
        htf_bias = str(htf.get("primary_bias") or "mixed")
        aligned = str(htf.get("intraday_alignment") or "") == "aligned"
        if best_return >= 500 or (candle_bias in {"bullish", "bearish"} and candle_bias == htf_bias and aligned):
            state = "active_shadow_runner"
        elif best_return >= 200 or candle_bias in {"bullish", "bearish"}:
            state = "runner_watch"
        else:
            state = "quiet"
        if state == "quiet":
            continue
        rows.append(
            {
                "symbol": symbol,
                "state": state,
                "best_return_pct": round(best_return, 2),
                "pattern": candle.get("primary_signal") or "none",
                "htf_bias": htf.get("primary_bias") or "unknown",
                "option_symbol": candidate.get("option_symbol"),
                "lesson": "track early setup quality, premium expansion, and whether the bot saw the move before screenshot hindsight",
            }
        )
    rows.sort(key=lambda row: (row["state"] == "active_shadow_runner", row["best_return_pct"]), reverse=True)
    return rows[:20]


def _no_trade_explanations(loop: dict[str, Any], targets: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows = loop.get("no_trade_explanations") if isinstance(loop.get("no_trade_explanations"), list) else []
    out: list[dict[str, Any]] = []
    target_by_symbol = {row["symbol"]: row for row in targets}
    for row in rows:
        if not isinstance(row, dict):
            continue
        symbol = str(row.get("symbol") or "unknown").upper()
        out.append(
            {
                "bot": row.get("bot"),
                "symbol": symbol,
                "strategy": row.get("strategy"),
                "primary_reason": row.get("primary_reason"),
                "why": row.get("explanation") or row.get("primary_reason") or "no stored explanation",
                "target_lane": target_by_symbol.get(symbol, {}).get("lane", "not_on_target_list"),
                "next_check": "verify whether skip was protective or a missed setup in next postmortem",
            }
        )
    return out[:25]


def _exit_accountability(loop: dict[str, Any]) -> list[dict[str, Any]]:
    rows = loop.get("trade_explanations") if isinstance(loop.get("trade_explanations"), list) else []
    out: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        quality = row.get("exit_quality") if isinstance(row.get("exit_quality"), dict) else {}
        capture = quality.get("capture_efficiency")
        giveback = quality.get("giveback_pct")
        if _safe_float(giveback) >= 25 or (capture is not None and _safe_float(capture) < 0.5):
            verdict = "poor_capture"
        elif _safe_float(row.get("pnl")) < 0:
            verdict = "loss_review"
        else:
            verdict = "acceptable_capture"
        out.append(
            {
                "bot": row.get("bot"),
                "symbol": row.get("symbol"),
                "pnl": row.get("pnl"),
                "exit_reason": row.get("exit_reason"),
                "best_pnl_pct": quality.get("best_pnl_pct"),
                "exit_return_pct": quality.get("exit_return_pct"),
                "giveback_pct": giveback,
                "capture_efficiency": capture,
                "verdict": verdict,
                "lesson": row.get("lesson") or "record exit quality before changing rules",
            }
        )
    out.sort(key=lambda item: (_safe_float(item.get("giveback_pct")), item["verdict"] == "poor_capture"), reverse=True)
    return out[:25]


def _recommended_use(state: str, blockers: list[str], name: str) -> str:
    text = f"{state} {name}".lower()
    if blockers or "not_ready" in text or "promising" in text:
        return "shadow_only"
    if "liquidity" in text:
        return "safety_gate"
    if "context_ready" in text or "market force" in text:
        return "context_gate"
    if "ready" in text:
        return "pre_entry_advice"
    return "shadow_only"


def _scanner_leadership(loop: dict[str, Any], learning: dict[str, Any], cheap_report: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    scoreboard = loop.get("promotion_scoreboard") if isinstance(loop.get("promotion_scoreboard"), list) else []
    for row in scoreboard:
        if not isinstance(row, dict):
            continue
        blockers = [str(item) for item in row.get("blockers") or []]
        state = str(row.get("promotion_state") or row.get("status") or "shadow")
        name = str(row.get("name") or "unknown")
        rows.append(
            {
                "name": name,
                "score": _safe_float(row.get("close_to_live_score")),
                "state": state,
                "sample_count": _safe_int(row.get("sample_count")),
                "blockers": blockers,
                "recommended_use": _recommended_use(state, blockers, name),
            }
        )
    readiness = learning.get("scanner_readiness") if isinstance(learning.get("scanner_readiness"), dict) else {}
    for row in readiness.get("closest_to_use") or []:
        if not isinstance(row, dict):
            continue
        name = str(row.get("name") or "unknown")
        if any(existing["name"] == name for existing in rows):
            continue
        state = str(row.get("status") or "shadow")
        rows.append(
            {
                "name": name,
                "score": 0.0,
                "state": state,
                "sample_count": 0,
                "blockers": [],
                "recommended_use": _recommended_use(state, [], name),
                "reason": row.get("reason"),
            }
        )
    goal_count = _safe_int((cheap_report.get("summary") or {}).get("goal_match_count")) if isinstance(cheap_report, dict) else 0
    if goal_count and not any(row["name"] == "Cheap Asymmetry Scanner" for row in rows):
        rows.append(
            {
                "name": "Cheap Asymmetry Scanner",
                "score": min(80.0 + goal_count, 95.0),
                "state": "promising_not_ready",
                "sample_count": goal_count,
                "blockers": ["needs_repeated_forward_samples"],
                "recommended_use": "shadow_only",
            }
        )
    rows.sort(key=lambda row: (row["recommended_use"] != "shadow_only", row["score"]), reverse=True)
    return rows[:20]


def build_report(day: str | None = None, report_dir: Path = REPORT_DIR) -> dict[str, Any]:
    report_dir = Path(report_dir)
    day = day or date.today().isoformat()
    candles_report = _read_json(report_dir / "candlestick-context.json", {})
    htf_report = _read_json(report_dir / "higher-timeframe-market-map.json", {})
    catalyst_report = _read_json(report_dir / "market-catalyst-calendar.json", {})
    liquidity_report = _read_json(report_dir / "options-liquidity-feasibility.json", {})
    cheap_report = _read_json(report_dir / "cheap-asymmetry-scanner.json", {})
    consensus_report = _read_json(report_dir / "shadow-consensus-gate.json", {})
    loop_report = _read_json(report_dir / "loop-closure-report.json", {})
    learning_report = _read_json(report_dir / "flip-bot-learning-report.json", {})
    kronos_report = _read_json(report_dir / "kronos-market-forecast.json", {})

    candles = _items_by_symbol(candles_report)
    htfs = _items_by_symbol(htf_report)
    liquidity = _liquidity_by_symbol(liquidity_report)
    cheap = _cheap_by_symbol(cheap_report)
    decisions = _decision_by_symbol(consensus_report)
    kronos = _items_by_symbol(kronos_report)
    global_blockers = _global_blockers(catalyst_report, consensus_report)
    targets = _morning_targets(candles, htfs, cheap, liquidity, decisions, kronos, global_blockers)
    runners = _runner_detection(candles, htfs, cheap)
    no_trades = _no_trade_explanations(loop_report, targets)
    exits = _exit_accountability(loop_report)
    leadership = _scanner_leadership(loop_report, learning_report, cheap_report)
    flip_selection = (
        learning_report.get("selection_decision")
        if isinstance(learning_report.get("selection_decision"), dict)
        else {}
    )
    rolling_flip = (
        learning_report.get("rolling_actual")
        if isinstance(learning_report.get("rolling_actual"), dict)
        else {}
    )

    return {
        "date": day,
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
        "provider": "daily_edge_orchestrator",
        "mode": "read_only",
        "execution_enabled": False,
        "can_submit_orders": False,
        "global_blockers": global_blockers,
        "summary": {
            "precision_watch_count": sum(1 for row in targets if row["lane"] == "precision_watch"),
            "runner_count": len(runners),
            "no_trade_explanation_count": len(no_trades),
            "poor_capture_count": sum(1 for row in exits if row["verdict"] == "poor_capture"),
            "scanner_leader_count": len(leadership),
            "flip_execution_symbol": flip_selection.get("execution_symbol") or "SPY",
            "flip_rolling_win_rate": rolling_flip.get("win_rate"),
            "flip_rolling_net_pnl": rolling_flip.get("net_pnl"),
        },
        "flip_selection_decision": flip_selection,
        "flip_rolling_quality": rolling_flip,
        "morning_targets": targets,
        "runner_detection": runners,
        "no_trade_explanations": no_trades,
        "exit_accountability": exits,
        "scanner_leadership": leadership,
        "warnings": [
            "Read-only orchestration. No broker calls. No orders.",
            "Screenshots and social claims remain discovery prompts, not execution triggers.",
            "Scanners can advise only after evidence gates; live execution still requires explicit approval.",
        ],
        "source_paths": {
            "candlestick_context": str(report_dir / "candlestick-context.json"),
            "higher_timeframe_map": str(report_dir / "higher-timeframe-market-map.json"),
            "market_catalyst_calendar": str(report_dir / "market-catalyst-calendar.json"),
            "options_liquidity": str(report_dir / "options-liquidity-feasibility.json"),
            "cheap_asymmetry": str(report_dir / "cheap-asymmetry-scanner.json"),
            "shadow_consensus": str(report_dir / "shadow-consensus-gate.json"),
            "loop_closure": str(report_dir / "loop-closure-report.json"),
            "flip_bot_learning": str(report_dir / "flip-bot-learning-report.json"),
            "kronos_market_forecast": str(report_dir / "kronos-market-forecast.json"),
        },
    }


def write_report(report: dict[str, Any], report_path: Path = REPORT_PATH, log_path: Path = LOG_PATH) -> None:
    report_path.parent.mkdir(parents=True, exist_ok=True)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    with log_path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(report, separators=(",", ":"), sort_keys=True) + "\n")


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate the daily read-only edge orchestrator report.")
    parser.add_argument("--date", default=None)
    parser.add_argument("--report-dir", type=Path, default=REPORT_DIR)
    parser.add_argument("--report-path", type=Path, default=REPORT_PATH)
    parser.add_argument("--log-path", type=Path, default=LOG_PATH)
    parser.add_argument("--print", action="store_true", dest="print_report")
    args = parser.parse_args()

    report = build_report(day=args.date, report_dir=args.report_dir)
    write_report(report, args.report_path, args.log_path)
    if args.print_report:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        print(f"Daily edge orchestrator wrote {args.report_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

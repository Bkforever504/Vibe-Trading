#!/usr/bin/env python3
"""Read-only consensus advisor for shadow signals.

This turns shadow logs into explicit trade assistance without giving them
execution authority. It can recommend approve/size_down/stand_aside/needs_review,
but it never submits orders and never changes bot risk settings.
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
DATA_DIR = ROOT / "data"
REPORT_PATH = REPORT_DIR / "shadow-consensus-gate.json"
LOG_PATH = DATA_DIR / "shadow_consensus_gate_log.jsonl"
KILL_SWITCH_PATH = VIBE_HOME / "PORTFOLIO_KILL_SWITCH.json"


def _read_json(path: Path) -> Any:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except json.JSONDecodeError:
        return None


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
        return int(value)
    except (TypeError, ValueError):
        return default


def _market_bias(report_dir: Path) -> dict[str, Any]:
    report = _read_json(report_dir / "market-force-score.json")
    if not isinstance(report, dict):
        return {"classification": "unknown", "confidence": 0.0, "direction": "unknown"}
    classification = str(report.get("classification") or "unknown").lower()
    direction = "unknown"
    if "bearish" in classification:
        direction = "bearish"
    elif "bullish" in classification:
        direction = "bullish"
    elif "mixed" in classification or "neutral" in classification:
        direction = "mixed"
    return {
        "classification": classification,
        "confidence": _safe_float(report.get("confidence")),
        "direction": direction,
    }


def _promotion_context(report_dir: Path) -> dict[str, Any]:
    report = _read_json(report_dir / "signal-stack-grades.json")
    if not isinstance(report, dict):
        return {"promotion_ready_count": 0, "items": []}
    return {
        "promotion_ready_count": _safe_int(report.get("promotion_ready_count")),
        "items": report.get("items") if isinstance(report.get("items"), list) else [],
    }


def _flip_shadow_by_symbol(report_dir: Path) -> dict[str, dict[str, Any]]:
    report = _read_json(report_dir / "flip-shadow-pnl-evaluator.json")
    by_symbol = report.get("by_symbol") if isinstance(report, dict) else None
    return by_symbol if isinstance(by_symbol, dict) else {}


def _adaptive_by_symbol(report_dir: Path) -> dict[str, dict[str, Any]]:
    report = _read_json(report_dir / "adaptive-options-shadow-playbook.json")
    rows = report.get("rows") if isinstance(report, dict) else None
    if not isinstance(rows, list):
        return {}
    out: dict[str, dict[str, Any]] = {}
    for row in rows:
        if isinstance(row, dict) and row.get("symbol"):
            out[str(row["symbol"]).upper()] = row
    return out


def _liquidity_by_symbol(report_dir: Path) -> dict[str, dict[str, Any]]:
    report = _read_json(report_dir / "options-liquidity-feasibility.json")
    rows = report.get("results") if isinstance(report, dict) else None
    if not isinstance(rows, list):
        return {}
    out: dict[str, dict[str, Any]] = {}
    for row in rows:
        if isinstance(row, dict) and row.get("symbol"):
            out[str(row["symbol"]).upper()] = row
    return out


def _rows_by_symbol(report_dir: Path, filename: str, key: str = "items") -> dict[str, dict[str, Any]]:
    report = _read_json(report_dir / filename)
    rows = report.get(key) if isinstance(report, dict) else None
    if not isinstance(rows, list):
        return {}
    out: dict[str, dict[str, Any]] = {}
    for row in rows:
        if isinstance(row, dict) and row.get("symbol"):
            out[str(row["symbol"]).upper()] = row
    return out


def _catalyst_context(report_dir: Path) -> dict[str, Any]:
    report = _read_json(report_dir / "market-catalyst-calendar.json")
    today = report.get("today") if isinstance(report, dict) else None
    return today if isinstance(today, dict) else {}


def _kronos_by_symbol(report_dir: Path) -> dict[str, dict[str, Any]]:
    return _rows_by_symbol(report_dir, "kronos-market-forecast.json")


def _kill_switch_status(path: Path) -> dict[str, Any]:
    payload = _read_json(path)
    if not isinstance(payload, dict):
        return {"active": False}
    active = payload.get("status") == "killed" or bool(payload.get("manual_reset_required"))
    return {
        "active": active,
        "reason": payload.get("reason"),
        "triggered_at": payload.get("triggered_at"),
        "daily_pnl_dollars": payload.get("daily_pnl_dollars"),
    }


def _symbols(*sources: dict[str, Any]) -> list[str]:
    symbols: set[str] = set()
    for source in sources:
        symbols.update(str(symbol).upper() for symbol in source.keys())
    return sorted(symbols)


def _alpha_quality(symbol_stats: dict[str, Any]) -> tuple[int, list[str], list[str]]:
    score = 0
    reasons: list[str] = []
    blockers: list[str] = []
    completed = _safe_int(symbol_stats.get("completed_count"))
    win_rate = _safe_float(symbol_stats.get("win_rate"))
    pnl = _safe_float(symbol_stats.get("total_hypothetical_pnl"))
    giveback = _safe_float(symbol_stats.get("avg_giveback_pct"))

    if completed >= 5:
        score += 1
        reasons.append(f"shadow_samples={completed}")
    else:
        blockers.append("not_enough_shadow_samples")

    if win_rate >= 0.60 and pnl > 0:
        score += 2
        reasons.append(f"positive_shadow_edge win_rate={win_rate:.1%} pnl={pnl:.2f}")
    elif win_rate >= 0.50 and pnl > 0:
        score += 1
        reasons.append(f"building_shadow_edge win_rate={win_rate:.1%} pnl={pnl:.2f}")
    elif symbol_stats:
        blockers.append("weak_shadow_pnl_evidence")

    if giveback > 75:
        blockers.append("large_shadow_giveback")
    elif giveback > 25:
        reasons.append(f"giveback_watch={giveback:.1f}%")
    elif symbol_stats:
        score += 1
        reasons.append(f"controlled_giveback={giveback:.1f}%")

    return score, reasons, blockers


def _liquidity_quality(row: dict[str, Any]) -> tuple[int, list[str], list[str]]:
    if not row:
        return 0, [], ["options_liquidity_unknown"]
    verdict = str(row.get("verdict") or "").lower()
    score = _safe_int(row.get("score"))
    eligible = bool(row.get("flip_shadow_eligible")) or score >= 4 or verdict == "qualified"
    if eligible:
        return 2, [f"options_liquidity={verdict or score}"], []
    if verdict == "borderline" or score == 3:
        return 0, [f"options_liquidity_borderline={score}"], ["options_liquidity_borderline"]
    return -1, [], ["options_liquidity_blocked"]


def _adaptive_quality(row: dict[str, Any], market_direction: str) -> tuple[int, list[str], list[str], str]:
    if not row:
        return 0, [], ["adaptive_playbook_missing"], "none"
    playbook = str(row.get("selected_playbook") or "none")
    action = str(row.get("action") or "")
    summary = row.get("condition_summary") if isinstance(row.get("condition_summary"), dict) else {}
    tradeable = bool(summary.get("tradeable"))
    blockers = row.get("explanation", {}).get("blockers") if isinstance(row.get("explanation"), dict) else []
    blocker_list = [str(item) for item in blockers] if isinstance(blockers, list) else []

    if not tradeable or playbook == "none" or "stand_aside" in action:
        out_blockers = ["adaptive_stand_aside"]
        out_blockers.extend("adaptive_" + item.lower().replace(" ", "_") for item in blocker_list[:3])
        # Do not escalate to options_liquidity_blocked here — adaptive is already
        # stand_aside. Execution-time spread filter is the real liquidity guard.
        return -1, [], out_blockers, playbook

    reasons = [f"adaptive_playbook={playbook}"]
    score = 1
    if market_direction == "bearish" and "put" in playbook:
        score += 1
        reasons.append("playbook_aligned_with_bearish_tape")
    elif market_direction == "bullish" and "call" in playbook:
        score += 1
        reasons.append("playbook_aligned_with_bullish_tape")
    return score, reasons, [], playbook


def _market_mastery_quality(
    symbol: str,
    candle: dict[str, Any],
    htf: dict[str, Any],
    catalyst: dict[str, Any],
    current_playbook: str,
) -> tuple[int, list[str], list[str], str]:
    score = 0
    reasons: list[str] = []
    blockers: list[str] = []
    playbook = current_playbook

    candle_bias = str(candle.get("bias") or "neutral")
    candle_signal = str(candle.get("primary_signal") or "none")
    candle_allowed = set(candle.get("allowed_playbooks") or [])
    htf_bias = str(htf.get("primary_bias") or "mixed")
    htf_alignment = str(htf.get("intraday_alignment") or "unknown")
    htf_allowed = set(htf.get("allowed_playbooks") or [])

    if candle_signal != "none" and candle_bias in {"bullish", "bearish"}:
        score += 1
        reasons.append(f"candlestick_{candle_signal}")
    if htf_bias in {"bullish", "bearish"} and htf_alignment == "aligned":
        score += 1
        reasons.append(f"higher_timeframe_{htf_bias}_aligned")
    elif htf_bias == "mixed":
        blockers.append("mixed_higher_timeframes")

    shared_playbooks = candle_allowed.intersection(htf_allowed)
    if "directional_long_call" in shared_playbooks and candle_bias == "bullish" and htf_bias == "bullish":
        playbook = "directional_long_call"
        score += 1
        reasons.append("market_mastery_call_playbook")
    elif "directional_long_put" in shared_playbooks and candle_bias == "bearish" and htf_bias == "bearish":
        playbook = "directional_long_put"
        score += 1
        reasons.append("market_mastery_put_playbook")

    for veto in candle.get("veto_reasons") or []:
        blockers.append(f"candlestick_{veto}")
    for veto in htf.get("veto_reasons") or []:
        blockers.append(f"htf_{veto}")

    catalyst_vetoes = catalyst.get("vetoes") if isinstance(catalyst, dict) else []
    if isinstance(catalyst_vetoes, list):
        for veto in catalyst_vetoes:
            blockers.append(f"catalyst_{veto}")
        if "size_down_required" in catalyst_vetoes:
            reasons.append("catalyst_size_down_required")
        if "new_short_premium_blocked" in catalyst_vetoes and playbook in {"put_spread", "iron_condor", "short_premium"}:
            playbook = "stand_aside"
    max_impact = str(catalyst.get("max_impact") or "none") if isinstance(catalyst, dict) else "none"
    if max_impact == "high":
        blockers.append("high_impact_catalyst_day")
    elif max_impact == "medium":
        reasons.append("medium_impact_catalyst_window")

    return score, reasons, blockers, playbook


def _kronos_quality(row: dict[str, Any], playbook: str) -> tuple[int, list[str], list[str]]:
    if not row:
        return 0, [], []
    status = str(row.get("status") or "unknown")
    if status != "ok":
        return 0, [], ["kronos_unavailable"]
    direction = str(row.get("forecast_direction") or "unknown")
    confidence = _safe_float(row.get("confidence"))
    reasons = [f"kronos_forecast_{direction}"]
    blockers: list[str] = []
    score = 0
    bullish_playbook = any(token in playbook for token in ("call", "put_spread"))
    bearish_playbook = "put" in playbook and "put_spread" not in playbook
    if confidence < 0.25:
        blockers.append("kronos_low_confidence")
    elif bullish_playbook and direction == "bullish":
        score += 1
    elif bearish_playbook and direction == "bearish":
        score += 1
    elif bullish_playbook and direction == "bearish":
        blockers.append("kronos_conflicts_with_bullish_playbook")
    elif bearish_playbook and direction == "bullish":
        blockers.append("kronos_conflicts_with_bearish_playbook")
    return score, reasons, blockers


def _recommendation(score: int, blockers: list[str], promotion_ready_count: int) -> str:
    if "portfolio_kill_switch_active" in blockers:
        return "stand_aside"
    if any(str(blocker).startswith("kronos_conflicts") for blocker in blockers):
        return "stand_aside"
    if "options_liquidity_blocked" in blockers or "weak_shadow_pnl_evidence" in blockers:
        return "stand_aside"
    if "adaptive_stand_aside" in blockers and score < 4:
        return "stand_aside"
    if "not_enough_shadow_samples" in blockers or "options_liquidity_unknown" in blockers:
        return "needs_review"
    if promotion_ready_count <= 0:
        return "size_down" if score >= 4 else "needs_review"
    if score >= 6:
        return "approve"
    if score >= 4:
        return "size_down"
    return "needs_review"


def build_report(
    *,
    day: str | None = None,
    report_dir: Path = REPORT_DIR,
    data_dir: Path = DATA_DIR,
    kill_switch_path: Path = KILL_SWITCH_PATH,
) -> dict[str, Any]:
    day = day or date.today().isoformat()
    report_dir = Path(report_dir)
    data_dir = Path(data_dir)
    if Path(kill_switch_path) == KILL_SWITCH_PATH and data_dir != DATA_DIR:
        kill_switch_path = data_dir / "PORTFOLIO_KILL_SWITCH.json"
    market = _market_bias(report_dir)
    promotion = _promotion_context(report_dir)
    flip = _flip_shadow_by_symbol(report_dir)
    adaptive = _adaptive_by_symbol(report_dir)
    liquidity = _liquidity_by_symbol(report_dir)
    candlesticks = _rows_by_symbol(report_dir, "candlestick-context.json")
    higher_timeframes = _rows_by_symbol(report_dir, "higher-timeframe-market-map.json")
    kronos = _kronos_by_symbol(report_dir)
    catalyst = _catalyst_context(report_dir)
    kill_switch = _kill_switch_status(kill_switch_path)
    promotion_ready_count = _safe_int(promotion.get("promotion_ready_count"))

    decisions: list[dict[str, Any]] = []
    for symbol in _symbols(flip, adaptive, liquidity, kronos):
        score = 0
        reasons: list[str] = []
        blockers: list[str] = []

        alpha_score, alpha_reasons, alpha_blockers = _alpha_quality(flip.get(symbol, {}))
        score += alpha_score
        reasons.extend(alpha_reasons)
        blockers.extend(alpha_blockers)

        liquidity_score, liquidity_reasons, liquidity_blockers = _liquidity_quality(liquidity.get(symbol, {}))
        score += liquidity_score
        reasons.extend(liquidity_reasons)
        blockers.extend(liquidity_blockers)

        adaptive_score, adaptive_reasons, adaptive_blockers, playbook = _adaptive_quality(
            adaptive.get(symbol, {}),
            str(market.get("direction") or "unknown"),
        )
        score += adaptive_score
        reasons.extend(adaptive_reasons)
        blockers.extend(adaptive_blockers)

        mastery_score, mastery_reasons, mastery_blockers, playbook = _market_mastery_quality(
            symbol,
            candlesticks.get(symbol, {}),
            higher_timeframes.get(symbol, {}),
            catalyst,
            playbook,
        )
        score += mastery_score
        reasons.extend(mastery_reasons)
        blockers.extend(mastery_blockers)

        kronos_score, kronos_reasons, kronos_blockers = _kronos_quality(kronos.get(symbol, {}), playbook)
        score += kronos_score
        reasons.extend(kronos_reasons)
        blockers.extend(kronos_blockers)

        if market.get("direction") in {"bearish", "bullish"} and _safe_float(market.get("confidence")) >= 8:
            score += 1
            reasons.append(f"market_force={market['classification']} confidence={market['confidence']}")
        else:
            blockers.append("market_force_unclear")

        if promotion_ready_count <= 0:
            blockers.append("shadow_not_promotion_ready")
        if kill_switch["active"]:
            blockers.append("portfolio_kill_switch_active")

        symbol_stats = flip.get(symbol, {})
        shadow_exit_control_eligible = (
            bool(symbol_stats.get("promotion_eligible"))
            and _safe_int(symbol_stats.get("out_of_sample_count")) >= 5
            and _safe_float(symbol_stats.get("out_of_sample_expectancy_return_pct")) > 0
        )
        recommendation = _recommendation(score, blockers, promotion_ready_count)
        decisions.append({
            "symbol": symbol,
            "recommendation": recommendation,
            "consensus_score": score,
            "market_direction": market.get("direction"),
            "options_playbook": playbook,
            "shadow_exit_control_eligible": shadow_exit_control_eligible,
            "shadow_exit_oos": {
                "sample_count": _safe_int(symbol_stats.get("out_of_sample_count")),
                "expectancy_return_pct": _safe_float(symbol_stats.get("out_of_sample_expectancy_return_pct")),
            },
            "bot_assist": {
                "flip_bot": recommendation in {"size_down", "needs_review"} and "weak_shadow_pnl_evidence" not in blockers,
                "options_bot": playbook != "none" and "options_liquidity_blocked" not in blockers,
                "execution_allowed": False,
            },
            "permitted_actions": [
                "entry_filter_advice",
                "size_adjustment_advice",
                "playbook_selection_advice",
                "exit_review_prompt",
                "daily_learning_input",
            ],
            "forbidden_actions": [
                "submit_orders",
                "increase_position_size_without_promotion",
                "override_kill_switch",
                "enable_live_trading",
            ],
            "reasons": reasons,
            "blockers": sorted(set(blockers)),
        })

    order = {"stand_aside": 0, "needs_review": 1, "size_down": 2, "approve": 3}
    decisions.sort(key=lambda row: (order.get(row["recommendation"], 0), row["consensus_score"]), reverse=True)
    summary = {key: 0 for key in ["approve", "size_down", "needs_review", "stand_aside"]}
    for row in decisions:
        summary[row["recommendation"]] = summary.get(row["recommendation"], 0) + 1

    return {
        "date": day,
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
        "provider": "shadow_consensus_gate",
        "mode": "read_only",
        "execution_enabled": False,
        "can_submit_orders": False,
        "promotion_ready_count": promotion_ready_count,
        "market": market,
        "kill_switch": kill_switch,
        "portfolio_kill_switch": kill_switch,
        "summary": summary,
        "decisions": decisions,
        "integration_guidance": {
            "flip_bot": "Use recommendations as pre-entry context: approve=size normal after existing guards, size_down=half risk or fewer contracts, stand_aside=no new trade.",
            "options_bot": "Use playbook and liquidity blockers before choosing credit spread, debit long option, iron condor, or no trade.",
            "exits": "Feed blockers and giveback reasons into postmortems and ratchet review.",
            "daily_learning": "Append report to nightly review; do not promote without 30-day forward evidence and human approval.",
        },
        "warnings": [
            "Read-only advisor. No broker orders are wired.",
            "Shadow scanners are not promoted to execution.",
            "Portfolio kill switch and execution guard remain authoritative.",
        ],
        "source_paths": {
            "signal_stack_grades": str(report_dir / "signal-stack-grades.json"),
            "flip_shadow_pnl": str(report_dir / "flip-shadow-pnl-evaluator.json"),
            "adaptive_options": str(report_dir / "adaptive-options-shadow-playbook.json"),
            "options_liquidity": str(report_dir / "options-liquidity-feasibility.json"),
            "market_force": str(report_dir / "market-force-score.json"),
            "candlestick_context": str(report_dir / "candlestick-context.json"),
            "higher_timeframe_map": str(report_dir / "higher-timeframe-market-map.json"),
            "market_catalyst_calendar": str(report_dir / "market-catalyst-calendar.json"),
            "kronos_market_forecast": str(report_dir / "kronos-market-forecast.json"),
            "kill_switch": str(kill_switch_path),
            "log": str(data_dir / LOG_PATH.name),
        },
    }


def write_report(report: dict[str, Any], report_path: Path = REPORT_PATH, log_path: Path = LOG_PATH) -> None:
    report_path.parent.mkdir(parents=True, exist_ok=True)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
    with log_path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(report, sort_keys=True) + "\n")


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate read-only shadow consensus gate report.")
    parser.add_argument("--date", default=None)
    parser.add_argument("--print", action="store_true", dest="print_report")
    args = parser.parse_args()
    report = build_report(day=args.date)
    write_report(report)
    if args.print_report:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        print(f"Shadow consensus gate wrote {REPORT_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

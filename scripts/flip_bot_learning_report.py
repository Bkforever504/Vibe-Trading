"""Generate a read-only Flip Bot learning report.

This stitches together actual Flip trades, postmortems, shadow P&L, and cheap
asymmetry scans so the bot's daily lessons are explicit before any tuning.
"""
from __future__ import annotations

import argparse
import json
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

try:
    from flip_exit_taxonomy import classify_exit_quality
except ModuleNotFoundError:
    from scripts.flip_exit_taxonomy import classify_exit_quality


ROOT = Path(__file__).resolve().parent.parent
VIBE_HOME = Path.home() / ".vibe-trading"
REPORT_DIR = VIBE_HOME / "reports"
REPORT_PATH = REPORT_DIR / "flip-bot-learning-report.json"
LOG_PATH = ROOT / "data" / "flip_bot_learning_log.jsonl"
FLIP_TRADES_PATH = VIBE_HOME / "flip-trades.json"
POSTMORTEM_PATH = REPORT_DIR / "closed-trade-postmortem.json"
SHADOW_PATH = REPORT_DIR / "flip-shadow-pnl-evaluator.json"
ASYMMETRY_PATH = REPORT_DIR / "cheap-asymmetry-scanner.json"
GRADES_PATH = REPORT_DIR / "signal-stack-grades.json"
RISK_HARDENING_DATE = "2026-06-29"


def _read_json(path: Path) -> Any:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        if value in (None, ""):
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def _trade_day(trade: dict[str, Any]) -> str:
    for key in ("exit_date", "closed_at", "entry_date", "opened_at"):
        if trade.get(key):
            return str(trade[key])[:10]
    return ""


def _load_daily_flip_trades(path: Path, day: str) -> list[dict[str, Any]]:
    payload = _read_json(path)
    if not isinstance(payload, list):
        return []
    return [
        row
        for row in payload
        if isinstance(row, dict)
        and row.get("status") == "closed"
        and _trade_day(row) == day
    ]


def _load_hardened_flip_trades(path: Path, through_day: str) -> tuple[list[dict[str, Any]], int]:
    payload = _read_json(path)
    if not isinstance(payload, list):
        return [], 0
    closed = [row for row in payload if isinstance(row, dict) and row.get("status") == "closed"]
    hardened = [
        row for row in closed
        if RISK_HARDENING_DATE <= _trade_day(row) <= through_day
    ]
    return hardened, len(closed) - len(hardened)


def _postmortem_rows(path: Path, day: str) -> list[dict[str, Any]]:
    payload = _read_json(path)
    if not isinstance(payload, dict) or str(payload.get("date")) != day:
        return []
    rows = payload.get("postmortems")
    if not isinstance(rows, list):
        return []
    return [row for row in rows if isinstance(row, dict) and row.get("bot") == "flip_bot"]


def _actual_summary(trades: list[dict[str, Any]]) -> dict[str, Any]:
    net = round(sum(_safe_float(row.get("pnl")) for row in trades), 2)
    wins = sum(1 for row in trades if _safe_float(row.get("pnl")) > 0)
    return {
        "closed_count": len(trades),
        "net_pnl": net,
        "winner_count": wins,
        "win_rate": round(wins / len(trades), 3) if trades else None,
        "symbols": sorted({str(row.get("symbol")) for row in trades if row.get("symbol")}),
    }


def _trade_exit_return_pct(trade: dict[str, Any]) -> float | None:
    entry = _safe_float(trade.get("entry_price"))
    exit_price = _safe_float(trade.get("exit_price"))
    if entry <= 0:
        return None
    return ((exit_price - entry) / entry) * 100


def _rolling_quality_summary(trades: list[dict[str, Any]], legacy_excluded: int) -> dict[str, Any]:
    wins = [trade for trade in trades if _safe_float(trade.get("pnl")) > 0]
    losses = [trade for trade in trades if _safe_float(trade.get("pnl")) < 0]
    gross_profit = sum(_safe_float(trade.get("pnl")) for trade in wins)
    gross_loss = abs(sum(_safe_float(trade.get("pnl")) for trade in losses))
    win_rate = len(wins) / len(trades) if trades else None
    loss_rate = len(losses) / len(trades) if trades else None
    avg_win = gross_profit / len(wins) if wins else 0.0
    avg_loss = gross_loss / len(losses) if losses else 0.0
    expectancy = (
        (win_rate * avg_win) - (loss_rate * avg_loss)
        if win_rate is not None and loss_rate is not None
        else None
    )
    payoff_ratio = avg_win / avg_loss if avg_loss > 0 else None
    capture_rows = []
    winner_to_loser = 0
    for trade in trades:
        best = trade.get("best_pnl_pct")
        exit_return = _trade_exit_return_pct(trade)
        if best not in (None, "") and _safe_float(best) > 0 and exit_return is not None:
            quality = classify_exit_quality(best, exit_return, trade.get("exit_reason"))
            if quality["winner_capture_eligible"]:
                capture_rows.append({
                    "trade_id": trade.get("id"),
                    "symbol": trade.get("symbol"),
                    **quality,
                })
            if exit_return <= 0:
                winner_to_loser += 1

    by_symbol: dict[str, dict[str, Any]] = {}
    for symbol in sorted({str(trade.get("symbol")) for trade in trades if trade.get("symbol")}):
        items = [trade for trade in trades if str(trade.get("symbol")) == symbol]
        symbol_wins = [trade for trade in items if _safe_float(trade.get("pnl")) > 0]
        by_symbol[symbol] = {
            "closed_count": len(items),
            "winner_count": len(symbol_wins),
            "win_rate": round(len(symbol_wins) / len(items), 3) if items else None,
            "net_pnl": round(sum(_safe_float(trade.get("pnl")) for trade in items), 2),
        }

    return {
        "window_start": RISK_HARDENING_DATE,
        "closed_count": len(trades),
        "winner_count": len(wins),
        "loser_count": len(losses),
        "win_rate": round(win_rate, 3) if win_rate is not None else None,
        "net_pnl": round(gross_profit - gross_loss, 2),
        "gross_profit": round(gross_profit, 2),
        "gross_loss": round(gross_loss, 2),
        "profit_factor": round(gross_profit / gross_loss, 2) if gross_loss > 0 else None,
        "avg_win": round(avg_win, 2) if wins else None,
        "avg_loss": round(avg_loss, 2) if losses else None,
        "payoff_ratio": round(payoff_ratio, 3) if payoff_ratio is not None else None,
        "expectancy": round(expectancy, 2) if expectancy is not None else None,
        "expectancy_per_100_trades": round(expectancy * 100, 2) if expectancy is not None else None,
        "expectancy_status": "positive" if expectancy is not None and expectancy > 0 else "negative_or_unproven",
        "avg_pnl": round((gross_profit - gross_loss) / len(trades), 2) if trades else None,
        "capture_sample_count": len(capture_rows),
        "avg_capture_efficiency": round(
            sum(row["capture_efficiency"] for row in capture_rows) / len(capture_rows), 3
        ) if capture_rows else None,
        "avg_giveback_pct": round(
            sum(row["giveback_pct"] for row in capture_rows) / len(capture_rows), 2
        ) if capture_rows else None,
        "poor_capture_count": sum(1 for row in capture_rows if row["capture_efficiency"] < 0.5),
        "winner_to_loser_count": winner_to_loser,
        "by_symbol": by_symbol,
        "legacy_pre_hardening_closed_trades_excluded": legacy_excluded,
        "legacy_exclusion_reason": "Risk sizing and contract caps changed after the 69-contract failure.",
    }


def _expectancy_lessons(rolling: dict[str, Any]) -> list[dict[str, Any]]:
    if not rolling.get("closed_count"):
        return []
    expectancy = _safe_float(rolling.get("expectancy"))
    win_rate = _safe_float(rolling.get("win_rate"))
    avg_win = _safe_float(rolling.get("avg_win"))
    avg_loss = _safe_float(rolling.get("avg_loss"))
    lessons: list[dict[str, Any]] = []
    if expectancy <= 0:
        lessons.append(
            {
                "type": "negative_expectancy",
                "severity": "high",
                "symbol": "ALL",
                "win_rate": rolling.get("win_rate"),
                "avg_win": rolling.get("avg_win"),
                "avg_loss": rolling.get("avg_loss"),
                "expectancy": rolling.get("expectancy"),
                "lesson": "Win rate is not enough; average loss is overpowering average win. Tighten invalidation or stop taking this setup until expectancy turns positive.",
            }
        )
    elif win_rate >= 0.6 and avg_loss > avg_win:
        lessons.append(
            {
                "type": "high_win_rate_payoff_warning",
                "severity": "medium",
                "symbol": "ALL",
                "win_rate": rolling.get("win_rate"),
                "avg_win": rolling.get("avg_win"),
                "avg_loss": rolling.get("avg_loss"),
                "expectancy": rolling.get("expectancy"),
                "lesson": "The bot is winning often but losers are larger than winners; preserve the edge by cutting thesis breaks faster and holding only clean runners.",
            }
        )
    return lessons


def _postmortem_outcome_lessons(postmortems: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Turn every closed Flip outcome into durable learning input.

    Aggregate expectancy and exit-capture rules are useful, but they do not
    guarantee that an ordinary stopped trade becomes a lesson.  The postmortem
    is the canonical source for the trade-specific cause and next action.
    """
    lessons: list[dict[str, Any]] = []
    for row in postmortems:
        explanation = row.get("pnl_explanation") if isinstance(row.get("pnl_explanation"), dict) else {}
        outcome = str(explanation.get("outcome") or ("loss" if _safe_float(row.get("pnl")) < 0 else "profit")).lower()
        driver = str(explanation.get("primary_driver") or "closed outcome needs a classified primary driver")
        next_action = str(explanation.get("next_action") or "review the observed entry, path, and exit before repeating")
        quality = explanation.get("exit_quality") if isinstance(explanation.get("exit_quality"), dict) else {}

        if outcome == "loss":
            lesson_type = "entry_regime_failure" if driver.startswith("entry/regime failure") else "closed_trade_loss"
            severity = "high"
            status = "open"
        else:
            lesson_type = "closed_trade_reinforcement"
            severity = "info"
            status = "observed"

        lessons.append(
            {
                "type": lesson_type,
                "severity": severity,
                "status": status,
                "trade_id": row.get("trade_id"),
                "symbol": row.get("symbol"),
                "strategy": row.get("strategy"),
                "pnl": row.get("pnl"),
                "primary_driver": driver,
                "exit_quality_classification": quality.get("exit_quality_classification"),
                "lesson": next_action,
                "requires_counterfactual": outcome == "loss",
                "authority": "research_only",
            }
        )
    return lessons


def _capture_gap_lessons(postmortems: list[dict[str, Any]]) -> list[dict[str, Any]]:
    lessons: list[dict[str, Any]] = []
    for row in postmortems:
        explanation = row.get("pnl_explanation") if isinstance(row.get("pnl_explanation"), dict) else {}
        quality = explanation.get("exit_quality") if isinstance(explanation.get("exit_quality"), dict) else {}
        giveback = _safe_float(quality.get("giveback_pct"))
        capture = quality.get("capture_efficiency")
        exit_return = quality.get("exit_return_pct")
        best = quality.get("best_pnl_pct")
        if exit_return not in (None, "") and _safe_float(exit_return) <= 0:
            if best not in (None, "") and _safe_float(best) > 0:
                classification = str(quality.get("exit_quality_classification") or "")
                lesson_type = (
                    "stop_loss_after_favorable_excursion"
                    if classification.startswith("stop_loss")
                    else "loss_after_favorable_excursion"
                )
                surrendered = quality.get("favorable_excursion_surrendered_pct")
                if surrendered in (None, ""):
                    surrendered = round(_safe_float(best) - _safe_float(exit_return), 2)
                lessons.append(
                    {
                        "type": lesson_type,
                        "severity": "high" if _safe_float(surrendered) >= 40 else "medium",
                        "symbol": row.get("symbol"),
                        "best_pnl_pct": best,
                        "exit_return_pct": exit_return,
                        "favorable_excursion_surrendered_pct": surrendered,
                        "capture_efficiency": None,
                        "lesson": "Trade briefly moved favorable but exited below zero; investigate entry timing, reversal detection, and the first post-entry directional conflict. This is not winner-capture evidence.",
                    }
                )
        elif _safe_float(exit_return) > 0 and giveback >= 25:
            lessons.append(
                {
                    "type": "capture_gap",
                    "severity": "high" if giveback >= 40 else "medium",
                    "symbol": row.get("symbol"),
                    "best_pnl_pct": quality.get("best_pnl_pct"),
                    "exit_return_pct": quality.get("exit_return_pct"),
                    "giveback_pct": round(giveback, 2),
                    "capture_efficiency": capture,
                    "lesson": "Winner faded too much before exit; keep ratchet/cadence pressure on similar 0DTE runners.",
                }
            )
    return lessons


def _same_day_reentry_lessons(trades: list[dict[str, Any]]) -> list[dict[str, Any]]:
    lessons: list[dict[str, Any]] = []
    closed_seen: set[tuple[str, str, str, str]] = set()
    for trade in sorted(trades, key=lambda row: str(row.get("entry_date") or row.get("opened_at") or "")):
        key = (
            _trade_day(trade),
            str(trade.get("symbol") or ""),
            str(trade.get("right") or ""),
            str(trade.get("strategy") or ""),
        )
        pnl = _safe_float(trade.get("pnl"))
        if key in closed_seen and pnl < 0:
            lessons.append(
                {
                    "type": "same_day_reentry_loss",
                    "severity": "high",
                    "symbol": trade.get("symbol"),
                    "right": trade.get("right"),
                    "strategy": trade.get("strategy"),
                    "pnl": round(pnl, 2),
                    "lesson": "A same-day same-direction re-entry lost money; require stronger fresh confirmation before repeating a closed setup.",
                }
            )
        closed_seen.add(key)
    return lessons


def _missed_asymmetry_lessons(
    trades: list[dict[str, Any]],
    asymmetry_path: Path,
    shadow_path: Path,
    day: str,
) -> list[dict[str, Any]]:
    actual_symbols = {str(row.get("symbol")) for row in trades if row.get("symbol")}
    asymmetry = _read_json(asymmetry_path)
    shadow = _read_json(shadow_path)
    if not isinstance(asymmetry, dict) or str(asymmetry.get("date")) != day:
        return []
    if isinstance(shadow, dict) and str(shadow.get("date")) != day:
        return []

    lessons: list[dict[str, Any]] = []
    candidates = asymmetry.get("top_candidates")
    if not isinstance(candidates, list):
        return lessons
    for candidate in candidates[:5]:
        if not isinstance(candidate, dict):
            continue
        symbol = str(candidate.get("symbol") or "")
        best_return = _safe_float(candidate.get("best_return_pct"))
        if symbol and symbol not in actual_symbols and best_return >= 200:
            lessons.append(
                {
                    "type": "missed_cheap_asymmetry",
                    "severity": "medium",
                    "symbol": symbol,
                    "right": candidate.get("right"),
                    "option_symbol": candidate.get("option_symbol"),
                    "cost_at_open": candidate.get("cost_at_open"),
                    "best_return_pct": candidate.get("best_return_pct"),
                    "simulated_return_pct": candidate.get("simulated_return_pct"),
                    "goal_match": bool(candidate.get("goal_match")),
                    "lesson": "A cheap asymmetric shadow setup outperformed live symbol selection; keep tracking, but do not promote without repeated samples.",
                }
            )
    return lessons


def _scanner_readiness(grades_path: Path) -> dict[str, Any]:
    payload = _read_json(grades_path)
    ready_count = 0
    if isinstance(payload, dict):
        ready_count = int(payload.get("promotion_ready_count") or 0)
    return {
        "promotion_ready_count": ready_count,
        "closest_to_use": [
            {
                "name": "Flip Shadow PnL Evaluator",
                "use": "learning_input",
                "status": "closest",
                "reason": "It already measures missed winners, capture efficiency, giveback, and symbol opportunity.",
            },
            {
                "name": "Cheap Asymmetry Scanner",
                "use": "shadow_filter",
                "status": "promising_not_ready",
                "reason": "It found cheap runners, but current report has zero goal matches and needs 30 trading days/10 samples per symbol.",
            },
            {
                "name": "Market Force Score",
                "use": "regime_gate",
                "status": "context_ready",
                "reason": "It can explain when Flip trades fight the broader tape, but it is context, not an entry trigger.",
            },
            {
                "name": "Options Liquidity Gate",
                "use": "safety_gate",
                "status": "gate_candidate",
                "reason": "It is suitable as a no-trade filter before it is treated as alpha.",
            },
        ],
    }


def build_report(
    day: str | None = None,
    flip_trades_path: Path = FLIP_TRADES_PATH,
    postmortem_path: Path = POSTMORTEM_PATH,
    shadow_path: Path = SHADOW_PATH,
    asymmetry_path: Path = ASYMMETRY_PATH,
    grades_path: Path = GRADES_PATH,
) -> dict[str, Any]:
    day = day or date.today().isoformat()
    trades = _load_daily_flip_trades(flip_trades_path, day)
    hardened_trades, legacy_excluded = _load_hardened_flip_trades(flip_trades_path, day)
    postmortems = _postmortem_rows(postmortem_path, day)
    lessons = []
    rolling_actual = _rolling_quality_summary(hardened_trades, legacy_excluded)
    lessons.extend(_expectancy_lessons(rolling_actual))
    lessons.extend(_postmortem_outcome_lessons(postmortems))
    lessons.extend(_capture_gap_lessons(postmortems))
    lessons.extend(_same_day_reentry_lessons(trades))
    lessons.extend(_missed_asymmetry_lessons(trades, asymmetry_path, shadow_path, day))
    shadow_report = _read_json(shadow_path)
    shadow_report = shadow_report if isinstance(shadow_report, dict) else {}
    execution_focus = shadow_report.get("execution_focus") if isinstance(shadow_report.get("execution_focus"), dict) else {}
    challengers = shadow_report.get("challenger_leaderboard") if isinstance(shadow_report.get("challenger_leaderboard"), list) else []

    return {
        "provider": "flip_bot_learning_report",
        "mode": "read_only",
        "execution_enabled": False,
        "date": day,
        "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "actual": _actual_summary(trades),
        "rolling_actual": rolling_actual,
        "selection_decision": {
            "execution_symbol": execution_focus.get("symbol") or "SPY",
            "reason": execution_focus.get("reason") or "SPY remains the execution benchmark until trusted challenger lifecycles mature.",
            "eligible_challengers": execution_focus.get("eligible_challengers") or [],
            "top_shadow_challengers": challengers[:5],
            "non_spy_execution_allowed": False,
        },
        "lessons": lessons,
        "scanner_readiness": _scanner_readiness(grades_path),
        "next_learning_actions": [
            "Persist every closed outcome to the canonical lesson ledger before any next-day review.",
            "Keep ratcheted profit protection active and monitor capture efficiency.",
            "Rank every setup by expectancy, average win, and average loss before trusting win rate.",
            "Treat same-day same-direction re-entry as blocked unless fresh confirmation is materially stronger.",
            "Compare live Flip symbols against top cheap-asymmetry candidates every day before promotion discussion.",
            "Use only schema-v2 complete shadow lifecycles for symbol rankings; legacy repeated snapshots are excluded.",
        ],
        "warnings": [
            "Read-only learning report. No broker calls and no orders placed.",
            "Scanner readiness is not live-trading approval.",
        ],
    }


def write_report(report: dict[str, Any], report_path: Path = REPORT_PATH) -> Path:
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return report_path


def append_log(report: dict[str, Any], log_path: Path = LOG_PATH) -> None:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(report, separators=(",", ":"), sort_keys=True) + "\n")


def print_report(report: dict[str, Any]) -> None:
    actual = report["actual"]
    rolling = report["rolling_actual"]
    readiness = report["scanner_readiness"]
    print("\nFlip Bot Learning Report | read-only")
    print("=" * 72)
    print(
        f"date={report['date']} closed={actual['closed_count']} "
        f"net_pnl=${actual['net_pnl']:.2f} lessons={len(report['lessons'])} "
        f"promotion_ready={readiness['promotion_ready_count']}"
    )
    print(
        f"rolling_since={rolling['window_start']} trades={rolling['closed_count']} "
        f"win_rate={rolling['win_rate']} net_pnl=${rolling['net_pnl']:.2f} "
        f"profit_factor={rolling['profit_factor']} expectancy=${rolling['expectancy']} "
        f"avg_win=${rolling['avg_win']} avg_loss=${rolling['avg_loss']} "
        f"poor_capture={rolling['poor_capture_count']}"
    )
    for lesson in report["lessons"]:
        print(f"- {lesson['type']}: {lesson.get('symbol')} severity={lesson['severity']} :: {lesson['lesson']}")
    print("No orders placed. No execution settings changed.\n")


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate Flip Bot daily learning report.")
    parser.add_argument("--date", default=date.today().isoformat())
    parser.add_argument("--report-path", type=Path, default=REPORT_PATH)
    parser.add_argument("--log-path", type=Path, default=LOG_PATH)
    parser.add_argument("--print", action="store_true", dest="do_print")
    args = parser.parse_args()

    report = build_report(day=args.date)
    write_report(report, args.report_path)
    append_log(report, args.log_path)
    if args.do_print:
        print_report(report)
    else:
        print(f"Flip Bot learning report written to {args.report_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

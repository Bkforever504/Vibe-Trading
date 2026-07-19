"""Generate read-only postmortems for closed Flip/IWM trades.

This is the discipline layer inspired by trading-journal skills: every closed
trade should earn a plain score for rule compliance, sizing, outcome, and
Market Force alignment. It does not trade.
"""
from __future__ import annotations

import argparse
import json
import re
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

try:
    from flip_exit_taxonomy import classify_exit_quality
except ModuleNotFoundError:
    from scripts.flip_exit_taxonomy import classify_exit_quality

try:
    from options_reporting import dedupe_options_trade_records
except ModuleNotFoundError:
    from scripts.options_reporting import dedupe_options_trade_records

ROOT = Path(__file__).resolve().parent.parent
VIBE_HOME = Path.home() / ".vibe-trading"
LOG_PATH = ROOT / "data" / "closed_trade_postmortem_log.jsonl"
REPORT_PATH = VIBE_HOME / "reports" / "closed-trade-postmortem.json"


def _read_json(path: Path) -> Any:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        raw = raw.strip()
        if not raw:
            continue
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict):
            rows.append(parsed)
    return rows


def _trade_date(trade: dict[str, Any]) -> str:
    for key in ("exit_date", "closed_at", "entry_date", "opened_at"):
        if trade.get(key):
            return str(trade[key])[:10]
    return ""


def _safe_float(value: Any) -> float | None:
    try:
        if value in (None, ""):
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _parse_dt(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        text = str(value).replace("Z", "+00:00")
        return datetime.fromisoformat(text)
    except ValueError:
        return None


def _hold_minutes(trade: dict[str, Any]) -> float | None:
    start = _parse_dt(trade.get("entry_at"))
    end = _parse_dt(trade.get("exit_at"))
    if not start or not end:
        return None
    return round((end - start).total_seconds() / 60.0, 2)


def _direction(trade: dict[str, Any]) -> str:
    strategy = str(trade.get("strategy") or "").lower()
    right = str(trade.get("right") or "").upper()
    if "bear" in strategy or right == "PUT":
        return "bearish"
    if "bull" in strategy or right == "CALL" or "put_spread" in strategy:
        return "bullish"
    return "neutral"


def _latest_force_for_day(day: str) -> dict[str, Any] | None:
    rows = [row for row in _read_jsonl(ROOT / "data" / "market_force_score_log.jsonl") if str(row.get("date", "")) == day]
    return rows[-1] if rows else None


def _force_alignment(direction: str, force: dict[str, Any] | None) -> tuple[int, str]:
    if not force:
        return 0, "market force unavailable"
    classification = str(force.get("classification") or "")
    if direction == "bullish" and "bullish" in classification:
        return 2, f"aligned with {classification}"
    if direction == "bearish" and "bearish" in classification:
        return 2, f"aligned with {classification}"
    if direction in {"bullish", "bearish"} and "mixed" in classification:
        return 0, "market force mixed"
    if direction in {"bullish", "bearish"} and direction not in classification:
        return -2, f"conflicted with {classification}"
    return 0, f"neutral direction vs {classification}"


def _options_pnl_estimate(trade: dict[str, Any]) -> tuple[float | None, bool]:
    pnl = _safe_float(trade.get("pnl"))
    if pnl is not None:
        return pnl, False
    credit = _safe_float(trade.get("net_credit")) or 0.0
    qty = int(trade.get("qty") or 1)
    reason = str(trade.get("closing_reason") or "")
    if credit <= 0 or not reason:
        return None, True
    match = re.search(r"([+-]?\d+(?:\.\d+)?)% of credit", reason)
    if not match:
        return None, True
    pct = float(match.group(1)) / 100.0
    return round(credit * 100 * qty * pct, 2), True


def explain_flip_pnl(trade: dict[str, Any], force: dict[str, Any] | None) -> dict[str, Any]:
    pnl = float(trade.get("pnl") or 0)
    outcome = "profit" if pnl > 0 else "loss" if pnl < 0 else "flat"
    exit_reason = str(trade.get("exit_reason") or "missing exit reason")
    catalyst = str(trade.get("catalyst") or "missing catalyst")
    contracts = int(trade.get("contracts") or 0)
    direction = _direction(trade)
    force_class = str((force or {}).get("classification") or "market force unavailable")
    evidence = [
        f"exit={exit_reason}",
        f"direction={direction}",
        f"contracts={contracts}",
    ]
    entry_price = _safe_float(trade.get("entry_price"))
    exit_price = _safe_float(trade.get("exit_price"))
    exit_return_pct = None
    if entry_price and exit_price is not None:
        exit_return_pct = ((exit_price - entry_price) / entry_price) * 100
        evidence.append(f"exit_return_pct={round(exit_return_pct, 2)}")
    quality = classify_exit_quality(
        trade.get("best_pnl_pct"),
        exit_return_pct,
        exit_reason,
    )
    hold_minutes = _hold_minutes(trade)
    giveback_pct = quality["giveback_pct"]
    capture_efficiency = quality["capture_efficiency"]
    if hold_minutes is not None:
        evidence.append(f"hold_minutes={hold_minutes}")
    if trade.get("best_pnl_pct") is not None:
        evidence.append(f"best_pnl_pct={trade.get('best_pnl_pct')}")
    evidence.append(f"exit_quality_classification={quality['exit_quality_classification']}")
    if giveback_pct is not None:
        evidence.append(f"giveback_pct={giveback_pct}")
    if capture_efficiency is not None:
        evidence.append(f"capture_efficiency={capture_efficiency}")
    if quality["favorable_excursion_surrendered_pct"] is not None:
        evidence.append(
            "favorable_excursion_surrendered_pct="
            f"{quality['favorable_excursion_surrendered_pct']}"
        )
    if catalyst:
        evidence.append(f"catalyst={catalyst}")
    if pnl > 0 and "profit protect" in exit_reason.lower():
        primary_driver = "price moved in the option direction, then faded enough for profit-protection to close it"
        if giveback_pct is not None and giveback_pct >= 25:
            next_action = "tighten profit-capture cadence or ratchet rules for similar 0DTE runners"
        else:
            next_action = "repeat only when the same entry evidence appears and profit-protection remains active"
    elif pnl > 0 and "profit" in exit_reason.lower():
        primary_driver = "price moved in the option direction enough to hit the profit target"
        next_action = "repeat only when the same entry evidence appears and sizing remains within cap"
    elif pnl > 0:
        primary_driver = "price moved in the option direction before the exit"
        next_action = "review whether the exit should be made more explicit"
    elif contracts > 5:
        primary_driver = "loss was magnified by pre-fix oversizing"
        next_action = "exclude from current-strategy grade except as a risk-control lesson"
    elif "stop" in exit_reason.lower():
        best_pnl = _safe_float(trade.get("best_pnl_pct"))
        if hold_minutes is not None and hold_minutes <= 10 and (best_pnl is None or best_pnl <= 0):
            primary_driver = "entry/regime failure: the option never moved favorably and hit stop within 10 minutes"
            next_action = "block similar primary entries when consensus says stand_aside with catalyst, higher-timeframe, or market-force caution; require ORB/retest proof or cleaner regime"
        else:
            primary_driver = "price moved against the option direction until stop rules closed it"
            next_action = "check whether entry evidence weakened before stop"
    else:
        primary_driver = "trade did not produce enough favorable movement before exit"
        next_action = "review entry timing and market context before repeating"
    return {
        "outcome": outcome,
        "pnl_source": (
            "broker_fill"
            if trade.get("exit_price_source") == "broker_fill"
            else "quote_mid_at_order_submission"
            if trade.get("exit_price_source") == "quote_mid_at_order_submission"
            else "legacy_record_unverified_fill"
        ),
        "primary_driver": primary_driver,
        "market_context": force_class,
        "evidence": evidence,
        "exit_quality": {
            **quality,
            "target_return_pct": 75.0,
            "hold_minutes": hold_minutes,
        },
        "risk_lesson": "sizing within current cap" if contracts <= 5 else "oversized versus current cap",
        "next_action": next_action,
    }


def explain_iwm_pnl(trade: dict[str, Any], force: dict[str, Any] | None) -> dict[str, Any]:
    pnl, estimated = _options_pnl_estimate(trade)
    outcome = "unknown"
    if pnl is not None:
        outcome = "profit" if pnl > 0 else "loss" if pnl < 0 else "flat"
    confidence = trade.get("candidate_confidence") if isinstance(trade.get("candidate_confidence"), dict) else {}
    conf_reasons = confidence.get("reasons") if isinstance(confidence.get("reasons"), list) else []
    close_reason = str(trade.get("closing_reason") or trade.get("exit_pending_reason") or "missing close reason")
    force_class = str((force or {}).get("classification") or "market force unavailable")
    evidence = [
        f"strategy={trade.get('strategy')}",
        f"entry_confidence={confidence.get('score')}",
        f"credit_to_risk={confidence.get('credit_to_risk')}",
        f"close_reason={close_reason}",
    ]
    evidence.extend(str(reason) for reason in conf_reasons[:4])
    if "profit" in close_reason.lower() or "near-target" in close_reason.lower():
        primary_driver = "short premium position decayed enough to reach the profit/near-target exit"
        next_action = "repeat only if credit/risk, liquidity, and trend gates remain strong"
    elif "stop" in close_reason.lower():
        primary_driver = "short premium position moved against the spread until stop criteria triggered"
        next_action = "review whether directional filter, width, or stop timing needs tightening"
    elif pnl is None:
        primary_driver = "realized option P/L is not available in the state file yet"
        next_action = "attach broker fill P/L or closing debit to the trade state"
    else:
        primary_driver = "closed without a classified exit driver"
        next_action = "improve close reason capture for this strategy"
    return {
        "outcome": outcome,
        "pnl_source": "estimated_from_credit_close_reason" if estimated else "realized",
        "primary_driver": primary_driver,
        "market_context": force_class,
        "evidence": evidence,
        "risk_lesson": "stop at or inside -100% credit" if float(trade.get("stop_loss_pct") or 0) >= -1.0 else "stop wider than current standard",
        "next_action": next_action,
    }


def score_flip_trade(trade: dict[str, Any]) -> dict[str, Any]:
    score = 5
    reasons: list[str] = []
    contracts = int(trade.get("contracts") or 0)
    pnl = float(trade.get("pnl") or 0)
    if contracts <= 5:
        score += 1
        reasons.append("contract count within current cap")
    else:
        score -= 3
        reasons.append("oversized vs current contract cap")
    if pnl > 0:
        score += 2
        reasons.append("profitable exit")
    elif pnl < 0:
        score -= 2
        reasons.append("loss trade")
    exit_reason = str(trade.get("exit_reason") or "").lower()
    if "profit target" in exit_reason:
        score += 1
        reasons.append("exited by profit target")
    elif "stop" in exit_reason:
        reasons.append("exited by stop")
    day = _trade_date(trade)
    force = _latest_force_for_day(day)
    alignment_score, alignment_reason = _force_alignment(_direction(trade), force)
    score += alignment_score
    reasons.append(alignment_reason)
    return {
        "bot": "flip_bot",
        "trade_id": trade.get("id"),
        "date": day,
        "symbol": trade.get("symbol"),
        "strategy": trade.get("strategy"),
        "direction": _direction(trade),
        "pnl": pnl,
        "score": max(0, min(10, score)),
        "grade": _grade(score),
        "reasons": reasons,
        "pnl_explanation": explain_flip_pnl(trade, force),
        "raw_ref": trade.get("option_symbol"),
    }


def score_iwm_trade(trade: dict[str, Any]) -> dict[str, Any]:
    score = 5
    reasons: list[str] = []
    confidence = trade.get("candidate_confidence") if isinstance(trade.get("candidate_confidence"), dict) else {}
    conf_score = confidence.get("score")
    if isinstance(conf_score, (int, float)):
        if conf_score >= 8:
            score += 2
            reasons.append("entry confidence met threshold")
        else:
            score -= 2
            reasons.append("entry confidence below desired threshold")
    stop = float(trade.get("stop_loss_pct") or 0)
    if stop >= -1.0:
        score += 1
        reasons.append("stop at or inside -100% credit")
    else:
        score -= 2
        reasons.append("stop wider than current standard")
    if trade.get("status") == "closed":
        reason = str(trade.get("closing_reason") or "").lower()
        if "stop" in reason:
            score -= 1
            reasons.append("closed by stop")
        else:
            reasons.append("closed without stop flag")
    day = _trade_date(trade)
    force = _latest_force_for_day(day)
    alignment_score, alignment_reason = _force_alignment(_direction(trade), force)
    score += alignment_score
    reasons.append(alignment_reason)
    pnl, estimated = _options_pnl_estimate(trade)
    return {
        "bot": "iwm_options_bot",
        "trade_id": trade.get("id"),
        "date": day,
        "symbol": trade.get("underlying"),
        "strategy": trade.get("strategy"),
        "direction": _direction(trade),
        "pnl": pnl,
        "pnl_estimated": estimated,
        "score": max(0, min(10, score)),
        "grade": _grade(score),
        "reasons": reasons,
        "pnl_explanation": explain_iwm_pnl(trade, force),
        "raw_ref": trade.get("label"),
    }


def _grade(score: int | float) -> str:
    if score >= 8:
        return "A"
    if score >= 6:
        return "B"
    if score >= 4:
        return "C"
    return "D"


def collect_closed_trades(day: str | None = None) -> list[dict[str, Any]]:
    postmortems = []
    flip = _read_json(VIBE_HOME / "flip-trades.json")
    if isinstance(flip, list):
        for trade in flip:
            if isinstance(trade, dict) and trade.get("status") == "closed":
                if day is None or _trade_date(trade) == day:
                    postmortems.append(score_flip_trade(trade))
    options = _read_json(VIBE_HOME / "options-trades.json")
    trades = options.get("trades") if isinstance(options, dict) else []
    if isinstance(trades, list):
        for trade in dedupe_options_trade_records(trades):
            if isinstance(trade, dict) and trade.get("status") == "closed":
                if day is None or _trade_date(trade) == day:
                    postmortems.append(score_iwm_trade(trade))
    return postmortems


def build_report(day: str | None = None) -> dict[str, Any]:
    day = day or date.today().isoformat()
    postmortems = collect_closed_trades(day=day)
    avg_score = round(sum(p["score"] for p in postmortems) / len(postmortems), 2) if postmortems else None
    return {
        "date": day,
        "timestamp": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "provider": "closed_trade_postmortem",
        "mode": "read_only",
        "execution_enabled": False,
        "closed_trade_count": len(postmortems),
        "avg_score": avg_score,
        "postmortems": postmortems,
        "warnings": [
            "Read-only postmortem. No broker orders are wired.",
            "Scores are process quality hints, not a guarantee of future performance.",
        ],
    }


def append_log(report: dict[str, Any], log_path: Path = LOG_PATH) -> None:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(report, separators=(",", ":")) + "\n")


def write_report(report: dict[str, Any], report_path: Path = REPORT_PATH) -> Path:
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    return report_path


def print_report(report: dict[str, Any]) -> None:
    print("\nClosed Trade Postmortem | read-only")
    print("=" * 72)
    print(f"date={report['date']} closed={report['closed_trade_count']} avg_score={report['avg_score']}")
    for row in report["postmortems"]:
        print(f"{row['bot']:<16} {row['symbol']:<5} {row['strategy']:<14} grade={row['grade']} score={row['score']} pnl={row['pnl']}")
    print("No orders placed.\n")


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate closed-trade postmortems.")
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
        print(f"Closed trade postmortem logged to {args.log_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Detect behavioral drift that ordinary process-health checks cannot see.

Read-only. No broker calls, order submission, threshold changes, or automatic
gate relaxation. The report surfaces opportunity suppression for review.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import urllib.request
from collections import Counter
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parent.parent
VIBE_HOME = Path.home() / ".vibe-trading"
DECISION_LOG = VIBE_HOME / "logs" / "flip-decisions.jsonl"
FLIP_TRADES = VIBE_HOME / "flip-trades.json"
SHADOW_REPORT = VIBE_HOME / "reports" / "flip-shadow-pnl-evaluator.json"
CONSENSUS_REPORT = VIBE_HOME / "reports" / "shadow-consensus-gate.json"
REPORT_PATH = VIBE_HOME / "reports" / "bot-behavior-regression-watchdog.json"
LOG_PATH = ROOT / "data" / "bot_behavior_regression_watchdog_log.jsonl"
NOTIFICATION_STATE_PATH = VIBE_HOME / "bot-behavior-watchdog-notification-state.json"
ENV_PATH = ROOT / "agent" / ".env"

QUALIFIED_PATH_REASONS = {
    "shadow_consensus_block",
    "same_day_reentry",
    "execution_guard_block",
    "order_submission_failed",
    "candidate_passed_all_filters",
}


def _read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        return None


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    try:
        lines = path.read_text(encoding="utf-8-sig").splitlines()
    except OSError:
        return []
    rows: list[dict[str, Any]] = []
    for raw in lines:
        try:
            row = json.loads(raw)
        except json.JSONDecodeError:
            continue
        if isinstance(row, dict):
            rows.append(row)
    return rows


def _env_value(name: str) -> str | None:
    value = os.environ.get(name)
    if value:
        return value.strip()
    try:
        lines = ENV_PATH.read_text(encoding="utf-8").splitlines()
    except OSError:
        return None
    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, _, raw = stripped.partition("=")
        if key.strip() == name:
            return raw.strip().strip('"').strip("'") or None
    return None


def _webhook_url() -> str | None:
    return _env_value("SHADOW_ALERT_WEBHOOK_URL") or _env_value("DISCORD_WEBHOOK_URL")


def _parse_time(value: Any) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _business_days_since(day: date, today: date) -> int:
    if day >= today:
        return 0
    count = 0
    cursor = day + timedelta(days=1)
    while cursor <= today:
        if cursor.weekday() < 5:
            count += 1
        cursor += timedelta(days=1)
    return count


def _setup_mismatches(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    mismatches: list[dict[str, Any]] = []
    for row in rows:
        details = row.get("details") if isinstance(row.get("details"), dict) else {}
        blockers = [str(value) for value in details.get("blockers") or []]
        right = str(details.get("right") or "").upper()
        strategy = str(row.get("strategy") or "").lower()
        issues: list[str] = []
        if right == "PUT" and any("bullish_direction" in blocker for blocker in blockers):
            issues.append("bearish_put_judged_by_bullish_direction_rule")
        if right == "CALL" and any("bearish_direction" in blocker for blocker in blockers):
            issues.append("bullish_call_judged_by_bearish_direction_rule")
        if strategy in {"0dte", "bull_trend", "bear_trend"} and any("credit_spread" in blocker for blocker in blockers):
            issues.append("long_option_judged_by_credit_spread_rule")
        if issues:
            mismatches.append({
                "ts": row.get("ts"),
                "symbol": row.get("symbol"),
                "strategy": row.get("strategy"),
                "right": right,
                "issues": issues,
            })
    return mismatches


def _positive_shadow_suppression(shadow: dict[str, Any], consensus: dict[str, Any]) -> list[dict[str, Any]]:
    by_symbol = shadow.get("by_symbol") if isinstance(shadow.get("by_symbol"), dict) else {}
    decisions = consensus.get("decisions") if isinstance(consensus.get("decisions"), list) else []
    output: list[dict[str, Any]] = []
    for decision in decisions:
        if not isinstance(decision, dict):
            continue
        symbol = str(decision.get("symbol") or "").upper()
        stats = by_symbol.get(symbol) if isinstance(by_symbol.get(symbol), dict) else {}
        expectancy = float(stats.get("out_of_sample_expectancy_return_pct") or 0.0)
        completed = int(stats.get("out_of_sample_count") or 0)
        recommendation = str(decision.get("recommendation") or "")
        if completed >= 5 and expectancy > 0 and recommendation == "stand_aside":
            output.append({
                "symbol": symbol,
                "out_of_sample_count": completed,
                "out_of_sample_expectancy_return_pct": round(expectancy, 2),
                "recommendation": recommendation,
                "blockers": decision.get("blockers") or [],
                "interpretation": "review_only_not_proof_gate_is_wrong",
            })
    return output


def build_report(
    *,
    decision_log: Path = DECISION_LOG,
    trades_path: Path = FLIP_TRADES,
    shadow_path: Path = SHADOW_REPORT,
    consensus_path: Path = CONSENSUS_REPORT,
    now: datetime | None = None,
    window_days: int = 7,
) -> dict[str, Any]:
    now = now or datetime.now(timezone.utc)
    cutoff = now - timedelta(days=max(1, window_days))
    decisions = [
        row for row in _read_jsonl(decision_log)
        if (_parse_time(row.get("ts")) or datetime.min.replace(tzinfo=timezone.utc)) >= cutoff
    ]
    reason_counts = Counter(str(row.get("reason") or "unknown") for row in decisions)
    qualified = [row for row in decisions if str(row.get("reason") or "") in QUALIFIED_PATH_REASONS]
    consensus_blocks = sum(1 for row in qualified if row.get("reason") == "shadow_consensus_block")
    consensus_block_share = consensus_blocks / len(qualified) if qualified else 0.0
    mismatches = _setup_mismatches(decisions)

    raw_trades = _read_json(trades_path)
    trades = raw_trades if isinstance(raw_trades, list) else []
    closed_dates: list[date] = []
    for trade in trades:
        if not isinstance(trade, dict) or trade.get("status") != "closed":
            continue
        raw = trade.get("exit_at") or trade.get("closed_at") or trade.get("entry_date")
        parsed = _parse_time(raw)
        if parsed:
            closed_dates.append(parsed.date())
        else:
            try:
                closed_dates.append(date.fromisoformat(str(raw)[:10]))
            except ValueError:
                pass
    last_closed = max(closed_dates) if closed_dates else None
    business_days_without_close = _business_days_since(last_closed, now.date()) if last_closed else None

    shadow = _read_json(shadow_path)
    consensus = _read_json(consensus_path)
    suppression = _positive_shadow_suppression(
        shadow if isinstance(shadow, dict) else {},
        consensus if isinstance(consensus, dict) else {},
    )

    alerts: list[dict[str, Any]] = []
    if consensus_blocks >= 5 and consensus_block_share >= 0.50:
        alerts.append({
            "code": "consensus_gate_dominates_qualified_path",
            "severity": "high",
            "observed": consensus_blocks,
            "share": round(consensus_block_share, 3),
        })
    if mismatches:
        latest_mismatch = max(
            (parsed for parsed in (_parse_time(row.get("ts")) for row in mismatches) if parsed),
            default=None,
        )
        mismatch_business_days_ago = (
            _business_days_since(latest_mismatch.date(), now.date()) if latest_mismatch else None
        )
        # A mismatch older than 2 business days with none since indicates the
        # generating defect was already repaired; the count is rolling-window
        # residue and must not keep the system in alert status.
        mismatch_active = mismatch_business_days_ago is None or mismatch_business_days_ago < 2
        alerts.append({
            "code": "setup_agnostic_gate_mismatch",
            "severity": "high" if mismatch_active else "decaying",
            "observed": len(mismatches),
            "latest_mismatch_ts": (
                latest_mismatch.isoformat().replace("+00:00", "Z") if latest_mismatch else None
            ),
            "business_days_since_latest_mismatch": mismatch_business_days_ago,
        })
    if business_days_without_close is not None and business_days_without_close >= 3:
        alerts.append({
            "code": "executed_trade_cadence_stall",
            "severity": "medium",
            "business_days_without_close": business_days_without_close,
        })
    if suppression:
        alerts.append({
            "code": "positive_shadow_symbols_still_stand_aside",
            "severity": "review",
            "symbols": [row["symbol"] for row in suppression],
        })

    return {
        "provider": "bot_behavior_regression_watchdog",
        "mode": "read_only",
        "execution_enabled": False,
        "can_submit_orders": False,
        "generated_at": now.isoformat().replace("+00:00", "Z"),
        "window_days": window_days,
        "status": "alert" if any(row["severity"] == "high" for row in alerts) else "watch" if alerts else "normal",
        "alerts": alerts,
        "decision_count": len(decisions),
        "decision_reason_counts": dict(reason_counts.most_common()),
        "qualified_path_count": len(qualified),
        "shadow_consensus_block_count": consensus_blocks,
        "shadow_consensus_block_share": round(consensus_block_share, 3),
        "setup_mismatch_count": len(mismatches),
        "setup_mismatch_examples": mismatches[-10:],
        "last_closed_trade_date": last_closed.isoformat() if last_closed else None,
        "business_days_without_close": business_days_without_close,
        "positive_shadow_suppression": suppression,
        "required_response": [
            "Investigate high-severity drift before adding more gates.",
            "Do not auto-loosen safety controls from this report.",
            "Require point-in-time counterfactual evidence before changing alpha thresholds.",
        ],
    }


def _notification_fingerprint(report: dict[str, Any]) -> str:
    material = {
        "status": report.get("status"),
        "alerts": report.get("alerts") or [],
        "setup_mismatch_count": report.get("setup_mismatch_count"),
        "shadow_consensus_block_count": report.get("shadow_consensus_block_count"),
        "business_days_without_close": report.get("business_days_without_close"),
    }
    encoded = json.dumps(material, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _format_discord_alert(report: dict[str, Any]) -> str:
    status = str(report.get("status") or "unknown").upper()
    lines = [
        f"**BOT BEHAVIOR WATCHDOG: {status}**",
        f"Window: `{report.get('window_days')} days` | Decisions: `{report.get('decision_count')}`",
        (
            "Qualified-path consensus blocks: "
            f"`{report.get('shadow_consensus_block_count')}/{report.get('qualified_path_count')}` "
            f"(`{float(report.get('shadow_consensus_block_share') or 0.0):.0%}`)"
        ),
        f"Setup mismatches: `{report.get('setup_mismatch_count')}`",
        f"Business days without a closed Flip: `{report.get('business_days_without_close')}`",
    ]
    for alert in report.get("alerts") or []:
        if not isinstance(alert, dict):
            continue
        detail = ""
        if alert.get("symbols"):
            detail = " symbols=" + ",".join(str(value) for value in alert["symbols"])
        lines.append(f"- `{alert.get('severity')}` {alert.get('code')}{detail}")
    lines.extend([
        "Review the watchdog report before adding or promoting gates.",
        "Read-only alert. No orders or threshold changes were made.",
    ])
    return "\n".join(lines)[:1900]


def _send_discord(webhook: str, message: str) -> None:
    payload = json.dumps({"content": message}).encode("utf-8")
    request = urllib.request.Request(
        webhook,
        data=payload,
        headers={
            "Content-Type": "application/json",
            "User-Agent": "VibeTrading-BehaviorWatchdog/1.0",
        },
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=10) as response:
        status = int(getattr(response, "status", 204) or 204)
        if status >= 300:
            raise RuntimeError(f"discord_http_{status}")


def notify_discord(
    report: dict[str, Any],
    *,
    state_path: Path = NOTIFICATION_STATE_PATH,
    webhook: str | None = None,
    sender: Any = _send_discord,
    notify_watch: bool | None = None,
) -> dict[str, Any]:
    """Send changed high-severity incidents once daily; never exposes the URL."""
    status = str(report.get("status") or "normal")
    if notify_watch is None:
        notify_watch = str(_env_value("BEHAVIOR_WATCHDOG_NOTIFY_WATCH") or "false").lower() in {"1", "true", "yes", "on"}
    eligible = status == "alert" or (status == "watch" and notify_watch)
    if not eligible:
        return {"status": "not_eligible", "sent": False, "watch_notifications_enabled": bool(notify_watch)}
    webhook = webhook or _webhook_url()
    if not webhook:
        return {"status": "not_configured", "sent": False, "watch_notifications_enabled": bool(notify_watch)}

    fingerprint = _notification_fingerprint(report)
    notification_day = str(report.get("generated_at") or "")[:10] or date.today().isoformat()
    prior = _read_json(state_path)
    if isinstance(prior, dict) and prior.get("fingerprint") == fingerprint and prior.get("notification_day") == notification_day:
        return {
            "status": "deduplicated",
            "sent": False,
            "fingerprint": fingerprint[:12],
            "watch_notifications_enabled": bool(notify_watch),
        }
    try:
        sender(webhook, _format_discord_alert(report))
    except Exception as exc:
        result = {
            "status": "error",
            "sent": False,
            "error": type(exc).__name__,
            "fingerprint": fingerprint[:12],
            "watch_notifications_enabled": bool(notify_watch),
        }
        status_code = getattr(exc, "code", None)
        if isinstance(status_code, int):
            result["http_status"] = status_code
        return result

    state_path.parent.mkdir(parents=True, exist_ok=True)
    temp = state_path.with_suffix(state_path.suffix + ".tmp")
    temp.write_text(json.dumps({
        "fingerprint": fingerprint,
        "notification_day": notification_day,
        "sent_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "status": status,
    }, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(temp, state_path)
    return {
        "status": "sent",
        "sent": True,
        "fingerprint": fingerprint[:12],
        "watch_notifications_enabled": bool(notify_watch),
    }


def write_report(report: dict[str, Any], report_path: Path = REPORT_PATH, log_path: Path = LOG_PATH) -> None:
    report_path.parent.mkdir(parents=True, exist_ok=True)
    temp = report_path.with_suffix(report_path.suffix + ".tmp")
    temp.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(temp, report_path)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(report, separators=(",", ":"), sort_keys=True) + "\n")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--print", action="store_true", dest="do_print")
    parser.add_argument("--window-days", type=int, default=7)
    args = parser.parse_args()
    report = build_report(window_days=args.window_days)
    report["notification"] = notify_discord(report)
    write_report(report)
    if args.do_print:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        print(f"Behavior watchdog written to {REPORT_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

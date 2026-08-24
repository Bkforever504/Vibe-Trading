#!/usr/bin/env python3
"""Build and send the deterministic weekday shadow-trading EOD check-in."""
from __future__ import annotations

import argparse
import json
import sys
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping
from zoneinfo import ZoneInfo


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from agent.notifier import send_discord
from scripts.shadow_ops import HEALTH_DIR, kill_switch_active
from scripts.shadow_system_heartbeat import build_report as build_heartbeat


CT = ZoneInfo("America/Chicago")
DATA_DIR = ROOT / "data"
REPORT_PATH = Path.home() / ".vibe-trading" / "reports" / "eod-shadow-checkin.json"
SCANNER_LOGS = {
    "Scout v1": DATA_DIR / "equity_orb_scout_v1_shadow_log.jsonl",
    "Scout v2": DATA_DIR / "equity_orb_scout_v2_shadow_log.jsonl",
    "MES ORB v2": DATA_DIR / "mes_orb_0932_vix_v2_shadow_log.jsonl",
    "MES reopen v2": DATA_DIR / "mes_reopen_drift_v2_shadow_log.jsonl",
}


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    for raw in path.read_text(encoding="utf-8-sig", errors="replace").splitlines():
        try:
            value = json.loads(raw)
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            rows.append(value)
    return rows


def _row_date(row: Mapping[str, Any]) -> str | None:
    if row.get("session_date"):
        return str(row["session_date"])[:10]
    for key in ("resolved_at", "captured_at", "generated_at", "timestamp", "created_at"):
        value = row.get(key)
        if not value:
            continue
        try:
            parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except ValueError:
            continue
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(CT).date().isoformat()
    return None


def _today(rows: Iterable[Mapping[str, Any]], session: date) -> list[dict[str, Any]]:
    target = session.isoformat()
    return [dict(row) for row in rows if _row_date(row) == target]


def _number(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _scanner_summary(label: str, rows: list[dict[str, Any]]) -> dict[str, Any]:
    entries = [row for row in rows if row.get("event_type") == "entry" and row.get("should_enter") is True]
    exits = [row for row in rows if row.get("event_type") == "exit" and row.get("outcome")]
    errors = [
        row for row in rows
        if str(row.get("event_type") or "").endswith("_error")
        or str(row.get("reason") or "").startswith("error:")
    ]
    top = sorted(entries, key=lambda row: _number(row.get("grade")), reverse=True)[:3]
    return {
        "label": label,
        "rows": len(rows),
        "qualified": len(entries),
        "resolved": len(exits),
        "wins": sum(row.get("outcome") == "win" for row in exits),
        "losses": sum(row.get("outcome") == "loss" for row in exits),
        "flats": sum(row.get("outcome") == "flat" for row in exits),
        "net_dollar": round(sum(_number(row.get("net_dollar")) for row in exits), 2),
        "errors": len(errors),
        "top_grades": [
            {
                "symbol": str(row.get("symbol") or "MES"),
                "direction": str(row.get("direction") or "?").upper(),
                "grade": round(_number(row.get("grade")), 3),
            }
            for row in top
        ],
        "exits": exits,
    }


def _halted_scanners() -> list[str]:
    if not HEALTH_DIR.exists():
        return []
    return sorted(path.stem for path in HEALTH_DIR.glob("*.halt"))


def build_report(
    *,
    session: date,
    scanner_logs: Mapping[str, Path] = SCANNER_LOGS,
    heartbeat: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    summaries = [
        _scanner_summary(label, _today(_read_jsonl(path), session))
        for label, path in scanner_logs.items()
    ]
    exits = [row for summary in summaries for row in summary.pop("exits")]
    ranked = sorted(exits, key=lambda row: _number(row.get("net_dollar")), reverse=True)
    health = dict(heartbeat or build_heartbeat())
    halts = _halted_scanners()
    kill = kill_switch_active()
    critical = health.get("status") != "PASS" or bool(halts) or kill or any(item["errors"] for item in summaries)
    outcomes_today = _today(_read_jsonl(DATA_DIR / "shadow_outcomes.jsonl"), session)
    hypothesis_events = _today(_read_jsonl(DATA_DIR / "hypothesis_ledger.jsonl"), session)
    return {
        "schema_version": 1,
        "provider": "eod_shadow_checkin",
        "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "session_date": session.isoformat(),
        "status": "ALERT" if critical else "PASS",
        "scanners": summaries,
        "totals": {
            "qualified": sum(item["qualified"] for item in summaries),
            "resolved": sum(item["resolved"] for item in summaries),
            "wins": sum(item["wins"] for item in summaries),
            "losses": sum(item["losses"] for item in summaries),
            "flats": sum(item["flats"] for item in summaries),
            "net_dollar": round(sum(item["net_dollar"] for item in summaries), 2),
            "shadow_outcomes_written": len(outcomes_today),
            "hypothesis_events": len(hypothesis_events),
        },
        "best_trade": ranked[0] if ranked else None,
        "worst_trade": ranked[-1] if ranked else None,
        "heartbeat_status": health.get("status", "UNKNOWN"),
        "kill_switch_active": kill,
        "halted_scanners": halts,
        "execution_enabled": False,
        "can_submit_orders": False,
    }


def format_report(report: Mapping[str, Any]) -> str:
    icon = "🚨" if report["status"] == "ALERT" else "✅"
    totals = report["totals"]
    lines = [
        f"{icon} **Shadow EOD check-in — {report['session_date']} — {report['status']}**",
        (
            f"Qualified={totals['qualified']} Resolved={totals['resolved']} "
            f"W/L/Flat={totals['wins']}/{totals['losses']}/{totals['flats']} "
            f"Net=${totals['net_dollar']:.2f}"
        ),
    ]
    for item in report["scanners"]:
        grades = ", ".join(
            f"{row['symbol']} {row['direction']} {row['grade']:.3f}" for row in item["top_grades"]
        ) or "none"
        lines.append(
            f"{item['label']}: Q={item['qualified']} R={item['resolved']} "
            f"W/L/F={item['wins']}/{item['losses']}/{item['flats']} top={grades}"
        )
    for title, key in (("Best", "best_trade"), ("Worst", "worst_trade")):
        row = report.get(key)
        if row:
            lines.append(
                f"{title}: {row.get('symbol') or 'MES'} {row.get('outcome')} "
                f"${_number(row.get('net_dollar')):.2f} ({row.get('exit_reason') or row.get('reason') or 'n/a'})"
            )
    lines.append(
        f"Evidence writes={totals['shadow_outcomes_written']} hypothesis events={totals['hypothesis_events']} "
        f"heartbeat={report['heartbeat_status']}"
    )
    if report["kill_switch_active"]:
        lines.append("KILL_SWITCH ACTIVE")
    if report["halted_scanners"]:
        lines.append("Auto-halted: " + ", ".join(report["halted_scanners"]))
    lines.append("Shadow/manual-review only. No order authority.")
    return "\n".join(lines)


def _write_atomic(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".partial")
    temporary.write_text(json.dumps(dict(payload), indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(path)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--session-date", type=date.fromisoformat)
    parser.add_argument("--output", type=Path, default=REPORT_PATH)
    parser.add_argument("--no-notify", action="store_true")
    args = parser.parse_args()
    session = args.session_date or datetime.now(CT).date()
    try:
        report = build_report(session=session)
    except Exception as exc:
        report = {
            "schema_version": 1,
            "provider": "eod_shadow_checkin",
            "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "session_date": session.isoformat(),
            "status": "ALERT",
            "error_type": type(exc).__name__,
            "execution_enabled": False,
            "can_submit_orders": False,
        }
    _write_atomic(args.output, report)
    message = format_report(report) if "totals" in report else f"🚨 **EOD check-in failed:** {report['error_type']}"
    notification = {"status": "disabled", "sent": False}
    if not args.no_notify:
        notification = send_discord(message)
    print(json.dumps({**report, "notification": notification}, sort_keys=True))
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())

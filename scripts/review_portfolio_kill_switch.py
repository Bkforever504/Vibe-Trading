#!/usr/bin/env python3
"""Audit and, with explicit approval, archive the paper portfolio kill switch."""
from __future__ import annotations

import argparse
import json
import os
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parent.parent
VIBE_HOME = Path.home() / ".vibe-trading"
DEFAULT_KILL = VIBE_HOME / "PORTFOLIO_KILL_SWITCH.json"
DEFAULT_REPORT_DIR = VIBE_HOME / "reports"
DEFAULT_AUDIT = DEFAULT_REPORT_DIR / "portfolio-kill-switch-review.json"
DEFAULT_ENV = ROOT / "agent" / ".env"


def _read_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
        return payload if isinstance(payload, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def _env_value(path: Path, name: str) -> str | None:
    if name in os.environ:
        return os.environ[name]
    try:
        for raw in path.read_text(encoding="utf-8-sig").splitlines():
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            if key.strip() == name:
                return value.strip().strip('"').strip("'")
    except OSError:
        pass
    return None


def _check(name: str, passed: bool, detail: str) -> dict[str, Any]:
    return {"name": name, "passed": bool(passed), "detail": detail}


def build_review(
    *,
    kill_path: Path = DEFAULT_KILL,
    report_dir: Path = DEFAULT_REPORT_DIR,
    env_path: Path = DEFAULT_ENV,
    today: str | None = None,
) -> dict[str, Any]:
    today = today or date.today().isoformat()
    current_report_dates = {today, datetime.now(timezone.utc).date().isoformat()}
    kill = _read_json(kill_path)
    concentration = _read_json(report_dir / "portfolio-concentration.json")
    reconciliation = _read_json(report_dir / "options-position-reconciliation.json")
    health = _read_json(report_dir / "signal-stack-health.json")
    execution = _read_json(report_dir / "execution-gate-audit.json")
    catalyst = _read_json(report_dir / "market-catalyst-calendar.json")

    paper_value = str(_env_value(env_path, "ALPACA_PAPER") or "").lower()
    account = concentration.get("account") if isinstance(concentration.get("account"), dict) else {}
    concentration_state = concentration.get("concentration") if isinstance(concentration.get("concentration"), dict) else {}
    recon = reconciliation.get("reconciliation") if isinstance(reconciliation.get("reconciliation"), dict) else {}
    health_summary = health.get("summary") if isinstance(health.get("summary"), dict) else {}
    hard_limit = float(kill.get("max_daily_loss_dollars") or 750.0)
    day_change = float(account.get("day_change") or 0.0)
    upcoming = catalyst.get("upcoming") if isinstance(catalyst.get("upcoming"), list) else []
    cpi_rows = [
        row for row in upcoming
        if isinstance(row, dict)
        and any("CPI" in str(event.get("name") or "") for event in row.get("events", []) if isinstance(event, dict))
    ]

    checks = [
        _check("paper_account", paper_value == "true", f"ALPACA_PAPER={paper_value or 'missing'}"),
        _check("kill_switch_active", bool(kill) and (kill.get("status") == "killed" or bool(kill.get("manual_reset_required"))), f"triggered_at={kill.get('triggered_at')} reason={kill.get('reason')}"),
        _check("current_concentration", concentration.get("date") in current_report_dates, f"report_date={concentration.get('date')} accepted_dates={sorted(current_report_dates)}"),
        _check("risk_normal", concentration_state.get("risk_level") == "normal", f"risk_level={concentration_state.get('risk_level')}"),
        _check("daily_loss_recovered", day_change > -hard_limit, f"day_change={day_change:.2f} hard_limit=-{hard_limit:.2f}"),
        _check("signed_book_balanced", recon.get("unexplained_residual") == {}, f"unexplained_residual={recon.get('unexplained_residual')} known_netted={recon.get('netted_symbols', [])}"),
        _check("signal_stack_healthy", all(int(health_summary.get(key) or 0) == 0 for key in ("error", "missing", "stale")), f"summary={health_summary}"),
        _check("execution_audit_passed", execution.get("passed") is True and int(execution.get("issue_count") or 0) == 0, f"passed={execution.get('passed')} issues={execution.get('issue_count')}"),
        _check("cpi_guard_present", bool(cpi_rows) and all("stand_aside" in (row.get("allowed_playbooks") or []) for row in cpi_rows), f"cpi_dates={[row.get('date') for row in cpi_rows]}"),
    ]
    eligible = all(item["passed"] for item in checks)
    return {
        "provider": "portfolio_kill_switch_review",
        "mode": "read_only",
        "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "date": today,
        "eligible_for_paper_reset": eligible,
        "checks": checks,
        "kill_switch": kill,
        "reset_performed": False,
        "archive_path": None,
        "warnings": [
            "Reset archives the kill file; it does not submit orders or loosen entry gates.",
            "Known P277 netting may keep reconciliation in review_required while the signed broker book remains exactly balanced.",
        ],
    }


def write_review(review: dict[str, Any], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(review, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(temp, path)


def archive_reset(review: dict[str, Any], kill_path: Path, *, approved_by: str, reason: str) -> Path:
    if not review.get("eligible_for_paper_reset"):
        raise RuntimeError("Kill-switch reset denied: one or more audit checks failed.")
    if not approved_by.strip() or not reason.strip():
        raise RuntimeError("Kill-switch reset requires approved-by and reason.")
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    archive = kill_path.parent / "archive" / f"PORTFOLIO_KILL_SWITCH.reset-{stamp}.json"
    archive.parent.mkdir(parents=True, exist_ok=True)
    if archive.exists():
        raise RuntimeError(f"Archive already exists: {archive}")
    os.replace(kill_path, archive)
    review.update({
        "mode": "approved_paper_reset",
        "reset_performed": True,
        "reset_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "approved_by": approved_by.strip(),
        "reset_reason": reason.strip(),
        "archive_path": str(archive),
    })
    return archive


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--kill-path", type=Path, default=DEFAULT_KILL)
    parser.add_argument("--report-dir", type=Path, default=DEFAULT_REPORT_DIR)
    parser.add_argument("--env-path", type=Path, default=DEFAULT_ENV)
    parser.add_argument("--audit-path", type=Path, default=DEFAULT_AUDIT)
    parser.add_argument("--approve-reset", action="store_true")
    parser.add_argument("--approved-by", default="")
    parser.add_argument("--reason", default="")
    args = parser.parse_args()

    review = build_review(kill_path=args.kill_path, report_dir=args.report_dir, env_path=args.env_path)
    if args.approve_reset:
        archive_reset(review, args.kill_path, approved_by=args.approved_by, reason=args.reason)
    write_review(review, args.audit_path)
    print(json.dumps(review, indent=2, sort_keys=True))
    return 0 if review.get("eligible_for_paper_reset") else 2


if __name__ == "__main__":
    raise SystemExit(main())

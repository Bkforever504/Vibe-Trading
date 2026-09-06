#!/usr/bin/env python3
"""Fail-closed premarket readiness check for the read-only research pipeline."""
from __future__ import annotations

import argparse
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

VIBE_HOME = Path.home() / ".vibe-trading"
ET = ZoneInfo("America/New_York")
REPORT_PATH = VIBE_HOME / "reports" / "premarket-operational-readiness.json"


def _read(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def _fresh(value: Any, now: datetime, minutes: int) -> bool:
    try:
        stamp = datetime.fromisoformat(str(value).replace("Z", "+00:00")).astimezone(timezone.utc)
    except ValueError:
        return False
    return timedelta(0) <= now.astimezone(timezone.utc) - stamp <= timedelta(minutes=minutes)


def build_report(*, radar: dict[str, Any], rvol: dict[str, Any], sec: dict[str, Any], dashboard_path: Path, now: datetime) -> dict[str, Any]:
    now = now.astimezone(ET)
    session = now.date().isoformat()
    dashboard_fresh = dashboard_path.exists() and datetime.fromtimestamp(dashboard_path.stat().st_mtime, tz=timezone.utc) >= now.astimezone(timezone.utc) - timedelta(minutes=45)
    checks = {
        "radar_snapshot": {
            "passed": str(radar.get("date") or "") == session and _fresh(radar.get("generated_at"), now, 45),
            "detail": "same-session discovery snapshot must be younger than 45 minutes",
        },
        "time_matched_rvol": {
            "passed": str(rvol.get("as_of_et") or "")[:10] == session and not (rvol.get("errors") or []) and bool(rvol.get("profiles")),
            "detail": "same-session IEX cumulative-volume baseline must exist with no source errors",
        },
        "primary_catalyst_feed": {
            "passed": str(sec.get("status") or "") == "ok" and str(sec.get("freshness") or "") == "live",
            "detail": "SEC EDGAR provenance must be live; publisher headlines do not substitute",
        },
        "dashboard_artifact": {
            "passed": dashboard_fresh,
            "detail": "dashboard artifact must be regenerated after the source checks",
        },
    }
    blockers = [f"{name}: {check['detail']}" for name, check in checks.items() if not check["passed"]]
    return {
        "schema_version": 1,
        "provider": "premarket_operational_readiness",
        "mode": "read_only_governance",
        "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "as_of_et": now.isoformat(),
        "status": "ready_for_shadow_observation" if not blockers else "blocked",
        "checks": checks,
        "blockers": blockers,
        "execution_enabled": False,
        "can_submit_orders": False,
        "interpretation": "Passing permits only shadow observation. It never authorizes an order, live trading, or a profitability claim.",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report-path", type=Path, default=REPORT_PATH)
    parser.add_argument("--radar-path", type=Path, default=VIBE_HOME / "reports" / "intraday-opportunity-radar.json")
    parser.add_argument("--rvol-path", type=Path, default=VIBE_HOME / "reports" / "intraday-rvol-baseline.json")
    parser.add_argument("--sec-path", type=Path, default=VIBE_HOME / "reports" / "sec-catalyst-feed.json")
    parser.add_argument("--dashboard-path", type=Path, default=VIBE_HOME / "dashboard.html")
    args = parser.parse_args()
    report = build_report(radar=_read(args.radar_path), rvol=_read(args.rvol_path), sec=_read(args.sec_path), dashboard_path=args.dashboard_path, now=datetime.now(timezone.utc))
    args.report_path.parent.mkdir(parents=True, exist_ok=True)
    args.report_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"Premarket readiness: {report['status']} blockers={len(report['blockers'])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Create immutable simulated lifecycles only after the governed veto gate."""
from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Mapping

VIBE_HOME = Path.home() / ".vibe-trading"
DECISION_PATH = VIBE_HOME / "reports" / "governed-shadow-decisions.json"
REPORT_PATH = VIBE_HOME / "reports" / "governed-shadow-lifecycle.json"
LEDGER_PATH = VIBE_HOME / "data" / "governed_shadow_lifecycle.jsonl"
HORIZON_MINUTES = 60


def _read_json(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        return default


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    try:
        lines = path.read_text(encoding="utf-8-sig").splitlines()
    except OSError:
        return []
    rows = []
    for line in lines:
        try:
            value = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            rows.append(value)
    return rows


def _number(value: Any) -> float | None:
    try:
        number = float(value)
        return number if number == number else None
    except (TypeError, ValueError):
        return None


def build_plan(decision: Mapping[str, Any]) -> dict[str, Any] | None:
    if decision.get("decision") != "shadow_accepted":
        return None
    candidate = decision.get("candidate") if isinstance(decision.get("candidate"), Mapping) else {}
    direction = str(candidate.get("direction") or "").upper()
    entry, stop, target = (_number(candidate.get(key)) for key in ("trigger", "stop", "target"))
    try:
        opened = datetime.fromisoformat(str(candidate.get("bar_completed_at") or "").replace("Z", "+00:00")).astimezone(timezone.utc)
    except ValueError:
        return None
    if direction not in {"LONG", "SHORT"} or None in {entry, stop, target}:
        return None
    plan_id = hashlib.sha256(f"{decision.get('event_id')}|lifecycle-v1".encode()).hexdigest()
    return {
        "schema_version": 1,
        "plan_id": plan_id,
        "decision_event_id": decision.get("event_id"),
        "candidate_key": decision.get("candidate_key"),
        "symbol": candidate.get("symbol"),
        "direction": direction,
        "setup": candidate.get("setup"),
        "grade": candidate.get("grade"),
        "state": "open_shadow_simulation",
        "opened_at": opened.isoformat().replace("+00:00", "Z"),
        "entry": entry,
        "initial_stop": stop,
        "target": target,
        "risk_points": abs(entry - stop),
        "planned_horizon_minutes": HORIZON_MINUTES,
        "planned_exit_at": (opened + timedelta(minutes=HORIZON_MINUTES)).isoformat().replace("+00:00", "Z"),
        "entry_basis": "completed_bar_planned_trigger_underlying_proxy_not_fill",
        "execution_enabled": False,
        "can_submit_orders": False,
    }


def run(decision_report: Mapping[str, Any], *, ledger_path: Path = LEDGER_PATH, report_path: Path = REPORT_PATH) -> dict[str, Any]:
    decisions = [row for row in decision_report.get("decisions") or [] if isinstance(row, Mapping)]
    plans = [plan for row in decisions if (plan := build_plan(row)) is not None]
    existing = {str(row.get("plan_id")) for row in _read_jsonl(ledger_path)}
    new = [row for row in plans if str(row.get("plan_id")) not in existing]
    if new:
        ledger_path.parent.mkdir(parents=True, exist_ok=True)
        with ledger_path.open("a", encoding="utf-8") as handle:
            for row in new:
                handle.write(json.dumps(row, sort_keys=True) + "\n")
    report = {
        "provider": "governed_shadow_lifecycle",
        "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "decision_count": len(decisions),
        "accepted_for_simulation": len(plans),
        "vetoed_observation_only": len(decisions) - len(plans),
        "new_lifecycles": len(new),
        "plans": plans,
        "execution_enabled": False,
        "can_submit_orders": False,
    }
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.parse_args()
    report = run(_read_json(DECISION_PATH, {}))
    print(json.dumps({key: report[key] for key in ("decision_count", "accepted_for_simulation", "vetoed_observation_only", "new_lifecycles")}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Sunday dry-run of the equity scout plus scheduler/source verification."""
from __future__ import annotations

import argparse
import json
import sys
import traceback
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Mapping
from zoneinfo import ZoneInfo


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from agent.notifier import redact, send_discord
from scripts.preregistration_validator import validate_spec
from scripts.shadow_ops import kill_switch_active
from scripts.shadow_system_heartbeat import (
    CATALYST_PATH,
    EXPECTED_TASKS,
    HMM_PATH,
    OBSERVABILITY_TASKS,
    _task_group,
    probe_tasks,
    report_freshness,
)


CT = ZoneInfo("America/Chicago")
REPORT_PATH = Path.home() / ".vibe-trading" / "reports" / "sunday-shadow-preflight.json"
SELF_TASK = ("\\VibeTrade\\", "SundayShadowPreflight")
# Preflight must be able to recover from a previous red run. Its own prior
# result and downstream observability consumers are not upstream readiness
# dependencies.
PREFLIGHT_TASKS = tuple(
    task for task in EXPECTED_TASKS
    if task != SELF_TASK and task not in OBSERVABILITY_TASKS
)


def previous_trading_weekday(value: date) -> date:
    candidate = value - timedelta(days=1)
    while candidate.weekday() >= 5:
        candidate -= timedelta(days=1)
    return candidate


def _write_atomic(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".partial")
    temporary.write_text(json.dumps(dict(payload), indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(path)


def run_preflight(
    *,
    now: datetime | None = None,
    network: bool = True,
    task_rows: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    from scripts import equity_orb_scout_v1_shadow as scout

    now = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    local_date = now.astimezone(CT).date()
    session = previous_trading_weekday(local_date)
    universe = scout.load_universe()
    spec = validate_spec(ROOT / scout.SPEC_PATH)
    tasks = task_rows if task_rows is not None else probe_tasks()
    task_status = _task_group(tasks, PREFLIGHT_TASKS)
    hmm = report_freshness(HMM_PATH, now=now, max_age_hours=72.0)
    catalyst = report_freshness(CATALYST_PATH, now=now, max_age_hours=36.0)

    market_data = {
        "mode": "no_network_smoke" if not network else "friday_market_data_dry_run",
        "session_date": session.isoformat(),
        "symbols_requested": len(universe["symbols"]),
        "symbols_with_complete_inputs": None,
        "eligible_setups": None,
        "coverage_ratio": None,
        "pass": not network,
    }
    if network:
        bars_1m = scout.download_bars_1m(list(universe["symbols"]))
        bars_5m = scout.download_bars_5m(list(universe["symbols"]))
        complete = 0
        eligible = 0
        for symbol in universe["symbols"]:
            decision = scout.build_symbol_plan(symbol, bars_1m, bars_5m, session)
            if decision.get("reason") not in {"no_data", "opening_range_unavailable"}:
                complete += 1
            eligible += int(decision.get("should_enter") is True)
        coverage = complete / max(1, len(universe["symbols"]))
        market_data.update(
            {
                "symbols_with_complete_inputs": complete,
                "eligible_setups": eligible,
                "coverage_ratio": round(coverage, 4),
                "pass": coverage >= 0.80,
            }
        )

    killed = kill_switch_active()
    passed = bool(spec["valid"] and task_status["alive"] and market_data["pass"] and hmm["fresh"] and catalyst["fresh"] and not killed)
    return {
        "schema_version": 1,
        "provider": "sunday_shadow_preflight",
        "generated_at": now.isoformat().replace("+00:00", "Z"),
        "status": "PASS" if passed else "FAIL",
        "spec_valid": spec["valid"],
        "universe_hash": universe["sha256_membership_hash"],
        "market_data": market_data,
        "scheduler": task_status,
        "hmm": hmm,
        "catalyst": catalyst,
        "kill_switch_active": killed,
        "execution_enabled": False,
        "can_submit_orders": False,
    }


def format_preflight(report: Mapping[str, Any]) -> str:
    icon = "✅" if report["status"] == "PASS" else "🚨"
    market = report["market_data"]
    return "\n".join(
        [
            f"{icon} **Sunday trading preflight: {report['status']}**",
            f"Spec: {'PASS' if report['spec_valid'] else 'FAIL'}",
            f"Friday scout dry-run: {'PASS' if market['pass'] else 'FAIL'} "
            f"coverage={market.get('coverage_ratio')} eligible={market.get('eligible_setups')}",
            f"Scheduled tasks Ready: {'PASS' if report['scheduler']['alive'] else 'FAIL'}",
            f"HMM fresh: {'PASS' if report['hmm']['fresh'] else 'FAIL'}",
            f"Catalyst fresh: {'PASS' if report['catalyst']['fresh'] else 'FAIL'}",
            f"Kill switch: {'ACTIVE' if report['kill_switch_active'] else 'clear'}",
            "Dry-run only. No logs, positions, or orders changed.",
        ]
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=REPORT_PATH)
    parser.add_argument("--no-network", action="store_true")
    parser.add_argument("--no-notify", action="store_true")
    args = parser.parse_args()
    try:
        report = run_preflight(network=not args.no_network)
        message = format_preflight(report)
    except Exception as exc:
        report = {
            "schema_version": 1,
            "provider": "sunday_shadow_preflight",
            "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "status": "FAIL",
            "error_type": type(exc).__name__,
            "execution_enabled": False,
            "can_submit_orders": False,
        }
        message = (
            f"🚨 **Sunday preflight exception** {type(exc).__name__}: {redact(str(exc))}\n"
            f"```\n{redact(traceback.format_exc(limit=12))[-1400:]}\n```"
        )
    _write_atomic(args.output, report)
    notification = {"status": "disabled", "sent": False}
    if not args.no_notify:
        notification = send_discord(message)
    print(json.dumps({**report, "notification": notification}, sort_keys=True))
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())

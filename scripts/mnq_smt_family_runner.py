#!/usr/bin/env python3
"""Run all frozen MNQ SMT/CISD ablations without coupling their health state."""
from __future__ import annotations

import argparse
import json
import sys
import traceback
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from agent.notifier import redact, send_discord
from scripts.shadow_alert_runner import run_guarded
from scripts.shadow_ops import kill_switch_active


SCANNER_IDS = (
    "mnq-smt-cisd-fvg-v1",
    "mnq-pdl-rejection-v1",
    "mnq-smt-only-v1",
    "mnq-cisd-only-v1",
)


def run_family(mode: str, *, smoke: bool = False) -> dict[str, Any]:
    if kill_switch_active():
        send_discord("**KILL SWITCH ACTIVE** — MNQ SMT/CISD family cycle did not run.")
        return {
            "schema_version": 1,
            "provider": "mnq_smt_family_runner",
            "mode": mode,
            "status": "killed",
            "run_count": 0,
            "failure_count": 0,
            "runs": [],
            "execution_enabled": False,
            "can_submit_orders": False,
        }
    modes = ("entry", "resolve") if mode == "cycle" else (mode,)
    rows: list[dict[str, Any]] = []
    for current_mode in modes:
        for scanner in SCANNER_IDS:
            try:
                result = run_guarded(scanner, current_mode, smoke=smoke)
            except Exception as exc:  # run_guarded normally contains failures; keep sibling ablations independent.
                stack = redact(traceback.format_exc(limit=12))
                send_discord(
                    f"**MNQ family orchestrator exception** scanner={scanner} mode={current_mode} "
                    f"error={type(exc).__name__}: {redact(str(exc))}\n```\n{stack[-1400:]}\n```"
                )
                result = {
                    "status": "orchestrator_exception",
                    "scanner": scanner,
                    "mode": current_mode,
                    "error_type": type(exc).__name__,
                    "exit_code": 1,
                }
            rows.append(result)
    failed = [row for row in rows if row.get("status") not in {"completed", "smoke_pass"}]
    return {
        "schema_version": 1,
        "provider": "mnq_smt_family_runner",
        "mode": mode,
        "status": "completed" if not failed else "partial_failure",
        "run_count": len(rows),
        "failure_count": len(failed),
        "runs": rows,
        "execution_enabled": False,
        "can_submit_orders": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=("entry", "resolve", "cycle"), default="cycle")
    parser.add_argument("--smoke", action="store_true")
    args = parser.parse_args()
    report = run_family(args.mode, smoke=args.smoke)
    print(json.dumps(report, sort_keys=True))
    return 0 if report["status"] == "completed" else 1


if __name__ == "__main__":
    raise SystemExit(main())

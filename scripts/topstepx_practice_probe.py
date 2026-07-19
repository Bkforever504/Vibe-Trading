#!/usr/bin/env python3
"""Read-only TopstepX credential, Practice-account, MES, and bar probe."""
from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import asdict
from datetime import datetime, timedelta, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from strategies.topstepx_practice_adapter import (
    PRACTICE_NAME_PATTERN,
    PracticeExecutionConfig,
    TopstepXPracticeAdapter,
    select_allowed_practice_account,
)


DEFAULT_OUTPUT = Path.home() / ".vibe-trading" / "reports" / "topstepx-practice-probe.json"


def load_agent_env(path: Path = ROOT / "agent" / ".env") -> None:
    if not path.exists():
        return
    allowed = {
        "TOPSTEPX_USERNAME",
        "TOPSTEPX_API_KEY",
        "TOPSTEPX_PRACTICE_ACCOUNT_ID",
        "TOPSTEPX_PRACTICE_EXECUTION",
        "TOPSTEPX_LOCAL_DEVICE",
    }
    for raw in path.read_text(encoding="utf-8-sig").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        if key.strip() in allowed:
            os.environ.setdefault(key.strip(), value.strip())


def run_probe(*, output: Path, days: int = 7) -> dict:
    load_agent_env()
    username = os.environ.get("TOPSTEPX_USERNAME", "").strip()
    api_key = os.environ.get("TOPSTEPX_API_KEY", "").strip()
    config = PracticeExecutionConfig.from_env()
    adapter = TopstepXPracticeAdapter(username=username, api_key=api_key, config=config)
    adapter.login()
    accounts = adapter.search_accounts()
    candidates = [account for account in accounts if PRACTICE_NAME_PATTERN.search(account.name.upper())]
    report = {
        "provider": "topstepx_practice_probe",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "mode": "read_only",
        "can_submit_orders": False,
        "active_account_count": len(accounts),
        "practice_candidates": [
            {"id": account.id, "name": account.name, "can_trade": account.can_trade, "is_visible": account.is_visible}
            for account in candidates
        ],
    }
    if config.allowed_account_id is None:
        report.update({
            "status": "configuration_required",
            "next_action": "Set TOPSTEPX_PRACTICE_ACCOUNT_ID to the returned PRACTICE candidate ID, then rerun.",
        })
    else:
        account = select_allowed_practice_account(accounts, config.allowed_account_id)
        contract = adapter.active_mes_contract()
        end = datetime.now(timezone.utc)
        bars = adapter.retrieve_bars(contract, start=end - timedelta(days=max(1, days)), end=end, minutes=5)
        report.update({
            "status": "practice_read_only_ready",
            "selected_account": asdict(account),
            "mes_contract": asdict(contract),
            "five_minute_bar_count": len(bars),
            "latest_complete_bar": bars[0].get("t") if bars else None,
            "execution_tripwires_configured": (
                config.execution_confirmation == "PRACTICE_ONLY_CONFIRMED"
                and config.local_device_confirmation == "PERSONAL_DEVICE_CONFIRMED"
            ),
        })
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--days", type=int, default=7)
    args = parser.parse_args()
    try:
        report = run_probe(output=args.output, days=args.days)
    except Exception as exc:
        report = {
            "provider": "topstepx_practice_probe",
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "mode": "read_only",
            "can_submit_orders": False,
            "status": "blocked",
            "error": f"{type(exc).__name__}: {exc}",
        }
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["status"] in {"configuration_required", "practice_read_only_ready"} else 2


if __name__ == "__main__":
    raise SystemExit(main())

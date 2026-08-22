#!/usr/bin/env python3
"""Authenticate and run the read-only MES ProjectX market recorder."""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from urllib.parse import quote


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.topstepx_practice_probe import load_agent_env
from strategies.topstepx_market_recorder import RotatingJsonlWriter, TopstepXMarketRecorder, default_output
from strategies.topstepx_practice_adapter import (
    LOCAL_DEVICE_CONFIRMATION,
    PracticeExecutionConfig,
    PracticeSafetyError,
    TopstepXPracticeAdapter,
)


DEFAULT_STATUS = Path.home() / ".vibe-trading" / "reports" / "topstepx-market-recorder.json"


def redact_error(value: BaseException, secrets: list[str]) -> str:
    message = f"{type(value).__name__}: {value}"
    for secret in secrets:
        if secret:
            message = message.replace(secret, "[REDACTED]")
            message = message.replace(quote(secret, safe=""), "[REDACTED]")
    return message


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seconds", type=int, default=900)
    parser.add_argument("--output", type=Path, default=None)
    parser.add_argument("--status", type=Path, default=DEFAULT_STATUS)
    args = parser.parse_args()
    load_agent_env()
    config = PracticeExecutionConfig.from_env()
    username = os.environ.get("TOPSTEPX_USERNAME", "")
    api_key = os.environ.get("TOPSTEPX_API_KEY", "")
    access_token = ""
    adapter = TopstepXPracticeAdapter(
        username=username,
        api_key=api_key,
        config=config,
    )
    try:
        if config.local_device_confirmation != LOCAL_DEVICE_CONFIRMATION:
            raise PracticeSafetyError("Personal-device confirmation is required for TopstepX market data")
        adapter.login()
        access_token = adapter.market_session_token()
        contract = adapter.active_mes_contract()
        recorder = TopstepXMarketRecorder(
            access_token=access_token,
            contract_id=contract.id,
            writer=RotatingJsonlWriter(args.output or default_output()),
        )
        report = recorder.run(duration_seconds=args.seconds)
        report["status"] = "ok" if report["event_count"] > 0 else "no_events"
    except Exception as exc:
        report = {
            "provider": "topstepx_market_recorder",
            "mode": "read_only",
            "execution_enabled": False,
            "can_submit_orders": False,
            "status": "blocked",
            "error": redact_error(exc, [username, api_key, access_token]),
        }
    args.status.parent.mkdir(parents=True, exist_ok=True)
    args.status.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["status"] == "ok" else 2


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Read-only Alpaca paper operations readiness and inactivity attribution."""
from __future__ import annotations

import json
import os
import subprocess
import sys
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import requests


ROOT = Path(__file__).resolve().parents[1]
ENV_PATH = ROOT / "agent" / ".env"
REPORT_PATH = Path.home() / ".vibe-trading" / "reports" / "flip-paper-operations-readiness.json"
DECISIONS_PATH = Path.home() / ".vibe-trading" / "logs" / "flip-decisions.jsonl"
CORE_TASKS = ("Flip-Bot-Entry", "Flip-Bot-Monitor", "Flip-Bot-Event-Monitor", "Flip-Bot-Exploration")


def _load_env() -> None:
    try:
        lines = ENV_PATH.read_text(encoding="utf-8", errors="ignore").splitlines()
    except OSError:
        return
    for line in lines:
        if line.strip() and not line.lstrip().startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip())


def _broker_get(path: str, params: dict[str, Any] | None = None) -> tuple[Any, str | None]:
    key = os.getenv("ALPACA_API_KEY", "")
    secret = os.getenv("ALPACA_SECRET_KEY", "")
    if not key or not secret:
        return {}, "credentials_missing"
    try:
        response = requests.get(
            "https://paper-api.alpaca.markets" + path,
            headers={"APCA-API-KEY-ID": key, "APCA-API-SECRET-KEY": secret},
            params=params,
            timeout=10,
        )
        response.raise_for_status()
        return response.json(), None
    except Exception as exc:
        return {}, f"{type(exc).__name__}:{str(exc)[:160]}"


def _scheduled_tasks() -> list[dict[str, Any]]:
    rows = []
    for name in CORE_TASKS:
        command = (
            f"$task=Get-ScheduledTask -TaskName '{name}' -ErrorAction SilentlyContinue;"
            "if($task){$info=$task|Get-ScheduledTaskInfo;[pscustomobject]@{"
            f"name='{name}';state=[string]$task.State;enabled=[bool]$task.Settings.Enabled;"
            "next_run=[string]$info.NextRunTime;last_run=[string]$info.LastRunTime;"
            "last_result=$info.LastTaskResult;wake_to_run=[bool]$task.Settings.WakeToRun;"
            "start_when_available=[bool]$task.Settings.StartWhenAvailable}|ConvertTo-Json -Compress}"
        )
        try:
            completed = subprocess.run(
                ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", command],
                capture_output=True,
                text=True,
                timeout=10,
                check=True,
            )
            payload = json.loads(completed.stdout) if completed.stdout.strip() else None
            if isinstance(payload, dict):
                rows.append(payload)
        except (OSError, subprocess.SubprocessError, json.JSONDecodeError):
            continue
    return rows


def _decision_summary() -> dict[str, Any]:
    rows = []
    try:
        lines = DECISIONS_PATH.read_text(encoding="utf-8", errors="ignore").splitlines()[-5000:]
    except OSError:
        lines = []
    for line in lines:
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(row, dict):
            rows.append(row)
    reasons = Counter(str(row.get("reason") or "unknown") for row in rows)
    return {
        "observed_decision_count": len(rows),
        "latest_decision_at": rows[-1].get("ts") if rows else None,
        "top_reasons": dict(reasons.most_common(10)),
    }


def _order_activity(orders: list[dict[str, Any]]) -> tuple[str | None, int | None, str]:
    latest = max((str(row.get("submitted_at") or "") for row in orders), default="") or None
    if latest is None:
        return None, None, "no_orders_in_21_days"
    try:
        submitted_at = datetime.fromisoformat(latest.replace("Z", "+00:00"))
        inactivity_days = max(0, (datetime.now(timezone.utc) - submitted_at).days)
    except ValueError:
        return latest, None, "order_timestamp_invalid"
    return latest, inactivity_days, "stalled_no_order_7d" if inactivity_days >= 7 else "recent_order_activity"


def build_report(account: dict[str, Any], clock: dict[str, Any], tasks: list[dict[str, Any]], orders: list[dict[str, Any]]) -> dict[str, Any]:
    by_name = {str(row.get("name")): row for row in tasks}
    launchers = {
        name: (ROOT / "scripts" / name).read_text(encoding="utf-8", errors="ignore")
        for name in ("run_flip_bot_entry.ps1", "run_flip_bot_monitor.ps1", "run_flip_bot_exploration.ps1")
    }
    exploration_registration = (ROOT / "scripts" / "register_flip_exploration_task.ps1").read_text(
        encoding="utf-8", errors="ignore"
    )
    checks = {
        "paper_account_active": account.get("status") == "ACTIVE",
        "broker_trading_not_blocked": account.get("trading_blocked") is False and account.get("account_blocked") is False,
        "options_level_available": int(account.get("options_trading_level") or account.get("options_approved_level") or 0) >= 2,
        "core_tasks_present": all(name in by_name for name in CORE_TASKS),
        "core_tasks_enabled": all(bool(by_name.get(name, {}).get("enabled")) for name in CORE_TASKS),
        "core_tasks_wake_and_catch_up": all(
            bool(by_name.get(name, {}).get("wake_to_run")) and bool(by_name.get(name, {}).get("start_when_available"))
            for name in CORE_TASKS
        ),
        "paper_only_launchers": all(
            '$env:ALPACA_PAPER = "true"' in text and '$env:FLIP_LIVE_EXECUTION_ENABLED = "false"' in text
            for text in launchers.values()
        ),
        "one_contract_one_position_caps": all(
            '$env:FLIP_MAX_CONTRACTS = "1"' in text and '$env:FLIP_MAX_OPEN_POSITIONS = "1"' in text
            for text in launchers.values()
        ),
        "paper_one_contract_budget_configured": all(
            '$env:FLIP_MAX_RISK_PCT = "0.10"' in text for text in launchers.values()
        ),
        "exploration_absolute_cap_configured": (
            '$env:FLIP_EXPLORATION_MAX_NOTIONAL_DOLLARS = "100"'
            in launchers["run_flip_bot_exploration.ps1"]
        ),
        "exploration_retry_checkpoints": all(
            checkpoint in exploration_registration for checkpoint in ('"8:40AM"', '"9:00AM"', '"9:20AM"')
        ),
        "authoritative_opra_required": all('$env:FLIP_REQUIRE_OPRA_EXECUTION_QUOTES = "true"' in text for text in launchers.values()),
        "candidate_stream_handshake_installed": "request_option_quote" in (ROOT / "strategies" / "flip_bot.py").read_text(encoding="utf-8", errors="ignore")
        and "requested_option_symbols" in (ROOT / "scripts" / "flip_event_monitor.py").read_text(encoding="utf-8", errors="ignore"),
    }
    latest_order, inactivity_days, activity_status = _order_activity(orders)
    if not all(checks.values()):
        status = "blocked"
    elif activity_status == "recent_order_activity":
        status = "ready_for_next_paper_session"
    else:
        status = "ready_but_inactive"
    return {
        "provider": "flip_paper_operations_readiness",
        "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "status": status,
        "activity_status": activity_status,
        "checks": checks,
        "broker": {
            "status": account.get("status"),
            "trading_blocked": account.get("trading_blocked"),
            "account_blocked": account.get("account_blocked"),
            "options_level": account.get("options_trading_level") or account.get("options_approved_level"),
            "market_is_open": clock.get("is_open"),
            "next_open": clock.get("next_open"),
            "next_close": clock.get("next_close"),
        },
        "tasks": tasks,
        "paper_risk_budget": {
            "modeled_account_dollars": 1000.0,
            "production_max_notional_dollars": 100.0,
            "exploration_max_notional_dollars": 100.0,
            "max_contracts": 1,
            "max_open_positions": 1,
        },
        "orders_last_21_days": len(orders),
        "latest_order_submitted_at": latest_order,
        "inactivity_days": inactivity_days,
        "decision_activity": _decision_summary(),
        "execution_enabled": False,
        "can_submit_orders": False,
        "orders_submitted_by_report": 0,
        "warnings": [
            "Readiness means the paper machinery can act; it does not guarantee a qualifying setup or a fill.",
            "The bot must remain selective. No trade is correct when a hard safety, data, liquidity, or executable-EV gate fails.",
            "Seven or more days without an order is operationally significant even when all readiness checks pass.",
        ],
    }


def main() -> int:
    _load_env()
    account, account_error = _broker_get("/v2/account")
    clock, clock_error = _broker_get("/v2/clock")
    after = (datetime.now(timezone.utc) - timedelta(days=21)).isoformat().replace("+00:00", "Z")
    orders, orders_error = _broker_get("/v2/orders", {"status": "all", "after": after, "limit": 500, "direction": "desc"})
    report = build_report(
        account if isinstance(account, dict) else {},
        clock if isinstance(clock, dict) else {},
        _scheduled_tasks(),
        orders if isinstance(orders, list) else [],
    )
    report["read_errors"] = {"account": account_error, "clock": clock_error, "orders": orders_error}
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["status"] != "blocked" else 1


if __name__ == "__main__":
    raise SystemExit(main())

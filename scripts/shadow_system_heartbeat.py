#!/usr/bin/env python3
"""Report scheduler and source freshness health to Discord."""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import date, datetime, time, timezone
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping
from zoneinfo import ZoneInfo


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from agent.notifier import send_discord
from scripts.shadow_ops import is_halted, kill_switch_active, read_state


CT = ZoneInfo("America/Chicago")
REPORT_DIR = Path.home() / ".vibe-trading" / "reports"
REPORT_PATH = REPORT_DIR / "shadow-system-heartbeat.json"
HMM_PATH = REPORT_DIR / "hmm-regime.json"
CATALYST_PATH = REPORT_DIR / "market-catalyst-calendar.json"
DATABENTO_CAPABILITY_PATH = ROOT / "data" / "databento_mes_capability.json"
MNQ_EVIDENCE_PATH = REPORT_DIR / "mnq-smt-evidence-status.json"
PATTERN_OUTCOMES_LEDGER = ROOT / "data" / "pattern_grader_outcomes.jsonl"

MES_TASKS = (
    ("\\VibeTrade\\", "MesOrb0932V2Entry"),
    ("\\VibeTrade\\", "MesOrb0932V2Resolve"),
    ("\\VibeTrade\\", "MesReopenDriftV2Entry"),
    ("\\VibeTrade\\", "MesReopenDriftV2Resolve"),
    ("\\VibeTrade\\", "MesV2DatabentoRegrade"),
)
SCOUT_TASKS = (
    ("\\VibeTrade\\", "EquityOrbScoutV1Entry"),
    ("\\VibeTrade\\", "EquityOrbScoutV1Resolve"),
    ("\\VibeTrade\\", "EquityOrbScoutV2Entry"),
    ("\\VibeTrade\\", "EquityOrbScoutV2Resolve"),
)
MNQ_SMT_TASKS = (
    ("\\VibeTrade\\", "MnqSmtCisdFamilyShadow"),
    ("\\VibeTrade\\", "MnqSmtDatabentoRegrade"),
)
PATTERN_GRADER_TASKS = (
    ("\\VibeTrade\\", "PatternGrader-Scanner-Intraday"),
    ("\\VibeTrade\\", "PatternGrader-Aggregator"),
    ("\\", "PatternGrader-OutcomeResolver"),
    ("\\", "CISD-PromotionTracker"),
    ("\\", "PromoteValidatedPatterns"),
)
OPTIONS_TASKS = (("\\", "IWM-Bot-Entry"), ("\\", "IWM-Bot-Monitor"))
OPS_TASKS = (
    ("\\VibeTrade\\", "HMMRegimeScanner"),
    ("\\VibeTrade\\", "SundayShadowPreflight"),
)
# These are observability consumers, not upstream dependencies. The heartbeat
# cannot require its own previous exit code, and the EOD check-in depends on
# the heartbeat. Keeping either in OPS_TASKS creates a circular failure that
# neither task can recover from after one red run.
OBSERVABILITY_TASKS = (
    ("\\VibeTrade\\", "ShadowSystemHeartbeat"),
    ("\\VibeTrade\\", "EodShadowCheckin"),
)
EXPECTED_TASKS = (
    MES_TASKS + SCOUT_TASKS + MNQ_SMT_TASKS + PATTERN_GRADER_TASKS
    + OPTIONS_TASKS + OPS_TASKS + OBSERVABILITY_TASKS
)


def _parse_datetime(value: Any) -> datetime | None:
    if not value:
        return None
    text = str(value).strip().replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        try:
            parsed_date = date.fromisoformat(text[:10])
        except ValueError:
            return None
        parsed = datetime.combine(parsed_date, time.min, timezone.utc)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def report_ledger_freshness(path: Path, *, now: datetime, max_age_hours: float) -> dict[str, Any]:
    """Verify a JSONL append-only ledger has grown recently.

    A resolver task can succeed (exit code 0) and still write zero rows. This
    check reads the last usable timestamp from the tail of the file so the
    heartbeat can see the difference between a task that ran and a task that
    ran AND produced evidence.
    """
    if not path.exists():
        return {"status": "missing", "fresh": False, "age_hours": None, "path": str(path), "row_count": 0}
    row_count = 0
    last_ts: datetime | None = None
    try:
        for raw in path.read_text(encoding="utf-8-sig").splitlines():
            raw = raw.strip()
            if not raw:
                continue
            try:
                row = json.loads(raw)
            except json.JSONDecodeError:
                continue
            if not isinstance(row, dict):
                continue
            row_count += 1
            for key in ("resolved_at", "generated_at", "scanned_at", "timestamp"):
                parsed = _parse_datetime(row.get(key))
                if parsed is not None:
                    last_ts = parsed if last_ts is None or parsed > last_ts else last_ts
                    break
    except OSError:
        return {"status": "unreadable", "fresh": False, "age_hours": None, "path": str(path), "row_count": 0}
    if row_count == 0:
        return {"status": "empty", "fresh": False, "age_hours": None, "path": str(path), "row_count": 0}
    if last_ts is None:
        return {"status": "no_timestamp", "fresh": False, "age_hours": None, "path": str(path), "row_count": row_count}
    age = max(0.0, (now.astimezone(timezone.utc) - last_ts).total_seconds() / 3600.0)
    return {
        "status": "fresh" if age <= max_age_hours else "stale",
        "fresh": age <= max_age_hours,
        "age_hours": round(age, 2),
        "last_row_at": last_ts.isoformat().replace("+00:00", "Z"),
        "row_count": row_count,
        "path": str(path),
    }


def report_freshness(path: Path, *, now: datetime, max_age_hours: float) -> dict[str, Any]:
    if not path.exists():
        return {"status": "missing", "fresh": False, "age_hours": None, "path": str(path)}
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        payload = {}
    candidates = (
        payload.get("generated_at"),
        payload.get("probed_at"),
        payload.get("timestamp"),
        payload.get("as_of"),
        payload.get("date"),
    ) if isinstance(payload, dict) else ()
    observed = next((parsed for raw in candidates if (parsed := _parse_datetime(raw)) is not None), None)
    if observed is None:
        observed = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)
    age = max(0.0, (now.astimezone(timezone.utc) - observed).total_seconds() / 3600.0)
    return {
        "status": "fresh" if age <= max_age_hours else "stale",
        "fresh": age <= max_age_hours,
        "age_hours": round(age, 2),
        "observed_at": observed.isoformat().replace("+00:00", "Z"),
        "path": str(path),
    }


def probe_tasks() -> list[dict[str, Any]]:
    wanted = [{"path": path, "name": name} for path, name in EXPECTED_TASKS]
    encoded = json.dumps(wanted, separators=(",", ":")).replace("'", "''")
    command = (
        f"$wanted = ConvertFrom-Json '{encoded}'; "
        "$rows = foreach ($item in $wanted) { "
        "$task = Get-ScheduledTask -TaskPath $item.path -TaskName $item.name -ErrorAction SilentlyContinue; "
        "if ($null -eq $task) { [pscustomobject]@{TaskPath=$item.path;TaskName=$item.name;State='Missing';LastTaskResult=$null} } "
        "else { $info = Get-ScheduledTaskInfo -TaskPath $item.path -TaskName $item.name; "
        "[pscustomobject]@{TaskPath=$task.TaskPath;TaskName=$task.TaskName;State=[string]$task.State;LastTaskResult=$info.LastTaskResult} } }; "
        "$rows | ConvertTo-Json -Compress"
    )
    completed = subprocess.run(
        ["powershell.exe", "-NoProfile", "-Command", command],
        capture_output=True,
        text=True,
        timeout=30,
        check=True,
    )
    payload = json.loads(completed.stdout or "[]")
    return payload if isinstance(payload, list) else [payload]


def _task_group(rows: Iterable[Mapping[str, Any]], expected: tuple[tuple[str, str], ...]) -> dict[str, Any]:
    indexed = {(str(row.get("TaskPath")), str(row.get("TaskName"))): row for row in rows}
    detail: list[dict[str, Any]] = []
    for key in expected:
        row = indexed.get(key, {"TaskPath": key[0], "TaskName": key[1], "State": "Missing"})
        state = str(row.get("State") or "Missing")
        result = row.get("LastTaskResult")
        # 0x41303 (267011) means a newly registered task has not run yet; its
        # Ready state is healthy until the first scheduled execution.
        healthy = state in {"Ready", "Running"} and (result in {None, 0, 267009, 267011})
        detail.append({"task_path": key[0], "task_name": key[1], "state": state, "last_result": result, "healthy": healthy})
    return {"alive": all(row["healthy"] for row in detail), "tasks": detail}


def build_report(
    *,
    now: datetime | None = None,
    task_rows: list[dict[str, Any]] | None = None,
    hmm_path: Path = HMM_PATH,
    catalyst_path: Path = CATALYST_PATH,
    databento_capability_path: Path = DATABENTO_CAPABILITY_PATH,
    mnq_evidence_path: Path = MNQ_EVIDENCE_PATH,
    pattern_outcomes_path: Path = PATTERN_OUTCOMES_LEDGER,
) -> dict[str, Any]:
    now = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    tasks = task_rows if task_rows is not None else probe_tasks()
    mes = _task_group(tasks, MES_TASKS)
    scout = _task_group(tasks, SCOUT_TASKS)
    mnq_smt = _task_group(tasks, MNQ_SMT_TASKS)
    pattern_grader = _task_group(tasks, PATTERN_GRADER_TASKS)
    options = _task_group(tasks, OPTIONS_TASKS)
    ops = _task_group(tasks, OPS_TASKS)
    observability = _task_group(tasks, OBSERVABILITY_TASKS)
    pattern_outcomes_ledger = report_ledger_freshness(pattern_outcomes_path, now=now, max_age_hours=30.0)
    pattern_grader["alive"] = pattern_grader["alive"] and pattern_outcomes_ledger["fresh"]
    scanner_halts = {
        name: {"halted": is_halted(name), "state": read_state(name)}
        for name in (
            "mes-orb-v2",
            "mes-reopen-v2",
            "equity-orb-scout-v1",
            "equity-orb-scout-v2",
            "mnq-smt-cisd-fvg-v1",
            "mnq-pdl-rejection-v1",
            "mnq-smt-only-v1",
            "mnq-cisd-only-v1",
        )
    }
    mes["alive"] = mes["alive"] and not any(scanner_halts[name]["halted"] for name in ("mes-orb-v2", "mes-reopen-v2"))
    scout["alive"] = scout["alive"] and not any(
        scanner_halts[name]["halted"] for name in ("equity-orb-scout-v1", "equity-orb-scout-v2")
    )
    mnq_smt["alive"] = mnq_smt["alive"] and not any(
        scanner_halts[name]["halted"]
        for name in ("mnq-smt-cisd-fvg-v1", "mnq-pdl-rejection-v1", "mnq-smt-only-v1", "mnq-cisd-only-v1")
    )
    hmm = report_freshness(hmm_path, now=now, max_age_hours=72.0)
    catalyst = report_freshness(catalyst_path, now=now, max_age_hours=36.0)
    databento_capability = report_freshness(databento_capability_path, now=now, max_age_hours=30.0)
    mnq_evidence = report_freshness(mnq_evidence_path, now=now, max_age_hours=30.0)
    kill = kill_switch_active()
    healthy = (
        mes["alive"]
        and scout["alive"]
        and mnq_smt["alive"]
        and pattern_grader["alive"]
        and options["alive"]
        and ops["alive"]
        and hmm["fresh"]
        and catalyst["fresh"]
        and databento_capability["fresh"]
        and mnq_evidence["fresh"]
        and pattern_outcomes_ledger["fresh"]
        and not kill
    )
    return {
        "schema_version": 1,
        "provider": "shadow_system_heartbeat",
        "generated_at": now.isoformat().replace("+00:00", "Z"),
        "status": "PASS" if healthy else "FAIL",
        "mes_v2": mes,
        "equity_scout": scout,
        "mnq_smt_family": mnq_smt,
        "pattern_grader": pattern_grader,
        "pattern_outcomes_ledger": pattern_outcomes_ledger,
        "options_bot": options,
        "operations_tasks": ops,
        "observability_tasks": observability,
        "hmm": hmm,
        "catalyst": catalyst,
        "databento_capability": databento_capability,
        "mnq_databento_evidence": mnq_evidence,
        "scanner_halts": scanner_halts,
        "kill_switch_active": kill,
        "execution_enabled": False,
        "can_submit_orders": False,
    }


def format_heartbeat(report: Mapping[str, Any]) -> str:
    icon = "✅" if report["status"] == "PASS" else "🚨"
    check = lambda value: "OK" if value else "FAIL"
    return "\n".join(
        [
            f"{icon} **Trading system heartbeat: {report['status']}**",
            f"MES v2 alive: {check(report['mes_v2']['alive'])}",
            f"Equity scout alive: {check(report['equity_scout']['alive'])}",
            f"MNQ SMT family alive: {check(report['mnq_smt_family']['alive'])}",
            f"Pattern grader alive: {check(report['pattern_grader']['alive'])}",
            f"Pattern outcomes fresh: {check(report['pattern_outcomes_ledger']['fresh'])} (age={report['pattern_outcomes_ledger']['age_hours']}h, rows={report['pattern_outcomes_ledger']['row_count']})",
            f"Options bot alive: {check(report['options_bot']['alive'])}",
            f"HMM fresh: {check(report['hmm']['fresh'])} (age={report['hmm']['age_hours']}h)",
            f"Catalyst fresh: {check(report['catalyst']['fresh'])} (age={report['catalyst']['age_hours']}h)",
            f"Databento probe fresh: {check(report['databento_capability']['fresh'])} (age={report['databento_capability']['age_hours']}h)",
            f"MNQ MBO evidence fresh: {check(report['mnq_databento_evidence']['fresh'])} (age={report['mnq_databento_evidence']['age_hours']}h)",
            f"Kill switch: {'ACTIVE' if report['kill_switch_active'] else 'clear'}",
            "Monitoring only. No order authority.",
        ]
    )


def _write_atomic(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".partial")
    temporary.write_text(json.dumps(dict(payload), indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(path)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=REPORT_PATH)
    parser.add_argument("--no-notify", action="store_true")
    args = parser.parse_args()
    try:
        report = build_report()
    except Exception as exc:
        report = {
            "schema_version": 1,
            "provider": "shadow_system_heartbeat",
            "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "status": "FAIL",
            "error_type": type(exc).__name__,
            "execution_enabled": False,
            "can_submit_orders": False,
        }
    _write_atomic(args.output, report)
    notification = {"status": "disabled", "sent": False}
    if not args.no_notify:
        notification = send_discord(format_heartbeat(report) if "mes_v2" in report else f"🚨 **Heartbeat exception** {report.get('error_type')}")
    print(json.dumps({**report, "notification": notification}, sort_keys=True))
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())

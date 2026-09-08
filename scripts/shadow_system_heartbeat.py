#!/usr/bin/env python3
"""Report scheduler and source freshness health to Discord."""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import date, datetime, time, timezone
from functools import lru_cache
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

# Intraday scanner ledgers whose freshness proves the scan cadence itself is
# alive during regular trading hours. A >15-minute gap here on 2026-08-26
# corresponded to the Modern Standby nap that silenced the radar from
# 10:13-12:28 CT and let four qualified QQQ move windows pass unmeasured.
# Only include artifacts that append once per scheduled scan. Strategy event
# ledgers append only when a setup appears, so using them as cadence evidence
# would falsely mark a healthy quiet scanner as stalled.
INTRADAY_SCANNER_LEDGERS = (
    ("marketwide_intraday_radar", ROOT / "data" / "intraday_opportunity_radar_cadence.jsonl"),
)
# The governed marketwide cadence begins at 08:35 CT. Starting freshness
# enforcement earlier would create a guaranteed false alarm before its first
# scheduled snapshot.
MARKET_OPEN_CT = (8, 35)
MARKET_CLOSE_CT = (15, 0)
MAX_SCANNER_GAP_MINUTES = 15.0

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
)
MNQ_EVIDENCE_TASKS = (
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
RADAR_TASKS = (("\\", "IntradayOpportunityRadar"),)
APLUS_TASKS = (("\\VibeTrade\\", "APlusSpotlight"),)
CATALYST_TAPE_TASKS = (("\\VibeTrade\\", "CatalystTapeShadow"),)
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
    MES_TASKS + SCOUT_TASKS + MNQ_SMT_TASKS + MNQ_EVIDENCE_TASKS + PATTERN_GRADER_TASKS
    + OPTIONS_TASKS + RADAR_TASKS + APLUS_TASKS + CATALYST_TAPE_TASKS + OPS_TASKS + OBSERVABILITY_TASKS
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


@lru_cache(maxsize=32)
def _equity_session(session_date: date) -> tuple[datetime, datetime] | None:
    """Exchange schedule, including holidays/early closes; never guess weekdays."""
    import pandas_market_calendars as mcal

    schedule = mcal.get_calendar("NYSE").schedule(start_date=session_date, end_date=session_date)
    if schedule.empty:
        return None
    row = schedule.iloc[0]
    opened = row["market_open"].to_pydatetime().astimezone(CT)
    closed = row["market_close"].to_pydatetime().astimezone(CT)
    cadence_start = opened.replace(hour=MARKET_OPEN_CT[0], minute=MARKET_OPEN_CT[1])
    return max(opened, cadence_start), closed


def _in_regular_session(now_ct: datetime) -> bool:
    session = _equity_session(now_ct.date())
    return session is not None and session[0] <= now_ct <= session[1]


def _latest_row_timestamp(path: Path) -> datetime | None:
    if not path.exists():
        return None
    try:
        with path.open("rb") as handle:
            handle.seek(0, 2)
            size = handle.tell()
            handle.seek(max(0, size - 200_000))
            tail = handle.read().decode("utf-8-sig", errors="ignore")
    except OSError:
        return None
    latest: datetime | None = None
    # Only tail is needed for freshness; read at most ~200KB so this stays
    # cheap even when the pattern ledger grows into hundreds of megabytes.
    for raw in tail.splitlines():
        raw = raw.strip()
        if not raw:
            continue
        try:
            row = json.loads(raw)
        except json.JSONDecodeError:
            continue
        if not isinstance(row, dict):
            continue
        for key in ("captured_at", "scanned_at", "generated_at", "as_of_et", "bar_close_ts", "trigger_bar_ts", "resolved_at", "timestamp"):
            parsed = _parse_datetime(row.get(key))
            if parsed is not None:
                latest = parsed if latest is None or parsed > latest else latest
                break
    if latest is not None:
        return latest
    try:
        return datetime.fromtimestamp(path.stat().st_mtime, timezone.utc)
    except OSError:
        return None


def _session_row_timestamps(path: Path, session_date: date) -> list[datetime]:
    """Read the compact cadence ledger and return ordered timestamps for one CT session."""
    try:
        lines = path.read_text(encoding="utf-8-sig").splitlines()
    except OSError:
        return []
    stamps: set[datetime] = set()
    for raw in lines:
        try:
            row = json.loads(raw)
        except json.JSONDecodeError:
            continue
        if not isinstance(row, dict):
            continue
        parsed = next(
            (
                value
                for key in ("as_of_et", "generated_at", "captured_at", "scanned_at", "timestamp")
                if (value := _parse_datetime(row.get(key))) is not None
            ),
            None,
        )
        if parsed is not None and parsed.astimezone(CT).date() == session_date:
            stamps.add(parsed.astimezone(timezone.utc))
    return sorted(stamps)


def report_scanner_gaps(
    ledgers: tuple[tuple[str, Path], ...] = INTRADAY_SCANNER_LEDGERS,
    *,
    now: datetime,
    max_gap_minutes: float = MAX_SCANNER_GAP_MINUTES,
) -> dict[str, Any]:
    """Fail loudly when a cadence-emitting scanner ledger stops during RTH.

    A scanner task can be Ready and its LastTaskResult 0, but if the host
    slept through Modern Standby the ledger has no new rows for the entire
    outage. This surfaces that gap so the heartbeat cannot report PASS while
    the market was moving without us. Event-only strategy ledgers are excluded
    because an absence of signals is not evidence that their task did not run.
    """
    now_ct = now.astimezone(CT)
    try:
        session = _equity_session(now_ct.date())
    except Exception as exc:
        return {"status": "calendar_unavailable", "error_type": type(exc).__name__,
                "in_regular_session": None, "session_started": None, "any_stalled": None,
                "worst_gap_minutes": None, "scanners": [], "max_gap_minutes": max_gap_minutes}
    in_rth = session is not None and session[0] <= now_ct <= session[1]
    open_ct, close_ct = session or (now_ct, now_ct)
    session_started = session is not None and now_ct >= open_ct
    observation_end = min(now_ct, close_ct) if session_started else open_ct
    scanners: list[dict[str, Any]] = []
    worst_gap = 0.0
    any_stalled = False
    for name, path in ledgers:
        observations = _session_row_timestamps(path, now_ct.date()) if session_started else []
        observations = [stamp for stamp in observations if open_ct <= stamp <= observation_end]
        latest = observations[-1] if observations else _latest_row_timestamp(path)
        gap_candidates: list[tuple[float, datetime, datetime]] = []
        if session_started:
            boundaries = [open_ct.astimezone(timezone.utc), *observations, observation_end.astimezone(timezone.utc)]
            for left, right in zip(boundaries, boundaries[1:]):
                gap_candidates.append(((right - left).total_seconds() / 60.0, left, right))
        worst = max(gap_candidates, default=(0.0, open_ct.astimezone(timezone.utc), open_ct.astimezone(timezone.utc)), key=lambda row: row[0])
        gap_minutes = max(0.0, worst[0]) if session_started else None
        stalled = bool(session_started and gap_minutes is not None and gap_minutes > max_gap_minutes)
        if stalled:
            any_stalled = True
        if gap_minutes is not None:
            worst_gap = max(worst_gap, gap_minutes)
        scanners.append({
            "name": name,
            "path": str(path),
            "latest_row_at": latest.isoformat().replace("+00:00", "Z") if latest else None,
            "gap_minutes": round(gap_minutes, 2) if gap_minutes is not None else None,
            "gap_start_at": worst[1].isoformat().replace("+00:00", "Z") if session_started else None,
            "gap_end_at": worst[2].isoformat().replace("+00:00", "Z") if session_started else None,
            "session_date": now_ct.date().isoformat() if session_started else None,
            "observation_count": len(observations),
            "stalled": stalled,
        })
    return {
        "status": "stalled" if any_stalled else "healthy" if session is not None else "market_closed",
        "in_regular_session": in_rth,
        "session_started": session_started,
        "max_gap_minutes": max_gap_minutes,
        "worst_gap_minutes": round(worst_gap, 2),
        "any_stalled": any_stalled,
        "scanners": scanners,
    }


def report_futures_coverage(
    databento_capability_path: Path = DATABENTO_CAPABILITY_PATH,
) -> dict[str, Any]:
    """Explicit futures-coverage state to prevent "no NQ moves" false-negatives.

    Values:
      - live_mbo:       Databento GLBX.MDP3 MBO entitlement confirmed active.
      - delayed_proxy:  Only yfinance/CME-delayed proxy; not executable.
      - unavailable:    No futures data at all.
    """
    payload: dict[str, Any] = {}
    if databento_capability_path.exists():
        try:
            payload = json.loads(databento_capability_path.read_text(encoding="utf-8-sig"))
        except (OSError, json.JSONDecodeError):
            payload = {}
    if not isinstance(payload, dict):
        payload = {}
    entitled = bool(
        payload.get("glbx_mdp3_entitled")
        or payload.get("mbo_available")
        or payload.get("live_status") == "available"
    )
    proxy_ok = bool(
        payload.get("yfinance_proxy_ok")
        or payload.get("delayed_proxy")
        or payload.get("historical_regrade_supported")
    )
    if entitled:
        state = "live_mbo"
    elif proxy_ok:
        state = "delayed_proxy"
    else:
        state = "unavailable"
    return {
        "state": state,
        "live_mbo": state == "live_mbo",
        "delayed_proxy": state == "delayed_proxy",
        "unavailable": state == "unavailable",
        "source": str(databento_capability_path),
        "raw_flags": {
            "glbx_mdp3_entitled": payload.get("glbx_mdp3_entitled"),
            "mbo_available": payload.get("mbo_available"),
            "yfinance_proxy_ok": payload.get("yfinance_proxy_ok"),
            "historical_regrade_supported": payload.get("historical_regrade_supported"),
            "live_status": payload.get("live_status"),
        },
    }


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
        "$ErrorActionPreference = 'Stop'; "
        f"$wanted = ConvertFrom-Json '{encoded}'; "
        "$service = New-Object -ComObject 'Schedule.Service'; $service.Connect(); "
        "$states = @('Unknown','Disabled','Queued','Ready','Running'); $folders = @{}; "
        "$rows = foreach ($item in $wanted) { "
        "try { if (-not $folders.ContainsKey($item.path)) { "
        "$folderPath = $item.path.TrimEnd([char]92); if (-not $folderPath) { $folderPath = [string][char]92 }; "
        "$folders[$item.path] = $service.GetFolder($folderPath) }; "
        "$task = $folders[$item.path].GetTask($item.name); "
        "[pscustomobject]@{TaskPath=$item.path;TaskName=$item.name;State=$states[[int]$task.State];LastTaskResult=$task.LastTaskResult} "
        "} catch { $code = $_.Exception.HResult; $state = 'Unknown'; $errorKind = 'scheduler_query_error'; "
        "if ($code -eq -2147024894 -or $code -eq -2147024893) { $state = 'Missing'; $errorKind = 'task_missing' }; "
        "[pscustomobject]@{TaskPath=$item.path;TaskName=$item.name;State=$state;LastTaskResult=$null;ProbeError=$errorKind} } }; "
        "$rows | ConvertTo-Json -Compress"
    )
    error = None
    try:
        completed = subprocess.run(
            ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", command],
            capture_output=True, text=True, timeout=20, check=True,
        )
        payload = json.loads(completed.stdout or "[]")
        rows = payload if isinstance(payload, list) else [payload]
        if any(not isinstance(row, dict) for row in rows):
            raise ValueError("invalid scheduler rows")
    except subprocess.TimeoutExpired:
        error, rows = "timeout", []
    except (OSError, subprocess.CalledProcessError, ValueError):
        error, rows = "scheduler_probe_unavailable", []
    indexed = {(row.get("TaskPath"), row.get("TaskName")): row for row in rows}
    return [indexed.get((path, name), {"TaskPath": path, "TaskName": name,
            "State": "Unknown", "LastTaskResult": None,
            "ProbeError": error or "missing_probe_row"}) for path, name in EXPECTED_TASKS]


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
    probe_errors = sorted({row["ProbeError"] for row in tasks if row.get("ProbeError")})
    observed = sum(row.get("State") not in {"Unknown", None} for row in tasks)
    task_probe = {"status": "complete" if not probe_errors else "partial" if observed else "unavailable",
                  "errors": probe_errors, "observed_count": observed, "expected_count": len(EXPECTED_TASKS)}
    mes = _task_group(tasks, MES_TASKS)
    scout = _task_group(tasks, SCOUT_TASKS)
    mnq_smt = _task_group(tasks, MNQ_SMT_TASKS)
    mnq_evidence_tasks = _task_group(tasks, MNQ_EVIDENCE_TASKS)
    pattern_grader = _task_group(tasks, PATTERN_GRADER_TASKS)
    options = _task_group(tasks, OPTIONS_TASKS)
    radar = _task_group(tasks, RADAR_TASKS)
    aplus = _task_group(tasks, APLUS_TASKS)
    ops = _task_group(tasks, OPS_TASKS)
    observability = _task_group(tasks, OBSERVABILITY_TASKS)
    pattern_outcomes_ledger = report_ledger_freshness(pattern_outcomes_path, now=now, max_age_hours=30.0)
    pattern_grader["alive"] = pattern_grader["alive"] and pattern_outcomes_ledger["fresh"]
    scanner_gaps = report_scanner_gaps(now=now)
    futures_coverage = report_futures_coverage(databento_capability_path)
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
        and radar["alive"]
        and aplus["alive"]
        and ops["alive"]
        and hmm["fresh"]
        and catalyst["fresh"]
        and pattern_outcomes_ledger["fresh"]
        and scanner_gaps["status"] in {"healthy", "market_closed"}
        and not kill
    )
    research_status = (
        "DEGRADED"
        if (
            not mnq_evidence_tasks["alive"]
            or not databento_capability["fresh"]
            or not mnq_evidence["fresh"]
        )
        else "LIVE"
        if futures_coverage["state"] == "live_mbo"
        else "DELAYED_ONLY"
        if futures_coverage["state"] == "delayed_proxy"
        else "UNAVAILABLE"
    )
    return {
        "schema_version": 1,
        "provider": "shadow_system_heartbeat",
        "generated_at": now.isoformat().replace("+00:00", "Z"),
        "status": "PASS" if healthy else "FAIL",
        "status_scope": "core_scheduled_operations",
        "research_status": research_status,
        "task_probe": task_probe,
        "mes_v2": mes,
        "equity_scout": scout,
        "mnq_smt_family": mnq_smt,
        "mnq_evidence_regrade": mnq_evidence_tasks,
        "pattern_grader": pattern_grader,
        "pattern_outcomes_ledger": pattern_outcomes_ledger,
        "options_bot": options,
        "marketwide_radar": radar,
        "aplus_spotlight": aplus,
        "operations_tasks": ops,
        "observability_tasks": observability,
        "hmm": hmm,
        "catalyst": catalyst,
        "databento_capability": databento_capability,
        "mnq_databento_evidence": mnq_evidence,
        "scanner_halts": scanner_halts,
        "scanner_gaps": scanner_gaps,
        "futures_coverage": futures_coverage,
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
            f"MNQ delayed evidence task: {check(report['mnq_evidence_regrade']['alive'])}",
            f"Pattern grader alive: {check(report['pattern_grader']['alive'])}",
            f"Pattern outcomes fresh: {check(report['pattern_outcomes_ledger']['fresh'])} (age={report['pattern_outcomes_ledger']['age_hours']}h, rows={report['pattern_outcomes_ledger']['row_count']})",
            f"Options bot alive: {check(report['options_bot']['alive'])}",
            f"Marketwide radar alive: {check(report['marketwide_radar']['alive'])}",
            f"A+ spotlight alive: {check(report['aplus_spotlight']['alive'])}",
            f"HMM fresh: {check(report['hmm']['fresh'])} (age={report['hmm']['age_hours']}h)",
            f"Catalyst fresh: {check(report['catalyst']['fresh'])} (age={report['catalyst']['age_hours']}h)",
            f"Databento probe fresh: {check(report['databento_capability']['fresh'])} (age={report['databento_capability']['age_hours']}h)",
            f"MNQ MBO evidence fresh: {check(report['mnq_databento_evidence']['fresh'])} (age={report['mnq_databento_evidence']['age_hours']}h)",
            f"Scanner gaps: {report.get('scanner_gaps', {}).get('status', 'unknown')} (worst={report.get('scanner_gaps', {}).get('worst_gap_minutes')}m, rth={report.get('scanner_gaps', {}).get('in_regular_session')})",
            f"Futures coverage: {report.get('futures_coverage', {}).get('state', 'unknown')}",
            f"Research evidence lane: {report.get('research_status', 'UNKNOWN')}",
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

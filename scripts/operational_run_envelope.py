#!/usr/bin/env python3
"""Persistent, fail-honest operational run envelopes for scanner jobs.

This module supervises evidence, not trading decisions.  It never calls a
broker and every emitted record explicitly denies order authority.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping


VIBE_HOME = Path.home() / ".vibe-trading"
CANONICAL_ROOT = VIBE_HOME / "health" / "run-envelopes"
DEFAULT_ROOT = Path(os.environ.get("VIBE_RUN_ENVELOPE_HOME", CANONICAL_ROOT))
SCHEMA_VERSION = "run-envelope-v1"
FAILURE_THRESHOLD = 3
DEFAULT_FRESHNESS_SLA_SECONDS = 900
SUCCESS_STATES = {"success", "completed", "ok"}
FAILURE_STATES = {
    "failed", "error", "timeout", "partial", "stale", "delivery_failure",
    "malformed_output", "reconciliation_mismatch", "silent_failure", "blocked_breaker",
}
FAILURE_CLASSES = {
    "timeout", "stale_input", "provider_unavailable", "partial_universe",
    "malformed_output", "delivery_failure", "reconciliation_mismatch",
    "policy_veto", "process_error", "silent_failure", "unknown",
}


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def utc_z(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def parse_time(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def safe_component(value: str) -> str:
    cleaned = re.sub(r"[^a-z0-9_.-]+", "-", str(value).lower()).strip("-.")
    if not cleaned:
        raise ValueError("component_invalid")
    return cleaned


def redact_error(value: Any, limit: int = 300) -> str:
    text = str(value or "")
    text = re.sub(r"https://(?:discord(?:app)?\.com)/api/webhooks/[^\s]+", "[REDACTED_WEBHOOK]", text, flags=re.I)
    text = re.sub(r"(?i)(authorization\s*:\s*(?:bearer|basic))\s+[^\s,;]+", r"\1 [REDACTED]", text)
    text = re.sub(r"(?i)(api[_-]?key|token|secret|password|apca-api-key-id|apca-api-secret-key)\s*[:=]\s*[^\s,;&]+", r"\1=[REDACTED]", text)
    text = re.sub(r"(?i)([?&](?:api[_-]?key|token|secret|password)=)[^&\s]+", r"\1[REDACTED]", text)
    text = re.sub(r"(?i)(https?://)[^/@\s:]+:[^/@\s]+@", r"\1[REDACTED]@", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text[:limit]


def classify_failure(status: str, detail: str = "") -> str | None:
    state = str(status or "").lower()
    text = f"{state} {detail}".lower()
    if state in SUCCESS_STATES:
        return None
    checks = (
        ("timeout", ("timeout", "timed out")),
        ("stale_input", ("stale", "freshness")),
        ("delivery_failure", ("delivery", "webhook", "discord")),
        ("partial_universe", ("partial", "universe incomplete")),
        ("provider_unavailable", ("provider", "connection", "unavailable")),
        ("malformed_output", ("malformed", "jsondecode", "schema")),
        ("reconciliation_mismatch", ("reconcil", "mismatch")),
        ("policy_veto", ("veto", "policy")),
        ("silent_failure", ("silent", "no row", "no output")),
    )
    for category, terms in checks:
        if any(term in text for term in terms):
            return category
    return "process_error" if state in {"failed", "error"} else "unknown"


class RunEnvelopeStore:
    def __init__(self, root: Path = DEFAULT_ROOT, *, failure_threshold: int = FAILURE_THRESHOLD,
                 report_path: Path | None = None):
        self.root = Path(root)
        self.latest_dir = self.root / "latest"
        self.breaker_dir = self.root / "breakers"
        self.ledger_path = self.root / "run-envelope.jsonl"
        self.report_path = Path(report_path) if report_path else (
            VIBE_HOME / "reports" / "operational-run-health.json"
            if self.root == CANONICAL_ROOT else self.root / "operational-run-health.json"
        )
        self.failure_threshold = max(1, int(failure_threshold))

    def _atomic(self, path: Path, payload: Mapping[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(path.suffix + ".partial")
        temporary.write_text(json.dumps(dict(payload), indent=2, sort_keys=True) + "\n", encoding="utf-8")
        temporary.replace(path)

    def _append(self, payload: Mapping[str, Any]) -> None:
        self.ledger_path.parent.mkdir(parents=True, exist_ok=True)
        with self.ledger_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(dict(payload), sort_keys=True) + "\n")

    def _read(self, path: Path) -> dict[str, Any]:
        try:
            value = json.loads(path.read_text(encoding="utf-8-sig"))
        except (OSError, json.JSONDecodeError):
            return {}
        return value if isinstance(value, dict) else {}

    def latest_path(self, component: str) -> Path:
        return self.latest_dir / f"{safe_component(component)}.json"

    def breaker_path(self, component: str) -> Path:
        return self.breaker_dir / f"{safe_component(component)}.json"

    def breaker(self, component: str) -> dict[str, Any]:
        path = self.breaker_path(component)
        value = self._read(path)
        if value:
            return value
        if path.exists():
            # Persisted safety state exists but cannot be trusted.  Never erase a
            # possibly-open breaker by treating corrupt evidence as a first run.
            return {
                "component": safe_component(component), "state": "OPEN",
                "consecutive_failures": self.failure_threshold, "opened_at": None,
                "last_failure_class": "malformed_output",
                "requires_manual_clear": True,
                "evidence_error": "breaker_state_unreadable",
            }
        return {
            "component": safe_component(component), "state": "CLOSED",
            "consecutive_failures": 0, "opened_at": None,
        }

    def start(self, component: str, *, scheduled_for: str | None = None,
              attempt: int = 1, input_count: int = 0,
              freshness_sla_seconds: int = DEFAULT_FRESHNESS_SLA_SECONDS) -> dict[str, Any]:
        name = safe_component(component)
        now = utc_now()
        prior = self._read(self.latest_path(name))
        row = {
            "schema_version": SCHEMA_VERSION,
            "run_id": f"{name}-{now.strftime('%Y%m%dT%H%M%S%fZ')}-{uuid.uuid4().hex[:8]}",
            "component": name,
            "scheduled_for": scheduled_for,
            "started_at": utc_z(now),
            "finished_at": None,
            "status": "running",
            "exit_code": None,
            "attempt": max(1, int(attempt)),
            "duration_ms": None,
            "last_success_at": prior.get("last_success_at"),
            "data_as_of": None,
            "freshness_seconds": None,
            "freshness_sla_seconds": max(1, int(freshness_sla_seconds)),
            "input_count": max(0, int(input_count)),
            "output_count": 0,
            "alerts_attempted": 0,
            "alerts_delivered": 0,
            "failure_class": None,
            "retryable": None,
            "next_action": "complete_or_fail_run",
            "error": "",
            "breaker_state": self.breaker(name).get("state", "UNKNOWN"),
            "execution_enabled": False,
            "can_submit_orders": False,
        }
        self._atomic(self.latest_path(name), row)
        self._append({**row, "event": "started"})
        self.refresh_report()
        return row

    def finish(self, component: str, *, run_id: str | None = None, status: str,
               exit_code: int = 0, data_as_of: str | None = None,
               input_count: int | None = None, output_count: int = 0,
               alerts_attempted: int = 0, alerts_delivered: int = 0,
               failure_class: str | None = None, retryable: bool | None = None,
               next_action: str = "none", error: str = "") -> dict[str, Any]:
        name = safe_component(component)
        row = self._read(self.latest_path(name))
        if not row or (run_id and row.get("run_id") != run_id):
            raise ValueError("run_id_not_current")
        normalized = str(status or "unknown").lower()
        attempted = max(0, int(alerts_attempted))
        delivered = max(0, int(alerts_delivered))
        if int(exit_code) != 0 and normalized in SUCCESS_STATES:
            normalized = "failed"
        if delivered > attempted:
            normalized, error = "malformed_output", "alerts_delivered_exceeds_attempted"
        elif attempted > delivered and normalized in SUCCESS_STATES:
            normalized = "delivery_failure"
        if normalized not in SUCCESS_STATES | FAILURE_STATES:
            normalized = "error"
        now = utc_now()
        observed = parse_time(data_as_of)
        try:
            freshness_sla = max(1, int(row.get("freshness_sla_seconds") or DEFAULT_FRESHNESS_SLA_SECONDS))
        except (TypeError, ValueError):
            freshness_sla = DEFAULT_FRESHNESS_SLA_SECONDS
        if normalized in SUCCESS_STATES and observed is None:
            normalized, error = "malformed_output", "data_as_of_missing_or_invalid"
        elif normalized in SUCCESS_STATES and observed and (observed - now).total_seconds() > 5:
            normalized, error = "malformed_output", "data_as_of_is_in_the_future"
        elif normalized in SUCCESS_STATES and observed and (now - observed).total_seconds() > freshness_sla:
            normalized, error = "stale", "data_as_of_exceeds_freshness_sla"
        category = failure_class or classify_failure(normalized, error)
        if category and category not in FAILURE_CLASSES:
            category = "unknown"
        if normalized in SUCCESS_STATES and category is not None:
            # A caller cannot attach failure evidence to a nominal success and
            # still receive a green run.  The contradictory envelope is itself
            # malformed and requires review.
            normalized = "malformed_output"
        started = parse_time(row.get("started_at")) or now
        freshness = max(0.0, (now - observed).total_seconds()) if observed else None
        successful = normalized in SUCCESS_STATES and int(exit_code) == 0 and category is None
        breaker = self._update_breaker(name, successful=successful, failure_class=category, now=now)
        row.update({
            "finished_at": utc_z(now),
            "status": "success" if successful else normalized,
            "exit_code": int(exit_code),
            "duration_ms": max(0, int((now - started).total_seconds() * 1000)),
            "last_success_at": utc_z(now) if successful else row.get("last_success_at"),
            "data_as_of": utc_z(observed) if observed else data_as_of,
            "freshness_seconds": round(freshness, 3) if freshness is not None else None,
            "input_count": max(0, int(input_count)) if input_count is not None else row.get("input_count", 0),
            "output_count": max(0, int(output_count)),
            "alerts_attempted": attempted,
            "alerts_delivered": delivered,
            "failure_class": category,
            "retryable": None if successful else bool(retryable),
            "next_action": "none" if successful else redact_error(next_action, 160) or "investigate",
            "error": "" if successful else redact_error(error),
            "breaker_state": breaker["state"],
            "execution_enabled": False,
            "can_submit_orders": False,
        })
        self._atomic(self.latest_path(name), row)
        self._append({**row, "event": "finished"})
        self.refresh_report()
        return row

    def _update_breaker(self, component: str, *, successful: bool,
                        failure_class: str | None, now: datetime) -> dict[str, Any]:
        prior = self.breaker(component)
        was_open = str(prior.get("state") or "").upper() == "OPEN"
        count = int(prior.get("consecutive_failures") or 0)
        if successful and not was_open:
            count = 0
        elif not successful:
            count += 1
        opened = was_open or count >= self.failure_threshold
        row = {
            "component": safe_component(component),
            "state": "OPEN" if opened else "CLOSED",
            "consecutive_failures": count,
            "opened_at": prior.get("opened_at") or (utc_z(now) if opened else None),
            "last_failure_class": failure_class if not successful else prior.get("last_failure_class"),
            "updated_at": utc_z(now),
            "requires_manual_clear": opened,
            "execution_enabled": False,
            "can_submit_orders": False,
        }
        self._atomic(self.breaker_path(component), row)
        return row

    def clear_breaker(self, component: str) -> dict[str, Any]:
        row = {
            "component": safe_component(component), "state": "CLOSED",
            "consecutive_failures": 0, "opened_at": None,
            "last_failure_class": None, "updated_at": utc_z(utc_now()),
            "requires_manual_clear": False, "execution_enabled": False,
            "can_submit_orders": False,
        }
        self._atomic(self.breaker_path(component), row)
        self.refresh_report()
        return row

    def refresh_report(self) -> dict[str, Any]:
        components: list[dict[str, Any]] = []
        if self.latest_dir.exists():
            for path in sorted(self.latest_dir.glob("*.json")):
                row = self._read(path)
                if not row:
                    components.append({
                        "schema_version": SCHEMA_VERSION,
                        "component": path.stem,
                        "run_id": "unreadable",
                        "status": "malformed_output",
                        "failure_class": "malformed_output",
                        "error": "latest_run_envelope_unreadable",
                        "next_action": "inspect_or_restore_run_envelope",
                        "breaker_state": "OPEN",
                        "breaker": {
                            "component": path.stem,
                            "state": "OPEN",
                            "requires_manual_clear": True,
                            "evidence_error": "latest_run_envelope_unreadable",
                        },
                        "execution_enabled": False,
                        "can_submit_orders": False,
                    })
                    continue
                breaker = self.breaker(str(row.get("component") or path.stem))
                row["breaker"] = breaker
                row["breaker_state"] = breaker.get("state", "UNKNOWN")
                components.append(row)
        now = utc_now()

        def trustworthy_success(row: Mapping[str, Any]) -> bool:
            finished = parse_time(row.get("finished_at"))
            observed = parse_time(row.get("data_as_of"))
            try:
                exit_ok = int(row.get("exit_code")) == 0
                sla = max(1, int(row.get("freshness_sla_seconds") or DEFAULT_FRESHNESS_SLA_SECONDS))
            except (TypeError, ValueError):
                return False
            current_age = (now - observed).total_seconds() if observed else None
            return (
                row.get("schema_version") == SCHEMA_VERSION
                and str(row.get("status") or "").lower() in SUCCESS_STATES
                and str(row.get("breaker_state") or "").upper() == "CLOSED"
                and not row.get("failure_class")
                and finished is not None
                and observed is not None
                and exit_ok
                and current_age is not None
                and -5 <= current_age <= sla
            )

        healthy = bool(components) and all(trustworthy_success(row) for row in components)
        report = {
            "schema_version": SCHEMA_VERSION,
            "generated_at": utc_z(utc_now()),
            "status": "healthy" if healthy else "attention",
            "summary": {
                "status": "healthy" if healthy else "attention",
                "components": len(components),
                "successful": sum(trustworthy_success(row) for row in components),
                "open_breakers": sum(str(row.get("breaker_state") or "").upper() == "OPEN" for row in components),
            },
            "components": components,
            "execution_enabled": False,
            "can_submit_orders": False,
        }
        self._atomic(self.report_path, report)
        return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    start = sub.add_parser("start")
    start.add_argument("--component", required=True)
    start.add_argument("--scheduled-for")
    start.add_argument("--attempt", type=int, default=1)
    start.add_argument("--input-count", type=int, default=0)
    start.add_argument("--freshness-sla-seconds", type=int, default=DEFAULT_FRESHNESS_SLA_SECONDS)
    finish = sub.add_parser("finish")
    finish.add_argument("--component", required=True)
    finish.add_argument("--run-id")
    finish.add_argument("--status", required=True)
    finish.add_argument("--exit-code", type=int, default=0)
    finish.add_argument("--data-as-of")
    finish.add_argument("--input-count", type=int)
    finish.add_argument("--output-count", type=int, default=0)
    finish.add_argument("--alerts-attempted", type=int, default=0)
    finish.add_argument("--alerts-delivered", type=int, default=0)
    finish.add_argument("--failure-class")
    finish.add_argument("--retryable", action="store_true")
    finish.add_argument("--next-action", default="investigate")
    finish.add_argument("--error", default="")
    clear = sub.add_parser("clear-breaker")
    clear.add_argument("--component", required=True)
    sub.add_parser("show")
    args = parser.parse_args()
    store = RunEnvelopeStore()
    if args.command == "start":
        result = store.start(
            args.component, scheduled_for=args.scheduled_for, attempt=args.attempt,
            input_count=args.input_count, freshness_sla_seconds=args.freshness_sla_seconds,
        )
    elif args.command == "finish":
        result = store.finish(
            args.component, run_id=args.run_id, status=args.status, exit_code=args.exit_code,
            data_as_of=args.data_as_of, input_count=args.input_count, output_count=args.output_count,
            alerts_attempted=args.alerts_attempted, alerts_delivered=args.alerts_delivered,
            failure_class=args.failure_class, retryable=args.retryable,
            next_action=args.next_action, error=args.error,
        )
    elif args.command == "clear-breaker":
        result = store.clear_breaker(args.component)
    else:
        result = store.refresh_report()
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

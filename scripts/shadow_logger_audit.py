#!/usr/bin/env python3
"""Audit every shadow JSON stream for freshness and resolved evidence."""
from __future__ import annotations

import argparse
import json
from collections import Counter
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Sequence

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
DEFAULT_REPORT_PATH = Path.home() / ".vibe-trading" / "reports" / "shadow-logger-audit.json"

DERIVED_TOKENS = ("report", "evaluation", "time_bucket", "consensus", "audit")
SLOW_TOKENS = ("monthly", "momentum", "qqq_gld", "swing_cash")
TIMESTAMP_FIELDS = (
    "timestamp", "generated_at", "generated_on", "captured_at", "observed_at", "resolved_at",
    "exit_at", "entry_at", "date", "exit_date", "entry_date", "as_of_date", "signal_asof",
)
RESOLVED_STATUSES = {"closed", "resolved", "settled", "winner", "loser", "win", "loss", "target", "stop"}
OPEN_STATUSES = {"open", "active", "pending", "entered", "unresolved"}


def _load_rows(path: Path) -> tuple[list[dict[str, Any]], int]:
    malformed = 0
    if path.suffix == ".jsonl":
        rows: list[dict[str, Any]] = []
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
            if not line.strip():
                continue
            try:
                value = json.loads(line)
            except json.JSONDecodeError:
                malformed += 1
                continue
            if isinstance(value, dict):
                rows.append(value)
        return rows, malformed
    try:
        value = json.loads(path.read_text(encoding="utf-8", errors="replace"))
    except json.JSONDecodeError:
        return [], 1
    if isinstance(value, list):
        return [row for row in value if isinstance(row, dict)], 0
    return ([value] if isinstance(value, dict) else []), 0


def _parse_timestamp(value: Any) -> datetime | None:
    if value in (None, ""):
        return None
    text = str(value).strip()
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        try:
            parsed = datetime.combine(date.fromisoformat(text[:10]), datetime.min.time())
        except ValueError:
            return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _row_timestamp(row: dict[str, Any]) -> datetime | None:
    values = [_parse_timestamp(row.get(field)) for field in TIMESTAMP_FIELDS]
    parsed = [value for value in values if value is not None]
    return max(parsed) if parsed else None


def _is_signal(row: dict[str, Any]) -> bool:
    record_type = str(row.get("record_type", row.get("type", ""))).lower()
    status = str(row.get("status", "")).lower()
    return record_type in {"signal", "candidate", "entry"} or status == "signal" or bool(row.get("shadow_signal"))


def _is_resolved(row: dict[str, Any]) -> bool:
    record_type = str(row.get("record_type", row.get("type", ""))).lower()
    status = str(row.get("status", "")).lower()
    outcome = row.get("outcome")
    return (
        record_type == "outcome"
        or status in RESOLVED_STATUSES
        or row.get("exit_at") is not None
        or outcome not in (None, "", "pending", "pending_external_evaluation")
    )


def _is_open(row: dict[str, Any]) -> bool:
    return str(row.get("status", "")).lower() in OPEN_STATUSES and not _is_resolved(row)


def _business_days_ago(latest: datetime | None, now: datetime) -> int | None:
    if latest is None:
        return None
    start = latest.date()
    end = now.date()
    if start >= end:
        return 0
    return sum(1 for offset in range(1, (end - start).days + 1) if (start.fromordinal(start.toordinal() + offset)).weekday() < 5)


def _role(path: Path) -> str:
    stem = path.stem.lower()
    if any(token in stem for token in DERIVED_TOKENS):
        return "derived_report_stream"
    if "candidate" in stem:
        return "candidate_stream"
    return "primary_shadow_logger"


def audit_path(path: Path, now: datetime) -> dict[str, Any]:
    rows, malformed = _load_rows(path)
    timestamps = [timestamp for row in rows if (timestamp := _row_timestamp(row)) is not None]
    latest = max(timestamps) if timestamps else None
    dates = {timestamp.date().isoformat() for timestamp in timestamps}
    role = _role(path)
    signal_count = sum(_is_signal(row) for row in rows)
    resolved_count = sum(_is_resolved(row) for row in rows)
    open_count = sum(_is_open(row) for row in rows)
    age = _business_days_ago(latest, now)
    stale_limit = 40 if any(token in path.stem.lower() for token in SLOW_TOKENS) else 2
    freshness = "unknown" if age is None else "stale" if age > stale_limit else "current"

    if malformed and not rows:
        evidence_status = "malformed"
    elif not rows:
        evidence_status = "empty"
    elif role == "derived_report_stream":
        evidence_status = "derived_not_independent_evidence"
    elif resolved_count >= 30 and len(dates) >= 20:
        evidence_status = "sample_size_review_ready"
    elif resolved_count:
        evidence_status = "collecting_resolved_outcomes"
    else:
        evidence_status = "context_only_no_resolved_outcomes"

    issues: list[str] = []
    if freshness == "stale":
        issues.append("stale_log")
    if evidence_status == "empty":
        issues.append("empty_log")
    if evidence_status == "malformed":
        issues.append("malformed_log")
    if role == "primary_shadow_logger" and evidence_status == "context_only_no_resolved_outcomes":
        issues.append("forward_outcome_contract_missing_or_external")

    return {
        "path": str(path),
        "name": path.name,
        "role": role,
        "record_count": len(rows),
        "malformed_record_count": malformed,
        "signal_count": signal_count,
        "resolved_count": resolved_count,
        "open_count": open_count,
        "distinct_observation_dates": len(dates),
        "latest_observation_at": latest.isoformat().replace("+00:00", "Z") if latest else None,
        "business_days_since_latest": age,
        "freshness": freshness,
        "evidence_status": evidence_status,
        "issues": issues,
    }


def discover_logs(data_dir: Path) -> list[Path]:
    return sorted(
        path for path in data_dir.glob("*shadow*.json*")
        if path.is_file() and path.suffix in {".json", ".jsonl"}
    )


def build_report(data_dir: Path = DATA, now: datetime | None = None) -> dict[str, Any]:
    observed_at = now or datetime.now(timezone.utc)
    rows = [audit_path(path, observed_at) for path in discover_logs(data_dir)]
    evidence_counts = Counter(row["evidence_status"] for row in rows)
    role_counts = Counter(row["role"] for row in rows)
    return {
        "provider": "shadow_logger_audit",
        "generated_at": observed_at.isoformat().replace("+00:00", "Z"),
        "mode": "read_only_evidence_governance",
        "execution_enabled": False,
        "can_submit_orders": False,
        "automatic_parameter_changes": False,
        "summary": {
            "log_count": len(rows),
            "role_counts": dict(sorted(role_counts.items())),
            "evidence_status_counts": dict(sorted(evidence_counts.items())),
            "stale_count": sum(row["freshness"] == "stale" for row in rows),
            "issue_count": sum(bool(row["issues"]) for row in rows),
            "sample_size_review_ready_count": evidence_counts["sample_size_review_ready"],
        },
        "rows": rows,
        "interpretation": "Fresh logs are not evidence of edge. Promotion still requires executable, cost-adjusted, forward outcomes on independent dates.",
    }


def _write(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path, default=DATA)
    parser.add_argument("--report-path", type=Path, default=DEFAULT_REPORT_PATH)
    parser.add_argument("--print", action="store_true", dest="do_print")
    args = parser.parse_args(argv)
    report = build_report(args.data_dir)
    _write(args.report_path, report)
    if args.do_print:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        summary = report["summary"]
        print(f"Shadow logger audit: logs={summary['log_count']} stale={summary['stale_count']} issues={summary['issue_count']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

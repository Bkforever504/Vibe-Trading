#!/usr/bin/env python3
"""Append-only journal for option-bot evaluations, including no-trade runs.

This module has no broker or order imports. It records why a strategy did or
did not produce a concrete shadow setup so evidence throughput can be audited
without weakening production gates.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_LOG_PATH = ROOT / "data" / "options_observation_log.jsonl"
DEFAULT_REPORT_PATH = ROOT / "data" / "options_observation_report.json"
DEFAULT_DECISION_PATHS = (
    ROOT / "data" / "spy_0dte_pm_decision.json",
    ROOT / "data" / "spy_iron_condor_decision.json",
    ROOT / "data" / "theta_harvester_entry_decision.json",
    ROOT / "data" / "theta_harvester_monitor_decision.json",
)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _date_part(value: Any) -> str | None:
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).date().isoformat()
    except (TypeError, ValueError):
        return None


def _setup_summary(setup: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(setup, dict):
        return {}
    symbols = [
        str(setup.get(key) or "")
        for key in (
            "short_symbol", "long_symbol", "short_put_symbol",
            "long_put_symbol", "short_call_symbol", "long_call_symbol",
        )
        if setup.get(key)
    ]
    return {
        "shadow_id": setup.get("shadow_id"),
        "symbol": setup.get("symbol"),
        "expiry": setup.get("expiry", setup.get("leg_expiry")),
        "dte": setup.get("dte"),
        "concrete_contracts": symbols,
        "entry_credit": setup.get(
            "entry_credit", setup.get("total_credit", setup.get("leg_entry_credit"))
        ),
        "midpoint_credit": setup.get("midpoint_credit"),
        "max_loss": setup.get("max_loss", setup.get("max_loss_total")),
        "quote_scope": setup.get("quote_scope", "public_snapshot_not_opra_nbbo"),
        "gate_states": setup.get("gates_passed", setup.get("gate_states", {})),
    }


def build_observation(
    decision: dict[str, Any],
    *,
    provider: str | None = None,
    setup: dict[str, Any] | None = None,
    source: str = "strategy_run",
) -> dict[str, Any]:
    generated_at = str(decision.get("generated_at") or _utc_now())
    provider_name = str(provider or decision.get("provider") or "unknown")
    status = str(decision.get("status") or "unknown")
    reason = str(decision.get("reason") or "unknown")
    details = decision.get("details") if isinstance(decision.get("details"), dict) else {}
    embedded = details.get("setup") if isinstance(details.get("setup"), dict) else None
    summary = _setup_summary(setup or embedded)
    identity = "|".join((provider_name, generated_at, status, reason, source))
    return {
        "schema_version": 1,
        "observation_id": hashlib.sha256(identity.encode("utf-8")).hexdigest()[:24],
        "observed_at": _utc_now(),
        "decision_at": generated_at,
        "decision_date": _date_part(generated_at),
        "provider": provider_name,
        "source": source,
        "status": status,
        "reason": reason,
        "details": details,
        "setup_available": bool(summary),
        "executable_candidate_available": bool(summary.get("concrete_contracts")),
        "setup": summary,
        "execution_enabled": False,
        "can_submit_orders": False,
        "orders_submitted": 0,
    }


def read_observations(path: Path = DEFAULT_LOG_PATH) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(row, dict):
                rows.append(row)
    return rows


def append_observation(
    decision: dict[str, Any],
    *,
    provider: str | None = None,
    setup: dict[str, Any] | None = None,
    source: str = "strategy_run",
    path: Path = DEFAULT_LOG_PATH,
) -> dict[str, Any]:
    row = build_observation(decision, provider=provider, setup=setup, source=source)
    if os.getenv("PYTEST_CURRENT_TEST") and path == DEFAULT_LOG_PATH:
        return row
    existing_ids = {item.get("observation_id") for item in read_observations(path)}
    if row["observation_id"] in existing_ids:
        return row
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(row, sort_keys=True, separators=(",", ":")) + "\n")
    return row


def ingest_decision_file(path: Path, *, log_path: Path = DEFAULT_LOG_PATH) -> dict[str, Any] | None:
    try:
        decision = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, OSError, json.JSONDecodeError):
        return None
    if not isinstance(decision, dict):
        return None
    return append_observation(decision, source=f"decision_file:{path.name}", path=log_path)


def build_report(rows: Iterable[dict[str, Any]]) -> dict[str, Any]:
    records = list(rows)
    by_provider = Counter(str(row.get("provider") or "unknown") for row in records)
    by_status = Counter(str(row.get("status") or "unknown") for row in records)
    by_reason = Counter(str(row.get("reason") or "unknown") for row in records)
    dates = sorted({str(row.get("decision_date")) for row in records if row.get("decision_date")})
    schedule_reasons = {
        reason: count for reason, count in by_reason.items()
        if "window" in reason or "day_not" in reason
    }
    data_reasons = {
        reason: count for reason, count in by_reason.items()
        if any(token in reason for token in ("unavailable", "failed", "stale", "invalid", "unreadable", "not_priceable"))
    }
    return {
        "schema_version": 1,
        "provider": "options_observation_journal",
        "generated_at": _utc_now(),
        "mode": "read_only_no_trade_evidence",
        "observation_count": len(records),
        "distinct_date_count": len(dates),
        "dates": dates,
        "setup_available_count": sum(bool(row.get("setup_available")) for row in records),
        "executable_candidate_count": sum(bool(row.get("executable_candidate_available")) for row in records),
        "by_provider": dict(sorted(by_provider.items())),
        "by_status": dict(sorted(by_status.items())),
        "by_reason": dict(by_reason.most_common()),
        "schedule_blockers": schedule_reasons,
        "data_blockers": data_reasons,
        "latest_observations": records[-20:],
        "execution_enabled": False,
        "can_submit_orders": False,
    }


def write_report(
    *,
    log_path: Path = DEFAULT_LOG_PATH,
    out_path: Path = DEFAULT_REPORT_PATH,
) -> dict[str, Any]:
    report = build_report(read_observations(log_path))
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--log", type=Path, default=DEFAULT_LOG_PATH)
    parser.add_argument("--out", type=Path, default=DEFAULT_REPORT_PATH)
    parser.add_argument("--ingest-current", action="store_true")
    parser.add_argument("--decision", action="append", type=Path, default=[])
    parser.add_argument("--print", action="store_true", dest="print_report")
    args = parser.parse_args()
    paths = list(args.decision)
    if args.ingest_current:
        paths.extend(DEFAULT_DECISION_PATHS)
    for path in paths:
        ingest_decision_file(path, log_path=args.log)
    report = write_report(log_path=args.log, out_path=args.out)
    if args.print_report:
        print(json.dumps(report, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()

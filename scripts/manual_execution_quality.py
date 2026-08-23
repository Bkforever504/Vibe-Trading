#!/usr/bin/env python3
"""Validate and summarize manual execution-quality observations.

The module is an evidence recorder only.  It has no broker integration and no
order vocabulary: callers supply fills that already occurred outside this
system.  Observations are immutable once their ``observation_id`` is appended.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Iterator, Mapping


SCHEMA_VERSION = 1
DEFAULT_FRESHNESS_SLA_MINUTES = 60
VIBE_HOME = Path.home() / ".vibe-trading"
DEFAULT_LEDGER = VIBE_HOME / "logs" / "manual-execution-quality.jsonl"
DEFAULT_REPORT = VIBE_HOME / "reports" / "manual-execution-quality.json"

FORBIDDEN_ORDER_FIELDS = {
    "action",
    "broker_order",
    "broker_order_id",
    "broker_order_request",
    "cancel_order",
    "client_order_id",
    "limit_price",
    "order",
    "order_id",
    "order_type",
    "replace_order",
    "side",
    "stop_price",
    "submit_order",
    "time_in_force",
}
INPUT_FIELDS = {
    "observation_id",
    "lifecycle_id",
    "detection_id",
    "plan_id",
    "plan_hash",
    "source_label",
    "source_as_of",
    "observed_at",
    "decision_at",
    "symbol",
    "direction",
    "intended_entry_price",
    "intended_stop_price",
    "intended_quantity",
    "pnl_multiplier",
    "entry_status",
    "entry_spread_bps",
    "entry_fills",
    "exit_fills",
    "notes",
    "execution_enabled",
    "can_submit_orders",
}
FILL_FIELDS = {"filled_at", "quantity", "price", "fee", "reference_price", "spread_bps", "slippage_bps"}
DERIVED_FIELDS = {
    "schema_version",
    "actual_entry",
    "entry_slippage_bps",
    "position_status",
    "filled_quantity",
    "exited_quantity",
    "open_quantity",
    "total_fees",
    "realized_gross_pnl",
    "realized_net_pnl",
    "realized_net_r",
    "risk_per_unit",
    "record_type",
}


def _utc(value: Any, field: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError) as exc:
        raise ValueError(f"invalid_{field}") from exc
    if parsed.tzinfo is None:
        raise ValueError(f"invalid_{field}:timezone_required")
    return parsed.astimezone(timezone.utc)


def _iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _number(value: Any, field: str, *, minimum: float | None = None, strictly_positive: bool = False) -> float:
    if isinstance(value, bool):
        raise ValueError(f"invalid_{field}")
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"invalid_{field}") from exc
    if not math.isfinite(number):
        raise ValueError(f"invalid_{field}")
    if strictly_positive and number <= 0:
        raise ValueError(f"invalid_{field}")
    if minimum is not None and number < minimum:
        raise ValueError(f"invalid_{field}")
    return number


def _identifier(payload: Mapping[str, Any], field: str) -> str:
    value = str(payload.get(field) or "").strip()
    if not value:
        raise ValueError(f"missing_{field}")
    if len(value) > 256 or any(character in value for character in "\r\n\0"):
        raise ValueError(f"invalid_{field}")
    return value


def _find_forbidden(value: Any) -> str | None:
    if isinstance(value, Mapping):
        for key, nested in value.items():
            normalized = str(key).strip().lower()
            if normalized in FORBIDDEN_ORDER_FIELDS:
                return normalized
            found = _find_forbidden(nested)
            if found:
                return found
    elif isinstance(value, (list, tuple)):
        for nested in value:
            found = _find_forbidden(nested)
            if found:
                return found
    return None


def _normalize_fill(raw: Mapping[str, Any], *, kind: str, direction: str) -> dict[str, Any]:
    forbidden = _find_forbidden(raw)
    if forbidden:
        raise ValueError(f"forbidden_order_field:{forbidden}")
    unexpected = sorted(set(raw) - FILL_FIELDS)
    if unexpected:
        raise ValueError(f"unexpected_{kind}_fill_field:{unexpected[0]}")
    timestamp = _utc(raw.get("filled_at"), f"{kind}_fill_timestamp")
    quantity = _number(raw.get("quantity"), f"{kind}_fill_quantity", strictly_positive=True)
    price = _number(raw.get("price"), f"{kind}_fill_price", strictly_positive=True)
    fee = _number(raw.get("fee", 0), f"{kind}_fill_fee", minimum=0)
    reference = raw.get("reference_price")
    reference_price = (
        None
        if reference is None
        else _number(reference, f"{kind}_fill_reference_price", strictly_positive=True)
    )
    spread = raw.get("spread_bps")
    spread_bps = None if spread is None else _number(spread, f"{kind}_fill_spread_bps", minimum=0)
    slippage_bps: float | None = None
    if reference_price is not None:
        if kind == "entry":
            adverse_move = price - reference_price if direction == "long" else reference_price - price
        else:
            adverse_move = reference_price - price if direction == "long" else price - reference_price
        slippage_bps = round(adverse_move / reference_price * 10_000, 6)
    return {
        "filled_at": _iso(timestamp),
        "quantity": quantity,
        "price": price,
        "fee": fee,
        "reference_price": reference_price,
        "spread_bps": spread_bps,
        "slippage_bps": slippage_bps,
    }


def _chronology(
    entry_fills: list[dict[str, Any]],
    exit_fills: list[dict[str, Any]],
    *,
    decision_at: datetime,
    observed_at: datetime,
) -> None:
    for label, fills in (("entry", entry_fills), ("exit", exit_fills)):
        timestamps = [_utc(fill["filled_at"], f"{label}_fill_timestamp") for fill in fills]
        if timestamps != sorted(timestamps):
            raise ValueError(f"non_monotonic_{label}_fills")
        if timestamps and timestamps[0] < decision_at:
            raise ValueError(f"{label}_fill_before_decision")
        if timestamps and timestamps[-1] > observed_at:
            raise ValueError("fill_after_observation")

    events: list[tuple[datetime, int, float]] = []
    events.extend((_utc(fill["filled_at"], "entry_fill_timestamp"), 0, float(fill["quantity"])) for fill in entry_fills)
    events.extend((_utc(fill["filled_at"], "exit_fill_timestamp"), 1, -float(fill["quantity"])) for fill in exit_fills)
    available = 0.0
    for _timestamp, _priority, quantity_delta in sorted(events):
        available += quantity_delta
        if available < -1e-9:
            raise ValueError("exit_before_available_entry")


def build_manual_observation(payload: Mapping[str, Any], *, expected_plan_hash: str) -> dict[str, Any]:
    """Return one canonical immutable observation or fail closed.

    ``expected_plan_hash`` must come from the scanner's immutable plan envelope,
    rather than from the manual form being validated.
    """
    forbidden = _find_forbidden(payload)
    if forbidden:
        raise ValueError(f"forbidden_order_field:{forbidden}")
    unexpected = sorted(set(payload) - INPUT_FIELDS)
    if unexpected:
        raise ValueError(f"unexpected_observation_field:{unexpected[0]}")
    if payload.get("execution_enabled") not in (None, False):
        raise ValueError("execution_enabled_must_be_false")
    if payload.get("can_submit_orders") not in (None, False):
        raise ValueError("can_submit_orders_must_be_false")

    observation_id = _identifier(payload, "observation_id")
    lifecycle_id = _identifier(payload, "lifecycle_id")
    detection_id = _identifier(payload, "detection_id")
    plan_id = _identifier(payload, "plan_id")
    plan_hash = _identifier(payload, "plan_hash")
    if not str(expected_plan_hash or "").strip() or plan_hash != str(expected_plan_hash):
        raise ValueError("plan_hash_mismatch")
    source_label = _identifier(payload, "source_label")
    symbol = _identifier(payload, "symbol").upper()
    direction = str(payload.get("direction") or "").lower()
    if direction not in {"long", "short"}:
        raise ValueError("invalid_direction")

    decision_at = _utc(payload.get("decision_at"), "decision_at")
    source_as_of = _utc(payload.get("source_as_of"), "source_as_of")
    observed_at = _utc(payload.get("observed_at"), "observed_at")
    if observed_at < decision_at:
        raise ValueError("observation_before_decision")
    if source_as_of > observed_at:
        raise ValueError("source_after_observation")

    intended_entry = _number(payload.get("intended_entry_price"), "intended_entry_price", strictly_positive=True)
    intended_stop = _number(payload.get("intended_stop_price"), "intended_stop_price", strictly_positive=True)
    intended_quantity = _number(payload.get("intended_quantity"), "intended_quantity", strictly_positive=True)
    pnl_multiplier = _number(payload.get("pnl_multiplier", 1), "pnl_multiplier", strictly_positive=True)
    if direction == "long" and intended_stop >= intended_entry:
        raise ValueError("invalid_long_stop_geometry")
    if direction == "short" and intended_stop <= intended_entry:
        raise ValueError("invalid_short_stop_geometry")
    risk_per_unit = abs(intended_entry - intended_stop)
    spread = payload.get("entry_spread_bps")
    entry_spread_bps = None if spread is None else _number(spread, "entry_spread_bps", minimum=0)

    raw_entries = payload.get("entry_fills", [])
    raw_exits = payload.get("exit_fills", [])
    if not isinstance(raw_entries, list) or not all(isinstance(fill, Mapping) for fill in raw_entries):
        raise ValueError("invalid_entry_fills")
    if not isinstance(raw_exits, list) or not all(isinstance(fill, Mapping) for fill in raw_exits):
        raise ValueError("invalid_exit_fills")
    entry_fills = [_normalize_fill(fill, kind="entry", direction=direction) for fill in raw_entries]
    exit_fills = [_normalize_fill(fill, kind="exit", direction=direction) for fill in raw_exits]
    _chronology(entry_fills, exit_fills, decision_at=decision_at, observed_at=observed_at)

    filled_quantity = sum(float(fill["quantity"]) for fill in entry_fills)
    exited_quantity = sum(float(fill["quantity"]) for fill in exit_fills)
    if filled_quantity > intended_quantity + 1e-9:
        raise ValueError("filled_quantity_exceeds_intended")
    if exited_quantity > filled_quantity + 1e-9:
        raise ValueError("exited_quantity_exceeds_filled")
    computed_entry_status = (
        "unfilled" if filled_quantity <= 1e-9
        else "filled" if math.isclose(filled_quantity, intended_quantity, rel_tol=0, abs_tol=1e-9)
        else "partial"
    )
    if str(payload.get("entry_status") or "").lower() != computed_entry_status:
        raise ValueError("entry_status_mismatch")

    average_entry = (
        sum(float(fill["quantity"]) * float(fill["price"]) for fill in entry_fills) / filled_quantity
        if filled_quantity else None
    )
    if average_entry is None:
        entry_slippage_bps = None
    else:
        adverse_move = average_entry - intended_entry if direction == "long" else intended_entry - average_entry
        entry_slippage_bps = round(adverse_move / intended_entry * 10_000, 6)
    open_quantity = max(0.0, filled_quantity - exited_quantity)
    position_status = (
        "unfilled" if computed_entry_status == "unfilled"
        else "closed" if math.isclose(open_quantity, 0.0, rel_tol=0, abs_tol=1e-9)
        else "partial_exit" if exited_quantity > 0
        else "open"
    )

    entry_fees = sum(float(fill["fee"]) for fill in entry_fills)
    exit_fees = sum(float(fill["fee"]) for fill in exit_fills)
    total_fees = entry_fees + exit_fees
    realized_gross_pnl: float | None = None
    realized_net_pnl: float | None = None
    realized_net_r: float | None = None
    if exited_quantity > 0 and average_entry is not None:
        multiplier = 1.0 if direction == "long" else -1.0
        realized_gross_pnl = sum(
            float(fill["quantity"]) * (float(fill["price"]) - average_entry) * multiplier
            for fill in exit_fills
        ) * pnl_multiplier
        allocated_entry_fees = entry_fees * exited_quantity / filled_quantity
        realized_net_pnl = realized_gross_pnl - allocated_entry_fees - exit_fees
        realized_net_r = realized_net_pnl / (risk_per_unit * exited_quantity * pnl_multiplier)

    return {
        "schema_version": SCHEMA_VERSION,
        "record_type": "manual_execution_quality_observation",
        "observation_id": observation_id,
        "lifecycle_id": lifecycle_id,
        "detection_id": detection_id,
        "plan_id": plan_id,
        "plan_hash": plan_hash,
        "source_label": source_label,
        "source_as_of": _iso(source_as_of),
        "observed_at": _iso(observed_at),
        "decision_at": _iso(decision_at),
        "symbol": symbol,
        "direction": direction,
        "intended_entry_price": intended_entry,
        "intended_stop_price": intended_stop,
        "intended_quantity": intended_quantity,
        "pnl_multiplier": pnl_multiplier,
        "entry_status": computed_entry_status,
        "entry_spread_bps": entry_spread_bps,
        "entry_fills": entry_fills,
        "exit_fills": exit_fills,
        "actual_entry": {
            "status": computed_entry_status,
            "filled_quantity": filled_quantity,
            "average_price": None if average_entry is None else round(average_entry, 8),
            "first_fill_at": entry_fills[0]["filled_at"] if entry_fills else None,
            "last_fill_at": entry_fills[-1]["filled_at"] if entry_fills else None,
        },
        "entry_slippage_bps": entry_slippage_bps,
        "position_status": position_status,
        "filled_quantity": filled_quantity,
        "exited_quantity": exited_quantity,
        "open_quantity": open_quantity,
        "total_fees": round(total_fees, 8),
        "realized_gross_pnl": None if realized_gross_pnl is None else round(realized_gross_pnl, 8),
        "realized_net_pnl": None if realized_net_pnl is None else round(realized_net_pnl, 8),
        "realized_net_r": None if realized_net_r is None else round(realized_net_r, 8),
        "risk_per_unit": round(risk_per_unit, 8),
        "notes": str(payload.get("notes") or "").strip() or None,
        "execution_enabled": False,
        "can_submit_orders": False,
    }


def _payload_from_row(row: Mapping[str, Any]) -> dict[str, Any]:
    return {field: row.get(field) for field in INPUT_FIELDS if field in row}


def validate_manual_observation(row: Mapping[str, Any], *, expected_plan_hash: str) -> dict[str, Any]:
    if row.get("execution_enabled") is not False:
        raise ValueError("execution_enabled_must_be_false")
    if row.get("can_submit_orders") is not False:
        raise ValueError("can_submit_orders_must_be_false")
    if row.get("schema_version") != SCHEMA_VERSION:
        raise ValueError("invalid_schema_version")
    unexpected = sorted(set(row) - INPUT_FIELDS - DERIVED_FIELDS)
    if unexpected:
        raise ValueError(f"unexpected_observation_field:{unexpected[0]}")
    canonical = build_manual_observation(_payload_from_row(row), expected_plan_hash=expected_plan_hash)
    if dict(row) != canonical:
        raise ValueError("derived_metrics_mismatch")
    return canonical


def read_observations(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    for line_number, raw in enumerate(path.read_text(encoding="utf-8-sig").splitlines(), 1):
        if not raw.strip():
            continue
        try:
            row = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ValueError(f"invalid_jsonl:{path}:{line_number}:{exc.msg}") from exc
        if not isinstance(row, dict):
            raise ValueError(f"jsonl_row_must_be_object:{path}:{line_number}")
        rows.append(row)
    return rows


@contextmanager
def _ledger_lock(path: Path, *, timeout_seconds: float = 5.0) -> Iterator[None]:
    path.parent.mkdir(parents=True, exist_ok=True)
    lock_path = path.with_suffix(path.suffix + ".lock")
    deadline = time.monotonic() + timeout_seconds
    while True:
        try:
            descriptor = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            os.close(descriptor)
            break
        except FileExistsError:
            if time.monotonic() >= deadline:
                raise TimeoutError(f"ledger_lock_timeout:{lock_path}")
            time.sleep(0.05)
    try:
        yield
    finally:
        try:
            lock_path.unlink()
        except FileNotFoundError:
            pass


def append_manual_observation(
    row: Mapping[str, Any],
    *,
    path: Path,
    expected_plan_hash: str,
) -> dict[str, Any]:
    """Append a validated row once; the same ID can never be rewritten."""
    canonical = validate_manual_observation(row, expected_plan_hash=expected_plan_hash)
    observation_id = canonical["observation_id"]
    with _ledger_lock(path):
        existing = next(
            (item for item in read_observations(path) if item.get("observation_id") == observation_id),
            None,
        )
        if existing is not None:
            if existing != canonical:
                raise ValueError(f"immutable_observation_conflict:{observation_id}")
            return {"recorded": False, "duplicate": True, "observation_id": observation_id}
        with path.open("a", encoding="utf-8", newline="\n") as handle:
            handle.write(json.dumps(canonical, separators=(",", ":"), sort_keys=True) + "\n")
    return {"recorded": True, "duplicate": False, "observation_id": observation_id}


def generate_execution_quality_report(
    rows: Iterable[Mapping[str, Any]],
    *,
    now: datetime | None = None,
    freshness_sla_minutes: int = DEFAULT_FRESHNESS_SLA_MINUTES,
) -> dict[str, Any]:
    if freshness_sla_minutes <= 0:
        raise ValueError("invalid_freshness_sla_minutes")
    now = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    observations: dict[str, dict[str, Any]] = {}
    for raw in rows:
        plan_hash = str(raw.get("plan_hash") or "")
        canonical = validate_manual_observation(raw, expected_plan_hash=plan_hash)
        observation_id = canonical["observation_id"]
        if observation_id in observations and observations[observation_id] != canonical:
            raise ValueError(f"immutable_observation_conflict:{observation_id}")
        observations[observation_id] = canonical

    details: list[dict[str, Any]] = []
    for row in sorted(observations.values(), key=lambda item: (item["observed_at"], item["observation_id"])):
        age_minutes = (now - _utc(row["source_as_of"], "source_as_of")).total_seconds() / 60
        freshness = "clock_skew" if age_minutes < -1 else "fresh" if age_minutes <= freshness_sla_minutes else "stale"
        missing_followup = row["position_status"] in {"open", "partial_exit"}
        details.append({
            "observation_id": row["observation_id"],
            "lifecycle_id": row["lifecycle_id"],
            "detection_id": row["detection_id"],
            "plan_id": row["plan_id"],
            "plan_hash": row["plan_hash"],
            "symbol": row["symbol"],
            "entry_status": row["entry_status"],
            "position_status": row["position_status"],
            "realized_net_pnl": row["realized_net_pnl"],
            "realized_net_r": row["realized_net_r"],
            "entry_slippage_bps": row["entry_slippage_bps"],
            "entry_spread_bps": row["entry_spread_bps"],
            "source_label": row["source_label"],
            "source_as_of": row["source_as_of"],
            "source_age_minutes": round(age_minutes, 3),
            "freshness": freshness,
            "missing_followup": missing_followup,
            "followup_reason": "open_manual_position_needs_exit_observation" if missing_followup else None,
            "execution_enabled": False,
            "can_submit_orders": False,
        })

    values = list(observations.values())
    summary = {
        "observation_count": len(values),
        "filled_count": sum(row["entry_status"] == "filled" for row in values),
        "partial_count": sum(row["entry_status"] == "partial" for row in values),
        "unfilled_count": sum(row["entry_status"] == "unfilled" for row in values),
        "closed_count": sum(row["position_status"] == "closed" for row in values),
        "open_count": sum(row["position_status"] in {"open", "partial_exit"} for row in values),
        "missing_followup_count": sum(item["missing_followup"] for item in details),
    }
    status = (
        "awaiting_observations"
        if not values
        else "followup_required"
        if summary["missing_followup_count"]
        else "complete"
    )
    return {
        "schema_version": SCHEMA_VERSION,
        "provider": "manual_execution_quality",
        "mode": "read_only_manual_fill_evidence",
        "report_type": "manual_execution_quality",
        "status": status,
        "generated_at": _iso(now),
        "source": {
            "label": "append_only_manual_execution_quality_observations",
            "freshness_sla_minutes": freshness_sla_minutes,
        },
        "source_labels": sorted({row["source_label"] for row in values}),
        "summary": summary,
        "observations": details,
        "execution_enabled": False,
        "can_submit_orders": False,
    }


def write_report(path: Path, report: Mapping[str, Any]) -> None:
    if report.get("execution_enabled") is not False or report.get("can_submit_orders") is not False:
        raise ValueError("report_order_authority_must_be_false")
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(dict(report), indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ledger", type=Path, default=DEFAULT_LEDGER, help="Existing manual observation JSONL ledger")
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT, help="JSON report output")
    parser.add_argument("--now", help="ISO-8601 report cutoff (tests/replay only)")
    parser.add_argument("--freshness-sla-minutes", type=int, default=DEFAULT_FRESHNESS_SLA_MINUTES)
    args = parser.parse_args()
    now = _utc(args.now, "now") if args.now else datetime.now(timezone.utc)
    report = generate_execution_quality_report(
        read_observations(args.ledger),
        now=now,
        freshness_sla_minutes=args.freshness_sla_minutes,
    )
    write_report(args.report, report)
    print(
        "manual_execution_quality "
        f"status={report['status']} observations={report['summary']['observation_count']} "
        f"followups={report['summary']['missing_followup_count']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Audit manually recorded social setup claims against pre-existing radar data.

This is a measurement tool, not a copy-trading feature.  A social post may
show a profitable outcome without proving the entry timestamp, fill, sizing,
or repeatability.  Claims are therefore immutable observations and the audit
only asks what the scanner knew *before* the stated observation time.
"""
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable


ROOT = Path(__file__).resolve().parents[1]
VIBE_HOME = Path.home() / ".vibe-trading"
DEFAULT_CLAIMS_PATH = ROOT / "data" / "social_evidence_claims.jsonl"
DEFAULT_RADAR_LOG = ROOT / "data" / "intraday_opportunity_radar_log.jsonl"
DEFAULT_REPORT_PATH = VIBE_HOME / "reports" / "social-evidence-coverage-audit.json"
MAX_PRIOR_SNAPSHOT_AGE_MINUTES = 15.0


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    try:
        lines = path.read_text(encoding="utf-8-sig").splitlines()
    except OSError:
        return []
    rows: list[dict[str, Any]] = []
    for line in lines:
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(row, dict):
            rows.append(row)
    return rows


def _atomic_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(path)


def _dt(value: Any) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None:
        return None
    return parsed.astimezone(timezone.utc)


def _stamp(row: dict[str, Any]) -> datetime | None:
    return _dt(row.get("as_of_et") or row.get("generated_at"))


def _symbol(value: Any) -> str:
    return str(value or "").strip().upper()


def _direction(value: Any) -> str | None:
    value = str(value or "").strip().lower()
    aliases = {
        "long": "bullish", "call": "bullish", "calls": "bullish", "bull": "bullish", "up": "bullish",
        "short": "bearish", "put": "bearish", "puts": "bearish", "bear": "bearish", "down": "bearish",
    }
    return aliases.get(value, value or None)


def _claim_time(claim: dict[str, Any]) -> datetime | None:
    # claimed_entry_at is preferred. observed_at must be labelled in the
    # evidence record as a post/share time when the true entry is unknown.
    return _dt(claim.get("claimed_entry_at") or claim.get("observed_at"))


def _candidates(snapshot: dict[str, Any]) -> list[dict[str, Any]]:
    lane = snapshot.get("benchmark_lane") if isinstance(snapshot.get("benchmark_lane"), dict) else {}
    groups = (
        snapshot.get("ranked_candidates") or [],
        snapshot.get("preconfirmation_heads_up") or [],
        snapshot.get("actionable_ranked_candidates") or [],
        lane.get("ranked_candidates") or [],
        lane.get("actionable_ranked_candidates") or [],
    )
    seen: set[tuple[str, str, str]] = set()
    output: list[dict[str, Any]] = []
    for group in groups:
        for row in group:
            if not isinstance(row, dict):
                continue
            key = (_symbol(row.get("symbol")), str(row.get("direction") or ""), str(row.get("setup") or ""))
            if key not in seen:
                seen.add(key)
                output.append(row)
    return output


def _candidate_confirmed(candidate: dict[str, Any] | None) -> bool:
    stage = str((candidate or {}).get("confirmation_stage") or "").lower()
    return stage == "completed_5m_confirmed" or stage.endswith("_confirmed")


def audit_claims(claims: Iterable[dict[str, Any]], snapshots: Iterable[dict[str, Any]]) -> dict[str, Any]:
    """Link claims to the nearest *prior* radar snapshot without assuming fills."""
    snapshot_rows = sorted(
        (row for row in snapshots if _stamp(row)), key=lambda row: _stamp(row) or datetime.min.replace(tzinfo=timezone.utc)
    )
    audited: list[dict[str, Any]] = []
    for claim in claims:
        symbol = _symbol(claim.get("symbol"))
        claim_at = _claim_time(claim)
        record = {
            "claim_id": str(claim.get("claim_id") or ""),
            "symbol": symbol or None,
            "claimed_direction": _direction(claim.get("direction")),
            "claimed_entry_at": claim.get("claimed_entry_at"),
            "observed_at": claim.get("observed_at"),
            "timestamp_basis": claim.get("timestamp_basis") or "unknown",
            "source": claim.get("source") or "manual",
            "evidence_ref": claim.get("evidence_ref"),
            "fill_assumed": False,
            "outcome_verified": False,
        }
        if not symbol or not claim_at:
            audited.append({**record, "status": "unusable_claim_missing_symbol_or_timezone_aware_timestamp"})
            continue
        prior = [row for row in snapshot_rows if (_stamp(row) or claim_at) <= claim_at]
        snapshot = prior[-1] if prior else None
        snapshot_at = _stamp(snapshot or {})
        if not snapshot or not snapshot_at:
            audited.append({**record, "status": "no_prior_radar_snapshot"})
            continue
        age_minutes = round((claim_at - snapshot_at).total_seconds() / 60.0, 2)
        if age_minutes > MAX_PRIOR_SNAPSHOT_AGE_MINUTES:
            audited.append({
                **record, "status": "stale_prior_radar_snapshot", "radar_snapshot_at": snapshot_at.isoformat(),
                "snapshot_age_minutes": age_minutes, "max_snapshot_age_minutes": MAX_PRIOR_SNAPSHOT_AGE_MINUTES,
            })
            continue
        trace = next((row for row in snapshot.get("coverage_trace") or [] if _symbol(row.get("symbol")) == symbol), {})
        candidate = next((row for row in _candidates(snapshot) if _symbol(row.get("symbol")) == symbol), None)
        candidate_direction = _direction((candidate or {}).get("direction"))
        discovered = symbol in {_symbol(value) for value in snapshot.get("all_discovered_symbols") or []}
        selected = bool(trace.get("selected_for_intraday_bars")) if trace else bool(candidate)
        evaluated = bool(candidate)
        confirmed = _candidate_confirmed(candidate)
        heads_up = bool((candidate or {}).get("heads_up_only"))
        audited.append({
            **record,
            "status": "audited_nearest_prior_snapshot",
            "radar_snapshot_at": snapshot_at.isoformat(),
            "snapshot_age_minutes": age_minutes,
            "discovered": discovered,
            "selected_for_intraday_bars": selected,
            "evaluated": evaluated,
            "setup_confirmed": confirmed,
            "heads_up_visible": heads_up,
            "candidate_direction": candidate_direction,
            "direction_aligned": (
                candidate_direction == record["claimed_direction"]
                if candidate_direction and record["claimed_direction"] else None
            ),
            "candidate_grade": (candidate or {}).get("grade"),
            "candidate_state": (candidate or {}).get("state"),
            "candidate_setup": (candidate or {}).get("setup"),
            "candidate_blockers": (candidate or {}).get("blockers") or [],
            "coverage_stop_stage": trace.get("stop_stage") if trace else ("evaluated" if candidate else "not_discovered"),
        })
    statuses: dict[str, int] = {}
    for row in audited:
        statuses[row["status"]] = statuses.get(row["status"], 0) + 1
    audited_rows = [row for row in audited if row["status"] == "audited_nearest_prior_snapshot"]
    return {
        "schema_version": 1,
        "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "mode": "retrospective_measurement_only",
        "execution_enabled": False,
        "can_submit_orders": False,
        "claim_count": len(audited),
        "status_counts": statuses,
        "metrics": {
            "discovered_count": sum(bool(row.get("discovered")) for row in audited_rows),
            "evaluated_count": sum(bool(row.get("evaluated")) for row in audited_rows),
            "confirmed_count": sum(bool(row.get("setup_confirmed")) for row in audited_rows),
            "heads_up_count": sum(bool(row.get("heads_up_visible")) for row in audited_rows),
            "direction_aligned_count": sum(row.get("direction_aligned") is True for row in audited_rows),
        },
        "claims": audited,
        "warnings": [
            "A social claim is evidence to investigate, not evidence of a reproducible edge.",
            "Observed/share time is not treated as entry time unless the claim explicitly says so.",
            "No fills, profit, or tradeability are inferred by this audit.",
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--claims", type=Path, default=DEFAULT_CLAIMS_PATH)
    parser.add_argument("--radar-log", type=Path, default=DEFAULT_RADAR_LOG)
    parser.add_argument("--out", type=Path, default=DEFAULT_REPORT_PATH)
    parser.add_argument("--print", action="store_true", dest="print_report")
    args = parser.parse_args()
    report = audit_claims(_read_jsonl(args.claims), _read_jsonl(args.radar_log))
    _atomic_json(args.out, report)
    if args.print_report:
        print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

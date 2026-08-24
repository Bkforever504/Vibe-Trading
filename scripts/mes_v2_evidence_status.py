#!/usr/bin/env python3
"""Build dashboard progress for the two frozen MES v2 shadow candidates.

This is an accountability report, not a promotion decision.  Only rows already
marked promotion eligible by the fail-closed outcome resolver are counted in
the qualified denominator.
"""
from __future__ import annotations

import argparse
import json
import math
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping


ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "data"
DEFAULT_OUTCOMES = DATA_DIR / "shadow_outcomes.jsonl"
DEFAULT_CAPABILITY = DATA_DIR / "databento_mes_capability.json"
DEFAULT_OUTPUT = Path.home() / ".vibe-trading" / "reports" / "mes-v2-evidence-status.json"

CANDIDATES = {
    "mes-orb-0932-vix-v2": "mes-opening-breakout",
    "mes-reopen-drift-v2": "mes-overnight-drift",
}
REQUIRED_REGIMES = ("trend", "chop", "high_vol", "low_vol")
TARGET_OUTCOMES = 100
TARGET_DATES = 30
TARGET_REGIME_DATES = 8


def _read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8-sig").splitlines():
        try:
            value = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            rows.append(value)
    return rows


def _timestamp(row: Mapping[str, Any]) -> str:
    return str(row.get("resolved_at") or row.get("timestamp") or "")


def _preferred_rows(rows: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Keep one current version per plan, preferring qualified regrades."""
    by_plan: dict[str, dict[str, Any]] = {}
    for raw in rows:
        row = dict(raw)
        plan_id = str(row.get("plan_id") or "")
        if not plan_id:
            continue
        prior = by_plan.get(plan_id)
        if prior is None:
            by_plan[plan_id] = row
            continue
        rank = (row.get("promotion_eligible") is True, _timestamp(row))
        prior_rank = (prior.get("promotion_eligible") is True, _timestamp(prior))
        if rank >= prior_rank:
            by_plan[plan_id] = row
    return list(by_plan.values())


def _regime_values(row: Mapping[str, Any]) -> set[str]:
    values: set[str] = set()
    direct = row.get("regime")
    if isinstance(direct, str) and direct in REQUIRED_REGIMES:
        values.add(direct)
    tags = row.get("regime_tags")
    if isinstance(tags, Mapping):
        for key, value in tags.items():
            if key in REQUIRED_REGIMES and value is True:
                values.add(str(key))
            if isinstance(value, str) and value in REQUIRED_REGIMES:
                values.add(value)
    elif isinstance(tags, list):
        values.update(str(value) for value in tags if str(value) in REQUIRED_REGIMES)
    return values


def _p90(values: list[float]) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    return ordered[max(0, math.ceil(0.9 * len(ordered)) - 1)]


def build_status(
    rows: Iterable[Mapping[str, Any]],
    *,
    capability: Mapping[str, Any] | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    now = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    selected = _preferred_rows(rows)
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in selected:
        candidate_id = str(row.get("candidate_id") or row.get("strategy_id") or "")
        if candidate_id in CANDIDATES:
            grouped[candidate_id].append(row)

    live_status = str((capability or {}).get("live_status") or "not_probed")
    candidates: list[dict[str, Any]] = []
    for candidate_id, family_id in CANDIDATES.items():
        candidate_rows = grouped.get(candidate_id, [])
        qualified = [row for row in candidate_rows if row.get("promotion_eligible") is True]
        excluded = [row for row in candidate_rows if row.get("promotion_eligible") is not True]
        dates = {
            str(row.get("session_date") or "")
            for row in qualified
            if row.get("session_date")
        }
        regime_dates: dict[str, set[str]] = {name: set() for name in REQUIRED_REGIMES}
        for row in qualified:
            session_date = str(row.get("session_date") or "")
            for regime in _regime_values(row):
                if session_date:
                    regime_dates[regime].add(session_date)
        latency_fractions = [
            float(row["alert_latency_fraction"])
            for row in qualified
            if isinstance(row.get("alert_latency_fraction"), (int, float))
            and not isinstance(row.get("alert_latency_fraction"), bool)
        ]
        blockers: list[str] = []
        if live_status != "available":
            blockers.append("databento_live_license_unavailable_historical_regrade_only")
        if not qualified:
            blockers.append("no_promotion_qualified_databento_mbo_outcomes")
        if len(qualified) < TARGET_OUTCOMES or len(dates) < TARGET_DATES:
            blockers.append("natural_forward_sample_incomplete")
        if any(len(regime_dates[name]) < TARGET_REGIME_DATES for name in REQUIRED_REGIMES):
            blockers.append("regime_date_coverage_incomplete")
        if candidate_id == "mes-orb-0932-vix-v2":
            blockers.append("frozen_trend_filter_conflicts_with_required_chop_outcomes")
        candidates.append(
            {
                "candidate_id": candidate_id,
                "family_id": family_id,
                "qualified_outcomes": len(qualified),
                "excluded_outcomes": len(excluded),
                "distinct_dates": len(dates),
                "targets": {
                    "resolved_outcomes": TARGET_OUTCOMES,
                    "distinct_dates": TARGET_DATES,
                    "dates_per_regime": TARGET_REGIME_DATES,
                },
                "regime_dates": {name: len(regime_dates[name]) for name in REQUIRED_REGIMES},
                "latency": {
                    "observations": len(latency_fractions),
                    "p90_fraction_of_expected_window": _p90(latency_fractions),
                    "maximum_allowed": 0.2,
                },
                "status": "evidence_complete_for_gate" if not blockers else "collecting_or_blocked",
                "blockers": blockers,
                "execution_enabled": False,
                "can_submit_orders": False,
            }
        )

    return {
        "schema_version": 1,
        "provider": "mes_v2_evidence_status",
        "generated_at": now.isoformat().replace("+00:00", "Z"),
        "live_feed": {
            "provider": "databento",
            "dataset": "GLBX.MDP3",
            "status": live_status,
            "reason": (capability or {}).get("live_reason"),
        },
        "evidence_planes": {
            "timely_discovery": "proxy_non_executable_not_promotion_eligible",
            "promotion_measurement": "delayed_databento_mbo_regrade",
        },
        "candidates": candidates,
        "execution_enabled": False,
        "can_submit_orders": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--outcomes", type=Path, default=DEFAULT_OUTCOMES)
    parser.add_argument("--capability", type=Path, default=DEFAULT_CAPABILITY)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    report = build_status(_read_jsonl(args.outcomes), capability=_read_json(args.capability))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(report, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

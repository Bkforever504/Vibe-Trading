#!/usr/bin/env python3
"""Aggregate resolved CISD outcomes into a fail-closed promotion status report."""
from __future__ import annotations

import argparse
import json
import math
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

ROOT = Path(__file__).resolve().parents[1]
SOURCE_LEDGER = ROOT / "data" / "pattern_grader_log.jsonl"
OUTCOME_LEDGER = ROOT / "data" / "pattern_grader_outcomes.jsonl"
REPORT_PATH = Path.home() / ".vibe-trading" / "reports" / "cisd-promotion-status.json"
CANONICAL_PATTERN_ID = "ict_cisd_universal_model"
CISD_PATTERN_IDS = {CANONICAL_PATTERN_ID, "cisd_bullish", "cisd_bearish"}


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    try:
        lines = path.read_text(encoding="utf-8-sig").splitlines()
    except OSError:
        return []
    output: list[dict[str, Any]] = []
    for line in lines:
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(row, dict):
            output.append(row)
    return output


def _pattern_id(row: dict[str, Any]) -> str:
    nested = row.get("pattern") if isinstance(row.get("pattern"), dict) else {}
    return str(row.get("pattern_id") or row.get("setup_id") or nested.get("id") or "")


def _detection_id(row: dict[str, Any]) -> str:
    explicit = row.get("detection_id") or row.get("event_id") or row.get("candidate_id")
    if explicit:
        return str(explicit)
    return "|".join(str(row.get(key) or "") for key in ("pattern_id", "symbol", "direction", "trigger_bar_ts"))


def _date(row: dict[str, Any]) -> str:
    return str(row.get("date") or row.get("session_date") or row.get("trigger_bar_ts") or row.get("bar_close_ts") or "")[:10]


def _number(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _probability(row: dict[str, Any]) -> float | None:
    value = row.get("probability")
    if isinstance(value, dict):
        value = next((value.get(key) for key in ("value", "win", "win_probability") if value.get(key) is not None), None)
    if value is None:
        value = row.get("win_probability") or row.get("probability_win")
    number = _number(value)
    if number is None:
        return None
    number = number / 100.0 if number > 1 else number
    return number if 0 <= number <= 1 else None


def _resolved_outcome(row: dict[str, Any]) -> tuple[bool, float] | None:
    value: Any = next((row.get(name) for name in ("outcome_eod", "outcome_60m", "outcome_15m", "outcome_5m") if row.get(name) is not None), None)
    if value is None:
        value = row.get("outcome")
    if isinstance(value, dict):
        realized = _number(value.get("realized_r") if value.get("realized_r") is not None else value.get("outcome_r"))
        won = value.get("won")
        if won is not None:
            return bool(won), realized if realized is not None else (1.0 if won else -1.0)
        return (realized > 0, realized) if realized is not None else None
    realized = _number(value)
    return (realized > 0, realized) if realized is not None else None


def wilson_lower_bound(wins: int, total: int, *, z: float = 1.96) -> float | None:
    if total <= 0:
        return None
    p = wins / total
    denominator = 1 + z * z / total
    center = p + z * z / (2 * total)
    margin = z * math.sqrt((p * (1 - p) + z * z / (4 * total)) / total)
    return (center - margin) / denominator


def evaluate_gate(*, n_outcomes: int, n_unique_dates: int, wilson: float | None, brier_skill: float | None) -> tuple[bool, list[str]]:
    reasons: list[str] = []
    if n_outcomes < 100:
        reasons.append("n_outcomes < 100")
    if n_unique_dates < 30:
        reasons.append("n_unique_dates < 30")
    if wilson is None or wilson < 0.55:
        reasons.append("wilson_lower_bound_95 < 0.55")
    if brier_skill is None or brier_skill <= 0:
        reasons.append("brier_skill <= 0")
    return not reasons, reasons


def build_status(rows: Iterable[dict[str, Any]], *, now_utc: str | None = None) -> dict[str, Any]:
    latest: dict[str, dict[str, Any]] = {}
    for row in rows:
        if not isinstance(row, dict) or _pattern_id(row) not in CISD_PATTERN_IDS:
            continue
        key = _detection_id(row)
        prior = latest.get(key, {})
        latest[key] = {**prior, **row}
    resolved = [(row, outcome) for row in latest.values() if (outcome := _resolved_outcome(row)) is not None]
    wins = sum(outcome[0] for _, outcome in resolved)
    n_outcomes = len(resolved)
    dates = {_date(row) for row, _ in resolved if _date(row)}
    scored = [(probability, float(outcome[0])) for row, outcome in resolved if (probability := _probability(row)) is not None]
    brier = sum((probability - outcome) ** 2 for probability, outcome in scored) / len(scored) if scored else None
    baseline = sum((0.5 - outcome) ** 2 for _, outcome in scored) / len(scored) if scored else None
    skill = (baseline - brier) / baseline if brier is not None and baseline else None
    wilson = wilson_lower_bound(wins, n_outcomes)
    eligible, reasons = evaluate_gate(n_outcomes=n_outcomes, n_unique_dates=len(dates), wilson=wilson, brier_skill=skill)
    stamp = now_utc or datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    return {
        "schema_version": 1,
        "pattern_id": CANONICAL_PATTERN_ID,
        "hypothesis_status": "validated_pattern" if eligible else "unvalidated_pattern_hypothesis",
        "n_outcomes": n_outcomes,
        "n_unique_dates": len(dates),
        "wins": wins,
        "win_rate_raw": round(wins / n_outcomes, 6) if n_outcomes else None,
        "wilson_lower_bound_95": round(wilson, 6) if wilson is not None else None,
        "n_scored_probabilities": len(scored),
        "brier_score": round(brier, 6) if brier is not None else None,
        "brier_baseline": round(baseline, 6) if baseline is not None else None,
        "brier_skill": round(skill, 6) if skill is not None else None,
        "gate_status": "passed" if eligible else "pending",
        "gate_reasons_pending": reasons,
        "eligible_for_validated_promotion": eligible,
        "last_updated_utc": stamp,
        "source_labels": ["data/pattern_grader_log.jsonl", "data/pattern_grader_outcomes.jsonl", "cisd_promotion_gate_v1"],
        "execution_enabled": False,
        "can_submit_orders": False,
    }


def _atomic(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(path)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=SOURCE_LEDGER)
    parser.add_argument("--outcomes", type=Path, default=OUTCOME_LEDGER)
    parser.add_argument("--output", type=Path, default=REPORT_PATH)
    args = parser.parse_args()
    status = build_status([*_read_jsonl(args.source), *_read_jsonl(args.outcomes)])
    _atomic(args.output, status)
    print(json.dumps(status, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Nominate grade reviews from post-Discord outcomes; never mutate rules."""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import statistics
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping

VIBE_HOME = Path.home() / ".vibe-trading"
INPUT_PATH = VIBE_HOME / "reports" / "discord-alert-chart-review.json"
HISTORY_PATH = VIBE_HOME / "data" / "discord_alert_chart_review_history.jsonl"
REPORT_PATH = VIBE_HOME / "reports" / "grade-recalibration-nominations.json"
LEDGER_PATH = VIBE_HOME / "data" / "grade_recalibration_nominations.jsonl"
MIN_SAMPLE = 30
INDEXES = {"SPY", "QQQ", "IWM", "DIA"}
MAG7 = {"AAPL", "MSFT", "AMZN", "GOOGL", "GOOG", "META", "NVDA", "TSLA"}


def symbol_class(symbol: Any) -> str:
    value = str(symbol or "").upper()
    return "index" if value in INDEXES else "mag7" if value in MAG7 else "other"


def build_report(outcomes: Iterable[Mapping[str, Any]], *, minimum_sample: int = MIN_SAMPLE) -> dict[str, Any]:
    minimum_sample = max(MIN_SAMPLE, minimum_sample)
    groups: dict[tuple[str, str, str, str], list[dict[str, Any]]] = defaultdict(list)
    excluded: Counter[str] = Counter()
    seen: set[str] = set()
    for source in outcomes:
        row = dict(source)
        value = row.get("outcome_r")
        if row.get("status") != "evaluated" or isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
            excluded["non_terminal_or_invalid_outcome"] += 1
            continue
        if row.get("duplicate_of"):
            excluded["duplicate"] += 1
            continue
        identity = row.get("outcome_id")
        if not identity:
            excluded["missing_unique_outcome_identity"] += 1
            continue
        if identity in seen:
            excluded["duplicate"] += 1
            continue
        if row.get("calibration_eligible") is not True or row.get("delivery_timestamp_quality") != "exact":
            excluded["unverified_delivery_or_outcome_policy"] += 1
            continue
        regime = row.get("regime_bucket")
        keys = ("vix_bucket", "trend_bucket", "session_slot", "day_of_week")
        if not isinstance(regime, Mapping) or any(not regime.get(key) or str(regime[key]).lower() in {"missing", "unknown", "unavailable", "outside_rth"} for key in keys):
            excluded["missing_regime_evidence"] += 1
            continue
        seen.add(identity)
        regime_key = json.dumps({key: regime[key] for key in keys}, sort_keys=True)
        groups[(str(row.get("setup") or "unknown"), str(row.get("grade") or "unknown"), symbol_class(row.get("symbol")), regime_key)].append(row)
    nominations = []
    for (setup, grade, klass, regime_key), rows in sorted(groups.items()):
        if len(rows) < minimum_sample:
            continue
        rows.sort(key=lambda row: str(row["outcome_id"]))
        values = [float(row["outcome_r"]) for row in rows]
        hit = sum(value > 0 for value in values) / len(values)
        median_r = statistics.median(values)
        action = "nominate_grade_tightening_review" if hit < 0.55 or median_r < 0.5 else "nominate_threshold_hold_review"
        evidence_ids = sorted(str(row["outcome_id"]) for row in rows)
        material = json.dumps([setup, grade, klass, regime_key, evidence_ids, values, action], sort_keys=True)
        nominations.append({
            "nomination_id": hashlib.sha256(material.encode("utf-8")).hexdigest(),
            "setup": setup, "grade": grade, "symbol_class": klass, "sample_size": len(rows),
            "regime_bucket": json.loads(regime_key),
            "evidence_outcome_ids": evidence_ids,
            "sample_sessions": len({row.get("session_date") for row in rows if row.get("session_date")}),
            "current_routing": "discord", "proposed_routing": "dashboard_only" if "tightening" in action else "discord",
            "action": action,
            "current": {"post_delivery_hit_rate": round(hit, 4), "median_r": round(median_r, 4)},
            "proposed": {"review": "raise_minimum_score_or_confirmation_quality" if "tightening" in action else "hold_thresholds", "target_hit_rate": 0.55, "target_median_r": 0.5},
            "automatic_parameter_changes": False, "human_review_required": True,
            "promotion_status": "human_review_required",
            "execution_enabled": False, "can_submit_orders": False,
        })
    return {
        "provider": "post_delivery_grade_calibrator", "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "minimum_sample": minimum_sample, "eligible_buckets": len(nominations), "nominations": nominations,
        "evidence_policy": "unique_terminal_post_delivery_outcomes_with_observed_regime_only",
        "excluded_counts": dict(excluded), "qualified_outcomes": len(seen),
        "promotion_status": "human_review_required",
        "automatic_parameter_changes": False, "human_review_required": True,
        "execution_enabled": False, "can_submit_orders": False,
    }


def _read(path: Path) -> dict[str, Any]:
    try: return json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError): return {}


def _history(path: Path) -> list[dict[str, Any]]:
    try: lines = path.read_text(encoding="utf-8-sig").splitlines()
    except OSError: return []
    rows=[]
    for line in lines:
        try: value=json.loads(line)
        except json.JSONDecodeError: continue
        if isinstance(value, dict): rows.append(value)
    return rows


def persist(report: Mapping[str, Any], report_path: Path = REPORT_PATH, ledger_path: Path = LEDGER_PATH) -> None:
    report_path.parent.mkdir(parents=True, exist_ok=True)
    temp = report_path.with_suffix(report_path.suffix + ".tmp")
    temp.write_text(json.dumps(dict(report), indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temp.replace(report_path)
    seen = set()
    if ledger_path.exists():
        for line in ledger_path.read_text(encoding="utf-8-sig").splitlines():
            try: seen.add(str(json.loads(line).get("nomination_id") or ""))
            except json.JSONDecodeError: pass
    fresh = [row for row in report.get("nominations") or [] if row.get("nomination_id") not in seen]
    if fresh:
        ledger_path.parent.mkdir(parents=True, exist_ok=True)
        with ledger_path.open("a", encoding="utf-8") as handle:
            for row in fresh: handle.write(json.dumps(row, sort_keys=True, separators=(",", ":")) + "\n")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=INPUT_PATH); parser.add_argument("--history", type=Path, default=HISTORY_PATH); parser.add_argument("--report", type=Path, default=REPORT_PATH); parser.add_argument("--ledger", type=Path, default=LEDGER_PATH)
    args = parser.parse_args(); source = _read(args.input)
    reports = _history(args.history)
    by_day = {str(row.get("session_date") or ""): row for row in reports if row.get("session_date")}
    if source.get("session_date"): by_day[str(source["session_date"])] = source
    report = build_report([alert for daily in by_day.values() for alert in (daily.get("alerts") or [])]); persist(report, args.report, args.ledger)
    print(json.dumps({"nominations": len(report["nominations"]), "automatic_parameter_changes": False}))
    return 0


if __name__ == "__main__": raise SystemExit(main())

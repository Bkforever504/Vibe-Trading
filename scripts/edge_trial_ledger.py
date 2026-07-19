#!/usr/bin/env python3
"""Immutable edge-trial ledger and multiple-testing governance report."""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import time
from contextlib import contextmanager
from datetime import date, datetime, timezone
from pathlib import Path
from statistics import NormalDist
from typing import Any, Iterator


ROOT = Path(__file__).resolve().parent.parent
VIBE_HOME = Path.home() / ".vibe-trading"
LEDGER_PATH = ROOT / "data" / "edge_trial_ledger.jsonl"
REPORT_PATH = VIBE_HOME / "reports" / "edge-trial-ledger.json"
REPORT_LOG_PATH = ROOT / "data" / "edge_trial_ledger_report_log.jsonl"

ALPHA = 0.05
MIN_OOS_TRADES = 30
REQUIRED_FIELDS = {
    "edge_id",
    "hypothesis",
    "variant",
    "stage",
    "dataset_start",
    "dataset_end",
    "cost_model",
    "metrics",
    "source",
}


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        try:
            value = json.loads(raw)
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            rows.append(value)
    return rows


def _number(value: Any, default: float | None = None) -> float | None:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return default
    return result if math.isfinite(result) else default


def _integer(value: Any, default: int = 0) -> int:
    value = _number(value, float(default))
    return int(value if value is not None else default)


def _canonical_identity(trial: dict[str, Any]) -> dict[str, Any]:
    return {
        "edge_id": trial.get("edge_id"),
        "variant": trial.get("variant"),
        "stage": trial.get("stage"),
        "parameters": trial.get("parameters") or {},
        "dataset_start": trial.get("dataset_start"),
        "dataset_end": trial.get("dataset_end"),
        "oos_start": trial.get("oos_start"),
        "oos_end": trial.get("oos_end"),
        "cost_model": trial.get("cost_model"),
        "source": trial.get("source"),
        "code_version": trial.get("code_version"),
    }


def trial_id(trial: dict[str, Any]) -> str:
    payload = json.dumps(_canonical_identity(trial), separators=(",", ":"), sort_keys=True)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:20]


def validate_trial(trial: dict[str, Any]) -> list[str]:
    errors = [f"missing_{field}" for field in sorted(REQUIRED_FIELDS) if trial.get(field) in (None, "", {})]
    metrics = trial.get("metrics")
    if not isinstance(metrics, dict):
        errors.append("metrics_must_be_object")
    stage = str(trial.get("stage") or "")
    if stage not in {"in_sample", "out_of_sample", "forward"}:
        errors.append("invalid_stage")
    if stage in {"out_of_sample", "forward"}:
        for field in ("oos_start", "oos_end"):
            if trial.get(field) in (None, ""):
                errors.append(f"missing_{field}")
    for field in ("dataset_start", "dataset_end"):
        try:
            date.fromisoformat(str(trial.get(field)))
        except ValueError:
            errors.append(f"invalid_{field}")
    for field in ("oos_start", "oos_end"):
        if trial.get(field) not in (None, ""):
            try:
                date.fromisoformat(str(trial.get(field)))
            except ValueError:
                errors.append(f"invalid_{field}")
    try:
        if date.fromisoformat(str(trial.get("dataset_start"))) > date.fromisoformat(str(trial.get("dataset_end"))):
            errors.append("dataset_window_reversed")
        if trial.get("oos_start") and trial.get("oos_end") and date.fromisoformat(str(trial.get("oos_start"))) > date.fromisoformat(str(trial.get("oos_end"))):
            errors.append("oos_window_reversed")
    except ValueError:
        pass
    return sorted(set(errors))


@contextmanager
def _ledger_lock(path: Path, timeout_seconds: float = 5.0) -> Iterator[None]:
    lock = path.with_suffix(path.suffix + ".lock")
    deadline = time.monotonic() + timeout_seconds
    while True:
        try:
            descriptor = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            os.close(descriptor)
            break
        except FileExistsError:
            if time.monotonic() >= deadline:
                raise TimeoutError(f"ledger lock timeout: {lock}")
            time.sleep(0.05)
    try:
        yield
    finally:
        try:
            lock.unlink()
        except FileNotFoundError:
            pass


def record_trial(trial: dict[str, Any], path: Path = LEDGER_PATH) -> dict[str, Any]:
    errors = validate_trial(trial)
    if errors:
        raise ValueError(";".join(errors))
    record = dict(trial)
    record["trial_id"] = trial_id(record)
    record["recorded_at"] = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    record["execution_enabled"] = False
    record["can_submit_orders"] = False
    path.parent.mkdir(parents=True, exist_ok=True)
    with _ledger_lock(path):
        rows = _read_jsonl(path)
        if any(row.get("trial_id") == record["trial_id"] for row in rows):
            return {"recorded": False, "duplicate": True, "trial_id": record["trial_id"]}
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, separators=(",", ":"), sort_keys=True) + "\n")
    return {"recorded": True, "duplicate": False, "trial_id": record["trial_id"]}


def _p_value(metrics: dict[str, Any]) -> float | None:
    explicit = _number(metrics.get("oos_p_value"))
    if explicit is not None and 0 <= explicit <= 1:
        return explicit
    t_stat = _number(metrics.get("oos_t_stat"))
    if t_stat is None:
        return None
    return 1 - NormalDist().cdf(t_stat)


def _bh_pass_ids(rows: list[dict[str, Any]], alpha: float) -> set[str]:
    eligible = sorted(
        ((row["p_value"], row["trial_id"]) for row in rows if row.get("p_value") is not None),
        key=lambda item: item[0],
    )
    count = len(rows)  # Every attempted trial counts, including trials missing a p-value.
    last_rank = 0
    for rank, (p_value, _) in enumerate(eligible, 1):
        if p_value <= rank / max(1, count) * alpha:
            last_rank = rank
    return {trial_id for _, trial_id in eligible[:last_rank]}


def build_report(path: Path = LEDGER_PATH, alpha: float = ALPHA) -> dict[str, Any]:
    trials = _read_jsonl(path)
    trial_count = len(trials)
    bonferroni_alpha = alpha / max(1, trial_count)
    bonferroni_t = NormalDist().inv_cdf(1 - bonferroni_alpha)
    rows = []
    for trial in trials:
        metrics = trial.get("metrics") if isinstance(trial.get("metrics"), dict) else {}
        p_value = _p_value(metrics)
        rows.append({
            "trial_id": trial.get("trial_id") or trial_id(trial),
            "edge_id": trial.get("edge_id"),
            "variant": trial.get("variant"),
            "source": trial.get("source"),
            "stage": trial.get("stage"),
            "oos_start": trial.get("oos_start"),
            "oos_end": trial.get("oos_end"),
            "oos_trade_count": _integer(metrics.get("oos_trade_count")),
            "oos_expectancy": _number(metrics.get("oos_expectancy")),
            "oos_profit_factor": _number(metrics.get("oos_profit_factor")),
            "oos_max_drawdown": _number(metrics.get("oos_max_drawdown")),
            "oos_t_stat": _number(metrics.get("oos_t_stat")),
            "p_value": round(p_value, 8) if p_value is not None else None,
            "bonferroni_pass": p_value is not None and p_value <= bonferroni_alpha,
        })
    bh_ids = _bh_pass_ids(rows, alpha)
    promotion_review = []
    for row in rows:
        row["benjamini_hochberg_pass"] = row["trial_id"] in bh_ids
        blockers = []
        if row["stage"] not in {"out_of_sample", "forward"}:
            blockers.append("out_of_sample_or_forward_stage_required")
        if not row["bonferroni_pass"]:
            blockers.append("multiple_testing_threshold_not_met")
        if row["oos_trade_count"] < MIN_OOS_TRADES:
            blockers.append("fewer_than_30_oos_trades")
        if row["oos_expectancy"] is None or row["oos_expectancy"] <= 0:
            blockers.append("positive_oos_expectancy_not_proven")
        if row["oos_profit_factor"] is None or row["oos_profit_factor"] <= 1:
            blockers.append("oos_profit_factor_not_above_one")
        if row["oos_max_drawdown"] is None:
            blockers.append("oos_max_drawdown_missing")
        row["promotion_blockers"] = blockers
        row["promotion_review_eligible"] = not blockers
        if not blockers:
            promotion_review.append(row)
    return {
        "provider": "edge_trial_ledger",
        "mode": "read_only_research_governance",
        "execution_enabled": False,
        "can_submit_orders": False,
        "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "ledger_path": str(path),
        "trial_count": trial_count,
        "edge_count": len({row.get("edge_id") for row in rows if row.get("edge_id")}),
        "promotion_review_count": len(promotion_review),
        "multiple_testing": {
            "family_alpha": alpha,
            "bonferroni_alpha": round(bonferroni_alpha, 8),
            "one_sided_normal_t_threshold": round(bonferroni_t, 4),
            "benjamini_hochberg_pass_count": len(bh_ids),
            "all_attempted_trials_counted": True,
        },
        "promotion_review": promotion_review,
        "trials": rows,
        "warnings": [
            "An empty ledger means no edge has earned statistical approval; it does not mean no tests were attempted historically.",
            "All new experiments must be recorded, including failures, before comparing strategy variants.",
            "Statistical significance is necessary but not sufficient; costs, drawdown, regime stability, and forward replication still matter.",
            "This ledger cannot promote a signal or submit orders.",
        ],
    }


def write_report(report: dict[str, Any], path: Path = REPORT_PATH) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(temp, path)


def append_report_log(report: dict[str, Any], path: Path = REPORT_LOG_PATH) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(report, separators=(",", ":"), sort_keys=True) + "\n")


def _load_import(path: Path) -> list[dict[str, Any]]:
    value = json.loads(path.read_text(encoding="utf-8-sig"))
    if isinstance(value, dict):
        return [value]
    if isinstance(value, list) and all(isinstance(row, dict) for row in value):
        return value
    raise ValueError("import must be a trial object or list of trial objects")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command")
    record = sub.add_parser("record", help="Append immutable trial record(s) from JSON.")
    record.add_argument("input", type=Path)
    record.add_argument("--ledger-path", type=Path, default=LEDGER_PATH)
    report = sub.add_parser("report", help="Build the multiple-testing report.")
    report.add_argument("--ledger-path", type=Path, default=LEDGER_PATH)
    report.add_argument("--report-path", type=Path, default=REPORT_PATH)
    report.add_argument("--log-path", type=Path, default=REPORT_LOG_PATH)
    report.add_argument("--print", action="store_true", dest="do_print")
    args = parser.parse_args()
    if args.command == "record":
        results = [record_trial(row, args.ledger_path) for row in _load_import(args.input)]
        print(json.dumps(results, indent=2, sort_keys=True))
        return 0
    if args.command in (None, "report"):
        ledger_path = getattr(args, "ledger_path", LEDGER_PATH)
        report_path = getattr(args, "report_path", REPORT_PATH)
        log_path = getattr(args, "log_path", REPORT_LOG_PATH)
        result = build_report(ledger_path)
        write_report(result, report_path)
        append_report_log(result, log_path)
        if getattr(args, "do_print", False):
            print(json.dumps(result, indent=2, sort_keys=True))
        else:
            print(f"Edge trial ledger report wrote {report_path}")
        return 0
    parser.error("unknown command")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())

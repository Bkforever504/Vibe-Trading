#!/usr/bin/env python3
"""Independent, fail-closed statistical attack on strategy evidence manifests.

The builder supplies raw return sequences and provenance. This reviewer tries
to disprove the edge. It never changes strategy settings or submits orders.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import random
from datetime import datetime, timezone
from pathlib import Path
from statistics import NormalDist, mean, pstdev
from typing import Any


ROOT = Path(__file__).resolve().parent.parent
VIBE_HOME = Path.home() / ".vibe-trading"
MANIFEST_DIR = ROOT / "research" / "adversarial_manifests"
RUNTIME_MANIFEST_DIR = VIBE_HOME / "adversarial-manifests"
REPORT_PATH = VIBE_HOME / "reports" / "adversarial-strategy-audit.json"
LOG_PATH = ROOT / "data" / "adversarial_strategy_audit_log.jsonl"

MIN_FINAL_TRADES = 30
MIN_FORWARD_TRADES = 30
MAX_OPERATION_COUNT = 20
MIN_NEIGHBOR_PASS_RATE = 0.60
MIN_REGIME_PASS_RATE = 0.67
MIN_WALK_FORWARD_PASS_RATE = 0.60
MIN_TOP_ONE_PCT_RETENTION = 0.50
MIN_DSR_PROBABILITY = 0.95


def _numbers(values: Any) -> list[float]:
    if not isinstance(values, list):
        return []
    out = []
    for value in values:
        try:
            number = float(value)
        except (TypeError, ValueError):
            continue
        if math.isfinite(number):
            out.append(number)
    return out


def _expectancy(values: list[float]) -> float | None:
    return mean(values) if values else None


def _remove_top_one_pct(values: list[float]) -> list[float]:
    if not values:
        return []
    remove_count = max(1, math.ceil(len(values) * 0.01))
    return sorted(values)[:-remove_count]


def _moving_block_bootstrap(values: list[float], samples: int = 2000, seed: int = 20260720) -> dict[str, Any]:
    if len(values) < 10:
        return {"sample_count": len(values), "lower_95": None, "upper_95": None, "passed": False}
    rng = random.Random(seed)
    block = max(2, int(math.sqrt(len(values))))
    estimates = []
    for _ in range(samples):
        sample: list[float] = []
        while len(sample) < len(values):
            start = rng.randrange(len(values))
            sample.extend(values[(start + offset) % len(values)] for offset in range(block))
        estimates.append(mean(sample[:len(values)]))
    estimates.sort()
    lower = estimates[int(samples * 0.025)]
    upper = estimates[min(samples - 1, int(samples * 0.975))]
    return {
        "sample_count": len(values),
        "block_length": block,
        "lower_95": round(lower, 8),
        "upper_95": round(upper, 8),
        "passed": lower > 0,
    }


def _moments(values: list[float]) -> tuple[float, float]:
    if len(values) < 3:
        return 0.0, 3.0
    center = mean(values)
    sigma = pstdev(values)
    if sigma == 0:
        return 0.0, 3.0
    standardized = [(value - center) / sigma for value in values]
    return mean([value ** 3 for value in standardized]), mean([value ** 4 for value in standardized])


def _deflated_sharpe(values: list[float], trials_considered: int) -> dict[str, Any]:
    if len(values) < 10 or pstdev(values) == 0:
        return {"probability": None, "passed": False, "reason": "insufficient_variation_or_sample"}
    n = len(values)
    observed = mean(values) / pstdev(values)
    trials = max(1, int(trials_considered))
    gamma = 0.5772156649
    if trials == 1:
        expected_max = 0.0
    else:
        normal = NormalDist()
        expected_z = (
            (1 - gamma) * normal.inv_cdf(1 - 1 / trials)
            + gamma * normal.inv_cdf(1 - 1 / (trials * math.e))
        )
        expected_max = expected_z / math.sqrt(max(1, n - 1))
    skew, kurtosis = _moments(values)
    denominator = math.sqrt(max(1e-12, (1 - skew * observed + ((kurtosis - 1) / 4) * observed ** 2) / (n - 1)))
    probability = NormalDist().cdf((observed - expected_max) / denominator)
    return {
        "observed_sharpe_per_trade": round(observed, 6),
        "expected_max_sharpe_under_trials": round(expected_max, 6),
        "trials_considered": trials,
        "probability": round(probability, 6),
        "passed": probability >= MIN_DSR_PROBABILITY,
    }


def _positive_rate(groups: Any) -> tuple[int, int, float]:
    rows = list(groups.values()) if isinstance(groups, dict) else groups if isinstance(groups, list) else []
    expectancies = []
    for row in rows:
        returns = _numbers(row.get("returns") if isinstance(row, dict) else row)
        if returns:
            expectancies.append(mean(returns))
    positive = sum(value > 0 for value in expectancies)
    rate = positive / len(expectancies) if expectancies else 0.0
    return positive, len(expectancies), rate


def audit_manifest(manifest: dict[str, Any]) -> dict[str, Any]:
    subject = str(manifest.get("subject_id") or "").strip()
    returns = manifest.get("returns") if isinstance(manifest.get("returns"), dict) else {}
    final = _numbers(returns.get("final"))
    forward = _numbers(returns.get("forward"))
    cost_2x = _numbers(returns.get("cost_2x"))
    cost_3x = _numbers(returns.get("cost_3x"))
    base_expectancy = _expectancy(final)
    trimmed = _remove_top_one_pct(final)
    trimmed_expectancy = _expectancy(trimmed)
    retention = (
        trimmed_expectancy / base_expectancy
        if base_expectancy is not None and base_expectancy > 0 and trimmed_expectancy is not None
        else 0.0
    )
    neighbor_positive, neighbor_count, neighbor_rate = _positive_rate(manifest.get("parameter_neighbors"))
    regime_positive, regime_count, regime_rate = _positive_rate(manifest.get("regimes"))
    fold_positive, fold_count, fold_rate = _positive_rate(manifest.get("walk_forward_folds"))
    bootstrap = _moving_block_bootstrap(forward or final)
    dsr = _deflated_sharpe(forward or final, int(manifest.get("trials_considered") or 1))

    checks = {
        "identity_complete": bool(subject and manifest.get("builder_id") and manifest.get("reviewer_id")),
        "independent_reviewer": bool(manifest.get("reviewer_id") and manifest.get("reviewer_id") != manifest.get("builder_id")),
        "preregistered": manifest.get("preregistered") is True,
        "point_in_time_timestamp_audit": (manifest.get("timestamp_audit") or {}).get("passed") is True,
        "backtest_forward_parity": (manifest.get("backtest_forward_parity") or {}).get("passed") is True,
        "execution_delay_positive": int(manifest.get("execution_delay_bars") or 0) >= 1,
        "operation_count_bounded": 0 < int(manifest.get("operation_count") or 0) <= MAX_OPERATION_COUNT,
        "final_sample_sufficient": len(final) >= MIN_FINAL_TRADES,
        "forward_sample_sufficient": len(forward) >= MIN_FORWARD_TRADES,
        "final_expectancy_positive": base_expectancy is not None and base_expectancy > 0,
        "forward_expectancy_positive": _expectancy(forward) is not None and mean(forward) > 0,
        "top_one_pct_not_decisive": retention >= MIN_TOP_ONE_PCT_RETENTION and (trimmed_expectancy or 0) > 0,
        "double_cost_positive": bool(cost_2x) and mean(cost_2x) > 0,
        "triple_cost_positive": bool(cost_3x) and mean(cost_3x) > 0,
        "parameter_neighborhood_stable": neighbor_count >= 5 and neighbor_rate >= MIN_NEIGHBOR_PASS_RATE,
        "regime_stable": regime_count >= 3 and regime_rate >= MIN_REGIME_PASS_RATE,
        "rolling_walk_forward_stable": fold_count >= 5 and fold_rate >= MIN_WALK_FORWARD_PASS_RATE,
        "bootstrap_lower_bound_positive": bootstrap["passed"],
        "deflated_sharpe_passed": dsr["passed"],
    }
    failed = [name for name, passed in checks.items() if not passed]
    score = round(sum(checks.values()) / len(checks) * 10, 2)
    return {
        "subject_id": subject or "missing_subject",
        "strategy_version": manifest.get("strategy_version"),
        "score_out_of_10": score,
        "passed": not failed and score >= 9.0,
        "promotion_authority": "human_review_only" if not failed else "blocked",
        "checks": checks,
        "failed_checks": failed,
        "diagnostics": {
            "final_trade_count": len(final),
            "forward_trade_count": len(forward),
            "final_expectancy": base_expectancy,
            "forward_expectancy": _expectancy(forward),
            "top_one_pct_removed_expectancy": trimmed_expectancy,
            "top_one_pct_retention": round(retention, 4),
            "parameter_neighbor_positive_rate": round(neighbor_rate, 4),
            "regime_positive_rate": round(regime_rate, 4),
            "walk_forward_positive_rate": round(fold_rate, 4),
            "bootstrap": bootstrap,
            "deflated_sharpe": dsr,
        },
        "execution_enabled": False,
        "can_submit_orders": False,
    }


def build_report(manifest_dir: Path = MANIFEST_DIR, runtime_manifest_dir: Path | None = None) -> dict[str, Any]:
    manifests = []
    directories = [manifest_dir]
    if runtime_manifest_dir is not None:
        directories.append(runtime_manifest_dir)
    elif manifest_dir == MANIFEST_DIR:
        directories.append(RUNTIME_MANIFEST_DIR)
    for directory in directories:
        for path in sorted(directory.glob("*.json")) if directory.exists() else []:
            try:
                value = json.loads(path.read_text(encoding="utf-8-sig"))
            except (OSError, json.JSONDecodeError):
                continue
            if isinstance(value, dict):
                manifests.append((path, value))
    subjects = []
    for path, manifest in manifests:
        result = audit_manifest(manifest)
        result["manifest_path"] = str(path)
        subjects.append(result)
    by_subject = {row["subject_id"]: row for row in subjects}
    return {
        "provider": "adversarial_strategy_audit",
        "mode": "read_only_independent_reviewer",
        "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "execution_enabled": False,
        "can_submit_orders": False,
        "summary": {
            "subject_count": len(subjects),
            "passed_count": sum(row["passed"] for row in subjects),
            "blocked_count": sum(not row["passed"] for row in subjects),
            "fail_closed": True,
        },
        "by_subject": by_subject,
        "subjects": subjects,
        "promotion_blockers": ["no_adversarial_manifests"] if not subjects else [],
        "warnings": [
            "Passing grants human review only, never automatic execution.",
            "Missing evidence fails closed; the reviewer does not infer favorable metrics.",
        ],
    }


def write_report(report: dict[str, Any], report_path: Path = REPORT_PATH, log_path: Path = LOG_PATH) -> None:
    report_path.parent.mkdir(parents=True, exist_ok=True)
    temp = report_path.with_suffix(report_path.suffix + ".tmp")
    temp.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(temp, report_path)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(report, separators=(",", ":"), sort_keys=True) + "\n")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest-dir", type=Path, default=MANIFEST_DIR)
    parser.add_argument("--runtime-manifest-dir", type=Path, default=RUNTIME_MANIFEST_DIR)
    parser.add_argument("--report-path", type=Path, default=REPORT_PATH)
    parser.add_argument("--log-path", type=Path, default=LOG_PATH)
    parser.add_argument("--print", action="store_true", dest="do_print")
    args = parser.parse_args()
    report = build_report(args.manifest_dir, args.runtime_manifest_dir)
    write_report(report, args.report_path, args.log_path)
    if args.do_print:
        print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

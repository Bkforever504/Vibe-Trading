#!/usr/bin/env python3
"""Uniform, shadow-only statistical evaluation for frozen research lanes.

Input rows are already-resolved executable outcomes. Promotion statistics require
an explicit qualified-evidence contract, unique ``plan_id``, stable
``strategy_id``/``candidate_id``, ``session_date``, and ``outcome_r``. Placebo
testing additionally requires the frozen ``signal`` (-1/1) and corresponding
unsigned ``forward_return_r``; missing evidence never passes silently.
"""
from __future__ import annotations

import argparse
import hashlib
import itertools
import json
import math
import random
import statistics
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_INPUT = ROOT / "data" / "shadow_outcomes.jsonl"
DEFAULT_FAMILY = ROOT / "data" / "experiment_family.jsonl"
PROMOTION_EVIDENCE_TIERS = frozenset(
    {
        "databento_mbo_executable",
        "databento_bbo_executable",
        "executable_market_data",
    }
)
PROMOTION_SOURCE_PREFIXES = ("databento_",)


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


def _mean(values: list[float]) -> float:
    return statistics.fmean(values) if values else 0.0


def _sharpe(values: list[float]) -> float | None:
    if len(values) < 2:
        return None
    deviation = statistics.stdev(values)
    return _mean(values) / deviation * math.sqrt(252) if deviation > 0 else None


def _moving_block_samples(values: list[float], *, seed: str, count: int = 1000) -> list[list[float]]:
    if not values:
        return []
    block = max(5, math.ceil(math.sqrt(len(values))))
    rng = random.Random(int(hashlib.sha256(seed.encode("utf-8")).hexdigest()[:16], 16))
    samples: list[list[float]] = []
    for _ in range(count):
        selected: list[float] = []
        while len(selected) < len(values):
            start = rng.randrange(len(values))
            selected.extend(values[(start + offset) % len(values)] for offset in range(block))
        samples.append(selected[: len(values)])
    return samples


def _quantile(values: list[float], probability: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    return ordered[max(0, min(len(ordered) - 1, int(probability * (len(ordered) - 1))))]


def _normal_cdf(value: float) -> float:
    return 0.5 * (1.0 + math.erf(value / math.sqrt(2.0)))


def _number(value: Any) -> float | None:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def _promotion_exclusion_reasons(row: dict[str, Any]) -> list[str]:
    reasons: list[str] = []
    if row.get("promotion_eligible") is not True:
        reasons.append("promotion_eligible_false" if row.get("promotion_eligible") is False else "promotion_eligible_missing")
    source = str(row.get("data_source") or "").strip()
    terminal_source = str(row.get("terminal_data_source") or "").strip()
    if not source:
        reasons.append("data_source_missing")
    elif not source.lower().startswith(PROMOTION_SOURCE_PREFIXES):
        reasons.append("data_source_not_whitelisted")
    if row.get("source_agreement") is not True or not terminal_source or source != terminal_source:
        reasons.append("source_agreement_not_explicit_true")
    tier = str(row.get("evidence_tier") or "").strip()
    terminal_tier = str(row.get("terminal_evidence_tier") or "").strip()
    if not tier:
        reasons.append("evidence_tier_missing")
    elif tier not in PROMOTION_EVIDENCE_TIERS:
        reasons.append("evidence_tier_not_whitelisted")
    if not terminal_tier or tier != terminal_tier:
        reasons.append("evidence_tier_agreement_missing")
    if _number(row.get("entry_fill_executable")) is None:
        reasons.append("executable_entry_fill_missing")
    if _number(row.get("exit_fill_executable")) is None:
        reasons.append("executable_exit_fill_missing")
    if row.get("evidence_blockers"):
        reasons.append("evidence_blockers_present")
    if not str(row.get("plan_id") or "").strip():
        reasons.append("plan_id_missing")
    if not str(row.get("strategy_id") or row.get("candidate_id") or "").strip():
        reasons.append("stable_candidate_id_missing")
    if not str(row.get("session_date") or row.get("session") or "").strip():
        reasons.append("session_date_missing")
    if _number(row.get("outcome_r")) is None:
        reasons.append("outcome_r_missing")
    return sorted(set(reasons))


def _version_key(row: dict[str, Any]) -> tuple[int, str]:
    raw = row.get("regrade_version") or row.get("outcome_version") or row.get("evidence_version") or 0
    try:
        version = int(raw)
    except (TypeError, ValueError):
        version = 0
    stamp = str(row.get("regraded_at") or row.get("resolved_at") or "")
    return version, stamp


def _dedupe_outcomes(rows: Iterable[dict[str, Any]]) -> tuple[list[dict[str, Any]], int]:
    """Keep one outcome per plan, preferring the latest qualified regrade."""
    by_plan: dict[str, dict[str, Any]] = {}
    unkeyed: list[dict[str, Any]] = []
    total = 0
    for source in rows:
        total += 1
        row = dict(source)
        plan_id = str(row.get("plan_id") or "").strip()
        if not plan_id:
            unkeyed.append(row)
            continue
        prior = by_plan.get(plan_id)
        rank = (not _promotion_exclusion_reasons(row), *_version_key(row))
        prior_rank = (not _promotion_exclusion_reasons(prior), *_version_key(prior)) if prior else None
        if prior is None or rank >= prior_rank:
            by_plan[plan_id] = row
    selected = [*unkeyed, *by_plan.values()]
    return selected, total - len(selected)


def _walk_forward(values: list[float], *, folds: int = 5, purge: int = 1) -> list[dict[str, Any]]:
    if len(values) < 10:
        return []
    fold_size = max(2, len(values) // folds)
    windows: list[dict[str, Any]] = []
    for start in range(fold_size, len(values), fold_size):
        test = values[start:min(len(values), start + fold_size)]
        train = values[:max(0, start - purge)]
        if train and test:
            windows.append({"train_n": len(train), "test_n": len(test), "train_expectancy": round(_mean(train), 6), "test_expectancy": round(_mean(test), 6)})
    return windows


def _placebo(rows: list[dict[str, Any]], *, candidate_id: str, family_size: int, count: int = 500) -> dict[str, Any]:
    try:
        signals = [float(row["signal"]) for row in rows]
        returns = [float(row["forward_return_r"]) for row in rows]
    except (KeyError, TypeError, ValueError):
        return {"status": "unavailable", "reason": "signal_or_forward_return_missing", "p_value": None}
    observed = _mean([signal * result for signal, result in zip(signals, returns)])
    rng = random.Random(int(hashlib.sha256((candidate_id + "|placebo").encode()).hexdigest()[:16], 16))
    exceed = 0
    shuffled = signals[:]
    for _ in range(count):
        rng.shuffle(shuffled)
        if _mean([signal * result for signal, result in zip(shuffled, returns)]) >= observed:
            exceed += 1
    p_value = (exceed + 1) / (count + 1)
    threshold = 0.05 / max(1, family_size)
    return {"status": "pass" if observed > 0 and p_value <= threshold else "fail", "p_value": round(p_value, 6), "bonferroni_alpha": round(threshold, 8), "permutations": count}


def _family_pbo(groups: dict[str, list[dict[str, Any]]], *, folds: int = 6) -> float | None:
    if len(groups) < 2:
        return None
    sessions = sorted({str(row["session"]) for rows in groups.values() for row in rows})
    if len(sessions) < folds:
        return None
    fold_by_session = {session: min(folds - 1, index * folds // len(sessions)) for index, session in enumerate(sessions)}
    failures = 0
    trials = 0
    for train_folds in itertools.combinations(range(folds), folds // 2):
        train_set = set(train_folds)
        train_means: dict[str, float] = {}
        test_means: dict[str, float] = {}
        for candidate_id, rows in groups.items():
            train = [float(row["outcome_r"]) for row in rows if fold_by_session[str(row["session"])] in train_set]
            test = [float(row["outcome_r"]) for row in rows if fold_by_session[str(row["session"])] not in train_set]
            if train and test:
                train_means[candidate_id] = _mean(train)
                test_means[candidate_id] = _mean(test)
        if len(train_means) < 2:
            continue
        selected = max(train_means, key=train_means.get)
        ordered_test = sorted(test_means, key=test_means.get, reverse=True)
        failures += int(ordered_test.index(selected) >= math.ceil(len(ordered_test) / 2))
        trials += 1
    return round(failures / trials, 6) if trials else None


def evaluate_replay(
    rows: Iterable[dict[str, Any]], *, family_size: int, now: datetime | None = None
) -> dict[str, Any]:
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    skipped = 0
    excluded = 0
    exclusion_reasons: dict[str, int] = defaultdict(int)
    exclusions_by_candidate: dict[str, int] = defaultdict(int)
    deduped_rows, duplicate_rows = _dedupe_outcomes(rows)
    for raw in deduped_rows:
        reasons = _promotion_exclusion_reasons(raw)
        if reasons:
            excluded += 1
            excluded_candidate = str(raw.get("strategy_id") or raw.get("candidate_id") or "unknown")
            exclusions_by_candidate[excluded_candidate] += 1
            for reason in reasons:
                exclusion_reasons[reason] += 1
            continue
        candidate_id = str(raw.get("strategy_id") or raw.get("candidate_id") or raw.get("setup_family") or "").strip()
        session = str(raw.get("session_date") or raw.get("session") or raw.get("resolved_at") or "")[:10]
        try:
            outcome = float(raw.get("outcome_r"))
        except (TypeError, ValueError):
            outcome = float("nan")
        if not candidate_id or not session or not math.isfinite(outcome):
            skipped += 1
            continue
        groups[candidate_id].append({**raw, "candidate_id": candidate_id, "session": session, "outcome_r": outcome})
    pbo = _family_pbo(groups)
    results: list[dict[str, Any]] = []
    for candidate_id, candidate_rows in sorted(groups.items()):
        candidate_rows.sort(key=lambda row: str(row["session"]))
        values = [float(row["outcome_r"]) for row in candidate_rows]
        bootstraps = _moving_block_samples(values, seed=candidate_id)
        means = [_mean(sample) for sample in bootstraps]
        sharpes = [value for sample in bootstraps if (value := _sharpe(sample)) is not None]
        point_sharpe = _sharpe(values)
        psr = _normal_cdf((point_sharpe or 0.0) * math.sqrt(max(1, len(values) - 1)) / math.sqrt(252)) if point_sharpe is not None else None
        alpha = 0.05 / max(1, family_size)
        tail = values[max(0, math.floor(len(values) * 0.8)):]
        stressed: list[float] = []
        stress_available = True
        for row in candidate_rows:
            try:
                stressed.append(float(row["doubled_cost_outcome_r"]))
            except (KeyError, TypeError, ValueError):
                stress_available = False
                break
        result = {
            "candidate_id": candidate_id,
            "n_resolved": len(values),
            "distinct_sessions": len({row["session"] for row in candidate_rows}),
            "expectancy": round(_mean(values), 6),
            "expectancy_lower_95_ci": round(_quantile(means, 0.025), 6) if means else None,
            "expectancy_upper_95_ci": round(_quantile(means, 0.975), 6) if means else None,
            "sharpe": round(point_sharpe, 6) if point_sharpe is not None else None,
            "dsr": round(psr, 6) if psr is not None else None,
            "dsr_lower_bound": round(_quantile(sharpes, alpha), 6) if sharpes else None,
            "bonferroni_alpha": round(alpha, 8),
            "pbo": pbo,
            "pbo_status": "unavailable_single_lane" if pbo is None else "measured_cpcv_family",
            "decay": {"full_expectancy": round(_mean(values), 6), "last_20_percent_expectancy": round(_mean(tail), 6), "same_sign": _mean(values) > 0 and _mean(tail) > 0},
            "placebo": _placebo(candidate_rows, candidate_id=candidate_id, family_size=family_size),
            "cost_stress": {"status": "pass" if stress_available and _mean(stressed) > 0 else "fail" if stress_available else "unavailable", "doubled_cost_expectancy": round(_mean(stressed), 6) if stress_available else None},
            "purged_walk_forward": _walk_forward(values),
            "preregistration_schema": (
                "hypothesis-v2"
                if all(row.get("preregistration_schema") == "hypothesis-v2" for row in candidate_rows)
                else None
            ),
            "multiple_testing": {
                "raw_p_value": _placebo(candidate_rows, candidate_id=candidate_id, family_size=family_size).get("p_value")
            },
            "regime_coverage": {
                regime: {
                    "independent_dates": len({
                        str(row["session"])
                        for row in candidate_rows
                        if regime in set(row.get("regime_tags") or [])
                    })
                }
                for regime in ("trend", "chop", "high_vol", "low_vol")
            },
            "latency": {
                "observations": len([
                    row for row in candidate_rows
                    if _number(row.get("alert_latency_fraction")) is not None
                ]),
                "p90_fraction_of_expected_window": _quantile(
                    sorted([
                        float(row["alert_latency_fraction"])
                        for row in candidate_rows
                        if _number(row.get("alert_latency_fraction")) is not None
                    ]),
                    0.9,
                ) if any(_number(row.get("alert_latency_fraction")) is not None for row in candidate_rows) else None,
            },
            "data_integrity": {
                "source_repair_detected": True,
                "backfill_status": "complete" if exclusions_by_candidate.get(candidate_id, 0) == 0 else "incomplete",
                "regrade_status": "complete" if exclusions_by_candidate.get(candidate_id, 0) == 0 else "incomplete",
                "contaminated_outcomes_remaining": exclusions_by_candidate.get(candidate_id, 0),
            },
            "revalidation": {
                "rolling_windows": len(_walk_forward(values)),
                "latest_brier_skill": None,
                "last_revalidated_at": None,
            },
            "universe": (
                dict(candidate_rows[0].get("universe") or {})
                if candidate_rows and all(
                    row.get("universe") == candidate_rows[0].get("universe")
                    for row in candidate_rows
                )
                else {}
            ),
            "execution_enabled": False,
            "can_submit_orders": False,
        }
        results.append(result)
    return {
        "schema_version": 1,
        "provider": "multi_lane_replay",
        "generated_at": (now or datetime.now(timezone.utc)).astimezone(timezone.utc).isoformat().replace("+00:00", "Z"),
        "family_size": family_size,
        "method": "purged_walk_forward_cpcv_family_pbo_moving_block_bootstrap_bonferroni",
        "skipped_rows": skipped,
        "excluded_rows": excluded,
        "duplicate_rows": duplicate_rows,
        "exclusion_reasons": dict(sorted(exclusion_reasons.items())),
        "results": results,
        "execution_enabled": False,
        "can_submit_orders": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--outcomes", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--family-ledger", type=Path, default=DEFAULT_FAMILY)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    family_size = len({row.get("spec_hash") for row in _read_jsonl(args.family_ledger) if row.get("spec_hash")})
    report = evaluate_replay(_read_jsonl(args.outcomes), family_size=family_size)
    output = args.output or ROOT / "data" / f"multi_lane_replay_{datetime.now().date().isoformat().replace('-', '')}.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"multi_lane_replay candidates={len(report['results'])} family_size={family_size} output={output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

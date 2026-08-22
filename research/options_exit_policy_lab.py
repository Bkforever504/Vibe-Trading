#!/usr/bin/env python3
"""Preregistered exit-policy replay over resolved shadow-directional lifecycles.

Reads `data/flip_shadow_candidates_log.jsonl` (per-lifecycle marks with
executable bid), replays a small frozen set of exit policies against every
completed lifecycle, and reports per-policy expectancy under baseline, doubled
cost, top-5%-outlier removal, chronological holdout, and per-regime splits.

Read-only. Never enables execution, never mutates production config, never
tunes on the holdout. Policy set is small and preregistered.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import sys
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterable

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

DEFAULT_CANDIDATES_PATH = ROOT / "data" / "flip_shadow_candidates_log.jsonl"
DEFAULT_OUTPUT_PATH = ROOT / "data" / "options_exit_policy_lab_results.json"
DEFAULT_HOLDOUT_FRACTION = 0.20
DEFAULT_FEE_PER_CONTRACT_PCT = 1.5  # single-leg round-trip friction proxy (%)
MIN_SAMPLES_FOR_REVIEW = 30
MIN_DATES_FOR_REVIEW = 20


@dataclass(frozen=True)
class Mark:
    ts: str
    bid: float
    mark: float
    ret_pct: float | None
    best_pct: float | None
    reason: str
    ask: float | None = None
    quote_age_seconds: float | None = None


@dataclass(frozen=True)
class Lifecycle:
    lifecycle_id: str
    date: str
    symbol: str
    right: str
    strategy: str
    day_type: str
    entry_premium: float
    marks: tuple[Mark, ...]
    entry_at: str = ""
    features: dict[str, Any] = field(default_factory=dict)
    episode_bucket_et: str = ""
    decision_pair_id: str = ""
    decision_lattice_role: str = ""
    entry_quote_timestamp: str = ""
    entry_quote_age_seconds: float | None = None
    pair_construction_method: str = ""
    pair_sync_status: str = ""


def _num(value: Any) -> float | None:
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    return out if math.isfinite(out) else None


def load_lifecycles(path: Path) -> list[Lifecycle]:
    if not path.exists():
        return []
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        lid = row.get("lifecycle_id")
        if isinstance(lid, str) and lid:
            groups[lid].append(row)
    lifecycles: list[Lifecycle] = []
    for lid, rows in groups.items():
        rows.sort(key=lambda r: str(r.get("scanned_at") or ""))
        entry_rows = [r for r in rows if r.get("event_type") == "shadow_entry"]
        exit_rows = [r for r in rows if r.get("event_type") == "shadow_exit"]
        if not entry_rows or not exit_rows:
            continue
        entry = entry_rows[0]
        entry_premium = _num(entry.get("entry_price_est"))
        if entry_premium is None:
            entry_premium = _num(entry.get("selection_bid"))
        if entry_premium is None or entry_premium <= 0:
            continue
        marks: list[Mark] = []
        for row in rows:
            bid = _num(row.get("selection_bid"))
            mark_p = _num(row.get("mark_price"))
            if bid is None or mark_p is None:
                continue
            marks.append(Mark(
                ts=str(row.get("scanned_at") or ""),
                bid=bid,
                mark=mark_p,
                ret_pct=_num(row.get("return_pct_at_mark")),
                best_pct=_num(row.get("best_return_pct_at_mark")),
                reason=str(row.get("mark_reason") or ""),
                ask=_num(row.get("selection_ask")),
                quote_age_seconds=_num(row.get("quote_age_seconds")),
            ))
        if not marks:
            continue
        lifecycles.append(Lifecycle(
            lifecycle_id=lid,
            date=str(entry.get("date") or ""),
            symbol=str(entry.get("symbol") or ""),
            right=str(entry.get("right") or ""),
            strategy=str(entry.get("strategy") or ""),
            day_type=str(entry.get("day_type") or "unknown"),
            entry_premium=entry_premium,
            marks=tuple(marks),
            entry_at=str(entry.get("scanned_at") or ""),
            features=(
                dict(entry.get("feature_snapshot"))
                if isinstance(entry.get("feature_snapshot"), dict)
                else {}
            ),
            episode_bucket_et=str(entry.get("episode_bucket_et") or ""),
            decision_pair_id=str(entry.get("decision_pair_id") or ""),
            decision_lattice_role=str(entry.get("decision_lattice_role") or ""),
            entry_quote_timestamp=str(entry.get("quote_timestamp") or ""),
            entry_quote_age_seconds=_num(entry.get("quote_age_seconds")),
            pair_construction_method=str(entry.get("pair_construction_method") or ""),
            pair_sync_status=str(entry.get("pair_sync_status") or ""),
        ))
    return lifecycles


PolicyResult = tuple[float, str]  # (executable_return_pct, exit_reason)


def _bid_return_pct(bid: float, entry_premium: float) -> float:
    return round((bid - entry_premium) / entry_premium * 100.0, 4)


def _policy_fixed(
    life: Lifecycle,
    *,
    stop_pct: float | None,
    target_pct: float | None,
    hard_close_reason: str = "hard_close",
) -> PolicyResult:
    entry = life.entry_premium
    for m in life.marks:
        if not m.bid:
            continue
        ret = _bid_return_pct(m.bid, entry)
        if stop_pct is not None and ret <= -abs(stop_pct):
            return ret, f"stop_{stop_pct:.0f}"
        if target_pct is not None and ret >= abs(target_pct):
            return ret, f"target_{target_pct:.0f}"
        if m.reason == hard_close_reason:
            return ret, hard_close_reason
    # session or horizon end fallback
    last = life.marks[-1]
    return _bid_return_pct(last.bid, entry), last.reason or "session_end"


def _policy_ratchet(
    life: Lifecycle,
    *,
    arm_pct: float,
    giveback_pct: float,
    stop_pct: float | None,
) -> PolicyResult:
    entry = life.entry_premium
    peak = -math.inf
    armed = False
    for m in life.marks:
        if not m.bid:
            continue
        ret = _bid_return_pct(m.bid, entry)
        peak = max(peak, ret)
        if stop_pct is not None and ret <= -abs(stop_pct):
            return ret, f"stop_{stop_pct:.0f}"
        if not armed and peak >= arm_pct:
            armed = True
        if armed and ret <= peak - giveback_pct:
            return ret, f"ratchet_lock_{peak:.0f}_gb{giveback_pct:.0f}"
        if m.reason == "hard_close":
            return ret, "hard_close"
    last = life.marks[-1]
    return _bid_return_pct(last.bid, entry), last.reason or "session_end"


def _policy_time_stop(life: Lifecycle, *, minutes: int) -> PolicyResult:
    entry = life.entry_premium
    start = life.marks[0].ts
    try:
        start_dt = datetime.fromisoformat(start.replace("Z", "+00:00"))
    except Exception:
        return _bid_return_pct(life.marks[-1].bid, entry), "bad_ts"
    for m in life.marks:
        if not m.bid:
            continue
        try:
            dt = datetime.fromisoformat(m.ts.replace("Z", "+00:00"))
        except Exception:
            continue
        elapsed = (dt - start_dt).total_seconds() / 60.0
        if elapsed >= minutes:
            return _bid_return_pct(m.bid, entry), f"time_{minutes}m"
        if m.reason == "hard_close":
            return _bid_return_pct(m.bid, entry), "hard_close"
    last = life.marks[-1]
    return _bid_return_pct(last.bid, entry), last.reason or "session_end"


POLICIES: dict[str, Callable[[Lifecycle], PolicyResult]] = {
    "baseline_current": lambda l: _policy_ratchet(l, arm_pct=25.0, giveback_pct=10.0, stop_pct=30.0),
    "stop30_target75": lambda l: _policy_fixed(l, stop_pct=30.0, target_pct=75.0),
    "stop20_target50": lambda l: _policy_fixed(l, stop_pct=20.0, target_pct=50.0),
    "stop50_target100": lambda l: _policy_fixed(l, stop_pct=50.0, target_pct=100.0),
    "stop30_target50": lambda l: _policy_fixed(l, stop_pct=30.0, target_pct=50.0),
    "no_stop_target50": lambda l: _policy_fixed(l, stop_pct=None, target_pct=50.0),
    "no_target_ratchet_40_15": lambda l: _policy_ratchet(l, arm_pct=40.0, giveback_pct=15.0, stop_pct=30.0),
    "no_target_ratchet_50_20": lambda l: _policy_ratchet(l, arm_pct=50.0, giveback_pct=20.0, stop_pct=30.0),
    "time_stop_30m": lambda l: _policy_time_stop(l, minutes=30),
    "time_stop_60m": lambda l: _policy_time_stop(l, minutes=60),
}


def _cohort_metrics(returns: list[float], fee_pct: float = 0.0) -> dict[str, Any]:
    adjusted = [r - fee_pct for r in returns]
    if not adjusted:
        return {"n": 0}
    wins = [r for r in adjusted if r > 0]
    losses = [r for r in adjusted if r <= 0]
    gross_win = sum(wins)
    gross_loss = -sum(losses)
    pf = round(gross_win / gross_loss, 3) if gross_loss > 0 else None
    expectancy = round(sum(adjusted) / len(adjusted), 3)
    # equity curve max drawdown in pct-additive space
    equity = 0.0
    peak = 0.0
    max_dd = 0.0
    for r in adjusted:
        equity += r
        peak = max(peak, equity)
        max_dd = min(max_dd, equity - peak)
    return {
        "n": len(adjusted),
        "win_rate": round(len(wins) / len(adjusted), 3),
        "expectancy_pct": expectancy,
        "profit_factor": pf,
        "max_dd_pct": round(max_dd, 3),
        "avg_win_pct": round(sum(wins) / len(wins), 3) if wins else 0.0,
        "avg_loss_pct": round(sum(losses) / len(losses), 3) if losses else 0.0,
        "gross_pct": round(sum(adjusted), 3),
    }


def _top_pct_removed(returns: list[float], drop_pct: float) -> list[float]:
    if not returns:
        return []
    k = max(1, int(len(returns) * drop_pct / 100.0))
    return sorted(returns)[:-k] if k < len(returns) else []


def _chronological_split(
    lives: list[Lifecycle], holdout_fraction: float
) -> tuple[list[Lifecycle], list[Lifecycle]]:
    dated = sorted(lives, key=lambda l: l.date)
    dates = sorted({l.date for l in dated if l.date})
    if len(dates) < 5:
        return dated, []
    cutoff_idx = int(len(dates) * (1.0 - holdout_fraction))
    cutoff = dates[cutoff_idx]
    train = [l for l in dated if l.date < cutoff]
    holdout = [l for l in dated if l.date >= cutoff]
    return train, holdout


def evaluate_policy(
    name: str, fn: Callable[[Lifecycle], PolicyResult], lives: list[Lifecycle],
    fee_pct: float,
) -> dict[str, Any]:
    results = [fn(l) for l in lives]
    returns = [r for r, _ in results]
    reasons = defaultdict(int)
    for _, reason in results:
        reasons[reason] += 1

    baseline = _cohort_metrics(returns, fee_pct=0.0)
    doubled_cost = _cohort_metrics(returns, fee_pct=fee_pct * 2.0)
    with_fee = _cohort_metrics(returns, fee_pct=fee_pct)
    top5_removed = _cohort_metrics(_top_pct_removed(returns, 5.0), fee_pct=fee_pct)

    # per-regime split
    regime_returns: dict[str, list[float]] = defaultdict(list)
    for life, (ret, _) in zip(lives, results):
        regime_returns[life.day_type].append(ret)
    per_regime = {k: _cohort_metrics(v, fee_pct=fee_pct) for k, v in regime_returns.items()}

    return {
        "policy": name,
        "sample_size": len(returns),
        "unique_dates": len({l.date for l in lives if l.date}),
        "baseline_pre_fee": baseline,
        "post_fee": with_fee,
        "doubled_cost": doubled_cost,
        "top5_removed_post_fee": top5_removed,
        "per_regime_post_fee": per_regime,
        "exit_reason_counts": dict(reasons),
    }


def review_gate_verdict(policy_report: dict[str, Any]) -> dict[str, Any]:
    n = int(policy_report["sample_size"])
    d = int(policy_report["unique_dates"])
    exp_post_fee = policy_report["post_fee"].get("expectancy_pct")
    exp_doubled = policy_report["doubled_cost"].get("expectancy_pct")
    exp_top5 = policy_report["top5_removed_post_fee"].get("expectancy_pct")
    failed = []
    if n < MIN_SAMPLES_FOR_REVIEW:
        failed.append(f"insufficient_samples_{n}/{MIN_SAMPLES_FOR_REVIEW}")
    if d < MIN_DATES_FOR_REVIEW:
        failed.append(f"insufficient_dates_{d}/{MIN_DATES_FOR_REVIEW}")
    if exp_post_fee is None or exp_post_fee <= 0:
        failed.append("post_fee_expectancy_not_positive")
    if exp_doubled is None or exp_doubled <= 0:
        failed.append("doubled_cost_expectancy_not_positive")
    if exp_top5 is None or exp_top5 <= 0:
        failed.append("top5_removed_expectancy_not_positive")
    return {
        "passed": not failed,
        "failed_checks": failed,
        "minimum_samples": MIN_SAMPLES_FOR_REVIEW,
        "minimum_dates": MIN_DATES_FOR_REVIEW,
    }


def build_report(
    candidates_path: Path = DEFAULT_CANDIDATES_PATH,
    holdout_fraction: float = DEFAULT_HOLDOUT_FRACTION,
    fee_pct: float = DEFAULT_FEE_PER_CONTRACT_PCT,
) -> dict[str, Any]:
    lives = load_lifecycles(candidates_path)
    train, holdout = _chronological_split(lives, holdout_fraction)
    policy_rows_train: list[dict[str, Any]] = []
    policy_rows_holdout: list[dict[str, Any]] = []
    for name, fn in POLICIES.items():
        train_report = evaluate_policy(name, fn, train, fee_pct)
        train_report["review_gate"] = review_gate_verdict(train_report)
        policy_rows_train.append(train_report)
        if holdout:
            hold_report = evaluate_policy(name, fn, holdout, fee_pct)
            hold_report["review_gate"] = review_gate_verdict(hold_report)
            policy_rows_holdout.append(hold_report)
    # rank by post-fee train expectancy (advisory only)
    policy_rows_train.sort(
        key=lambda r: (r["post_fee"].get("expectancy_pct") or float("-inf")), reverse=True
    )
    return {
        "provider": "options_exit_policy_lab",
        "mode": "read_only_bid_based_replay",
        "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "execution_enabled": False,
        "can_submit_orders": False,
        "automatic_parameter_changes": False,
        "candidates_path": str(candidates_path),
        "total_lifecycles": len(lives),
        "train_lifecycles": len(train),
        "holdout_lifecycles": len(holdout),
        "holdout_fraction": holdout_fraction,
        "fee_pct_per_trade": fee_pct,
        "min_samples_for_review": MIN_SAMPLES_FOR_REVIEW,
        "min_dates_for_review": MIN_DATES_FOR_REVIEW,
        "policies_train_ranked": policy_rows_train,
        "policies_holdout": policy_rows_holdout,
        "promotion_authority": "shadow_challenger_only",
        "notes": (
            "Ranking is advisory. Do not promote a policy unless holdout passes "
            "the review gate AND survives regime and doubled-cost checks. Never "
            "tune on the holdout."
        ),
    }


def write_report(report: dict[str, Any], out_path: Path = DEFAULT_OUTPUT_PATH) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = out_path.with_suffix(out_path.suffix + ".tmp")
    tmp.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(tmp, out_path)


def _summary_table(report: dict[str, Any]) -> str:
    rows = report.get("policies_train_ranked", [])
    header = f"{'policy':<25} {'n':>5} {'d':>4} {'exp%':>8} {'exp2×%':>8} {'top5%':>8} {'WR':>6} {'PF':>6}"
    lines = [header, "-" * len(header)]
    for r in rows:
        pf = r["post_fee"].get("profit_factor")
        pf_s = f"{pf:.2f}" if pf is not None else "n/a"
        lines.append(
            f"{r['policy']:<25} {r['sample_size']:>5} {r['unique_dates']:>4} "
            f"{r['post_fee'].get('expectancy_pct',0):>8.2f} "
            f"{r['doubled_cost'].get('expectancy_pct',0):>8.2f} "
            f"{r['top5_removed_post_fee'].get('expectancy_pct',0):>8.2f} "
            f"{r['post_fee'].get('win_rate',0):>6.2%} {pf_s:>6}"
        )
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidates", type=Path, default=DEFAULT_CANDIDATES_PATH)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUTPUT_PATH)
    parser.add_argument("--holdout", type=float, default=DEFAULT_HOLDOUT_FRACTION)
    parser.add_argument("--fee-pct", type=float, default=DEFAULT_FEE_PER_CONTRACT_PCT)
    parser.add_argument("--print", action="store_true", dest="do_print")
    args = parser.parse_args()
    report = build_report(
        candidates_path=args.candidates,
        holdout_fraction=args.holdout,
        fee_pct=args.fee_pct,
    )
    write_report(report, args.out)
    if args.do_print:
        print(_summary_table(report))
        print(f"\nreport: {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

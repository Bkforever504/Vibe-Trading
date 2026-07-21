#!/usr/bin/env python3
"""Build a fail-closed adversarial manifest from active forward shadow evidence."""
from __future__ import annotations

import argparse
import json
import os
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts import accelerated_bot_learning_report as accelerated
from scripts import flip_shadow_pnl_evaluator as evaluator

VIBE_HOME = Path.home() / ".vibe-trading"
PLAN_PATH = ROOT / "research" / "edge_trials" / "fresh_orb_retest_forward_plan_2026-07-20.json"
SHADOW_PATH = ROOT / "data" / "flip_shadow_candidates_log.jsonl"
MANIFEST_PATH = VIBE_HOME / "adversarial-manifests" / "fresh-orb-retest-options.json"
REPORT_PATH = VIBE_HOME / "reports" / "active-trial-manifest-builder.json"
ATTEMPT_INVENTORY_PATH = ROOT / "research" / "attempted_trial_inventory_2026-07-20.json"


def _read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def _session(bucket: str) -> str:
    try:
        hour, minute = (int(value) for value in bucket.split(":", 1))
        total = hour * 60 + minute
    except (TypeError, ValueError):
        return "unknown"
    return "opening" if total < 10 * 60 + 30 else "midday" if total < 12 * 60 + 30 else "late"


def _fresh_delayed_trials(shadow_path: Path) -> list[dict[str, Any]]:
    raw = evaluator._read_jsonl(shadow_path)
    groups: dict[tuple[str, ...], list[dict[str, Any]]] = defaultdict(list)
    for row in raw:
        if (
            int(row.get("schema_version") or 0) >= 3
            and row.get("data_quality") == "current_session_lifecycle"
            and row.get("execution_mode") == "shadow_only"
            and row.get("symbol")
            and row.get("option_symbol")
        ):
            groups[evaluator._row_key(row)].append(row)
    outcomes = {row["lifecycle_id"]: row for row in accelerated._shadow_trades(shadow_path)}
    trials = []
    for group in groups.values():
        ordered = sorted(group, key=lambda row: str(row.get("scanned_at") or ""))
        entry = next((row for row in ordered if row.get("action") == "enter_shadow"), None)
        if not entry:
            continue
        features = entry.get("feature_snapshot") if isinstance(entry.get("feature_snapshot"), dict) else {}
        if not (
            features.get("orb_entry_pattern") == "breakout_retest"
            and features.get("orb_retest_status") == "retest_confirmed_fresh"
        ):
            continue
        lifecycle_id = "|".join(
            str(entry.get(key) or "") for key in ("date", "symbol", "right", "strategy", "episode_bucket_et")
        )
        outcome = outcomes.get(lifecycle_id)
        delayed = next(
            (
                row for row in ordered
                if str(row.get("scanned_at") or "") > str(entry.get("scanned_at") or "")
                and row.get("selection_ask") not in (None, "")
            ),
            None,
        )
        if not outcome or not delayed or outcome.get("executable_exit_bid") in (None, ""):
            continue
        delayed_ask = float(delayed["selection_ask"])
        delayed_bid = float(delayed.get("selection_bid") or delayed_ask)
        exit_bid = float(outcome["executable_exit_bid"])
        if delayed_ask <= 0:
            continue
        net_return = exit_bid / delayed_ask - 1.0
        extra_spread_cost = max(0.0, delayed_ask - delayed_bid) / delayed_ask
        trials.append({
            "lifecycle_id": lifecycle_id,
            "date": str(entry.get("date") or ""),
            "entry_seen_at": entry.get("scanned_at"),
            "delayed_entry_seen_at": delayed.get("scanned_at"),
            "symbol": entry.get("symbol"),
            "right": entry.get("right"),
            "session": _session(str(entry.get("episode_bucket_et") or "")),
            "retest_age_bars": features.get("orb_retest_age_bars"),
            "return": net_return,
            "cost_2x_return": net_return - extra_spread_cost,
            "cost_3x_return": net_return - 2 * extra_spread_cost,
        })
    return sorted(trials, key=lambda row: (row["date"], str(row["entry_seen_at"] or ""), row["lifecycle_id"]))


def _returns(rows: list[dict[str, Any]], key: str = "return") -> list[float]:
    return [round(float(row[key]), 8) for row in rows]


def build_manifest(plan_path: Path = PLAN_PATH, shadow_path: Path = SHADOW_PATH) -> tuple[dict[str, Any], dict[str, Any]]:
    plan = _read_json(plan_path)
    inventory = _read_json(ATTEMPT_INVENTORY_PATH)
    trials = _fresh_delayed_trials(shadow_path)
    start, end = str(plan.get("oos_start") or ""), str(plan.get("oos_end") or "9999-12-31")
    consumed = [row for row in trials if row["date"] < start]
    oos = [row for row in trials if start <= row["date"] <= end]
    validation, forward = oos[:30], oos[30:]
    neighbors = []
    for maximum_age in (5, 8, 12, 15, 20):
        eligible = [row for row in forward if row.get("retest_age_bars") is not None and float(row["retest_age_bars"]) <= maximum_age]
        neighbors.append({"parameters": {"maximum_retest_age_bars": maximum_age}, "returns": _returns(eligible)})
    regimes = {
        name: _returns([row for row in forward if row["session"] == name])
        for name in ("opening", "midday", "late")
    }
    fold_size = max(1, len(forward) // 5) if forward else 1
    folds = [
        {"fold": pos + 1, "returns": _returns(forward[pos * fold_size:(pos + 1) * fold_size])}
        for pos in range(5)
    ]
    timestamp_passed = bool(oos) and all(
        str(row.get("delayed_entry_seen_at") or "") > str(row.get("entry_seen_at") or "") for row in oos
    )
    manifest = {
        "subject_id": "fresh-orb-retest-options",
        "strategy_version": "fresh-orb-retest-forward-v1",
        "builder_id": "learning-loop-manifest-builder-v1",
        "reviewer_id": "adversarial-strategy-audit-v1",
        "preregistered": plan.get("created_before_oos_start") is True,
        "execution_delay_bars": 1,
        "operation_count": 12,
        "trials_considered": max(1, int(inventory.get("documented_minimum_attempt_count") or 1)),
        "timestamp_audit": {
            "passed": timestamp_passed,
            "evidence": "first subsequent observed executable ask is strictly after the signal observation",
        },
        "backtest_forward_parity": {
            "passed": False,
            "evidence": "No independent historical replay using the same one-observation delay exists yet.",
        },
        "returns": {
            "final": _returns(validation),
            "forward": _returns(forward),
            "cost_2x": _returns(forward, "cost_2x_return"),
            "cost_3x": _returns(forward, "cost_3x_return"),
        },
        "parameter_neighbors": neighbors,
        "regimes": regimes,
        "walk_forward_folds": folds,
        "evidence_partition": {
            "development_consumed_before_oos": len(consumed),
            "validation_first_30_oos": len(validation),
            "forward_after_first_30_oos": len(forward),
            "distinct_oos_days": len({row["date"] for row in oos}),
            "instant_signal_quotes_excluded": True,
            "return_basis": "first_subsequent_ask_to_frozen_exit_bid",
        },
        "execution_enabled": False,
        "can_submit_orders": False,
    }
    consumed_returns = _returns(consumed)
    report = {
        "provider": "active_trial_manifest_builder",
        "plan_id": plan.get("plan_id"),
        "subject_id": manifest["subject_id"],
        "manifest_path": str(MANIFEST_PATH),
        "execution_enabled": False,
        "can_submit_orders": False,
        "consumed_context": {
            "completed_count": len(consumed_returns),
            "delayed_entry_expectancy_return_pct": (
                round(sum(consumed_returns) / len(consumed_returns) * 100, 3) if consumed_returns else None
            ),
        },
        "oos": manifest["evidence_partition"],
        "multiple_testing_trials_considered": manifest["trials_considered"],
        "ready_for_adversarial_pass": len(validation) >= 30 and len(forward) >= 30,
        "warnings": [
            "The manifest fails closed until validation and later forward partitions each contain 30 outcomes.",
            "Consumed pre-OOS context is reported but excluded from audit return arrays.",
            "Backtest-forward parity remains false until an independent delayed-entry replay exists.",
        ],
    }
    return manifest, report


def _atomic_write(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(temp, path)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan-path", type=Path, default=PLAN_PATH)
    parser.add_argument("--shadow-path", type=Path, default=SHADOW_PATH)
    parser.add_argument("--manifest-path", type=Path, default=MANIFEST_PATH)
    parser.add_argument("--report-path", type=Path, default=REPORT_PATH)
    parser.add_argument("--print", action="store_true", dest="do_print")
    args = parser.parse_args()
    manifest, report = build_manifest(args.plan_path, args.shadow_path)
    _atomic_write(args.manifest_path, manifest)
    report["manifest_path"] = str(args.manifest_path)
    _atomic_write(args.report_path, report)
    if args.do_print:
        print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Persist the daily read-only trade board for later outcome review.

The snapshot is evidence, not execution authority. Re-running with the same
decision date and plan set is idempotent so a dashboard refresh cannot inflate
the review sample.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.live_trading_cockpit import REPORT_DIR, build_cockpit


DEFAULT_OUT = REPORT_DIR / "daily-trade-plan.json"
DEFAULT_LEDGER = ROOT / "data" / "daily_trade_plan_log.jsonl"


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            value = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            rows.append(value)
    return rows


def build_snapshot(cockpit: dict[str, Any], *, now: datetime | None = None) -> dict[str, Any]:
    now = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    board = cockpit.get("trade_board") if isinstance(cockpit.get("trade_board"), dict) else {}
    plans = [
        row
        for lane in ("stocks", "options", "futures")
        for row in (board.get(lane) or [])
        if isinstance(row, dict)
    ]
    plan_states = sorted(
        f"{row.get('plan_id')}:{row.get('actionability', row.get('lane', 'unknown'))}"
        for row in plans
        if row.get("plan_id")
    )
    identity = "|".join([now.date().isoformat(), *plan_states])
    snapshot_id = hashlib.sha256(identity.encode("utf-8")).hexdigest()[:20]
    return {
        "schema_version": 2,
        "snapshot_id": snapshot_id,
        "decision_date": now.date().isoformat(),
        "captured_at": now.isoformat(),
        "mode": "read_only_decision_support",
        "authority": cockpit.get("authority", {}),
        "headline": cockpit.get("headline", {}),
        "market": cockpit.get("market", {}),
        "score_definition": board.get("score_definition"),
        "probability_policy": board.get("probability_policy"),
        "plans": plans,
        "shadow_protocol": {
            "capture_rule": "append_once_per_distinct_daily_plan_state_set",
            "entry_rule": "mark_triggered_only_after_completed_bar_confirmation_and_fresh_quote",
            "late_rule": "do_not_shadow_when_less_than_1.25R_remains_or_half_the_path_is_consumed",
            "review_rule": "record MFE, MAE, outcome in R, and whether waiting or no-chase was correct",
            "execution_enabled": False,
            "can_submit_orders": False,
        },
        "review_template": {
            "taken": None,
            "triggered": None,
            "entry_fill": None,
            "max_favorable_excursion": None,
            "max_adverse_excursion": None,
            "exit_fill": None,
            "outcome_r": None,
            "decision_was_correct": None,
            "counterfactual_outcome_r": None,
            "lesson": None,
        },
    }


def persist_snapshot(snapshot: dict[str, Any], *, out: Path, ledger: Path) -> bool:
    out.parent.mkdir(parents=True, exist_ok=True)
    ledger.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(snapshot, indent=2, default=str) + "\n", encoding="utf-8")
    existing = {str(row.get("snapshot_id")) for row in _read_jsonl(ledger)}
    if str(snapshot.get("snapshot_id")) in existing:
        return False
    with ledger.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(snapshot, separators=(",", ":"), default=str) + "\n")
    return True


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report-dir", type=Path, default=REPORT_DIR)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--ledger", type=Path, default=DEFAULT_LEDGER)
    args = parser.parse_args()

    snapshot = build_snapshot(build_cockpit(report_dir=args.report_dir))
    appended = persist_snapshot(snapshot, out=args.out, ledger=args.ledger)
    print(json.dumps({
        "status": "ok",
        "snapshot_id": snapshot["snapshot_id"],
        "decision_date": snapshot["decision_date"],
        "plan_count": len(snapshot["plans"]),
        "ledger_appended": appended,
        "execution_enabled": False,
        "can_submit_orders": False,
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

from __future__ import annotations

import json
from datetime import datetime, timezone

from scripts.daily_trade_plan_snapshot import build_snapshot, persist_snapshot


NOW = datetime(2026, 8, 20, 14, 45, tzinfo=timezone.utc)


def test_snapshot_is_read_only_and_idempotent(tmp_path) -> None:
    cockpit = {
        "authority": {"execution_enabled": False, "can_submit_orders": False},
        "headline": {"state": "no_eligible_setup"},
        "market": {"classification": "mixed"},
        "trade_board": {
            "score_definition": "quality, not probability",
            "probability_policy": "calibrated only",
            "stocks": [{"plan_id": "stock-1", "symbol": "NVDA"}],
            "options": [{"plan_id": "option-1", "symbol": "SPY"}],
            "futures": [],
        },
    }
    snapshot = build_snapshot(cockpit, now=NOW)
    out = tmp_path / "latest.json"
    ledger = tmp_path / "ledger.jsonl"

    assert persist_snapshot(snapshot, out=out, ledger=ledger) is True
    assert persist_snapshot(snapshot, out=out, ledger=ledger) is False
    rows = [json.loads(line) for line in ledger.read_text(encoding="utf-8").splitlines()]

    assert len(rows) == 1
    assert rows[0]["authority"]["can_submit_orders"] is False
    assert rows[0]["review_template"]["outcome_r"] is None
    assert rows[0]["shadow_protocol"]["can_submit_orders"] is False
    assert len(rows[0]["plans"]) == 2

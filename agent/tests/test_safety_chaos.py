from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from scripts.live_trading_cockpit import build_cockpit
from strategies.order_envelope import OrderIntent, evaluate_order_intent


NOW = datetime(2026, 8, 22, 15, 0, tzinfo=timezone.utc)


def test_malformed_and_missing_reports_fail_closed(tmp_path: Path) -> None:
    (tmp_path / "trade-signal-generator.json").write_text("{malformed", encoding="utf-8")

    cockpit = build_cockpit(report_dir=tmp_path, now=NOW)

    assert cockpit["command_card"]["state"] == "STAND_ASIDE"
    assert cockpit["headline"]["best_setup"] is None
    assert cockpit["authority"]["execution_enabled"] is False
    assert cockpit["authority"]["can_submit_orders"] is False


def test_stale_candidate_is_quarantined_from_favorable_state(tmp_path: Path) -> None:
    report = {
        "generated_at": "2026-08-19T15:00:00Z",
        "signals": [{"symbol": "SPY", "setup": "break_retest", "direction": "bullish", "paper_consumable": True, "blockers": [], "entry": 600, "stop": 598, "targets": [{"price": 604}], "reward_risk": 2}],
    }
    (tmp_path / "trade-signal-generator.json").write_text(json.dumps(report), encoding="utf-8")

    cockpit = build_cockpit(report_dir=tmp_path, now=NOW)
    candidate = next(row for row in cockpit["candidates"] if row["symbol"] == "SPY")

    assert candidate["actionability"] == "research_only"
    assert "source_older_than_24h_or_missing" in candidate["blockers"]
    assert candidate["probability"]["ranking_eligible"] is False
    assert cockpit["command_card"]["state"] == "STAND_ASIDE"


def test_quote_gap_and_kill_switch_cannot_become_order_permission(tmp_path: Path) -> None:
    kill_switch = tmp_path / "MANUAL_RESET_REQUIRED.json"
    kill_switch.write_text("{}", encoding="utf-8")
    decision = evaluate_order_intent(
        OrderIntent("lane-a", "SPY", "2026-08-22T15:01:00Z", "2026-08-22T15:00:00Z", freshness="quote_gap"),
        kill_switch_file=kill_switch,
        reconciliation_log=tmp_path / "reconciliation.jsonl",
    )
    assert decision["allowed"] is False
    assert decision["submitted"] is False
    assert {"stale_freshness", "kill_switch_red"} <= set(decision["blockers"])

from __future__ import annotations

import json
from datetime import datetime, timezone

from scripts.flip_decision_missed_banger_review import build_report, evaluate_decision


def _bars() -> list[dict]:
    return [
        {"ts": datetime(2026, 7, 14, 15, 0, tzinfo=timezone.utc), "open": 600.0, "high": 600.2, "low": 599.8, "close": 600.0},
        {"ts": datetime(2026, 7, 14, 15, 30, tzinfo=timezone.utc), "open": 600.0, "high": 604.0, "low": 599.0, "close": 603.0},
        {"ts": datetime(2026, 7, 14, 16, 0, tzinfo=timezone.utc), "open": 603.0, "high": 603.5, "low": 602.0, "close": 603.0},
    ]


def test_evaluate_bull_skip_uses_forward_underlying_path() -> None:
    row = {"ts": "2026-07-14T15:00:00Z", "symbol": "SPY", "strategy": "bull_trend", "action": "skip", "reason": "breadth_not_confirmed", "details": {}}
    result = evaluate_decision(row, _bars())
    assert result["outcome_status"] == "observed"
    assert result["direction"] == "bull"
    assert result["max_favorable_underlying_pct"] > 0.5
    assert result["is_missed_banger_proxy"] is True


def test_unknown_historical_direction_is_not_inferred() -> None:
    row = {"ts": "2026-07-14T15:00:00Z", "symbol": "SPY", "strategy": "0dte", "action": "blocked", "reason": "shadow_consensus_block", "details": {"blockers": ["market_force_unclear"]}}
    assert evaluate_decision(row, _bars())["outcome_status"] == "direction_unavailable"


def test_build_report_is_read_only_and_attributes_reason(tmp_path) -> None:
    decisions = tmp_path / "decisions.jsonl"
    decisions.write_text(json.dumps({"ts": "2026-07-14T15:00:00Z", "symbol": "SPY", "strategy": "bear_trend", "action": "skip", "reason": "score_below_minimum", "details": {}}) + "\n", encoding="utf-8")

    report = build_report(
        decision_log=decisions,
        now=datetime(2026, 7, 14, 20, tzinfo=timezone.utc),
        fetcher=lambda symbol, start, end: _bars(),
    )
    assert report["execution_enabled"] is False
    assert report["can_submit_orders"] is False
    assert report["observed_count"] == 1
    assert report["by_reason"]["score_below_minimum"]["trading_days"] == 1

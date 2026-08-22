from __future__ import annotations

import json
from datetime import datetime, timezone

import pandas as pd

from strategies.fibonacci_shadow_journal import record_plan, resolve_plans


def _analysis() -> dict:
    return {
        "as_of": "2026-08-17T10:00:00-04:00",
        "direction": "bullish",
        "anchor_start": {"timestamp": "2026-08-17T09:30:00-04:00"},
        "anchor_end": {"timestamp": "2026-08-17T09:50:00-04:00"},
        "execution_plan": {
            "status": "eligible_shadow",
            "entry_reference": 100.0,
            "stop_reference": 99.0,
            "target_reference": 102.0,
            "order_ttl_completed_bars": 3,
        },
    }


def test_record_is_deduplicated_and_has_no_execution_authority(tmp_path) -> None:
    path = tmp_path / "plans.json"
    setup = {"symbol": "SPY", "strategy": "bull_trend"}
    first = record_plan(setup, _analysis(), path=path, now=datetime(2026, 8, 17, tzinfo=timezone.utc))
    second = record_plan(setup, _analysis(), path=path)
    rows = json.loads(path.read_text(encoding="utf-8"))

    assert first == second
    assert len(rows) == 1
    assert rows[0]["can_submit_orders"] is False


def test_resolver_scores_target_after_limit_fill(tmp_path, monkeypatch) -> None:
    path = tmp_path / "plans.json"
    report_path = tmp_path / "report.json"
    record_plan({"symbol": "SPY", "strategy": "bull_trend"}, _analysis(), path=path)
    index = pd.date_range("2026-08-17 10:05", periods=3, freq="5min", tz="America/New_York")
    frame = pd.DataFrame(
        {
            "Open": [100.4, 100.5, 101.2],
            "High": [100.6, 101.4, 102.1],
            "Low": [99.9, 100.3, 101.0],
            "Close": [100.3, 101.2, 102.0],
        },
        index=index,
    )

    report = resolve_plans({"SPY": frame}, path=path, report_path=report_path)
    rows = json.loads(path.read_text(encoding="utf-8"))

    assert rows[0]["status"] == "resolved_target"
    assert rows[0]["r_multiple"] == 2.0
    assert report["resolved_fill_count"] == 1
    assert report["promotion_gate"]["passed"] is False


def test_same_bar_ambiguity_is_not_scored(tmp_path) -> None:
    path = tmp_path / "plans.json"
    report_path = tmp_path / "report.json"
    record_plan({"symbol": "SPY", "strategy": "bull_trend"}, _analysis(), path=path)
    index = pd.date_range("2026-08-17 10:05", periods=1, freq="5min", tz="America/New_York")
    frame = pd.DataFrame(
        {"Open": [100.0], "High": [102.1], "Low": [98.9], "Close": [100.5]},
        index=index,
    )

    report = resolve_plans({"SPY": frame}, path=path, report_path=report_path)

    assert report["resolved_fill_count"] == 0
    assert report["status_counts"]["ambiguous_same_bar"] == 1

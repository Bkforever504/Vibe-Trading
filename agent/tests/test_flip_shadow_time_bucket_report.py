from __future__ import annotations

import json
from pathlib import Path

from scripts import flip_shadow_time_bucket_report as report


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    path.write_text("\n".join(json.dumps(row) for row in rows) + "\n", encoding="utf-8")


def _row(
    lifecycle: str,
    bucket: str,
    price: float,
    *,
    event: str = "shadow_mark",
    strategy: str = "0dte",
) -> dict:
    return {
        "schema_version": 3,
        "data_quality": "current_session_lifecycle",
        "execution_mode": "shadow_only",
        "lifecycle_id": lifecycle,
        "event_type": event,
        "date": "2026-07-14",
        "episode_bucket_et": bucket,
        "symbol": "SPY",
        "right": "CALL",
        "strategy": strategy,
        "option_symbol": f"{lifecycle}C",
        "entry_price_est": price,
        "selection_ask": price,
        "selection_bid": price,
        "contracts": 1,
        "scanned_at": f"2026-07-14T{bucket}:00Z",
    }


def test_time_bucket_report_ranks_completed_shadow_lifecycles(tmp_path: Path) -> None:
    source = tmp_path / "shadow.jsonl"
    rows = []
    for index in range(10):
        rows.extend([
            _row(f"win-{index}", "12:00", 1.0),
            _row(f"win-{index}", "12:00", 1.9, event="shadow_exit"),
        ])
    for index in range(10):
        rows.extend([
            _row(f"loss-{index}", "13:30", 1.0),
            _row(f"loss-{index}", "13:30", 0.8, event="shadow_exit"),
        ])
    _write_jsonl(source, rows)

    built = report.build_report(source)

    assert built["execution_enabled"] is False
    assert built["can_submit_orders"] is False
    assert built["completed_lifecycle_count"] == 20
    assert built["best_buckets"][0]["bucket_et"] == "12:00"
    assert built["best_buckets"][0]["shadow_selector_rank"] == 1
    assert built["best_buckets"][0]["sample_status"] == "shadow_rank_only"
    assert built["best_buckets"][0]["live_gate_eligible"] is False
    assert built["weak_buckets"][0]["bucket_et"] == "13:30"
    assert built["time_gate_authority"] == "none"


def test_time_bucket_report_isolates_research_challengers(tmp_path: Path) -> None:
    source = tmp_path / "shadow.jsonl"
    rows = [
        _row("primary", "12:00", 1.0),
        _row("primary", "12:00", 0.7, event="shadow_exit"),
        _row("research", "12:00", 1.0, strategy="orb_15m_retest"),
        _row("research", "12:00", 2.0, event="shadow_exit", strategy="orb_15m_retest"),
    ]
    _write_jsonl(source, rows)

    built = report.build_report(source)

    assert built["completed_lifecycle_count"] == 1
    assert built["research_completed_lifecycle_count"] == 1
    assert built["buckets"][0]["expectancy_return_pct"] == -30.0
    assert built["research_strategy_results"][0]["strategy"] == "orb_15m_retest"
    assert built["research_strategy_results"][0]["expectancy_return_pct"] == 100.0

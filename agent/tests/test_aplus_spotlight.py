from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from scripts import aplus_spotlight as spotlight


ET = ZoneInfo("America/New_York")


def _candidate(**overrides):
    row = {
        "symbol": "CRM",
        "grade": "A",
        "score": 94.0,
        "ranking_score": 101.0,
        "actionable_for_ranking": True,
        "confirmation_stage": "completed_5m_confirmed",
        "direction": "bullish",
        "setup": "opening_range_breakout",
        "price_action_confirmation": {
            "state": "bullish_confirmed",
            "bar_completed_at": "2026-08-27T14:00:00Z",
        },
        "trade_levels": {
            "confirmation_trigger": 250.0,
            "invalidation": 249.0,
            "target_2r": 252.0,
        },
        "remaining_opportunity": {"status": "confirmed_review"},
    }
    row.update(overrides)
    return row


def _write_snapshot(path: Path, as_of_et: str, candidates: list[dict]) -> None:
    path.write_text(
        json.dumps({"as_of_et": as_of_et, "actionable_ranked_candidates": candidates}) + "\n",
        encoding="utf-8",
    )


def test_collect_ignores_stale_intraday_setups(tmp_path: Path) -> None:
    radar = tmp_path / "radar.jsonl"
    _write_snapshot(radar, "2026-08-27T10:00:00-04:00", [_candidate()])

    rows = spotlight.collect_fresh_aplus(
        radar,
        now=datetime(2026, 8, 27, 10, 30, tzinfo=ET),
        max_age_minutes=15,
    )

    assert rows == []


def test_collect_requires_complete_directional_geometry(tmp_path: Path) -> None:
    radar = tmp_path / "radar.jsonl"
    invalid = _candidate(
        trade_levels={
            "confirmation_trigger": 250.0,
            "invalidation": 251.0,
            "target_2r": 252.0,
        }
    )
    _write_snapshot(radar, "2026-08-27T10:00:00-04:00", [invalid])

    rows = spotlight.collect_fresh_aplus(
        radar,
        now=datetime(2026, 8, 27, 10, 5, tzinfo=ET),
        max_age_minutes=15,
    )

    assert rows == []


def test_collect_deduplicates_repeated_snapshot_of_same_setup(tmp_path: Path) -> None:
    radar = tmp_path / "radar.jsonl"
    candidate = _candidate()
    radar.write_text(
        "\n".join(
            [
                json.dumps({"as_of_et": "2026-08-27T10:00:00-04:00", "rows": [candidate]}),
                json.dumps({"as_of_et": "2026-08-27T10:05:00-04:00", "rows": [candidate]}),
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    rows = spotlight.collect_fresh_aplus(
        radar,
        now=datetime(2026, 8, 27, 10, 6, tzinfo=ET),
        max_age_minutes=15,
    )

    assert len(rows) == 1
    assert rows[0]["as_of"] == "2026-08-27T10:05:00-04:00"


def test_successful_fingerprints_only_returns_delivered_alerts(monkeypatch) -> None:
    setups = [
        {"fingerprint": "one", "symbol": "CRM"},
        {"fingerprint": "two", "symbol": "CRWD"},
    ]
    result = {
        "results": [
            {"fingerprint": "one", "symbol": "CRM", "result": {"sent": True}},
            {"fingerprint": "two", "symbol": "CRWD", "result": {"sent": False}},
        ]
    }

    assert spotlight.successful_fingerprints(setups, result) == {"one"}


def test_spotlight_preserves_and_displays_market_context(tmp_path: Path) -> None:
    radar = tmp_path / "radar.jsonl"
    candidate = _candidate(market_context={
        "sector_etf": "XLK",
        "sector_alignment": "supportive",
        "qqq_vs_spy_pct": 0.42,
        "qqq_spy_regime": "qqq_leading_spy",
    })
    _write_snapshot(radar, "2026-08-27T10:00:00-04:00", [candidate])

    rows = spotlight.collect_fresh_aplus(
        radar,
        now=datetime(2026, 8, 27, 10, 5, tzinfo=ET),
        max_age_minutes=15,
    )
    fields = spotlight.format_setup_fields(rows[0])

    assert rows[0]["market_context"]["sector_etf"] == "XLK"
    context_field = next(field for field in fields if field["name"] == "Market Context")
    assert "XLK" in context_field["value"]
    assert "qqq_leading_spy" in context_field["value"]


def test_scheduler_contract_is_wake_capable_and_staggered_after_radar() -> None:
    root = Path(__file__).resolve().parents[2]
    registration = (root / "scripts" / "register_aplus_spotlight_task.ps1").read_text(encoding="utf-8")
    runner = (root / "scripts" / "run_aplus_spotlight.ps1").read_text(encoding="utf-8")

    assert "/ST 08:39" in registration
    assert "/RI 5" in registration
    assert "/DU 06:21" in registration
    assert "-WakeToRun" in registration
    assert "-MultipleInstances IgnoreNew" in registration
    assert "aplus_spotlight.py" in runner
    assert "generate_dashboard.py" in runner

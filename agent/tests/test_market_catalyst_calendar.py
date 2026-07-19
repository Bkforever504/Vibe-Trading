"""Tests for market_catalyst_calendar.py — read-only macro event veto layer."""
from __future__ import annotations

import json
import sys
from datetime import date, datetime, timezone
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "scripts"))

from market_catalyst_calendar import (
    build_report,
    events_for_date,
    risk_window_for_date,
    EVENTS_2026,
)


def test_events_2026_not_empty():
    assert len(EVENTS_2026) > 0


def test_each_event_has_required_fields():
    required = {"date", "time_et", "name", "impact", "veto_type", "source"}
    for ev in EVENTS_2026:
        missing = required - ev.keys()
        assert not missing, f"Event {ev.get('name')} missing: {missing}"


def test_cpi_july_14_is_high_impact():
    events = events_for_date(date(2026, 7, 14))
    names = [e["name"] for e in events]
    assert any("CPI" in n for n in names)
    assert any(e["impact"] == "high" for e in events)


def test_fed_minutes_july_8_marks_caution_window():
    events = events_for_date(date(2026, 7, 8))
    assert any("Fed" in e["name"] or "Minutes" in e["name"] for e in events)


def test_10y_auction_july_8_present():
    events = events_for_date(date(2026, 7, 8))
    assert any("10Y" in e["name"] or "Treasury" in e["name"] for e in events)


def test_30y_auction_july_9_present():
    events = events_for_date(date(2026, 7, 9))
    assert any("30Y" in e["name"] or "Treasury" in e["name"] for e in events)


def test_fomc_july_28_29_blocks_new_short_premium():
    for d in (date(2026, 7, 28), date(2026, 7, 29)):
        window = risk_window_for_date(d)
        assert window["max_impact"] == "high"
        assert "new_short_premium_blocked" in window["vetoes"]


def test_gdp_july_30_is_high_impact():
    events = events_for_date(date(2026, 7, 30))
    assert any("GDP" in e["name"] or "PCE" in e["name"] for e in events)


def test_no_event_day_returns_clear_window():
    window = risk_window_for_date(date(2026, 7, 11))  # Saturday, no events
    assert window["max_impact"] in ("none", "low")
    assert window["vetoes"] == []


def test_build_report_no_execution():
    report = build_report(today=date(2026, 7, 8))
    assert report["execution_enabled"] is False
    assert report["can_submit_orders"] is False
    assert report["provider"] == "market_catalyst_calendar"


def test_build_report_july_8_has_caution():
    report = build_report(today=date(2026, 7, 8))
    assert report["today"]["max_impact"] in ("medium", "high")
    assert len(report["today"]["events"]) > 0


def test_build_report_cpi_day_blocks_new_short_premium():
    report = build_report(today=date(2026, 7, 14))
    assert "new_short_premium_blocked" in report["today"]["vetoes"]


def test_build_report_includes_next_5_days():
    report = build_report(today=date(2026, 7, 8))
    assert len(report["upcoming"]) == 5


def test_allowed_playbooks_present():
    report = build_report(today=date(2026, 7, 8))
    assert "allowed_playbooks" in report["today"]
    assert isinstance(report["today"]["allowed_playbooks"], list)


def test_pre_event_window_reduces_playbooks():
    report = build_report(today=date(2026, 7, 14))  # CPI day
    playbooks = report["today"]["allowed_playbooks"]
    assert "short_premium" not in playbooks


def test_clear_day_allows_full_playbook():
    report = build_report(today=date(2026, 7, 15))  # day after CPI, no event
    playbooks = report["today"]["allowed_playbooks"]
    assert "directional_long" in playbooks or "short_premium" in playbooks


def test_fresh_dynamic_geopolitical_risk_forces_stand_aside(tmp_path: Path):
    now = datetime(2026, 7, 13, 15, 0, tzinfo=timezone.utc)
    dynamic = tmp_path / "geopolitical-risk-context.json"
    dynamic.write_text(
        json.dumps({
            "date": "2026-07-13",
            "generated_at": "2026-07-13T14:55:00Z",
            "risk_level": "high",
            "recommended_posture": "stand_aside",
            "max_evidence_score": 7,
            "vetoes": ["dynamic_geopolitical_risk", "new_short_premium_blocked"],
            "evidence": [{"headline": "Strait risk"}],
        }),
        encoding="utf-8",
    )

    report = build_report(
        today=date(2026, 7, 13),
        now=now,
        dynamic_risk_path=dynamic,
    )

    assert report["today"]["max_impact"] == "high"
    assert report["today"]["allowed_playbooks"] == ["stand_aside"]
    assert "dynamic_geopolitical_risk" in report["today"]["vetoes"]


def test_stale_dynamic_risk_is_ignored(tmp_path: Path):
    dynamic = tmp_path / "geopolitical-risk-context.json"
    dynamic.write_text(
        json.dumps({
            "date": "2026-07-13",
            "generated_at": "2026-07-13T12:00:00Z",
            "risk_level": "high",
            "vetoes": ["dynamic_geopolitical_risk"],
        }),
        encoding="utf-8",
    )
    report = build_report(
        today=date(2026, 7, 13),
        now=datetime(2026, 7, 13, 15, 0, tzinfo=timezone.utc),
        dynamic_risk_path=dynamic,
    )
    assert "dynamic_geopolitical_risk" not in report["today"]["vetoes"]

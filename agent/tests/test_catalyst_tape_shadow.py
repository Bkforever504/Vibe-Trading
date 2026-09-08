import json
import sys
from datetime import datetime, timezone

from scripts.catalyst_tape_shadow import build_report, format_shadow_card, main


NOW = datetime(2026, 9, 8, 14, 3, tzinfo=timezone.utc)


def _catalyst(**overrides):
    row = {
        "symbol": "QCOM",
        "event_type": "material_current_report",
        "source": "sec_edgar_latest_atom",
        "source_url": "https://www.sec.gov/Archives/example",
        "verification_status": "primary_index_verified",
        "event_at": "2026-09-08T14:00:00Z",
        "source_observed_at": "2026-09-08T14:00:08Z",
    }
    row.update(overrides)
    return row


def _tape(state="CONFIRMED", **overrides):
    row = {
        "symbol": "QCOM",
        "state": state,
        "direction": "LONG",
        "reason": "two_successive_completed_1m_pressure_observations",
        "transition": True,
        "data_status": "ok",
        "bar_completed_at": "2026-09-08T14:02:00Z",
        "detected_at": "2026-09-08T14:02:04Z",
    }
    row.update(overrides)
    return row


def _plan(**overrides):
    row = {
        "plan_id": "qcom-long-20260908",
        "symbol": "QCOM",
        "direction": "LONG",
        "as_of": "2026-09-08T13:59:00Z",
        "entry_zone": {"low": 174.20, "high": 174.60},
        "max_chase_price": 175.10,
        "stop": 173.60,
        "targets": [176.50, 178.00],
        "expires_at": "2026-09-08T15:00:00Z",
        "execution_enabled": False,
        "can_submit_orders": False,
    }
    row.update(overrides)
    return row


def test_verified_primary_event_and_completed_tape_create_manual_review_candidate():
    report = build_report([_catalyst()], [_tape()], [_plan()], now=NOW)
    row = report["transitions"][0]
    assert row["state"] == "CONFIRMED"
    assert row["actionability"] == "manual_review_candidate"
    assert row["actionable_for_manual_review"] is True
    assert row["event_to_bar_seconds"] == 120.0
    assert row["source_to_bar_seconds"] == 112.0
    assert row["source_to_decision_seconds"] == 116.0
    assert row["execution_enabled"] is False and row["can_submit_orders"] is False


def test_social_event_is_nomination_only_even_when_tape_confirms():
    social = _catalyst(source="x", source_url="https://x.com/example", verified=True)
    report = build_report([social], [_tape()], [_plan()], now=NOW)
    row = report["transitions"][0]
    assert row["state"] == "WATCH"
    assert row["actionability"] == "nomination_only"
    assert row["data_status"] == "unverified"
    assert row["actionable_for_manual_review"] is False
    assert row["tape"] is None
    assert "unverified_social_nomination_only" in row["catalyst"]["blockers"]


def test_point_in_time_join_rejects_tape_completed_before_source_was_observed():
    future_observation = _catalyst(source_observed_at="2026-09-08T14:02:30Z")
    report = build_report([future_observation], [_tape()], [_plan()], now=NOW)
    assert report["transitions"][0]["state"] == "WATCH"
    assert report["point_in_time_rejections"] == 1
    assert report["transitions"][0]["actionable_for_manual_review"] is False


def test_missing_or_stale_tape_fails_honestly_to_watch():
    missing = build_report([_catalyst()], [], [_plan()], now=NOW)
    stale = build_report(
        [_catalyst()],
        [_tape(bar_completed_at="2026-09-08T13:50:00Z", detected_at="2026-09-08T13:50:04Z")],
        [_plan()],
        now=NOW,
    )
    assert missing["status"] == "missing_or_invalid_tape_input"
    assert missing["transitions"][0]["state"] == "WATCH"
    assert missing["transitions"][0]["data_status"] == "unavailable"
    assert stale["status"] == "degraded"
    assert stale["transitions"][0]["state"] == "WATCH"


def test_plan_levels_are_copied_exactly_and_never_invented():
    plan = _plan()
    row = build_report([_catalyst()], [_tape()], [plan], now=NOW)["transitions"][0]
    assert row["deterministic_plan"]["entry_zone"] == plan["entry_zone"]
    assert row["deterministic_plan"]["max_chase_price"] == plan["max_chase_price"]
    assert row["deterministic_plan"]["stop"] == plan["stop"]
    assert row["deterministic_plan"]["targets"] == plan["targets"]

    no_plan = build_report([_catalyst()], [_tape()], [], now=NOW)["transitions"][0]
    assert no_plan["state"] == "CONFIRMED"
    assert no_plan["deterministic_plan"] is None
    assert no_plan["actionable_for_manual_review"] is False
    assert no_plan["blockers"] == ["deterministic_plan_missing_or_not_point_in_time"]

    incomplete = build_report([_catalyst()], [_tape()], [_plan(targets=[])], now=NOW)["transitions"][0]
    assert incomplete["deterministic_plan"]["targets"] == []
    assert incomplete["actionable_for_manual_review"] is False
    assert incomplete["blockers"] == ["deterministic_plan_levels_incomplete"]


def test_future_expired_or_execution_capable_plan_cannot_be_used():
    future = build_report([_catalyst()], [_tape()], [_plan(as_of="2026-09-08T14:02:01Z")], now=NOW)["transitions"][0]
    expired = build_report([_catalyst()], [_tape()], [_plan(expires_at="2026-09-08T14:01:59Z")], now=NOW)["transitions"][0]
    unsafe = build_report([_catalyst()], [_tape()], [_plan(execution_enabled=True)], now=NOW)["transitions"][0]
    assert future["deterministic_plan"] is None and not future["actionable_for_manual_review"]
    assert expired["blockers"] == ["deterministic_plan_expired_or_expiry_invalid"]
    assert unsafe["deterministic_plan"] is None and not unsafe["actionable_for_manual_review"]


def test_transition_id_is_stable_and_prior_id_is_not_new():
    first = build_report([_catalyst()], [_tape()], [_plan()], now=NOW)
    identity = first["transitions"][0]["transition_id"]
    second = build_report([_catalyst()], [_tape()], [_plan()], now=NOW, existing_transition_ids=[identity])
    assert second["transitions"][0]["transition_id"] == identity
    assert second["transitions"][0]["is_new"] is False
    assert second["new_transition_count"] == 0


def test_armed_and_invalidated_preserve_tape_lifecycle_without_becoming_candidates():
    armed = build_report([_catalyst()], [_tape("ARMED")], [_plan()], now=NOW)["transitions"][0]
    invalidated = build_report([_catalyst()], [_tape("INVALIDATED")], [_plan()], now=NOW)["transitions"][0]
    assert (armed["state"], armed["actionability"]) == ("ARMED", "prepare_only")
    assert (invalidated["state"], invalidated["actionability"]) == ("INVALIDATED", "stand_aside")
    assert not armed["actionable_for_manual_review"] and not invalidated["actionable_for_manual_review"]


def test_formatter_is_explicitly_shadow_manual_review():
    row = build_report([_catalyst()], [_tape()], [_plan()], now=NOW)["transitions"][0]
    card = format_shadow_card(row)
    assert "SHADOW / MANUAL REVIEW" in card
    assert "No order will be placed" in card
    assert "174.2" in card and "175.1" in card and "173.6" in card


def test_cli_generates_report_without_dispatching(monkeypatch, tmp_path):
    class FrozenDateTime(datetime):
        @classmethod
        def now(cls, tz=None):
            return NOW if tz is None else NOW.astimezone(tz)

    catalysts = tmp_path / "catalysts.json"
    tape = tmp_path / "tape.json"
    plans = tmp_path / "plans.json"
    output = tmp_path / "report.json"
    catalysts.write_text(json.dumps({"generated_at": "2026-09-08T14:00:08Z", "catalysts": [_catalyst()]}), encoding="utf-8")
    tape.write_text(json.dumps({"observations": [_tape()]}), encoding="utf-8")
    plans.write_text(json.dumps({"plans": [_plan()]}), encoding="utf-8")
    monkeypatch.setattr(
        sys,
        "argv",
        ["catalyst_tape_shadow.py", "--catalysts", str(catalysts), "--tape", str(tape), "--plans", str(plans), "--out", str(output)],
    )
    monkeypatch.setattr("scripts.catalyst_tape_shadow.datetime", FrozenDateTime)
    assert main() == 0
    report = json.loads(output.read_text(encoding="utf-8"))
    assert report["mode"] == "shadow_manual_review_only"
    assert report["transitions"][0]["actionability"] == "manual_review_candidate"
    assert report["execution_enabled"] is False and report["can_submit_orders"] is False

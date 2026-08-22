from __future__ import annotations

import json

from scripts.options_observation_journal import (
    append_observation,
    build_report,
    read_observations,
)


def _decision(status: str, reason: str) -> dict:
    return {
        "provider": "test_strategy",
        "generated_at": "2026-08-11T14:45:00+00:00",
        "status": status,
        "reason": reason,
        "details": {"gate": False},
        "execution_enabled": False,
    }


def test_blocked_run_is_append_only_evidence(tmp_path) -> None:
    path = tmp_path / "observations.jsonl"

    row = append_observation(_decision("blocked", "outside_entry_window"), path=path)

    saved = read_observations(path)
    assert saved == [row]
    assert saved[0]["orders_submitted"] == 0
    assert saved[0]["setup_available"] is False


def test_concrete_setup_is_counted_without_execution_authority(tmp_path) -> None:
    path = tmp_path / "observations.jsonl"
    setup = {
        "shadow_id": "shadow-1",
        "symbol": "SPY",
        "expiry": "2026-09-18",
        "short_symbol": "SPY260918P00700000",
        "long_symbol": "SPY260918P00695000",
        "entry_credit": 1.2,
    }

    append_observation(_decision("blocked", "volatility_edge_failed"), setup=setup, path=path)
    report = build_report(read_observations(path))

    assert report["observation_count"] == 1
    assert report["setup_available_count"] == 1
    assert report["executable_candidate_count"] == 1
    assert report["execution_enabled"] is False


def test_reingesting_same_decision_is_idempotent(tmp_path) -> None:
    path = tmp_path / "observations.jsonl"
    decision = _decision("blocked", "spread_not_priceable")

    append_observation(decision, path=path)
    append_observation(decision, path=path)

    assert len(path.read_text(encoding="utf-8").splitlines()) == 1


def test_report_separates_schedule_and_data_blockers(tmp_path) -> None:
    path = tmp_path / "observations.jsonl"
    append_observation(_decision("blocked", "outside_entry_window"), path=path)
    second = _decision("blocked", "spread_not_priceable")
    second["generated_at"] = "2026-08-12T17:00:00+00:00"
    append_observation(second, path=path)

    report = build_report(read_observations(path))

    assert report["distinct_date_count"] == 2
    assert report["schedule_blockers"] == {"outside_entry_window": 1}
    assert report["data_blockers"] == {"spread_not_priceable": 1}
    assert json.dumps(report)

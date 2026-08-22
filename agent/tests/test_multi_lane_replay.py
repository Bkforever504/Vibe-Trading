from __future__ import annotations

from datetime import datetime, timedelta, timezone

from research.multi_lane_replay import evaluate_replay


def test_multi_lane_replay_is_deterministic_and_reports_every_gate() -> None:
    start = datetime(2026, 1, 2, tzinfo=timezone.utc)
    rows = []
    for index in range(60):
        session = (start + timedelta(days=index)).date().isoformat()
        signal = 1 if index % 2 == 0 else -1
        forward = signal * (0.35 + (index % 5) * 0.01)
        rows.append({"candidate_id": "lane-a", "session": session, "signal": signal, "forward_return_r": forward, "outcome_r": signal * forward, "doubled_cost_outcome_r": signal * forward - 0.05})
        rows.append({"candidate_id": "lane-b", "session": session, "signal": signal, "forward_return_r": -forward, "outcome_r": -signal * forward, "doubled_cost_outcome_r": -signal * forward - 0.05})
    now = datetime(2026, 8, 22, tzinfo=timezone.utc)

    first = evaluate_replay(rows, family_size=2, now=now)
    second = evaluate_replay(rows, family_size=2, now=now)

    assert first == second
    lane = first["results"][0]
    assert lane["n_resolved"] == 60
    assert lane["distinct_sessions"] == 60
    assert lane["expectancy_lower_95_ci"] > 0
    assert lane["placebo"]["status"] == "pass"
    assert lane["cost_stress"]["status"] == "pass"
    assert lane["pbo"] is not None
    assert lane["execution_enabled"] is False
    assert lane["can_submit_orders"] is False


def test_missing_placebo_inputs_never_pass() -> None:
    report = evaluate_replay(
        [{"candidate_id": "lane-a", "session": f"2026-01-{day:02d}", "outcome_r": 0.2} for day in range(1, 11)],
        family_size=1,
        now=datetime(2026, 8, 22, tzinfo=timezone.utc),
    )
    assert report["results"][0]["placebo"]["status"] == "unavailable"
    assert report["results"][0]["pbo_status"] == "unavailable_single_lane"

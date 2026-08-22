from __future__ import annotations

from datetime import date, timedelta

from research.topstep_prior_date_router import route_candidate


def _rows(candidate: str, start: date, pnls: list[float]) -> list[dict]:
    return [
        {
            "candidate_id": candidate,
            "session_date": (start + timedelta(days=index)).isoformat(),
            "status": "resolved",
            "pnl_after_double_cost": pnl,
        }
        for index, pnl in enumerate(pnls)
    ]


def test_router_uses_only_dates_before_route_date() -> None:
    start = date(2026, 1, 1)
    rows = _rows("stable", start, [20.0, 10.0] * 20)
    rows.append({
        "candidate_id": "future-leak",
        "session_date": "2026-08-17",
        "status": "resolved",
        "pnl_after_double_cost": 1_000_000.0,
    })

    report = route_candidate(rows, route_date=date(2026, 8, 17), minimum_outcomes=30)

    assert report["selected_shadow_candidate"] == "stable"
    assert report["rejected_same_or_future_rows"] == 1
    assert report["prior_date_enforced"] is True
    assert report["can_submit_orders"] is False


def test_router_rejects_positive_average_with_unreliable_lower_bound() -> None:
    rows = _rows("fragile", date(2026, 1, 1), [100.0, -90.0] * 15)

    report = route_candidate(rows, route_date=date(2026, 8, 17), minimum_outcomes=30)

    candidate = report["candidates"][0]
    assert candidate["expectancy_after_double_cost"] > 0
    assert "nonpositive_expectancy_lcb_90" in candidate["reasons"]
    assert report["selected_shadow_candidate"] is None


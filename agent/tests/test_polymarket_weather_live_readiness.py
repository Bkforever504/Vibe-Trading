from __future__ import annotations

import json

from scripts.polymarket_weather_live_readiness import build_report


def _write(path, payload):
    path.write_text(json.dumps(payload), encoding="utf-8")


def _qualified_state(count: int = 200) -> dict:
    rows = []
    for index in range(count):
        rows.append({
            "promotion_grade": True,
            "target_date": f"2026-06-{(index % 30) + 1:02d}",
            "pnl_dollars": 2.0 if index % 4 else -1.0,
            "risk_dollars": 5.0,
            "exit_reason": "resolved_settlement",
        })
    return {"positions": [], "closed_positions": rows}


def test_geoblock_prevents_live_eligibility_even_with_strong_evidence(tmp_path) -> None:
    state = tmp_path / "state.json"
    bot = tmp_path / "bot.json"
    _write(state, _qualified_state())
    _write(bot, {
        "errors": [],
        "venue_eligibility": {"checked": True, "blocked": True, "country": "US", "region": "TX"},
    })

    report = build_report(state_path=state, bot_report_path=bot)

    assert report["go_live_eligible"] is False
    assert "jurisdiction_blocked" in report["blockers"]
    assert report["checks"]["promotion_grade_closures"]["passed"] is True
    assert report["checks"]["distinct_target_dates"]["passed"] is True
    assert report["execution_enabled"] is False
    assert report["can_submit_orders"] is False


def test_short_or_losing_sample_is_not_ready(tmp_path) -> None:
    state = tmp_path / "state.json"
    bot = tmp_path / "bot.json"
    _write(state, {
        "positions": [],
        "closed_positions": [{
            "promotion_grade": True,
            "target_date": "2026-07-15",
            "pnl_dollars": -2.0,
            "risk_dollars": 5.0,
            "exit_reason": "resolved_settlement",
        }],
    })
    _write(bot, {"errors": [], "venue_eligibility": {"checked": True, "blocked": False, "country": "CA", "region": "QC"}})

    report = build_report(state_path=state, bot_report_path=bot)

    assert report["go_live_eligible"] is False
    assert "insufficient_promotion_grade_closures" in report["blockers"]
    assert "insufficient_distinct_target_dates" in report["blockers"]
    assert "non_positive_net_pnl" in report["blockers"]
    assert "profit_factor_below_minimum" in report["blockers"]
    assert "order_adapter_not_reviewed" in report["blockers"]


def test_report_never_enables_orders_even_when_evidence_checks_pass(tmp_path) -> None:
    state = tmp_path / "state.json"
    bot = tmp_path / "bot.json"
    _write(state, _qualified_state())
    _write(bot, {"errors": [], "venue_eligibility": {"checked": True, "blocked": False, "country": "CA", "region": "QC"}})

    report = build_report(state_path=state, bot_report_path=bot, order_adapter_reviewed=True)

    assert report["evidence_ready"] is True
    assert report["go_live_eligible"] is True
    assert report["execution_enabled"] is False
    assert report["can_submit_orders"] is False
    assert report["requires_explicit_human_enablement"] is True

import json

from scripts.polymarket_weather_performance_report import build_report, write_report


def test_performance_report_separates_city_lead_time_and_promotion_grade(tmp_path) -> None:
    state = tmp_path / "state.json"
    state.write_text(json.dumps({
        "positions": [{"slug": "highest-temperature-in-london-on-july-16-2026", "entry_lead_hours": 20}],
        "closed_positions": [
            {"slug": "highest-temperature-in-madrid-on-july-15-2026", "entry_lead_hours": 8, "exit_reason": "resolved_settlement", "pnl_dollars": 4.0, "risk_dollars": 5.0, "entry_edge": 0.12, "promotion_grade": True},
            {"slug": "highest-temperature-in-madrid-on-july-14-2026", "entry_lead_hours": 4, "exit_reason": "take_profit", "pnl_dollars": -1.0, "risk_dollars": 5.0, "entry_edge": 0.10, "promotion_grade": False},
        ],
    }), encoding="utf-8")

    report = build_report(state)
    json_path, html_path = tmp_path / "report.json", tmp_path / "report.html"
    write_report(report, json_path, html_path)

    assert report["overall"]["win_rate"] == 0.5
    assert report["by_city"]["Madrid"]["net_pnl_dollars"] == 3.0
    assert report["by_lead_time"]["6_to_12h"]["promotion_grade_closed_count"] == 1
    assert report["evidence_status"] == "insufficient_paper_evidence"
    assert "Polymarket Weather Paper Bot" in html_path.read_text(encoding="utf-8")
    assert json.loads(json_path.read_text(encoding="utf-8"))["execution_enabled"] is False

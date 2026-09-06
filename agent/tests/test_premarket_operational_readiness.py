from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from scripts.premarket_operational_readiness import build_report


NOW = datetime(2026, 8, 31, 8, 25, tzinfo=ZoneInfo("America/New_York"))


def test_premarket_readiness_requires_live_primary_source_and_fresh_artifacts(tmp_path: Path) -> None:
    dashboard = tmp_path / "dashboard.html"
    dashboard.write_text("ok", encoding="utf-8")
    report = build_report(
        radar={"date": "2026-08-31", "generated_at": "2026-08-31T12:20:00Z"},
        rvol={"as_of_et": "2026-08-31T08:20:00-04:00", "profiles": {"TSLA": {}}, "errors": []},
        sec={"status": "disabled", "freshness": "missing"},
        dashboard_path=dashboard,
        now=NOW,
    )

    assert report["status"] == "blocked"
    assert report["checks"]["primary_catalyst_feed"]["passed"] is False
    assert report["can_submit_orders"] is False


def test_premarket_readiness_allows_shadow_observation_only_when_all_inputs_pass(tmp_path: Path) -> None:
    dashboard = tmp_path / "dashboard.html"
    dashboard.write_text("ok", encoding="utf-8")
    report = build_report(
        radar={"date": "2026-08-31", "generated_at": "2026-08-31T12:20:00Z"},
        rvol={"as_of_et": "2026-08-31T08:20:00-04:00", "profiles": {"TSLA": {}}, "errors": []},
        sec={"status": "ok", "freshness": "live"},
        dashboard_path=dashboard,
        now=NOW,
    )

    assert report["status"] == "ready_for_shadow_observation"
    assert report["execution_enabled"] is False

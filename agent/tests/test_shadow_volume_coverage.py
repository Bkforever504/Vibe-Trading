from __future__ import annotations

from research.shadow_volume_coverage import build_report


def test_every_shadow_strategy_program_has_volume_coverage_classification() -> None:
    report = build_report()
    assert report["discovered_strategy_shadow_programs"] > 0
    assert report["unknown_programs"] == []
    assert report["stale_manifest_entries"] == []
    assert report["classified_programs"] == report["discovered_strategy_shadow_programs"]

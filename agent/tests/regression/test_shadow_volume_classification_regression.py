from research import shadow_volume_coverage


def test_shadow_volume_manifest_covers_only_strategy_programs():
    report = shadow_volume_coverage.build_report()
    assert report["unknown_programs"] == []
    assert "governed_shadow_alert.py" not in {row["program"] for row in report["rows"]}

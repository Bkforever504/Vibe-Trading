from scripts.source_freshness_invariant import evaluate_sources


def test_freshness_invariant_quarantines_missing_and_older_than_24h() -> None:
    report = evaluate_sources([
        {"name": "fresh", "available": True, "age_seconds": 60},
        {"name": "old", "available": True, "age_seconds": 86401},
        {"name": "missing", "available": False, "age_seconds": None},
    ])
    assert report["status"] == "degraded"
    assert {row["name"] for row in report["quarantined"]} == {"old", "missing"}
    assert report["execution_enabled"] is False
    assert report["can_submit_orders"] is False

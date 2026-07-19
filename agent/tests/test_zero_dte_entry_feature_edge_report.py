import json

from scripts.zero_dte_entry_feature_edge_report import (
    _numeric_bucket,
    _time_bucket,
    build_report,
)


def test_preregistered_buckets_have_stable_boundaries() -> None:
    labels = ("low", "middle", "high")
    assert _numeric_bucket(0.19, 0.20, 0.45, labels) == "low"
    assert _numeric_bucket(0.20, 0.20, 0.45, labels) == "middle"
    assert _numeric_bucket(0.45, 0.20, 0.45, labels) == "middle"
    assert _numeric_bucket(0.46, 0.20, 0.45, labels) == "high"
    assert _numeric_bucket(None, 0.20, 0.45, labels) == "unavailable"


def test_lunch_bucket_is_explicit() -> None:
    assert _time_bucket("12:00") == "lunch_1200_to_1330"
    assert _time_bucket("13:30") == "lunch_1200_to_1330"
    assert _time_bucket("11:45") == "outside_lunch"


def test_report_uses_entry_snapshot_and_does_not_reconstruct(tmp_path) -> None:
    path = tmp_path / "shadow.jsonl"
    common = {
        "schema_version": 3,
        "data_quality": "current_session_lifecycle",
        "execution_mode": "shadow_only",
        "date": "2026-07-14",
        "symbol": "SPY",
        "right": "CALL",
        "strategy": "0dte",
        "option_symbol": "SPY_TEST",
        "lifecycle_id": "test-lifecycle",
        "contracts": 1,
        "episode_bucket_et": "12:30",
        "selection_ask": 1.0,
        "selection_bid": 0.98,
    }
    rows = [
        {
            **common,
            "event_type": "shadow_entry",
            "scanned_at": "2026-07-14T17:30:00Z",
            "entry_price_est": 1.0,
            "feature_snapshot": {
                "opening_range_fraction": 0.19,
                "expected_move_consumed_fraction": 0.60,
                "orb_breakout_candle_atr_ratio": 1.30,
                "rv_iv_regime": "iv_rich",
            },
        },
        {
            **common,
            "event_type": "shadow_exit",
            "scanned_at": "2026-07-14T18:00:00Z",
            "entry_price_est": 1.2,
            "selection_bid": 1.18,
            "mark_reason": "horizon_close",
        },
    ]
    path.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")

    report = build_report(path)

    assert report["completed_lifecycle_count"] == 1
    assert report["by_entry_time"]["lunch_1200_to_1330"]["completed_count"] == 1
    assert report["by_breakout_atr"]["over_1_2_atr"]["completed_count"] == 1
    assert report["opening_range_x_consumed"]["compressed_under_20pct|50_to_100pct"]["completed_count"] == 1
    assert report["by_regime"]["iv_rich"]["evidence_status"] == "insufficient_forward_evidence"
    assert report["execution_enabled"] is False
    assert report["can_submit_orders"] is False

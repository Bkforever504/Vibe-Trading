from __future__ import annotations

import json
from pathlib import Path

from scripts import outcome_science_report as report


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    path.write_text("\n".join(json.dumps(row) for row in rows) + "\n", encoding="utf-8")


def _shadow_rows(lifecycle: str, exit_bid: float, *, orb: str = "bull", spread: int = 2) -> list[dict]:
    base = {
        "schema_version": 3,
        "data_quality": "current_session_lifecycle",
        "execution_mode": "shadow_only",
        "date": "2026-07-15",
        "symbol": "SPY",
        "right": "CALL",
        "strategy": "0dte",
        "option_symbol": f"SPY-{lifecycle}",
        "lifecycle_id": lifecycle,
        "contracts": 1,
        "episode_bucket_et": "10:30",
        "feature_snapshot": {
            "orb_direction": orb,
            "spread_cents_at_signal": spread,
            "quote_age_seconds": 1.0,
            "orb_breakout_candle_atr_ratio": 0.8,
            "expected_move_consumed_fraction": 0.3,
            "opening_range_fraction": 0.2,
        },
    }
    return [
        {**base, "event_type": "shadow_entry", "scanned_at": "2026-07-15T15:00:00Z", "entry_price_est": 1.0, "selection_bid": 0.98, "selection_ask": 1.0},
        {**base, "event_type": "shadow_exit", "scanned_at": "2026-07-15T15:30:00Z", "entry_price_est": exit_bid, "selection_bid": exit_bid, "selection_ask": exit_bid + 0.02, "mark_reason": "hard_close"},
    ]


def test_clean_shadow_loss_is_not_called_bad_process(tmp_path: Path) -> None:
    path = tmp_path / "shadow.jsonl"
    _write_jsonl(path, _shadow_rows("loss", 0.70))

    row = report.load_flip_shadow_attributions(path)[0]

    assert row["outcome"] == "loss"
    assert row["process_classification"] == "valid_process_negative_outcome"
    assert row["primary_attribution_hypothesis"] == "signal_failed_without_favorable_excursion"
    assert row["attribution_confidence"] == "high"


def test_profitable_shadow_with_conflicted_signal_is_process_unproven(tmp_path: Path) -> None:
    path = tmp_path / "shadow.jsonl"
    _write_jsonl(path, _shadow_rows("win", 1.80, orb="bear"))

    row = report.load_flip_shadow_attributions(path)[0]

    assert row["outcome"] == "win"
    assert row["process_classification"] == "positive_outcome_process_unproven"
    assert "orb_direction_conflicted_with_contract" in row["process_concerns"]


def test_weather_resolution_preserves_model_evidence() -> None:
    row = report.attribute_weather({
        "paper_position_id": "w1",
        "station": "KJFK",
        "exit_at": "2026-07-15T20:00:00Z",
        "exit_reason": "resolved_settlement",
        "pnl_dollars": -4.0,
        "entry_model_agreement": True,
        "promotion_grade": True,
        "entry_edge": 0.14,
        "model_probabilities": {"gfs": 0.7, "ecmwf": 0.65, "icon": 0.68},
    })

    assert row["outcome"] == "loss"
    assert row["process_classification"] == "valid_process_negative_outcome"
    assert row["primary_attribution_hypothesis"] == "forecast_probability_missed_at_settlement"


def test_build_report_deduplicates_live_snapshots_and_never_enables_changes(tmp_path: Path) -> None:
    shadow = tmp_path / "shadow.jsonl"
    shadow.write_text("", encoding="utf-8")
    live = tmp_path / "live.jsonl"
    snapshot = {
        "postmortems": [{
            "trade_id": "t1",
            "date": "2026-07-15",
            "symbol": "SPY",
            "strategy": "0dte",
            "score": 8,
            "pnl": 50,
            "pnl_explanation": {"outcome": "profit", "pnl_source": "realized", "primary_driver": "target", "evidence": [], "next_action": "repeat"},
        }]
    }
    _write_jsonl(live, [snapshot, snapshot])
    weather = tmp_path / "weather.json"
    weather.write_text(json.dumps({"closed_positions": []}), encoding="utf-8")

    built = report.build_report(shadow, live, weather)

    assert built["outcome_count"] == 1
    assert built["win_count"] == 1
    assert built["automatic_strategy_changes_enabled"] is False
    assert built["can_submit_orders"] is False
    assert built["outcomes"][0]["process_classification"] == "process_supported_positive_outcome"


def test_repeated_pattern_only_creates_review_candidate(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(report, "MIN_PATTERN_SAMPLES", 2)
    shadow = tmp_path / "shadow.jsonl"
    _write_jsonl(shadow, [*_shadow_rows("a", 0.70), *_shadow_rows("b", 0.70)])
    live = tmp_path / "live.jsonl"
    live.write_text("", encoding="utf-8")
    weather = tmp_path / "weather.json"
    weather.write_text("{}", encoding="utf-8")

    built = report.build_report(shadow, live, weather)

    assert built["review_candidates"][0]["sample_count"] == 2
    assert built["review_candidates"][0]["automatic_live_change_allowed"] is False

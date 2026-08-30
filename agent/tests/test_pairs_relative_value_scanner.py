from __future__ import annotations

from datetime import datetime, timedelta, timezone

import numpy as np

from scripts.pairs_relative_value_scanner import (
    PairSpec,
    benjamini_hochberg,
    build_report,
    evaluate_pair,
)


NOW = datetime(2026, 8, 21, 21, 0, tzinfo=timezone.utc)


def _cointegrated_bars(*, deviation: float = 0.0, days_old: int = 0) -> dict[str, list[dict]]:
    rng = np.random.default_rng(17)
    right = 100.0 + np.cumsum(rng.normal(0.04, 0.55, 320))
    noise = np.zeros(320)
    for index in range(1, len(noise)):
        noise[index] = 0.72 * noise[index - 1] + rng.normal(0, 0.16)
    left = np.exp(0.2 + 0.92 * np.log(right) + noise * 0.01)
    left[-1] *= np.exp(deviation)
    end = NOW - timedelta(days=days_old)
    timestamps = [end - timedelta(days=len(left) - 1 - index) for index in range(len(left))]
    return {
        "AAA": [{"timestamp": stamp.isoformat(), "close": float(price)} for stamp, price in zip(timestamps, left)],
        "BBB": [{"timestamp": stamp.isoformat(), "close": float(price)} for stamp, price in zip(timestamps, right)],
    }


def test_benjamini_hochberg_controls_the_declared_family() -> None:
    adjusted = benjamini_hochberg({"a": 0.001, "b": 0.01, "c": 0.04, "d": 0.2})

    assert adjusted == {"a": 0.004, "b": 0.02, "c": 0.05333333, "d": 0.2}


def test_pair_model_is_fit_before_the_signal_bar_and_never_grants_order_authority() -> None:
    bars = _cointegrated_bars(deviation=0.035)
    spec = PairSpec("AAA_BBB", "AAA", "BBB", "same-index control")

    baseline = evaluate_pair(spec, bars["AAA"], bars["BBB"], timeframe="1Day", now=NOW)
    changed = _cointegrated_bars(deviation=0.11)
    stressed = evaluate_pair(spec, changed["AAA"], changed["BBB"], timeframe="1Day", now=NOW)

    assert baseline["model"]["hedge_ratio"] == stressed["model"]["hedge_ratio"]
    assert baseline["model"]["cointegration_pvalue"] == stressed["model"]["cointegration_pvalue"]
    assert abs(stressed["current"]["zscore"]) > abs(baseline["current"]["zscore"])
    assert stressed["plan"]["signal_on_completed_bar"] is True
    assert stressed["plan"]["earliest_manual_review"] == "next_bar"
    assert stressed["execution_enabled"] is False
    assert stressed["can_submit_orders"] is False


def test_report_applies_family_fdr_and_keeps_unvalidated_pairs_out_of_main_ranking() -> None:
    bars = _cointegrated_bars(deviation=0.06)
    report = build_report(
        bars,
        specs=[PairSpec("AAA_BBB", "AAA", "BBB", "same-index control")],
        timeframe="1Day",
        now=NOW,
        source_label="test_completed_bars",
    )

    row = report["pairs"][0]
    assert report["provider"] == "pairs_relative_value_scanner"
    assert report["mode"] == "read_only_shadow_research"
    assert report["summary"]["pair_count"] == 1
    assert row["model"]["cointegration_qvalue"] <= 0.05
    assert row["probability"]["value"] is None
    assert row["probability"]["ranking_eligible"] is False
    assert row["main_candidate_ranking_eligible"] is False
    assert row["source_labels"] == ["test_completed_bars", "completed_bar_causal_model"]
    assert report["execution_enabled"] is False
    assert report["can_submit_orders"] is False


def test_stale_or_missing_pair_evidence_fails_closed() -> None:
    stale = _cointegrated_bars(deviation=0.06, days_old=10)
    report = build_report(
        stale,
        specs=[
            PairSpec("AAA_BBB", "AAA", "BBB", "same-index control"),
            PairSpec("AAA_CCC", "AAA", "CCC", "missing leg"),
        ],
        timeframe="1Day",
        now=NOW,
    )

    by_id = {row["pair_id"]: row for row in report["pairs"]}
    assert "stale_completed_bars" in by_id["AAA_BBB"]["blockers"]
    assert by_id["AAA_BBB"]["state"] == "blocked"
    assert by_id["AAA_CCC"]["blockers"] == ["missing_leg_bars"]
    assert by_id["AAA_CCC"]["execution_enabled"] is False
    assert by_id["AAA_CCC"]["can_submit_orders"] is False

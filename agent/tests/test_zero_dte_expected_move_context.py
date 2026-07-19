from __future__ import annotations

import json
import math
from pathlib import Path

from scripts.zero_dte_expected_move_context import (
    build_report,
    build_symbol_context,
    classify_opening_range_fraction,
    daily_expected_move,
)


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    path.write_text("\n".join(json.dumps(row) for row in rows) + "\n", encoding="utf-8")


def test_daily_expected_move_uses_annualized_iv() -> None:
    assert daily_expected_move(100.0, 0.16) == 100.0 * 0.16 / math.sqrt(252.0)


def test_daily_expected_move_rejects_invalid_inputs() -> None:
    assert daily_expected_move(0.0, 0.16) is None
    assert daily_expected_move(100.0, 0.0) is None


def test_opening_range_buckets_are_deterministic() -> None:
    assert classify_opening_range_fraction(None) == "unavailable"
    assert classify_opening_range_fraction(0.19) == "compressed_under_20pct"
    assert classify_opening_range_fraction(0.20) == "balanced_20_to_45pct"
    assert classify_opening_range_fraction(0.45) == "balanced_20_to_45pct"
    assert classify_opening_range_fraction(0.46) == "expanded_over_45pct"


def test_symbol_context_normalizes_opening_range_and_breakout() -> None:
    row = build_symbol_context(
        "SPY",
        {"spot": 100.0, "atm_iv": 0.16},
        {"opening_range_high": 100.2, "opening_range_low": 99.8, "latest_close": 100.4, "state": "above_opening_range"},
    )
    expected = 100.0 * 0.16 / math.sqrt(252.0)
    assert row["status"] == "ok"
    assert row["opening_range_fraction"] == round(0.4 / expected, 4)
    assert row["breakout_overshoot_fraction"] == round(0.2 / expected, 4)
    assert row["opening_range_state"] == "above_opening_range"


def test_symbol_context_fails_closed_on_missing_data() -> None:
    row = build_symbol_context("SPY", {"spot": 100.0}, {})
    assert row == {"symbol": "SPY", "status": "unavailable", "reason": "missing_or_invalid_iv_or_opening_range"}


def test_report_uses_latest_same_day_rows_and_cannot_trade(tmp_path: Path) -> None:
    ivr = tmp_path / "ivr.jsonl"
    orb = tmp_path / "orb.jsonl"
    _write_jsonl(
        ivr,
        [
            {"date": "2026-07-13", "scans": [{"symbol": "SPY", "spot": 90, "atm_iv": 0.2}]},
            {"date": "2026-07-14", "scans": [{"symbol": "SPY", "spot": 100, "atm_iv": 0.16}]},
        ],
    )
    _write_jsonl(
        orb,
        [{"date": "2026-07-14", "scans": [{"symbol": "SPY", "opening_range_high": 100.2, "opening_range_low": 99.8, "latest_close": 100.1}]}],
    )
    report = build_report(["SPY", "QQQ"], day="2026-07-14", ivr_path=ivr, opening_range_path=orb)
    assert report["execution_enabled"] is False
    assert report["can_submit_orders"] is False
    assert report["ok_count"] == 1
    assert report["scans"][0]["spot"] == 100.0
    assert report["scans"][1]["status"] == "unavailable"


def test_report_does_not_reuse_stale_prior_day_context(tmp_path: Path) -> None:
    ivr = tmp_path / "ivr.jsonl"
    orb = tmp_path / "orb.jsonl"
    _write_jsonl(ivr, [{"date": "2026-07-13", "scans": [{"symbol": "SPY", "spot": 100, "atm_iv": 0.16}]}])
    _write_jsonl(orb, [{"date": "2026-07-13", "scans": [{"symbol": "SPY", "opening_range_high": 101, "opening_range_low": 99, "latest_close": 100}]}])
    report = build_report(["SPY"], day="2026-07-14", ivr_path=ivr, opening_range_path=orb)
    assert report["ok_count"] == 0
    assert report["scans"][0]["status"] == "unavailable"

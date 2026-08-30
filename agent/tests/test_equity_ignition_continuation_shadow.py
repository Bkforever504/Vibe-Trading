from __future__ import annotations

import json

import pandas as pd
import pytest

from scripts.equity_ignition_continuation_shadow import (
    EXPECTED_UNIVERSE_HASH,
    SPEC_HASH,
    _validated_universe,
    evaluate_symbol,
    revalidate_candidate,
    resolve_next_session,
)


def _frame() -> pd.DataFrame:
    dates = pd.bdate_range("2026-05-01", periods=80)
    closes = [100.0 + index * 0.28 for index in range(70)]
    closes.extend([123.0, 123.7, 123.4, 123.6, 123.8, 124.0, 124.1, 124.2, 124.25, 125.2])
    volumes = [1_000_000.0] * 70 + [3_200_000.0] + [900_000.0] * 8 + [1_900_000.0]
    close = pd.Series(closes, index=dates, dtype=float)
    return pd.DataFrame({
        "Open": close.shift(1).fillna(close.iloc[0]),
        "High": close + 0.35,
        "Low": close - 0.35,
        "Close": close,
        "Volume": volumes,
    })


def test_ignition_contraction_continuation_is_shadow_only_with_defined_geometry() -> None:
    frame = _frame()
    benchmark = frame.copy()
    benchmark["Close"] = pd.Series([100.0 + index * 0.12 for index in range(len(frame))], index=frame.index)
    sector = frame.copy()
    sector["Close"] = pd.Series([100.0 + index * 0.18 for index in range(len(frame))], index=frame.index)

    row = evaluate_symbol("NVDA", frame, benchmark=benchmark, sector=sector)

    assert row["setup_family"] == "ignition_contraction_continuation"
    assert row["state"] == "SHADOW_READY"
    assert row["ema_stack"] == "8_above_21_above_50"
    assert row["ignition"]["volume_ratio"] >= 1.8
    assert row["contraction"]["volume_contracted"] is True
    assert row["confirmation"]["volume_expanded"] is True
    assert row["entry"] > 0
    assert row["stop"] < row["entry"] < row["target_2r"]
    assert row["plan_id"].startswith("equity-ignition-contraction-continuation-v1:NVDA:")
    assert row["spec_hash"] == SPEC_HASH
    assert row["universe_hash"] == EXPECTED_UNIVERSE_HASH
    assert row["data_source"] == "yfinance_adjusted_daily_proxy"
    assert row["promotion_eligible"] is False
    assert row["execution_enabled"] is False
    assert row["can_submit_orders"] is False


def test_breakout_bar_is_not_counted_as_a_second_contraction_day() -> None:
    frame = _frame().iloc[:70].copy()
    extra_dates = pd.bdate_range(frame.index[-1] + pd.Timedelta(days=1), periods=3)
    extra = pd.DataFrame({
        "Open": [119.0, 123.0, 123.4],
        "High": [123.3, 123.8, 125.6],
        "Low": [118.8, 122.8, 123.1],
        "Close": [123.0, 123.4, 125.2],
        "Volume": [3_200_000.0, 900_000.0, 1_900_000.0],
    }, index=extra_dates)
    frame = pd.concat([frame, extra])
    benchmark = frame.copy()
    benchmark["Close"] = pd.Series([100.0 + index * 0.10 for index in range(len(frame))], index=frame.index)
    sector = frame.copy()
    sector["Close"] = pd.Series([100.0 + index * 0.15 for index in range(len(frame))], index=frame.index)

    row = evaluate_symbol("NVDA", frame, benchmark=benchmark, sector=sector)

    assert row["state"] != "SHADOW_READY"
    assert "base_not_tight_or_duration_outside_2_10_days" in row["blockers"]


def test_universe_membership_hash_fails_closed_on_drift(tmp_path) -> None:
    path = tmp_path / "universe.json"
    path.write_text(json.dumps({
        "symbols": ["SPY", "TSLA"],
        "sha256_membership_hash": EXPECTED_UNIVERSE_HASH,
        "universe_id": "equity-scout-hot20-plus-sp100-liquid",
        "universe_version": "equity-scout-hot20-plus-sp100-liquid-v1",
    }), encoding="utf-8")

    with pytest.raises(ValueError, match="universe_membership_hash_mismatch"):
        _validated_universe(path)


def test_next_session_outcome_is_adverse_first_and_promotion_ineligible() -> None:
    signal = {
        "plan_id": "equity-ignition-contraction-continuation-v1:NVDA:2026-08-24",
        "symbol": "NVDA",
        "signal_date": "2026-08-24",
        "entry": 100.0,
        "stop": 98.0,
        "target_2r": 104.0,
        "atr": 2.0,
        "spec_hash": SPEC_HASH,
    }

    outcome = resolve_next_session(
        signal,
        {"date": "2026-08-25", "Open": 99.5, "High": 105.0, "Low": 97.5, "Close": 103.0},
    )

    assert outcome["event_type"] == "outcome"
    assert outcome["terminal_reason"] == "stop_adverse_first"
    assert outcome["outcome"] == "loss"
    assert outcome["outcome_r"] < 0
    assert outcome["promotion_eligible"] is False
    assert outcome["execution_enabled"] is False
    assert outcome["can_submit_orders"] is False


def test_next_open_revalidation_requires_completed_confirmation_and_blocks_gap_chase() -> None:
    candidate = {
        "plan_id": "equity-ignition-contraction-continuation-v1:NVDA:2026-08-24",
        "symbol": "NVDA", "entry": 100.0, "stop": 98.0, "target_2r": 104.0,
        "atr": 2.0, "state": "SHADOW_READY", "blockers": [],
    }

    ready = revalidate_candidate(candidate, open_price=99.5, current_price=100.4, completed_close=100.2)
    chased = revalidate_candidate(candidate, open_price=100.6, current_price=101.0, completed_close=100.9)

    assert ready["state"] == "READY_TO_REVIEW"
    assert ready["open_revalidation"]["completed_confirmation"] is True
    assert chased["state"] == "NO_CHASE"
    assert "opening_gap_skipped_trigger_by_more_than_0_25_atr" in chased["blockers"]


def test_missing_sector_or_benchmark_context_blocks_ready_state() -> None:
    row = evaluate_symbol("NVDA", _frame(), benchmark=None, sector=None)

    assert row["state"] != "SHADOW_READY"
    assert "benchmark_context_missing" in row["blockers"]
    assert "sector_context_missing" in row["blockers"]
    assert row["execution_enabled"] is False
    assert row["can_submit_orders"] is False

from __future__ import annotations

import pandas as pd

from strategies.flip_shadow_setup_challengers import (
    evaluate_15m_orb_retest,
    evaluate_level_sweep_reversal,
    evaluate_orb_extension_reversal,
)


def _bars(rows: list[tuple[float, float, float, float]]) -> pd.DataFrame:
    return pd.DataFrame(
        rows,
        columns=["Open", "High", "Low", "Close"],
        index=pd.date_range("2026-07-16 09:30", periods=len(rows), freq="1min", tz="America/New_York"),
    )


def test_15m_orb_requires_breakout_then_retest_and_records_prior_day_alignment() -> None:
    opening = [(100.0, 100.5, 99.8, 100.1)] * 15
    frame = _bars(opening + [
        (100.4, 101.0, 100.4, 100.8),
        (100.7, 100.9, 100.48, 100.75),
        (100.75, 101.1, 100.7, 101.0),
    ])

    result = evaluate_15m_orb_retest(frame, prior_day_high=100.25, prior_day_low=98.0)

    assert result["shadow_signal"] is True
    assert result["shadow_direction"] == "call"
    assert result["prior_day_aligned"] is True
    assert result["setup_grade_context"] == "a_plus_prior_day_aligned"
    assert result["counterfactual"]["reward_risk"] == 2.0
    assert result["execution_enabled"] is False
    assert result["can_submit_orders"] is False


def test_15m_orb_does_not_treat_breakout_without_retest_as_signal() -> None:
    opening = [(100.0, 100.5, 99.8, 100.1)] * 15
    frame = _bars(opening + [
        (100.4, 101.0, 100.4, 100.8),
        (100.8, 101.3, 100.7, 101.2),
    ])

    result = evaluate_15m_orb_retest(frame, prior_day_high=100.25, prior_day_low=98.0)

    assert result["shadow_signal"] is False
    assert result["status"] == "awaiting_retest"


def test_level_sweep_requires_close_back_inside_and_next_bar_confirmation() -> None:
    frame = _bars([
        (99.8, 100.35, 99.7, 99.9),
        (99.9, 99.95, 99.4, 99.6),
        (99.6, 99.8, 99.2, 99.3),
    ])

    result = evaluate_level_sweep_reversal(
        frame,
        levels={"prior_day_high": 100.0, "prior_day_low": 98.0, "prior_week_low": 97.0},
    )

    assert result["shadow_signal"] is True
    assert result["shadow_direction"] == "put"
    assert result["swept_level_name"] == "prior_day_high"
    assert result["target_level_name"] == "prior_day_low"
    assert result["claim_status"] == "social_70pct_reversal_claim_unverified"
    assert result["live_execution_allowed"] is False


def test_level_sweep_rejects_unconfirmed_wick() -> None:
    frame = _bars([
        (99.8, 100.35, 99.7, 99.9),
        (99.9, 100.2, 99.8, 100.1),
    ])

    result = evaluate_level_sweep_reversal(frame, levels={"prior_day_high": 100.0})

    assert result["shadow_signal"] is False
    assert result["status"] == "no_confirmed_sweep"


def test_orb_extension_reversal_requires_extension_and_structure_confirmation() -> None:
    frame = _bars([
        (100.0, 100.4, 99.8, 100.1),
        (100.1, 100.5, 100.0, 100.3),
        (100.3, 100.45, 100.1, 100.2),
        (100.2, 100.35, 99.9, 100.0),
        (100.0, 100.3, 99.8, 100.2),
        (100.2, 101.4, 100.2, 101.2),
        (101.2, 101.7, 101.0, 101.5),
        (101.4, 101.55, 100.8, 100.85),
    ])

    result = evaluate_orb_extension_reversal(frame)

    assert result["shadow_signal"] is True
    assert result["shadow_direction"] == "put"
    assert result["orb_extension_fraction"] >= 1.0
    assert result["reversal_confirmation"] == "lower_high_close_below_prior_low"
    assert result["execution_enabled"] is False
    assert result["can_submit_orders"] is False
    assert result["live_execution_allowed"] is False


def test_orb_extension_without_confirmation_stays_shadow_no_signal() -> None:
    frame = _bars([
        (100.0, 100.4, 99.8, 100.1),
        (100.1, 100.5, 100.0, 100.3),
        (100.3, 100.45, 100.1, 100.2),
        (100.2, 100.35, 99.9, 100.0),
        (100.0, 100.3, 99.8, 100.2),
        (100.2, 101.4, 100.2, 101.2),
        (101.2, 101.7, 101.0, 101.5),
        (101.5, 101.8, 101.3, 101.7),
    ])

    result = evaluate_orb_extension_reversal(frame)

    assert result["shadow_signal"] is False
    assert result["status"] == "extension_without_reversal"


def test_flip_builder_attaches_option_contract_but_keeps_shadow_authority(monkeypatch) -> None:
    from strategies import flip_bot

    monkeypatch.setattr(
        flip_bot,
        "_atm_option",
        lambda symbol, right: (f"{symbol}260716C00100000", 100.0, 0.50, "2026-07-16"),
    )
    monkeypatch.setattr(flip_bot, "_option_bid_ask_spread_cents", lambda symbol: 2)
    monkeypatch.setattr(
        flip_bot,
        "_selection_quote_fields",
        lambda symbol: {"selection_bid": 0.49, "selection_ask": 0.51, "quote_age_seconds": 1.0},
    )
    signal = {
        "strategy": "orb_15m_retest", "shadow_signal": True, "shadow_direction": "call",
        "live_execution_allowed": False, "retest_at": "2026-07-16T10:00:00-04:00",
        "setup_grade_context": "a_plus_prior_day_aligned", "prior_day_aligned": True,
        "counterfactual": {"entry_underlying": 100.8, "stop_underlying": 100.4},
    }

    setup = flip_bot._build_shadow_challenger_setup(10_000, "SPY", signal)

    assert setup is not None
    assert setup["strategy"] == "orb_15m_retest"
    assert setup["right"] == "CALL"
    assert setup["shadow_setup_authority"] == "shadow_challenger_only"
    assert setup["live_execution_allowed"] is False
    assert setup["execution_enabled"] is False
    assert setup["can_submit_orders"] is False

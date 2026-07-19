from __future__ import annotations

import pandas as pd

from strategies.ict_macro_shadow import IctMacroConfig, evaluate_macro_setup


LEVELS = {
    "prior_day_high": 105.0,
    "prior_day_low": 99.0,
    "overnight_high": 104.0,
    "overnight_low": 100.0,
    "asia_high": 103.5,
    "asia_low": 100.0,
    "london_high": 103.0,
    "london_low": 100.0,
}


def _bullish_sequence(start: str = "2026-07-20 09:30") -> pd.DataFrame:
    index = pd.date_range(start, periods=12, freq="5min", tz="America/New_York")
    rows = [
        (101.0, 101.2, 100.8, 101.1),
        (101.1, 101.3, 100.9, 101.0),
        (101.0, 101.2, 100.8, 101.1),
        (101.1, 101.25, 100.9, 101.0),
        (100.4, 100.6, 99.6, 100.2),   # 09:50 sweep and reclaim of 100
        (100.2, 101.8, 100.15, 101.7), # displacement
        (101.75, 102.2, 100.9, 102.0), # bullish FVG versus sweep high 100.6
        (101.4, 101.7, 100.8, 101.2),  # retrace into FVG and accept midpoint
        (101.5, 102.0, 101.4, 101.9),
        (101.9, 102.4, 101.8, 102.2),
        (102.2, 102.8, 102.1, 102.7),
        (102.7, 103.2, 102.6, 103.0),
    ]
    return pd.DataFrame(rows, columns=["open", "high", "low", "close"], index=index)


def test_bullish_macro_sequence_emits_two_r_shadow_signal() -> None:
    result = evaluate_macro_setup(_bullish_sequence(), levels=LEVELS)

    assert result["status"] == "signal"
    assert result["direction"] == "buy"
    assert result["swept_level"] in {"overnight_low", "asia_low", "london_low"}
    assert result["entry_model"] == "ifvg_retest"
    assert result["reward_risk"] >= 2.0
    assert result["execution_enabled"] is False


def test_sequence_outside_macro_window_is_rejected() -> None:
    result = evaluate_macro_setup(_bullish_sequence("2026-07-20 12:30"), levels=LEVELS)

    assert result["status"] == "no_complete_sequence"
    assert result["shadow_signal"] is False


def test_high_impact_news_veto_blocks_even_valid_sequence() -> None:
    result = evaluate_macro_setup(
        _bullish_sequence(),
        levels=LEVELS,
        high_impact_news_veto=True,
    )

    assert result["status"] == "blocked_high_impact_news"
    assert result["shadow_signal"] is False


def test_no_displacement_means_no_signal() -> None:
    bars = _bullish_sequence()
    bars.loc[bars.index[5], ["open", "high", "low", "close"]] = [100.2, 100.5, 100.1, 100.3]

    result = evaluate_macro_setup(
        bars,
        levels=LEVELS,
        config=IctMacroConfig(displacement_lookahead_bars=1),
    )

    assert result["status"] == "no_complete_sequence"


def test_signal_never_exposes_execution_authority() -> None:
    result = evaluate_macro_setup(_bullish_sequence(), levels=LEVELS, config=IctMacroConfig())

    assert result["mode"] == "shadow_only"
    assert result["can_submit_orders"] is False
    assert result["live_execution_allowed"] is False

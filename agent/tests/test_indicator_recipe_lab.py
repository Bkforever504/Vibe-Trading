from __future__ import annotations

import pandas as pd

from research.indicator_recipe_lab import (
    MES_SPEC,
    _ha_aligned,
    _variant_allows,
    asof_htf,
    build_htf_states,
    failed2_direction,
    heikin_ashi_state,
    rejected_level,
    resample_real_bars,
    simulate_exit,
    stop_is_valid,
    traditional_levels,
)


def bar(open_: float, high: float, low: float, close: float) -> pd.Series:
    return pd.Series({"open": open_, "high": high, "low": low, "close": close, "volume": 100})


def minute_frame(start: str, periods: int, price: float = 100.0) -> pd.DataFrame:
    index = pd.date_range(start, periods=periods, freq="1min")
    return pd.DataFrame(
        {
            "open": price,
            "high": price + 0.2,
            "low": price - 0.2,
            "close": price + 0.1,
            "volume": 100.0,
        },
        index=index,
    )


def test_failed2_short_requires_attempt_and_opposite_close() -> None:
    base = bar(100, 101, 99, 100.5)
    attempt = bar(100.5, 102, 99.5, 101.5)
    confirmation = bar(101.5, 101.6, 98.8, 99.0)
    assert failed2_direction(base, attempt, confirmation) == "short"
    assert failed2_direction(base, attempt, bar(101.5, 102, 99.6, 100)) is None


def test_failed2_long_is_mirror_image() -> None:
    base = bar(100, 101, 99, 100)
    attempt = bar(100, 100.5, 98, 98.5)
    confirmation = bar(98.5, 101.2, 98.4, 100.8)
    assert failed2_direction(base, attempt, confirmation) == "long"


def test_pivots_use_only_prior_session_values() -> None:
    prior = minute_frame("2026-07-20 09:30", 3)
    prior.iloc[0, prior.columns.get_loc("high")] = 105
    prior.iloc[1, prior.columns.get_loc("low")] = 95
    prior.iloc[-1, prior.columns.get_loc("close")] = 101
    levels = traditional_levels(prior)
    assert levels["pdh"] == 105
    assert levels["pdl"] == 95
    assert round(levels["pivot"], 4) == round((105 + 95 + 101) / 3, 4)


def test_rejected_level_requires_close_back_through_and_tolerance() -> None:
    levels = {"pdh": 101.0}
    assert rejected_level(bar(100, 101.2, 99.8, 100.8), "short", levels, 0.25) == "pdh"
    assert rejected_level(bar(100, 101.4, 99.8, 100.8), "short", levels, 0.25) is None
    assert rejected_level(bar(100, 101.2, 99.8, 101.1), "short", levels, 0.25) is None


def test_heikin_ashi_is_state_only_and_alignment_uses_completed_bars() -> None:
    source = minute_frame("2026-07-20 09:30", 45)
    for position in range(len(source)):
        source.iloc[position] = [
            100 + position * 0.02,
            100.3 + position * 0.02,
            99.9 + position * 0.02,
            100.2 + position * 0.02,
            100,
        ]
    real = resample_real_bars(source, 15)
    ha = heikin_ashi_state(real)
    assert list(ha.columns) == ["open", "close", "bullish", "bearish"]
    assert _ha_aligned(ha, pd.Timestamp("2026-07-20 10:10"), "long")
    assert not _ha_aligned(ha, pd.Timestamp("2026-07-20 09:40"), "long")


def test_htf_asof_excludes_current_session() -> None:
    frames = []
    for offset, day in enumerate(pd.bdate_range("2026-01-02", periods=130)):
        frame = minute_frame(f"{day.date()} 09:30", 1, 100 + offset)
        frames.append(frame)
    states = build_htf_states(pd.concat(frames))
    session = pd.bdate_range("2026-01-02", periods=130)[-1].date()
    selected = asof_htf(states, session)
    eligible = states["daily"][states["daily"].index < pd.Timestamp(session)]
    assert selected["daily"] == eligible.iloc[-1]


def test_full_recipe_requires_every_context() -> None:
    assert _variant_allows(
        "full_recipe",
        killzone=True,
        pivot=True,
        ha=True,
        vwap=True,
        htf=True,
    )
    assert not _variant_allows(
        "full_recipe",
        killzone=True,
        pivot=True,
        ha=False,
        vwap=True,
        htf=True,
    )


def test_same_bar_stop_target_collision_is_stop_first() -> None:
    path = pd.DataFrame(
        [{"open": 100, "high": 102, "low": 98, "close": 101, "volume": 100}],
        index=[pd.Timestamp("2026-07-20 10:00")],
    )
    result = simulate_exit(
        path,
        direction="long",
        entry=100,
        stop=99,
        target=101.5,
        cost_r=0.1,
    )
    assert result["outcome"] == "stop"
    assert result["net_r"] == -1.1


def test_mes_cost_includes_two_sided_slippage_and_commission() -> None:
    path = pd.DataFrame(
        [{"open": 100, "high": 102, "low": 99.5, "close": 101, "volume": 100}],
        index=[pd.Timestamp("2026-07-20 10:00")],
    )
    price_cost = (
        2 * MES_SPEC.slippage_ticks_per_side * MES_SPEC.tick_size
        + MES_SPEC.commission_round_trip / MES_SPEC.point_value
    )
    assert price_cost == 0.996
    result = simulate_exit(
        path,
        direction="long",
        entry=100,
        stop=99,
        target=101.5,
        cost_r=price_cost,
    )
    assert result["net_r"] == 0.504


def test_gap_through_stop_is_invalid() -> None:
    assert not stop_is_valid("long", entry=98.0, stop=99.0)
    assert not stop_is_valid("short", entry=102.0, stop=101.0)
    assert stop_is_valid("long", entry=100.0, stop=99.0)

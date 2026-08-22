import pandas as pd

from research.x_pdbo_source_matched_lab import simulate_session, wilder_atr


def _bars(rows):
    return pd.DataFrame(rows, columns=["open", "high", "low", "close"])


def test_source_open_check_enters_only_when_bar_opens_outside_previous_range():
    bars = _bars([
        (99.0, 100.5, 98.0, 100.0),
        (101.0, 103.0, 100.0, 102.0),
        (102.0, 104.0, 101.0, 103.0),
    ])

    trade = simulate_session(
        bars,
        session="2026-08-14",
        previous_high=100.0,
        previous_low=90.0,
        trigger="bar_open",
    )

    assert trade is not None
    assert trade.side == 1
    assert trade.entry == 101.0
    assert trade.exit == 103.0
    assert trade.exit_reason == "end_of_day"


def test_intrabar_cross_variant_enters_at_previous_high():
    bars = _bars([
        (99.0, 101.0, 98.0, 100.5),
        (100.5, 102.0, 100.0, 101.0),
    ])

    trade = simulate_session(
        bars,
        session="2026-08-14",
        previous_high=100.0,
        previous_low=90.0,
        trigger="intrabar_cross",
    )

    assert trade is not None
    assert trade.entry == 100.0
    assert trade.gross_points == 1.0


def test_intrabar_cross_variant_does_not_backfill_gap_at_stale_level():
    bars = _bars([(103.0, 104.0, 102.0, 103.5)])

    trade = simulate_session(
        bars,
        session="2026-08-14",
        previous_high=100.0,
        previous_low=90.0,
        trigger="intrabar_cross",
    )

    assert trade is not None
    assert trade.entry == 103.0


def test_ambiguous_stop_and_target_bar_resolves_to_stop():
    bars = _bars([(101.0, 135.0, 89.0, 110.0)])

    trade = simulate_session(
        bars,
        session="2026-08-14",
        previous_high=100.0,
        previous_low=90.0,
        trigger="bar_open",
    )

    assert trade is not None
    assert trade.exit_reason == "stop"
    assert trade.gross_points == -11.0


def test_wilder_atr_requires_full_seed_period():
    frame = pd.DataFrame({
        "high": [11.0] * 10,
        "low": [9.0] * 10,
        "close": [10.0] * 10,
    })

    atr = wilder_atr(frame, 5)

    assert atr.iloc[:4].isna().all()
    assert atr.iloc[-1] == 2.0


def test_wilder_atr_uses_sma_seed_then_recursive_smoothing():
    frame = pd.DataFrame({
        "high": [2.0, 4.0, 7.0, 8.0],
        "low": [1.0, 2.0, 3.0, 4.0],
        "close": [1.5, 3.0, 6.0, 5.0],
    })

    atr = wilder_atr(frame, 3)

    assert atr.iloc[2] == 2.5
    assert atr.iloc[3] == 3.0

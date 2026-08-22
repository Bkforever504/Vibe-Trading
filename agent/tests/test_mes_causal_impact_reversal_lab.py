from __future__ import annotations

from research.mes_causal_impact_reversal_lab import (
    Candidate,
    confirmation_passes,
    cont_ofi,
    metrics,
    positive_mean_bootstrap_probability,
    qualifies_impact_failure,
    simulate_trade,
)


def candidate(direction: int = 1) -> Candidate:
    return Candidate(
        candidate_id=1,
        session_date="2026-01-02",
        instrument_id=7,
        signal_ts="2026-01-02 10:05:30",
        entry_ts="2026-01-02 10:05:39",
        direction=direction,
        entry_bid=99.75,
        entry_ask=100.0,
        flow_z=-3.0 if direction > 0 else 3.0,
        expected_move=-1.0 if direction > 0 else 1.0,
        realized_fraction=0.1,
        ending_quote_imbalance=0.2 if direction > 0 else -0.2,
    )


def test_cont_ofi_tracks_same_price_queue_changes() -> None:
    assert cont_ofi(
        bid=100, bid_size=15, ask=100.25, ask_size=8,
        previous_bid=100, previous_bid_size=10,
        previous_ask=100.25, previous_ask_size=12,
    ) == 9.0


def test_cont_ofi_tracks_price_level_changes() -> None:
    assert cont_ofi(
        bid=100.25, bid_size=7, ask=100.50, ask_size=9,
        previous_bid=100, previous_bid_size=10,
        previous_ask=100.25, previous_ask_size=12,
    ) == 19.0


def test_impact_failure_requires_opposing_quote_and_one_tick_spread() -> None:
    kwargs = dict(
        flow_z=2.6, beta=0.5, expected_move=0.75,
        realized_fraction=0.2, flow_sign=1,
        quote_imbalance=-0.2, spread=0.25,
    )
    assert qualifies_impact_failure(**kwargs)
    assert not qualifies_impact_failure(**{**kwargs, "quote_imbalance": 0.2})
    assert not qualifies_impact_failure(**{**kwargs, "spread": 0.5})


def test_confirmation_is_delayed_and_opposes_flow() -> None:
    assert confirmation_passes(
        flow_sign=1, signal_mid=100, confirm_mid=99.75,
        adverse_extreme_mid=100.25, confirm_quote_imbalance=-0.1,
        entry_spread=0.25,
    )
    assert not confirmation_passes(
        flow_sign=1, signal_mid=100, confirm_mid=100.25,
        adverse_extreme_mid=100.25, confirm_quote_imbalance=-0.1,
        entry_spread=0.25,
    )


def test_long_target_uses_executable_bid_and_frozen_costs() -> None:
    trade = simulate_trade(
        candidate(),
        [("2026-01-02 10:06:00", 101.0, 101.25),
         ("2026-01-02 10:06:30", 103.0, 103.25)],
    )
    assert trade is not None
    assert trade.exit_reason == "target"
    assert trade.base_pnl == 12.52
    assert trade.stress_pnl == 7.54


def test_short_stop_gaps_to_worse_executable_ask() -> None:
    trade = simulate_trade(
        candidate(direction=-1),
        [("2026-01-02 10:06:00", 101.75, 102.25)],
    )
    assert trade is not None
    assert trade.exit_reason == "stop"
    assert trade.base_pnl == -14.98


def test_empty_metrics_and_bootstrap_are_fail_closed() -> None:
    assert metrics([], "base_pnl") == {"trades": 0}
    assert positive_mean_bootstrap_probability([]) == 0.0
    probability = positive_mean_bootstrap_probability(
        [1.0, 1.0, -0.25], simulations=100, block_size=2
    )
    assert 0.0 <= probability <= 1.0

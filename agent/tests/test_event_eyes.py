from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from src.market_data.event_eyes import (
    EventKind,
    EventTimeGuard,
    HotCandidate,
    HotSetSelector,
    LevelDirection,
    LevelStateMachine,
    MarketEvent,
    QuotePersistence,
    SaleConditionPolicy,
    TapeTruthBook,
)


T0 = datetime(2026, 9, 4, 14, 30, tzinfo=timezone.utc)


def _trade(**overrides: object) -> MarketEvent:
    values = {
        "symbol": "SPY",
        "kind": EventKind.TRADE,
        "event_ts": T0,
        "received_ts": T0 + timedelta(milliseconds=25),
        "sequence": 10,
        "source": "sip",
        "price": 600.0,
        "size": 100.0,
        "conditions": ("@",),
    }
    values.update(overrides)
    return MarketEvent(**values)  # type: ignore[arg-type]


def _quote(seconds: float, *, bid: float = 99.99, ask: float = 100.01, bid_size: float = 10, ask_size: float = 10) -> MarketEvent:
    ts = T0 + timedelta(seconds=seconds)
    return MarketEvent(
        symbol="qqq", kind=EventKind.QUOTE, event_ts=ts, received_ts=ts,
        sequence=int(seconds * 10) + 1, source="sip", bid=bid, ask=ask,
        bid_size=bid_size, ask_size=ask_size,
    )


def test_event_envelope_normalizes_symbol_and_times() -> None:
    event = _trade(symbol=" spy ", event_ts=T0.astimezone(), received_ts=T0.astimezone())
    assert event.symbol == "SPY"
    assert event.event_ts.tzinfo == timezone.utc


def test_event_envelope_rejects_naive_timestamps() -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        _trade(event_ts=datetime(2026, 9, 4, 9, 30))


def test_integrity_accepts_causal_fresh_event_and_preserves_shadow_authority() -> None:
    result = EventTimeGuard().evaluate(_trade(), now=T0 + timedelta(seconds=1))
    assert result["accepted"] is True
    assert result["transport_latency_ms"] == 25.0
    assert result["execution_enabled"] is False
    assert result["can_submit_orders"] is False


@pytest.mark.parametrize(
    ("event", "reason"),
    [
        (_trade(event_ts=T0 - timedelta(seconds=61)), "stale_event"),
        (_trade(event_ts=T0 + timedelta(seconds=3)), "future_event"),
        (_trade(price=None), "invalid_trade_payload"),
        (
            MarketEvent(symbol="SPY", kind=EventKind.CORRECTION, event_ts=T0, received_ts=T0),
            "missing_original_sequence",
        ),
        (
            MarketEvent(symbol="SPY", kind=EventKind.LULD, event_ts=T0, received_ts=T0, lower_band=101, upper_band=100),
            "invalid_luld_bands",
        ),
    ],
)
def test_integrity_fails_honestly(event: MarketEvent, reason: str) -> None:
    result = EventTimeGuard().evaluate(event, now=T0)
    assert result["accepted"] is False
    assert reason in result["reasons"]


def test_sequence_gap_is_rejected_and_does_not_poison_next_sequence() -> None:
    guard = EventTimeGuard()
    assert guard.evaluate(_trade(sequence=10), now=T0)["accepted"] is True
    gap = guard.evaluate(_trade(sequence=12, event_ts=T0 + timedelta(milliseconds=2)), now=T0)["reasons"]
    assert "sequence_gap" in gap
    assert guard.evaluate(_trade(sequence=11, event_ts=T0 + timedelta(milliseconds=1)), now=T0)["accepted"] is True


def test_trade_condition_policy_rejects_non_price_forming_and_unknown_codes() -> None:
    policy = SaleConditionPolicy()
    assert policy.evaluate(_trade(conditions=("W",)))["reason"] == "excluded_sale_condition"
    assert policy.evaluate(_trade(conditions=("?",)))["reason"] == "unknown_sale_condition"
    assert policy.evaluate(_trade(conditions=("@",)))["eligible"] is True
    assert policy.evaluate(_trade(conditions=("@", "F", "T")))["eligible"] is True
    assert policy.evaluate(_trade(conditions=("@", "F", "T", "I")))["reason"] == "excluded_sale_condition"


def test_tape_truth_revokes_corrected_source_sequence_without_using_it_as_price() -> None:
    book = TapeTruthBook()
    correction = MarketEvent(
        symbol="SPY", kind=EventKind.CORRECTION, event_ts=T0,
        received_ts=T0, source="sip", original_sequence=41,
    )
    result = book.apply(correction, integrity_accepted=True)
    assert result["reason"] == "source_event_revoked"
    assert result["price_forming"] is False
    assert book.is_revoked(source="sip", symbol="spy", sequence=41) is True


def test_tape_truth_halt_is_terminal_until_explicit_resume() -> None:
    book = TapeTruthBook()
    halt = MarketEvent(
        symbol="QQQ", kind=EventKind.STATUS, event_ts=T0,
        received_ts=T0, status_code="HALT",
    )
    book.apply(halt, integrity_accepted=True)
    assert book.tradability(symbol="QQQ", price=100, as_of=T0)["tradable"] is False
    unknown = MarketEvent(
        symbol="QQQ", kind=EventKind.STATUS, event_ts=T0 + timedelta(seconds=1),
        received_ts=T0 + timedelta(seconds=1), status_code="SOMETHING_NEW",
    )
    book.apply(unknown, integrity_accepted=True)
    assert book.tradability(symbol="QQQ", price=100, as_of=T0 + timedelta(seconds=1))["halted"] is True


def test_tape_truth_uses_documented_status_reason_table() -> None:
    book = TapeTruthBook()
    halted = book.apply(MarketEvent(
        symbol="SPY", kind=EventKind.STATUS, event_ts=T0, received_ts=T0,
        status_code="F", reason_code="LUDP",
    ), integrity_accepted=True)
    assert halted["halted"] is True
    resumed = book.apply(MarketEvent(
        symbol="SPY", kind=EventKind.STATUS, event_ts=T0 + timedelta(seconds=1),
        received_ts=T0 + timedelta(seconds=1), status_code="F", reason_code="R4",
    ), integrity_accepted=True)
    assert resumed["halted"] is False
    assert resumed["reason"] == "trading_resumed"


def test_tape_truth_requires_fresh_luld_and_blocks_near_band() -> None:
    book = TapeTruthBook(luld_buffer_bps=10)
    event = MarketEvent(
        symbol="SPY", kind=EventKind.LULD, event_ts=T0,
        received_ts=T0, lower_band=95, upper_band=105,
    )
    book.apply(event, integrity_accepted=True)
    assert book.tradability(symbol="SPY", price=100, as_of=T0)["tradable"] is True
    near_band = book.tradability(symbol="SPY", price=104.95, as_of=T0)
    assert near_band["tradable"] is False
    assert "at_or_near_luld_band" in near_band["reasons"]
    stale = book.tradability(symbol="SPY", price=100, as_of=T0 + timedelta(seconds=61))
    assert stale["reasons"] == ["luld_stale"]


def test_hot_set_reserves_core_symbols_and_ranks_only_eligible_candidates() -> None:
    selector = HotSetSelector(3, reserved_symbols=("SPY", "DELL"))
    result = selector.select([
        HotCandidate("SPY", 80, 5),
        HotCandidate("NVDA", 95, 10),
        HotCandidate("AAPL", 90, 2),
        HotCandidate("TSLA", 100, None),
    ])
    assert result["symbols"] == ["SPY", "DELL", "NVDA"]
    assert result["unavailable_reserved"] == [{"symbol": "DELL", "reason": "missing"}]
    assert all(row["symbol"] != "TSLA" for row in result["selections"])
    assert result["can_submit_orders"] is False


def test_level_machine_moves_proximity_touch_holding_on_event_time() -> None:
    machine = LevelStateMachine(symbol="QQQ", level=100, direction=LevelDirection.LONG, hold_seconds=5)
    assert machine.observe(price=99.90, event_ts=T0)["state"] == "PROXIMITY"
    assert machine.observe(price=100.0, event_ts=T0 + timedelta(seconds=1))["state"] == "TOUCH"
    held = machine.observe(price=100.05, event_ts=T0 + timedelta(seconds=6))
    assert held["state"] == "HOLDING"
    assert held["transition"] == "TOUCH->HOLDING"


def test_level_machine_invalidates_after_touch_and_abstains_on_missing_data() -> None:
    machine = LevelStateMachine(symbol="SPY", level=100, direction=LevelDirection.LONG, invalidation_bps=10)
    machine.observe(price=100, event_ts=T0)
    invalid = machine.observe(price=99.80, event_ts=T0 + timedelta(seconds=1))
    assert invalid["state"] == "INVALIDATED"
    assert machine.observe(price=100.5, event_ts=T0 + timedelta(seconds=2))["state"] == "INVALIDATED"
    missing = machine.observe(price=None, event_ts=None, data_status="timeout")
    assert missing["state"] == "UNAVAILABLE"
    assert missing["reason"] == "market_data_unavailable"
    assert missing["execution_enabled"] is False


def test_level_hold_timer_resets_when_favorable_side_is_lost() -> None:
    machine = LevelStateMachine(symbol="QQQ", level=100, direction=LevelDirection.LONG, hold_seconds=5)
    machine.observe(price=100.0, event_ts=T0)
    assert machine.observe(price=99.95, event_ts=T0 + timedelta(seconds=4))["state"] == "PROXIMITY"
    assert machine.observe(price=100.05, event_ts=T0 + timedelta(seconds=6))["state"] == "TOUCH"
    assert machine.observe(price=100.06, event_ts=T0 + timedelta(seconds=11))["state"] == "HOLDING"


def test_quote_persistence_requires_duration_samples_and_continuous_quality() -> None:
    observer = QuotePersistence(window_seconds=5, minimum_samples=3, max_spread_bps=3)
    assert observer.observe(_quote(0), integrity_accepted=True)["state"] == "OBSERVING"
    assert observer.observe(_quote(2.5), integrity_accepted=True)["state"] == "OBSERVING"
    result = observer.observe(_quote(5), integrity_accepted=True)
    assert result["state"] == "PERSISTENT"
    assert result["quote_persistent"] is True


def test_quote_persistence_handles_irregular_event_timing() -> None:
    observer = QuotePersistence(window_seconds=5, minimum_samples=3, max_spread_bps=3)
    observer.observe(_quote(0), integrity_accepted=True)
    observer.observe(_quote(2.5), integrity_accepted=True)
    result = observer.observe(_quote(5.1), integrity_accepted=True)
    assert result["state"] == "PERSISTENT"


def test_quote_liquidity_vacuum_requires_size_withdrawal_and_spread_expansion() -> None:
    observer = QuotePersistence(window_seconds=5, minimum_samples=3)
    observer.observe(_quote(0, bid_size=20, ask_size=20), integrity_accepted=True)
    result = observer.observe(_quote(1, bid=99.95, ask=100.05, bid_size=5, ask_size=5), integrity_accepted=True)
    assert result["state"] == "LIQUIDITY_VACUUM"
    assert result["liquidity_vacuum"] is True


def test_quote_observer_fails_honestly_when_integrity_rejects_event() -> None:
    result = QuotePersistence().observe(_quote(0), integrity_accepted=False)
    assert result["status"] == "unavailable"
    assert result["reason"] == "integrity_rejected"
    assert result["can_submit_orders"] is False

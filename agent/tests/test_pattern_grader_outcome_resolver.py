from __future__ import annotations

from datetime import datetime, timezone

from scripts.pattern_grader_outcome_resolver import resolve_rows


def _detection() -> dict:
    return {
        "detection_id": "SPY-cisd-1",
        "pattern_id": "ict_cisd_universal_model",
        "symbol": "SPY",
        "direction": "bullish",
        "trigger_bar_ts": "2026-08-21T14:00:00Z",
        "trigger": 100.0,
        "invalidation": 99.0,
        "probability": 0.62,
        "outcome_5m": None,
        "outcome_15m": None,
        "outcome_60m": None,
        "outcome_eod": None,
    }


def test_resolver_fills_only_elapsed_horizons_without_trigger_bar_lookahead() -> None:
    bars = [
        {"t": "2026-08-21T13:55:00Z", "o": 100.0, "h": 103.0, "l": 98.0, "c": 101.0},
        {"t": "2026-08-21T14:00:00Z", "o": 100.0, "h": 101.2, "l": 99.8, "c": 100.9},
        {"t": "2026-08-21T14:05:00Z", "o": 100.4, "h": 101.2, "l": 100.2, "c": 101.0},
        {"t": "2026-08-21T14:10:00Z", "o": 101.0, "h": 102.2, "l": 100.8, "c": 102.0},
    ]

    additions, warnings = resolve_rows(
        [_detection()], [], now=datetime(2026, 8, 21, 14, 16, tzinfo=timezone.utc),
        bar_loader=lambda _symbol, _start, _end: bars,
    )

    assert warnings == []
    assert len(additions) == 1
    resolved = additions[0]
    assert resolved["outcome_5m"]["hit_t1"] is True
    assert resolved["outcome_5m"]["hit_t2"] is False
    assert resolved["outcome_15m"]["hit_t2"] is True
    assert resolved["outcome_60m"] is None
    assert resolved["outcome_eod"] is None
    assert resolved["execution_enabled"] is False
    assert resolved["can_submit_orders"] is False


def test_resolver_is_idempotent_and_fails_closed_when_bars_are_missing() -> None:
    detection = _detection()
    now = datetime(2026, 8, 21, 15, 1, tzinfo=timezone.utc)
    additions, warnings = resolve_rows([detection], [], now=now, bar_loader=lambda *_args: [])
    assert additions == []
    assert warnings[0]["reason"] == "forward_bars_unavailable"

    bars = [{"t": "2026-08-21T14:05:00Z", "o": 100.0, "h": 100.4, "l": 99.8, "c": 100.2}]
    first, _ = resolve_rows([detection], [], now=now, bar_loader=lambda *_args: bars)
    second, _ = resolve_rows([detection], first, now=now, bar_loader=lambda *_args: bars)
    assert len(first) == 1
    assert second == []

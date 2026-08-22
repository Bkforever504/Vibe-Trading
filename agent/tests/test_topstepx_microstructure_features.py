from __future__ import annotations

from research.topstepx_microstructure_features import build_feature_windows, latency_audit


def _event(second: int, event_type: str, payload: dict) -> dict:
    return {
        "source_timestamp": f"2026-08-10T14:00:{second:02d}Z",
        "event_type": event_type,
        "payload": payload,
    }


def test_build_complete_window_with_trade_and_depth_imbalances() -> None:
    events = [
        _event(1, "quote", {"bestBid": 6000.0, "bestAsk": 6000.25}),
        _event(1, "depth", {"type": 0, "price": 6000.0, "currentVolume": 12}),
        _event(1, "depth", {"type": 1, "price": 6000.25, "currentVolume": 4}),
        _event(2, "trade", {"type": 0, "volume": 6}),
        _event(3, "trade", {"type": 1, "volume": 2}),
        _event(4, "quote", {"bestBid": 6000.25, "bestAsk": 6000.5}),
    ]
    window = build_feature_windows(events)[0]
    assert window["data_complete"] is True
    assert window["avg_spread_ticks"] == 1.0
    assert window["mid_move_ticks"] == 1.0
    assert window["aggressor_imbalance"] == 0.5
    assert window["top5_depth_imbalance"] == 0.5


def test_depth_zero_removes_level_and_windows_are_chronological() -> None:
    events = [
        _event(7, "quote", {"bestBid": 6000.0, "bestAsk": 6000.25}),
        _event(1, "depth", {"type": 0, "price": 6000.0, "currentVolume": 10}),
        _event(2, "depth", {"type": 0, "price": 6000.0, "currentVolume": 0}),
    ]
    windows = build_feature_windows(events)
    assert len(windows) == 2
    assert windows[0]["top5_bid_depth"] is None
    assert windows[0]["window_start_utc"] < windows[1]["window_start_utc"]


def test_quote_only_window_is_marked_incomplete() -> None:
    window = build_feature_windows([
        _event(1, "quote", {"bestBid": 6000.0, "bestAsk": 6000.25}),
    ])[0]
    assert window["data_complete"] is False
    assert window["aggressor_imbalance"] is None


def test_latency_audit_reports_percentiles_and_negative_clock_rows() -> None:
    events = [
        {
            "source_timestamp": "2026-08-10T14:00:00.000Z",
            "received_at_utc": "2026-08-10T14:00:00.100Z",
        },
        {
            "source_timestamp": "2026-08-10T14:00:01.000Z",
            "received_at_utc": "2026-08-10T14:00:01.900Z",
        },
        {
            "source_timestamp": "2026-08-10T14:00:02.000Z",
            "received_at_utc": "2026-08-10T14:00:01.900Z",
        },
    ]
    audit = latency_audit(events)
    assert audit["receipt_latency_ms_p50"] == 100.0
    assert audit["receipt_latency_ms_p99"] == 900.0
    assert audit["negative_latency_count"] == 1

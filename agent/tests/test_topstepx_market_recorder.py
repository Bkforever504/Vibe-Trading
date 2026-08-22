from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from strategies.topstepx_market_recorder import (
    RECORD_SEPARATOR,
    RotatingJsonlWriter,
    TopstepXMarketRecorder,
    decode_signalr_frames,
    normalize_market_event,
    signalr_frame,
)
from scripts.topstepx_market_recorder import redact_error


def test_signalr_frames_round_trip_multiple_messages() -> None:
    raw = signalr_frame({"type": 6}) + signalr_frame({"type": 3, "invocationId": "1"})
    assert decode_signalr_frames(raw) == [{"type": 6}, {"type": 3, "invocationId": "1"}]
    assert raw.endswith(RECORD_SEPARATOR)


def test_normalize_trade_preserves_source_and_receipt_timestamps() -> None:
    received = datetime(2026, 8, 10, 14, 0, tzinfo=timezone.utc)
    event = normalize_market_event({
        "type": 1,
        "target": "GatewayTrade",
        "arguments": ["CON.F.US.MES.U26", {"price": 6000.25, "volume": 2, "timestamp": "2026-08-10T14:00:00Z"}],
    }, received_at=received)
    assert event is not None
    assert event["event_type"] == "trade"
    assert event["source_timestamp"] == "2026-08-10T14:00:00Z"
    assert event["received_at_utc"] == "2026-08-10T14:00:00Z"


def test_recorder_ignores_other_contracts_and_has_only_market_subscriptions(tmp_path: Path) -> None:
    writer = RotatingJsonlWriter(tmp_path / "events.jsonl")
    recorder = TopstepXMarketRecorder(
        access_token="secret token",
        contract_id="CON.F.US.MES.U26",
        writer=writer,
    )
    frames = [json.loads(frame.rstrip(RECORD_SEPARATOR)) for frame in recorder.subscription_frames()]
    assert {frame["target"] for frame in frames} == {
        "SubscribeContractQuotes", "SubscribeContractTrades", "SubscribeContractMarketDepth",
    }
    raw = signalr_frame({
        "type": 1,
        "target": "GatewayQuote",
        "arguments": ["CON.F.US.MNQ.U26", {"bestBid": 1, "bestAsk": 2}],
    })
    assert recorder.record_message(raw) == 0
    assert not writer.path.exists()
    assert "secret%20token" in recorder.url
    assert "secret token" not in recorder.url


def test_jsonl_writer_rotates_before_exceeding_cap(tmp_path: Path) -> None:
    path = tmp_path / "events.jsonl"
    writer = RotatingJsonlWriter(path, max_bytes=80, backup_count=2)
    for index in range(5):
        writer.append({"index": index, "payload": "x" * 25})
    assert path.exists()
    assert path.with_name("events.jsonl.1").exists()
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    assert rows[-1]["index"] == 4


def test_status_error_redacts_credentials_and_session_token() -> None:
    error = RuntimeError("wss://example?access_token=session%20secret api-key user-name")
    message = redact_error(error, ["session secret", "api-key", "user-name"])
    assert "session%20secret" not in message
    assert "api-key" not in message
    assert "user-name" not in message
    assert message.count("[REDACTED]") == 3

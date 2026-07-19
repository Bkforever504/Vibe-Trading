"""Tests for scripts/point_in_time_quotes.py - point-in-time option capture.

Contract under test (from the 2026-07-13 research-validity handoff):
- record NBBO, quote timestamp, underlying, IV, Greeks, OI, volume at
  lifecycle events with provenance;
- missing data fails to null + provenance, never to a fabricated value;
- flow classification is ALWAYS "unknown" (no licensed OPRA adapter);
- capture never raises into a trading path.
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts import point_in_time_quotes as pit

CAPTURED_AT = datetime(2026, 7, 13, 14, 45, 10, tzinfo=timezone.utc)

FULL_PAYLOAD = {
    "snapshots": {
        "SPY260713P00746000": {
            "latestQuote": {
                "bp": 1.52, "ap": 1.56, "bs": 120, "as": 95,
                "t": "2026-07-13T14:45:08.123456789Z",
            },
            "latestTrade": {"p": 1.54, "s": 3, "t": "2026-07-13T14:45:07Z", "c": ["a"]},
            "greeks": {"delta": -0.48, "gamma": 0.09, "theta": -0.31, "vega": 0.12, "rho": -0.02},
            "impliedVolatility": 0.187,
            "openInterest": 15321,
            "dailyBar": {"v": 8842},
        }
    }
}


def test_parser_extracts_full_snapshot_with_ok_provenance() -> None:
    parsed = pit.parse_alpaca_option_snapshot("SPY260713P00746000", FULL_PAYLOAD, CAPTURED_AT)

    q = parsed["quote"]
    assert q["bid"] == 1.52 and q["ask"] == 1.56
    assert q["bid_size"] == 120 and q["ask_size"] == 95
    assert q["mid"] == 1.54
    assert q["spread_cents"] == 4
    # nanosecond timestamp parsed; age = 14:45:10 - 14:45:08.123456 ~= 1.877s
    assert 1.8 < q["quote_age_seconds"] < 2.0
    assert parsed["trade"]["price"] == 1.54
    assert parsed["trade"]["conditions"] == ["a"]
    assert parsed["greeks"]["delta"] == -0.48
    assert parsed["implied_volatility"] == 0.187
    assert parsed["open_interest"] == 15321
    assert parsed["volume"] == 8842
    assert parsed["provenance"]["status"] == "ok"
    assert parsed["provenance"]["feed"] == "indicative"
    assert parsed["provenance"]["quote_scope"] == "indicative_modified_not_opra_nbbo"
    assert parsed["provenance"]["missing_fields"] == []


def test_parser_nulls_missing_fields_and_reports_partial() -> None:
    payload = {
        "snapshots": {
            "X": {"latestQuote": {"bp": 0.50, "ap": 0.54, "t": "2026-07-13T14:45:09Z"}}
        }
    }
    parsed = pit.parse_alpaca_option_snapshot("X", payload, CAPTURED_AT)

    assert parsed["quote"]["bid"] == 0.50
    assert parsed["greeks"]["delta"] is None
    assert parsed["implied_volatility"] is None
    assert parsed["open_interest"] is None
    assert parsed["provenance"]["status"] == "partial"
    missing = set(parsed["provenance"]["missing_fields"])
    assert "greeks.delta" in missing
    assert "implied_volatility" in missing
    assert "open_interest" in missing
    assert "volume" in missing


def test_parser_empty_payload_is_unavailable_not_guessed() -> None:
    parsed = pit.parse_alpaca_option_snapshot("X", {"snapshots": {}}, CAPTURED_AT)
    assert parsed["provenance"]["status"] == "unavailable"
    assert parsed["quote"]["bid"] is None
    assert parsed["quote"]["mid"] is None


def test_flow_classification_is_always_unknown() -> None:
    flow = pit.classified_flow()
    assert flow["flow_classification"] == "unknown"

    parsed = pit.parse_alpaca_option_snapshot("SPY260713P00746000", FULL_PAYLOAD, CAPTURED_AT)
    record = pit.build_lifecycle_record(
        "fill", "SPY260713P00746000", parsed, bot="flip", captured_at=CAPTURED_AT
    )
    assert record["flow_classification"] == "unknown"


def test_build_record_rejects_unknown_events() -> None:
    parsed = pit.parse_alpaca_option_snapshot("X", {"snapshots": {}}, CAPTURED_AT)
    try:
        pit.build_lifecycle_record("guess", "X", parsed, bot="flip")
        raise AssertionError("expected ValueError")
    except ValueError:
        pass


def test_capture_writes_jsonl_record_with_full_schema(tmp_path: Path) -> None:
    out = tmp_path / "samples.jsonl"

    record = pit.capture_lifecycle_sample(
        "monitor",
        "SPY260713P00746000",
        bot="flip",
        trade_id="t-1",
        order_id="o-1",
        context={"pnl_pct": 12.5},
        path=out,
        fetch_fn=lambda occ: (FULL_PAYLOAD, {"endpoint": "test", "http_status": 200, "latency_ms": 5}),
    )

    assert record is not None
    rows = [json.loads(line) for line in out.read_text(encoding="utf-8").splitlines()]
    assert len(rows) == 1
    row = rows[0]
    assert row["schema_version"] == 1
    assert row["event"] == "monitor"
    assert row["bot"] == "flip"
    assert row["trade_id"] == "t-1" and row["order_id"] == "o-1"
    assert row["contract"] == "SPY260713P00746000"
    assert row["quote"]["bid"] == 1.52
    assert row["greeks"]["vega"] == 0.12
    assert row["provenance"]["status"] == "ok"
    assert row["provenance"]["http_status"] == 200
    assert row["flow_classification"] == "unknown"
    assert row["context"] == {"pnl_pct": 12.5}
    assert row["captured_at"].endswith("Z")


def test_capture_records_failed_fetch_as_unavailable(tmp_path: Path) -> None:
    out = tmp_path / "samples.jsonl"

    record = pit.capture_lifecycle_sample(
        "exit",
        "X",
        bot="flip",
        path=out,
        fetch_fn=lambda occ: (None, {"endpoint": "test", "http_status": 500}),
    )

    assert record is not None
    row = json.loads(out.read_text(encoding="utf-8").splitlines()[0])
    assert row["provenance"]["status"] == "unavailable"
    assert row["quote"] is None
    assert row["greeks"] is None
    assert row["flow_classification"] == "unknown"


def test_capture_records_raised_fetch_as_unavailable(tmp_path: Path) -> None:
    out = tmp_path / "samples.jsonl"

    def broken_fetch(occ: str):
        raise TimeoutError("vendor timeout")

    record = pit.capture_lifecycle_sample("monitor", "X", bot="flip", path=out, fetch_fn=broken_fetch)

    assert record is not None
    assert record["provenance"]["status"] == "unavailable"
    assert "vendor timeout" in record["provenance"]["error"]


def test_nonfinite_and_crossed_quotes_are_not_derived() -> None:
    payload = {"snapshots": {"X": {"latestQuote": {"bp": "nan", "ap": 1.0, "t": "2026-07-13T14:45:09Z"}}}}
    parsed = pit.parse_alpaca_option_snapshot("X", payload, CAPTURED_AT)
    assert parsed["quote"]["bid"] is None
    assert parsed["quote"]["mid"] is None

    crossed = {"snapshots": {"X": {"latestQuote": {"bp": 1.1, "ap": 1.0, "t": "2026-07-13T14:45:09Z"}}}}
    parsed = pit.parse_alpaca_option_snapshot("X", crossed, CAPTURED_AT)
    assert parsed["quote"]["mid"] is None
    assert parsed["quote"]["spread_cents"] is None
    assert "quote.valid_market" in parsed["provenance"]["missing_fields"]


def test_capture_never_raises_even_on_unwritable_path() -> None:
    # Directory path that cannot be a file: append will fail internally.
    result = pit.capture_lifecycle_sample(
        "fill",
        "X",
        bot="flip",
        path=Path("/"),
        fetch_fn=lambda occ: (FULL_PAYLOAD, {}),
    )
    assert result is None  # swallowed, logged, no exception


def test_quote_age_handles_missing_and_bad_timestamps() -> None:
    assert pit.quote_age_seconds(None, CAPTURED_AT) is None
    assert pit.quote_age_seconds("not-a-time", CAPTURED_AT) is None
    assert pit.quote_age_seconds("2026-07-13T14:45:00Z", CAPTURED_AT) == 10.0
    # Future timestamps clamp to zero, never negative.
    assert pit.quote_age_seconds("2026-07-13T14:45:59Z", CAPTURED_AT) == 0.0


def test_flip_bot_capture_wrapper_never_raises(monkeypatch) -> None:
    from strategies import flip_bot as bot

    # Even with a broken underlying module import path, the wrapper swallows.
    trade = {"option_symbol": None, "short_option_symbol": None, "symbol": "SPY"}
    bot._capture_point_in_time("monitor", trade, context={})  # no legs -> no-op

    called = []

    def fake_capture(event, occ, **kwargs):
        called.append((event, occ, kwargs.get("trade_id"), kwargs.get("context", {}).get("leg_role")))
        return {}

    monkeypatch.setattr(
        "scripts.point_in_time_quotes.capture_lifecycle_sample", fake_capture
    )
    trade = {
        "id": "t-9",
        "option_symbol": "SPY260713P00746000",
        "short_option_symbol": "SPY260713P00741000",
        "symbol": "SPY",
        "alpaca_order_id": "o-9",
    }
    bot._capture_point_in_time("exit", trade, context={"exit_reason": "TARGET"}, blocking=True)
    assert ("exit", "SPY260713P00746000", "t-9", "long") in called
    assert ("exit", "SPY260713P00741000", "t-9", "short") in called


def test_flip_signal_wrapper_uses_preallocated_telemetry_trade_id(monkeypatch) -> None:
    from strategies import flip_bot as bot

    called = []
    monkeypatch.setattr(
        "scripts.point_in_time_quotes.capture_lifecycle_sample",
        lambda event, occ, **kwargs: called.append(kwargs),
    )
    setup = {
        "telemetry_trade_id": "candidate-1",
        "option_symbol": "SPY260713C00750000",
        "symbol": "SPY",
    }

    bot._capture_point_in_time("signal", setup, blocking=True)

    assert called[0]["trade_id"] == "candidate-1"
    assert called[0]["context"]["leg_role"] == "long"

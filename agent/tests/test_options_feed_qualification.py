from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from scripts import options_feed_qualification as qualification


NOW = datetime(2026, 8, 24, 14, 30, tzinfo=timezone.utc)


def _quote(**overrides: object) -> dict[str, object]:
    row: dict[str, object] = {
        "symbol": "SPY260824C00650000",
        "provider": "alpaca",
        "feed": "opra",
        "entitled": True,
        "quote_timestamp": "2026-08-24T14:29:58Z",
        "bid": 2.0,
        "ask": 2.1,
        "bid_size": 12,
        "ask_size": 15,
        "trade_provenance": "opra_tape",
    }
    row.update(overrides)
    return row


def test_entitled_fresh_opra_nbbo_is_qualified() -> None:
    result = qualification.qualify_options_feed(_quote(), now=NOW)

    assert result["provider_class"] == "alpaca"
    assert result["feed_class"] == "opra"
    assert result["entitlement_status"] == "verified"
    assert result["quote_provenance"] == "opra_nbbo"
    assert result["trade_provenance"] == "opra_tape"
    assert result["freshness"] == "fresh"
    assert result["age_seconds"] == 2.0
    assert result["spread"] == 0.1
    assert result["spread_pct"] == 4.878
    assert result["spread_bps"] == 487.8
    assert result["quote_valid"] is True
    assert result["feed_qualified"] is True
    assert result["context_qualified"] is True
    assert result["price_discovery_qualified"] is True
    assert result["manual_execution_qualified"] is True
    assert result["support"] == {
        "context": True,
        "price_discovery": True,
        "manual_execution": True,
    }
    assert result["blockers"] == []
    assert result["execution_enabled"] is False
    assert result["can_submit_orders"] is False


def test_indicative_feed_is_context_only_and_fails_closed() -> None:
    result = qualification.qualify_options_feed(
        _quote(feed="indicative", entitled=False, trade_provenance="indicative"),
        now=NOW,
    )

    assert result["feed_class"] == "indicative"
    assert result["quote_provenance"] == "indicative_modified"
    assert result["feed_qualified"] is False
    assert result["context_qualified"] is True
    assert result["price_discovery_qualified"] is False
    assert result["manual_execution_qualified"] is False
    assert "indicative_not_opra_nbbo" in result["blockers"]
    assert "opra_entitlement_unverified" in result["blockers"]
    assert result["qualification_label"] == "context_only"


def test_unknown_or_delayed_feed_cannot_support_any_decision() -> None:
    unknown = qualification.qualify_options_feed(
        _quote(provider="mystery", feed="unknown", entitled=True), now=NOW
    )
    delayed = qualification.qualify_options_feed(
        _quote(feed="opra", delayed=True), now=NOW
    )

    assert unknown["provider_class"] == "unknown"
    assert unknown["feed_class"] == "unknown"
    assert unknown["quote_provenance"] == "unknown"
    assert unknown["context_qualified"] is False
    assert "unknown_feed" in unknown["blockers"]
    assert delayed["freshness"] == "delayed"
    assert delayed["context_qualified"] is False
    assert delayed["price_discovery_qualified"] is False
    assert "delayed_feed" in delayed["blockers"]


def test_stale_and_future_quotes_fail_closed() -> None:
    stale = qualification.qualify_options_feed(
        _quote(quote_timestamp="2026-08-24T14:29:40Z"), now=NOW, max_age_seconds=5
    )
    future = qualification.qualify_options_feed(
        _quote(quote_timestamp="2026-08-24T14:30:03Z"), now=NOW, clock_skew_tolerance_seconds=1
    )

    assert stale["freshness"] == "stale"
    assert stale["context_qualified"] is False
    assert "stale_quote" in stale["blockers"]
    assert future["freshness"] == "clock_skew"
    assert future["clock_skew_seconds"] == 3.0
    assert future["manual_execution_qualified"] is False
    assert "quote_timestamp_in_future" in future["blockers"]


def test_crossed_or_zero_size_quotes_fail_closed() -> None:
    crossed = qualification.qualify_options_feed(_quote(bid=2.2, ask=2.1), now=NOW)
    zero_size = qualification.qualify_options_feed(_quote(bid_size=0), now=NOW)

    assert crossed["quote_valid"] is False
    assert "crossed_quote" in crossed["blockers"]
    assert crossed["spread_bps"] is None
    assert zero_size["quote_valid"] is False
    assert "zero_or_missing_quote_size" in zero_size["blockers"]
    assert zero_size["context_qualified"] is False


def test_wide_opra_quote_is_context_only_not_manual_price_reference() -> None:
    result = qualification.qualify_options_feed(
        _quote(bid=1.0, ask=2.0),
        now=NOW,
    )

    assert result["feed_qualified"] is True
    assert result["context_qualified"] is True
    assert result["spread_bps"] == 6666.67
    assert result["price_discovery_qualified"] is False
    assert result["manual_execution_qualified"] is False
    assert result["qualification_label"] == "context_only"
    assert "spread_exceeds_manual_limit" in result["blockers"]


def test_report_and_cli_use_injected_paths(tmp_path: Path) -> None:
    source = tmp_path / "input.json"
    output = tmp_path / "report.json"
    source.write_text(json.dumps({"quotes": [_quote()]}), encoding="utf-8")

    rc = qualification.main(
        [
            "--input",
            str(source),
            "--output",
            str(output),
            "--now",
            "2026-08-24T14:30:00Z",
        ]
    )

    assert rc == 0
    report = json.loads(output.read_text(encoding="utf-8"))
    assert report["schema_version"] == 1
    assert report["source_label"] == "injected_options_quote_snapshot"
    assert report["summary"]["total"] == 1
    assert report["summary"]["manual_execution_qualified"] == 1
    assert report["execution_enabled"] is False
    assert report["can_submit_orders"] is False
    assert report["records"][0]["symbol"] == "SPY260824C00650000"


def test_point_in_time_quote_log_native_nested_schema_is_supported() -> None:
    result = qualification.qualify_options_feed(
        {
            "contract": "SPY260824C00650000",
            "captured_at": "2026-08-24T14:29:59Z",
            "provenance": {
                "provider": "alpaca",
                "feed": "indicative",
                "quote_scope": "indicative_modified_not_opra_nbbo",
            },
            "quote": {
                "bid": 2.0,
                "ask": 2.1,
                "bid_size": 12,
                "ask_size": 15,
                "quote_timestamp": "2026-08-24T14:29:58Z",
            },
        },
        now=NOW,
    )

    assert result["symbol"] == "SPY260824C00650000"
    assert result["bid"] == 2.0
    assert result["ask"] == 2.1
    assert result["freshness"] == "fresh"
    assert result["context_qualified"] is True
    assert result["manual_execution_qualified"] is False


def test_jsonl_loader_keeps_latest_quote_per_contract(tmp_path: Path) -> None:
    path = tmp_path / "quotes.jsonl"
    rows = [
        {"contract": "SPY1", "captured_at": "2026-08-24T14:29:50Z", "quote": {"quote_timestamp": "2026-08-24T14:29:49Z"}},
        {"contract": "SPY1", "captured_at": "2026-08-24T14:29:59Z", "quote": {"quote_timestamp": "2026-08-24T14:29:58Z"}},
        {"contract": "QQQ1", "captured_at": "2026-08-24T14:29:57Z", "quote": {"quote_timestamp": "2026-08-24T14:29:56Z"}},
    ]
    path.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")

    loaded = qualification._latest_by_symbol(qualification._load_records(path))

    assert [row["contract"] for row in loaded] == ["QQQ1", "SPY1"]
    assert loaded[1]["captured_at"] == "2026-08-24T14:29:59Z"

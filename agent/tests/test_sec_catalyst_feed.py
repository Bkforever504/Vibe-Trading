from __future__ import annotations

from scripts.sec_catalyst_feed import build_disabled_report, classify_filing, partition_sec_eligible_symbols


def test_sec_adapter_fails_closed_without_required_identity() -> None:
    report = build_disabled_report(["NVDA", "AMD"], reason="SEC_USER_AGENT is not configured")

    assert report["status"] == "disabled"
    assert report["execution_enabled"] is False
    assert report["can_submit_orders"] is False
    assert report["symbols"] == ["AMD", "NVDA"]
    assert report["freshness"] == "missing"


def test_sec_filing_classifier_preserves_source_and_event_time() -> None:
    row = classify_filing(
        symbol="NVDA",
        form="8-K",
        accession="0001045810-26-000001",
        filed_at="2026-08-21",
        primary_document="nvda-20260821.htm",
        items="2.02,9.01",
    )

    assert row["symbol"] == "NVDA"
    assert row["event_type"] == "material_current_report"
    assert row["priority"] == "high"
    assert row["source"] == "sec_edgar_submissions"
    assert row["source_url"].endswith("nvda-20260821.htm")
    assert row["execution_enabled"] is False
    assert row["can_submit_orders"] is False


def test_non_issuer_radar_symbols_are_skipped_not_reported_as_sec_errors() -> None:
    eligible, skipped = partition_sec_eligible_symbols(
        ["NVDA", "SPY", "NVDW"], {"NVDA": "0001045810"}
    )

    assert eligible == ["NVDA"]
    assert skipped == ["SPY", "NVDW"]

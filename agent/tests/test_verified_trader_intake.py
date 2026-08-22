from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts import verified_trader_intake as intake
from scripts.verified_trader_webhook import process_tradingview_payload


NOW = datetime(2026, 7, 25, 15, 0, tzinfo=timezone.utc)


def test_public_x_claim_is_context_only_even_when_author_is_verified() -> None:
    record = intake.normalize_record(
        {
            "post_id": "x-1",
            "author_id": "author-1",
            "author_username": "blue_check",
            "created_at": "2026-07-25T14:59:30Z",
            "text": "$SPY calls now, guaranteed winner",
            "author_verified": True,
        },
        source_type="x_api",
        source_id="paid-x-research",
        observed_at=NOW,
        ingested_at=NOW,
    )

    assert record["instrument"]["symbol"] == "SPY"
    assert record["evidence"]["base_score"] == 2
    assert record["evidence"]["source_claim_unverified"] is True
    assert record["safety"]["replay_eligible"] is False
    assert record["safety"]["execution_eligible"] is False
    assert record["safety"]["promotion_eligible"] is False


def test_private_broker_fill_without_consent_is_quarantined() -> None:
    record = intake.normalize_record(
        {
            "external_id": "fill-1",
            "trader_id": "trader-1",
            "source_timestamp": "2026-07-25T14:59:30Z",
            "symbol": "SPY",
            "action": "BUY",
            "direction": "LONG",
            "quantity": 1,
            "price": 640.25,
        },
        source_type="broker_csv",
        source_id="broker-export",
        observed_at=NOW,
        ingested_at=NOW,
    )

    assert record["safety"]["quarantined"] is True
    assert "consent_reference_required" in record["safety"]["quarantine_reasons"]
    assert record["safety"]["replay_eligible"] is False


def test_consented_broker_fill_is_high_quality_replay_evidence() -> None:
    record = intake.normalize_record(
        {
            "external_id": "fill-1",
            "trader_id": "trader-1",
            "source_timestamp": "2026-07-25T14:59:30Z",
            "symbol": "SPY",
            "action": "BUY",
            "direction": "LONG",
            "quantity": 1,
            "price": 640.25,
        },
        source_type="broker_csv",
        source_id="broker-export",
        consent_ref="agreement-2026-07-25-001",
        observed_at=NOW,
        ingested_at=NOW,
    )

    assert record["source"]["broker_linked"] is True
    assert record["evidence"]["base_score"] == 9
    assert record["evidence"]["completeness_score"] == 1.0
    assert record["safety"]["quarantined"] is False
    assert record["safety"]["replay_eligible"] is True
    assert record["safety"]["live_shadow_eligible"] is False
    assert record["safety"]["execution_eligible"] is False


def test_tradingview_alert_must_be_timely_and_consented_for_live_shadow() -> None:
    raw = {
        "external_id": "alert-1",
        "trader_id": "trader-1",
        "source_timestamp": "2026-07-25T14:58:00Z",
        "symbol": "SPY",
        "direction": "LONG",
        "price": 640.25,
        "observed_market_price": 640.30,
        "strategy": "frozen-rule",
    }
    timely = intake.normalize_record(
        raw,
        source_type="tradingview_webhook",
        source_id="tv-trader-1",
        consent_ref="agreement-1",
        observed_at=NOW,
        ingested_at=NOW,
    )
    stale = intake.normalize_record(
        {**raw, "external_id": "alert-2", "source_timestamp": "2026-07-25T14:30:00Z"},
        source_type="tradingview_webhook",
        source_id="tv-trader-1",
        consent_ref="agreement-1",
        observed_at=NOW,
        ingested_at=NOW,
    )

    assert timely["evidence"]["timeliness_score"] == 7
    assert timely["safety"]["live_shadow_eligible"] is True
    assert timely["trade"]["price_drift"] == pytest.approx(0.000078, abs=0.000001)
    assert stale["evidence"]["timeliness_score"] == 3
    assert stale["safety"]["live_shadow_eligible"] is False
    assert stale["safety"]["execution_eligible"] is False


def test_timely_signal_without_market_join_is_replay_candidate_not_live() -> None:
    record = intake.normalize_record(
        {
            "external_id": "alert-no-market-join",
            "trader_id": "trader-1",
            "source_timestamp": "2026-07-25T14:59:00Z",
            "symbol": "SPY",
            "direction": "LONG",
            "price": 640.25,
        },
        source_type="tradingview_webhook",
        source_id="tv-trader-1",
        consent_ref="agreement-1",
        observed_at=NOW,
        ingested_at=NOW,
    )

    assert record["safety"]["replay_eligible"] is True
    assert record["safety"]["live_shadow_eligible"] is False
    assert record["trade"]["observed_market_price"] is None
    assert record["trade"]["price_drift"] is None


def test_non_broker_outcome_is_quarantined_and_cannot_inflate_gate() -> None:
    record = intake.normalize_record(
        {
            "event_type": "outcome",
            "trader_id": "t1",
            "source_timestamp": "2026-07-01T12:00:00Z",
            "symbol": "SPY",
            "action": "BUY",
            "price": 100.0,
            "quantity": 1,
            "realized_pnl": 50.0,
        },
        source_type="tradingview_webhook",
        source_id="test",
        consent_ref="consent-001",
        observed_at=NOW,
        ingested_at=NOW,
    )

    assert record["safety"]["quarantined"] is True
    assert (
        "outcome_claimed_by_non_broker_source"
        in record["safety"]["quarantine_reasons"]
    )
    profile = intake.build_report([record])["profiles"][0]
    assert profile["resolved_outcome_count"] == 0


def test_negative_latency_fails_closed() -> None:
    record = intake.normalize_record(
        {
            "external_id": "alert-future",
            "trader_id": "trader-1",
            "source_timestamp": "2026-07-25T15:01:00Z",
            "symbol": "SPY",
            "direction": "LONG",
            "price": 640.25,
        },
        source_type="tradingview_webhook",
        source_id="tv-trader-1",
        consent_ref="agreement-1",
        observed_at=NOW,
        ingested_at=NOW,
    )

    assert record["evidence"]["timeliness_score"] == 0
    assert "timestamp_paradox" in record["safety"]["quarantine_reasons"]
    assert record["safety"]["replay_eligible"] is False


def test_option_right_never_sets_direction() -> None:
    record = intake.normalize_record(
        {
            "external_id": "option-claim-1",
            "event_type": "signal",
            "trader_id": "trader-1",
            "source_timestamp": "2026-07-25T14:59:00Z",
            "symbol": "SPY260725P00640000",
            "option_right": "PUT",
            "side": "PUT",
            "price": 1.25,
        },
        source_type="manual_export",
        source_id="manual-options",
        consent_ref="agreement-1",
        observed_at=NOW,
        ingested_at=NOW,
    )

    assert record["instrument"]["option_right"] == "PUT"
    assert record["trade"]["direction"] is None
    assert record["trade"]["action"] is None
    assert "side_missing" in record["safety"]["quarantine_reasons"]
    assert record["safety"]["replay_eligible"] is False


def test_append_only_journal_deduplicates_identical_source_event(tmp_path: Path) -> None:
    record = intake.normalize_record(
        {
            "external_id": "fill-1",
            "trader_id": "trader-1",
            "source_timestamp": "2026-07-25T14:59:30Z",
            "symbol": "SPY",
            "action": "BUY",
            "quantity": 1,
            "price": 640.25,
        },
        source_type="broker_csv",
        source_id="broker-export",
        consent_ref="agreement-1",
        observed_at=NOW,
        ingested_at=NOW,
    )
    journal = tmp_path / "journal.jsonl"

    first = intake.append_records([record], path=journal)
    second = intake.append_records([record], path=journal)

    assert first["accepted"] == 1
    assert second["accepted"] == 0
    assert second["duplicates"] == 1
    assert len(journal.read_text(encoding="utf-8").splitlines()) == 1


def test_broker_duplicate_emits_suppression_warning(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    record = intake.normalize_record(
        {
            "external_id": "broker-fill-duplicate",
            "trader_id": "trader-1",
            "source_timestamp": "2026-07-25T14:59:30Z",
            "symbol": "SPY",
            "action": "BUY",
            "quantity": 1,
            "price": 640.25,
        },
        source_type="broker_csv",
        source_id="broker-export",
        consent_ref="agreement-1",
        observed_at=NOW,
        ingested_at=NOW,
    )
    journal = tmp_path / "journal.jsonl"
    intake.append_records([record], path=journal)
    capsys.readouterr()

    result = intake.append_records([record], path=journal)
    captured = capsys.readouterr()

    assert result["broker_duplicates"] == 1
    assert "broker-linked record(s) were deduplicated" in captured.err
    assert "Verify no losing records are suppressed" in captured.err


def test_raw_payload_credentials_are_redacted_recursively() -> None:
    record = intake.normalize_record(
        {
            "external_id": "fill-1",
            "trader_id": "trader-1",
            "source_timestamp": "2026-07-25T14:59:30Z",
            "symbol": "SPY",
            "action": "BUY",
            "quantity": 1,
            "price": 640.25,
            "api_key": "do-not-store",
            "x-api-key": "do-not-store-hyphen",
            "x-auth-token": "do-not-store-auth",
            "nested": {"Authorization": "Bearer do-not-store", "safe": "keep"},
        },
        source_type="broker_csv",
        source_id="broker-export",
        consent_ref="agreement-1",
        observed_at=NOW,
        ingested_at=NOW,
    )

    assert record["raw_payload"]["api_key"] == "[REDACTED]"
    assert record["raw_payload"]["x-api-key"] == "[REDACTED]"
    assert record["raw_payload"]["x-auth-token"] == "[REDACTED]"
    assert record["raw_payload"]["nested"]["Authorization"] == "[REDACTED]"
    assert record["raw_payload"]["nested"]["safe"] == "keep"
    assert "do-not-store" not in json.dumps(record)


def test_x_report_adapter_preserves_original_post_identity() -> None:
    rows = intake.x_report_rows(
        {
            "posts": [
                {
                    "post_id": "123",
                    "author_id": "7",
                    "author_username": "trader",
                    "created_at": "2026-07-25T14:59:00Z",
                    "text": "$SPY puts",
                    "url": "https://x.com/trader/status/123",
                }
            ]
        }
    )

    assert rows[0]["external_id"] == "123"
    assert rows[0]["trader_id"] == "7"
    assert rows[0]["url"].endswith("/123")


def test_snaptrade_activity_maps_type_and_explicit_trader_override() -> None:
    records, result = intake.ingest_rows(
        [
            {
                "id": "activity-1",
                "type": "BUY",
                "trade_date": "2026-07-24",
                "symbol": {"symbol": "SPY"},
                "units": 2,
                "price": 639.50,
                "fee": {"amount": 0.02},
            }
        ],
        source_type="snaptrade_activity",
        source_id="connection-alias",
        consent_ref="agreement-1",
        trader_id="anonymized-trader-1",
        observed_at=NOW,
        write=False,
    )

    record = records[0]
    assert result["quarantined"] == 0
    assert record["trader"]["id"] == "anonymized-trader-1"
    assert record["event"]["type"] == "fill"
    assert record["trade"]["action"] == "BUY"
    assert record["trade"]["fees"] == 0.02
    assert record["safety"]["replay_eligible"] is True


def test_report_uses_only_clean_outcomes_for_performance() -> None:
    rows = []
    for index, pnl in enumerate((20.0, -10.0, 30.0), 1):
        rows.append(
            intake.normalize_record(
                {
                    "external_id": f"outcome-{index}",
                    "event_type": "outcome",
                    "trader_id": "trader-1",
                    "source_timestamp": f"2026-07-{20 + index:02d}T15:00:00Z",
                    "symbol": "SPY",
                    "action": "SELL",
                    "direction": "LONG",
                    "realized_pnl": pnl,
                },
                source_type="broker_csv",
                source_id="broker-export",
                consent_ref="agreement-1",
                observed_at=NOW + timedelta(days=index),
                ingested_at=NOW + timedelta(days=index),
            )
        )
    rows.append(
        intake.normalize_record(
            {
                "external_id": "outcome-no-consent",
                "event_type": "outcome",
                "trader_id": "trader-1",
                "source_timestamp": "2026-07-24T15:00:00Z",
                "symbol": "SPY",
                "action": "SELL",
                "realized_pnl": 1_000_000,
            },
            source_type="broker_csv",
            source_id="broker-export",
            observed_at=NOW + timedelta(days=4),
            ingested_at=NOW + timedelta(days=4),
        )
    )

    report = intake.build_report(rows)
    profile = report["profiles"][0]

    assert profile["resolved_outcome_count"] == 3
    assert profile["realized_pnl"] == 40.0
    assert profile["win_rate"] == pytest.approx(2 / 3, abs=0.0001)
    assert profile["profit_factor"] == 5.0
    assert profile["max_drawdown_dollars"] == 10.0
    assert profile["broker_connected_evidence"] is True
    assert profile["broker_outcome_count_sufficient"] is False
    assert profile["coverage_verified"] is False
    assert report["execution_enabled"] is False
    assert report["promotion_enabled"] is False


def test_thirty_broker_outcomes_do_not_verify_history_without_coverage_manifest() -> None:
    records = []
    for index in range(30):
        records.append(
            intake.normalize_record(
                {
                    "external_id": f"coverage-outcome-{index}",
                    "event_type": "outcome",
                    "trader_id": "coverage-trader",
                    "source_timestamp": f"2026-07-01T{index % 24:02d}:00:00Z",
                    "symbol": "SPY",
                    "action": "SELL",
                    "direction": "LONG",
                    "realized_pnl": 1.0,
                },
                source_type="broker_csv",
                source_id="possibly-cherry-picked-export",
                consent_ref="agreement-1",
                observed_at=NOW,
                ingested_at=NOW,
            )
        )

    profile = intake.build_report(records)["profiles"][0]
    legacy = intake._legacy_profile(profile)

    assert profile["broker_outcome_count_sufficient"] is True
    assert profile["coverage_verified"] is False
    assert profile["status"] == "adversarial_review_required"
    assert legacy["verified"] is False
    assert legacy["source"] == "external_evidence"


def test_legacy_signal_export_stays_empty_without_current_market_join(tmp_path: Path) -> None:
    report = intake.build_report([])
    report_path = tmp_path / "report.json"
    profiles_path = tmp_path / "profiles.json"
    signals_path = tmp_path / "signals.json"

    intake.write_report_and_exports(
        report,
        report_path=report_path,
        profiles_path=profiles_path,
        signals_path=signals_path,
    )

    assert json.loads(signals_path.read_text(encoding="utf-8")) == []
    assert json.loads(report_path.read_text(encoding="utf-8"))["execution_enabled"] is False


def test_webhook_rejects_wrong_token_without_writing(tmp_path: Path) -> None:
    journal = tmp_path / "journal.jsonl"

    with pytest.raises(PermissionError):
        process_tradingview_payload(
            {"trader_id": "t"},
            supplied_token="wrong",
            expected_token="correct",
            source_id="tv",
            consent_ref="agreement",
            journal_path=journal,
        )

    assert not journal.exists()


def test_webhook_accepts_only_shadow_record(tmp_path: Path) -> None:
    journal = tmp_path / "journal.jsonl"
    now = intake._now_utc()

    result = process_tradingview_payload(
        {
            "external_id": "tv-1",
            "event_type": "signal",
            "trader_id": "trader-1",
            "source_timestamp": now.isoformat(),
            "symbol": "SPY",
            "direction": "LONG",
            "price": 640.25,
            "observed_market_price": 640.30,
        },
        supplied_token="correct",
        expected_token="correct",
        source_id="tv",
        consent_ref="agreement",
        journal_path=journal,
    )
    saved = intake.load_journal(journal)[0]

    assert result["accepted"] == 1
    assert result["execution_enabled"] is False
    assert saved["safety"]["live_shadow_eligible"] is True
    assert saved["safety"]["execution_eligible"] is False


def test_webhook_market_provider_creates_separate_observed_price(tmp_path: Path) -> None:
    journal = tmp_path / "journal.jsonl"
    now = intake._now_utc()

    result = process_tradingview_payload(
        {
            "external_id": "tv-market-join-1",
            "event_type": "signal",
            "trader_id": "trader-1",
            "source_timestamp": now.isoformat(),
            "symbol": "SPY",
            "direction": "LONG",
            "price": 640.25,
        },
        supplied_token="correct",
        expected_token="correct",
        source_id="tv",
        consent_ref="agreement",
        journal_path=journal,
        market_price_provider=lambda payload: {
            "observed_market_price": 640.35,
            "observed_market_timestamp": now.isoformat(),
            "observed_market_source": "test_point_in_time_quote",
        },
    )
    saved = intake.load_journal(journal)[0]

    assert result["market_joined"] is True
    assert saved["trade"]["price"] == 640.25
    assert saved["trade"]["observed_market_price"] == 640.35
    assert saved["trade"]["price_drift"] > 0
    assert saved["evidence"]["market_join"]["source"] == "test_point_in_time_quote"
    assert saved["safety"]["live_shadow_eligible"] is True


def test_every_source_policy_is_permanently_non_executable() -> None:
    for source_type, policy in intake.SOURCE_POLICIES.items():
        record = intake.normalize_record(
            {
                "external_id": f"{source_type}-1",
                "event_type": policy["default_event_type"],
                "trader_id": "trader-1",
                "source_timestamp": "2026-07-25T14:59:30Z",
                "symbol": "SPY",
                "direction": "LONG",
                "price": 640.25,
                "quantity": 1,
            },
            source_type=source_type,
            source_id=f"{source_type}-source",
            consent_ref="agreement",
            observed_at=NOW,
            ingested_at=NOW,
        )

        assert record["safety"]["execution_eligible"] is False
        assert record["safety"]["promotion_eligible"] is False


def test_collective2_hypothetical_signal_cannot_enter_shadow_replay() -> None:
    record = intake.normalize_record(
        {
            "external_id": "c2-1",
            "event_type": "signal",
            "trader_id": "strategy-1",
            "source_timestamp": "2026-07-25T14:59:30Z",
            "symbol": "SPY",
            "direction": "LONG",
            "price": 640.25,
            "observed_market_price": 640.30,
        },
        source_type="collective2_signal",
        source_id="collective2",
        observed_at=NOW,
        ingested_at=NOW,
    )

    assert record["source"]["results_hypothetical"] is True
    assert record["evidence"]["base_score"] == 4
    assert record["safety"]["replay_eligible"] is False
    assert record["safety"]["live_shadow_eligible"] is False


def test_robinhood_social_signal_can_only_reach_shadow_with_market_join() -> None:
    record = intake.normalize_record(
        {
            "external_id": "rh-social-1",
            "event_type": "signal",
            "trader_id": "verified-user-1",
            "source_timestamp": "2026-07-25T14:59:30Z",
            "symbol": "SPY260821C00650000",
            "action": "BUY",
            "price": 2.10,
            "observed_market_price": 2.14,
        },
        source_type="robinhood_social_signal",
        source_id="robinhood-social",
        observed_at=NOW,
        ingested_at=NOW,
    )

    assert record["source"]["trade_verified_by_platform"] is True
    assert record["source"]["broker_linked"] is False
    assert record["safety"]["replay_eligible"] is True
    assert record["safety"]["live_shadow_eligible"] is True
    assert record["safety"]["execution_eligible"] is False


def test_kinfo_public_profile_is_verification_context_not_trade_evidence() -> None:
    record = intake.normalize_record(
        {
            "external_id": "kinfo-profile-1",
            "trader_id": "public-options-trader",
            "source_timestamp": "2026-07-25T14:59:30Z",
            "text": "Broker-imported public performance profile",
        },
        source_type="kinfo_public_profile",
        source_id="kinfo",
        observed_at=NOW,
        ingested_at=NOW,
    )

    assert record["source"]["performance_verified_by_broker_import"] is True
    assert record["source"]["context_only"] is True
    assert record["safety"]["replay_eligible"] is False
    assert record["safety"]["live_shadow_eligible"] is False


def _broker_fill(external_id: str, action: str, price: float, timestamp: str) -> dict:
    return intake.normalize_record(
        {
            "external_id": external_id,
            "event_type": "fill",
            "trader_id": "complete-trader",
            "source_timestamp": timestamp,
            "symbol": "SPY",
            "option_symbol": "SPY260821C00650000",
            "asset_class": "option",
            "action": action,
            "quantity": 1,
            "price": price,
            "fees": 0.65,
        },
        source_type="broker_csv",
        source_id="complete-export",
        consent_ref="agreement-1",
        observed_at=NOW,
        ingested_at=NOW,
    )


def _coverage_manifest(record_count: int) -> dict:
    return intake.normalize_record(
        {
            "external_id": "manifest-1",
            "event_type": "coverage_manifest",
            "trader_id": "complete-trader",
            "source_timestamp": "2026-07-25T14:59:50Z",
            "account_id_hash": "a" * 64,
            "requested_start": "2026-07-01T00:00:00Z",
            "requested_end": "2026-07-25T23:59:59Z",
            "coverage_start": "2026-07-01T00:00:00Z",
            "coverage_end": "2026-07-25T23:59:59Z",
            "record_count": record_count,
            "complete": True,
            "losses_included": True,
            "export_sha256": "b" * 64,
        },
        source_type="broker_csv",
        source_id="complete-export",
        consent_ref="agreement-1",
        observed_at=NOW,
        ingested_at=NOW,
    )


def test_broker_fills_reconstruct_fee_adjusted_option_outcome() -> None:
    records = [
        _broker_fill("buy-1", "BUY", 1.00, "2026-07-10T14:30:00Z"),
        _broker_fill("sell-1", "SELL", 1.50, "2026-07-10T15:30:00Z"),
        _coverage_manifest(2),
    ]

    profile = intake.build_report(records)["profiles"][0]

    assert profile["resolved_outcome_count"] == 1
    assert profile["fill_derived_outcome_count"] == 1
    assert profile["performance_source"] == "fifo_broker_fill_reconstruction"
    assert profile["realized_pnl"] == 48.7
    assert profile["coverage_verified"] is True
    assert profile["coverage_blockers"] == []


def test_coverage_manifest_fails_when_export_count_does_not_match_journal() -> None:
    records = [
        _broker_fill("buy-1", "BUY", 1.00, "2026-07-10T14:30:00Z"),
        _broker_fill("sell-1", "SELL", 1.50, "2026-07-10T15:30:00Z"),
        _coverage_manifest(3),
    ]

    profile = intake.build_report(records)["profiles"][0]

    assert profile["coverage_verified"] is False
    assert profile["coverage_blockers"] == ["coverage_manifest_record_count_mismatch"]


def test_acquisition_funnel_exposes_claim_only_dataset() -> None:
    claim = intake.normalize_record(
        {
            "external_id": "claim-only",
            "trader_id": "social-trader",
            "source_timestamp": "2026-07-25T14:59:30Z",
            "text": "$SPY winner",
        },
        source_type="x_api",
        source_id="x-research",
        observed_at=NOW,
        ingested_at=NOW,
    )

    funnel = intake.build_report([claim])["acquisition_funnel"]

    assert funnel["claim_count"] == 1
    assert funnel["trade_event_count"] == 0
    assert funnel["primary_bottleneck"] == "no_trade_records_only_claims"


def test_covered_snaptrade_import_hashes_full_export_and_verifies_coverage(
    tmp_path: Path,
) -> None:
    export = tmp_path / "activities.json"
    export.write_text(
        json.dumps(
            [
                {
                    "id": "buy-1",
                    "type": "BUY",
                    "trade_date": "2026-07-10T14:30:00Z",
                    "symbol": {"symbol": "SPY"},
                    "units": 1,
                    "price": 640.0,
                    "fee": {"amount": 0.01},
                },
                {
                    "id": "sell-1",
                    "type": "SELL",
                    "trade_date": "2026-07-10T15:30:00Z",
                    "symbol": {"symbol": "SPY"},
                    "units": 1,
                    "price": 641.0,
                    "fee": {"amount": 0.01},
                },
                {
                    "id": "dividend-1",
                    "type": "DIVIDEND",
                    "trade_date": "2026-07-11T15:30:00Z",
                    "symbol": {"symbol": "SPY"},
                    "amount": 2.0,
                },
            ]
        ),
        encoding="utf-8",
    )

    records, result = intake.ingest_covered_export(
        export,
        source_type="snaptrade_activity",
        source_id="snaptrade-export-1",
        consent_ref="agreement-1",
        trader_id="covered-trader",
        account_alias="account-a",
        requested_start="2026-07-01T00:00:00Z",
        requested_end="2026-07-31T23:59:59Z",
        coverage_start="2026-07-01T00:00:00Z",
        coverage_end="2026-07-31T23:59:59Z",
        attest_complete_losses=True,
        observed_at="2026-08-01T12:00:00Z",
        write=False,
    )
    manifest = next(row for row in records if row["event"]["type"] == "coverage_manifest")
    profile = intake.build_report(records)["profiles"][0]

    assert result["source_row_count"] == 3
    assert result["source_trade_record_count"] == 2
    assert len(manifest["coverage_manifest"]["export_sha256"]) == 64
    assert len(manifest["coverage_manifest"]["account_id_hash"]) == 64
    assert profile["coverage_verified"] is True
    assert profile["realized_pnl"] == 0.98


def test_covered_export_requires_complete_loss_attestation(tmp_path: Path) -> None:
    export = tmp_path / "fills.json"
    export.write_text(
        json.dumps(
            [{
                "id": "buy-1",
                "type": "BUY",
                "trade_date": "2026-07-10T14:30:00Z",
                "symbol": {"symbol": "SPY"},
                "units": 1,
                "price": 640.0,
            }]
        ),
        encoding="utf-8",
    )

    with pytest.raises(intake.EvidenceIntakeError, match="loss-inclusive"):
        intake.ingest_covered_export(
            export,
            source_type="snaptrade_activity",
            source_id="snaptrade-export-1",
            consent_ref="agreement-1",
            trader_id="covered-trader",
            account_alias="account-a",
            requested_start="2026-07-01T00:00:00Z",
            requested_end="2026-07-31T23:59:59Z",
            coverage_start="2026-07-01T00:00:00Z",
            coverage_end="2026-07-31T23:59:59Z",
            attest_complete_losses=False,
            observed_at=NOW,
            write=False,
        )

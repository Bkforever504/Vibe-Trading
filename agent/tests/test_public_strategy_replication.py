from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from scripts import public_strategy_replication as replication


BASE = datetime(2026, 1, 2, 14, 45, tzinfo=timezone.utc)


def _rule() -> dict:
    return {
        "rule_id": "spy_orb_retest_public",
        "version": "1.0.0",
        "frozen_at": "2026-01-01T00:00:00Z",
        "setup_family": "opening_range_break_retest",
        "source_traders": ["trader-1"],
        "instruments": ["SPY"],
        "session_windows_et": [{"start": "09:45", "end": "10:30"}],
        "entry_predicates": [
            {"left": "close_5m", "operator": "gt", "right": "opening_range_high"}
        ],
        "contract_selection": {
            "quote_authority": "opra",
            "dte_min": 0,
            "dte_max": 1,
            "max_quote_age_seconds": 5,
            "max_spread_pct": 10,
        },
        "entry_order": {"type": "limit", "market_fallback": False},
        "stop_policy": {"type": "underlying_structure", "confirm_bars": 2},
        "target_policy": {"type": "r_multiple", "target_r": 1.5},
        "time_exit": {"minutes_after_entry": 30},
        "no_trade_conditions": [
            {"left": "event_blackout", "operator": "eq", "right": True}
        ],
        "regime_filters": [
            {"left": "opening_rvol", "operator": "gte", "right": 1.2}
        ],
        "regime_definition": {
            "method": "vix_opening_tercile",
            "version": "2026-01",
            "boundaries": [16, 24],
        },
        "position_sizing": {"max_account_risk_pct": 0.5, "max_contracts": 1},
    }


def _verified_signal(index: int = 0) -> dict:
    observed = BASE + timedelta(days=index)
    source = observed - timedelta(seconds=1)
    market = observed + timedelta(seconds=1)
    return {
        "event_id": f"source-{index}",
        "fingerprint": f"fingerprint-{index}",
        "source": {
            "type": "tradingview_webhook",
            "id": "tv-public-trader",
            "external_id": f"alert-{index}",
            "url": f"https://example.test/alert/{index}",
        },
        "trader": {"id": "trader-1", "handle": "trader-1"},
        "event": {
            "type": "signal",
            "source_timestamp": source.isoformat(),
            "observed_at": observed.isoformat(),
        },
        "instrument": {
            "symbol": "SPY260102C00650000",
            "underlying": "SPY",
            "option_symbol": "SPY260102C00650000",
        },
        "trade": {
            "action": "BUY",
            "direction": "LONG",
            "price": 1.00,
            "stop_price": 0.75,
            "target_price": 1.50,
        },
        "evidence": {
            "market_join": {
                "available": True,
                "price": 1.05,
                "timestamp": market.isoformat(),
                "source": "opra_point_in_time_quote",
            }
        },
        "safety": {"quarantined": False, "replay_eligible": True},
    }


def _register(tmp_path: Path) -> tuple[Path, dict]:
    ledger = tmp_path / "replication.jsonl"
    replication.register_rules([_rule()], ledger_path=ledger)
    rule = replication.load_ledger(ledger)[0]["rule"]
    return ledger, rule


def _outcome(signal: dict, rule: dict, *, exit_value: float = 1.20) -> dict:
    observed = datetime.fromisoformat(signal["observed_at"])
    return {
        "signal_event_id": signal["event_id"],
        "rule_hash": rule["rule_hash"],
        "quote_authority": "opra",
        "quote_method": "opra_aggregate_executable_nbbo",
        "regime_definition_hash": rule["regime_definition"]["definition_hash"],
        "instrument": "SPY260102C00650000",
        "position_side": "long_premium",
        "entry_quote_timestamp": (observed + timedelta(seconds=2)).isoformat(),
        "exit_quote_timestamp": (observed + timedelta(minutes=10)).isoformat(),
        "entry_executable_value": 1.05,
        "exit_executable_value": exit_value,
        "entry_mid_value": 1.00,
        "exit_mid_value": 1.25,
        "quantity": 1,
        "multiplier": 100,
        "capital_at_risk_dollars": 105,
        "fees_dollars": 1,
        "additional_slippage_dollars": 0,
        "regime": "trend_up",
        "resolution": "target",
    }


def test_rule_is_frozen_limit_only_and_non_executable(tmp_path: Path) -> None:
    ledger, rule = _register(tmp_path)
    saved = replication.load_ledger(ledger)[0]

    assert len(rule["rule_hash"]) == 64
    assert rule["entry_order"] == {"type": "limit", "market_fallback": False}
    assert saved["execution_enabled"] is False
    assert saved["can_submit_orders"] is False
    assert replication.verify_ledger(replication.load_ledger(ledger))["valid"] is True


def test_rule_rejects_market_fallback() -> None:
    rule = _rule()
    rule["entry_order"] = {"type": "market", "market_fallback": True}

    with pytest.raises(replication.ReplicationError, match="limit-only"):
        replication.normalize_rule(rule)


def test_frozen_rule_version_cannot_be_mutated(tmp_path: Path) -> None:
    ledger, _ = _register(tmp_path)
    changed = _rule()
    changed["target_policy"] = {"type": "r_multiple", "target_r": 3.0}

    with pytest.raises(replication.ReplicationError, match="mutation rejected"):
        replication.register_rules([changed], ledger_path=ledger)


def test_hash_chain_detects_historical_edit(tmp_path: Path) -> None:
    ledger, _ = _register(tmp_path)
    row = json.loads(ledger.read_text(encoding="utf-8").splitlines()[0])
    row["rule"]["setup_family"] = "edited_after_the_fact"
    ledger.write_text(json.dumps(row) + "\n", encoding="utf-8")

    with pytest.raises(replication.ReplicationError, match="tamper detected"):
        replication.load_ledger(ledger)


def test_only_pretrade_replay_eligible_signals_are_snapshotted(tmp_path: Path) -> None:
    ledger, rule = _register(tmp_path)
    invalid = _verified_signal(1)
    invalid["safety"]["replay_eligible"] = False

    result = replication.snapshot_verified_signals(
        [_verified_signal(), invalid],
        rule_id=rule["rule_id"],
        version=rule["version"],
        ledger_path=ledger,
    )
    signals = [
        row for row in replication.load_ledger(ledger)
        if row["event_type"] == "signal_snapshot"
    ]

    assert result["accepted"] == 1
    assert result["source_records_rejected"] == 1
    assert signals[0]["pre_entry_captured"] is True
    assert signals[0]["reconstruction_ready"] is True
    assert signals[0]["rule_ref"]["rule_hash"] == rule["rule_hash"]
    assert signals[0]["execution_enabled"] is False


def test_option_symbol_can_supply_missing_underlying(tmp_path: Path) -> None:
    ledger, rule = _register(tmp_path)
    signal = _verified_signal()
    signal["instrument"]["underlying"] = None

    result = replication.snapshot_verified_signals(
        [signal],
        rule_id=rule["rule_id"],
        version=rule["version"],
        ledger_path=ledger,
    )

    assert result["accepted"] == 1


def test_signal_before_rule_freeze_is_diagnostic_not_forward_evidence(tmp_path: Path) -> None:
    rule_input = _rule()
    rule_input["frozen_at"] = "2026-02-01T00:00:00Z"
    ledger = tmp_path / "replication.jsonl"
    replication.register_rules([rule_input], ledger_path=ledger)
    rule = replication.load_ledger(ledger)[0]["rule"]

    replication.snapshot_verified_signals(
        [_verified_signal()],
        rule_id=rule["rule_id"],
        version=rule["version"],
        ledger_path=ledger,
    )
    report = replication.build_report(replication.load_ledger(ledger))
    cohort = report["cohorts"][0]

    assert cohort["observed_signal_count"] == 1
    assert cohort["signal_count"] == 0
    assert "fewer_than_30_pretrade_signals" in cohort["promotion_blockers"]


def test_executable_outcome_is_pipeline_computed_not_source_claimed(tmp_path: Path) -> None:
    ledger, rule = _register(tmp_path)
    replication.snapshot_verified_signals(
        [_verified_signal()],
        rule_id=rule["rule_id"],
        version=rule["version"],
        ledger_path=ledger,
    )
    signal = next(
        row for row in replication.load_ledger(ledger)
        if row["event_type"] == "signal_snapshot"
    )
    observed = datetime.fromisoformat(signal["observed_at"])
    raw = {
        "signal_event_id": signal["event_id"],
        "rule_hash": rule["rule_hash"],
        "quote_authority": "opra",
        "quote_method": "opra_aggregate_executable_nbbo",
        "regime_definition_hash": rule["regime_definition"]["definition_hash"],
        "instrument": "SPY260102C00650000",
        "position_side": "long_premium",
        "entry_quote_timestamp": (observed + timedelta(seconds=2)).isoformat(),
        "exit_quote_timestamp": (observed + timedelta(minutes=10)).isoformat(),
        "entry_executable_value": 1.05,
        "exit_executable_value": 1.20,
        "entry_mid_value": 1.00,
        "exit_mid_value": 1.25,
        "quantity": 1,
        "multiplier": 100,
        "capital_at_risk_dollars": 105,
        "fees_dollars": 1,
        "additional_slippage_dollars": 0,
        "claimed_net_pnl_dollars": 999999,
        "regime": "trend_up",
    }

    replication.import_replay_outcomes([raw], ledger_path=ledger)
    outcome = next(
        row["outcome"] for row in replication.load_ledger(ledger)
        if row["event_type"] == "replay_outcome"
    )

    assert outcome["gross_pnl_dollars"] == 15.0
    assert outcome["spread_friction_dollars"] == 10.0
    assert outcome["net_pnl_dollars"] == 14.0
    assert outcome["doubled_cost_pnl_dollars"] == 3.0
    assert outcome["calculation_authority"] == "pipeline_computed_not_source_claimed"
    assert "claimed_net_pnl_dollars" not in outcome


def test_outcome_rejects_stale_or_non_opra_reconstruction(tmp_path: Path) -> None:
    ledger, rule = _register(tmp_path)
    replication.snapshot_verified_signals(
        [_verified_signal()],
        rule_id=rule["rule_id"],
        version=rule["version"],
        ledger_path=ledger,
    )
    signal = next(
        row for row in replication.load_ledger(ledger)
        if row["event_type"] == "signal_snapshot"
    )
    observed = datetime.fromisoformat(signal["observed_at"])
    raw = {
        "signal_event_id": signal["event_id"],
        "rule_hash": rule["rule_hash"],
        "quote_authority": "indicative",
        "instrument": "SPY260102C00650000",
        "position_side": "long_premium",
        "entry_quote_timestamp": (observed + timedelta(seconds=30)).isoformat(),
        "exit_quote_timestamp": (observed + timedelta(minutes=10)).isoformat(),
    }

    with pytest.raises(replication.ReplicationError, match="OPRA"):
        replication.import_replay_outcomes([raw], ledger_path=ledger)


def test_second_conflicting_outcome_for_signal_is_rejected(tmp_path: Path) -> None:
    ledger, rule = _register(tmp_path)
    replication.snapshot_verified_signals(
        [_verified_signal()],
        rule_id=rule["rule_id"],
        version=rule["version"],
        ledger_path=ledger,
    )
    signal = next(
        row for row in replication.load_ledger(ledger)
        if row["event_type"] == "signal_snapshot"
    )
    replication.import_replay_outcomes([_outcome(signal, rule)], ledger_path=ledger)

    with pytest.raises(replication.ReplicationError, match="conflicting second outcome"):
        replication.import_replay_outcomes(
            [_outcome(signal, rule, exit_value=1.19)], ledger_path=ledger
        )


def test_incomplete_source_coverage_cannot_enter_ledger(tmp_path: Path) -> None:
    ledger, _ = _register(tmp_path)
    manifest = {
        "source_type": "tradingview_webhook",
        "source_id": "tv-public-trader",
        "trader": "trader-1",
        "coverage_start": "2026-01-01T00:00:00Z",
        "coverage_end": "2026-02-28T23:59:59Z",
        "capture_method": "authenticated_webhook_archive",
        "poll_interval_seconds": 1,
        "captured_record_count": 40,
        "capture_complete": True,
        "deletions_tracked": False,
        "archive_sha256": "a" * 64,
    }

    with pytest.raises(replication.ReplicationError, match="deletion tracking"):
        replication.import_coverage_manifests([manifest], ledger_path=ledger)


def test_positive_league_still_has_no_paper_or_execution_authority(tmp_path: Path) -> None:
    ledger, rule = _register(tmp_path)
    signals = [_verified_signal(index) for index in range(40)]
    replication.snapshot_verified_signals(
        signals,
        rule_id=rule["rule_id"],
        version=rule["version"],
        ledger_path=ledger,
    )
    replication.import_coverage_manifests(
        [
            {
                "source_type": "tradingview_webhook",
                "source_id": "tv-public-trader",
                "trader": "trader-1",
                "coverage_start": "2026-01-01T00:00:00Z",
                "coverage_end": "2026-03-31T23:59:59Z",
                "capture_method": "authenticated_webhook_archive",
                "poll_interval_seconds": 1,
                "captured_record_count": 40,
                "capture_complete": True,
                "deletions_tracked": True,
                "archive_sha256": "a" * 64,
            }
        ],
        ledger_path=ledger,
    )
    snapshots = [
        row for row in replication.load_ledger(ledger)
        if row["event_type"] == "signal_snapshot"
    ]
    outcomes = []
    for index, signal in enumerate(snapshots):
        observed = datetime.fromisoformat(signal["observed_at"])
        outcomes.append(
            {
                "signal_event_id": signal["event_id"],
                "rule_hash": rule["rule_hash"],
                "quote_authority": "opra",
                "quote_method": "opra_aggregate_executable_nbbo",
                "regime_definition_hash": rule["regime_definition"]["definition_hash"],
                "instrument": f"SPY2603{index + 1:02d}C00650000",
                "position_side": "long_premium",
                "entry_quote_timestamp": (observed + timedelta(seconds=2)).isoformat(),
                "exit_quote_timestamp": (observed + timedelta(minutes=10)).isoformat(),
                "entry_executable_value": 1.05,
                "exit_executable_value": 1.20,
                "entry_mid_value": 1.00,
                "exit_mid_value": 1.25,
                "quantity": 1,
                "multiplier": 100,
                "capital_at_risk_dollars": 105,
                "fees_dollars": 1,
                "additional_slippage_dollars": 0,
                "regime": "trend_up_low_vol" if index < 20 else "trend_up_high_vol",
                "trading_date": (BASE + timedelta(days=index)).date().isoformat(),
                "resolution": "target",
            }
        )
    replication.import_replay_outcomes(outcomes, ledger_path=ledger)

    report = replication.build_report(replication.load_ledger(ledger))
    cohort = report["cohorts"][0]

    assert cohort["status"] == "forward_shadow_nominee"
    assert cohort["promotion_blockers"] == []
    assert cohort["paper_gate_ready"] is False
    assert cohort["production_change_allowed"] is False
    assert report["execution_enabled"] is False
    assert report["can_submit_orders"] is False
    assert report["paper_gate_ready"] is False

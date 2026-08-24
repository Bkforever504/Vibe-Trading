from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from scripts.shadow_outcome_resolver import LEDGER_NAMES, build_resolutions, run_once


NOW = datetime(2026, 8, 20, 20, 30, tzinfo=timezone.utc)


def ledger_rows() -> list[dict]:
    return [
        {"type": "candidate", "candidate_id": "plan-1", "created_at": "2026-08-20T14:30:00Z", "executable_entry_credit": 1.0, "max_risk_per_contract": 400},
        {"type": "mark", "candidate_id": "plan-1", "marked_at": "2026-08-20T14:35:00Z", "executable_close_debit": 0.8},
        {"type": "mark", "candidate_id": "plan-1", "marked_at": "2026-08-20T14:40:00Z", "executable_close_debit": 1.25},
        {"type": "outcome", "candidate_id": "plan-1", "resolved_at": "2026-08-20T15:00:00Z", "closing_debit": 0.5, "pnl_before_fees": 50, "quantity": 1, "reason": "profit_target"},
    ]


def test_resolver_uses_executable_marks_and_terminal_fill() -> None:
    rows = build_resolutions({"ledger.jsonl": ledger_rows()}, resolved_at=NOW)

    assert len(rows) == 1
    row = rows[0]
    assert row["entry_fill_executable"] == 1.0
    assert row["exit_fill_executable"] == 0.5
    assert row["mfe"] == pytest.approx(0.2)
    assert row["mae"] == pytest.approx(-0.25)
    assert row["outcome_r"] == 0.125
    assert row["time_in_trade_minutes"] == 30.0
    assert row["execution_enabled"] is False
    assert row["can_submit_orders"] is False


def test_run_once_is_append_only_and_idempotent(tmp_path: Path) -> None:
    ledger = tmp_path / LEDGER_NAMES[0]
    ledger.write_text("".join(json.dumps(row) + "\n" for row in ledger_rows()), encoding="utf-8")
    output = tmp_path / "outcomes.jsonl"

    first = run_once(data_dir=tmp_path, output_path=output, now=NOW)
    original = output.read_bytes()
    second = run_once(data_dir=tmp_path, output_path=output, now=NOW)

    assert first["resolved_count"] == 1
    assert second["resolved_count"] == 0
    assert output.read_bytes() == original


def test_proxy_ohlcv_terminal_uses_net_result_and_stays_non_promotable() -> None:
    rows = [
        {
            "type": "entry",
            "plan_id": "mes-orb-0932-vix-v2:2026-08-17",
            "candidate_id": "mes-orb-0932-vix-v2",
            "strategy_id": "mes-orb-0932-vix-v2",
            "family_id": "mes-opening-breakout",
            "spec_hash": "sha256:" + "a" * 64,
            "created_at": "2026-08-17T13:35:00Z",
            "entry_price_observed_proxy": 100.0,
            "max_risk_per_contract": 20.0,
            "data_source": "yfinance_proxy_MES=F",
            "evidence_tier": "proxy_ohlcv_non_executable",
            "promotion_eligible": False,
            "evidence_blockers": ["databento_mbo_and_executable_quotes_required"],
        },
        {
            "type": "exit",
            "plan_id": "mes-orb-0932-vix-v2:2026-08-17",
            "resolved_at": "2026-08-17T16:00:00Z",
            "pnl_before_fees": 15.0,
            "net_dollar": 10.0,
            "outcome_r": 0.5,
            "promotion_eligible": False,
            "reason": "time_stop",
        },
    ]

    outcome = build_resolutions({"proxy.jsonl": rows}, resolved_at=NOW)[0]

    assert outcome["entry_fill_executable"] is None
    assert outcome["exit_fill_executable"] is None
    assert outcome["pnl_before_fees"] == 15.0
    assert outcome["net_dollar"] == 10.0
    assert outcome["outcome_r"] == 0.5
    assert outcome["candidate_id"] == "mes-orb-0932-vix-v2"
    assert outcome["promotion_eligible"] is False
    assert outcome["quote_method"] == "proxy_ohlcv_non_executable"


def test_resolver_aggregates_under_stable_strategy_and_requires_explicit_qualified_contract() -> None:
    source = "databento_glbx_mdp3_mbo"
    tier = "databento_mbo_executable"
    rows = [
        {
            "type": "entry",
            "plan_id": "mes-orb-0932-vix-v2:2026-08-24",
            "candidate_id": "mes-orb-0932-vix-v2:2026-08-24",
            "strategy_id": "mes-orb-0932-vix-v2",
            "session_date": "2026-08-24",
            "created_at": "2026-08-24T13:35:00Z",
            "entry_fill_executable": 6500.25,
            "max_risk_per_contract": 50.0,
            "data_source": source,
            "evidence_tier": tier,
            "promotion_eligible": True,
            "evidence_blockers": [],
        },
        {
            "type": "exit",
            "plan_id": "mes-orb-0932-vix-v2:2026-08-24",
            "resolved_at": "2026-08-24T16:00:00Z",
            "exit_fill_executable": 6502.25,
            "outcome_r": 0.8,
            "data_source": source,
            "evidence_tier": tier,
            "promotion_eligible": True,
            "evidence_blockers": [],
            "regrade_version": 2,
        },
    ]

    outcome = build_resolutions({"qualified.jsonl": rows}, resolved_at=NOW)[0]

    assert outcome["plan_id"] == "mes-orb-0932-vix-v2:2026-08-24"
    assert outcome["candidate_id"] == "mes-orb-0932-vix-v2"
    assert outcome["strategy_id"] == "mes-orb-0932-vix-v2"
    assert outcome["session"] == "2026-08-24"
    assert outcome["session_date"] == "2026-08-24"
    assert outcome["outcome_version"] == 2
    assert outcome["promotion_eligible"] is True
    assert outcome["promotion_exclusion_reasons"] == []


def test_resolver_fails_closed_when_terminal_provenance_is_missing_or_mismatched() -> None:
    base = ledger_rows()
    base[0].update(
        {
            "promotion_eligible": True,
            "data_source": "databento_glbx_mdp3_mbo",
            "evidence_tier": "databento_mbo_executable",
            "evidence_blockers": [],
        }
    )
    base[-1].update(
        {
            "promotion_eligible": True,
            "data_source": "databento_other_feed",
            "evidence_tier": "databento_mbo_executable",
            "evidence_blockers": [],
        }
    )

    outcome = build_resolutions({"mismatch.jsonl": base}, resolved_at=NOW)[0]

    assert outcome["promotion_eligible"] is False
    assert "promotion_data_source_mismatch" in outcome["promotion_exclusion_reasons"]

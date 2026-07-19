from __future__ import annotations

import json

from strategies.kalshi_weather_execution import (
    LIVE_APPROVAL_PHRASE,
    build_order_payload,
    execution_preflight,
)


def test_v2_payload_maps_yes_and_no_to_single_book() -> None:
    yes = build_order_payload(ticker="KXTEST", outcome_side="YES", contracts=1, outcome_price=0.30, client_order_id="yes-1")
    no = build_order_payload(ticker="KXTEST", outcome_side="NO", contracts=1, outcome_price=0.72, client_order_id="no-1")

    assert yes["side"] == "bid"
    assert yes["price"] == "0.3000"
    assert no["side"] == "ask"
    assert no["price"] == "0.2800"
    assert yes["time_in_force"] == "fill_or_kill"
    assert yes["cancel_order_on_pause"] is True
    assert yes["self_trade_prevention_type"] == "taker_at_cross"


def test_order_payload_enforces_one_contract_and_five_dollar_cap() -> None:
    try:
        build_order_payload(ticker="KXTEST", outcome_side="YES", contracts=2, outcome_price=0.30, client_order_id="bad")
    except ValueError as exc:
        assert "one contract" in str(exc)
    else:
        raise AssertionError("two-contract order must fail")


def test_preflight_requires_readiness_credentials_and_explicit_ack(tmp_path) -> None:
    readiness = tmp_path / "readiness.json"
    readiness.write_text(json.dumps({"go_live_eligible": True, "blockers": []}), encoding="utf-8")

    blocked = execution_preflight(
        readiness_path=readiness,
        live_enabled=True,
        approval_ack="wrong",
        key_id="",
        private_key_path=tmp_path / "missing.key",
        manual_block_path=tmp_path / "manual-block.json",
    )
    assert blocked["allowed"] is False
    assert "approval_ack_missing" in blocked["blockers"]
    assert "credentials_missing" in blocked["blockers"]

    key = tmp_path / "kalshi.key"
    key.write_text("PRIVATE", encoding="utf-8")
    allowed = execution_preflight(
        readiness_path=readiness,
        live_enabled=True,
        approval_ack=LIVE_APPROVAL_PHRASE,
        key_id="key-id",
        private_key_path=key,
        manual_block_path=tmp_path / "manual-block.json",
    )
    assert allowed["allowed"] is True


def test_preflight_fails_on_readiness_or_manual_block(tmp_path) -> None:
    readiness = tmp_path / "readiness.json"
    readiness.write_text(json.dumps({"go_live_eligible": False, "blockers": ["insufficient_sample"]}), encoding="utf-8")
    key = tmp_path / "kalshi.key"
    key.write_text("PRIVATE", encoding="utf-8")
    manual = tmp_path / "manual-block.json"
    manual.write_text("{}", encoding="utf-8")

    result = execution_preflight(
        readiness_path=readiness,
        live_enabled=True,
        approval_ack=LIVE_APPROVAL_PHRASE,
        key_id="key-id",
        private_key_path=key,
        manual_block_path=manual,
    )
    assert result["allowed"] is False
    assert "readiness_not_passed" in result["blockers"]
    assert "manual_reset_required" in result["blockers"]

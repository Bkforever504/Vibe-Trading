from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pytest

from strategies.prop_rule_gate import AccountState
from strategies.topstepx_practice_adapter import (
    EXECUTION_CONFIRMATION,
    LOCAL_DEVICE_CONFIRMATION,
    PracticeExecutionConfig,
    PracticeSafetyError,
    ProjectXContract,
    TopstepXPracticeAdapter,
    parse_accounts,
    select_active_mes_contract,
    select_allowed_practice_account,
    to_eastern,
)


class FakeTransport:
    def __init__(self, responses: list[dict[str, Any]]) -> None:
        self.responses = list(responses)
        self.calls: list[dict[str, Any]] = []

    def post(self, url: str, payload: dict[str, Any], headers: dict[str, str]) -> dict[str, Any]:
        self.calls.append({"url": url, "payload": payload, "headers": headers})
        if not self.responses:
            raise AssertionError(f"Unexpected API call: {url}")
        response = self.responses.pop(0)
        if isinstance(response, BaseException):
            raise response
        return response


def account_payload(name: str = "PRACTICE", account_id: int = 42) -> dict[str, Any]:
    return {
        "success": True,
        "accounts": [{"id": account_id, "name": name, "balance": 150000, "canTrade": True, "isVisible": True}],
    }


def contract_payload() -> dict[str, Any]:
    return {
        "success": True,
        "contracts": [{
            "id": "CON.F.US.MES.U26",
            "name": "MESU6",
            "description": "Micro E-mini S&P September 2026",
            "tickSize": 0.25,
            "tickValue": 1.25,
            "activeContract": True,
            "symbolId": "F.US.MES",
        }],
    }


def practice_profile() -> dict[str, Any]:
    return {
        "firm": "Topstep",
        "account_type": "Practice",
        "automation": {"allowed": True, "status": "practice_only", "requires_local_device": True},
        "risk": {"max_daily_loss": 100, "max_trailing_drawdown": 2000, "max_contracts": 1},
        "consistency": {"enabled": True, "max_best_day_pct": 0.50},
        "unknown_rules_block": True,
    }


def enabled_config(tmp_path: Path) -> PracticeExecutionConfig:
    return PracticeExecutionConfig(
        allowed_account_id=42,
        execution_confirmation=EXECUTION_CONFIRMATION,
        local_device_confirmation=LOCAL_DEVICE_CONFIRMATION,
        journal_path=tmp_path / "orders.jsonl",
        block_file=tmp_path / "manual-reset.json",
    )


def test_eastern_conversion_handles_summer_and_winter_without_tzdata() -> None:
    assert to_eastern(datetime(2026, 7, 20, 14, 0, tzinfo=timezone.utc)).hour == 10
    assert to_eastern(datetime(2026, 1, 20, 15, 0, tzinfo=timezone.utc)).hour == 10


def test_account_selection_requires_id_and_standalone_practice_marker() -> None:
    accounts = parse_accounts(account_payload("TOPSTEPX PRACTICE 150K"))
    assert select_allowed_practice_account(accounts, 42).id == 42
    with pytest.raises(PracticeSafetyError, match="PRACTICE"):
        select_allowed_practice_account(parse_accounts(account_payload("50K COMBINE")), 42)
    with pytest.raises(PracticeSafetyError, match="ID"):
        select_allowed_practice_account(accounts, 99)


def test_mes_contract_selection_rejects_wrong_or_ambiguous_contract() -> None:
    mes = ProjectXContract("CON.F.US.MES.U26", "MESU6", "MES", 0.25, 1.25, True, "F.US.MES")
    assert select_active_mes_contract([mes]) == mes
    mnq = ProjectXContract("CON.F.US.MNQ.U26", "MNQU6", "MNQ", 0.25, 0.50, True, "F.US.MNQ")
    with pytest.raises(PracticeSafetyError, match="exactly one"):
        select_active_mes_contract([mnq])
    with pytest.raises(PracticeSafetyError, match="exactly one"):
        select_active_mes_contract([mes, mes])


def test_execution_is_disabled_before_any_order_api_call(tmp_path: Path) -> None:
    transport = FakeTransport([])
    adapter = TopstepXPracticeAdapter(
        username="user",
        api_key="key",
        config=PracticeExecutionConfig(allowed_account_id=42, journal_path=tmp_path / "x.jsonl"),
        transport=transport,
        now_fn=lambda: datetime(2026, 7, 20, 14, 0, tzinfo=timezone.utc),
    )
    with pytest.raises(PracticeSafetyError, match="confirmation"):
        adapter.place_practice_bracket_order(
            side="buy", size=1, stop_ticks=40, target_ticks=60,
            account_state=AccountState(150000, 150000, 0, 2000),
            rule_profile=practice_profile(),
        )
    assert transport.calls == []


def test_global_kill_switch_blocks_entry_before_api_calls(tmp_path: Path) -> None:
    config = enabled_config(tmp_path)
    config.block_file.write_text('{"status":"blocked"}', encoding="utf-8")
    transport = FakeTransport([])
    adapter = TopstepXPracticeAdapter(
        username="user", api_key="key", config=config, transport=transport,
        now_fn=lambda: datetime(2026, 7, 20, 14, 0, tzinfo=timezone.utc),
    )
    with pytest.raises(PracticeSafetyError, match="kill switch"):
        adapter.place_practice_bracket_order(
            side="buy", size=1, stop_ticks=40, target_ticks=60,
            account_state=AccountState(150000, 150000, 0, 2000),
            rule_profile=practice_profile(),
        )
    assert transport.calls == []


def test_practice_order_uses_one_mes_and_attached_brackets(tmp_path: Path) -> None:
    transport = FakeTransport([
        {"success": True, "token": "jwt"},
        account_payload(),
        contract_payload(),
        {"success": True, "positions": []},
        {"success": True, "orders": []},
        {"success": True, "orderId": 9056},
    ])
    adapter = TopstepXPracticeAdapter(
        username="user",
        api_key="key",
        config=enabled_config(tmp_path),
        transport=transport,
        now_fn=lambda: datetime(2026, 7, 20, 14, 0, tzinfo=timezone.utc),
    )
    adapter.login()
    record = adapter.place_practice_bracket_order(
        side="buy", size=1, stop_ticks=40, target_ticks=60,
        account_state=AccountState(150000, 150000, 0, 2000),
        rule_profile=practice_profile(),
        custom_tag="mes-practice-test-1",
    )
    order_call = transport.calls[-1]
    assert order_call["url"].endswith("/api/Order/place")
    assert order_call["payload"] == {
        "accountId": 42,
        "contractId": "CON.F.US.MES.U26",
        "type": 2,
        "side": 0,
        "size": 1,
        "customTag": "mes-practice-test-1",
        "stopLossBracket": {"ticks": 40, "type": 4},
        "takeProfitBracket": {"ticks": 60, "type": 1},
    }
    assert record["mode"] == "topstep_practice_only"
    assert record["risk_dollars"] == 50.0
    assert record["rule_gate"]["allowed"] is True


def test_adapter_rejects_outside_window_oversize_and_excess_stop(tmp_path: Path) -> None:
    base = dict(
        username="user",
        api_key="key",
        config=enabled_config(tmp_path),
        transport=FakeTransport([]),
    )
    adapter = TopstepXPracticeAdapter(
        **base,
        now_fn=lambda: datetime(2026, 7, 20, 13, 0, tzinfo=timezone.utc),
    )
    with pytest.raises(PracticeSafetyError, match="outside"):
        adapter.place_practice_bracket_order(
            side="buy", size=1, stop_ticks=40, target_ticks=60,
            account_state=AccountState(150000, 150000, 0, 2000),
            rule_profile=practice_profile(),
        )
    adapter.now_fn = lambda: datetime(2026, 7, 20, 14, 0, tzinfo=timezone.utc)
    with pytest.raises(PracticeSafetyError, match="one-MES"):
        adapter.place_practice_bracket_order(
            side="buy", size=2, stop_ticks=40, target_ticks=60,
            account_state=AccountState(150000, 150000, 0, 2000),
            rule_profile=practice_profile(),
        )
    with pytest.raises(PracticeSafetyError, match="Stop ticks"):
        adapter.place_practice_bracket_order(
            side="buy", size=1, stop_ticks=41, target_ticks=60,
            account_state=AccountState(150000, 150000, 0, 2000),
            rule_profile=practice_profile(),
        )


def test_rule_gate_blocks_before_position_and_order_queries(tmp_path: Path) -> None:
    transport = FakeTransport([
        {"success": True, "token": "jwt"}, account_payload(), contract_payload(),
    ])
    adapter = TopstepXPracticeAdapter(
        username="user", api_key="key", config=enabled_config(tmp_path), transport=transport,
        now_fn=lambda: datetime(2026, 7, 20, 14, 0, tzinfo=timezone.utc),
    )
    adapter.login()
    with pytest.raises(PracticeSafetyError, match="daily_loss_limit"):
        adapter.place_practice_bracket_order(
            side="sell", size=1, stop_ticks=40, target_ticks=60,
            account_state=AccountState(150000, 150000, -60, 2000),
            rule_profile=practice_profile(),
        )
    assert all(not call["url"].endswith("/api/Order/place") for call in transport.calls)


def test_open_position_blocks_entry(tmp_path: Path) -> None:
    transport = FakeTransport([
        {"success": True, "token": "jwt"}, account_payload(), contract_payload(),
        {"success": True, "positions": [{"contractId": "CON.F.US.MES.U26", "size": 1}]},
        {"success": True, "orders": []},
    ])
    adapter = TopstepXPracticeAdapter(
        username="user", api_key="key", config=enabled_config(tmp_path), transport=transport,
        now_fn=lambda: datetime(2026, 7, 20, 14, 0, tzinfo=timezone.utc),
    )
    adapter.login()
    with pytest.raises(PracticeSafetyError, match="open position"):
        adapter.place_practice_bracket_order(
            side="buy", size=1, stop_ticks=40, target_ticks=60,
            account_state=AccountState(150000, 150000, 0, 2000),
            rule_profile=practice_profile(),
        )


def test_accepted_journal_blocks_second_entry_same_day(tmp_path: Path) -> None:
    journal = tmp_path / "orders.jsonl"
    journal.write_text('{"session_date":"2026-07-20","status":"accepted"}\n', encoding="utf-8")
    adapter = TopstepXPracticeAdapter(
        username="user", api_key="key", config=enabled_config(tmp_path), transport=FakeTransport([]),
        now_fn=lambda: datetime(2026, 7, 20, 14, 0, tzinfo=timezone.utc),
    )
    with pytest.raises(PracticeSafetyError, match="already exists"):
        adapter.place_practice_bracket_order(
            side="buy", size=1, stop_ticks=40, target_ticks=60,
            account_state=AccountState(150000, 150000, 0, 2000),
            rule_profile=practice_profile(),
        )


def test_bar_request_is_sim_only_and_excludes_partial_bar(tmp_path: Path) -> None:
    transport = FakeTransport([{"success": True, "token": "jwt"}, {"success": True, "bars": []}])
    adapter = TopstepXPracticeAdapter(username="user", api_key="key", transport=transport)
    adapter.login()
    contract = ProjectXContract("CON.F.US.MES.U26", "MESU6", "MES", 0.25, 1.25, True, "F.US.MES")
    adapter.retrieve_bars(
        contract,
        start=datetime(2026, 7, 1, tzinfo=timezone.utc),
        end=datetime(2026, 7, 2, tzinfo=timezone.utc),
        minutes=5,
    )
    payload = transport.calls[-1]["payload"]
    assert payload["live"] is False
    assert payload["unit"] == 2
    assert payload["unitNumber"] == 5
    assert payload["includePartialBar"] is False


def test_uncertain_order_response_blocks_same_day_retry(tmp_path: Path) -> None:
    from strategies.topstepx_practice_adapter import ProjectXAPIError

    transport = FakeTransport([
        {"success": True, "token": "jwt"}, account_payload(), contract_payload(),
        {"success": True, "positions": []}, {"success": True, "orders": []},
        ProjectXAPIError("connection dropped after submit"),
    ])
    adapter = TopstepXPracticeAdapter(
        username="user", api_key="key", config=enabled_config(tmp_path), transport=transport,
        now_fn=lambda: datetime(2026, 7, 20, 14, 0, tzinfo=timezone.utc),
    )
    adapter.login()
    kwargs = dict(
        side="buy", size=1, stop_ticks=40, target_ticks=60,
        account_state=AccountState(150000, 150000, 0, 2000),
        rule_profile=practice_profile(),
    )
    with pytest.raises(ProjectXAPIError, match="dropped"):
        adapter.place_practice_bracket_order(**kwargs)
    calls_after_unknown = len(transport.calls)
    with pytest.raises(PracticeSafetyError, match="already exists"):
        adapter.place_practice_bracket_order(**kwargs)
    assert len(transport.calls) == calls_after_unknown


def test_emergency_flatten_cancels_mes_orders_then_closes_position_despite_kill_switch(tmp_path: Path) -> None:
    config = enabled_config(tmp_path)
    config.block_file.write_text('{"status":"blocked"}', encoding="utf-8")
    transport = FakeTransport([
        {"success": True, "token": "jwt"}, account_payload(), contract_payload(),
        {"success": True, "orders": [{"id": 77, "contractId": "CON.F.US.MES.U26"}]},
        {"success": True, "positions": [{"id": 88, "contractId": "CON.F.US.MES.U26", "size": 1}]},
        {"success": True}, {"success": True},
    ])
    adapter = TopstepXPracticeAdapter(username="user", api_key="key", config=config, transport=transport)
    adapter.login()
    result = adapter.emergency_flatten_practice_mes()
    assert result["canceled_order_ids"] == [77]
    assert result["position_close_requested"] is True
    assert transport.calls[-2]["url"].endswith("/api/Order/cancel")
    assert transport.calls[-1]["url"].endswith("/api/Position/closeContract")

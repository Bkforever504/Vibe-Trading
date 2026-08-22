from __future__ import annotations

import json
from pathlib import Path

from strategies.order_envelope import OrderIntent, client_order_id_for, evaluate_order_intent, submit_order


def test_client_order_id_is_deterministic_and_alpaca_safe() -> None:
    intent = OrderIntent("strategy-a", "SPY260821C00770000", "2026-08-20T14:31:00Z", "2026-08-20T14:30:00Z")

    assert client_order_id_for(intent) == client_order_id_for(intent)
    assert len(client_order_id_for(intent)) == 48


def test_envelope_blocks_stale_kill_switch_and_reconciliation_collision(tmp_path: Path) -> None:
    intent = OrderIntent("strategy-a", "SPY", "2026-08-20T14:31:00Z", "2026-08-20T14:30:00Z", freshness="stale")
    order_id = client_order_id_for(intent)
    reconciliation = tmp_path / "reconciliation.jsonl"
    reconciliation.write_text(json.dumps({"client_order_id": order_id}) + "\n", encoding="utf-8")
    kill_switch = tmp_path / "MANUAL_RESET_REQUIRED.json"
    kill_switch.write_text("{}", encoding="utf-8")

    result = evaluate_order_intent(intent, reconciliation_log=reconciliation, kill_switch_file=kill_switch)

    assert result["allowed"] is False
    assert result["submitted"] is False
    assert result["execution_enabled"] is False
    assert result["can_submit_orders"] is False
    assert {"stale_freshness", "kill_switch_red", "reconciliation_log_collision"} <= set(result["blockers"])


def test_submit_wrapper_never_invokes_submitter(tmp_path: Path) -> None:
    calls: list[dict] = []
    intent = OrderIntent("strategy-a", "SPY", "2026-08-20T14:31:00Z", "2026-08-20T14:30:00Z")

    result = submit_order(
        intent,
        {"symbol": "SPY", "qty": 1},
        lambda payload: calls.append(dict(payload)),
        event_log=tmp_path / "events.jsonl",
        reconciliation_log=tmp_path / "reconciliation.jsonl",
        kill_switch_file=tmp_path / "kill-switch.json",
    )

    assert calls == []
    assert result["submitted"] is False
    assert "execution_disabled" in result["blockers"]


from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from agent import notifier
from scripts import shadow_alert_runner as runner
from scripts import shadow_ops
from scripts import shadow_system_heartbeat as heartbeat
from scripts import sunday_shadow_preflight as preflight


NOW = datetime(2026, 8, 24, 12, 0, tzinfo=timezone.utc)


def test_notifier_uses_env_first_redacts_and_disables_mentions(tmp_path: Path) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text("DISCORD_WEBHOOK_URL=https://discord.com/api/webhooks/file/token\n", encoding="utf-8")
    assert notifier._env_value(
        "DISCORD_WEBHOOK_URL",
        environ={"DISCORD_WEBHOOK_URL": "https://discord.com/api/webhooks/env/token"},
        env_path=env_file,
    ).endswith("/env/token")

    sent: list[tuple[str, dict, float]] = []
    result = notifier.send_discord(
        "@everyone test DATABENTO_API_KEY=db-secret-value",
        webhook_url="https://discord.com/api/webhooks/fixture/token",
        transport=lambda url, payload, timeout: sent.append((url, payload, timeout)),
    )
    assert result == {"status": "sent", "sent": True, "chunks": 1}
    assert sent[0][1]["allowed_mentions"] == {"parse": []}
    assert "db-secret-value" not in sent[0][1]["content"]


def test_notifier_rejects_non_discord_or_non_https_webhooks() -> None:
    with pytest.raises(ValueError, match="official_https_host"):
        notifier.send_discord("x", webhook_url="https://example.com/api/webhooks/1/2")
    with pytest.raises(ValueError, match="official_https_host"):
        notifier.send_discord("x", webhook_url="http://discord.com/api/webhooks/1/2")


def test_failure_counter_auto_halts_at_three_and_kill_switch_is_file_drop(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(shadow_ops, "HEALTH_DIR", tmp_path / "health")
    monkeypatch.setattr(shadow_ops, "KILL_SWITCH", tmp_path / "KILL_SWITCH")
    for expected in (1, 2, 3):
        state = shadow_ops.record_failure("scanner-a", error_type="RuntimeError", reason="fixture")
        assert state["consecutive_failures"] == expected
    assert shadow_ops.is_halted("scanner-a") is True
    assert shadow_ops.record_success("scanner-a")["halted"] is True
    assert shadow_ops.clear_halt("scanner-a")["halted"] is False
    shadow_ops.KILL_SWITCH.write_text("halt\n", encoding="utf-8")
    assert shadow_ops.kill_switch_active() is True


def test_entry_and_resolve_alerts_include_levels_grades_and_outcomes() -> None:
    entries = [
        {
            "event_type": "entry",
            "should_enter": True,
            "symbol": "AAPL",
            "direction": "long",
            "entry_price": 100,
            "stop_price": 98,
            "t1_price": 102,
            "t2_price": 104,
            "grade": 0.91,
            "dashboard_rank_in_top_n": 1,
        }
    ]
    message = runner.format_entry_alert("Scout", entries)
    assert "AAPL LONG" in message
    assert "entry=100" in message and "T2=104" in message and "grade=0.910" in message

    exits = [
        {"event_type": "exit", "symbol": "AAPL", "outcome": "win", "net_dollar": 4.2, "exit_reason": "t2_after_t1"},
        {"event_type": "exit", "symbol": "MSFT", "outcome": "loss", "net_dollar": -2.0, "exit_reason": "stop_before_t1"},
    ]
    summary = runner.format_resolve_alert("Scout", exits)
    assert "Setups scanned=0" in summary
    assert "W/L/Flat=1/1/0" in summary
    assert "AAPL win net=$4.20" in summary


def _ready_tasks() -> list[dict]:
    return [
        {"TaskPath": path, "TaskName": name, "State": "Ready", "LastTaskResult": 0}
        for path, name in heartbeat.EXPECTED_TASKS
    ]


def _fresh_report(path: Path, stamp: datetime = NOW) -> None:
    path.write_text(json.dumps({"generated_at": stamp.isoformat()}), encoding="utf-8")


def test_heartbeat_passes_ready_tasks_and_fresh_sources_then_fails_stale_hmm(tmp_path: Path, monkeypatch) -> None:
    hmm = tmp_path / "hmm.json"
    catalyst = tmp_path / "catalyst.json"
    _fresh_report(hmm)
    _fresh_report(catalyst)
    monkeypatch.setattr(heartbeat, "is_halted", lambda _name: False)
    monkeypatch.setattr(heartbeat, "read_state", lambda _name: {})
    monkeypatch.setattr(heartbeat, "kill_switch_active", lambda: False)
    databento = tmp_path / "databento.json"
    mnq_evidence = tmp_path / "mnq-evidence.json"
    _fresh_report(databento, NOW)
    _fresh_report(mnq_evidence, NOW)
    report = heartbeat.build_report(now=NOW, task_rows=_ready_tasks(), hmm_path=hmm, catalyst_path=catalyst,
                                    databento_capability_path=databento, mnq_evidence_path=mnq_evidence)
    assert report["status"] == "PASS"
    assert "MES v2 alive: OK" in heartbeat.format_heartbeat(report)

    _fresh_report(hmm, NOW - timedelta(days=4))
    stale = heartbeat.build_report(now=NOW, task_rows=_ready_tasks(), hmm_path=hmm, catalyst_path=catalyst,
                                   databento_capability_path=databento, mnq_evidence_path=mnq_evidence)
    assert stale["status"] == "FAIL"
    assert stale["hmm"]["fresh"] is False


def test_preflight_no_network_validates_spec_universe_tasks_and_sources(tmp_path: Path, monkeypatch) -> None:
    hmm = tmp_path / "hmm.json"
    catalyst = tmp_path / "catalyst.json"
    _fresh_report(hmm)
    _fresh_report(catalyst)
    monkeypatch.setattr(preflight, "HMM_PATH", hmm)
    monkeypatch.setattr(preflight, "CATALYST_PATH", catalyst)
    monkeypatch.setattr(preflight, "kill_switch_active", lambda: False)
    report = preflight.run_preflight(now=NOW, network=False, task_rows=_ready_tasks())
    assert report["status"] == "PASS"
    assert report["market_data"]["mode"] == "no_network_smoke"
    assert report["execution_enabled"] is False
    assert report["can_submit_orders"] is False


def test_registration_scripts_define_required_cadences_and_master_scope() -> None:
    root = Path(__file__).resolve().parents[2]
    ops = (root / "scripts" / "register_shadow_ops_tasks.ps1").read_text(encoding="utf-8")
    assert '-At "09:00"' in ops and '-At "12:00"' in ops and '-At "15:30"' in ops
    assert '-At "08:40"' in ops and 'HMMRegimeScanner' in ops
    assert '-DaysOfWeek Sunday -At "20:00"' in ops
    master = (root / "scripts" / "register_trading_alert_system.ps1").read_text(encoding="utf-8")
    assert "register_mes_v2_shadow_tasks.ps1" in master
    assert "register_equity_orb_scout_v1_task.ps1" in master
    assert "register_equity_orb_scout_v2_task.ps1" in master
    assert "register_monday_checkin_task.ps1" in master
    assert "register_shadow_ops_tasks.ps1" in master
    assert "iwm_options_bot.py" not in master


def test_eod_runner_is_deterministic_and_does_not_launch_an_agent() -> None:
    root = Path(__file__).resolve().parents[2]
    runner_text = (root / "scripts" / "run_monday_checkin.ps1").read_text(encoding="utf-8")
    assert "eod_shadow_checkin.py" in runner_text
    assert "claude" not in runner_text.lower()
    assert "dangerously-skip-permissions" not in runner_text

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


def test_scanner_runners_use_policy_safe_system_python_resolver() -> None:
    root = Path(__file__).resolve().parents[2]
    resolver = (root / "scripts" / "resolve_vibe_python.ps1").read_text(encoding="utf-8")
    runner_names = (
        "run_deep_liquid_universe_scanner.ps1",
        "run_equity_orb_scout_v1_shadow.ps1",
        "run_equity_orb_scout_v2_shadow.ps1",
        "run_gex_scanner.ps1",
        "run_hurst_regime_scanner.ps1",
        "run_ivr_scanner.ps1",
        "run_liquid_options_edge_shadow.ps1",
        "run_micro_momentum_paper.ps1",
        "run_mnq_smt_family_databento_regrader.ps1",
        "run_opening_range_breadth_scanner.ps1",
        "run_portfolio_concentration_monitor.ps1",
        "run_premarket_ema_retest_shadow_logger.ps1",
        "run_profitability_control_plane.ps1",
        "run_realized_implied_vol_scanner.ps1",
    )

    assert "Get-Command python -CommandType Application" in resolver
    assert "repository .venv" in resolver
    for runner_name in runner_names:
        runner = (root / "scripts" / runner_name).read_text(encoding="utf-8")
        assert "Get-VibePython" in runner
        assert ".venv/Scripts/python.exe" not in runner
        assert ".venv\\Scripts\\python.exe" not in runner


def test_uv_shadow_runners_pin_statistical_gate_dependency() -> None:
    root = Path(__file__).resolve().parents[2]
    for runner_name in ("run_mes_orb_0932_vix_v2_shadow.ps1", "run_mnq_smt_family_shadow.ps1"):
        runner = (root / "scripts" / runner_name).read_text(encoding="utf-8")
        assert "--with purgedcv==0.1.6" in runner


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
    assert result == {"status": "sent", "sent": True, "chunks": 1,
                      "receipts": [{"discord_message_id": None, "discord_delivered_ts": None}]}
    assert sent[0][0].endswith("?wait=true")
    assert sent[0][1]["allowed_mentions"] == {"parse": []}
    assert "db-secret-value" not in sent[0][1]["content"]


def test_notifier_rejects_non_discord_or_non_https_webhooks() -> None:
    with pytest.raises(ValueError, match="official_https_host"):
        notifier.send_discord("x", webhook_url="https://example.com/api/webhooks/1/2")
    with pytest.raises(ValueError, match="official_https_host"):
        notifier.send_discord("x", webhook_url="http://discord.com/api/webhooks/1/2")


def test_embed_notifier_allows_here_only_when_explicitly_enabled() -> None:
    sent: list[tuple[str, dict, float]] = []
    result = notifier.send_discord_embed(
        title="A+ CRM",
        description="confirmed",
        content="@here A+ trade alert",
        fields=[{"name": "Entry", "value": "250.00", "inline": True}],
        webhook_url="https://discord.com/api/webhooks/fixture/token",
        transport=lambda url, payload, timeout: sent.append((url, payload, timeout)),
        allow_mentions=True,
    )

    assert result["sent"] is True
    assert sent[0][1]["allowed_mentions"] == {"parse": ["everyone"]}
    assert sent[0][1]["embeds"][0]["color"] == 0xE53935

    sent.clear()
    notifier.send_discord_embed(
        title="A+ CRM",
        description="confirmed",
        content="@here A+ trade alert",
        webhook_url="https://discord.com/api/webhooks/fixture/token",
        transport=lambda url, payload, timeout: sent.append((url, payload, timeout)),
        allow_mentions=False,
    )
    assert sent[0][1]["allowed_mentions"] == {"parse": []}


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
    pattern_outcomes = tmp_path / "pattern_grader_outcomes.jsonl"
    pattern_outcomes.write_text(
        json.dumps({"resolved_at": NOW.isoformat().replace("+00:00", "Z"), "detection_id": "X"}) + "\n",
        encoding="utf-8",
    )
    _fresh_report(databento, NOW)
    _fresh_report(mnq_evidence, NOW)
    report = heartbeat.build_report(now=NOW, task_rows=_ready_tasks(), hmm_path=hmm, catalyst_path=catalyst,
                                    databento_capability_path=databento, mnq_evidence_path=mnq_evidence,
                                    pattern_outcomes_path=pattern_outcomes)
    assert report["status"] == "PASS"
    assert report["aplus_spotlight"]["alive"] is True
    assert "MES v2 alive: OK" in heartbeat.format_heartbeat(report)
    assert "Pattern grader alive: OK" in heartbeat.format_heartbeat(report)

    _fresh_report(hmm, NOW - timedelta(days=4))
    stale = heartbeat.build_report(now=NOW, task_rows=_ready_tasks(), hmm_path=hmm, catalyst_path=catalyst,
                                   databento_capability_path=databento, mnq_evidence_path=mnq_evidence,
                                   pattern_outcomes_path=pattern_outcomes)
    assert stale["status"] == "FAIL"
    assert stale["hmm"]["fresh"] is False


def test_stale_databento_research_does_not_fail_core_operations(tmp_path: Path, monkeypatch) -> None:
    hmm = tmp_path / "hmm.json"
    catalyst = tmp_path / "catalyst.json"
    databento = tmp_path / "databento.json"
    mnq_evidence = tmp_path / "mnq-evidence.json"
    pattern_outcomes = tmp_path / "pattern_grader_outcomes.jsonl"
    _fresh_report(hmm)
    _fresh_report(catalyst)
    _fresh_report(databento, NOW - timedelta(days=3))
    _fresh_report(mnq_evidence, NOW - timedelta(days=3))
    pattern_outcomes.write_text(
        json.dumps({"resolved_at": NOW.isoformat().replace("+00:00", "Z")}) + "\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(heartbeat, "is_halted", lambda _name: False)
    monkeypatch.setattr(heartbeat, "read_state", lambda _name: {})
    monkeypatch.setattr(heartbeat, "kill_switch_active", lambda: False)

    report = heartbeat.build_report(
        now=NOW,
        task_rows=_ready_tasks(),
        hmm_path=hmm,
        catalyst_path=catalyst,
        databento_capability_path=databento,
        mnq_evidence_path=mnq_evidence,
        pattern_outcomes_path=pattern_outcomes,
    )

    assert report["status"] == "PASS"
    assert report["status_scope"] == "core_scheduled_operations"
    assert report["research_status"] == "DEGRADED"


def test_heartbeat_fails_when_pattern_outcomes_ledger_did_not_grow(tmp_path: Path, monkeypatch) -> None:
    hmm = tmp_path / "hmm.json"
    catalyst = tmp_path / "catalyst.json"
    databento = tmp_path / "databento.json"
    mnq_evidence = tmp_path / "mnq-evidence.json"
    _fresh_report(hmm)
    _fresh_report(catalyst)
    _fresh_report(databento, NOW)
    _fresh_report(mnq_evidence, NOW)
    monkeypatch.setattr(heartbeat, "is_halted", lambda _name: False)
    monkeypatch.setattr(heartbeat, "read_state", lambda _name: {})
    monkeypatch.setattr(heartbeat, "kill_switch_active", lambda: False)
    stale_outcomes = tmp_path / "pattern_grader_outcomes.jsonl"
    stale_outcomes.write_text(
        json.dumps({"resolved_at": (NOW - timedelta(days=3)).isoformat().replace("+00:00", "Z")}) + "\n",
        encoding="utf-8",
    )

    report = heartbeat.build_report(
        now=NOW, task_rows=_ready_tasks(), hmm_path=hmm, catalyst_path=catalyst,
        databento_capability_path=databento, mnq_evidence_path=mnq_evidence,
        pattern_outcomes_path=stale_outcomes,
    )
    assert report["status"] == "FAIL"
    assert report["pattern_outcomes_ledger"]["fresh"] is False
    assert report["pattern_grader"]["alive"] is False


def test_heartbeat_does_not_create_circular_dependency_on_its_consumers() -> None:
    assert ("\\", "IntradayOpportunityRadar") in heartbeat.EXPECTED_TASKS
    assert ("\\VibeTrade\\", "APlusSpotlight") in heartbeat.EXPECTED_TASKS
    assert ("\\VibeTrade\\", "ShadowSystemHeartbeat") in heartbeat.OBSERVABILITY_TASKS
    assert ("\\VibeTrade\\", "EodShadowCheckin") in heartbeat.OBSERVABILITY_TASKS
    assert ("\\VibeTrade\\", "ShadowSystemHeartbeat") not in heartbeat.OPS_TASKS
    assert ("\\VibeTrade\\", "EodShadowCheckin") not in heartbeat.OPS_TASKS


def test_scanner_gap_health_preserves_intraday_outage_after_recovery_and_close(
    tmp_path: Path,
) -> None:
    now = datetime(2026, 8, 26, 15, 0, tzinfo=timezone.utc)  # 10:00 CT
    fresh = tmp_path / "fresh.jsonl"
    stale = tmp_path / "stale.jsonl"
    fresh_stamps = [
        datetime(2026, 8, 26, 13, 35, tzinfo=timezone.utc) + timedelta(minutes=10 * index)
        for index in range(9)
    ]
    fresh.write_text("\n".join(json.dumps({"generated_at": stamp.isoformat()}) for stamp in fresh_stamps) + "\n", encoding="utf-8")
    stale.write_text("\n".join(json.dumps({"generated_at": stamp.isoformat()}) for stamp in (
        datetime(2026, 8, 26, 13, 35, tzinfo=timezone.utc),
        datetime(2026, 8, 26, 13, 40, tzinfo=timezone.utc),
        now - timedelta(minutes=5),
    )) + "\n", encoding="utf-8")

    report = heartbeat.report_scanner_gaps(
        (("fresh", fresh), ("stale", stale)), now=now, max_gap_minutes=15
    )

    assert report["in_regular_session"] is True
    assert report["any_stalled"] is True
    assert report["status"] == "stalled"
    assert {row["name"]: row["stalled"] for row in report["scanners"]} == {
        "fresh": False,
        "stale": True,
    }

    assert next(row for row in report["scanners"] if row["name"] == "stale")["observation_count"] == 3

    after_hours = heartbeat.report_scanner_gaps(
        (("stale", stale),), now=datetime(2026, 8, 26, 21, 30, tzinfo=timezone.utc), max_gap_minutes=15
    )
    assert after_hours["in_regular_session"] is False
    assert after_hours["any_stalled"] is True
    assert after_hours["worst_gap_minutes"] > 15


def test_futures_coverage_reports_capability_without_implying_no_move(tmp_path: Path) -> None:
    capability = tmp_path / "databento.json"
    capability.write_text(json.dumps({"mbo_available": True}), encoding="utf-8")
    assert heartbeat.report_futures_coverage(capability)["state"] == "live_mbo"

    capability.write_text(json.dumps({"delayed_proxy": True}), encoding="utf-8")
    assert heartbeat.report_futures_coverage(capability)["state"] == "delayed_proxy"

    capability.write_text(json.dumps({"historical_regrade_supported": True}), encoding="utf-8")
    assert heartbeat.report_futures_coverage(capability)["state"] == "delayed_proxy"

    capability.write_text("{}", encoding="utf-8")
    assert heartbeat.report_futures_coverage(capability)["state"] == "unavailable"


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

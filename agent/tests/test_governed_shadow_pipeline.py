from datetime import datetime, timezone
import json
from pathlib import Path

from scripts import governed_shadow_alert as alert
from scripts import governed_shadow_lifecycle as lifecycle
from scripts import governed_shadow_outcome as outcome
from scripts import governed_shadow_rule_update as rules


def _decision(*, accepted: bool = True, event_id: str = "decision-1", setup: str = "orb"):
    return {
        "event_id": event_id,
        "candidate_key": f"SPY|LONG|{setup}|2026-09-02T14:35:00Z|100",
        "decision": "shadow_accepted" if accepted else "shadow_rejected",
        "blockers": [] if accepted else ["consensus_stand_aside"],
        "candidate": {
            "symbol": "SPY", "direction": "LONG", "setup": setup, "grade": "B+",
            "trigger": 100.0, "stop": 99.0, "target": 102.0,
            "bar_completed_at": "2026-09-02T14:35:00Z",
        },
        "execution_enabled": False,
        "can_submit_orders": False,
    }


def test_alert_retries_then_succeeds_without_exposing_webhook(monkeypatch) -> None:
    calls = []

    class Response:
        def __enter__(self): return self
        def __exit__(self, *_args): return False
        def read(self):
            return json.dumps({"id": "123456789", "timestamp": "2026-09-04T15:00:04Z"}).encode()

    def opener(request, timeout):
        calls.append((request.full_url, timeout))
        if len(calls) < 3:
            raise TimeoutError("secret URL should not persist")
        return Response()

    monkeypatch.setattr(alert, "webhook_url", lambda: "https://discord.invalid/secret")
    monkeypatch.setattr(alert.time, "sleep", lambda _seconds: None)
    result = alert.deliver("message", opener=opener)
    assert result["delivered"] is True
    assert result["attempts"] == 3
    assert result["discord_message_id"] == "123456789"
    assert result["discord_delivered_ts"] == "2026-09-04T15:00:04Z"
    assert "wait=true" in calls[-1][0]


def test_stale_alert_is_archived_without_delivery(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(alert, "MAX_LIVE_ALERT_AGE", alert.timedelta(seconds=0))
    calls = []
    report = alert.run(
        {"decisions": [_decision()]}, send=True,
        state_path=tmp_path / "state.json", report_path=tmp_path / "report.json",
        event_path=tmp_path / "events.jsonl",
        sender=lambda message: calls.append(message) or {"delivered": True, "attempts": 1, "error_class": None},
    )
    assert calls == []
    assert report["stale_skipped"] == 1
    assert report["pending_delivery"] == 0


def test_naive_alert_timestamp_is_interpreted_as_utc() -> None:
    row = _decision()
    row["candidate"]["bar_completed_at"] = "2026-09-02T14:35:00"
    assert alert._is_fresh(row, now=datetime(2026, 9, 2, 14, 40, tzinfo=timezone.utc)) is True


def test_rejected_research_and_duplicate_daily_map_rows_stay_off_discord(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(alert, "_is_fresh", lambda *_args, **_kwargs: True)
    core = _decision(accepted=False, event_id="core")
    core["candidate"]["lane"] = "CORE_INDEX_SHADOW"
    standard = _decision(accepted=False, event_id="standard")
    standard["candidate"]["lane"] = "STANDARD_SHADOW"
    mapped = _decision(accepted=False, event_id="mapped")
    mapped["candidate"]["lane"] = "DAILY_MAP_3M_SHADOW"
    messages = []

    report = alert.run(
        {"decisions": [core, standard, mapped]}, send=True,
        state_path=tmp_path / "state.json", report_path=tmp_path / "report.json",
        event_path=tmp_path / "events.jsonl",
        sender=lambda message: messages.append(message) or {"delivered": True, "attempts": 1, "error_class": None},
    )

    assert messages == []
    assert report["alerts_sent"] == 0
    assert report["dashboard_only"] == 3


def test_lifecycle_is_created_only_after_acceptance() -> None:
    assert lifecycle.build_plan(_decision(accepted=False)) is None
    plan = lifecycle.build_plan(_decision(accepted=True))
    assert plan is not None
    assert plan["state"] == "open_shadow_simulation"
    assert plan["execution_enabled"] is False
    assert plan["can_submit_orders"] is False


def test_outcome_uses_only_post_decision_bars_and_resolves_target() -> None:
    bars = [
        {"t": "2026-09-02T14:30:00Z", "h": 1000, "l": 1, "c": 500},
        {"t": "2026-09-02T14:35:00Z", "h": 101.0, "l": 99.5, "c": 100.8},
        {"t": "2026-09-02T14:40:00Z", "h": 102.2, "l": 100.5, "c": 102.0},
    ]
    result = outcome.resolve_decision(
        _decision(), bars, now=datetime(2026, 9, 2, 15, 40, tzinfo=timezone.utc),
    )
    assert result is not None
    assert result["terminal_event"] == "target"
    assert result["outcome_r"] == 2.0
    assert result["observed_bar_count"] == 2
    assert result["reconciliation_status"] == "underlying_proxy_reconciled"


def test_same_bar_stop_and_target_is_excluded_as_ambiguous() -> None:
    result = outcome.resolve_decision(
        _decision(),
        [{"t": "2026-09-02T14:35:00Z", "h": 103, "l": 98, "c": 101}],
        now=datetime(2026, 9, 2, 15, 40, tzinfo=timezone.utc),
    )
    assert result is not None
    assert result["reconciliation_status"] == "ambiguous_excluded"
    assert result["outcome_r"] is None


def test_after_hours_decision_is_not_left_in_ready_queue() -> None:
    row = _decision()
    row["candidate"]["bar_completed_at"] = "2026-09-02T20:05:00Z"  # 16:05 ET
    assert outcome.ready_decisions(
        [row], set(), now=datetime(2026, 9, 3, 14, 0, tzinfo=timezone.utc),
    ) == []
    opened = outcome._timestamp(row["candidate"]["bar_completed_at"])
    end, truncated = outcome._resolution_end(opened)
    assert end >= opened
    assert truncated is True


def test_rule_updates_require_sample_and_never_auto_mutate() -> None:
    decisions = [_decision(accepted=False, event_id=f"d-{index}") for index in range(10)]
    outcomes = [
        {
            "decision_event_id": f"d-{index}", "setup": "orb", "direction": "LONG",
            "governed_decision": "shadow_rejected", "reconciliation_status": "underlying_proxy_reconciled",
            "outcome_r": 1.0 if index < 7 else -1.0,
        }
        for index in range(10)
    ]
    nomination = rules.build_nominations(outcomes, decisions)[0]
    assert nomination["action"] == "nominate_veto_calibration_review"
    assert nomination["automatic_parameter_changes"] is False
    assert nomination["can_submit_orders"] is False


def test_runner_enforces_exact_governed_pipeline_order() -> None:
    runner = (Path(__file__).resolve().parents[2] / "scripts" / "run_intraday_opportunity_radar.ps1").read_text(encoding="utf-8")
    names = [
        "simple_price_action_alerts.py", "institutional_confluence_shadow.py", "governed_shadow_decision.py", "governed_shadow_alert.py",
        "governed_shadow_lifecycle.py", "governed_shadow_outcome.py", "governed_shadow_rule_update.py",
    ]
    positions = [runner.index(name) for name in names]
    assert positions == sorted(positions)
    assert "simple_price_action_alerts.py --alert" not in runner


def test_runner_records_fail_honest_envelope_before_final_dashboard() -> None:
    runner = (Path(__file__).resolve().parents[2] / "scripts" / "run_intraday_opportunity_radar.ps1").read_text(encoding="utf-8")
    assert "operational_run_envelope.py start" in runner
    assert "operational_run_envelope.py', 'finish'" in runner
    assert "--status error" in runner
    assert "$EnvelopeFailureClass = if ($delta -lt 1) { 'silent_failure' }" in runner
    assert "$AlertReport.stale_skipped" in runner
    assert "$AlertReport.delivery_failures" in runner
    assert "$AlertReport.pending_delivery" in runner
    assert "RequiredAlertFields" in runner
    assert "alert report invalid nonnegative count" in runner
    assert "alert report event counts do not reconcile" in runner
    assert "alert report predates this run" in runner
    assert "alert delivery report missing" in runner
    assert runner.index("operational_run_envelope.py', 'finish'") < runner.index('Log-Line "STEP generate_dashboard_final"')


def test_runner_wrapper_health_is_written_from_final_envelope_not_early_append_success() -> None:
    runner = (Path(__file__).resolve().parents[2] / "scripts" / "run_intraday_opportunity_radar.ps1").read_text(encoding="utf-8")
    finish = runner.index("& python @EnvelopeArgs")
    success_health = runner.index("Write-Health -status $EnvelopeStatus")
    assert success_health > finish
    assert "Write-Health -status 'ok' -detail 'appended row'" not in runner

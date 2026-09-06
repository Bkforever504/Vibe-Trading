from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from scripts.operational_run_envelope import RunEnvelopeStore, classify_failure, redact_error


def test_success_writes_latest_append_only_ledger_and_healthy_report(tmp_path: Path) -> None:
    store = RunEnvelopeStore(tmp_path / "health" / "run-envelopes")
    observed = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    started = store.start("intraday-radar", scheduled_for=observed, input_count=40)
    finished = store.finish(
        "intraday-radar", run_id=started["run_id"], status="success", exit_code=0,
        data_as_of=observed, output_count=6,
        alerts_attempted=2, alerts_delivered=2,
    )
    assert finished["status"] == "success"
    assert finished["breaker_state"] == "CLOSED"
    assert finished["last_success_at"]
    rows = [json.loads(line) for line in store.ledger_path.read_text(encoding="utf-8").splitlines()]
    assert [row["event"] for row in rows] == ["started", "finished"]
    assert json.loads(store.report_path.read_text(encoding="utf-8"))["status"] == "healthy"


@pytest.mark.parametrize("status", ["timeout", "partial", "stale", "delivery_failure"])
def test_non_success_states_never_render_as_success(tmp_path: Path, status: str) -> None:
    store = RunEnvelopeStore(tmp_path / "health" / "run-envelopes")
    started = store.start("scanner")
    finished = store.finish("scanner", run_id=started["run_id"], status=status, error=status)
    assert finished["status"] not in {"success", "completed", "ok"}
    assert json.loads(store.report_path.read_text(encoding="utf-8"))["status"] == "attention"


def test_delivery_mismatch_forces_failure_and_errors_are_redacted(tmp_path: Path) -> None:
    store = RunEnvelopeStore(tmp_path / "health" / "run-envelopes")
    started = store.start("alerts")
    finished = store.finish(
        "alerts", run_id=started["run_id"], status="success",
        alerts_attempted=2, alerts_delivered=1,
        error="token=abc https://discord.com/api/webhooks/123/secret",
    )
    assert finished["status"] == "delivery_failure"
    assert finished["failure_class"] == "delivery_failure"
    assert "abc" not in finished["error"]
    assert "123/secret" not in finished["error"]


def test_breaker_persists_and_requires_explicit_clear(tmp_path: Path) -> None:
    root = tmp_path / "health" / "run-envelopes"
    store = RunEnvelopeStore(root, failure_threshold=3)
    for _ in range(3):
        started = store.start("provider")
        store.finish("provider", run_id=started["run_id"], status="error", exit_code=1, error="connection")
    assert RunEnvelopeStore(root).breaker("provider")["state"] == "OPEN"

    started = store.start("provider")
    recovered = store.finish("provider", run_id=started["run_id"], status="success")
    assert recovered["breaker_state"] == "OPEN"
    assert store.clear_breaker("provider")["state"] == "CLOSED"


def test_invalid_exit_code_and_malformed_alert_counts_fail_closed(tmp_path: Path) -> None:
    store = RunEnvelopeStore(tmp_path / "health" / "run-envelopes")
    started = store.start("runner")
    failed = store.finish("runner", run_id=started["run_id"], status="success", exit_code=7)
    assert failed["status"] == "failed"
    assert failed["failure_class"] == "process_error"

    started = store.start("runner")
    malformed = store.finish(
        "runner", run_id=started["run_id"], status="success",
        alerts_attempted=1, alerts_delivered=2,
    )
    assert malformed["status"] == "malformed_output"
    assert malformed["failure_class"] == "malformed_output"


def test_success_with_failure_class_cannot_render_healthy(tmp_path: Path) -> None:
    store = RunEnvelopeStore(tmp_path / "health" / "run-envelopes")
    started = store.start("contradictory")

    finished = store.finish(
        "contradictory", run_id=started["run_id"], status="success",
        failure_class="policy_veto",
    )

    assert finished["status"] == "malformed_output"
    assert finished["failure_class"] == "policy_veto"
    assert json.loads(store.report_path.read_text(encoding="utf-8"))["status"] == "attention"


def test_success_without_fresh_completed_evidence_is_not_green(tmp_path: Path) -> None:
    store = RunEnvelopeStore(tmp_path / "health" / "run-envelopes")
    started = store.start("no-data")
    finished = store.finish("no-data", run_id=started["run_id"], status="success")

    assert finished["status"] == "malformed_output"
    assert finished["failure_class"] == "malformed_output"
    report = json.loads(store.report_path.read_text(encoding="utf-8"))
    assert report["status"] == "attention"
    assert report["summary"]["successful"] == 0


def test_success_with_stale_data_is_classified_stale(tmp_path: Path) -> None:
    store = RunEnvelopeStore(tmp_path / "health" / "run-envelopes")
    started = store.start("stale-data", freshness_sla_seconds=60)
    stale_time = (datetime.now(timezone.utc) - timedelta(minutes=5)).isoformat()

    finished = store.finish(
        "stale-data", run_id=started["run_id"], status="success",
        data_as_of=stale_time,
    )

    assert finished["status"] == "stale"
    assert finished["failure_class"] == "stale_input"
    assert json.loads(store.report_path.read_text(encoding="utf-8"))["status"] == "attention"


def test_corrupt_breaker_and_latest_evidence_fail_closed(tmp_path: Path) -> None:
    store = RunEnvelopeStore(tmp_path / "health" / "run-envelopes")
    started = store.start("scanner")
    store.finish("scanner", run_id=started["run_id"], status="success")

    store.breaker_path("scanner").write_text("{broken", encoding="utf-8")
    assert store.breaker("scanner")["state"] == "OPEN"
    assert store.refresh_report()["status"] == "attention"

    store.latest_path("scanner").write_text("{broken", encoding="utf-8")
    report = store.refresh_report()
    assert report["status"] == "attention"
    assert report["components"][0]["status"] == "malformed_output"
    assert report["components"][0]["breaker_state"] == "OPEN"


def test_failure_taxonomy_is_stable() -> None:
    assert classify_failure("timeout") == "timeout"
    assert classify_failure("error", "provider connection unavailable") == "provider_unavailable"
    assert classify_failure("stale", "old bar") == "stale_input"
    assert classify_failure("success") is None


@pytest.mark.parametrize("secret_text", [
    "Authorization: Bearer abc123",
    "Authorization: Basic dXNlcjpwYXNz",
    "APCA-API-KEY-ID: pk-secret",
    "https://user:pass@example.com/path",
    "https://example.com/path?token=abc123&safe=1",
])
def test_error_redaction_covers_common_credential_forms(secret_text: str) -> None:
    redacted = redact_error(secret_text)
    assert "abc123" not in redacted
    assert "dXNlcjpwYXNz" not in redacted
    assert "pk-secret" not in redacted
    assert "user:pass" not in redacted

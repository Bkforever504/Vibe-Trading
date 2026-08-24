from __future__ import annotations

from datetime import datetime, timezone

from scripts.databento_mes_capability_probe import probe_live


NOW = datetime(2026, 8, 23, 20, 0, tzinfo=timezone.utc)


class AcceptedClient:
    def __init__(self, **_kwargs):
        self.terminated = False

    def subscribe(self, **kwargs):
        assert kwargs["dataset"] == "GLBX.MDP3"
        assert kwargs["schema"] == "mbo"
        assert kwargs["symbols"] == "MESU6"
        assert kwargs["snapshot"] is True

    def start(self):
        self.started = True

    def block_for_close(self, timeout):
        assert timeout == 2.0

    def terminate(self):
        self.terminated = True


class RejectedClient(AcceptedClient):
    def subscribe(self, **_kwargs):
        raise RuntimeError("A live data license is required to access GLBX.MDP3")


def test_probe_reports_subscription_acceptance_without_authority() -> None:
    report = probe_live(now=NOW, client_factory=AcceptedClient, key="fixture")
    assert report["live_status"] == "available"
    assert report["credentials_logged"] is False
    assert report["execution_enabled"] is False
    assert report["can_submit_orders"] is False


def test_probe_classifies_license_failure_without_secret_or_exception_text() -> None:
    report = probe_live(now=NOW, client_factory=RejectedClient, key="fixture-secret")
    assert report["live_status"] == "unavailable"
    assert report["live_reason"] == "live_data_license_required"
    assert "fixture-secret" not in str(report)

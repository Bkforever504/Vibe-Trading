from datetime import datetime, timezone

from scripts import catalyst_symbol_tape_shadow as subject


NOW = datetime(2026, 9, 8, 10, 0, tzinfo=subject.MARKET_TZ)


def _filing(symbol="QCOM", accepted="2026-09-08T09:00:20Z", source="sec_edgar_latest_atom"):
    return {"symbol": symbol, "event_at": accepted, "accession": "0001", "form": "8-K", "priority": "high", "source": source, "source_url": "https://www.sec.gov/test", "verification_status": "primary_index_verified", "collector_received_at": "2026-09-08T09:00:23Z"}


def _bars():
    base = datetime(2026, 9, 8, 13, 30, tzinfo=timezone.utc)
    return [
        {"t": (base.replace(minute=30 + i)).isoformat().replace("+00:00", "Z"), "o": 170 + i, "h": 171 + i, "l": 169.5 + i, "c": 170.8 + i, "v": 1000 + i * 100}
        for i in range(8)
    ]


def test_selects_recent_verified_liquid_primary_catalyst_only():
    report = {"catalysts": [_filing(), _filing("FAKE"), _filing("AMD", source="social_x")]}
    selected = subject.select_verified_symbols(report, {}, now=NOW.astimezone(timezone.utc))
    assert [row["symbol"] for row in selected] == ["QCOM"]
    assert selected[0]["liquidity_basis"] == "base_liquid_universe"


def test_build_report_is_shadow_only_and_observes_dynamic_symbol():
    def fetcher(symbols, **_kwargs):
        assert symbols == ["QCOM"]
        return {"QCOM": _bars()}, []

    report = subject.build_report(now_et=NOW, sec_report={"status": "ok", "catalysts": [_filing()]}, radar_report={}, fetcher=fetcher)
    assert report["status"] == "ok"
    assert report["symbols"] == ["QCOM"]
    assert report["observations"][0]["primary_catalyst"]["accession"] == "0001"
    assert report["execution_enabled"] is False
    assert report["can_submit_orders"] is False


def test_social_nomination_and_stale_filing_cannot_enter_tape_lane():
    report = {"catalysts": [_filing("QCOM", source="social_x"), _filing("AMD", accepted="2026-09-06T09:00:00Z")]}
    result = subject.build_report(now_et=NOW, sec_report=report, radar_report={}, fetcher=lambda *_a, **_k: ({}, []))
    assert result["symbols"] == []
    assert result["observations"] == []


def test_legacy_submissions_timestamp_cannot_enter_verified_lane():
    report = {"events": [_filing(source="sec_edgar_submissions")]}
    result = subject.build_report(now_et=NOW, sec_report=report, radar_report={}, fetcher=lambda *_a, **_k: ({}, []))
    assert result["symbols"] == []


def test_routine_prospectus_supplement_does_not_enter_fast_tape_lane():
    filing = _filing()
    filing["form"] = "424B2"
    assert subject.select_verified_symbols({"events": [filing]}, {}, now=NOW.astimezone(timezone.utc)) == []


def test_persist_is_idempotent(tmp_path):
    row = {"session_date": "2026-09-08", "symbol": "QCOM", "state": "ARMED", "direction": "LONG", "bar_completed_at": "2026-09-08T14:00:00Z", "transition": True, "primary_catalyst": _filing(), "execution_enabled": False, "can_submit_orders": False}
    report = {"generated_at": "2026-09-08T14:00:05Z", "observations": [row], "execution_enabled": False, "can_submit_orders": False}
    paths = (tmp_path / "report.json", tmp_path / "state.json", tmp_path / "events.jsonl")
    assert subject.persist(report, report_path=paths[0], state_path=paths[1], event_path=paths[2]) == 1
    assert '"new_transition_count": 1' in paths[0].read_text()
    assert subject.persist(report, report_path=paths[0], state_path=paths[1], event_path=paths[2]) == 0
    assert len(paths[2].read_text().splitlines()) == 1


def test_alert_delivery_is_idempotent_and_remains_shadow_only(tmp_path):
    calls = []
    row = {"session_date": "2026-09-08", "symbol": "QCOM", "state": "ARMED", "direction": "LONG", "bar_completed_at": "2026-09-08T14:00:00Z", "detected_at": "2026-09-08T14:00:03Z", "transition": True, "alertable": True, "primary_catalyst": _filing(), "execution_enabled": False, "can_submit_orders": False}
    report = {"generated_at": "2026-09-08T14:00:05Z", "observations": [row], "execution_enabled": False, "can_submit_orders": False}
    report_path, state_path, event_path, delivery_path = (tmp_path / name for name in ("report.json", "state.json", "events.jsonl", "delivery.jsonl"))

    def sender(message):
        calls.append(message)
        return {"delivered": True, "attempts": 1, "discord_message_id": "1", "discord_delivered_ts": "2026-09-08T14:00:06Z"}

    subject.persist(report, report_path=report_path, state_path=state_path, event_path=event_path, alert=True, sender=sender, delivery_event_path=delivery_path)
    subject.persist(report, report_path=report_path, state_path=state_path, event_path=event_path, alert=True, sender=sender, delivery_event_path=delivery_path)
    assert len(calls) == 1
    assert "Shadow early-warning only" in calls[0]
    state = subject._read_json(state_path)
    assert state["execution_enabled"] is False
    assert state["can_submit_orders"] is False

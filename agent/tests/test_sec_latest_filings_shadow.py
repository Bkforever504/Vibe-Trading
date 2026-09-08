from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from scripts.sec_latest_filings_shadow import (
    INDEX_URL,
    LATEST_FILINGS_ATOM_URL,
    TICKER_MAP_URL,
    RequestRateGuard,
    collect_latest_filings,
    is_relevant_form,
    parse_latest_atom,
)


ACCESSION = "0000804328-26-000123"
CIK = "0000804328"


def _atom(*, updated: str = "2026-09-08T09:30:01-04:00", form: str = "8-K", cik: str = CIK) -> bytes:
    return f'''<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <updated>{updated}</updated>
  <entry>
    <title>{form} - QUALCOMM INC/DE</title>
    <id>urn:tag:sec.gov,2008:accession-number={ACCESSION}</id>
    <updated>{updated}</updated>
    <category term="{form}" />
    <summary>CIK: {cik} AccNo: {ACCESSION}</summary>
    <link href="https://www.sec.gov/Archives/edgar/data/{int(cik)}/{ACCESSION}-index.htm" />
  </entry>
</feed>'''.encode()


class Response:
    def __init__(self, status_code: int, content: bytes = b"", *, url: str = "", headers=None):
        self.status_code = status_code
        self.content = content
        self.url = url
        self.headers = headers or {}


class FakeClient:
    def __init__(self, responses):
        self.responses = {key: list(value) for key, value in responses.items()}
        self.calls = []

    def get(self, url, *, headers, timeout):
        self.calls.append({"url": url, "headers": dict(headers), "timeout": timeout})
        return self.responses[url].pop(0)


def _client(*, atom=None, index=None, map_response=None):
    index_url = INDEX_URL.format(cik_int=int(CIK), accession_compact=ACCESSION.replace("-", ""), accession=ACCESSION)
    ticker_map = json.dumps({"0": {"ticker": "QCOM", "cik_str": int(CIK)}}).encode()
    return FakeClient(
        {
            LATEST_FILINGS_ATOM_URL: atom or [Response(200, _atom(), url=LATEST_FILINGS_ATOM_URL, headers={"ETag": '"feed-1"'})],
            TICKER_MAP_URL: map_response or [Response(200, ticker_map, url=TICKER_MAP_URL, headers={"ETag": '"map-1"'})],
            index_url: index
            or [
                Response(
                    200,
                    f"<html>CIK {CIK} accession {ACCESSION}</html>".encode(),
                    url=index_url,
                    headers={"Last-Modified": "Tue, 08 Sep 2026 13:30:03 GMT"},
                )
            ],
        }
    )


def _collect(tmp_path: Path, client, **kwargs):
    user_agent = kwargs.pop("user_agent", "Vibe Trading ops@domain.test")
    return collect_latest_filings(
        ["QCOM", "SPY"],
        user_agent=user_agent,
        client=client,
        ledger_path=tmp_path / "ledger.jsonl",
        state_path=tmp_path / "state.json",
        now=lambda: datetime(2026, 9, 8, 13, 30, 5, 123456, tzinfo=timezone.utc),
        monotonic=lambda: 10.0,
        monotonic_ns=lambda: 10_000_000_000,
        sleeper=lambda _: None,
        random_fn=lambda: 0.0,
        **kwargs,
    )


def test_relevant_form_family_includes_amendments_and_rejects_noise():
    assert is_relevant_form("SC 13D/A")
    assert is_relevant_form("DEFM14A")
    assert is_relevant_form("424B5")
    assert is_relevant_form("SC 13E3")
    assert is_relevant_form("425")
    assert not is_relevant_form("4")


def test_atom_requires_explicit_offset_and_preserves_raw_precision():
    _, rows = parse_latest_atom(_atom())
    assert rows[0]["atom_updated"] == {
        "raw": "2026-09-08T09:30:01-04:00",
        "utc": "2026-09-08T13:30:01.000000Z",
        "timestamp_precision": "second",
        "clock_status": "good",
    }
    _, ambiguous = parse_latest_atom(_atom(updated="2026-09-08T13:30:01Z"))
    assert ambiguous[0]["atom_updated"]["utc"] is None
    assert ambiguous[0]["atom_updated"]["clock_status"] == "ambiguous_or_missing_offset"


def test_verified_in_universe_filing_is_hashed_shadow_only_and_idempotent(tmp_path):
    first_client = _client()
    report = _collect(tmp_path, first_client)

    assert report["status"] == "ok"
    assert report["sec_eligible_symbols"] == ["QCOM"]
    assert report["skipped_non_issuer_symbols"] == ["SPY"]
    assert report["summary"]["primary_index_verified"] == 1
    event = report["events"][0]
    assert event["source_status"] == "primary_index_verified"
    assert event["source"] == "sec_edgar_latest_atom"
    assert event["verification_status"] == "primary_index_verified"
    assert event["source_url"] == event["canonical_url"]
    assert event["accession"] == ACCESSION
    assert event["cik"] == CIK
    assert event["content_sha256"]
    assert event["acceptanceDateTime_raw"] == "2026-09-08T09:30:01-04:00"
    assert event["source_accepted_at"] == "2026-09-08T13:30:01.000000Z"
    assert event["collector_received_at"] == "2026-09-08T13:30:05.123456Z"
    assert event["source_observed_at"] == event["document_verified_at"]
    assert event["collector_monotonic_ns"] == 10_000_000_000
    assert event["execution_enabled"] is False
    assert event["can_submit_orders"] is False
    assert report["ledger_rows_appended"] == 1
    assert len((tmp_path / "ledger.jsonl").read_text().splitlines()) == 1

    # A repeated 200 response cannot duplicate the same verified transition.
    second = _collect(tmp_path, _client())
    assert second["ledger_rows_appended"] == 0
    assert len((tmp_path / "ledger.jsonl").read_text().splitlines()) == 1

    persisted = json.loads((tmp_path / "state.json").read_text())
    assert persisted["execution_enabled"] is False
    assert "user_agent" not in json.dumps(persisted).lower()
    assert all("User-Agent" in call["headers"] for call in first_client.calls)
    assert "Vibe Trading ops@domain.test" not in json.dumps(report)


def test_primary_index_failure_is_pending_and_not_written_to_verified_ledger(tmp_path):
    index_url = INDEX_URL.format(cik_int=int(CIK), accession_compact=ACCESSION.replace("-", ""), accession=ACCESSION)
    client = _client(index=[Response(404, url=index_url)])
    report = _collect(tmp_path, client)

    assert report["status"] == "degraded"
    assert report["summary"]["pending_verification"] == 1
    assert report["events"][0]["source_status"] == "pending_verification"
    assert report["events"][0]["content_sha256"] is None
    assert report["events"][0]["verification_reason"] == "primary_index_http_404"
    assert report["ledger_rows_appended"] == 0
    assert not (tmp_path / "ledger.jsonl").exists()


def test_redirect_outside_sec_is_rejected(tmp_path):
    client = _client(
        index=[Response(200, f"CIK {CIK} {ACCESSION}".encode(), url="https://attacker.invalid/index.htm")]
    )
    report = _collect(tmp_path, client)
    assert report["events"][0]["verification_reason"] == "verification_redirect_disallowed"


def test_missing_identity_fails_closed_without_transport_or_secret_echo(tmp_path):
    client = FakeClient({})
    report = _collect(tmp_path, client, user_agent="missing")
    assert report["status"] == "not_configured"
    assert report["reason"] == "sec_user_agent_required"
    assert report["events"] == []
    assert client.calls == []
    assert "missing" not in json.dumps(report)


def test_conditional_304_uses_state_validators_and_makes_no_index_call(tmp_path):
    state = {
        "validators": {"latest_atom": {"etag": '"feed-1"', "last_modified": None}},
        "ticker_map": {"QCOM": CIK},
        "events": {},
    }
    (tmp_path / "state.json").write_text(json.dumps(state))
    client = FakeClient(
        {LATEST_FILINGS_ATOM_URL: [Response(304, url=LATEST_FILINGS_ATOM_URL, headers={"ETag": '"feed-1"'})]}
    )
    report = _collect(tmp_path, client)
    assert report["status"] == "no_change"
    assert report["requests_made"] == 1
    assert client.calls[0]["headers"]["If-None-Match"] == '"feed-1"'


def test_pending_verification_is_retried_when_atom_is_not_modified(tmp_path):
    filing = parse_latest_atom(_atom())[1][0]
    state = {
        "validators": {"latest_atom": {"etag": '"feed-1"'}},
        "ticker_map": {"QCOM": CIK},
        "feed_updated_at_raw": "2026-09-08T09:30:01-04:00",
        "events": {
            ACCESSION: {
                "source_status": "pending_verification",
                "filing": filing,
            }
        },
    }
    (tmp_path / "state.json").write_text(json.dumps(state))
    index_url = INDEX_URL.format(cik_int=int(CIK), accession_compact=ACCESSION.replace("-", ""), accession=ACCESSION)
    ticker_map = json.dumps({"0": {"ticker": "QCOM", "cik_str": int(CIK)}}).encode()
    client = FakeClient(
        {
            LATEST_FILINGS_ATOM_URL: [Response(304, url=LATEST_FILINGS_ATOM_URL)],
            TICKER_MAP_URL: [Response(200, ticker_map, url=TICKER_MAP_URL)],
            index_url: [Response(200, f"CIK {CIK} accession {ACCESSION}".encode(), url=index_url)],
        }
    )
    report = _collect(tmp_path, client)
    assert report["status"] == "ok"
    assert report["summary"]["primary_index_verified"] == 1
    assert report["ledger_rows_appended"] == 1


def test_verified_event_remains_in_no_change_report_for_active_tape_join(tmp_path):
    first = _collect(tmp_path, _client())
    stored = json.loads((tmp_path / "state.json").read_text())
    client = FakeClient({LATEST_FILINGS_ATOM_URL: [Response(304, url=LATEST_FILINGS_ATOM_URL)]})
    report = _collect(tmp_path, client)
    assert first["events"][0]["accession"] == ACCESSION
    assert report["status"] == "no_change"
    assert report["events"][0]["accession"] == ACCESSION
    assert stored["events"][ACCESSION]["event"]["source_observed_at"]


def test_retry_after_and_application_rate_guard_are_enforced(tmp_path):
    sleeps = []
    clock = [0.0]

    def monotonic():
        return clock[0]

    def sleeper(delay):
        sleeps.append(delay)
        clock[0] += delay

    guard = RequestRateGuard(monotonic=monotonic, sleeper=sleeper)
    for _ in range(9):
        guard.acquire()
    assert sleeps == [1.0]

    client = _client(
        atom=[
            Response(429, url=LATEST_FILINGS_ATOM_URL, headers={"Retry-After": "2"}),
            Response(200, _atom(), url=LATEST_FILINGS_ATOM_URL),
        ]
    )
    report = collect_latest_filings(
        ["QCOM"],
        user_agent="Vibe Trading ops@domain.test",
        client=client,
        ledger_path=tmp_path / "ledger.jsonl",
        state_path=tmp_path / "state.json",
        now=lambda: datetime(2026, 9, 8, 13, 30, 5, tzinfo=timezone.utc),
        monotonic=monotonic,
        monotonic_ns=lambda: int(clock[0] * 1_000_000_000),
        sleeper=sleeper,
        random_fn=lambda: 0.0,
    )
    assert report["status"] == "ok"
    assert 2.0 in sleeps


def test_parse_and_http_errors_fail_honestly(tmp_path):
    parse_client = _client(atom=[Response(200, b"not xml", url=LATEST_FILINGS_ATOM_URL)])
    parse_report = _collect(tmp_path, parse_client)
    assert parse_report["status"] == "degraded"
    assert parse_report["reason"] == "invalid_atom_xml"

    http_client = _client(atom=[Response(500, url=LATEST_FILINGS_ATOM_URL)] * 3)
    http_report = _collect(tmp_path / "http", http_client)
    assert http_report["status"] == "degraded"
    assert http_report["reason"] == "latest_atom_http_500"

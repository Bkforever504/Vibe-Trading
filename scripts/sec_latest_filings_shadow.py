#!/usr/bin/env python3
"""Shadow-only collector for the SEC's global Latest Filings Atom feed.

The feed is discovery metadata.  An in-universe filing is not considered a
verified primary-source catalyst until its canonical SEC accession index is
retrieved and its accession/CIK provenance checks pass.  This module has no
broker imports, signal direction, contract selection, or execution authority.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import random
import re
import time
import xml.etree.ElementTree as ET
from collections import deque
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping
from urllib.parse import urlparse

import requests


LATEST_FILINGS_ATOM_URL = "https://www.sec.gov/cgi-bin/browse-edgar?action=getcurrent&output=atom"
TICKER_MAP_URL = "https://www.sec.gov/files/company_tickers.json"
INDEX_URL = "https://www.sec.gov/Archives/edgar/data/{cik_int}/{accession_compact}/{accession}-index.htm"
DEFAULT_LEDGER_PATH = Path.home() / ".vibe-trading" / "data" / "sec-latest-filings-shadow.jsonl"
DEFAULT_STATE_PATH = Path.home() / ".vibe-trading" / "state" / "sec-latest-filings-shadow.json"
DEFAULT_REPORT_PATH = Path.home() / ".vibe-trading" / "reports" / "sec-latest-filings-shadow.json"
MAX_RESPONSE_BYTES = 5_000_000
MAX_REQUESTS_PER_SECOND = 8
ATOM_NS = {"atom": "http://www.w3.org/2005/Atom"}
ACCESSION_RE = re.compile(r"(?<!\d)(\d{10}-\d{2}-\d{6})(?!\d)")
CIK_PATH_RE = re.compile(r"/Archives/edgar/data/(\d+)(?:/|$)", re.I)
CIK_TEXT_RE = re.compile(r"\bCIK\s*[:#]?\s*(\d{1,10})\b", re.I)

# Amendments of these forms are retained and explicitly labeled as amendments.
RELEVANT_FORMS = frozenset(
    {
        "8-K",
        "6-K",
        "10-Q",
        "10-K",
        "20-F",
        "SC 13D",
        "SC 13G",
        "SC TO-I",
        "SC TO-T",
        "SC TO-C",
        "SC 14D9",
        "SC 13E3",
        "DEFM14A",
        "PREM14A",
        "425",
        "CB",
        "S-4",
        "F-4",
        "S-1",
        "S-3",
        "F-1",
        "F-3",
        "424B1",
        "424B2",
        "424B3",
        "424B4",
        "424B5",
        "424B7",
        "424B8",
    }
)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _iso_utc(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")


def _authority() -> dict[str, bool]:
    return {"execution_enabled": False, "can_submit_orders": False}


def _valid_user_agent(value: str) -> bool:
    # Keep the identity out of every output; this only validates configuration.
    text = value.strip()
    return bool(len(text) >= 8 and "@" in text and not re.search(r"example\.com|replace|todo", text, re.I))


def _atomic_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def _read_state(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else {}
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return {}


def _ledger_keys(path: Path) -> set[str]:
    keys: set[str] = set()
    try:
        with path.open("r", encoding="utf-8") as handle:
            for line in handle:
                try:
                    row = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if isinstance(row, dict) and row.get("ledger_record_id"):
                    keys.add(str(row["ledger_record_id"]))
    except FileNotFoundError:
        pass
    return keys


def _append_new_rows(path: Path, rows: Iterable[dict[str, Any]]) -> int:
    existing = _ledger_keys(path)
    additions = [row for row in rows if str(row.get("ledger_record_id") or "") not in existing]
    if not additions:
        return 0
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8", newline="\n") as handle:
        for row in additions:
            handle.write(json.dumps(row, sort_keys=True, separators=(",", ":")) + "\n")
        handle.flush()
        os.fsync(handle.fileno())
    return len(additions)


class RequestRateGuard:
    """Sliding-window guard; every network attempt counts toward the ceiling."""

    def __init__(
        self,
        *,
        limit: int = MAX_REQUESTS_PER_SECOND,
        monotonic: Callable[[], float] = time.monotonic,
        sleeper: Callable[[float], None] = time.sleep,
    ) -> None:
        if limit < 1 or limit > MAX_REQUESTS_PER_SECOND:
            raise ValueError(f"request limit must be between 1 and {MAX_REQUESTS_PER_SECOND}")
        self.limit = limit
        self.monotonic = monotonic
        self.sleeper = sleeper
        self._attempts: deque[float] = deque()
        self.total_attempts = 0

    def acquire(self) -> None:
        now = self.monotonic()
        while self._attempts and now - self._attempts[0] >= 1.0:
            self._attempts.popleft()
        if len(self._attempts) >= self.limit:
            self.sleeper(max(0.0, 1.0 - (now - self._attempts[0])))
            now = self.monotonic()
            while self._attempts and now - self._attempts[0] >= 1.0:
                self._attempts.popleft()
        self._attempts.append(now)
        self.total_attempts += 1


@dataclass(frozen=True)
class FetchResult:
    status: str
    status_code: int | None
    content: bytes | None
    etag: str | None
    last_modified: str | None
    final_url: str | None
    received_at: str | None
    received_monotonic_ns: int | None


def _header(headers: Mapping[str, Any], name: str) -> str | None:
    for key, value in headers.items():
        if str(key).lower() == name.lower() and value is not None:
            return str(value)
    return None


def _retry_delay(response: Any, attempt: int, random_fn: Callable[[], float]) -> float:
    retry_after = _header(getattr(response, "headers", {}) or {}, "Retry-After")
    if retry_after:
        try:
            return min(60.0, max(0.0, float(retry_after)))
        except ValueError:
            try:
                parsed = parsedate_to_datetime(retry_after)
                return min(60.0, max(0.0, (parsed - _utc_now()).total_seconds()))
            except (TypeError, ValueError, OverflowError):
                pass
    return min(30.0, (0.5 * (2**attempt)) + (0.25 * random_fn()))


def fetch_url(
    client: Any,
    url: str,
    *,
    user_agent: str,
    guard: RequestRateGuard,
    validators: Mapping[str, str] | None = None,
    timeout: float = 15.0,
    max_attempts: int = 3,
    sleeper: Callable[[float], None] = time.sleep,
    random_fn: Callable[[], float] = random.random,
    now: Callable[[], datetime] = _utc_now,
    monotonic_ns: Callable[[], int] = time.monotonic_ns,
) -> FetchResult:
    headers = {"User-Agent": user_agent, "Accept": "application/atom+xml,application/json,text/html"}
    if validators:
        if validators.get("etag"):
            headers["If-None-Match"] = validators["etag"]
        if validators.get("last_modified"):
            headers["If-Modified-Since"] = validators["last_modified"]
    for attempt in range(max_attempts):
        guard.acquire()
        try:
            response = client.get(url, headers=headers, timeout=timeout)
        except Exception as exc:  # transport errors are classified, never serialized verbatim
            if attempt + 1 < max_attempts:
                sleeper(min(30.0, (0.5 * (2**attempt)) + (0.25 * random_fn())))
                continue
            return FetchResult(f"transport_{type(exc).__name__}", None, None, None, None, None, None, None)
        received = now()
        received_mono = monotonic_ns()
        status_code = int(getattr(response, "status_code", 0) or 0)
        response_headers = getattr(response, "headers", {}) or {}
        result_base = {
            "status_code": status_code,
            "etag": _header(response_headers, "ETag"),
            "last_modified": _header(response_headers, "Last-Modified"),
            "final_url": str(getattr(response, "url", url) or url),
            "received_at": _iso_utc(received),
            "received_monotonic_ns": received_mono,
        }
        if status_code == 304:
            return FetchResult(status="not_modified", content=None, **result_base)
        if status_code in {403, 429} or 500 <= status_code <= 599:
            if attempt + 1 < max_attempts:
                sleeper(_retry_delay(response, attempt, random_fn))
                continue
            return FetchResult(status=f"http_{status_code}", content=None, **result_base)
        if status_code != 200:
            return FetchResult(status=f"http_{status_code}", content=None, **result_base)
        content = bytes(getattr(response, "content", b"") or b"")
        if not content:
            return FetchResult(status="empty_response", content=None, **result_base)
        if len(content) > MAX_RESPONSE_BYTES:
            return FetchResult(status="response_too_large", content=None, **result_base)
        return FetchResult(status="ok", content=content, **result_base)
    raise AssertionError("unreachable")


def _canonical_accession(value: str) -> str | None:
    match = ACCESSION_RE.search(value)
    return match.group(1) if match else None


def _canonical_cik(value: str | int) -> str | None:
    digits = re.sub(r"\D", "", str(value))
    return digits.zfill(10) if digits and len(digits) <= 10 else None


def _parse_atom_timestamp(raw: str) -> dict[str, Any]:
    text = raw.strip()
    # Require seconds and an explicit numeric UTC offset.  Do not guess a zone.
    match = re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:(\d{2})(?:\.\d+)?([+-]\d{2}:\d{2})", text)
    if not match:
        return {
            "raw": text or None,
            "utc": None,
            "timestamp_precision": "unknown",
            "clock_status": "ambiguous_or_missing_offset",
        }
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return {
            "raw": text,
            "utc": None,
            "timestamp_precision": "unknown",
            "clock_status": "invalid_timestamp",
        }
    return {
        "raw": text,
        "utc": _iso_utc(parsed),
        "timestamp_precision": "second",
        "clock_status": "good",
    }


def _entry_cik(entry: ET.Element, links: list[str], summary: str, title: str) -> str | None:
    candidates = [*links, summary, title]
    for candidate in candidates:
        match = CIK_PATH_RE.search(candidate) or CIK_TEXT_RE.search(candidate)
        if match:
            return _canonical_cik(match.group(1))
    return None


def _base_form(form: str) -> str:
    normalized = re.sub(r"\s+", " ", form.strip().upper())
    return normalized[:-2] if normalized.endswith("/A") else normalized


def is_relevant_form(form: str) -> bool:
    return _base_form(form) in RELEVANT_FORMS


def parse_latest_atom(content: bytes) -> tuple[str | None, list[dict[str, Any]]]:
    try:
        root = ET.fromstring(content)
    except ET.ParseError as exc:
        raise ValueError("invalid_atom_xml") from exc
    if root.tag != "{http://www.w3.org/2005/Atom}feed":
        raise ValueError("unexpected_atom_root")
    feed_updated = (root.findtext("atom:updated", default="", namespaces=ATOM_NS) or "").strip() or None
    filings: list[dict[str, Any]] = []
    for entry in root.findall("atom:entry", ATOM_NS):
        title = (entry.findtext("atom:title", default="", namespaces=ATOM_NS) or "").strip()
        summary = (entry.findtext("atom:summary", default="", namespaces=ATOM_NS) or "").strip()
        entry_id = (entry.findtext("atom:id", default="", namespaces=ATOM_NS) or "").strip()
        updated_raw = (entry.findtext("atom:updated", default="", namespaces=ATOM_NS) or "").strip()
        links = [str(link.attrib.get("href") or "") for link in entry.findall("atom:link", ATOM_NS)]
        category = entry.find("atom:category", ATOM_NS)
        form = str(category.attrib.get("term") or "").strip() if category is not None else ""
        if not form:
            form = title.split(" - ", 1)[0].strip()
        accession = _canonical_accession(" ".join([entry_id, summary, title, *links]))
        cik = _entry_cik(entry, links, summary, title)
        if accession and cik and is_relevant_form(form):
            filings.append(
                {
                    "accession": accession,
                    "cik": cik,
                    "form": re.sub(r"\s+", " ", form.upper()),
                    "is_amendment": form.upper().endswith("/A"),
                    "atom_updated": _parse_atom_timestamp(updated_raw),
                }
            )
    return feed_updated, filings


def parse_ticker_map(content: bytes) -> dict[str, str]:
    try:
        payload = json.loads(content)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("invalid_ticker_map_json") from exc
    rows = payload.values() if isinstance(payload, dict) else payload if isinstance(payload, list) else []
    mapping: dict[str, str] = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        symbol = str(row.get("ticker") or "").strip().upper()
        cik = _canonical_cik(row.get("cik_str") or "")
        if symbol and cik:
            mapping[symbol] = cik
    if not mapping:
        raise ValueError("empty_ticker_map")
    return mapping


def _official_sec_url(url: str) -> bool:
    parsed = urlparse(url)
    return parsed.scheme == "https" and (parsed.hostname or "").lower() in {"sec.gov", "www.sec.gov"}


def _verify_index(content: bytes, *, accession: str, cik: str, final_url: str | None) -> str | None:
    if not final_url or not _official_sec_url(final_url):
        return "verification_redirect_disallowed"
    text = content.decode("utf-8", errors="replace")
    compact = accession.replace("-", "")
    normalized_text = re.sub(r"[^0-9A-Za-z-]", "", text)
    accession_present = accession in text or compact in normalized_text
    cik_int = str(int(cik))
    cik_present = cik in text or re.search(rf"\b0*{re.escape(cik_int)}\b", text) is not None
    if not accession_present:
        return "accession_not_in_index"
    if not cik_present:
        return "cik_not_in_index"
    return None


def _event_id(accession: str) -> str:
    return hashlib.sha256(f"sec_edgar|{accession}|1".encode("utf-8")).hexdigest()


def _ledger_id(event: Mapping[str, Any]) -> str:
    material = f"{event['event_id']}|{event['source_status']}|{event.get('content_sha256') or ''}"
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


def _freshness(atom_timestamp: Mapping[str, Any], received_at: str) -> tuple[str, int | None, str | None]:
    if atom_timestamp.get("clock_status") != "good" or not atom_timestamp.get("utc"):
        return "unknown", None, "source_timestamp_ambiguous"
    source = datetime.fromisoformat(str(atom_timestamp["utc"]).replace("Z", "+00:00"))
    received = datetime.fromisoformat(received_at.replace("Z", "+00:00"))
    latency_ms = max(0, round((received - source).total_seconds() * 1000))
    return ("fresh" if latency_ms <= 15 * 60 * 1000 else "stale"), latency_ms, None


def _active_verified_events(event_state: Mapping[str, Any], now: datetime) -> list[dict[str, Any]]:
    cutoff = now.astimezone(timezone.utc) - timedelta(hours=24)
    rows: list[dict[str, Any]] = []
    for value in event_state.values():
        event = value.get("event") if isinstance(value, Mapping) and isinstance(value.get("event"), Mapping) else None
        if not event or event.get("source_status") != "primary_index_verified":
            continue
        try:
            event_at = datetime.fromisoformat(str(event.get("event_at") or "").replace("Z", "+00:00"))
        except ValueError:
            continue
        if event_at.tzinfo and event_at.astimezone(timezone.utc) >= cutoff:
            rows.append(dict(event))
    return sorted(rows, key=lambda row: (str(row.get("event_at") or ""), str(row.get("accession") or "")))


def build_disabled_report(symbols: Iterable[str], reason: str, *, generated_at: datetime | None = None) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "generated_at": _iso_utc(generated_at or _utc_now()),
        "provider": "sec_edgar",
        "source": "sec_latest_filings_atom",
        "mode": "shadow_primary_catalyst_discovery",
        "status": "not_configured",
        "reason": reason,
        "symbols": sorted({str(symbol).strip().upper() for symbol in symbols if str(symbol).strip()}),
        "events": [],
        "errors": [],
        **_authority(),
    }


def collect_latest_filings(
    symbols: Iterable[str],
    *,
    user_agent: str | None = None,
    client: Any | None = None,
    ledger_path: Path = DEFAULT_LEDGER_PATH,
    state_path: Path = DEFAULT_STATE_PATH,
    now: Callable[[], datetime] = _utc_now,
    monotonic: Callable[[], float] = time.monotonic,
    monotonic_ns: Callable[[], int] = time.monotonic_ns,
    sleeper: Callable[[float], None] = time.sleep,
    random_fn: Callable[[], float] = random.random,
) -> dict[str, Any]:
    clean_symbols = sorted({str(symbol).strip().upper() for symbol in symbols if str(symbol).strip()})
    generated = now()
    identity = (user_agent or os.getenv("SEC_USER_AGENT") or "").strip()
    if not _valid_user_agent(identity):
        return build_disabled_report(clean_symbols, "sec_user_agent_required", generated_at=generated)

    transport = client or requests.Session()
    guard = RequestRateGuard(monotonic=monotonic, sleeper=sleeper)
    state = _read_state(state_path)
    event_state = state.get("events") if isinstance(state.get("events"), dict) else {}
    pending_filings = [
        value["filing"]
        for value in event_state.values()
        if isinstance(value, dict)
        and value.get("source_status") == "pending_verification"
        and isinstance(value.get("filing"), dict)
    ]
    validators = state.get("validators") if isinstance(state.get("validators"), dict) else {}
    errors: list[dict[str, Any]] = []
    feed_result = fetch_url(
        transport,
        LATEST_FILINGS_ATOM_URL,
        user_agent=identity,
        guard=guard,
        validators=validators.get("latest_atom") if isinstance(validators.get("latest_atom"), dict) else None,
        sleeper=sleeper,
        random_fn=random_fn,
        now=now,
        monotonic_ns=monotonic_ns,
    )
    if feed_result.status == "not_modified" and not pending_filings:
        active_events = _active_verified_events(event_state, generated)
        report = {
            "schema_version": 1,
            "generated_at": _iso_utc(generated),
            "provider": "sec_edgar",
            "source": "sec_latest_filings_atom",
            "mode": "shadow_primary_catalyst_discovery",
            "status": "no_change",
            "reason": None,
            "symbols": clean_symbols,
            "events": active_events,
            "errors": [],
            "requests_made": 1,
            "ledger_rows_appended": 0,
            "summary": {"active_verified": len(active_events), "pending_verification": 0},
            **_authority(),
        }
        return report
    if feed_result.status not in {"ok", "not_modified"}:
        return {
            **build_disabled_report(clean_symbols, f"latest_atom_{feed_result.status}", generated_at=generated),
            "status": "degraded",
            "errors": [{"stage": "latest_atom", "status": feed_result.status}],
        }
    if feed_result.status == "not_modified":
        feed_updated_raw = state.get("feed_updated_at_raw")
        filings = list(pending_filings)
    else:
        try:
            feed_updated_raw, filings = parse_latest_atom(feed_result.content or b"")
        except ValueError as exc:
            return {
                **build_disabled_report(clean_symbols, str(exc), generated_at=generated),
                "status": "degraded",
                "errors": [{"stage": "latest_atom", "status": str(exc)}],
            }
        by_accession = {str(row.get("accession")): row for row in pending_filings}
        by_accession.update({str(row.get("accession")): row for row in filings})
        filings = list(by_accession.values())

    map_result = fetch_url(
        transport,
        TICKER_MAP_URL,
        user_agent=identity,
        guard=guard,
        validators=validators.get("ticker_map") if isinstance(validators.get("ticker_map"), dict) else None,
        sleeper=sleeper,
        random_fn=random_fn,
        now=now,
        monotonic_ns=monotonic_ns,
    )
    cached_map = state.get("ticker_map") if isinstance(state.get("ticker_map"), dict) else None
    try:
        if map_result.status == "not_modified" and cached_map:
            ticker_map = {str(key): str(value) for key, value in cached_map.items()}
        elif map_result.status == "ok" and map_result.content is not None:
            ticker_map = parse_ticker_map(map_result.content)
        else:
            raise ValueError(f"ticker_map_{map_result.status}")
    except ValueError as exc:
        return {
            **build_disabled_report(clean_symbols, str(exc), generated_at=generated),
            "status": "degraded",
            "errors": [{"stage": "ticker_map", "status": str(exc)}],
        }

    eligible = {symbol: ticker_map[symbol] for symbol in clean_symbols if symbol in ticker_map}
    skipped = [symbol for symbol in clean_symbols if symbol not in ticker_map]
    symbols_by_cik: dict[str, list[str]] = {}
    for symbol, cik in eligible.items():
        symbols_by_cik.setdefault(cik, []).append(symbol)

    events: list[dict[str, Any]] = []
    for filing in filings:
        cik = filing["cik"]
        matched_symbols = sorted(symbols_by_cik.get(cik, []))
        if not matched_symbols:
            continue
        accession = filing["accession"]
        prior_record = event_state.get(accession) if isinstance(event_state.get(accession), dict) else {}
        prior_event = prior_record.get("event") if isinstance(prior_record.get("event"), dict) else None
        if prior_record.get("source_status") == "primary_index_verified" and prior_event:
            # An accession index is immutable evidence for this intake purpose;
            # amendments receive a different accession and are collected separately.
            events.append(dict(prior_event))
            continue
        canonical_url = INDEX_URL.format(cik_int=int(cik), accession_compact=accession.replace("-", ""), accession=accession)
        index_result = fetch_url(
            transport,
            canonical_url,
            user_agent=identity,
            guard=guard,
            sleeper=sleeper,
            random_fn=random_fn,
            now=now,
            monotonic_ns=monotonic_ns,
        )
        atom_timestamp = filing["atom_updated"]
        collector_received_at = feed_result.received_at or _iso_utc(now())
        freshness, latency_ms, latency_reason = _freshness(atom_timestamp, collector_received_at)
        content_hash: str | None = None
        verification_reason: str | None = None
        document_verified_at: str | None = None
        if index_result.status != "ok" or index_result.content is None:
            verification_reason = f"primary_index_{index_result.status}"
        else:
            verification_reason = _verify_index(index_result.content, accession=accession, cik=cik, final_url=index_result.final_url)
            if verification_reason is None:
                content_hash = hashlib.sha256(index_result.content).hexdigest()
                document_verified_at = index_result.received_at
        source_status = "primary_index_verified" if verification_reason is None else "pending_verification"
        event: dict[str, Any] = {
            "event_id": _event_id(accession),
            "symbol": matched_symbols[0],
            "matched_symbols": matched_symbols,
            "cik": cik,
            "source_class": "sec_edgar",
            "source": "sec_edgar_latest_atom",
            "source_status": source_status,
            "verification_status": source_status,
            "form": filing["form"],
            "is_amendment": filing["is_amendment"],
            "items": [],
            "accession": accession,
            "canonical_url": canonical_url,
            "source_url": canonical_url,
            "event_at": atom_timestamp["utc"],
            "acceptanceDateTime_raw": atom_timestamp["raw"],
            "source_accepted_at": atom_timestamp["utc"],
            "source_published_at": None,
            "source_updated_at": atom_timestamp["utc"],
            "source_updated_at_raw": atom_timestamp["raw"],
            "http_last_modified_at": index_result.last_modified,
            "collector_received_at": collector_received_at,
            "collector_monotonic_ns": feed_result.received_monotonic_ns,
            "document_verified_at": document_verified_at,
            "source_observed_at": document_verified_at,
            "content_sha256": content_hash,
            "revision": 1,
            "timestamp_precision": atom_timestamp["timestamp_precision"],
            "clock_status": atom_timestamp["clock_status"],
            "freshness_status": freshness,
            "source_to_observation_latency_ms": latency_ms,
            "latency_unavailable_reason": latency_reason,
            "verification_reason": verification_reason,
            **_authority(),
        }
        event["ledger_record_id"] = _ledger_id(event)
        events.append(event)
        event_state[accession] = {
            "event_id": event["event_id"],
            "source_status": source_status,
            "content_sha256": content_hash,
            "last_observed_at": collector_received_at,
            "verification_reason": verification_reason,
            "filing": filing if verification_reason else None,
            "event": event if verification_reason is None else None,
        }
        if verification_reason:
            errors.append({"stage": "primary_index", "accession": accession, "status": verification_reason})

    verified_rows = [event for event in events if event["source_status"] == "primary_index_verified"]
    appended = _append_new_rows(ledger_path, verified_rows)
    new_validators = dict(validators)
    new_validators["latest_atom"] = {
        "etag": feed_result.etag,
        "last_modified": feed_result.last_modified,
    }
    new_validators["ticker_map"] = {"etag": map_result.etag, "last_modified": map_result.last_modified}
    # Retain only the most recently observed accessions to bound durable state.
    event_state = dict(sorted(event_state.items(), key=lambda item: str(item[1].get("last_observed_at") or ""))[-2000:])
    new_state = {
        "schema_version": 1,
        "updated_at": _iso_utc(now()),
        "feed_updated_at_raw": feed_updated_raw,
        "validators": new_validators,
        "ticker_map": ticker_map,
        "events": event_state,
        **_authority(),
    }
    _atomic_json(state_path, new_state)
    status = "degraded" if errors else "ok"
    current_by_accession = {str(row.get("accession")): row for row in _active_verified_events(event_state, generated)}
    current_by_accession.update({str(row.get("accession")): row for row in events if row.get("source_status") != "primary_index_verified"})
    report_events = list(current_by_accession.values())
    return {
        "schema_version": 1,
        "generated_at": _iso_utc(generated),
        "provider": "sec_edgar",
        "source": "sec_latest_filings_atom",
        "mode": "shadow_primary_catalyst_discovery",
        "status": status,
        "reason": "verification_debt" if errors else None,
        "symbols": clean_symbols,
        "sec_eligible_symbols": sorted(eligible),
        "skipped_non_issuer_symbols": skipped,
        "feed_updated_at_raw": feed_updated_raw,
        "events": report_events,
        "summary": {
            "relevant_global_filings": len(filings),
            "in_universe_filings": len(report_events),
            "primary_index_verified": sum(row.get("source_status") == "primary_index_verified" for row in report_events),
            "pending_verification": sum(row.get("source_status") == "pending_verification" for row in report_events),
        },
        "errors": errors,
        "requests_made": guard.total_attempts,
        "request_rate_limit_per_second": MAX_REQUESTS_PER_SECOND,
        "ledger_rows_appended": appended,
        **_authority(),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--symbols", required=True, help="Comma-separated governed issuer-symbol allowlist")
    parser.add_argument("--ledger", type=Path, default=DEFAULT_LEDGER_PATH)
    parser.add_argument("--state", type=Path, default=DEFAULT_STATE_PATH)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT_PATH)
    parser.add_argument("--print", action="store_true", dest="print_report")
    args = parser.parse_args()
    report = collect_latest_filings(
        args.symbols.split(","),
        ledger_path=args.ledger,
        state_path=args.state,
    )
    _atomic_json(args.report, report)
    if args.print_report:
        print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["status"] in {"ok", "no_change"} else 2


if __name__ == "__main__":
    raise SystemExit(main())

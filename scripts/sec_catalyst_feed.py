#!/usr/bin/env python3
"""Read-only SEC EDGAR filing catalyst adapter.

SEC asks automated clients to identify themselves.  The adapter therefore
fails closed until ``SEC_USER_AGENT`` contains a real name and contact email.
It reads public JSON endpoints and writes only an atomic report, never a ledger.
"""
from __future__ import annotations

import argparse
import json
import os
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import requests


DEFAULT_REPORT_PATH = Path.home() / ".vibe-trading" / "reports" / "sec-catalyst-feed.json"
TICKER_MAP_URL = "https://www.sec.gov/files/company_tickers.json"
SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK{cik}.json"
ARCHIVE_DOCUMENT_URL = "https://www.sec.gov/Archives/edgar/data/{cik_number}/{accession}/{document}"
MATERIAL_FORMS = {"8-K", "10-Q", "10-K", "6-K", "20-F", "S-3", "424B2", "424B3", "424B5"}


def _authority() -> dict[str, bool]:
    return {"execution_enabled": False, "can_submit_orders": False}


def _atomic_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(path)


def _valid_user_agent(value: str) -> bool:
    text = value.strip()
    return bool(len(text) >= 8 and "@" in text and not re.search(r"example\.com|replace|todo", text, re.I))


def build_disabled_report(symbols: list[str], *, reason: str) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "provider": "sec_edgar",
        "mode": "read_only_public_filings",
        "status": "disabled",
        "freshness": "missing",
        "symbols": sorted({value.strip().upper() for value in symbols if value.strip()}),
        "catalysts": [],
        "reason": reason,
        "source_labels": ["sec_company_tickers", "sec_company_submissions"],
        **_authority(),
    }


def classify_filing(
    *,
    symbol: str,
    form: str,
    accession: str,
    filed_at: str,
    primary_document: str,
    items: str = "",
    accepted_at: str = "",
    cik: str | int | None = None,
) -> dict[str, Any]:
    normalized_form = form.strip().upper()
    if normalized_form in {"8-K", "6-K"}:
        event_type, priority = "material_current_report", "high"
    elif normalized_form in {"10-Q", "10-K", "20-F"}:
        event_type, priority = "periodic_financial_report", "high"
    elif normalized_form.startswith("424B") or normalized_form == "S-3":
        event_type, priority = "capital_markets_filing", "medium"
    else:
        event_type, priority = "other_filing", "low"
    cik_number = str(cik or "1045810").lstrip("0")
    compact_accession = accession.replace("-", "")
    source_url = ARCHIVE_DOCUMENT_URL.format(
        cik_number=cik_number,
        accession=compact_accession,
        document=primary_document,
    )
    return {
        "symbol": symbol.strip().upper(),
        "form": normalized_form,
        "event_type": event_type,
        "priority": priority,
        "filed_at": filed_at,
        "accepted_at": accepted_at or None,
        "items": [value.strip() for value in items.split(",") if value.strip()],
        "accession": accession,
        "primary_document": primary_document,
        "source": "sec_edgar_submissions",
        "source_url": source_url,
        "freshness": "live",
        **_authority(),
    }


def _ticker_map(session: requests.Session) -> dict[str, str]:
    response = session.get(TICKER_MAP_URL, timeout=20)
    response.raise_for_status()
    payload = response.json()
    output: dict[str, str] = {}
    for row in payload.values() if isinstance(payload, dict) else []:
        if not isinstance(row, dict):
            continue
        ticker = str(row.get("ticker") or "").upper()
        cik = str(row.get("cik_str") or "")
        if ticker and cik:
            output[ticker] = cik.zfill(10)
    return output


def partition_sec_eligible_symbols(symbols: list[str], ticker_map: dict[str, str]) -> tuple[list[str], list[str]]:
    """Keep non-issuer instruments visible without misclassifying them as EDGAR errors."""
    eligible = [symbol for symbol in symbols if symbol in ticker_map]
    skipped = [symbol for symbol in symbols if symbol not in ticker_map]
    return eligible, skipped


def fetch_sec_catalysts(
    symbols: list[str],
    *,
    user_agent: str | None = None,
    lookback_days: int = 3,
    session: requests.Session | None = None,
) -> dict[str, Any]:
    clean_symbols = sorted({value.strip().upper() for value in symbols if value.strip()})
    identity = (user_agent or os.getenv("SEC_USER_AGENT") or "").strip()
    if not _valid_user_agent(identity):
        return build_disabled_report(clean_symbols, reason="SEC_USER_AGENT is not configured with a contact email")
    client = session or requests.Session()
    client.headers.update({"User-Agent": identity, "Accept-Encoding": "gzip, deflate"})
    errors: list[str] = []
    catalysts: list[dict[str, Any]] = []
    try:
        mapping = _ticker_map(client)
    except Exception as exc:
        report = build_disabled_report(clean_symbols, reason=f"ticker_map_unavailable:{type(exc).__name__}")
        report["status"] = "degraded"
        return report
    cutoff = (datetime.now(timezone.utc).date() - timedelta(days=max(0, lookback_days))).isoformat()
    eligible_symbols, skipped_symbols = partition_sec_eligible_symbols(clean_symbols, mapping)
    for symbol in eligible_symbols:
        cik = mapping[symbol]
        try:
            response = client.get(SUBMISSIONS_URL.format(cik=cik), timeout=20)
            response.raise_for_status()
            recent = ((response.json().get("filings") or {}).get("recent") or {})
        except Exception as exc:
            errors.append(f"{symbol}:{type(exc).__name__}")
            continue
        forms = recent.get("form") or []
        for index, form in enumerate(forms):
            filed_at = str((recent.get("filingDate") or [""] * len(forms))[index])
            if filed_at < cutoff or str(form).upper() not in MATERIAL_FORMS:
                continue
            catalysts.append(
                classify_filing(
                    symbol=symbol,
                    form=str(form),
                    accession=str((recent.get("accessionNumber") or [""] * len(forms))[index]),
                    filed_at=filed_at,
                    primary_document=str((recent.get("primaryDocument") or [""] * len(forms))[index]),
                    items=str((recent.get("items") or [""] * len(forms))[index]),
                    accepted_at=str((recent.get("acceptanceDateTime") or [""] * len(forms))[index]),
                    cik=cik,
                )
            )
    catalysts.sort(key=lambda row: (row["filed_at"], row["priority"], row["symbol"]), reverse=True)
    return {
        "schema_version": 1,
        "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "provider": "sec_edgar",
        "mode": "read_only_public_filings",
        "status": "ok" if catalysts and not errors else "degraded" if errors else "ok",
        "freshness": "live",
        "symbols": clean_symbols,
        "sec_eligible_symbols": eligible_symbols,
        "skipped_non_issuer_symbols": skipped_symbols,
        "lookback_days": lookback_days,
        "catalysts": catalysts,
        "errors": errors,
        "source_labels": ["sec_company_tickers", "sec_company_submissions"],
        **_authority(),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--symbols", required=True, help="Comma-separated US equity symbols")
    parser.add_argument("--lookback-days", type=int, default=3)
    parser.add_argument("--out", type=Path, default=DEFAULT_REPORT_PATH)
    parser.add_argument("--print", action="store_true", dest="print_report")
    args = parser.parse_args()
    report = fetch_sec_catalysts(args.symbols.split(","), lookback_days=args.lookback_days)
    _atomic_json(args.out, report)
    if args.print_report:
        print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

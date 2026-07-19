"""Read-only SEC Form 4 insider-buying scanner.

Uses public SEC EDGAR endpoints to watch our core symbols for recent Form 4
open-market acquisitions. This is a slow swing-context layer, not an options
entry signal. No broker calls and no orders.
"""
from __future__ import annotations

import argparse
import json
import re
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
LOG_PATH = ROOT / "data" / "sec_insider_buying_log.jsonl"
REPORT_PATH = Path.home() / ".vibe-trading" / "reports" / "sec-insider-buying.json"

SEC_COMPANY_TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"
SEC_SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK{cik}.json"
SEC_ARCHIVE_URL = "https://www.sec.gov/Archives/edgar/data/{cik_int}/{accession}/{document}"
USER_AGENT = "VibeTradingBot/1.0 kennethanthonymeyers@yahoo.com"

DEFAULT_SYMBOLS = [
    "SPY", "QQQ", "IWM", "SMH", "NVDA", "AMD", "AVGO", "MSFT", "AAPL",
    "TSLA", "PLTR", "COIN", "MSTR", "HOOD", "LLY", "NVO", "RIVN",
    "NKE", "LULU", "COST", "WMT", "CELH", "GME", "AMC",
]


def _http_json(url: str, timeout: int = 20) -> Any:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept-Encoding": "identity"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8", errors="replace"))


def _http_text(url: str, timeout: int = 20) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept-Encoding": "identity"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read().decode("utf-8", errors="replace")


def fetch_ticker_cik_map() -> dict[str, str]:
    payload = _http_json(SEC_COMPANY_TICKERS_URL)
    mapping: dict[str, str] = {}
    if isinstance(payload, dict):
        rows = payload.values()
    else:
        rows = payload or []
    for row in rows:
        if not isinstance(row, dict):
            continue
        ticker = str(row.get("ticker") or "").upper()
        cik = str(row.get("cik_str") or "").zfill(10)
        if ticker and cik:
            mapping[ticker] = cik
    return mapping


def fetch_recent_filings(cik: str) -> list[dict[str, Any]]:
    payload = _http_json(SEC_SUBMISSIONS_URL.format(cik=cik))
    recent = (payload.get("filings") or {}).get("recent") if isinstance(payload, dict) else {}
    if not isinstance(recent, dict):
        return []
    forms = recent.get("form") or []
    accession_numbers = recent.get("accessionNumber") or []
    filing_dates = recent.get("filingDate") or []
    report_dates = recent.get("reportDate") or []
    documents = recent.get("primaryDocument") or []
    rows = []
    for idx, form in enumerate(forms):
        if str(form).upper() != "4":
            continue
        rows.append({
            "form": "4",
            "accession_number": accession_numbers[idx] if idx < len(accession_numbers) else "",
            "filing_date": filing_dates[idx] if idx < len(filing_dates) else "",
            "report_date": report_dates[idx] if idx < len(report_dates) else "",
            "primary_document": documents[idx] if idx < len(documents) else "",
        })
    return rows


def _xml_text(node: ET.Element | None, path: str) -> str:
    if node is None:
        return ""
    found = node.find(path)
    return (found.text or "").strip() if found is not None and found.text else ""


def parse_form4_acquisitions(xml_text: str) -> dict[str, Any]:
    if "<html" in xml_text[:500].lower():
        raise ValueError("SEC returned transformed HTML instead of raw Form 4 XML")
    xml_text = re.sub(r"^\s*<\?xml[^>]*>\s*", "", xml_text)
    root = ET.fromstring(xml_text)
    for elem in root.iter():
        if "}" in elem.tag:
            elem.tag = elem.tag.split("}", 1)[1]
    owner = root.find(".//reportingOwner")
    owner_name = _xml_text(owner, ".//rptOwnerName")
    issuer_symbol = _xml_text(root.find(".//issuer"), ".//issuerTradingSymbol").upper()
    acquisitions = []
    for tx in root.findall(".//nonDerivativeTransaction"):
        code = _xml_text(tx, ".//transactionAcquiredDisposedCode/value").upper()
        tx_code = _xml_text(tx, ".//transactionCode").upper()
        if code != "A" or tx_code not in {"P", ""}:
            continue
        shares = float(_xml_text(tx, ".//transactionShares/value") or 0)
        price = float(_xml_text(tx, ".//transactionPricePerShare/value") or 0)
        acquisitions.append({
            "security": _xml_text(tx, ".//securityTitle/value"),
            "transaction_date": _xml_text(tx, ".//transactionDate/value"),
            "transaction_code": tx_code or "unknown",
            "shares": round(shares, 4),
            "price": round(price, 4),
            "estimated_value": round(shares * price, 2),
        })
    return {
        "issuer_symbol": issuer_symbol,
        "owner_name": owner_name,
        "acquisition_count": len(acquisitions),
        "total_estimated_value": round(sum(float(a["estimated_value"]) for a in acquisitions), 2),
        "acquisitions": acquisitions,
    }


def _filing_url(cik: str, filing: dict[str, Any]) -> str:
    accession = str(filing.get("accession_number") or "")
    document = Path(str(filing.get("primary_document") or "")).name
    cik_int = str(int(cik))
    return SEC_ARCHIVE_URL.format(cik_int=cik_int, accession=accession.replace("-", ""), document=document)


def _within_days(date_text: str, days: int, now: datetime | None = None) -> bool:
    if not date_text:
        return False
    now = now or datetime.now(timezone.utc)
    try:
        parsed = datetime.fromisoformat(date_text).replace(tzinfo=timezone.utc)
    except ValueError:
        return False
    return parsed >= now - timedelta(days=days)


def scan_symbol(symbol: str, cik: str, lookback_days: int = 14, max_filings: int = 3) -> dict[str, Any]:
    try:
        filings = [f for f in fetch_recent_filings(cik) if _within_days(str(f.get("filing_date")), lookback_days)]
        events = []
        for filing in filings[:max_filings]:
            if not filing.get("primary_document") or not filing.get("accession_number"):
                continue
            url = _filing_url(cik, filing)
            parsed = parse_form4_acquisitions(_http_text(url))
            if parsed["acquisition_count"] <= 0:
                continue
            events.append({**filing, "url": url, **parsed})
        return {
            "symbol": symbol.upper(),
            "status": "ok",
            "cik": cik,
            "filings_checked": len(filings[:max_filings]),
            "buy_event_count": len(events),
            "total_estimated_value": round(sum(float(e["total_estimated_value"]) for e in events), 2),
            "events": events,
            "context_signal": bool(events),
        }
    except Exception as exc:
        return {
            "symbol": symbol.upper(),
            "status": "error",
            "cik": cik,
            "error": str(exc)[:200],
        }


def build_report(symbols: list[str] | None = None, lookback_days: int = 14) -> dict[str, Any]:
    symbols = symbols or DEFAULT_SYMBOLS
    cik_map = fetch_ticker_cik_map()
    scans = []
    for symbol in symbols:
        cik = cik_map.get(symbol.upper())
        if not cik:
            scans.append({"symbol": symbol.upper(), "status": "not_found", "context_signal": False})
            continue
        scans.append(scan_symbol(symbol, cik, lookback_days=lookback_days))
    signals = [row for row in scans if row.get("context_signal")]
    signals.sort(key=lambda row: float(row.get("total_estimated_value") or 0), reverse=True)
    return {
        "date": datetime.now(timezone.utc).date().isoformat(),
        "timestamp": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "provider": "sec_insider_buying_scanner",
        "source": "sec_edgar_public_apis",
        "mode": "context_only",
        "execution_enabled": False,
        "lookback_days": lookback_days,
        "symbol_count": len(scans),
        "signal_count": len(signals),
        "signals": signals,
        "scans": scans,
        "warnings": [
            "Context only. No broker orders are wired.",
            "ETFs usually have no Form 4 insider activity and may show not_found.",
            "Insider buying is a slow swing context, not an intraday options entry.",
        ],
    }


def append_log(report: dict[str, Any], log_path: Path = LOG_PATH) -> None:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(report, separators=(",", ":")) + "\n")


def write_report(report: dict[str, Any], report_path: Path = REPORT_PATH) -> Path:
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    return report_path


def print_report(report: dict[str, Any]) -> None:
    print("\nSEC Insider Buying Scanner | context only")
    print("=" * 72)
    print(f"lookback={report['lookback_days']}d symbols={report['symbol_count']} signals={report['signal_count']}")
    for row in report["signals"][:15]:
        print(f"{row['symbol']:<6} buys={row['buy_event_count']} value=${row['total_estimated_value']:,.0f}")
    print("No orders placed.\n")


def main() -> int:
    parser = argparse.ArgumentParser(description="Scan public SEC Form 4 insider buying.")
    parser.add_argument("--symbols", default=",".join(DEFAULT_SYMBOLS))
    parser.add_argument("--lookback-days", type=int, default=14)
    parser.add_argument("--log-path", type=Path, default=LOG_PATH)
    parser.add_argument("--report-path", type=Path, default=REPORT_PATH)
    parser.add_argument("--print", action="store_true", dest="print_output")
    args = parser.parse_args()
    symbols = [s.strip().upper() for s in args.symbols.split(",") if s.strip()]
    report = build_report(symbols=symbols, lookback_days=args.lookback_days)
    append_log(report, args.log_path)
    write_report(report, args.report_path)
    if args.print_output:
        print_report(report)
    else:
        print(f"SEC insider buying scan logged to {args.log_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

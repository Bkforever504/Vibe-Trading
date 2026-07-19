#!/usr/bin/env python3
"""Autonomous public social intake scanner.

Collects public Reddit RSS mentions of stock cashtags and appends them to the
same social-arbitrage observation file used by the weekly hot-instrument report.

No logged-in scraping. No private feeds. No broker calls. Context only.
"""
from __future__ import annotations

import argparse
import json
import re
import time
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from html import unescape
from pathlib import Path
from typing import Any, Callable

ROOT = Path(__file__).resolve().parent.parent
VIBE_HOME = Path.home() / ".vibe-trading"
OBSERVATIONS_PATH = VIBE_HOME / "social-arb-observations.json"
REPORT_PATH = VIBE_HOME / "reports" / "public-social-intake.json"
LOG_PATH = ROOT / "data" / "public_social_intake_log.jsonl"

USER_AGENT = "VibeTradingPublicSocialIntake/1.0"
DEFAULT_SUBREDDITS = ["Shortsqueeze", "wallstreetbets", "options", "stocks", "Daytrading", "pennystocks"]
REQUEST_DELAY_SECONDS = 2.0
CASHTAG_RE = re.compile(r"(?<![A-Z0-9])\$([A-Z][A-Z0-9]{1,5})(?:\b|$)")
IGNORED_CASHTAGS = {
    "BTC",
    "ETH",
    "SOL",
    "DOGE",
    "BNB",
    "XRP",
    "USDT",
    "USDC",
}


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _read_json(path: Path, fallback: Any) -> Any:
    if not path.exists():
        return fallback
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except json.JSONDecodeError:
        return fallback


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def _append_jsonl(path: Path, row: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(row, separators=(",", ":"), default=str) + "\n")


def extract_cashtags(text: str) -> list[str]:
    """Return unique equity-style cashtags from text in mention order."""
    found: list[str] = []
    for match in CASHTAG_RE.finditer(str(text or "").upper()):
        symbol = match.group(1).upper()
        suffix = str(text or "")[match.end(1): match.end(1) + 2].upper()
        if symbol in IGNORED_CASHTAGS or suffix == ".X":
            continue
        if symbol not in found:
            found.append(symbol)
    return found


def reddit_rss_url(subreddit: str) -> str:
    clean = str(subreddit).strip().strip("/")
    return f"https://www.reddit.com/r/{clean}/new/.rss"


def _element_text(element: ET.Element, suffix: str) -> str:
    for child in list(element):
        if child.tag.lower().endswith(suffix.lower()):
            return child.text or ""
    return ""


def _element_link(element: ET.Element) -> str:
    for child in list(element):
        if not child.tag.lower().endswith("link"):
            continue
        href = child.attrib.get("href")
        if href:
            return href
        if child.text:
            return child.text
    return ""


def parse_reddit_rss(xml_text: str, subreddit: str) -> list[dict[str, Any]]:
    root = ET.fromstring(xml_text)
    entries = [node for node in root.iter() if node.tag.lower().endswith("entry")]
    if not entries:
        entries = [node for node in root.iter() if node.tag.lower().endswith("item")]

    rows: list[dict[str, Any]] = []
    for entry in entries:
        title = unescape(_element_text(entry, "title")).strip()
        summary = unescape(_element_text(entry, "summary") or _element_text(entry, "description")).strip()
        rows.append({
            "subreddit": subreddit,
            "title": title,
            "summary": summary,
            "url": _element_link(entry),
            "updated": _element_text(entry, "updated") or _element_text(entry, "pubDate"),
            "id": _element_text(entry, "id") or _element_text(entry, "guid"),
        })
    return rows


def fetch_reddit_rss(subreddit: str, limit: int = 25, timeout: int = 20) -> list[dict[str, Any]]:
    req = urllib.request.Request(reddit_rss_url(subreddit), headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        xml_text = resp.read().decode("utf-8", errors="replace")
    return parse_reddit_rss(xml_text, subreddit)[:limit]


def _observation_key(row: dict[str, Any]) -> str:
    return "|".join([
        str(row.get("source") or ""),
        str(row.get("platform") or ""),
        str(row.get("keyword") or "").upper(),
        str(row.get("url") or row.get("caption") or "")[:240],
    ])


def append_new_observations(
    rows: list[dict[str, Any]],
    *,
    observations_path: Path = OBSERVATIONS_PATH,
) -> int:
    existing = _read_json(observations_path, [])
    observations = existing if isinstance(existing, list) else []
    seen = {_observation_key(row) for row in observations if isinstance(row, dict)}

    added = 0
    for row in rows:
        key = _observation_key(row)
        if key in seen:
            continue
        observations.append(row)
        seen.add(key)
        added += 1
    _write_json(observations_path, observations)
    return added


def _observation_from_entry(symbol: str, entry: dict[str, Any], now: datetime) -> dict[str, Any]:
    title = str(entry.get("title") or "")
    summary = str(entry.get("summary") or "")
    caption = " ".join(part for part in (title, summary) if part).strip()
    subreddit = str(entry.get("subreddit") or "")
    return {
        "source": "reddit_public_rss",
        "platform": "reddit",
        "subreddit": subreddit,
        "keyword": f"${symbol.upper()}",
        "caption": caption[:1200],
        "title": title[:500],
        "observed_at": now.isoformat().replace("+00:00", "Z"),
        "post_updated_at": str(entry.get("updated") or ""),
        "url": str(entry.get("url") or entry.get("id") or ""),
        "views": 0,
        "likes": 0,
        "comments": 0,
        "growth_pct": 0,
        "mode": "context_only",
        "execution_enabled": False,
        "notes": "Autonomous public Reddit RSS observation. Context-only; never an execution signal by itself.",
    }


def _observations_from_entries(entries: list[dict[str, Any]], now: datetime) -> list[dict[str, Any]]:
    observations: list[dict[str, Any]] = []
    for entry in entries:
        text = f"{entry.get('title') or ''} {entry.get('summary') or ''}"
        for symbol in extract_cashtags(text):
            observations.append(_observation_from_entry(symbol, entry, now))
    return observations


def build_report(
    *,
    subreddits: list[str] | None = None,
    fetcher: Callable[[str, int], list[dict[str, Any]]] = fetch_reddit_rss,
    observations_path: Path = OBSERVATIONS_PATH,
    log_path: Path = LOG_PATH,
    report_path: Path = REPORT_PATH,
    limit_per_subreddit: int = 25,
    append: bool = True,
    now: datetime | None = None,
    request_delay_seconds: float = REQUEST_DELAY_SECONDS,
    sleep_fn: Callable[[float], None] = time.sleep,
) -> dict[str, Any]:
    now = now or _now_utc()
    subreddits = subreddits or DEFAULT_SUBREDDITS
    all_observations: list[dict[str, Any]] = []
    errors: list[str] = []
    fetched_counts: dict[str, int] = {}

    for idx, subreddit in enumerate(subreddits):
        if idx and request_delay_seconds > 0:
            sleep_fn(request_delay_seconds)
        try:
            entries = fetcher(subreddit, limit_per_subreddit)
        except Exception as exc:
            errors.append(f"{subreddit}: {type(exc).__name__}: {exc}")
            continue
        fetched_counts[subreddit] = len(entries)
        all_observations.extend(_observations_from_entries(entries, now))

    by_symbol: dict[str, int] = {}
    by_subreddit: dict[str, int] = {}
    for row in all_observations:
        symbol = str(row.get("keyword") or "").lstrip("$").upper()
        subreddit = str(row.get("subreddit") or "")
        by_symbol[symbol] = by_symbol.get(symbol, 0) + 1
        by_subreddit[subreddit] = by_subreddit.get(subreddit, 0) + 1

    new_count = append_new_observations(all_observations, observations_path=observations_path) if append else 0
    report = {
        "date": now.date().isoformat(),
        "timestamp": now.isoformat().replace("+00:00", "Z"),
        "provider": "public_social_intake_scanner",
        "source": "reddit_public_rss",
        "mode": "context_only",
        "execution_enabled": False,
        "subreddits": subreddits,
        "fetched_counts": fetched_counts,
        "observation_count": len(all_observations),
        "new_observation_count": new_count,
        "by_symbol": dict(sorted(by_symbol.items())),
        "by_subreddit": dict(sorted(by_subreddit.items())),
        "errors": errors,
        "observations_path": str(observations_path),
        "warnings": [
            "Context only. No broker orders are wired.",
            "Uses public Reddit RSS only; no logged-in social scraping.",
            "X/Threads/TikTok/Instagram remain manual or official-API only unless explicitly approved.",
        ],
    }
    _write_json(report_path, report)
    _append_jsonl(log_path, report)
    return report


def print_report(report: dict[str, Any]) -> None:
    print("\nPublic Social Intake | context only")
    print("=" * 64)
    print(
        f"source={report['source']} observations={report['observation_count']} "
        f"new={report['new_observation_count']} symbols={report['by_symbol']}"
    )
    if report.get("errors"):
        print(f"errors={report['errors']}")
    print("No orders placed.\n")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Collect public Reddit cashtag observations.")
    parser.add_argument("--subreddit", action="append", dest="subreddits", help="Subreddit to scan; repeatable.")
    parser.add_argument("--limit", type=int, default=25, help="Posts per subreddit.")
    parser.add_argument("--observations", type=Path, default=OBSERVATIONS_PATH)
    parser.add_argument("--log-path", type=Path, default=LOG_PATH)
    parser.add_argument("--report-path", type=Path, default=REPORT_PATH)
    parser.add_argument("--no-append", action="store_true", help="Build report without appending observations.")
    parser.add_argument("--print", action="store_true", dest="print_output")
    args = parser.parse_args(argv)

    report = build_report(
        subreddits=args.subreddits,
        observations_path=args.observations,
        log_path=args.log_path,
        report_path=args.report_path,
        limit_per_subreddit=args.limit,
        append=not args.no_append,
    )
    if args.print_output:
        print_report(report)
    else:
        print(f"Public social intake report written to: {args.report_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

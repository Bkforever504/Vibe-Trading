#!/usr/bin/env python3
"""X (Twitter) intake scanner.

Pulls cashtag/keyword mentions from public X via tweety-ns (no-login guest
session). Writes to the same social-arb-observations file used by the Reddit
intake so downstream signal pipelines consume both feeds uniformly.

Context-only. Never emits execution signals.

Two lanes:
  - curated: hand-picked FinTwit accounts (SPY / 0DTE / options focus)
  - broad:   hashtag firehose ($SPY, #0DTE, #ES_F, etc.)

Falls back gracefully on rate-limit / auth errors so the scheduler never fails
closed.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
VIBE_HOME = Path.home() / ".vibe-trading"
OBSERVATIONS_PATH = VIBE_HOME / "social-arb-observations.json"
REPORT_PATH = VIBE_HOME / "reports" / "x-intake.json"
LOG_PATH = ROOT / "data" / "x_intake_log.jsonl"

CASHTAG_RE = re.compile(r"(?<![A-Z0-9])\$([A-Z][A-Z0-9]{1,5})(?:\b|$)")
IGNORED_CASHTAGS = {"BTC", "ETH", "SOL", "DOGE", "BNB", "XRP", "USDT", "USDC"}

# Curated FinTwit handles focused on SPY / index / 0DTE / macro-vol posture.
# Deliberately small and public. Extend by editing this list.
CURATED_HANDLES = [
    "unusual_whales",
    "Barchart",
    "zerohedge",
    "DeItaone",
    "spotgamma",
    "Ksidiii",
    "CGasparino",
    "SPYJared",
    "OptionsHawk",
    "hmeisler",
    "ThePupOfWallSt",
    "MenthorQpro",
    "sentimentrader",
    "GunjanJS",
]

# Broad-firehose queries. Kept tight to reduce garbage.
BROAD_QUERIES = [
    "$SPY -filter:replies min_faves:25",
    "$QQQ -filter:replies min_faves:25",
    "$IWM -filter:replies min_faves:15",
    "$ES_F -filter:replies min_faves:10",
    "#0DTE -filter:replies min_faves:10",
    "#SPY options -filter:replies min_faves:10",
]

DEFAULT_LIMIT_PER_QUERY = 20
DEFAULT_LIMIT_PER_HANDLE = 15


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
    found: list[str] = []
    for match in CASHTAG_RE.finditer(str(text or "").upper()):
        symbol = match.group(1).upper()
        suffix = str(text or "")[match.end(1): match.end(1) + 2].upper()
        if symbol in IGNORED_CASHTAGS or suffix == ".X":
            continue
        if symbol not in found:
            found.append(symbol)
    return found


def _observation_key(row: dict[str, Any]) -> str:
    return "|".join([
        str(row.get("source") or ""),
        str(row.get("platform") or ""),
        str(row.get("keyword") or "").upper(),
        str(row.get("url") or row.get("caption") or "")[:240],
    ])


def append_new_observations(rows: list[dict[str, Any]], *, path: Path = OBSERVATIONS_PATH) -> int:
    existing = _read_json(path, [])
    observations = existing if isinstance(existing, list) else []
    seen = {_observation_key(r) for r in observations if isinstance(r, dict)}
    added = 0
    for row in rows:
        key = _observation_key(row)
        if key in seen:
            continue
        observations.append(row)
        seen.add(key)
        added += 1
    _write_json(path, observations)
    return added


def _tweet_to_observation(symbol: str, tweet: dict[str, Any], lane: str, now: datetime) -> dict[str, Any]:
    text = str(tweet.get("text") or "")
    author = str(tweet.get("author") or "")
    url = str(tweet.get("url") or "")
    return {
        "source": f"x_public_{lane}",
        "platform": "x",
        "handle": author,
        "keyword": f"${symbol.upper()}",
        "caption": text[:1200],
        "title": text[:280],
        "observed_at": now.isoformat().replace("+00:00", "Z"),
        "post_updated_at": str(tweet.get("created_at") or ""),
        "url": url,
        "views": int(tweet.get("views") or 0),
        "likes": int(tweet.get("likes") or 0),
        "comments": int(tweet.get("replies") or 0),
        "retweets": int(tweet.get("retweets") or 0),
        "growth_pct": 0,
        "mode": "context_only",
        "execution_enabled": False,
        "notes": "Autonomous public X observation. Context-only; never an execution signal by itself.",
    }


async def _fetch_via_tweety(handles: list[str], queries: list[str], limit_handle: int, limit_query: int) -> tuple[list[dict[str, Any]], list[str]]:
    """Use tweety-ns to pull tweets. Returns (tweets, errors)."""
    tweets: list[dict[str, Any]] = []
    errors: list[str] = []
    try:
        from tweety import TwitterAsync
    except Exception as exc:
        return tweets, [f"import tweety failed: {type(exc).__name__}: {exc}"]

    app = TwitterAsync("x_intake_session")
    try:
        await app.connect()
    except Exception as exc:
        return tweets, [f"connect failed: {type(exc).__name__}: {exc}"]

    def _norm(t: Any, lane: str) -> dict[str, Any]:
        author = ""
        try:
            author = str(getattr(getattr(t, "author", None), "username", "") or "")
        except Exception:
            pass
        return {
            "lane": lane,
            "author": author,
            "text": str(getattr(t, "text", "") or ""),
            "url": str(getattr(t, "url", "") or ""),
            "created_at": str(getattr(t, "created_on", "") or ""),
            "likes": int(getattr(t, "likes", 0) or 0),
            "retweets": int(getattr(t, "retweet_counts", 0) or 0),
            "replies": int(getattr(t, "reply_counts", 0) or 0),
            "views": int(getattr(t, "views", 0) or 0),
        }

    for handle in handles:
        try:
            resp = await app.get_tweets(handle, pages=1)
            count = 0
            for tw in resp:
                tweets.append(_norm(tw, "curated"))
                count += 1
                if count >= limit_handle:
                    break
        except Exception as exc:
            errors.append(f"handle {handle}: {type(exc).__name__}: {exc}")

    for query in queries:
        try:
            resp = await app.search(query, pages=1)
            count = 0
            for tw in resp:
                tweets.append(_norm(tw, "broad"))
                count += 1
                if count >= limit_query:
                    break
        except Exception as exc:
            errors.append(f"query {query!r}: {type(exc).__name__}: {exc}")

    return tweets, errors


def _tweets_to_observations(tweets: list[dict[str, Any]], now: datetime) -> list[dict[str, Any]]:
    observations: list[dict[str, Any]] = []
    for tw in tweets:
        text = tw.get("text") or ""
        cashtags = extract_cashtags(text)
        if not cashtags:
            continue
        lane = str(tw.get("lane") or "broad")
        for symbol in cashtags:
            observations.append(_tweet_to_observation(symbol, tw, lane, now))
    return observations


def build_report(
    *,
    handles: list[str] | None = None,
    queries: list[str] | None = None,
    limit_per_handle: int = DEFAULT_LIMIT_PER_HANDLE,
    limit_per_query: int = DEFAULT_LIMIT_PER_QUERY,
    append: bool = True,
    now: datetime | None = None,
) -> dict[str, Any]:
    now = now or _now_utc()
    handles = handles if handles is not None else CURATED_HANDLES
    queries = queries if queries is not None else BROAD_QUERIES

    tweets, errors = asyncio.run(_fetch_via_tweety(handles, queries, limit_per_handle, limit_per_query))
    observations = _tweets_to_observations(tweets, now)

    by_symbol: dict[str, int] = {}
    by_handle: dict[str, int] = {}
    by_lane: dict[str, int] = {}
    for row in observations:
        symbol = str(row.get("keyword") or "").lstrip("$").upper()
        handle = str(row.get("handle") or "")
        lane = str(row.get("source") or "")
        by_symbol[symbol] = by_symbol.get(symbol, 0) + 1
        if handle:
            by_handle[handle] = by_handle.get(handle, 0) + 1
        by_lane[lane] = by_lane.get(lane, 0) + 1

    new_count = append_new_observations(observations) if append else 0

    report = {
        "date": now.date().isoformat(),
        "timestamp": now.isoformat().replace("+00:00", "Z"),
        "provider": "x_intake_scanner",
        "mode": "context_only",
        "execution_enabled": False,
        "can_submit_orders": False,
        "handles_probed": handles,
        "queries_probed": queries,
        "tweets_fetched": len(tweets),
        "observations_generated": len(observations),
        "new_observations_appended": new_count,
        "top_symbols": sorted(by_symbol.items(), key=lambda kv: kv[1], reverse=True)[:25],
        "by_handle": by_handle,
        "by_lane": by_lane,
        "errors": errors,
    }
    _write_json(REPORT_PATH, report)
    _append_jsonl(LOG_PATH, report)
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description="X (Twitter) public intake scanner. Context-only.")
    parser.add_argument("--no-append", action="store_true", help="Do not persist to observations file.")
    parser.add_argument("--print", action="store_true", help="Print JSON report to stdout.")
    parser.add_argument("--limit-per-handle", type=int, default=DEFAULT_LIMIT_PER_HANDLE)
    parser.add_argument("--limit-per-query", type=int, default=DEFAULT_LIMIT_PER_QUERY)
    args = parser.parse_args()

    report = build_report(
        append=not args.no_append,
        limit_per_handle=args.limit_per_handle,
        limit_per_query=args.limit_per_query,
    )
    if args.print:
        print(json.dumps(report, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

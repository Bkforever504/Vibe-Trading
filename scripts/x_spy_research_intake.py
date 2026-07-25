#!/usr/bin/env python3
"""Read-only X recent-search intake for SPY trading research.

The output is research context, never an execution signal. The client uses one
app-only Bearer Token, enforces local request budgets before each call, and
stores request provenance so social claims can be tested against later market
outcomes.
"""
from __future__ import annotations

import argparse
import json
import os
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

ROOT = Path(__file__).resolve().parent.parent
VIBE_HOME = Path.home() / ".vibe-trading"
ENV_PATH = ROOT / "agent" / ".env"
REPORT_PATH = VIBE_HOME / "reports" / "x-spy-research-intake.json"
LOG_PATH = ROOT / "data" / "x_spy_research_intake_log.jsonl"
BUDGET_PATH = VIBE_HOME / "x-api-request-budget.json"

X_RECENT_SEARCH_URL = "https://api.x.com/2/tweets/search/recent"
DEFAULT_QUERY = (
    '$SPY '
    '(options OR calls OR puts OR gamma OR dealer OR vwap OR volume OR "order flow") '
    "lang:en -is:retweet -is:reply"
)
DEFAULT_DAILY_REQUEST_CAP = 1
DEFAULT_MONTHLY_REQUEST_CAP = 20
USER_AGENT = "VibeTradingXSPYResearch/1.0"


class XResearchError(RuntimeError):
    """A sanitized X intake failure."""


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _safe_int(value: Any, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def load_env_file(path: Path = ENV_PATH) -> None:
    """Load missing environment variables without overriding the process."""
    if not path.exists():
        return
    for raw in path.read_text(encoding="utf-8-sig").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key:
            os.environ.setdefault(key, value)


def _read_json(path: Path, fallback: Any) -> Any:
    if not path.exists():
        return fallback
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        return fallback


def _atomic_write(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(temp, path)


def _append_jsonl(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, separators=(",", ":"), sort_keys=True) + "\n")


def request_budget(
    *,
    path: Path = BUDGET_PATH,
    now: datetime | None = None,
    daily_cap: int = DEFAULT_DAILY_REQUEST_CAP,
    monthly_cap: int = DEFAULT_MONTHLY_REQUEST_CAP,
) -> dict[str, Any]:
    now = now or _now_utc()
    state = _read_json(path, {})
    events = state.get("events") if isinstance(state, dict) else []
    events = [str(value) for value in events or []]
    day_prefix = now.date().isoformat()
    month_prefix = day_prefix[:7]
    daily_used = sum(value.startswith(day_prefix) for value in events)
    monthly_used = sum(value.startswith(month_prefix) for value in events)
    return {
        "daily_cap": daily_cap,
        "daily_used": daily_used,
        "daily_remaining": max(0, daily_cap - daily_used),
        "monthly_cap": monthly_cap,
        "monthly_used": monthly_used,
        "monthly_remaining": max(0, monthly_cap - monthly_used),
        "allowed": daily_used < daily_cap and monthly_used < monthly_cap,
    }


def record_request(path: Path = BUDGET_PATH, now: datetime | None = None) -> None:
    now = now or _now_utc()
    state = _read_json(path, {})
    events = state.get("events") if isinstance(state, dict) else []
    events = [str(value) for value in events or []]
    events.append(now.isoformat().replace("+00:00", "Z"))
    cutoff = str(now.year - 1)
    _atomic_write(path, {"events": [value for value in events if value[:4] >= cutoff]})


def build_search_url(query: str, max_results: int = 10) -> str:
    params = {
        "query": query,
        "max_results": max(10, min(100, int(max_results))),
        "tweet.fields": "author_id,created_at,lang,public_metrics,conversation_id,entities",
        "expansions": "author_id",
        "user.fields": "created_at,description,public_metrics,verified,username",
    }
    return f"{X_RECENT_SEARCH_URL}?{urllib.parse.urlencode(params)}"


def fetch_recent_posts(
    bearer_token: str,
    *,
    query: str = DEFAULT_QUERY,
    max_results: int = 10,
    timeout: int = 20,
    opener: Callable[..., Any] = urllib.request.urlopen,
) -> tuple[dict[str, Any], dict[str, str]]:
    if not bearer_token.strip():
        raise XResearchError("X_BEARER_TOKEN is not configured")
    request = urllib.request.Request(
        build_search_url(query, max_results),
        headers={
            "Authorization": f"Bearer {bearer_token.strip()}",
            "User-Agent": USER_AGENT,
        },
    )
    try:
        with opener(request, timeout=timeout) as response:
            payload = json.loads(response.read().decode("utf-8", errors="replace"))
            headers = {
                "x-rate-limit-limit": str(response.headers.get("x-rate-limit-limit") or ""),
                "x-rate-limit-remaining": str(response.headers.get("x-rate-limit-remaining") or ""),
                "x-rate-limit-reset": str(response.headers.get("x-rate-limit-reset") or ""),
            }
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")[:500]
        raise XResearchError(f"X API HTTP {exc.code}: {body}") from None
    except urllib.error.URLError as exc:
        raise XResearchError(f"X API connection failed: {exc.reason}") from None
    except json.JSONDecodeError:
        raise XResearchError("X API returned invalid JSON") from None
    if not isinstance(payload, dict):
        raise XResearchError("X API returned an unexpected response")
    return payload, headers


def normalize_response(
    payload: dict[str, Any],
    *,
    query: str,
    now: datetime | None = None,
) -> dict[str, Any]:
    now = now or _now_utc()
    users = {
        str(row.get("id")): row
        for row in ((payload.get("includes") or {}).get("users") or [])
        if isinstance(row, dict)
    }
    posts = []
    for row in payload.get("data") or []:
        if not isinstance(row, dict):
            continue
        text = str(row.get("text") or "")
        if "$SPY" not in text.upper():
            continue
        author = users.get(str(row.get("author_id")), {})
        metrics = row.get("public_metrics") if isinstance(row.get("public_metrics"), dict) else {}
        posts.append({
            "post_id": str(row.get("id") or ""),
            "created_at": row.get("created_at"),
            "author_id": str(row.get("author_id") or ""),
            "author_username": author.get("username"),
            "author_verified": bool(author.get("verified")),
            "author_followers": _safe_int(
                (author.get("public_metrics") or {}).get("followers_count"), 0
            ),
            "text": text[:1000],
            "like_count": _safe_int(metrics.get("like_count"), 0),
            "reply_count": _safe_int(metrics.get("reply_count"), 0),
            "repost_count": _safe_int(metrics.get("retweet_count"), 0),
            "quote_count": _safe_int(metrics.get("quote_count"), 0),
            "url": (
                f"https://x.com/{author.get('username')}/status/{row.get('id')}"
                if author.get("username") and row.get("id")
                else None
            ),
            "research_labels": {
                "source_claim_unverified": True,
                "outcome_test_required": True,
                "execution_eligible": False,
            },
        })
    return {
        "date": now.date().isoformat(),
        "timestamp": now.isoformat().replace("+00:00", "Z"),
        "provider": "x_spy_research_intake",
        "source": "x_api_v2_recent_search",
        "query": query,
        "mode": "context_only",
        "execution_enabled": False,
        "post_count": len(posts),
        "posts": posts,
        "result_count": _safe_int((payload.get("meta") or {}).get("result_count"), len(posts)),
        "newest_id": (payload.get("meta") or {}).get("newest_id"),
        "oldest_id": (payload.get("meta") or {}).get("oldest_id"),
        "warnings": [
            "X posts are unverified claims and may contain survivorship bias or promotion.",
            "No X post can change a trading rule or submit an order.",
            "Every proposed edge requires preregistration, historical testing, and forward shadow validation.",
        ],
    }


def run_intake(
    *,
    token: str,
    query: str = DEFAULT_QUERY,
    max_results: int = 10,
    report_path: Path = REPORT_PATH,
    log_path: Path = LOG_PATH,
    budget_path: Path = BUDGET_PATH,
    daily_cap: int = DEFAULT_DAILY_REQUEST_CAP,
    monthly_cap: int = DEFAULT_MONTHLY_REQUEST_CAP,
    now: datetime | None = None,
    fetcher: Callable[..., tuple[dict[str, Any], dict[str, str]]] = fetch_recent_posts,
    write: bool = True,
) -> dict[str, Any]:
    now = now or _now_utc()
    budget = request_budget(
        path=budget_path, now=now, daily_cap=daily_cap, monthly_cap=monthly_cap
    )
    if not budget["allowed"]:
        raise XResearchError(
            f"local X request budget exhausted: daily={budget['daily_used']}/{daily_cap}, "
            f"monthly={budget['monthly_used']}/{monthly_cap}"
        )
    if not token.strip():
        raise XResearchError("X_BEARER_TOKEN is not configured")
    # Record the attempt before sending it. Diagnostic/no-write requests still
    # consume API capacity and must never bypass the local cost guard.
    record_request(budget_path, now)
    payload, rate_headers = fetcher(token, query=query, max_results=max_results)
    report = normalize_response(payload, query=query, now=now)
    report["request_budget_before_call"] = budget
    report["rate_limit_headers"] = rate_headers
    if write:
        _atomic_write(report_path, report)
        _append_jsonl(log_path, report)
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--query", default=DEFAULT_QUERY)
    parser.add_argument("--max-results", type=int, default=10)
    parser.add_argument("--daily-request-cap", type=int, default=DEFAULT_DAILY_REQUEST_CAP)
    parser.add_argument("--monthly-request-cap", type=int, default=DEFAULT_MONTHLY_REQUEST_CAP)
    parser.add_argument("--no-write", action="store_true")
    parser.add_argument("--print", action="store_true", dest="print_output")
    args = parser.parse_args()

    load_env_file()
    token = os.environ.get("X_BEARER_TOKEN", "")
    try:
        report = run_intake(
            token=token,
            query=args.query,
            max_results=args.max_results,
            daily_cap=max(0, args.daily_request_cap),
            monthly_cap=max(0, args.monthly_request_cap),
            write=not args.no_write,
        )
    except XResearchError as exc:
        print(f"X SPY research intake blocked: {exc}")
        return 2
    if args.print_output:
        print(json.dumps({
            "provider": report["provider"],
            "post_count": report["post_count"],
            "mode": report["mode"],
            "execution_enabled": report["execution_enabled"],
            "request_budget_before_call": report["request_budget_before_call"],
        }, indent=2))
    else:
        print(f"X SPY research intake captured {report['post_count']} context-only posts.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

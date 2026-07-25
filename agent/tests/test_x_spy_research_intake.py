from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts import x_spy_research_intake as intake


def test_search_url_is_read_only_and_bounded() -> None:
    url = intake.build_search_url(intake.DEFAULT_QUERY, max_results=999)

    assert url.startswith("https://api.x.com/2/tweets/search/recent?")
    assert "max_results=100" in url
    assert "expansions=author_id" in url


def test_normalize_marks_every_post_unverified_and_non_executable() -> None:
    payload = {
        "data": [{
            "id": "123",
            "author_id": "7",
            "created_at": "2026-07-24T15:00:00Z",
            "text": "$SPY calls because gamma",
            "public_metrics": {"like_count": 10, "reply_count": 2, "retweet_count": 3},
        }],
        "includes": {"users": [{
            "id": "7",
            "username": "trader",
            "verified": True,
            "public_metrics": {"followers_count": 5000},
        }]},
        "meta": {"result_count": 1},
    }

    report = intake.normalize_response(
        payload,
        query=intake.DEFAULT_QUERY,
        now=datetime(2026, 7, 24, 15, tzinfo=timezone.utc),
    )

    assert report["mode"] == "context_only"
    assert report["execution_enabled"] is False
    assert report["post_count"] == 1
    assert report["posts"][0]["research_labels"]["source_claim_unverified"] is True
    assert report["posts"][0]["research_labels"]["execution_eligible"] is False


def test_request_budget_blocks_second_daily_call(tmp_path: Path) -> None:
    path = tmp_path / "budget.json"
    now = datetime(2026, 7, 24, 15, tzinfo=timezone.utc)
    path.write_text(json.dumps({"events": ["2026-07-24T14:00:00Z"]}), encoding="utf-8")

    budget = intake.request_budget(path=path, now=now, daily_cap=1, monthly_cap=20)

    assert budget["allowed"] is False
    assert budget["daily_remaining"] == 0


def test_run_intake_records_one_request_and_writes_context(tmp_path: Path) -> None:
    now = datetime(2026, 7, 24, 15, tzinfo=timezone.utc)

    def fake_fetcher(token: str, **kwargs):
        assert token == "secret"
        return {"data": [], "meta": {"result_count": 0}}, {
            "x-rate-limit-remaining": "449"
        }

    report = intake.run_intake(
        token="secret",
        report_path=tmp_path / "report.json",
        log_path=tmp_path / "log.jsonl",
        budget_path=tmp_path / "budget.json",
        now=now,
        fetcher=fake_fetcher,
    )

    assert report["post_count"] == 0
    assert report["execution_enabled"] is False
    assert intake.request_budget(
        path=tmp_path / "budget.json", now=now, daily_cap=1, monthly_cap=20
    )["allowed"] is False


def test_no_write_request_still_consumes_local_budget(tmp_path: Path) -> None:
    now = datetime(2026, 7, 24, 15, tzinfo=timezone.utc)

    report = intake.run_intake(
        token="secret",
        budget_path=tmp_path / "budget.json",
        now=now,
        write=False,
        fetcher=lambda *args, **kwargs: (
            {"data": [], "meta": {"result_count": 0}},
            {},
        ),
    )

    assert report["post_count"] == 0
    assert intake.request_budget(
        path=tmp_path / "budget.json", now=now, daily_cap=1, monthly_cap=20
    )["daily_used"] == 1


def test_missing_token_fails_without_network() -> None:
    with pytest.raises(intake.XResearchError, match="not configured"):
        intake.fetch_recent_posts("")

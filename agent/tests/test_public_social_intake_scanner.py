from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts import public_social_intake_scanner as scanner


def test_extract_cashtags_ignores_common_crypto_suffixes() -> None:
    text = "$FRMM squeeze setup, $TSLA puts, $QQQ calls, but $BTC.X is crypto context."

    assert scanner.extract_cashtags(text) == ["FRMM", "TSLA", "QQQ"]


def test_append_new_observations_dedupes_existing_urls(tmp_path: Path) -> None:
    observations_path = tmp_path / "social-arb-observations.json"
    existing = {
        "source": "reddit_public_rss",
        "platform": "reddit",
        "keyword": "$FRMM",
        "url": "https://reddit.example/frmm",
    }
    observations_path.write_text(json.dumps([existing]), encoding="utf-8")

    added = scanner.append_new_observations(
        [
            dict(existing),
            {
                "source": "reddit_public_rss",
                "platform": "reddit",
                "keyword": "$TSLA",
                "url": "https://reddit.example/tsla",
            },
        ],
        observations_path=observations_path,
    )

    saved = json.loads(observations_path.read_text(encoding="utf-8"))
    assert added == 1
    assert len(saved) == 2
    assert {row["keyword"] for row in saved} == {"$FRMM", "$TSLA"}


def test_build_report_appends_public_reddit_observations_context_only(tmp_path: Path) -> None:
    observations_path = tmp_path / "social-arb-observations.json"
    log_path = tmp_path / "public_social_intake_log.jsonl"
    report_path = tmp_path / "public-social-intake.json"

    def fake_fetcher(subreddit: str, limit: int = 25) -> list[dict]:
        assert limit == 25
        return [
            {
                "subreddit": subreddit,
                "title": "$FRMM squeeze metrics look interesting",
                "summary": "Watching $FRMM and $TSLA, no entry yet.",
                "url": f"https://reddit.example/{subreddit}/1",
                "updated": "2026-07-02T13:18:00Z",
            }
        ]

    built = scanner.build_report(
        subreddits=["Shortsqueeze"],
        fetcher=fake_fetcher,
        observations_path=observations_path,
        log_path=log_path,
        report_path=report_path,
    )

    saved = json.loads(observations_path.read_text(encoding="utf-8"))
    assert built["execution_enabled"] is False
    assert built["mode"] == "context_only"
    assert built["new_observation_count"] == 2
    assert built["by_symbol"] == {"FRMM": 1, "TSLA": 1}
    assert {row["keyword"] for row in saved} == {"$FRMM", "$TSLA"}
    assert all(row["source"] == "reddit_public_rss" for row in saved)
    assert all(row["execution_enabled"] is False for row in saved)
    assert log_path.exists()
    assert report_path.exists()


def test_build_report_throttles_between_multiple_subreddits(tmp_path: Path) -> None:
    calls: list[str] = []
    sleeps: list[float] = []

    def fake_fetcher(subreddit: str, limit: int = 25) -> list[dict]:
        calls.append(subreddit)
        return []

    scanner.build_report(
        subreddits=["Shortsqueeze", "options", "stocks"],
        fetcher=fake_fetcher,
        observations_path=tmp_path / "social-arb-observations.json",
        log_path=tmp_path / "public_social_intake_log.jsonl",
        report_path=tmp_path / "public-social-intake.json",
        sleep_fn=sleeps.append,
        request_delay_seconds=2.0,
    )

    assert calls == ["Shortsqueeze", "options", "stocks"]
    assert sleeps == [2.0, 2.0]

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from strategies.social_arbitrage_watchlist import build_report, score_social_arbitrage


def test_social_arbitrage_scores_cross_platform_trend() -> None:
    observations = [
        {
            "source": "tiktok",
            "caption": "Stanley cup restock is everywhere again",
            "views": 750000,
            "likes": 62000,
            "comments": 1100,
            "growth_pct": 140,
        },
        {
            "source": "youtube",
            "title": "Stanley cup dupes and real demand",
            "views": 120000,
            "likes": 8000,
            "comments": 300,
            "growth_pct": 40,
        },
    ]
    mapping = {"stanley cup": {"ticker": "SWK", "theme": "consumer trend"}}

    ideas = score_social_arbitrage(observations, keyword_map=mapping)

    assert ideas[0]["ticker"] == "SWK"
    assert ideas[0]["source_count"] == 2
    assert ideas[0]["action"] == "paper_watch"
    assert "social attention is not a trade signal" in ideas[0]["warnings"][0] or ideas[0]["warnings"][1]


def test_social_arbitrage_report_stays_research_only(tmp_path) -> None:
    observations = tmp_path / "obs.json"
    mapping = tmp_path / "map.json"
    observations.write_text(
        json.dumps([
            {"source": "tiktok", "caption": "Nvidia AI laptops trending", "views": 500000},
        ]),
        encoding="utf-8",
    )
    mapping.write_text(json.dumps({"nvidia ai": "NVDA"}), encoding="utf-8")

    report = build_report(observations_path=observations, mapping_path=mapping)

    assert report["mode"] == "research_only"
    assert report["execution_enabled"] is False
    assert report["observation_count"] == 1
    assert report["ideas"][0]["ticker"] == "NVDA"
    assert report["ideas"][0]["action"] == "research_only"

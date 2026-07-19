from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts import pmxt_market_schema_probe as probe


def test_build_report_marks_missing_dependency() -> None:
    report = probe.build_report(
        {
            "status": "missing_dependency",
            "error": "pmxtjs is not installed",
            "install_command": "cd tools\\pmxt-probe && npm install",
        },
        "Fed",
        ["polymarket", "kalshi"],
    )

    assert report["recommendation"] == "install_pmxt_sandbox"
    assert report["execution_enabled"] is False
    assert report["install_command"]


def test_build_report_scores_schema_samples() -> None:
    raw = {
        "status": "ok",
        "results": [
            {
                "venue": "polymarket",
                "status": "ok",
                "market_count": 1,
                "markets": [
                    {
                        "id": "1",
                        "title": "Fed decision",
                        "slug": "fed",
                        "volume": 1000,
                        "best_bid": 0.45,
                        "best_ask": 0.47,
                        "raw_keys": ["id", "title"],
                    }
                ],
            },
            {"venue": "kalshi", "status": "error", "error": "timeout", "markets": []},
        ],
    }

    report = probe.build_report(raw, "Fed", ["polymarket", "kalshi"])

    assert report["ok_venue_count"] == 1
    assert report["recommendation"] == "partial_candidate_review_manually"
    assert report["venues_report"][0]["schema_score"] > 0


def test_append_and_write_report(tmp_path: Path) -> None:
    report = {"date": "2026-06-30", "provider": "pmxt_market_schema_probe"}
    log_path = tmp_path / "probe.jsonl"
    report_path = tmp_path / "probe.json"

    probe.append_log(report, log_path)
    probe.write_report(report, report_path)

    assert json.loads(log_path.read_text(encoding="utf-8"))["provider"] == "pmxt_market_schema_probe"
    assert json.loads(report_path.read_text(encoding="utf-8"))["date"] == "2026-06-30"

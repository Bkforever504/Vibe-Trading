from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts import social_trending_persistence_report as persistence


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    path.write_text(
        "\n".join(json.dumps(row, separators=(",", ":")) for row in rows) + "\n",
        encoding="utf-8",
    )


def test_persistence_report_promotes_repeated_intraday_symbols(tmp_path, monkeypatch) -> None:
    log_path = tmp_path / "social.jsonl"
    _write_jsonl(
        log_path,
        [
            {
                "date": "2026-06-30",
                "intraday_scan_index": 0,
                "symbols": [
                    {"symbol": "NVDA", "rank": 1, "trending_score": 10, "bucket": "ai_semis_software", "action": "watch_context"},
                    {"symbol": "AMC", "rank": 2, "trending_score": 7, "bucket": "meme_high_noise", "action": "context_only"},
                ],
            },
            {
                "date": "2026-06-30",
                "intraday_scan_index": 1,
                "symbols": [
                    {"symbol": "NVDA", "rank": 3, "trending_score": 8, "bucket": "ai_semis_software", "action": "watch_context"},
                    {"symbol": "TSLA", "rank": 1, "trending_score": 9, "bucket": "ev_batteries", "action": "watch_context"},
                ],
            },
        ],
    )
    monkeypatch.setattr(persistence, "_cutoff_date", lambda days: "2026-06-01")

    report = persistence.build_persistence_report(log_path, days=30, min_slots=2)

    assert report["mode"] == "context_only"
    assert report["execution_enabled"] is False
    assert report["scan_rows"] == 2
    assert report["persistent_count"] == 1
    assert report["persistent_symbols"][0]["symbol"] == "NVDA"
    assert report["persistent_symbols"][0]["slots"] == [0, 1]
    assert report["persistent_symbols"][0]["best_rank"] == 1

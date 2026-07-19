from __future__ import annotations

import csv
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts import export_daily_bot_activity_csv as export


def test_export_csv_writes_spreadsheet_headers_and_rows(tmp_path: Path) -> None:
    events = [
        {
            "date": "2026-06-30",
            "timestamp": "2026-06-30T14:30:00Z",
            "source": "flip_bot",
            "event_type": "trade",
            "strategy": "bull_trend",
            "symbol": "SPY",
            "side": "CALL",
            "action": "PROFIT TARGET",
            "mode": "alpaca",
            "status": "closed",
            "confidence": "9",
            "pnl": "535",
            "reason": "trend",
            "notional": "100",
            "summary": "5x SPY call",
            "raw": "{}",
        }
    ]
    output = tmp_path / "daily.csv"

    export.export_csv(events, output)

    with output.open(newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    assert rows[0]["source"] == "flip_bot"
    assert rows[0]["pnl"] == "535"
    assert rows[0]["event_type"] == "trade"


def test_collect_events_combines_collectors_in_timestamp_order(monkeypatch) -> None:
    monkeypatch.setattr(export, "_flip_events", lambda day: [{"date": day, "timestamp": "2026-06-30T15:00:00Z", "source": "b", "event_type": "trade"}])
    monkeypatch.setattr(export, "_iwm_events", lambda day: [])
    monkeypatch.setattr(export, "_guard_events", lambda day: [{"date": day, "timestamp": "2026-06-30T14:00:00Z", "source": "a", "event_type": "guard_block"}])
    monkeypatch.setattr(export, "_shadow_events", lambda day: [])
    monkeypatch.setattr(export, "_context_events", lambda day: [])

    rows = export.collect_events("2026-06-30")

    assert [row["source"] for row in rows] == ["a", "b"]


def test_base_event_is_context_safe() -> None:
    row = {"timestamp": "2026-06-30T01:00:00Z", "mode": "context_only"}
    event = export._base_event("2026-06-30", "social", "social_context", row)

    assert event["mode"] == "context_only"
    assert event["source"] == "social"
    assert event["event_type"] == "social_context"

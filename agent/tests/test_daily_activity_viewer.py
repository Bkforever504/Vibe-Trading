from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts import launch_daily_activity_viewer as viewer


def test_load_activity_reads_csv(tmp_path: Path) -> None:
    path = tmp_path / "activity.csv"
    path.write_text("date,source,event_type\n2026-06-30,test,context\n", encoding="utf-8")

    df = viewer.load_activity(path)

    assert list(df.columns) == ["date", "source", "event_type"]
    assert df.iloc[0]["source"] == "test"


def test_default_csv_path_uses_report_dir() -> None:
    path = viewer.default_csv_path("2026-06-30")

    assert path.name == "daily-bot-activity-2026-06-30.csv"

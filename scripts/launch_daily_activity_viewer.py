#!/usr/bin/env python3
"""Open the daily bot activity CSV in D-Tale for local visual review."""
from __future__ import annotations

import argparse
from datetime import date
from pathlib import Path

import pandas as pd

VIBE_HOME = Path.home() / ".vibe-trading"
REPORT_DIR = VIBE_HOME / "reports"


def default_csv_path(day: str) -> Path:
    return REPORT_DIR / f"daily-bot-activity-{day}.csv"


def load_activity(path: Path) -> pd.DataFrame:
    if not path.exists():
        raise FileNotFoundError(f"Daily activity CSV not found: {path}")
    return pd.read_csv(path)


def launch_viewer(path: Path, *, port: int = 40000, no_open: bool = False) -> str:
    df = load_activity(path)
    try:
        import dtale
    except ImportError as exc:
        raise ImportError(
            "D-Tale is not installed. Run with: uv run --no-project --with dtale --with pandas "
            "python scripts\\launch_daily_activity_viewer.py"
        ) from exc
    instance = dtale.show(df, port=port, open_browser=not no_open)
    return str(instance._main_url)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--date", default=date.today().isoformat())
    parser.add_argument("--csv", type=Path, default=None)
    parser.add_argument("--port", type=int, default=40000)
    parser.add_argument("--no-open", action="store_true")
    args = parser.parse_args()
    path = args.csv or default_csv_path(args.date)
    url = launch_viewer(path, port=args.port, no_open=args.no_open)
    print(f"D-Tale daily activity viewer: {url}")
    print(f"CSV: {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

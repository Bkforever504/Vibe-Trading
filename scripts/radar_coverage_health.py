"""Daily radar coverage health check.

Counts today's rows in intraday_opportunity_radar_log.jsonl and marks
the health status FAIL when the count is below the session minimum.

Emits a JSON status file that the dashboard health section reads.
Exits 0 always (fail-open) so downstream scheduled tasks are not blocked;
the failure is expressed via the health JSON, not the exit code.
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

try:
    from scripts.signal_stack_health_report import is_expected_market_session
except ModuleNotFoundError:
    from signal_stack_health_report import is_expected_market_session

ROOT = Path(__file__).resolve().parent.parent
RADAR_LOG = ROOT / "data" / "intraday_opportunity_radar_log.jsonl"
HEALTH_DIR = Path.home() / ".vibe-trading" / "health"
HEALTH_PATH = HEALTH_DIR / "radar_coverage.json"

ET = ZoneInfo("America/New_York")

# The full-RTH task fires 78 times.  A low threshold previously allowed severe
# data loss to look healthy; require roughly 90% coverage instead.
EXPECTED_ROWS = 78
DEFAULT_MIN_ROWS = 70


def count_rows_for_date(path: Path, date_str: str) -> int:
    if not path.exists():
        return 0
    needle = f'"as_of_et":"{date_str}T'
    n = 0
    with path.open("r", encoding="utf-8", errors="replace") as fh:
        for line in fh:
            if needle in line:
                n += 1
    return n


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--min-rows", type=int, default=DEFAULT_MIN_ROWS)
    parser.add_argument("--date", default=None, help="YYYY-MM-DD ET. Default: today ET.")
    args = parser.parse_args()

    now_et = datetime.now(ET)
    date_str = args.date or now_et.strftime("%Y-%m-%d")
    rows = count_rows_for_date(RADAR_LOG, date_str)

    checked_date = datetime.strptime(date_str, "%Y-%m-%d").date()
    session_expected = is_expected_market_session(checked_date)
    is_pre_close = now_et.hour < 16 and session_expected and now_et.strftime("%Y-%m-%d") == date_str

    if not session_expected:
        status = "ok"
        detail = "non-market session; no coverage expected"
    elif rows >= args.min_rows:
        status = "ok"
        detail = f"{rows} rows meets min {args.min_rows}"
    elif is_pre_close:
        status = "warn"
        detail = f"only {rows}/{args.min_rows} rows so far; session in progress"
    else:
        status = "fail"
        detail = f"only {rows} rows; expected >={args.min_rows} for RTH session"

    payload = {
        "as_of": datetime.now(timezone.utc).isoformat(),
        "date_checked": date_str,
        "row_count": rows,
        "min_rows": args.min_rows,
        "expected_rows": EXPECTED_ROWS,
        "expected_market_session": session_expected,
        "status": status,
        "detail": detail,
        "provider": "radar_coverage_health",
    }
    HEALTH_DIR.mkdir(parents=True, exist_ok=True)
    HEALTH_PATH.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(json.dumps(payload, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

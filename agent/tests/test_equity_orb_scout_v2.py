from __future__ import annotations

import json
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd
import pytest

from scripts import equity_orb_scout_v2_shadow as scout
from scripts.preregistration_validator import validate_spec


ET = ZoneInfo("America/New_York")
SESSION = date(2026, 8, 24)
ROOT = Path(__file__).resolve().parents[2]


def _frame(rows: list[tuple[datetime, float, float, float, float, float]]) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "Open": [row[1] for row in rows],
            "High": [row[2] for row in rows],
            "Low": [row[3] for row in rows],
            "Close": [row[4] for row in rows],
            "Volume": [row[5] for row in rows],
        },
        index=pd.DatetimeIndex([row[0] for row in rows]),
    )


def _daily_bundle() -> pd.DataFrame:
    stamps = pd.date_range("2026-07-20", periods=25, freq="B", tz=ET)
    aapl = pd.DataFrame(
        {
            "Open": range(100, 125),
            "High": range(101, 126),
            "Low": range(99, 124),
            "Close": range(100, 125),
            "Volume": [1_000] * 25,
        },
        index=stamps,
    )
    spy = pd.DataFrame(
        {
            "Open": [100] * 25,
            "High": [101] * 25,
            "Low": [99] * 25,
            "Close": [100 + i * 0.1 for i in range(25)],
            "Volume": [1_000] * 25,
        },
        index=stamps,
    )
    return pd.concat({"AAPL": aapl, "SPY": spy}, axis=1)


def _intraday() -> tuple[pd.DataFrame, pd.DataFrame]:
    start = datetime(2026, 8, 24, 9, 30, tzinfo=ET)
    minute = _frame(
        [(start + timedelta(minutes=i), 99.5, 100.0, 99.0, 99.7, 100.0) for i in range(20)]
    )
    five = _frame(
        [(datetime(2026, 8, day, 9, 45, tzinfo=ET), 99.5, 100.0, 99.0, 99.7, 100.0) for day in (17, 18, 19, 20, 21)]
        + [(datetime(2026, 8, 24, 9, 45, tzinfo=ET), 100.2, 101.4, 100.1, 101.2, 200.0)]
    )
    return minute, five


def test_frozen_identity_universe_and_shadow_authority() -> None:
    validation = validate_spec(ROOT / scout.SPEC_PATH)
    universe = scout.load_universe()
    assert validation["valid"] is True
    assert validation["metadata"]["Spec Hash"] == scout.SPEC_HASH
    assert universe["symbol_count"] == len(universe["symbols"]) == 121
    base = scout._base_record("entry", datetime(2026, 8, 24, 10, 33, tzinfo=ET), universe)
    assert base["promotion_eligible"] is False
    assert base["execution_enabled"] is False
    assert base["can_submit_orders"] is False


def test_a_plus_orb_plan_requires_and_records_all_filters(monkeypatch) -> None:
    minute, five = _intraday()
    monkeypatch.setattr(scout, "_EARNINGS_CACHE", {("AAPL", SESSION.isoformat()): (False, "clear")})
    monkeypatch.setattr(
        scout,
        "_SECTOR_CACHE",
        {"tech": {"rank": 1, "total": 11, "return_5d": 0.02, "source": "XLK"}},
    )
    decision = scout.build_symbol_plan(
        "AAPL", minute, five, _daily_bundle(), SESSION, macro_blocked=False, macro_events=[]
    )
    assert decision["should_enter"] is True
    plan = decision["plan"]
    assert plan["path"] == "orb"
    assert plan["grade"] >= scout.DASHBOARD_GRADE_FLOOR
    assert set(plan["grade_components"]) == {
        "rvol", "displacement", "vwap", "rs", "ema", "sector", "time"
    }


def test_sector_confirmation_fails_closed_without_rank_data(monkeypatch) -> None:
    minute, five = _intraday()
    monkeypatch.setattr(scout, "_EARNINGS_CACHE", {("AAPL", SESSION.isoformat()): (False, "clear")})
    monkeypatch.setattr(scout, "_SECTOR_CACHE", {})
    decision = scout.build_symbol_plan(
        "AAPL", minute, five, _daily_bundle(), SESSION, macro_blocked=False, macro_events=[]
    )
    assert decision["should_enter"] is False
    assert "sector_rank_gate" in decision["reason"]


def test_universe_loader_rejects_tampering(tmp_path: Path) -> None:
    payload = scout.load_universe().copy()
    payload["symbols"] = [*payload["symbols"], "FAKE"]
    payload["symbol_count"] += 1
    path = tmp_path / "universe.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ValueError, match="hash_mismatch"):
        scout.load_universe(path)


def test_v2_scheduler_is_offset_and_alert_wrapped() -> None:
    registration = (ROOT / "scripts" / "register_equity_orb_scout_v2_task.ps1").read_text(encoding="utf-8")
    assert '-At "09:33"' in registration and '-At "15:06"' in registration
    runner = (ROOT / "scripts" / "run_equity_orb_scout_v2_shadow.ps1").read_text(encoding="utf-8")
    assert "shadow_alert_runner.py --scanner equity-orb-scout-v2 --mode $Mode" in runner
    assert "submit_order" not in runner

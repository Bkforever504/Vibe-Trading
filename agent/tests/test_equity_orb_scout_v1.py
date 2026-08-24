from __future__ import annotations

import json
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd
import pytest

from scripts import equity_orb_scout_v1_shadow as scout
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


def _fixtures() -> tuple[pd.DataFrame, pd.DataFrame]:
    minute_rows: list[tuple[datetime, float, float, float, float, float]] = []
    start = datetime(2026, 8, 24, 9, 30, tzinfo=ET)
    for offset in range(20):
        stamp = start + timedelta(minutes=offset)
        minute_rows.append((stamp, 99.5, 100.0, 99.0, 99.7, 100.0))

    five_rows = [
        (datetime(2026, 8, day, 9, 45, tzinfo=ET), 99.5, 100.0, 99.0, 99.7, 100.0)
        for day in (17, 18, 19, 20, 21)
    ]
    five_rows.append(
        (datetime(2026, 8, 24, 9, 45, tzinfo=ET), 100.2, 101.4, 100.1, 101.2, 200.0)
    )
    return _frame(minute_rows), _frame(five_rows)


def test_frozen_spec_universe_and_scanner_identity_are_consistent() -> None:
    validation = validate_spec(ROOT / scout.SPEC_PATH)
    universe = scout.load_universe()
    assert validation["valid"] is True
    assert validation["metadata"]["Spec Hash"] == scout.SPEC_HASH
    assert validation["metadata"]["Universe Hash"] == universe["sha256_membership_hash"]
    assert universe["symbol_count"] == len(universe["symbols"]) == 121


def test_universe_loader_fails_closed_on_membership_tampering(tmp_path: Path) -> None:
    payload = scout.load_universe().copy()
    payload["symbols"] = [*payload["symbols"], "FAKE"]
    payload["symbol_count"] += 1
    path = tmp_path / "universe.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ValueError, match="hash_mismatch"):
        scout.load_universe(path)


def test_equity_orb_fixture_builds_and_resolves_without_execution_authority() -> None:
    bars_1m, bars_5m = _fixtures()
    decision = scout.build_symbol_plan("AAPL", bars_1m, bars_5m, SESSION)
    assert decision["should_enter"] is True
    assert decision["plan"]["trigger"]["rvol"] == 2.0
    assert decision["plan"]["trigger"]["vwap_pass"] is True

    plan = decision["plan"]
    forward = _frame(
        [
            (datetime(2026, 8, 24, 9, 46, tzinfo=ET), 101.2, plan["t1_price"] + 0.1, 101.0, 102.0, 100),
            (datetime(2026, 8, 24, 9, 47, tzinfo=ET), 102.0, plan["t2_price"] + 0.1, 101.9, 103.2, 100),
        ]
    )
    pre_trigger = bars_1m[bars_1m.index <= datetime(2026, 8, 24, 9, 45, tzinfo=ET)]
    outcome = scout.resolve_symbol(pd.concat([pre_trigger, forward]), "AAPL", SESSION, plan)
    assert outcome["outcome"] == "win"
    assert outcome["exit_reason"] == "t2_after_t1"

    base = scout._base_record("entry", datetime(2026, 8, 24, 10, 32, tzinfo=ET), scout.load_universe())
    assert base["promotion_eligible"] is False
    assert base["execution_enabled"] is False
    assert base["can_submit_orders"] is False
    assert "entry_fill_executable" not in base


def test_opening_range_and_rvol_require_complete_frozen_inputs() -> None:
    bars_1m, bars_5m = _fixtures()
    incomplete_open = bars_1m.drop(datetime(2026, 8, 24, 9, 31, tzinfo=ET))
    assert scout.build_symbol_plan("AAPL", incomplete_open, bars_5m, SESSION)["reason"] == "opening_range_unavailable"

    four_prior = bars_5m[bars_5m.index.date != date(2026, 8, 17)]
    decision = scout.build_symbol_plan("AAPL", bars_1m, four_prior, SESSION)
    assert decision["should_enter"] is False
    assert "rvol_below_1_5" in decision["reason"]


def test_scheduler_is_central_time_scoped_and_shadow_only() -> None:
    text = (ROOT / "scripts" / "register_equity_orb_scout_v1_task.ps1").read_text(encoding="utf-8")
    assert 'Get-TimeZone).Id -ne "Central Standard Time"' in text
    assert '-TaskPath "\\VibeTrade\\"' in text
    assert '-At "09:32"' in text
    assert '-At "15:05"' in text
    runner = (ROOT / "scripts" / "run_equity_orb_scout_v1_shadow.ps1").read_text(encoding="utf-8")
    assert "shadow_alert_runner.py --scanner equity-orb-scout-v1 --mode $Mode" in runner
    assert "submit_order" not in runner

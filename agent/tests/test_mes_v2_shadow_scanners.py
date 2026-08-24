from __future__ import annotations

from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd

from scripts import mes_orb_0932_vix_v2_shadow as orb
from scripts import mes_reopen_drift_v2_shadow as reopen


ET = ZoneInfo("America/New_York")
CT = ZoneInfo("America/Chicago")
SESSION = date(2026, 8, 17)  # Monday


def _frame(rows: list[tuple[str, float, float, float, float, float]], tz: ZoneInfo) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "Open": [row[1] for row in rows],
            "High": [row[2] for row in rows],
            "Low": [row[3] for row in rows],
            "Close": [row[4] for row in rows],
            "Volume": [row[5] for row in rows],
        },
        index=pd.DatetimeIndex([row[0] for row in rows], tz=tz),
    )


def test_orb_entry_is_causal_and_resolution_ignores_pre_actionable_bars() -> None:
    bars_2m = _frame(
        [
            ("2026-08-17 09:30", 99.5, 100.0, 99.0, 99.8, 100),
            # This adverse bar is before the 09:35 actionable time and must not score.
            ("2026-08-17 09:32", 99.8, 100.0, 98.0, 99.0, 100),
            ("2026-08-17 09:36", 101.2, 102.4, 101.0, 102.0, 100),
            ("2026-08-17 09:38", 102.0, 103.4, 101.8, 103.0, 100),
        ],
        ET,
    )
    prior_rows = [
        (f"2026-08-{day:02d} 09:30", 99.0, 100.0, 98.5, 99.5, 100)
        for day in (10, 11, 12, 13, 14)
    ]
    bars_5m = _frame(
        [*prior_rows, ("2026-08-17 09:30", 99.8, 101.4, 99.7, 101.2, 200)],
        ET,
    )
    vix = pd.DataFrame({"Close": [20.0]}, index=pd.DatetimeIndex(["2026-08-14"]))

    decision = orb.build_entry_plan(
        bars_2m,
        bars_5m,
        vix,
        SESSION,
        hmm_state="trend",
        macro_blocked=False,
        macro_names=[],
    )

    assert decision["should_enter"] is True
    assert decision["filters"]["trigger"]["rvol"] == 2.0
    assert decision["plan"]["trigger"]["actionable_at"].endswith("09:35:00-04:00")
    outcome = orb.resolve_plan(bars_2m, SESSION, decision["plan"])
    assert outcome["outcome"] == "win"
    assert outcome["exit_reason"] == "t2_after_t1"


def test_orb_requires_five_rvol_sessions_and_proxy_is_not_promotable() -> None:
    bars = _frame(
        [
            (f"2026-08-{day:02d} 09:30", 99.0, 100.0, 98.5, 99.5, 100)
            for day in (11, 12, 13, 14)
        ],
        ET,
    )
    assert orb.rvol_baseline(bars, SESSION, datetime(2026, 8, 17, 9, 30).time()) is None
    base = orb._base_record("entry", datetime(2026, 8, 17, 9, 47, tzinfo=ET))
    assert base["promotion_eligible"] is False
    assert base["can_submit_orders"] is False


def _reopen_frames() -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    thirty_rows: list[tuple[str, float, float, float, float, float]] = []
    for day in (10, 11, 12, 13, 14):
        thirty_rows.append((f"2026-08-{day:02d} 17:00", 100, 101, 99, 100, 100))
    start = datetime(2026, 8, 17, 9, 30, tzinfo=CT)
    for index in range(15):
        stamp = start + timedelta(minutes=30 * index)
        price = 100 + index * 0.2
        thirty_rows.append((stamp.strftime("%Y-%m-%d %H:%M"), price, price + 1, price - 1, price + 0.2, 100))
    thirty_rows.append(("2026-08-17 17:00", 103, 104, 102, 103.5, 80))
    bars_30m = _frame(thirty_rows, CT)
    bars_5m = _frame(
        [
            ("2026-08-17 09:30", 100, 101, 99, 100, 100),
            ("2026-08-17 15:55", 109, 111, 108, 110.5, 100),
        ],
        ET,
    )
    bars_1h = _frame(
        [
            ((datetime(2026, 8, 1, tzinfo=ET) + timedelta(hours=index)).strftime("%Y-%m-%d %H:%M"), 100 + index, 101 + index, 99 + index, 100.5 + index, 100)
            for index in range(400)
        ],
        ET,
    )
    vix = pd.DataFrame({"Close": [20.0]}, index=pd.DatetimeIndex(["2026-08-17"]))
    return bars_30m, bars_1h, bars_5m, vix


def test_reopen_applies_filters_and_adverse_first(monkeypatch) -> None:
    bars_30m, bars_1h, bars_5m, vix = _reopen_frames()
    monkeypatch.setattr(reopen, "eth_hurst", lambda *_args: 0.60)
    monkeypatch.setattr(reopen, "_macro_block_next_day", lambda *_args: (False, []))

    decision = reopen.build_entry_plan(
        bars_30m=bars_30m,
        bars_1h=bars_1h,
        bars_5m=bars_5m,
        vix_daily=vix,
        session_date=SESSION,
    )

    assert decision["should_enter"] is True
    assert decision["plan"]["direction"] == "long"
    assert decision["filters"]["eth_volume"]["pass"] is True
    actionable = datetime.fromisoformat(decision["plan"]["actionable_at"])
    stop = decision["plan"]["stop_price"]
    t1 = decision["plan"]["t1_price"]
    collision = _frame(
        [
            ((actionable + timedelta(minutes=30)).strftime("%Y-%m-%d %H:%M"), 103.5, t1 + 1, stop - 1, 103.5, 100),
        ],
        CT,
    )
    outcome = reopen.resolve_plan(collision, decision["plan"])
    assert outcome["exit_reason"] == "stop_before_t1"
    assert outcome["outcome"] == "loss"


def test_scheduler_uses_central_time_and_valid_reopen_days() -> None:
    text = (Path(__file__).resolve().parents[2] / "scripts" / "register_mes_v2_shadow_tasks.ps1").read_text(encoding="utf-8")
    assert 'Get-TimeZone).Id -ne "Central Standard Time"' in text
    assert '-At "08:47"' in text
    assert '-At "11:05"' in text
    assert '-DaysOfWeek Monday,Tuesday,Wednesday,Thursday -At "17:35"' in text
    assert '-DaysOfWeek Tuesday,Wednesday,Thursday,Friday -At "07:35"' in text
    assert 'New-ScheduledTaskTrigger -Daily -At "12:30"' in text
    assert 'MesV2DatabentoRegrade' in text
    assert '-TaskPath "\\VibeTrade\\"' in text

from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

ET = ZoneInfo("America/New_York")


def _mes_frame() -> pd.DataFrame:
    index = pd.DatetimeIndex(
        [
            "2026-08-16 15:55:00-04:00",
            "2026-08-17 15:55:00-04:00",
            "2026-08-17 18:00:00-04:00",
            "2026-08-18 09:30:00-04:00",
        ]
    )
    return pd.DataFrame(
        {
            "Open": [6000.0, 6030.0, 6040.0, 6050.0],
            "Close": [6000.0, 6030.0, 6042.0, 6051.0],
        },
        index=index,
    )


def _vix_frame(day: str = "2026-08-17") -> pd.DataFrame:
    return pd.DataFrame({"Close": [17.0]}, index=pd.DatetimeIndex([day]))


def test_entry_context_uses_final_close_and_reopen_open() -> None:
    import pytest

    from strategies.mes_reopen_vix_shadow_logger import build_entry_context

    row = build_entry_context(_mes_frame(), _vix_frame(), datetime(2026, 8, 17).date())

    assert row["entry_price"] == 6040.0
    assert row["prior_move"] == pytest.approx(0.005)
    assert row["vix_pass"] is True
    assert row["prior_move_pass"] is True


def test_entry_context_rejects_stale_vix_close() -> None:
    import pytest

    from strategies.mes_reopen_vix_shadow_logger import build_entry_context

    with pytest.raises(ValueError, match="same-day final VIX close"):
        build_entry_context(_mes_frame(), _vix_frame("2026-08-14"), datetime(2026, 8, 17).date())


def test_entry_is_idempotent_and_shadow_only(tmp_path: Path) -> None:
    from strategies.mes_reopen_vix_shadow_logger import run_entry

    path = tmp_path / "shadow.jsonl"
    now = datetime(2026, 8, 17, 18, 6, tzinfo=ET)
    assert run_entry(as_of=now, mes=_mes_frame(), vix=_vix_frame(), log_path=path) == 0
    assert run_entry(as_of=now, mes=_mes_frame(), vix=_vix_frame(), log_path=path) == 0

    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    assert len(rows) == 1
    assert rows[0]["should_enter"] is True
    assert rows[0]["execution_enabled"] is False
    assert rows[0]["can_submit_orders"] is False


def test_exit_resolves_once_with_friction(tmp_path: Path) -> None:
    from strategies.mes_reopen_vix_shadow_logger import run_entry, run_exit

    path = tmp_path / "shadow.jsonl"
    entry_time = datetime(2026, 8, 17, 18, 6, tzinfo=ET)
    exit_time = datetime(2026, 8, 18, 9, 36, tzinfo=ET)
    run_entry(as_of=entry_time, mes=_mes_frame(), vix=_vix_frame(), log_path=path)
    run_exit(as_of=exit_time, mes=_mes_frame(), log_path=path)

    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    assert rows[0]["settled"] is True
    assert rows[1]["exit_price"] == 6050.0
    assert rows[1]["net_dollar"] == 46.02
    assert rows[1]["outcome"] == "win"

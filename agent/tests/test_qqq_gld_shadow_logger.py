from __future__ import annotations

import json
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.qqq_gld_shadow_logger import compute_signal_from_close, log_entry


def _close(qqq: list[float], gld: list[float]) -> pd.DataFrame:
    idx = pd.date_range("2026-01-01", periods=len(qqq), freq="D")
    return pd.DataFrame({"QQQ": qqq, "GLD": gld}, index=idx)


def test_compute_signal_selects_qqq_when_relative_momentum_is_stronger() -> None:
    close = _close(
        qqq=[100, 101, 102, 103, 106, 109],
        gld=[100, 100, 100, 101, 101, 101],
    )

    entry = compute_signal_from_close(close, lookback_days=3, as_of="2026-01-06")

    assert entry["selected"] == "QQQ"
    assert entry["action"] == "hold_qqq"
    assert entry["confidence"] == 9.0
    assert entry["paper_rules"]["leveraged_tqqq_allowed"] is False


def test_compute_signal_rotates_to_gld_when_defensive_momentum_leads() -> None:
    close = _close(
        qqq=[100, 100, 106, 108, 110, 100],
        gld=[100, 100, 101, 102, 106, 110],
    )

    entry = compute_signal_from_close(close, lookback_days=3, as_of="2026-01-06")

    assert entry["selected"] == "GLD"
    assert entry["action"] == "rotate_to_gld"


def test_log_entry_replaces_same_date(tmp_path: Path) -> None:
    log = tmp_path / "qqq_gld_shadow_log.jsonl"
    first = {"date": "2026-01-05", "selected": "QQQ"}
    second = {"date": "2026-01-05", "selected": "GLD"}

    log_entry(first, log)
    log_entry(second, log)

    rows = [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines()]
    assert rows == [second]

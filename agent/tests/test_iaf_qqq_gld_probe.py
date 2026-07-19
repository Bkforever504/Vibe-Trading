from __future__ import annotations

import json
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.iaf_qqq_gld_probe import (
    build_probe_report,
    compute_rotation_backtest,
    compare_to_shadow_entry,
    replay_shadow_entries,
)


def _close(qqq: list[float], gld: list[float]) -> pd.DataFrame:
    idx = pd.date_range("2026-01-01", periods=len(qqq), freq="D")
    return pd.DataFrame({"QQQ": qqq, "GLD": gld}, index=idx)


def test_compute_rotation_backtest_tracks_selection_and_trade_count() -> None:
    close = _close(
        qqq=[100, 101, 102, 103, 104, 105, 90, 90],
        gld=[100, 100, 100, 100, 100, 101, 106, 108],
    )

    result = compute_rotation_backtest(close, lookback_days=3)

    assert result["latest"]["selected"] == "GLD"
    assert result["latest"]["action"] == "hold_gld"
    assert result["summary"]["trade_count"] >= 1
    assert result["summary"]["max_drawdown_pct"] >= 0
    assert result["summary"]["execution_enabled"] is False


def test_compare_to_shadow_entry_flags_match() -> None:
    close = _close(
        qqq=[100, 101, 102, 103, 106, 109],
        gld=[100, 100, 100, 101, 101, 101],
    )
    shadow = {
        "date": "2026-01-06",
        "strategy": "qqq_gld_40d_rotation",
        "selected": "QQQ",
        "action": "hold_qqq",
    }

    comparison = compare_to_shadow_entry(close, shadow, lookback_days=3)

    assert comparison["status"] == "match"
    assert comparison["shadow_selected"] == "QQQ"
    assert comparison["probe_selected"] == "QQQ"


def test_compare_to_shadow_entry_flags_mismatch() -> None:
    close = _close(
        qqq=[100, 101, 102, 103, 106, 109],
        gld=[100, 100, 100, 101, 101, 101],
    )
    shadow = {
        "date": "2026-01-06",
        "strategy": "qqq_gld_40d_rotation",
        "selected": "GLD",
        "action": "hold_gld",
    }

    comparison = compare_to_shadow_entry(close, shadow, lookback_days=3)

    assert comparison["status"] == "mismatch"
    assert comparison["probe_selected"] == "QQQ"


def test_build_probe_report_is_read_only_and_json_serializable() -> None:
    close = _close(
        qqq=[100, 101, 102, 103, 106, 109],
        gld=[100, 100, 100, 101, 101, 101],
    )

    report = build_probe_report(close, shadow_entry=None, lookback_days=3)

    assert report["source_repo"] == "coding-kitties/investing-algorithm-framework"
    assert report["integration_mode"] == "sandbox_probe"
    assert report["execution_enabled"] is False
    assert report["live_trading_allowed"] is False
    assert report["shadow_replay"]["checked"] == 0
    json.dumps(report)


def test_replay_shadow_entries_requires_ten_clean_matches() -> None:
    close = _close(
        qqq=[100, 101, 102, 103, 106, 109, 112, 115, 118, 121, 124, 127, 130, 133, 136],
        gld=[100, 100, 100, 101, 101, 101, 101, 101, 101, 101, 101, 101, 101, 101, 101],
    )
    entries = [
        {
            "date": str(day.date()),
            "selected": "QQQ",
            "action": "hold_qqq",
        }
        for day in close.index[-10:]
    ]

    replay = replay_shadow_entries(close, entries, lookback_days=3, limit=10)

    assert replay["status"] == "pass"
    assert replay["checked"] == 10
    assert replay["matches"] == 10
    assert replay["expansion_allowed"] is True


def test_replay_shadow_entries_blocks_on_mismatch() -> None:
    close = _close(
        qqq=[100, 101, 102, 103, 106, 109],
        gld=[100, 100, 100, 101, 101, 101],
    )
    entries = [
        {"date": "2026-01-06", "selected": "GLD", "action": "hold_gld"},
    ]

    replay = replay_shadow_entries(close, entries, lookback_days=3, limit=10)

    assert replay["status"] == "fail"
    assert replay["mismatches"] == 1
    assert replay["expansion_allowed"] is False

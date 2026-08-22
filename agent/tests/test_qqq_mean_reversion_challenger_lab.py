from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from research.qqq_mean_reversion_challenger_lab import (
    BONFERRONI_ALPHA,
    EFFECTIVE_ATTEMPTS,
    VARIANTS,
    _gap_allowed,
    prepare_frame,
    simulate,
)
from scripts import qqq_mean_reversion_shadow as shadow
from scripts.qqq_mean_reversion_shadow_report import summarize


def _frame() -> pd.DataFrame:
    index = pd.date_range("2024-01-02", periods=280, freq="B")
    close = pd.Series([100.0 + index * 0.2 for index in range(len(index))], index=index)
    close.iloc[249] = 145.0
    close.iloc[250:258] = [146, 147, 148, 149, 150, 151, 152, 153]
    open_price = close.copy()
    open_price.iloc[250] = 144.0
    open_price.iloc[257] = 153.0
    return pd.DataFrame(
        {
            "open": open_price,
            "high": pd.concat([open_price, close], axis=1).max(axis=1) + 0.5,
            "low": pd.concat([open_price, close], axis=1).min(axis=1) - 0.5,
            "close": close,
            "volume": 1_000_000,
        },
        index=index,
    )


def test_frozen_trial_count_and_attempt_accounting() -> None:
    assert len(VARIANTS) == 12
    assert EFFECTIVE_ATTEMPTS == 921
    assert BONFERRONI_ALPHA == 0.05 / 921


def test_double7_decision_fills_at_next_open() -> None:
    frame = prepare_frame(_frame())
    variant = next(row for row in VARIANTS if row.name == "double7_baseline")
    trades = simulate(frame, variant)
    matching = [row for row in trades if row["entry_date"] == frame.index[250].date().isoformat()]

    assert matching
    assert matching[0]["entry"] == 144.0
    exit_pos = next(
        pos for pos, timestamp in enumerate(frame.index)
        if timestamp.date().isoformat() == matching[0]["exit_date"]
    )
    assert exit_pos > 250
    assert frame["close"].iloc[exit_pos - 1] >= frame["high7"].iloc[exit_pos - 1]
    assert matching[0]["exit"] == float(frame["open"].iloc[exit_pos])


def test_gap_guard_uses_signal_close_and_next_open() -> None:
    frame = prepare_frame(_frame())
    variant = next(row for row in VARIANTS if row.name == "double7_gap_guard_1atr")
    signal_pos, entry_pos = 249, 250
    frame.iloc[entry_pos, frame.columns.get_loc("open")] = (
        frame["close"].iloc[signal_pos] - 1.01 * frame["atr20"].iloc[signal_pos]
    )

    assert _gap_allowed(frame, signal_pos, entry_pos, variant) is False


def test_shadow_snapshot_is_read_only_and_tracks_both_families(monkeypatch) -> None:
    monkeypatch.setattr(shadow, "fetch_vix_context", lambda: {"available": False})
    records = shadow.compute_records(_frame())
    snapshot = records[0]

    assert snapshot["record_type"] == "signal"
    assert snapshot["execution_enabled"] is False
    assert snapshot["can_submit_orders"] is False
    assert set(snapshot["setups"]) == set(shadow.TRACKED)
    assert all(row["can_submit_orders"] is False for row in snapshot["setups"].values())
    assert "confidence" not in json.dumps(snapshot)


def test_shadow_log_replaces_same_record_key(tmp_path: Path) -> None:
    path = tmp_path / "shadow.jsonl"
    first = {"record_type": "signal", "date": "2026-08-19", "value": 1}
    replacement = {"record_type": "signal", "date": "2026-08-19", "value": 2}

    shadow.write_records([first], path)
    shadow.write_records([replacement], path)

    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    assert rows == [replacement]


def test_generated_report_keeps_holdouts_sealed() -> None:
    path = Path("data/qqq_mean_reversion_challenger_results.json")
    report = json.loads(path.read_text(encoding="utf-8"))

    assert report["execution_enabled"] is False
    assert report["can_submit_orders"] is False
    assert report["sealed_holdouts"]["selection"]["opened"] is False
    assert report["sealed_holdouts"]["final"]["opened"] is False
    assert report["survivors"] == []


def test_shadow_report_never_promotes_sample_automatically() -> None:
    rows = [
        {
            "record_type": "signal",
            "date": f"2026-09-{day:02d}",
            "setups": {"double7_baseline": {"action": "flat"}},
        }
        for day in range(1, 31)
    ]
    rows.extend(
        {
            "record_type": "outcome",
            "status": "resolved",
            "date": "2026-10-01",
            "variant": "double7_baseline",
            "net_pnl_per_10000": 10.0,
        }
        for _ in range(10)
    )

    report = summarize(rows)

    assert report["variant_evidence"]["double7_baseline"]["review_sample_ready"] is True
    assert report["promotion_ready"] is False
    assert report["execution_enabled"] is False

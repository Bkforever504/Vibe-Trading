from __future__ import annotations

from datetime import datetime, timedelta

import pandas as pd

from research.mes_sequence_grammar_tournament import (
    BONFERRONI_ALPHA,
    EFFECTIVE_ATTEMPTS,
    TRIAL_COUNT,
    build_registry,
    find_signal,
    metrics,
    prepare,
)


def _minute_frame(days: int = 1) -> pd.DataFrame:
    rows = []
    for day_offset in range(days):
        start = datetime(2026, 8, 17 + day_offset, 9, 30)
        for idx in range(390):
            price = 100.0
            rows.append({
                "timestamp": (start + timedelta(minutes=idx)).isoformat(),
                "open": price,
                "high": price + 0.25,
                "low": price - 0.25,
                "close": price,
                "volume": 100,
                "instrument_id": "MES-TEST",
            })
    return pd.DataFrame(rows)


def test_registry_counts_every_sequence_and_attempt() -> None:
    registry = build_registry()
    ids = [row["trial_id"] for row in registry["trials"]]
    assert TRIAL_COUNT == 288
    assert len(ids) == len(set(ids)) == 288
    assert EFFECTIVE_ATTEMPTS == 803
    assert BONFERRONI_ALPHA == 0.05 / 803
    assert registry["execution_enabled"] is False
    assert registry["can_submit_orders"] is False


def test_breakout_signal_uses_completed_close_and_structural_stop() -> None:
    dates, sessions = prepare(_minute_frame())
    bars = sessions[dates[0]].copy()
    bars.loc[6, ["open", "high", "low", "close"]] = [100.0, 101.0, 99.75, 100.75]
    trial = {
        "anchor": "opening_15m",
        "event": "breakout",
        "confirmation": "none",
        "entry": "signal_close",
        "reward_risk": 2.0,
    }
    signal = find_signal(bars, trial, None)
    assert signal is not None
    entry_idx, side, stop = signal
    assert entry_idx == 6
    assert side == 1
    assert stop == 99.75


def test_metrics_charge_full_round_trip_and_doubled_stress() -> None:
    baseline = metrics([2.0, -1.0])
    stress = metrics([2.0, -1.0], cost_multiple=2.0)
    assert baseline["total_pnl"] == -4.96
    assert stress["total_pnl"] == -14.92

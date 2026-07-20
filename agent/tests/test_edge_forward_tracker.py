from __future__ import annotations

import importlib.util
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location(
    "edge_forward_tracker", ROOT / "scripts" / "edge_forward_tracker.py"
)
assert SPEC and SPEC.loader
tracker = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(tracker)


def synthetic_closes(rows: int = 270) -> pd.DataFrame:
    index = pd.bdate_range("2025-01-02", periods=rows)
    data = {}
    for rank, symbol in enumerate(tracker.MOMENTUM_SYMBOLS, start=1):
        data[symbol] = [100.0 + rank * i / 10.0 for i in range(rows)]
    return pd.DataFrame(data, index=index)


def test_momentum_snapshot_matches_frozen_signal_and_phase() -> None:
    closes = synthetic_closes()
    signal = tracker._momentum_signal(
        closes,
        tracker.MOMENTUM_LOOKBACK_DAYS,
        tracker.MOMENTUM_REBALANCE_DAYS,
        tracker.MOMENTUM_TOP_N,
    )

    target, rebalance_date = tracker.momentum_snapshot(closes)

    assert target == tracker._normalize_position(signal.iloc[-1])
    assert rebalance_date == str(closes.index[267].date())


def test_momentum_migration_invalidates_old_legs_and_starts_baseline(monkeypatch) -> None:
    closes = synthetic_closes()
    events: list[dict] = []
    state = {
        "momentum": {
            "holdings": {
                "XLE": {"date": "2026-01-01", "price": 50.0},
                "XLK": {"date": "2026-01-01", "price": 100.0},
            },
            "last_rebalance": "2026-01-01",
        }
    }
    monkeypatch.setattr(tracker, "fetch_closes", lambda *_: closes)
    monkeypatch.setattr(tracker, "log_event", events.append)

    tracker.run_momentum(state)

    assert [event["action"] for event in events[:2]] == ["invalidated", "invalidated"]
    position = state["momentum"]["position"]
    assert tuple(position["symbols"]) == tracker.momentum_snapshot(closes)[0]
    assert position["eligible_for_gate"] is False


def test_momentum_rebalance_is_one_resolved_portfolio_trade(monkeypatch) -> None:
    closes = synthetic_closes()
    target, _ = tracker.momentum_snapshot(closes)
    old_symbols = ("SPY", "QQQ")
    events: list[dict] = []
    state = {
        "momentum": {
            "strategy_version": tracker.MOMENTUM_STRATEGY_VERSION,
            "position": {
                "symbols": list(old_symbols),
                "date": "2025-01-02",
                "prices": {symbol: 100.0 for symbol in old_symbols},
                "eligible_for_gate": True,
            },
        }
    }
    assert tuple(old_symbols) != target
    monkeypatch.setattr(tracker, "fetch_closes", lambda *_: closes)
    monkeypatch.setattr(tracker, "log_event", events.append)

    tracker.run_momentum(state)

    exits = [event for event in events if event["action"] == "exit"]
    assert len(exits) == 1
    assert exits[0]["symbols"] == list(old_symbols)
    assert exits[0]["eligible_for_gate"] is True

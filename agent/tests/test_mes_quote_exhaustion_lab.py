from __future__ import annotations

import pandas as pd

from research import mes_quote_exhaustion_lab as lab


def _frame(prices: list[tuple[float, float]], imbalances: list[float]) -> pd.DataFrame:
    start = lab.SIGNAL_START
    return pd.DataFrame({
        "sec": [start + i for i in range(len(prices))],
        "bid": [row[0] for row in prices],
        "ask": [row[1] for row in prices],
        "imb": imbalances,
    })


def test_positive_imbalance_cross_is_faded_short(monkeypatch) -> None:
    monkeypatch.setattr(lab, "WINDOW_OBSERVATIONS", 3)
    monkeypatch.setattr(lab, "HOLD_SECONDS", 3)
    prices = [(100.00, 100.25)] * 4 + [(99.75, 100.00), (99.50, 99.75), (99.25, 99.50)]
    trades = lab.replay_session(_frame(prices, [0.0, 0.0, 0.0, 0.4, 0.4, 0.4, 0.0]))

    assert len(trades) == 1
    assert trades[0]["direction"] == "short"
    assert trades[0]["entry_price"] == 100.0
    assert trades[0]["exit_reason"] == "time_exit"
    assert trades[0]["gross_usd"] == 2.5


def test_negative_imbalance_cross_is_faded_long_and_hard_stop_is_enforced(monkeypatch) -> None:
    monkeypatch.setattr(lab, "WINDOW_OBSERVATIONS", 3)
    monkeypatch.setattr(lab, "HOLD_SECONDS", 10)
    prices = [(100.00, 100.25)] * 4 + [(94.75, 95.00), (94.50, 94.75)]
    trades = lab.replay_session(_frame(prices, [0.0, 0.0, 0.0, -0.4, -0.4, -0.4]))

    assert len(trades) == 1
    assert trades[0]["direction"] == "long"
    assert trades[0]["exit_reason"] == "hard_stop"
    assert trades[0]["gross_usd"] < -25.0


def test_stage_stats_include_initial_loss_drawdown_and_stressed_costs() -> None:
    trades = {
        "d1": [{"gross_usd": -10.0, "exit_reason": "time_exit"}],
        "d2": [{"gross_usd": 20.0, "exit_reason": "time_exit"}],
    }

    base = lab.stage_stats(trades, ["d1", "d2"], stress=False)
    stressed = lab.stage_stats(trades, ["d1", "d2"], stress=True)

    assert base["max_drawdown"] == 12.48
    assert base["cost_per_trade"] == 2.48
    assert stressed["cost_per_trade"] == 7.46
    assert stressed["expectancy"] < base["expectancy"]


def test_selection_failure_keeps_final_outcomes_sealed() -> None:
    sessions = [f"d{i:03d}" for i in range(100)]
    trades = {day: [{"gross_usd": 20.0, "exit_reason": "time_exit"}] for day in sessions}

    result = lab.evaluate(trades, sessions)

    assert result["selection_pass"] is False
    assert "minimum_trades" in result["selection_failed_checks"]
    assert result["final"]["outcomes_opened"] is False
    assert "final_stressed" not in result


def test_passing_selection_opens_final_once_without_retuning() -> None:
    sessions = [f"d{i:03d}" for i in range(300)]
    trades = {}
    for index, day in enumerate(sessions):
        # Three winners then one loser remains profitable after doubled costs.
        gross = 12.0 if index % 4 else -5.0
        trades[day] = [{"gross_usd": gross, "exit_reason": "time_exit"}]

    gated = lab.evaluate(trades, sessions)
    assert gated["selection_pass"] is True
    assert gated["final"]["outcomes_opened"] is False
    assert gated["final"]["reason"] == "selection_passed_but_final_data_not_loaded"

    result = lab.evaluate(trades, sessions, final_trades_by_date=trades)

    assert result["selection_pass"] is True
    assert result["final"]["outcomes_opened"] is True
    assert result["final_pass"] is True
    assert result["development"]["outcomes_opened"] is False

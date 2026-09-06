import pandas as pd

from research import trader_barbie_3m_ce_lab as lab


def _bars(closes: list[float]) -> pd.DataFrame:
    dt = pd.date_range("2026-08-28 10:00", periods=len(closes), freq="3min", tz="America/New_York")
    return pd.DataFrame({
        "dt": dt,
        "date": ["2026-08-28"] * len(closes),
        "open": closes,
        "high": [value + 0.2 for value in closes],
        "low": [value - 0.2 for value in closes],
        "close": closes,
        "volume": [1000] * len(closes),
    })


def test_second_cross_requires_failure_between_crosses() -> None:
    execution = _bars([99.8, 100.2, 100.3, 99.9, 100.4, 100.5])
    event = {"date": "2026-08-28", "context_complete_at": execution.loc[0, "dt"], "ce": 100.0, "side": 1}
    result = lab.signal_indices(execution, event)
    assert result["first_ce_cross"] == 1
    assert result["second_ce_recross"] == 4


def test_no_second_cross_when_first_never_fails() -> None:
    execution = _bars([99.8, 100.2, 100.3, 100.4])
    event = {"date": "2026-08-28", "context_complete_at": execution.loc[0, "dt"], "ce": 100.0, "side": 1}
    assert lab.signal_indices(execution, event) == {"first_ce_cross": 1}


def test_stop_wins_same_bar_and_hold_is_30_minutes() -> None:
    execution = _bars([100.0] * 12)
    execution.loc[1, ["open", "high", "low", "close"]] = [100.0, 102.5, 98.5, 101.0]
    event = {"date": "2026-08-28", "side": 1, "stop": 99.0}
    row = lab.simulate(execution, event, 0, 0.0)
    assert row is not None and row["gross_r"] == -1.0 and row["reason"] == "stop"


def test_cross_market_gate_is_always_blocked() -> None:
    aggregate = {"trades": 100, "expectancy_r": 0.2, "profit_factor": 1.3, "one_sided_p_value": lab.BONFERRONI_ALPHA / 2}
    stress = {"expectancy_r": 0.1}
    folds = [{"expectancy_r": 0.1}, {"expectancy_r": 0.2}, {"expectancy_r": -0.1}]
    gates = lab._gates(aggregate, stress, folds)
    assert gates["cross_market_confirmation"] is False

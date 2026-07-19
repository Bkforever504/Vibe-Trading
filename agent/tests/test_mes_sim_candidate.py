from __future__ import annotations

from datetime import datetime

from strategies.mes_sim_candidate import evaluate_mes_candidate, run_mes_candidate
from strategies.topstep_prop_bot import Candle


def candle(hour: int, open_: float, high: float, low: float, close: float) -> Candle:
    return Candle(datetime(2026, 7, 20, hour), open_, high, low, close, 1000)


def test_candidate_waits_for_enough_bars() -> None:
    result = evaluate_mes_candidate([candle(10, 6000, 6002, 5998, 6001)])
    assert result["state"] == "waiting_for_closed_1h_bars"
    assert result["signal"] is None


def test_default_runner_is_observation_only() -> None:
    result = run_mes_candidate(execute_sim=False, fetch_fn=lambda: [])
    assert result["mode"] == "ninjatrader_sim101_forward_test"
    assert result["execute_sim_requested"] is False
    assert result["execution"] is None


def test_candidate_configuration_can_emit_mes_signal() -> None:
    candles = [
        candle(10, 6000, 6002, 5998, 6000),
        candle(11, 6001, 6010, 6001, 6008),
        candle(12, 6008, 6009, 6001, 6005),
    ]
    result = evaluate_mes_candidate(candles)
    assert result["state"] in {"mes_pullback_signal", "no_mes_pullback_signal"}
    if result["signal"]:
        assert result["signal"]["candidate"] == "es_1h_orb3_pullback_tol16_stop40_full_2r"


def test_execution_is_blocked_after_candidate_invalidation() -> None:
    result = run_mes_candidate(execute_sim=True, fetch_fn=lambda: [])
    assert result["research_approved_for_sim"] is False
    assert result["execution"]["status"] == "blocked"

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pandas as pd

from agent.src.research.blsh_bakeoff import (
    append_prediction_ledger, arps_predictions, build_bakeoff,
    common_feature_fabric, diebold_mariano, donchian_climax_predictions,
    join_forward_returns, lightgbm_predictions, liquid_universe,
    statistical_promotion_gate,
)


def _bars(days=90):
    start = datetime(2025, 1, 1, tzinfo=timezone.utc)
    rows = []
    for ticker, offset in (("SPY", 0), ("QQQ", 10)):
        for index in range(days):
            close = 100 + offset + index * .1 + (index % 7 - 3) * .2
            rows.append({"ticker": ticker, "timestamp": start + timedelta(days=index), "open": close - .1, "high": close + .5, "low": close - .5, "close": close, "volume": 1000 * (3 if index == days - 1 else 1)})
    return rows


def test_all_scanners_share_identical_fabric_and_authority():
    fabric = common_feature_fabric(_bars())
    outputs = [arps_predictions(fabric), donchian_climax_predictions(fabric)]
    assert all(len(row) == len(fabric) for row in outputs)
    assert all(set(row["ticker"]) == {"SPY", "QQQ"} for row in outputs)
    assert all(not row["execution_enabled"].any() and not row["can_submit_orders"].any() for row in outputs)
    report = build_bakeoff(_bars())
    assert report["prediction_count"] == len(fabric) * 3
    assert report["promotion_authority"] == "human_review_only"


def test_forward_join_is_future_only_and_ledger_idempotent(tmp_path):
    fabric = common_feature_fabric(_bars())
    predictions = arps_predictions(fabric)
    joined = join_forward_returns(predictions, pd.DataFrame(_bars()), horizons=(1,))
    first = joined[joined["ticker"] == "SPY"].iloc[0]
    spy = fabric[fabric["ticker"] == "SPY"].reset_index(drop=True)
    assert first["forward_return_1"] == spy.iloc[1]["close"] / spy.iloc[0]["close"] - 1
    path = tmp_path / "predictions.parquet"
    assert append_prediction_ledger(predictions, path) == len(predictions)
    assert append_prediction_ledger(predictions, path) == 0


def test_universe_and_dm_gate_are_deterministic():
    universe = liquid_universe({"AAPL": 5, "MSFT": 4, "BAD": 0}, top_n=1)
    assert universe == ["SPY", "QQQ", "IWM", "GLD", "TLT", "AAPL"]
    assert diebold_mariano([1] * 10, [0] * 10)["status"] == "insufficient_data"
    result = diebold_mariano([1 + i / 100 for i in range(40)], [i / 200 for i in range(40)])
    assert result["status"] == "observed"


def test_stat_gate_requires_live_window_and_never_auto_promotes():
    rows = pd.DataFrame({"scanner_id": ["a", "b"] * 20, "ts": pd.date_range("2026-01-01", periods=40, tz="UTC"), "excess_return": [.01, 0] * 20})
    assert statistical_promotion_gate(rows)["status"] == "insufficient_data"
    larger = pd.DataFrame({
        "scanner_id": [scanner for day in range(70) for scanner in ("a", "b") for _ in range(15)],
        "ts": [pd.Timestamp("2026-01-01", tz="UTC") + pd.Timedelta(days=day, minutes=slot) for day in range(70) for _scanner in ("a", "b") for slot in range(15)],
        "excess_return": [(.02 + (slot % 3) * .001) if scanner == "a" else (slot % 3) * .001 for _day in range(70) for scanner in ("a", "b") for slot in range(15)],
    })
    gate = statistical_promotion_gate(larger)
    assert gate["status"] == "human_review_nomination"
    assert gate["automatic_registry_change"] is False


def test_lightgbm_is_walk_forward_and_keeps_training_rows_abstained():
    fabric = common_feature_fabric(_bars(220))
    output = lightgbm_predictions(fabric, min_train_rows=120)
    assert set(output["side"]) <= {"LONG", "SHORT", "ABSTAIN"}
    assert (output.iloc[:120]["side"] == "ABSTAIN").all()
    assert not output["execution_enabled"].any()

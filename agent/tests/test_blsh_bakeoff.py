from __future__ import annotations

from datetime import datetime, timedelta, timezone
import math

import pandas as pd
import pytest

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


def _schedule(bars):
    # Explicit synthetic one-bar sessions; not a production holiday calendar.
    stamps = pd.to_datetime(pd.DataFrame(bars).timestamp, utc=True).drop_duplicates().sort_values()
    return pd.DataFrame({"market_open": stamps - pd.Timedelta(minutes=15), "market_close": stamps})


def test_all_scanners_share_identical_fabric_and_authority():
    fabric = common_feature_fabric(_bars())
    outputs = [arps_predictions(fabric), donchian_climax_predictions(fabric)]
    assert all(len(row) == len(fabric) for row in outputs)
    assert all(set(row["ticker"]) == {"SPY", "QQQ"} for row in outputs)
    assert all(not row["execution_enabled"].any() and not row["can_submit_orders"].any() for row in outputs)
    report = build_bakeoff(_bars(), schedule=_schedule(_bars()))
    assert report["prediction_count"] == len(fabric) * 3
    assert report["promotion_authority"] == "human_review_only"


def test_forward_join_is_future_only_and_ledger_idempotent(tmp_path):
    fabric = common_feature_fabric(_bars())
    predictions = arps_predictions(fabric)
    joined = join_forward_returns(predictions, pd.DataFrame(_bars()), horizons=(1,), schedule=_schedule(_bars()))
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
    assert statistical_promotion_gate(rows)["status"] == "blocked_validation_defects"
    larger = pd.DataFrame({
        "scanner_id": [scanner for day in range(70) for scanner in ("a", "b") for _ in range(15)],
        "ts": [pd.Timestamp("2026-01-01", tz="UTC") + pd.Timedelta(days=day, minutes=slot) for day in range(70) for _scanner in ("a", "b") for slot in range(15)],
        "excess_return": [(.02 + (slot % 3) * .001) if scanner == "a" else (slot % 3) * .001 for _day in range(70) for scanner in ("a", "b") for slot in range(15)],
    })
    gate = statistical_promotion_gate(larger)
    assert gate["status"] == "blocked_validation_defects"
    assert gate["winner_candidate"] is None
    assert gate["automatic_registry_change"] is False


def test_lightgbm_is_walk_forward_and_keeps_training_rows_abstained():
    fabric = common_feature_fabric(_bars(220))
    output = lightgbm_predictions(fabric, min_train_rows=120, schedule=_schedule(_bars(220)))
    assert set(output["side"]) <= {"LONG", "SHORT", "ABSTAIN"}
    assert (output.iloc[:120]["side"] == "ABSTAIN").all()
    assert not output["execution_enabled"].any()


def test_outcomes_do_not_change_when_another_scanner_is_added():
    bars = pd.DataFrame(_bars())
    predictions = arps_predictions(common_feature_fabric(bars))
    second = predictions.assign(scanner_id="other")
    alone = join_forward_returns(predictions, bars, horizons=(1,), schedule=_schedule(bars))
    together = join_forward_returns(pd.concat([predictions, second]), bars, horizons=(1,), schedule=_schedule(bars))
    pd.testing.assert_series_equal(alone["forward_return_1"].reset_index(drop=True), together[together.scanner_id == "arps_v1"]["forward_return_1"].reset_index(drop=True))


def test_vwap_resets_each_new_session():
    fabric = common_feature_fabric(_bars())
    spy = fabric[fabric.ticker == "SPY"]
    assert spy.iloc[1].vwap == (spy.iloc[1].high + spy.iloc[1].low + spy.iloc[1].close) / 3


def test_calendar_holiday_and_missing_session_never_shorten_horizon():
    dates = ["2026-09-04T20:00:00Z", "2026-09-08T20:00:00Z", "2026-09-09T20:00:00Z"]
    rows = _bars(3)[:3]
    for row, stamp in zip(rows, dates):
        row["timestamp"] = pd.Timestamp(stamp)
    schedule = _schedule(rows)
    predictions = arps_predictions(common_feature_fabric(rows)).iloc[:1].assign(side="SHORT")
    joined = join_forward_returns(predictions, pd.DataFrame(rows), (1,), schedule=schedule)
    assert joined.iloc[0].outcome_ts_1 == pd.Timestamp(dates[1])
    assert joined.iloc[0].mfe_1 >= 0
    assert joined.iloc[0].mae_1 <= 0
    missing = join_forward_returns(predictions, pd.DataFrame([rows[0], rows[2]]), (1,), schedule=schedule)
    assert pd.isna(missing.iloc[0].forward_return_1)
    assert missing.iloc[0].outcome_status_1 == "missing_future_session_or_bars"


def test_intraday_horizon_requires_every_bar_through_next_close():
    stamps = pd.to_datetime(["2026-09-04T19:45Z", "2026-09-04T20:00Z", "2026-09-08T19:45Z", "2026-09-08T20:00Z"])
    rows = _bars(4)[:4]
    for row, stamp in zip(rows, stamps):
        row["timestamp"] = stamp
    schedule = pd.DataFrame({"market_open": pd.to_datetime(["2026-09-04T19:30Z", "2026-09-08T19:30Z"]), "market_close": stamps[[1, 3]]})
    prediction = arps_predictions(common_feature_fabric(rows)).iloc[:1]
    result = join_forward_returns(prediction, pd.DataFrame(rows), (1,), schedule=schedule)
    assert result.iloc[0].forward_return_1 == rows[3]["close"] / rows[0]["close"] - 1
    missing = join_forward_returns(prediction, pd.DataFrame([rows[0], rows[1], rows[3]]), (1,), schedule=schedule)
    assert pd.isna(missing.iloc[0].forward_return_1)


def test_walk_forward_global_purge_and_future_perturbation():
    rows = _bars(500)
    # Ensure the training target genuinely has both classes; the ordinary
    # fixture trends upward and correctly causes the classifier to abstain.
    for ticker in ("SPY", "QQQ"):
        ticker_rows = [row for row in rows if row["ticker"] == ticker]
        for index, row in enumerate(ticker_rows):
            close = (100 if ticker == "SPY" else 110) + 4 * math.sin(index / 3) + index * .002
            row.update(open=close - .1, high=close + .5, low=close - .5, close=close)
    schedule = _schedule(rows)
    original = lightgbm_predictions(common_feature_fabric(rows), min_train_rows=100, schedule=schedule)
    trained = original.dropna(subset=["training_cutoff"])
    assert len(trained) > 0
    assert (trained.training_label_max_ts < trained.training_cutoff).all()
    assert (trained.training_cutoff <= trained.ts).all()
    future_boundary = pd.Timestamp("2026-04-01", tz="UTC")
    changed = pd.DataFrame(rows)
    mask = changed.timestamp >= future_boundary
    changed.loc[mask, ["open", "high", "low", "close"]] *= 3
    rerun = lightgbm_predictions(common_feature_fabric(changed), min_train_rows=100, schedule=schedule)
    cols = ["ticker", "ts", "side", "score", "training_cutoff", "training_label_max_ts"]
    pd.testing.assert_frame_equal(original.loc[original.ts < future_boundary, cols], rerun.loc[rerun.ts < future_boundary, cols])


def test_replay_never_claims_live_and_asof_excludes_future():
    rows = _bars()
    cutoff = pd.Timestamp("2025-02-01", tz="UTC")
    report = build_bakeoff(rows, as_of=cutoff, schedule=_schedule(rows))
    assert not report["live_evidence_eligible"]
    assert report["status"] == "quarantined_research_predictions"
    assert all(pd.Timestamp(row["ts"]) <= cutoff for row in report["predictions"])
    assert all(row["collection_mode"] == "historical_replay" for row in report["predictions"])


@pytest.mark.parametrize("script,flag", [("blsh_bakeoff_shadow.py", "--input"), ("blsh_outcome_shadow.py", "--bars")])
def test_cli_missing_input_is_nonzero_and_writes_honest_report(tmp_path, script, flag):
    import json
    import subprocess
    import sys
    from pathlib import Path
    root = Path(__file__).resolve().parents[2]
    report = tmp_path / "report.json"
    result = subprocess.run([sys.executable, str(root / "scripts" / script), flag, str(tmp_path / "missing.json"), "--report", str(report)], capture_output=True, text=True, timeout=30)
    assert result.returncode == 1
    payload = json.loads(report.read_text())
    assert payload["status"] == "unavailable"
    assert payload["generated_at"]
    assert not payload["execution_enabled"]

from __future__ import annotations

import json
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts import timesfm_market_forecaster as timesfm_adapter


def _bars(values: list[float]) -> pd.DataFrame:
    return pd.DataFrame({"Close": values})


def test_interpret_forecast_requires_full_interval_confirmation() -> None:
    row = timesfm_adapter.interpret_forecast(
        "SPY",
        current_close=100.0,
        forecast={
            "point": [101.0, 102.0],
            "q10": [100.5, 101.0],
            "q50": [101.0, 102.0],
            "q90": [102.0, 103.0],
        },
        model_name="test-timesfm",
    )

    assert row["status"] == "ok"
    assert row["forecast_direction"] == "bullish_range"
    assert row["point_forecast_return_pct"] == 2.0
    assert row["q10_q90_width_pct"] == 2.0
    assert row["calibration_status"] == "unvalidated"
    assert row["can_submit_orders"] is False
    assert row["can_change_sizing"] is False


def test_interpret_forecast_marks_straddling_band_uncertain() -> None:
    row = timesfm_adapter.interpret_forecast(
        "QQQ",
        current_close=100.0,
        forecast={
            "point": [101.0],
            "q10": [98.0],
            "q50": [100.5],
            "q90": [103.0],
        },
        model_name="test-timesfm",
    )

    assert row["forecast_direction"] == "uncertain"
    assert row["q10_return_pct"] == -2.0
    assert row["q90_return_pct"] == 3.0


def test_build_report_uses_injected_predictor_without_execution() -> None:
    def predictor(symbol: str, bars: pd.DataFrame, pred_len: int) -> dict[str, list[float]]:
        assert pred_len == 2
        return {
            "point": [101.0, 102.0],
            "q10": [100.2, 100.5],
            "q50": [101.0, 102.0],
            "q90": [102.0, 103.0],
        }

    report = timesfm_adapter.build_report(
        symbols=["SPY"],
        fetcher=lambda symbol, period, interval: _bars([99.0, 100.0]),
        predictor=predictor,
        model_name="test-timesfm",
        pred_len=2,
    )

    assert report["provider"] == "timesfm_market_forecaster"
    assert report["summary"]["ok"] == 1
    assert report["execution_enabled"] is False
    assert report["can_submit_orders"] is False
    assert report["can_change_sizing"] is False
    assert "No broker calls" in " ".join(report["warnings"])


def test_build_report_does_not_load_model_by_default() -> None:
    report = timesfm_adapter.build_report(
        symbols=["SPY"],
        fetcher=lambda symbol, period, interval: _bars([99.0, 100.0]),
    )

    row = report["items"][0]
    assert row["status"] == "model_unavailable"
    assert "timesfm_not_configured" in row["blockers"]
    assert row["recommended_use"] == "setup_required"


def test_invalid_quantile_order_is_rejected() -> None:
    row = timesfm_adapter.interpret_forecast(
        "SPY",
        current_close=100.0,
        forecast={"point": [101.0], "q10": [102.0], "q50": [101.0], "q90": [100.0]},
        model_name="test-timesfm",
    )

    assert row["status"] == "model_unavailable"
    assert "timesfm_quantile_crossing" in row["blockers"]


def test_write_report_and_log_round_trip(tmp_path: Path) -> None:
    report = timesfm_adapter.build_report(symbols=["SPY"])
    report_path = tmp_path / "reports" / "timesfm-market-forecast.json"
    log_path = tmp_path / "data" / "timesfm_market_forecast_log.jsonl"

    timesfm_adapter.write_report(report, report_path, log_path)

    assert json.loads(report_path.read_text(encoding="utf-8")) == report
    rows = [json.loads(line) for line in log_path.read_text(encoding="utf-8").splitlines()]
    assert rows == [report]

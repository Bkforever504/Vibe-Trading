from __future__ import annotations

import json
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts import kronos_market_forecaster as kronos


def _bars(values: list[float]) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "Open": values,
            "High": [value + 1.0 for value in values],
            "Low": [value - 1.0 for value in values],
            "Close": values,
            "Volume": [1_000_000 for _ in values],
        }
    )


def test_interpret_forecast_classifies_direction_and_risk() -> None:
    row = kronos.interpret_forecast(
        "SPY",
        current_close=100.0,
        forecast_closes=[101.0, 102.0, 103.0],
        model_name="NeoQuasar/Kronos-small",
    )

    assert row["symbol"] == "SPY"
    assert row["status"] == "ok"
    assert row["forecast_direction"] == "bullish"
    assert row["forecast_return_pct"] == 3.0
    assert row["max_drawdown_pct"] == 0.0
    assert row["recommended_use"] == "shadow_context"
    assert row["can_submit_orders"] is False


def test_build_report_uses_injected_predictor_without_execution() -> None:
    def fetcher(symbol: str, period: str, interval: str) -> pd.DataFrame:
        return _bars([98.0, 99.0, 100.0])

    def predictor(symbol: str, bars: pd.DataFrame, pred_len: int) -> list[float]:
        return [101.0, 102.0]

    report = kronos.build_report(
        symbols=["SPY"],
        fetcher=fetcher,
        predictor=predictor,
        model_name="test-kronos",
        pred_len=2,
    )

    assert report["provider"] == "kronos_market_forecaster"
    assert report["execution_enabled"] is False
    assert report["can_submit_orders"] is False
    assert report["summary"]["ok"] == 1
    assert report["items"][0]["forecast_direction"] == "bullish"
    assert "No orders" in " ".join(report["warnings"])


def test_build_report_marks_model_unavailable_when_not_configured() -> None:
    report = kronos.build_report(
        symbols=["SPY"],
        fetcher=lambda symbol, period, interval: _bars([99.0, 100.0]),
        predictor=None,
        kronos_repo_path="",
    )

    row = report["items"][0]
    assert row["symbol"] == "SPY"
    assert row["status"] == "model_unavailable"
    assert "kronos_not_configured" in row["blockers"]
    assert row["recommended_use"] == "setup_required"


def test_write_report_and_log_round_trip(tmp_path: Path) -> None:
    report = kronos.build_report(
        symbols=["SPY"],
        fetcher=lambda symbol, period, interval: _bars([99.0, 100.0]),
        predictor=lambda symbol, bars, pred_len: [100.5],
        pred_len=1,
    )
    report_path = tmp_path / "reports" / "kronos-market-forecast.json"
    log_path = tmp_path / "data" / "kronos_market_forecast_log.jsonl"

    kronos.write_report(report, report_path, log_path)

    assert json.loads(report_path.read_text(encoding="utf-8")) == report
    rows = [json.loads(line) for line in log_path.read_text(encoding="utf-8").splitlines()]
    assert rows == [report]

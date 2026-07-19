from __future__ import annotations

import json
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts import distribution_day_scanner as scanner


def test_compute_distribution_days_counts_down_days_on_higher_volume() -> None:
    idx = pd.date_range("2026-05-01", periods=31, freq="B")
    closes = [100.0 + i * 0.2 for i in range(31)]
    volumes = [1_000_000 + i * 1000 for i in range(31)]
    for i in (8, 12, 16, 20, 24):
        closes[i] = closes[i - 1] * 0.99
        volumes[i] = volumes[i - 1] + 500_000
    df = pd.DataFrame({"open": closes, "high": closes, "low": closes, "close": closes, "volume": volumes}, index=idx)

    result = scanner.compute_distribution_days(df, lookback_sessions=25)

    assert result["status"] == "ok"
    assert result["distribution_day_count"] >= 3
    assert result["regime"] in {"caution", "high", "severe"}


def test_aggregate_regime_uses_worst_symbol() -> None:
    agg = scanner.aggregate_regime(
        [
            {"symbol": "QQQ", "status": "ok", "distribution_day_count": 2, "regime": "normal"},
            {"symbol": "SPY", "status": "ok", "distribution_day_count": 5, "regime": "high"},
        ]
    )

    assert agg["regime"] == "high"
    assert agg["max_distribution_days"] == 5


def test_append_log_writes_jsonl(tmp_path: Path) -> None:
    path = tmp_path / "dist.jsonl"
    report = {"date": "2026-06-30", "provider": "distribution_day_scanner"}

    scanner.append_log(report, path)

    assert json.loads(path.read_text(encoding="utf-8").strip()) == report

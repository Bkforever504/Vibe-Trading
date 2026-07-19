from __future__ import annotations

import json
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts import market_breadth_uptrend_scanner as scanner


def test_compute_breadth_detects_confirmed_uptrend() -> None:
    idx = pd.date_range("2025-01-01", periods=220, freq="B")
    data = {}
    for sym in ["SPY", "QQQ", "SMH", "XLK", "NVDA", "AAPL", "XLP", "XLU", "GLD", "TLT"]:
        data[sym] = [100 + i * 0.5 for i in range(220)]
    close = pd.DataFrame(data, index=idx)

    result = scanner.compute_breadth(close)

    assert result["status"] == "ok"
    assert result["pct_above_50dma"] == 100.0
    assert result["uptrend_status"] == "confirmed_uptrend"


def test_force_score_penalizes_defensive_rotation() -> None:
    breadth = {
        "status": "ok",
        "uptrend_status": "confirmed_uptrend",
        "leadership_count": 5,
        "defensive_outperformer_count": 2,
    }

    assert scanner.force_score(breadth) == 1.75


def test_append_log_writes_jsonl(tmp_path: Path) -> None:
    path = tmp_path / "breadth.jsonl"
    report = {"date": "2026-06-30", "provider": "market_breadth_uptrend_scanner"}

    scanner.append_log(report, path)

    assert json.loads(path.read_text(encoding="utf-8").strip()) == report

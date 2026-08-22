from __future__ import annotations

import json
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts import sector_rotation_ranker as ranker


def _close_frame() -> pd.DataFrame:
    idx = pd.date_range("2025-01-01", periods=80, freq="B")
    data = {
        "SPY": [100 + i * 0.1 for i in range(80)],
        "QQQ": [100 + i * 0.6 for i in range(80)],
        "SMH": [100 + i * 0.7 for i in range(80)],
        "XLK": [100 + i * 0.55 for i in range(80)],
        "XLP": [100 + i * 0.05 for i in range(80)],
        "XLU": [100 + i * 0.04 for i in range(80)],
        "TLT": [100 - i * 0.02 for i in range(80)],
    }
    return pd.DataFrame(data, index=idx)


def test_compute_rankings_detects_risk_on_leadership() -> None:
    result = ranker.compute_rankings(_close_frame())

    assert result["status"] == "ok"
    assert result["leadership"] == "risk_on_leadership"
    assert result["force_score"] == 1.5
    assert result["top5"][0]["symbol"] in {"QQQ", "SMH", "XLK"}
    assert result["true_rrg_calculation"] is False
    assert result["execution_authority"] == "context_only"
    assert all("rotation_quadrant_proxy" in row for row in result["rankings"])


def test_rotation_quadrant_proxy_uses_strength_and_momentum_signs() -> None:
    assert ranker._rotation_quadrant("XLK", 1.0, 0.5) == "leading_proxy"
    assert ranker._rotation_quadrant("XLK", 1.0, -0.5) == "weakening_proxy"
    assert ranker._rotation_quadrant("XLV", -1.0, 0.5) == "improving_proxy"
    assert ranker._rotation_quadrant("XLU", -1.0, -0.5) == "lagging_proxy"
    assert ranker._rotation_quadrant("SPY", 1.0, 1.0) == "benchmark"


def test_compute_rankings_detects_insufficient_data() -> None:
    result = ranker.compute_rankings(pd.DataFrame({"SPY": [1, 2, 3]}))

    assert result["status"] == "insufficient_data"


def test_append_log_writes_jsonl(tmp_path: Path) -> None:
    path = tmp_path / "sector.jsonl"
    report = {"date": "2026-06-30", "provider": "sector_rotation_ranker"}

    ranker.append_log(report, path)

    assert json.loads(path.read_text(encoding="utf-8").strip()) == report

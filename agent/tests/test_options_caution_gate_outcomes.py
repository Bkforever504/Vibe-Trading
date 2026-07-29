from __future__ import annotations

import json
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts import options_caution_gate_outcomes as gate


def _closes(symbol: str) -> list[tuple[str, float]]:
    days = [f"2026-07-{day:02d}" for day in range(1, 21)]
    return [(day, 100.0 + index) for index, day in enumerate(days)]


def _decisions_file(tmp_path: Path) -> Path:
    rows = [
        {"action": "skip", "reason": gate.BLOCK_REASON, "symbol": "AAPL",
         "strategy": "ps", "ts": "2026-07-02T14:45:00Z", "warning_count": 2,
         "candidate_confidence": {"score": 8}},
        {"action": "skip", "reason": gate.BLOCK_REASON, "symbol": "NVDA",
         "strategy": "ps", "ts": "2026-07-18T14:45:00Z", "warning_count": 3,
         "candidate_confidence": {"score": 7}},  # unresolved horizon
        {"action": "skip", "reason": gate.BLOCK_REASON, "symbol": "IWM",
         "strategy": "ps", "ts": "2026-07-02T14:45:00Z", "warning_count": 1,
         "candidate_confidence": None},  # synthetic/advisory row
        {"action": "skip", "reason": "trend_filter_below_20sma", "symbol": "PLTR",
         "strategy": "ps", "ts": "2026-07-02T14:45:00Z"},  # different reason
        {"action": "submitted", "symbol": "IWM", "strategy": "ic",
         "ts": "2026-07-03T14:45:00Z"},
    ]
    path = tmp_path / "decisions.jsonl"
    path.write_text("\n".join(json.dumps(row) for row in rows) + "\n", encoding="utf-8")
    return path


def test_forward_move_is_point_in_time_and_unresolved_until_horizon() -> None:
    closes = _closes("X")

    resolved = gate.forward_move(closes, "2026-07-02", 5)
    unresolved = gate.forward_move(closes, "2026-07-18", 5)

    assert resolved is not None
    assert resolved["start_date"] == "2026-07-02"
    assert resolved["end_date"] == "2026-07-07"
    assert resolved["move_pct"] > 0
    assert unresolved is None


def test_daily_closes_degrades_when_parquet_engine_is_unavailable(monkeypatch, tmp_path: Path) -> None:
    parquet = tmp_path / "aapl_sample.parquet"
    parquet.write_text("placeholder", encoding="utf-8")
    monkeypatch.setattr(gate, "DAILY_DIR", tmp_path)
    monkeypatch.setattr(pd, "read_parquet", lambda _path: (_ for _ in ()).throw(ImportError("missing engine")))

    assert gate._daily_closes("AAPL") == []


def test_report_separates_blocked_and_taken_and_gates_on_30_candidates(tmp_path: Path) -> None:
    report = gate.build_report(
        decisions_path=_decisions_file(tmp_path), horizon=5, closes_fn=_closes
    )

    assert report["blocked"]["candidates"] == 2
    assert report["blocked"]["resolved"] == 1
    assert report["blocked"]["unresolved"] == 1
    assert report["taken"]["candidates"] == 1
    assert report["independent_blocked_dates"] == 2
    assert report["review_gate"]["review_eligible"] is False
    assert report["metric_basis"] == "underlying_forward_move_proxy_not_option_pnl"
    # Different-reason skip rows must not enter the blocked cohort.
    blocked_symbols = {row["symbol"] for row in report["rows"]["blocked"]}
    assert "PLTR" not in blocked_symbols

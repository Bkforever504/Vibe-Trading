from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts import rejected_trade_intelligence as rejected


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    path.write_text("\n".join(json.dumps(row) for row in rows) + "\n", encoding="utf-8")


def test_classify_duplicate_exposure_as_likely_good() -> None:
    review = rejected.classify_block(
        {"date": "2026-06-30", "reason": "duplicate_symbol_exposure", "symbol": "SPY", "confidence": 9},
        {"event_summary": {"realized_pnl": 100}},
        {"classification": "bullish_lean"},
    )

    assert review["verdict"] == "likely_good_rejection"
    assert review["review_score"] > 5


def test_classify_near_threshold_confidence_as_possibly_too_strict() -> None:
    review = rejected.classify_block(
        {"date": "2026-06-30", "reason": "confidence_below_minimum", "symbol": "SPY", "confidence": 8.2, "min_confidence": 8.5},
        {"event_summary": {"realized_pnl": 500}},
        {"classification": "bullish_lean"},
    )

    assert review["verdict"] == "possibly_too_strict"


def test_build_report_rolls_up_reason_quality(tmp_path: Path) -> None:
    guard = tmp_path / "guard.jsonl"
    outcome = tmp_path / "outcome.jsonl"
    mf = tmp_path / "mf.jsonl"
    _write_jsonl(guard, [
        {"reason": "duplicate_symbol_exposure", "details": {"checked_at": "2026-06-30T14:00:00Z", "symbol": "SPY", "bot": "flip"}},
        {"reason": "spread_too_wide", "details": {"checked_at": "2026-06-30T15:00:00Z", "symbol": "QQQ", "bot": "flip"}},
    ])
    _write_jsonl(outcome, [{"date": "2026-06-30", "event_summary": {"realized_pnl": 100}}])
    _write_jsonl(mf, [{"date": "2026-06-30", "classification": "bullish_lean"}])

    report = rejected.build_report(guard_paths=[guard], outcome_path=outcome, market_force_path=mf)

    assert report["block_count"] == 2
    assert report["by_reason"]["duplicate_symbol_exposure"] == 1
    assert report["by_verdict"]["likely_good_rejection"] == 2

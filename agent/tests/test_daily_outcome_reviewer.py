from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts import daily_outcome_reviewer as reviewer


def test_summarize_events_counts_trades_blocks_and_pnl() -> None:
    events = [
        {"event_type": "trade", "source": "flip_bot", "pnl": "125.50"},
        {"event_type": "trade", "source": "iwm_options_bot", "pnl": "-25"},
        {"event_type": "guard_block", "reason": "daily_loss_limit"},
        {"event_type": "shadow_signal", "action": "enter_long"},
        {"event_type": "market_force_context"},
    ]

    summary = reviewer.summarize_events(events)

    assert summary["trade_count"] == 2
    assert summary["guard_block_count"] == 1
    assert summary["entry_like_shadow_count"] == 1
    assert summary["realized_pnl"] == 100.5
    assert summary["winning_trade_count"] == 1
    assert summary["losing_trade_count"] == 1


def test_evaluate_posture_marks_cautious_as_helpful_when_risk_showed() -> None:
    result = reviewer.evaluate_posture(
        "cautious",
        -0.75,
        {"realized_pnl": -50, "guard_block_count": 1, "trade_count": 1, "entry_like_shadow_count": 0},
        {"classification": "mixed"},
    )

    assert result["verdict"] == "posture_helpful"
    assert result["review_score"] > 5


def test_evaluate_posture_flags_risk_on_loss() -> None:
    result = reviewer.evaluate_posture(
        "aggressive",
        5,
        {"realized_pnl": -250, "guard_block_count": 0, "trade_count": 2, "entry_like_shadow_count": 0},
        {"classification": "bullish_confirmation"},
    )

    assert result["verdict"] == "possibly_too_loose"
    assert result["review_score"] < 5


def test_build_report_uses_sources_and_event_collector(tmp_path: Path, monkeypatch) -> None:
    paths = {name: tmp_path / f"{name}.jsonl" for name in reviewer.SOURCE_PATHS}
    paths["exposure"].write_text(json.dumps({"date": "2026-06-30", "posture": "normal", "score": 3}) + "\n", encoding="utf-8")
    paths["market_force"].write_text(json.dumps({"date": "2026-06-30", "classification": "bullish_confirmation", "total_score": 4}) + "\n", encoding="utf-8")
    paths["breadth"].write_text(json.dumps({"date": "2026-06-30", "breadth": {"uptrend_status": "confirmed_uptrend"}}) + "\n", encoding="utf-8")
    paths["distribution"].write_text(json.dumps({"date": "2026-06-30", "aggregate": {"regime": "normal"}}) + "\n", encoding="utf-8")
    monkeypatch.setattr(reviewer, "collect_events", lambda day: [{"event_type": "trade", "source": "flip_bot", "pnl": "100"}])

    report = reviewer.build_report(day="2026-06-30", paths=paths)

    assert report["execution_enabled"] is False
    assert report["posture"] == "normal"
    assert report["verdict"] == "posture_helpful"
    assert report["event_summary"]["realized_pnl"] == 100


def test_append_log_writes_jsonl(tmp_path: Path) -> None:
    path = tmp_path / "review.jsonl"
    report = {"date": "2026-06-30", "provider": "daily_outcome_reviewer"}

    reviewer.append_log(report, path)

    assert json.loads(path.read_text(encoding="utf-8").strip()) == report

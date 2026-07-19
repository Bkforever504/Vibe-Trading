from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts import needs_review_queue as queue


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    path.write_text("\n".join(json.dumps(row) for row in rows) + "\n", encoding="utf-8")


def test_build_queue_prioritizes_possibly_too_strict(tmp_path: Path) -> None:
    guard = tmp_path / "guard.jsonl"
    outcome = tmp_path / "outcome.jsonl"
    market_force = tmp_path / "market_force.jsonl"
    _write_jsonl(guard, [
        {
            "reason": "confidence_below_minimum",
            "details": {
                "checked_at": "2026-06-30T14:00:00Z",
                "symbol": "SPY",
                "bot": "flip",
                "confidence": 8.2,
                "min_confidence": 8.5,
            },
        },
        {
            "reason": "duplicate_symbol_exposure",
            "details": {
                "checked_at": "2026-06-30T14:05:00Z",
                "symbol": "QQQ",
                "bot": "flip",
                "confidence": 9.0,
            },
        },
    ])
    _write_jsonl(outcome, [{"date": "2026-06-30", "event_summary": {"realized_pnl": 535}}])
    _write_jsonl(market_force, [{"date": "2026-06-30", "classification": "bullish_lean"}])

    report = queue.build_queue(
        guard_paths=[guard],
        outcome_path=outcome,
        market_force_path=market_force,
    )

    assert report["execution_enabled"] is False
    assert report["queue_count"] == 1
    assert report["items"][0]["priority"] == "high"
    assert report["items"][0]["symbol"] == "SPY"
    assert "not permission" in " ".join(report["warnings"])


def test_build_queue_respects_max_items(tmp_path: Path) -> None:
    guard = tmp_path / "guard.jsonl"
    outcome = tmp_path / "outcome.jsonl"
    market_force = tmp_path / "market_force.jsonl"
    rows = [
        {
            "reason": "confidence_below_minimum",
            "details": {
                "checked_at": f"2026-06-{20 + idx:02d}T14:00:00Z",
                "symbol": f"SYM{idx}",
                "bot": "flip",
                "confidence": 8.2,
                "min_confidence": 8.5,
            },
        }
        for idx in range(5)
    ]
    _write_jsonl(guard, rows)
    _write_jsonl(outcome, [
        {"date": f"2026-06-{20 + idx:02d}", "event_summary": {"realized_pnl": 100}}
        for idx in range(5)
    ])
    _write_jsonl(market_force, [
        {"date": f"2026-06-{20 + idx:02d}", "classification": "bullish_lean"}
        for idx in range(5)
    ])

    report = queue.build_queue(
        guard_paths=[guard],
        outcome_path=outcome,
        market_force_path=market_force,
        max_items=2,
    )

    assert report["queue_count"] == 2
    assert report["by_priority"]["high"] == 2


def test_kalshi_safety_locks_do_not_enter_needs_review_queue(tmp_path: Path) -> None:
    guard = tmp_path / "kalshi-guard-blocks.jsonl"
    outcome = tmp_path / "outcome.jsonl"
    market_force = tmp_path / "market_force.jsonl"
    _write_jsonl(guard, [
        {
            "reason": "dry_run_active",
            "details": {
                "checked_at": "2026-06-30T14:00:00Z",
                "market_ticker": "KXHIGHNY-26JUN30-T95",
                "side": "yes",
                "price_cents": 40,
                "contracts": 2,
                "edge": 0.12,
            },
        }
    ])
    _write_jsonl(outcome, [])
    _write_jsonl(market_force, [])

    report = queue.build_queue(
        guard_paths=[guard],
        outcome_path=outcome,
        market_force_path=market_force,
    )

    assert report["queue_count"] == 0


def test_kalshi_contract_limit_gets_medium_review_action(tmp_path: Path) -> None:
    guard = tmp_path / "kalshi-guard-blocks.jsonl"
    outcome = tmp_path / "outcome.jsonl"
    market_force = tmp_path / "market_force.jsonl"
    _write_jsonl(guard, [
        {
            "reason": "contracts_above_limit",
            "details": {
                "checked_at": "2026-06-30T14:00:00Z",
                "market_ticker": "KXHIGHNY-26JUN30-T95",
                "side": "yes",
                "price_cents": 40,
                "contracts": 5,
                "edge": 0.12,
            },
        }
    ])
    _write_jsonl(outcome, [])
    _write_jsonl(market_force, [])

    report = queue.build_queue(
        guard_paths=[guard],
        outcome_path=outcome,
        market_force_path=market_force,
    )

    assert report["queue_count"] == 1
    item = report["items"][0]
    assert item["priority"] == "medium"
    assert item["guard_source"] == "kalshi"
    assert item["market_ticker"] == "KXHIGHNY-26JUN30-T95"
    assert "contract cap unchanged" in item["next_action"]

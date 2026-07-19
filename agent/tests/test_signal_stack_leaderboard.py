from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts import signal_stack_leaderboard as leaderboard


def test_summarize_jsonl_source_extracts_confidence_actions_and_freshness(tmp_path: Path) -> None:
    path = tmp_path / "shadow.jsonl"
    path.write_text(
        json.dumps({
            "date": "2026-06-30",
            "execution_mode": "shadow_only",
            "primary_setup": {"action": "enter_long", "confidence": 9.2},
        }) + "\n",
        encoding="utf-8",
    )

    item = leaderboard._summarize_jsonl_source(
        "Test Shadow",
        "shadow_strategy",
        path,
        datetime(2026, 6, 30, 12, tzinfo=timezone.utc),
    )

    assert item["sample_count"] == 1
    assert item["signal_count"] == 1
    assert item["avg_confidence"] == 9.2
    assert item["freshness"]["status"] == "fresh"
    assert item["execution_mode"] == "shadow_only"


def test_flip_shadow_leaderboard_excludes_legacy_repeated_rows(tmp_path: Path) -> None:
    path = tmp_path / "flip_shadow.jsonl"
    path.write_text(
        "\n".join([
            json.dumps({"date": "2026-07-09", "action": "enter_shadow", "execution_mode": "shadow_only"}),
            json.dumps({
                "date": "2026-07-10",
                "schema_version": 2,
                "data_quality": "current_session_lifecycle",
                "action": "enter_shadow",
                "execution_mode": "shadow_only",
            }),
            json.dumps({
                "date": "2026-07-10",
                "schema_version": 2,
                "data_quality": "current_session_lifecycle",
                "action": "hold_shadow",
                "execution_mode": "shadow_only",
            }),
        ]) + "\n",
        encoding="utf-8",
    )

    item = leaderboard._summarize_jsonl_source(
        "Flip Shadow Candidates",
        "shadow_strategy",
        path,
        datetime(2026, 7, 10, 18, tzinfo=timezone.utc),
    )

    assert item["sample_count"] == 2
    assert item["signal_count"] == 1
    assert any("Excluded 1 legacy" in note for note in item["notes"])


def test_max_drawdown_from_pnls_uses_cumulative_curve() -> None:
    assert leaderboard._max_drawdown_from_pnls([100, -50, -75, 25]) == -125


def test_summarize_flip_trades_splits_post_config_metrics(monkeypatch, tmp_path: Path) -> None:
    vibe_home = tmp_path / ".vibe-trading"
    vibe_home.mkdir()
    (vibe_home / "flip-trades.json").write_text(
        json.dumps([
            {"entry_date": "2026-06-23", "status": "closed", "contracts": 69, "pnl": -11557.5},
            {"entry_date": "2026-06-29", "status": "closed", "contracts": 5, "pnl": 535.0},
            {"entry_date": "2026-06-30", "status": "closed", "contracts": 5, "pnl": 488.0},
        ]),
        encoding="utf-8",
    )
    monkeypatch.setattr(leaderboard, "VIBE_HOME", vibe_home)
    monkeypatch.setattr(
        leaderboard,
        "_registry_signal",
        lambda signal_id: {
            "config_change_date": "2026-06-24",
            "post_config_start_date": "2026-06-29",
        },
    )

    item = leaderboard._summarize_flip_trades(datetime(2026, 7, 4, tzinfo=timezone.utc))

    assert item["total_pnl"] == -10534.5
    assert item["config_change_date"] == "2026-06-24"
    assert item["post_config"]["sample_count"] == 2
    assert item["post_config"]["total_pnl"] == 1023.0
    assert item["post_config"]["win_rate"] == 1.0
    assert "All-time PnL includes pre-fix risk artifact." in item["notes"]


def test_market_force_leaderboard_uses_top_level_confidence(tmp_path: Path) -> None:
    path = tmp_path / "market_force.jsonl"
    path.write_text(
        json.dumps({
            "date": "2026-06-30",
            "provider": "market_force_score",
            "mode": "read_only",
            "confidence": 7.0,
            "forces": [{"name": "trend", "score": 2.0}, {"name": "narrative", "score": 1.0}],
        }) + "\n",
        encoding="utf-8",
    )

    item = leaderboard._summarize_jsonl_source(
        "Market Force Score",
        "context_scanner",
        path,
        datetime(2026, 6, 30, 12, tzinfo=timezone.utc),
    )

    assert item["avg_confidence"] == 7.0


def test_leaderboard_accepts_generated_at_timestamps(tmp_path: Path) -> None:
    path = tmp_path / "review.jsonl"
    path.write_text(
        json.dumps({
            "generated_at": "2026-06-30T20:00:00",
            "provider": "challenge_account_simulator",
            "mode": "read_only",
        }) + "\n",
        encoding="utf-8",
    )

    item = leaderboard._summarize_jsonl_source(
        "Challenge Account Simulator",
        "review_layer",
        path,
        datetime(2026, 7, 1, 1, tzinfo=timezone.utc),
    )

    assert item["freshness"]["status"] == "fresh"
    assert item["execution_mode"] == "read_only"


def test_build_leaderboard_applies_guard_block_counts(monkeypatch) -> None:
    monkeypatch.setattr(
        leaderboard,
        "JSONL_SOURCES",
        [],
    )
    monkeypatch.setattr(
        leaderboard,
        "_summarize_flip_trades",
        lambda now: {
            "name": "Flip Bot",
            "category": "alpaca_options_execution",
            "sample_count": 1,
            "signal_count": 1,
            "freshness": {"status": "fresh", "age_days": 0},
            "execution_mode": "paper_or_live_alpaca",
            "avg_confidence": None,
            "blocked_count": 0,
            "total_pnl": 50,
            "win_rate": 1.0,
            "max_drawdown_dollars": 0,
            "notes": [],
        },
    )
    monkeypatch.setattr(
        leaderboard,
        "_summarize_iwm_trades",
        lambda now: {
            "name": "IWM Options Bot",
            "category": "alpaca_options_execution",
            "sample_count": 1,
            "signal_count": 1,
            "freshness": {"status": "fresh", "age_days": 0},
            "execution_mode": "paper_or_live_alpaca",
            "avg_confidence": 9,
            "blocked_count": 0,
            "total_pnl": None,
            "win_rate": None,
            "max_drawdown_dollars": None,
            "notes": [],
        },
    )
    monkeypatch.setattr(leaderboard, "_guard_block_counts", lambda: {"flip": 2, "options": 1})

    report = leaderboard.build_leaderboard(datetime(2026, 6, 30, tzinfo=timezone.utc))

    counts = {item["name"]: item["blocked_count"] for item in report["items"]}
    assert counts["Flip Bot"] == 2
    assert counts["IWM Options Bot"] == 1
    assert report["execution_enabled"] is False

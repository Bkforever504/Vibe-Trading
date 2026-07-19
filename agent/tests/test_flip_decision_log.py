from __future__ import annotations

import json
from datetime import datetime, time, timezone
from pathlib import Path


def test_decision_log_has_stable_nested_schema(monkeypatch, tmp_path: Path) -> None:
    from strategies import flip_bot

    path = tmp_path / "flip-decisions.jsonl"
    monkeypatch.setattr(flip_bot, "DECISION_LOG_FILE", path)
    monkeypatch.setattr(flip_bot, "_utc_now_text", lambda: "2026-07-13T15:00:00Z")

    flip_bot._decision("spy", "bear_trend", "skip", "entry_cutoff", cutoff_et="14:00:00")

    row = json.loads(path.read_text(encoding="utf-8"))
    assert row == {
        "action": "skip",
        "details": {"cutoff_et": "14:00:00"},
        "paper": flip_bot.PAPER,
        "reason": "entry_cutoff",
        "strategy": "bear_trend",
        "symbol": "SPY",
        "ts": "2026-07-13T15:00:00Z",
    }


def test_pytest_process_never_targets_real_runtime_log() -> None:
    from strategies import flip_bot

    assert "vibe-trading-pytest-" in str(flip_bot.DECISION_LOG_FILE)
    assert flip_bot.DECISION_LOG_FILE != flip_bot.LOG_DIR / "flip-decisions.jsonl"


def test_bear_cutoff_writes_exactly_one_skip(monkeypatch, tmp_path: Path) -> None:
    from strategies import flip_bot

    path = tmp_path / "flip-decisions.jsonl"
    monkeypatch.setattr(flip_bot, "DECISION_LOG_FILE", path)
    monkeypatch.setattr(
        flip_bot,
        "_now_et",
        lambda: datetime(2026, 7, 13, 14, 1, tzinfo=timezone.utc),
    )
    monkeypatch.setattr(flip_bot, "BEAR_TREND_ENTRY_CUTOFF_ET", time(14, 0))

    assert flip_bot.find_bear_trend_day(10_000) is None

    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    assert len(rows) == 1
    assert rows[0]["reason"] == "entry_cutoff"


def test_entry_quality_preserves_missing_quote_age() -> None:
    from strategies import flip_bot

    quality = flip_bot._entry_quality_snapshot(
        {"entry_price_est": 1.0, "selection_bid": 0.95, "selection_ask": 1.05},
        1.0,
        "broker_fill",
        now_et=datetime(2026, 7, 13, 10, 0, tzinfo=timezone.utc),
    )

    assert quality["selection_bid"] == 0.95
    assert quality["selection_ask"] == 1.05
    assert quality["quote_timestamp"] is None
    assert quality["quote_age_seconds"] is None


def test_bear_stale_session_reason_is_not_collapsed(monkeypatch, tmp_path: Path) -> None:
    from strategies import flip_bot

    path = tmp_path / "flip-decisions.jsonl"
    monkeypatch.setattr(flip_bot, "DECISION_LOG_FILE", path)
    monkeypatch.setattr(flip_bot, "_now_et", lambda: datetime(2026, 7, 13, 10, 0, tzinfo=timezone.utc))
    monkeypatch.setattr(flip_bot, "_fetch_vix_term_structure", lambda: {"regime": "contango"})
    monkeypatch.setattr(flip_bot, "_vix_term_structure_direction_ok", lambda *args: True)
    monkeypatch.setattr(flip_bot, "_intraday_bars", lambda symbol: None)
    flip_bot._INTRADAY_DATA_ISSUES["SPY"] = "stale_session"

    assert flip_bot.find_bear_trend_day(10_000) is None

    row = json.loads(path.read_text(encoding="utf-8").splitlines()[0])
    assert row["reason"] == "stale_session"


def test_option_mid_captures_quote_age(monkeypatch) -> None:
    from strategies import flip_bot

    class Response:
        status_code = 200

        @staticmethod
        def json():
            return {"snapshots": {"SPYOPT": {"latestQuote": {
                "bp": 0.95, "ap": 1.05, "t": "2026-07-13T15:00:00Z",
            }}}}

    class FixedDateTime(datetime):
        @classmethod
        def now(cls, tz=None):
            return cls(2026, 7, 13, 15, 0, 4, tzinfo=timezone.utc)

    monkeypatch.setattr(flip_bot.req, "get", lambda *args, **kwargs: Response())
    monkeypatch.setattr(flip_bot, "datetime", FixedDateTime)

    assert flip_bot._option_mid("SPYOPT") == 1.0
    assert flip_bot._selection_quote_fields("SPYOPT") == {
        "selection_bid": 0.95,
        "selection_ask": 1.05,
        "quote_timestamp": "2026-07-13T15:00:00Z",
        "quote_age_seconds": 4.0,
    }

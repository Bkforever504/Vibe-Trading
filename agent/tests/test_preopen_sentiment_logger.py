from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts import preopen_sentiment_logger as logger


def test_classify_prefers_stocktwits_sentiment_tag() -> None:
    msg = {
        "id": 1,
        "body": "$SPY this looks terrible but user tagged bullish",
        "entities": {"sentiment": {"basic": "Bullish"}},
        "user": {"username": "tester", "followers": 99},
    }

    classified = logger.classify_message(msg)

    assert classified["score"] == 1
    assert classified["score_source"] == "stocktwits_tag"


def test_summarize_symbol_scores_bias_from_messages() -> None:
    messages = [
        {"body": "$SPY breakout calls", "entities": {}, "user": {"followers": 10}},
        {"body": "$SPY bullish rally", "entities": {}, "user": {"followers": 20}},
        {"body": "$SPY weak sell", "entities": {}, "user": {"followers": 5}},
    ]

    result = logger.summarize_symbol("SPY", messages)

    assert result["symbol"] == "SPY"
    assert result["message_count"] == 3
    assert result["classified_count"] == 3
    assert result["bias"] == "bullish"


def test_build_entry_is_context_only(monkeypatch) -> None:
    monkeypatch.setattr(
        logger,
        "fetch_stocktwits_messages",
        lambda symbol, limit=30, timeout=15: [
            {
                "id": f"{symbol}-1",
                "body": f"${symbol} bearish breakdown",
                "entities": {"sentiment": {"basic": "Bearish"}},
                "user": {"username": "bear", "followers": 100},
            }
        ],
    )

    entry = logger.build_entry(symbols=["SPY", "QQQ"], limit=1)

    assert entry["mode"] == "context_only"
    assert entry["execution_enabled"] is False
    assert entry["aggregate"]["bias"] == "bearish"
    assert len(entry["scans"]) == 2


def test_append_log_writes_jsonl(tmp_path) -> None:
    log_path = tmp_path / "sentiment.jsonl"
    entry = {"date": "2026-06-30", "aggregate": {"bias": "neutral"}}

    logger.append_log(entry, log_path=log_path)

    rows = [json.loads(line) for line in log_path.read_text(encoding="utf-8").splitlines()]
    assert rows == [entry]

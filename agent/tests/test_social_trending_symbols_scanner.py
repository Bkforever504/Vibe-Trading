from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts import social_trending_symbols_scanner as scanner


def test_normalize_symbol_buckets_core_names() -> None:
    row = {
        "rank": 1,
        "symbol": "NVDA",
        "title": "Nvidia",
        "instrument_class": "Stock",
        "trending_score": 9.5,
        "watchlist_count": 100000,
        "fundamentals": {"MarketCap": 1_000_000, "AverageDailyVolumeLastMonth": 50_000_000},
        "trends": {"summary": "AI chip demand", "summary_at": "2026-06-30T00:00:00Z"},
    }

    normalized = scanner.normalize_symbol(row)

    assert normalized["symbol"] == "NVDA"
    assert normalized["bucket"] == "ai_semis_software"
    assert normalized["action"] == "watch_context"
    assert normalized["execution_enabled"] is False if "execution_enabled" in normalized else True


def test_normalize_symbol_flags_small_thin_stock() -> None:
    row = {
        "rank": 3,
        "symbol": "TINY",
        "instrument_class": "Stock",
        "trending_score": 5,
        "fundamentals": {"MarketCap": 250, "AverageDailyVolumeLastMonth": 100_000},
    }

    normalized = scanner.normalize_symbol(row)

    assert normalized["action"] == "context_only"
    assert any("small-cap" in flag for flag in normalized["noise_flags"])
    assert any("liquidity" in flag for flag in normalized["noise_flags"])


def test_meme_symbols_stay_context_only_even_if_core_watchlist() -> None:
    row = {
        "rank": 1,
        "symbol": "GME",
        "instrument_class": "Stock",
        "trending_score": 10,
        "fundamentals": {"MarketCap": 20_000, "AverageDailyVolumeLastMonth": 10_000_000},
    }

    normalized = scanner.normalize_symbol(row)

    assert normalized["bucket"] == "meme_high_noise"
    assert normalized["action"] == "context_only"
    assert any("meme-stock baseline" in flag for flag in normalized["noise_flags"])


def test_social_squeeze_watch_symbols_stay_context_only() -> None:
    row = {
        "rank": 2,
        "symbol": "FRMM",
        "instrument_class": "Stock",
        "trending_score": 9,
        "fundamentals": {"MarketCap": 83, "AverageDailyVolumeLastMonth": 2_000_000},
        "trends": {"summary": "Short squeeze metrics and July call open interest rising"},
    }

    normalized = scanner.normalize_symbol(row)

    assert normalized["bucket"] == "social_squeeze_watch"
    assert normalized["action"] == "context_only"
    assert any("social squeeze watch" in flag for flag in normalized["noise_flags"])
    assert any("small-cap" in flag for flag in normalized["noise_flags"])


def test_build_report_is_context_only(monkeypatch) -> None:
    monkeypatch.setattr(
        scanner,
        "fetch_stocktwits_trending",
        lambda: [
            {
                "rank": 1,
                "symbol": "SPY",
                "instrument_class": "Exchange Traded Fund",
                "trending_score": 10,
                "fundamentals": {"MarketCap": 500_000, "AverageDailyVolumeLastMonth": 80_000_000},
            },
            {
                "rank": 2,
                "symbol": "BTC.X",
                "instrument_class": "Crypto",
                "trending_score": 8,
                "fundamentals": {},
            },
        ],
    )

    report = scanner.build_report(limit=10, now=datetime(2026, 6, 30, 15, 20, tzinfo=timezone.utc))

    assert report["date"] == "2026-06-30"
    assert report["mode"] == "context_only"
    assert report["execution_enabled"] is False
    assert "intraday_scan_index" in report
    assert report["scheduled_interval_minutes"] == 120
    assert report["symbol_count"] == 2
    assert report["symbols"][0]["symbol"] == "SPY"
    assert report["symbols"][1]["bucket"] == "crypto"


def test_intraday_scan_index_uses_two_hour_slots() -> None:
    assert scanner.intraday_scan_index(datetime(2026, 6, 30, 8, 20)) == 0
    assert scanner.intraday_scan_index(datetime(2026, 6, 30, 10, 20)) == 1
    assert scanner.intraday_scan_index(datetime(2026, 6, 30, 12, 45)) == 2


def test_append_and_write_report(tmp_path) -> None:
    report = {"provider": "social_trending_symbols_scanner", "mode": "context_only"}
    log_path = tmp_path / "trend.jsonl"
    report_path = tmp_path / "trend.json"

    scanner.append_log(report, log_path)
    scanner.write_report(report, report_path)

    assert json.loads(log_path.read_text(encoding="utf-8").strip()) == report
    assert json.loads(report_path.read_text(encoding="utf-8")) == report

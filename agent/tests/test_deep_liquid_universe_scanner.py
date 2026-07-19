from __future__ import annotations

import json
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts import deep_liquid_universe_scanner as scanner


def _frame(closes: list[float], volumes: list[int] | None = None) -> pd.DataFrame:
    volumes = volumes or [10_000_000] * len(closes)
    index = pd.date_range("2026-01-01", periods=len(closes), freq="B")
    return pd.DataFrame(
        {
            "open": closes,
            "high": [c * 1.02 for c in closes],
            "low": [c * 0.98 for c in closes],
            "close": closes,
            "volume": volumes,
        },
        index=index,
    )


def test_score_symbol_prefers_liquid_momentum_with_social_persistence() -> None:
    df = _frame(
        [100 + i for i in range(70)],
        [8_000_000] * 49 + [10_000_000] * 20 + [35_000_000],
    )

    row = scanner.score_symbol("AAPL", df, social_context={"social_slot_count": 3, "best_social_rank": 8})

    assert row["symbol"] == "AAPL"
    assert row["status"] == "ok"
    assert row["avg_dollar_volume_20d"] > 1_000_000_000
    assert row["relative_volume"] > 3
    assert row["social_slot_count"] == 3
    assert row["recommendation"] == "shadow_review_candidate"
    assert row["deep_score"] >= 8


def test_score_symbol_rejects_thin_low_price_names() -> None:
    df = _frame([4.0 + i * 0.01 for i in range(70)], [80_000] * 70)

    row = scanner.score_symbol("PUMP", df, social_context={"social_slot_count": 6, "best_social_rank": 1})

    assert row["recommendation"] == "reject_for_flip_bot"
    assert "price_below_minimum" in row["risk_flags"]
    assert "thin_dollar_volume" in row["risk_flags"]


def test_load_social_context_counts_recent_slots(tmp_path: Path) -> None:
    log = tmp_path / "social.jsonl"
    log.write_text(
        "\n".join(
            [
                json.dumps(
                    {
                        "date": "2026-07-01",
                        "intraday_scan_index": 0,
                        "symbols": [{"symbol": "AAPL", "rank": 10, "trending_score": 8}],
                    }
                ),
                json.dumps(
                    {
                        "date": "2026-07-02",
                        "intraday_scan_index": 2,
                        "symbols": [{"symbol": "AAPL", "rank": 8, "trending_score": 11}],
                    }
                ),
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    context = scanner.load_social_context(log, days=7, today="2026-07-02")

    assert context["AAPL"]["social_day_count"] == 2
    assert context["AAPL"]["social_slot_count"] == 2
    assert context["AAPL"]["best_social_rank"] == 8


def test_build_report_is_read_only_and_ranks_candidates(monkeypatch, tmp_path: Path) -> None:
    def fake_fetch(symbol: str, lookback_days: int = 120):
        if symbol == "AAPL":
            return _frame([100 + i for i in range(70)], [8_000_000] * 49 + [10_000_000] * 20 + [35_000_000])
        return _frame([50] * 70, [2_000_000] * 70)

    monkeypatch.setattr(scanner, "fetch_ohlcv", fake_fetch)
    monkeypatch.setattr(scanner, "data_source", lambda: "test")

    report = scanner.build_report(
        symbols=["MSFT", "AAPL"],
        social_context={"AAPL": {"social_slot_count": 3, "best_social_rank": 8}},
        log_path=tmp_path / "deep.jsonl",
        report_path=tmp_path / "deep.json",
    )

    assert report["execution_enabled"] is False
    assert report["top_candidates"][0]["symbol"] == "AAPL"
    assert report["top_candidates"][0]["recommendation"] == "shadow_review_candidate"


def test_build_report_dedupes_symbol_universe(monkeypatch, tmp_path: Path) -> None:
    calls: list[str] = []

    def fake_fetch(symbol: str, lookback_days: int = 120):
        calls.append(symbol)
        return _frame([100 + i for i in range(70)], [10_000_000] * 70)

    monkeypatch.setattr(scanner, "fetch_ohlcv", fake_fetch)
    monkeypatch.setattr(scanner, "data_source", lambda: "test")

    report = scanner.build_report(
        symbols=["AAPL", "MSFT", "AAPL"],
        social_context={},
        log_path=tmp_path / "deep.jsonl",
        report_path=tmp_path / "deep.json",
    )

    assert calls == ["AAPL", "MSFT"]
    assert report["symbol_count"] == 2


def test_scan_symbol_marks_data_failures_unavailable_not_error(monkeypatch) -> None:
    def fail_fetch(symbol: str, lookback_days: int = 160):
        raise ValueError("No Alpaca price data")

    monkeypatch.setattr(scanner, "fetch_ohlcv", fail_fetch)

    row = scanner.scan_symbol("SQ")

    assert row["symbol"] == "SQ"
    assert row["status"] == "unavailable"
    assert "No Alpaca price data" in row["warning"]


def test_default_universe_includes_competitor_alert_tickers() -> None:
    for symbol in [
        "MCD",
        "ABBV",
        "AAPL",
        "LTH",
        "MSFT",
        "L",
        "IBM",
        "TDOC",
        "BMY",
        "GOOGL",
        "KVUE",
        "JNJ",
        "HOOD",
        "AUR",
        "PATH",
        "REGN",
        "RDDT",
        "LYFT",
        "SPY",
        "QQQ",
        "TSLA",
        "NVDA",
    ]:
        assert symbol in scanner.DEFAULT_UNIVERSE

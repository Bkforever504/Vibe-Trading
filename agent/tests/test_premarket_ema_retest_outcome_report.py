from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd


def _bars(day: str, closes: list[float]) -> pd.DataFrame:
    index = pd.date_range(f"{day} 11:01", periods=len(closes), freq="1min", tz="America/New_York")
    return pd.DataFrame(
        {
            "open": closes,
            "high": [value + 0.1 for value in closes],
            "low": [value - 0.1 for value in closes],
            "close": closes,
            "volume": [1000] * len(closes),
        },
        index=index,
    )


def _report(day: str, symbol: str, bull: int, bear: int, *, bull_stack: bool, bear_stack: bool) -> dict:
    action = "watch_call_retest" if bull >= 7 else "watch_put_retest" if bear >= 7 else "stand_aside"
    return {
        "date": day,
        "timestamp": f"{day}T15:00:00Z",
        "scans": [
            {
                "status": "ok",
                "symbol": symbol,
                "action": action,
                "latest_close": 100.0,
                "bull_score": bull,
                "bear_score": bear,
                "features": {
                    "bull_stack_13_48_200": bull_stack,
                    "bear_stack_13_48_200": bear_stack,
                },
            }
        ],
    }


def test_call_and_put_signals_use_directional_returns() -> None:
    from scripts.premarket_ema_retest_outcome_report import evaluate_observation

    call = _report("2026-07-01", "SPY", 8, 2, bull_stack=True, bear_stack=False)
    put = _report("2026-07-02", "QQQ", 2, 8, bull_stack=False, bear_stack=True)

    call_result = evaluate_observation(call, call["scans"][0], _bars("2026-07-01", [100.2, 101.0]))
    put_result = evaluate_observation(put, put["scans"][0], _bars("2026-07-02", [99.8, 99.0]))

    assert call_result is not None and call_result["cohort"] == "signal"
    assert put_result is not None and put_result["cohort"] == "signal"
    assert call_result["net_return_bps"] == 98.0
    assert put_result["net_return_bps"] == 98.0


def test_high_score_without_aligned_stack_is_control() -> None:
    from scripts.premarket_ema_retest_outcome_report import evaluate_observation

    report = _report("2026-07-01", "SPY", 8, 2, bull_stack=False, bear_stack=False)
    result = evaluate_observation(report, report["scans"][0], _bars("2026-07-01", [100.2, 101.0]))

    assert result is not None
    assert result["cohort"] == "control"
    assert result["direction"] == "call"


def test_build_report_deduplicates_and_excludes_replayed_dates(tmp_path: Path) -> None:
    from scripts.premarket_ema_retest_outcome_report import build_report

    source = tmp_path / "signals.jsonl"
    rows = [
        _report("2026-07-01", "SPY", 8, 2, bull_stack=True, bear_stack=False),
        _report("2026-07-01", "SPY", 8, 2, bull_stack=True, bear_stack=False),
        {
            **_report("2026-07-02", "SPY", 8, 2, bull_stack=True, bear_stack=False),
            "timestamp": "2026-07-19T15:00:00Z",
        },
    ]
    source.write_text("\n".join(json.dumps(row) for row in rows), encoding="utf-8")

    report = build_report(source, fetcher=lambda symbol, day: _bars(day, [100.5, 101.0]))

    assert report["deduplicated_observation_count"] == 1
    assert report["excluded_replay_or_unusable_count"] == 1
    assert report["signal"]["count"] == 1


def test_report_compares_signals_with_directional_controls(tmp_path: Path) -> None:
    from scripts.premarket_ema_retest_outcome_report import build_report

    source = tmp_path / "signals.jsonl"
    rows = [
        _report("2026-07-01", "SPY", 8, 2, bull_stack=True, bear_stack=False),
        _report("2026-07-02", "SPY", 6, 2, bull_stack=False, bear_stack=False),
    ]
    source.write_text("\n".join(json.dumps(row) for row in rows), encoding="utf-8")

    def fetcher(symbol: str, day: str) -> pd.DataFrame:
        return _bars(day, [100.2, 101.0] if day.endswith("01") else [99.8, 99.5])

    report = build_report(source, fetcher=fetcher)

    assert report["signal"]["expectancy_net_bps"] == 98.0
    assert report["control"]["expectancy_net_bps"] == -52.0
    assert report["signal_vs_control_expectancy_lift_bps"] == 150.0
    assert report["review_eligible"] is False
    assert "fewer_than_30_trading_days" in report["promotion_blockers"]
    assert "signal_expectancy_confidence_interval_not_above_zero" in report["promotion_blockers"]
    assert report["profitability_confidence_score"] < 9


def test_neutral_control_has_no_fabricated_direction() -> None:
    from scripts.premarket_ema_retest_outcome_report import evaluate_observation

    report = _report("2026-07-01", "SPY", 5, 5, bull_stack=False, bear_stack=False)
    result = evaluate_observation(report, report["scans"][0], _bars("2026-07-01", [100.2, 101.0]))

    assert result is not None
    assert result["status"] == "neutral_no_direction"
    assert result["direction"] is None


def test_default_fetch_hook_imports_repo_scanner(monkeypatch) -> None:
    from scripts import premarket_ema_retest_outcome_report as evaluator
    from scripts import premarket_ema_retest_shadow_logger as scanner

    expected = _bars("2026-07-01", [100.2, 101.0])
    monkeypatch.setattr(scanner, "fetch_intraday_bars_alpaca", lambda symbol, trading_day: expected)

    result = evaluator._fetch_bars("SPY", "2026-07-01")

    assert result is expected

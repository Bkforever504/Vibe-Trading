from __future__ import annotations

import json
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd

from scripts import spy_1200_daily_aligned_shadow as lane

NY = ZoneInfo("America/New_York")


def bullish_session(day: date) -> pd.DataFrame:
    index = pd.date_range(f"{day} 09:30", f"{day} 11:59", freq="1min", tz=NY)
    close = [100.0 + position * 0.02 for position in range(len(index))]
    frame = pd.DataFrame(
        {
            "open": [value - 0.01 for value in close],
            "high": [value + 0.04 for value in close],
            "low": [value - 0.04 for value in close],
            "close": close,
            "volume": 1000.0,
        },
        index=index,
    )
    work = frame.copy()
    typical = (work["high"] + work["low"] + work["close"]) / 3.0
    work["vwap"] = (typical * work["volume"]).cumsum() / work["volume"].cumsum()
    work["ema50"] = work["close"].ewm(span=50, adjust=False).mean()
    frame.iloc[-3, frame.columns.get_loc("low")] = min(work["vwap"].iloc[-3], work["ema50"].iloc[-3])
    return frame


def test_frozen_signal_requires_complete_150_bars_and_daily_alignment() -> None:
    day = date(2026, 7, 27)
    frame = bullish_session(day)
    signal = lane.evaluate_frozen_signal(frame, {"daily": "bullish"}, day)
    assert signal is not None
    assert signal["direction"] == "bull"
    assert signal["bar_count"] == 150
    assert lane.evaluate_frozen_signal(frame.iloc[:-1], {"daily": "bullish"}, day) is None
    assert lane.evaluate_frozen_signal(frame, {"daily": "mixed"}, day) is None


def test_contract_selection_is_frozen_and_deterministic() -> None:
    candidates = [
        {
            "option_symbol": "SPY260729C00600000",
            "delta": 0.50,
            "bid": 1.00,
            "ask": 1.10,
        },
        {
            "option_symbol": "SPY260727C00601000",
            "delta": 0.48,
            "bid": 0.90,
            "ask": 1.00,
        },
        {
            "option_symbol": "SPY260727C00600000",
            "delta": 0.50,
            "bid": 1.00,
            "ask": 1.05,
        },
        {
            "option_symbol": "SPY260727P00600000",
            "delta": -0.50,
            "bid": 1.00,
            "ask": 1.05,
        },
    ]
    selected = lane.select_tracking_contract(
        candidates,
        direction="bull",
        spot=600.2,
        trading_day=date(2026, 7, 27),
    )
    assert selected is not None
    assert selected["option_symbol"] == "SPY260727C00600000"
    assert selected["quote_scope"] == "indicative_modified_not_opra_nbbo"


def test_contract_selection_rejects_wide_or_wrong_delta() -> None:
    candidates = [
        {"option_symbol": "SPY260727C00600000", "delta": 0.20, "bid": 1.0, "ask": 1.1},
        {"option_symbol": "SPY260727C00601000", "delta": 0.50, "bid": 0.5, "ask": 1.0},
    ]
    assert lane.select_tracking_contract(
        candidates,
        direction="bull",
        spot=600,
        trading_day=date(2026, 7, 27),
    ) is None


def test_outcome_uses_underlying_direction_and_option_ask_to_bid() -> None:
    signal = {
        "signal_id": "s1",
        "trading_date": "2026-07-27",
        "signal": {"direction": "bear"},
        "underlying_entry": {"price": 600.0},
        "selected_contract": {"option_symbol": "SPY260727P00600000", "ask": 1.00},
    }
    outcome = lane.build_outcome(
        signal,
        exit_underlying={"price": 594.0},
        exit_option_record={"quote": {"bid": 1.20}},
        resolved_at=datetime(2026, 7, 27, 13, 0, tzinfo=NY),
    )
    assert outcome is not None
    assert outcome["underlying_gross_bps"] == 100.0
    assert outcome["underlying_net_bps"] == 98.0
    assert outcome["option_ask_to_bid_return_pct"] == 20.0


def test_summary_counts_independent_dates_and_quote_coverage() -> None:
    rows = [
        {"event": "signal", "lane": lane.LANE, "trading_date": "2026-07-27"},
        {"event": "signal", "lane": lane.LANE, "trading_date": "2026-07-27"},
        {
            "event": "outcome",
            "lane": lane.LANE,
            "trading_date": "2026-07-27",
            "underlying_net_bps": 5.0,
            "option_ask_to_bid_return_pct": None,
        },
    ]
    summary = lane.summarize(rows)
    assert summary["signal_dates"] == 1
    assert summary["resolved_independent_dates"] == 1
    assert summary["option_quote_coverage"] == 0.0
    assert summary["ready_for_human_review"] is False


def test_moving_block_interval_is_withheld_until_twenty_dates() -> None:
    short = lane.moving_block_mean_ci(pd.Series(range(19), dtype=float).to_numpy())
    enough = lane.moving_block_mean_ci(pd.Series(range(20), dtype=float).to_numpy())
    assert short["status"] == "insufficient_n"
    assert enough["status"] == "ok"
    assert enough["lower"] < enough["upper"]


def test_frozen_rule_drift_audit_accepts_compliant_records() -> None:
    signal = {
        "event": "signal",
        "lane": lane.LANE,
        "signal_id": "s1",
        "trading_date": "2026-07-27",
        "captured_at": "2026-07-27T12:03:00-04:00",
        "option_quote_scope": lane.OPTION_QUOTE_SCOPE,
        "signal": {
            "checkpoint_et": "12:00",
            "bar_count": 150,
            "signal_rule": "production_parity_vwap_ema50_9_of_9_daily_aligned",
            "weekly_state": "bullish",
            "monthly_state": "mixed",
        },
    }
    outcome = {
        "event": "outcome",
        "lane": lane.LANE,
        "signal_id": "s1",
        "trading_date": "2026-07-27",
        "resolved_at": "2026-07-27T13:03:00-04:00",
        "direction": "bull",
        "underlying_net_bps": 5.0,
        "option_quote_scope": lane.OPTION_QUOTE_SCOPE,
    }
    summary = lane.summarize([signal, outcome])
    assert summary["frozen_rule_drift_count"] == 0
    assert summary["underlying_by_direction"]["bull"]["count"] == 1
    assert "weekly=bullish|monthly=mixed" in summary["underlying_by_htf_context"]


def test_duplicate_signal_is_skipped_without_network(tmp_path: Path) -> None:
    log = tmp_path / "lane.jsonl"
    existing = {
        "event": "signal",
        "lane": lane.LANE,
        "signal_id": "existing",
        "trading_date": "2026-07-27",
    }
    log.write_text(json.dumps(existing) + "\n", encoding="utf-8")
    result = lane.run_signal(datetime(2026, 7, 27, 12, 0, tzinfo=NY), log_path=log)
    assert result["status"] == "duplicate_skipped"


def test_auto_phase_fails_closed_outside_frozen_windows(tmp_path: Path) -> None:
    result = lane.run(
        "auto",
        now_et=datetime(2026, 7, 27, 14, 0, tzinfo=NY),
        log_path=tmp_path / "empty.jsonl",
    )
    assert result["status"] == "outside_frozen_window"


def test_signal_data_failure_is_fail_closed_and_retryable(tmp_path: Path) -> None:
    def failed_fetch(*_args, **_kwargs):
        raise TimeoutError("provider unavailable")

    log = tmp_path / "lane.jsonl"
    result = lane.run_signal(
        datetime(2026, 7, 27, 12, 3, tzinfo=NY),
        intraday_fetcher=failed_fetch,
        log_path=log,
    )
    assert result["status"] == "blocked_signal_data_error"
    assert result["error_type"] == "TimeoutError"
    assert not log.exists()

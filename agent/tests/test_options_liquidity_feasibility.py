from __future__ import annotations

import json
import math
from datetime import date
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch
import sys

import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.options_liquidity_feasibility import (
    OI_MIN,
    PRICE_MAX,
    QUALIFY_SCORE,
    SPREAD_MAX_PCT,
    _error_result,
    build_report,
    check_symbol,
    load_last_report,
    log_report,
)

TODAY = date(2026, 7, 2)
TODAY_STR = "2026-07-02"
NEXT_WEEK = "2026-07-09"


# ---------------------------------------------------------------------------
# Helpers to build fake yfinance chain data
# ---------------------------------------------------------------------------

def _make_chain(calls_oi: int = 2000, puts_oi: int = 1500, bid: float = 2.50, ask: float = 2.70) -> SimpleNamespace:
    calls = pd.DataFrame({
        "strike":        [100.0, 105.0, 110.0],
        "openInterest":  [calls_oi, calls_oi // 2, calls_oi // 4],
        "bid":           [bid, bid - 0.1, bid - 0.2],
        "ask":           [ask, ask - 0.1, ask - 0.2],
        "lastPrice":     [(bid + ask) / 2, 0.0, 0.0],
        "volume":        [1000, 500, 250],
    })
    puts = pd.DataFrame({
        "strike":       [95.0, 100.0, 105.0],
        "openInterest": [puts_oi // 4, puts_oi, puts_oi // 2],
        "bid":          [bid - 0.3, bid, bid - 0.1],
        "ask":          [ask - 0.3, ask, ask - 0.1],
        "lastPrice":    [0.0, (bid + ask) / 2, 0.0],
        "volume":       [250, 1000, 500],
    })
    return SimpleNamespace(calls=calls, puts=puts)


def _mock_ticker(
    options: tuple[str, ...],
    spot: float = 100.0,
    calls_oi: int = 2000,
    puts_oi: int = 1500,
    bid: float = 2.50,
    ask: float = 2.70,
) -> MagicMock:
    t = MagicMock()
    t.options = options
    t.option_chain.return_value = _make_chain(calls_oi, puts_oi, bid, ask)
    fi = SimpleNamespace(last_price=spot, previous_close=spot)
    t.fast_info = fi
    return t


# ---------------------------------------------------------------------------
# _error_result
# ---------------------------------------------------------------------------

def test_error_result_sets_not_eligible():
    r = _error_result("FOO", "no_chain")
    assert r["flip_shadow_eligible"] is False
    assert r["score"] == 0
    assert r["verdict"] == "not_qualified"
    assert r["symbol"] == "FOO"


# ---------------------------------------------------------------------------
# check_symbol — qualified path
# ---------------------------------------------------------------------------

def test_qualified_symbol_returns_score_5():
    with patch("scripts.options_liquidity_feasibility.yf.Ticker") as MockTicker:
        MockTicker.return_value = _mock_ticker(
            options=(TODAY_STR, NEXT_WEEK),
            spot=100.0, calls_oi=3000, puts_oi=2000, bid=2.50, ask=2.70,
        )
        r = check_symbol("QQQ", today=TODAY)
    assert r["status"] == "ok"
    assert r["score"] == 5
    assert r["verdict"] == "qualified"
    assert r["flip_shadow_eligible"] is True
    assert r["has_0dte"] is True
    assert r["has_weekly"] is True
    assert r["oi_ok"] is True
    assert r["volume_ok"] is True
    assert r["spread_ok"] is True
    assert r["price_ok"] is True


def test_criteria_dict_matches_boolean_fields():
    with patch("scripts.options_liquidity_feasibility.yf.Ticker") as MockTicker:
        MockTicker.return_value = _mock_ticker(
            options=(TODAY_STR, NEXT_WEEK), spot=100.0,
        )
        r = check_symbol("SPY", today=TODAY)
    c = r["criteria"]
    assert c["0dte_available"] == r["has_0dte"]
    assert c["weekly_available"] == r["has_weekly"]
    assert c["oi_ok"] == r["oi_ok"]
    assert c["volume_ok"] == r["volume_ok"]
    assert c["spread_ok"] == r["spread_ok"]
    assert c["price_ok"] == r["price_ok"]


# ---------------------------------------------------------------------------
# check_symbol — individual criterion failures
# ---------------------------------------------------------------------------

def test_no_0dte_misses_one_point():
    with patch("scripts.options_liquidity_feasibility.yf.Ticker") as MockTicker:
        MockTicker.return_value = _mock_ticker(
            options=(NEXT_WEEK,),  # no today
            spot=100.0, calls_oi=2000, puts_oi=2000, bid=2.50, ask=2.70,
        )
        r = check_symbol("X", today=TODAY)
    assert r["has_0dte"] is False
    assert r["has_weekly"] is True
    assert r["score"] == 4  # misses 0DTE only → still qualified
    assert r["flip_shadow_eligible"] is True


def test_low_oi_scores_oi_false():
    with patch("scripts.options_liquidity_feasibility.yf.Ticker") as MockTicker:
        MockTicker.return_value = _mock_ticker(
            options=(TODAY_STR, NEXT_WEEK),
            spot=100.0, calls_oi=50, puts_oi=50,  # below OI_MIN
            bid=2.50, ask=2.70,
        )
        r = check_symbol("RIVN", today=TODAY)
    assert r["oi_ok"] is False
    assert r["atm_oi_min"] == 50
    # score = 4 (misses only OI): 0DTE + weekly + spread + price still pass
    assert r["score"] == QUALIFY_SCORE


def test_nan_open_interest_scores_oi_false_without_crashing():
    chain = _make_chain(calls_oi=2000, puts_oi=1500)
    chain.calls.loc[0, "openInterest"] = math.nan
    chain.puts.loc[1, "openInterest"] = math.nan
    ticker = MagicMock()
    ticker.options = (TODAY_STR, NEXT_WEEK)
    ticker.option_chain.return_value = chain
    ticker.fast_info = SimpleNamespace(last_price=100.0, previous_close=100.0)

    with patch("scripts.options_liquidity_feasibility.yf.Ticker", return_value=ticker):
        r = check_symbol("NANOI", today=TODAY)

    assert r["status"] == "ok"
    assert r["atm_oi_calls"] == 0
    assert r["atm_oi_puts"] == 0
    assert r["oi_ok"] is False


def test_wide_spread_scores_spread_false():
    # bid=1.00, ask=3.00 → spread=200%, mid=2.00 → spread_pct=100%
    with patch("scripts.options_liquidity_feasibility.yf.Ticker") as MockTicker:
        MockTicker.return_value = _mock_ticker(
            options=(TODAY_STR, NEXT_WEEK),
            spot=100.0, calls_oi=2000, puts_oi=2000,
            bid=1.00, ask=3.00,
        )
        r = check_symbol("WIDE", today=TODAY)
    assert r["spread_ok"] is False
    assert r["atm_spread_pct"] > SPREAD_MAX_PCT


def test_expensive_contract_scores_price_false():
    # $8/share = $800/contract — above PRICE_MAX
    with patch("scripts.options_liquidity_feasibility.yf.Ticker") as MockTicker:
        MockTicker.return_value = _mock_ticker(
            options=(TODAY_STR, NEXT_WEEK),
            spot=500.0, calls_oi=2000, puts_oi=2000,
            bid=7.50, ask=8.00,
        )
        r = check_symbol("EXPENSIVE", today=TODAY)
    assert r["price_ok"] is False
    assert r["atm_price"] > PRICE_MAX


def test_illiquid_put_side_blocks_two_sided_spread_gate():
    chain = _make_chain()
    chain.puts.loc[1, "bid"] = 0.50
    chain.puts.loc[1, "ask"] = 2.50
    ticker = MagicMock()
    ticker.options = (TODAY_STR, NEXT_WEEK)
    ticker.option_chain.return_value = chain
    ticker.fast_info = SimpleNamespace(last_price=100.0, previous_close=100.0)

    with patch("scripts.options_liquidity_feasibility.yf.Ticker", return_value=ticker):
        r = check_symbol("ONESIDED", today=TODAY)

    assert r["atm_call_spread_pct"] <= SPREAD_MAX_PCT
    assert r["atm_put_spread_pct"] > SPREAD_MAX_PCT
    assert r["spread_ok"] is False


def test_low_contract_volume_fails_depth_criterion():
    chain = _make_chain()
    chain.calls.loc[0, "volume"] = 10
    chain.puts.loc[1, "volume"] = 20
    ticker = MagicMock()
    ticker.options = (TODAY_STR, NEXT_WEEK)
    ticker.option_chain.return_value = chain
    ticker.fast_info = SimpleNamespace(last_price=100.0, previous_close=100.0)

    with patch("scripts.options_liquidity_feasibility.yf.Ticker", return_value=ticker):
        r = check_symbol("NOVOLUME", today=TODAY)

    assert r["oi_ok"] is True
    assert r["volume_ok"] is False
    assert r["score"] == 4


def test_no_option_chain_returns_error():
    with patch("scripts.options_liquidity_feasibility.yf.Ticker") as MockTicker:
        t = MagicMock()
        t.options = ()
        MockTicker.return_value = t
        r = check_symbol("NOCHAIN", today=TODAY)
    assert r["status"] == "error"
    assert r["flip_shadow_eligible"] is False


def test_ticker_fetch_exception_returns_error():
    with patch("scripts.options_liquidity_feasibility.yf.Ticker") as MockTicker:
        MockTicker.side_effect = RuntimeError("network down")
        r = check_symbol("BOOM", today=TODAY)
    assert r["status"] == "error"
    assert r["flip_shadow_eligible"] is False


# ---------------------------------------------------------------------------
# build_report
# ---------------------------------------------------------------------------

def test_build_report_structure():
    with patch("scripts.options_liquidity_feasibility.check_symbol") as mock_check:
        mock_check.side_effect = lambda sym, today: {
            "symbol": sym, "score": 5, "verdict": "qualified",
            "flip_shadow_eligible": True, "status": "ok",
            "criteria": {"0dte_available": True, "weekly_available": True, "oi_ok": True, "spread_ok": True, "price_ok": True},
        }
        report = build_report(["QQQ", "SPY"], today=TODAY)
    assert report["execution_mode"] == "read_only"
    assert report["summary"]["total"] == 2
    assert report["summary"]["qualified"] == 2
    assert "QQQ" in report["qualified_symbols"]
    assert len(report["results"]) == 2


def test_build_report_separates_borderline():
    def _score_result(sym, today):
        score = 3 if sym == "BORDER" else 5
        verdict = "borderline" if score == 3 else "qualified"
        return {"symbol": sym, "score": score, "verdict": verdict,
                "flip_shadow_eligible": score >= QUALIFY_SCORE, "status": "ok",
                "criteria": {}}
    with patch("scripts.options_liquidity_feasibility.check_symbol", side_effect=_score_result):
        report = build_report(["QQQ", "BORDER"], today=TODAY)
    assert report["summary"]["borderline"] == 1
    assert "BORDER" in report["borderline_symbols"]
    assert "QQQ" in report["qualified_symbols"]


# ---------------------------------------------------------------------------
# log_report / load_last_report
# ---------------------------------------------------------------------------

def test_log_and_reload(tmp_path):
    log = tmp_path / "feas.jsonl"
    report = {"date": TODAY_STR, "execution_mode": "read_only", "summary": {}, "results": [], "qualified_symbols": []}
    log_report(report, log_path=log)
    loaded = load_last_report(log_path=log)
    assert loaded is not None
    assert loaded["date"] == TODAY_STR


def test_log_deduplicates_by_date(tmp_path):
    log = tmp_path / "feas.jsonl"
    r1 = {"date": TODAY_STR, "qualified_symbols": ["QQQ"]}
    r2 = {"date": TODAY_STR, "qualified_symbols": ["QQQ", "META"]}
    log_report(r1, log_path=log)
    log_report(r2, log_path=log)
    lines = [l for l in log.read_text().splitlines() if l.strip()]
    assert len(lines) == 1
    assert json.loads(lines[0])["qualified_symbols"] == ["QQQ", "META"]


def test_log_preserves_different_dates(tmp_path):
    log = tmp_path / "feas.jsonl"
    r1 = {"date": "2026-07-01", "qualified_symbols": ["QQQ"]}
    r2 = {"date": TODAY_STR, "qualified_symbols": ["META"]}
    log_report(r1, log_path=log)
    log_report(r2, log_path=log)
    lines = [l for l in log.read_text().splitlines() if l.strip()]
    assert len(lines) == 2

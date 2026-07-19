"""Tests for bull call spread fallback in find_bull_trend_day."""
from pathlib import Path
from unittest.mock import patch
import pandas as pd


def _make_chain(calls_data: list[dict], puts_data: list[dict] | None = None):
    """Return a mock option_chain result with calls and puts DataFrames."""
    import collections
    Chain = collections.namedtuple("Chain", ["calls", "puts"])
    calls_df = pd.DataFrame(calls_data) if calls_data else pd.DataFrame(columns=["strike", "ask", "bid", "lastPrice"])
    puts_df  = pd.DataFrame(puts_data  or [])
    return Chain(calls=calls_df, puts=puts_df)


def _bull_signal(score: float = 9.0) -> dict:
    return {
        "score": score,
        "close": 530.0,
        "vwap": 528.0,
        "ema50": 525.0,
        "vwap_distance": 0.004,
        "reasons": ["above VWAP", "above 50EMA", "not extended from VWAP"],
    }


# ---------------------------------------------------------------------------
# _bull_call_spread unit tests
# ---------------------------------------------------------------------------

def test_bull_call_spread_returns_none_when_chain_empty():
    from strategies.flip_bot import _bull_call_spread
    import yfinance as yf

    ticker_mock = type("T", (), {"option_chain": lambda self, exp: _make_chain([])})()
    with patch.object(yf, "Ticker", return_value=ticker_mock):
        result = _bull_call_spread("SPY", "2026-07-18", 530.0, 200.0)
    assert result is None


def test_bull_call_spread_returns_narrowest_fit():
    from strategies.flip_bot import _bull_call_spread
    import yfinance as yf

    calls = [
        {"strike": 530.0, "ask": 3.00, "bid": 2.80, "lastPrice": 2.90},  # ATM long
        {"strike": 532.0, "ask": 2.20, "bid": 2.00, "lastPrice": 2.10},  # width=2 short
        {"strike": 535.0, "ask": 1.50, "bid": 1.30, "lastPrice": 1.40},  # width=5 short
    ]
    ticker_mock = type("T", (), {"option_chain": lambda self, exp: _make_chain(calls)})()
    with patch.object(yf, "Ticker", return_value=ticker_mock):
        # max_risk=200 per contract → net_debit must be ≤ 2.00
        # width=2: 3.00 - 2.00 = 1.00 → fits → should pick this
        result = _bull_call_spread("SPY", "2026-07-18", 530.0, 200.0)
    assert result is not None
    net_debit, long_strike, short_strike = result
    assert long_strike == 530.0
    assert short_strike == 532.0
    assert net_debit == 1.00


def test_bull_call_spread_returns_none_when_no_width_fits():
    from strategies.flip_bot import _bull_call_spread
    import yfinance as yf

    calls = [
        {"strike": 530.0, "ask": 5.00, "bid": 4.80, "lastPrice": 4.90},
        {"strike": 532.0, "ask": 4.50, "bid": 4.30, "lastPrice": 4.40},
    ]
    ticker_mock = type("T", (), {"option_chain": lambda self, exp: _make_chain(calls)})()
    with patch.object(yf, "Ticker", return_value=ticker_mock):
        # net_debit=0.50 * 100=50 which is > max_risk=30
        result = _bull_call_spread("SPY", "2026-07-18", 530.0, 30.0)
    assert result is None


# ---------------------------------------------------------------------------
# find_bull_trend_day integration tests
# ---------------------------------------------------------------------------

def _patch_bull_prereqs(monkeypatch, *, now_hour=10, vix_ok=True, valid_signals=3):
    """Patch all I/O-bound prereqs for find_bull_trend_day."""
    from strategies import flip_bot
    from zoneinfo import ZoneInfo
    from datetime import datetime

    fake_now = datetime(2026, 6, 27, now_hour, 0, tzinfo=ZoneInfo("America/New_York"))
    monkeypatch.setattr(flip_bot, "_now_et", lambda: fake_now)
    monkeypatch.setattr(flip_bot, "_fetch_vix_term_structure", lambda: {"regime": "contango", "ratio": 1.05})
    monkeypatch.setattr(flip_bot, "_vix_term_structure_direction_ok", lambda dir, reg: vix_ok)

    scores = [9.0] * valid_signals + [0.0] * (3 - valid_signals)
    def fake_bull_signal(hist, sym="?"):
        idx = ["SPY", "QQQ", "IWM"].index(sym) if sym in ["SPY", "QQQ", "IWM"] else 0
        s = scores[idx]
        if s < flip_bot.BEAR_TREND_MIN_CONFIDENCE:
            return None
        return _bull_signal(score=s)

    monkeypatch.setattr(flip_bot, "_intraday_bars", lambda sym: pd.DataFrame({"Close": [1.0] * 30}))
    monkeypatch.setattr(flip_bot, "_vwap_50ema_bull_signal", fake_bull_signal)
    monkeypatch.setattr(flip_bot, "_option_bid_ask_spread_cents", lambda occ: 10)


def test_find_bull_trend_day_single_call_when_affordable(monkeypatch):
    from strategies import flip_bot

    _patch_bull_prereqs(monkeypatch)
    monkeypatch.setattr(flip_bot, "_atm_option", lambda sym, right: ("SPY260627C00530000", 530.0, 1.00, "2026-06-27"))

    result = flip_bot.find_bull_trend_day(account=100_000)

    assert result is not None
    assert result["strategy"] == "bull_trend"
    assert result["right"] == "CALL"
    assert result["option_symbol"] == "SPY260627C00530000"
    assert result["contracts"] >= 1
    assert "spread_cents" in result


def test_find_bull_trend_day_spread_when_call_too_expensive(monkeypatch):
    from strategies import flip_bot
    import yfinance as yf

    _patch_bull_prereqs(monkeypatch)
    # ATM call at $50 → exceeds 2% of $1000 account ($20 budget)
    monkeypatch.setattr(flip_bot, "_atm_option", lambda sym, right: ("SPY260627C00530000", 530.0, 50.0, "2026-06-27"))

    calls = [
        {"strike": 530.0, "ask": 50.00, "bid": 49.80, "lastPrice": 49.90},
        {"strike": 532.0, "ask": 49.00, "bid": 48.80, "lastPrice": 48.90},  # width=2: net=1.00*100=100 > 20
        {"strike": 533.0, "ask": 49.00, "bid": 48.80, "lastPrice": 48.90},
        {"strike": 535.0, "ask": 49.00, "bid": 48.80, "lastPrice": 48.90},
        {"strike": 537.0, "ask": 49.00, "bid": 48.80, "lastPrice": 48.90},
        {"strike": 540.0, "ask": 49.50, "bid": 49.30, "lastPrice": 49.40},  # width=10: net=0.50*100=50 > 20
    ]
    ticker_mock = type("T", (), {"option_chain": lambda self, exp: _make_chain(calls)})()
    monkeypatch.setattr(yf, "Ticker", lambda sym: ticker_mock)

    # Account too small for any spread either → should return None
    result = flip_bot.find_bull_trend_day(account=1_000)
    assert result is None


def test_find_bull_trend_day_spread_fits_budget(monkeypatch):
    from strategies import flip_bot
    import yfinance as yf

    _patch_bull_prereqs(monkeypatch)
    # Single call at $20 exceeds 2% of $500 ($10), but spread net_debit=$0.05 fits
    monkeypatch.setattr(flip_bot, "_atm_option", lambda sym, right: ("SPY260627C00530000", 530.0, 20.0, "2026-06-27"))

    calls = [
        {"strike": 530.0, "ask": 20.00, "bid": 19.80, "lastPrice": 19.90},
        {"strike": 532.0, "ask": 20.00, "bid": 19.95, "lastPrice": 19.97},  # short_bid=19.95 → net=0.05*100=5 ≤ 10
    ]
    ticker_mock = type("T", (), {"option_chain": lambda self, exp: _make_chain(calls)})()
    monkeypatch.setattr(yf, "Ticker", lambda sym: ticker_mock)

    result = flip_bot.find_bull_trend_day(account=500)

    assert result is not None
    assert result["strategy"] == "bull_trend_spread"
    assert result["right"] == "CALL"
    assert result["short_option_symbol"] is not None
    assert result["short_strike"] == 532.0
    assert result["max_gain"] > 0
    assert result["max_loss"] > 0
    assert result["contracts"] >= 1


def test_find_bull_trend_day_returns_none_when_vix_blocks(monkeypatch):
    from strategies import flip_bot

    _patch_bull_prereqs(monkeypatch, vix_ok=False)

    result = flip_bot.find_bull_trend_day(account=100_000)
    assert result is None


def test_find_bull_trend_day_returns_none_insufficient_signals(monkeypatch):
    from strategies import flip_bot

    _patch_bull_prereqs(monkeypatch, valid_signals=1)
    monkeypatch.setattr(flip_bot, "_atm_option", lambda sym, right: ("SPY260627C00530000", 530.0, 1.00, "2026-06-27"))

    result = flip_bot.find_bull_trend_day(account=100_000)
    assert result is None

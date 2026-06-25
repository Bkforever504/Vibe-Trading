from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _bars(closes: list[float]) -> pd.DataFrame:
    return pd.DataFrame({
        "High": [c + 0.5 for c in closes],
        "Low": [c - 0.5 for c in closes],
        "Close": closes,
        "Volume": [1000 + i * 10 for i in range(len(closes))],
    })


def test_bear_trend_candidate_uses_vwap_and_50ema(monkeypatch) -> None:
    from datetime import datetime, timezone, timedelta
    from strategies import flip_bot

    # Fix clock to 10:30 AM ET so cutoff check passes regardless of real time
    _et = timezone(timedelta(hours=-4))
    monkeypatch.setattr(flip_bot, "_now_et", lambda: datetime(2026, 6, 24, 10, 30, tzinfo=_et))

    closes = [100 - i * 0.05 for i in range(65)] + [97.0, 97.1, 97.0, 96.9, 96.8]
    monkeypatch.setattr(flip_bot, "_intraday_bars", lambda symbol: _bars(closes))
    monkeypatch.setattr(flip_bot, "_atm_option", lambda sym, right: ("SPY260624P00730000", 730.0, 0.20, "2026-06-24"))

    setup = flip_bot.find_bear_trend_day(5000.0)

    assert setup is not None
    assert setup["strategy"] == "bear_trend"
    assert setup["symbol"] == "SPY"
    assert setup["right"] == "PUT"
    assert setup["contracts"] == 5
    assert setup["confidence"] >= 8
    assert "VWAP" in setup["catalyst"]
    assert "50EMA" in setup["catalyst"]


def test_bear_trend_candidate_does_not_chase_extended_dump(monkeypatch) -> None:
    from datetime import datetime, timezone, timedelta
    from strategies import flip_bot

    _et = timezone(timedelta(hours=-4))
    monkeypatch.setattr(flip_bot, "_now_et", lambda: datetime(2026, 6, 24, 10, 30, tzinfo=_et))

    closes = [100 - i * 0.06 for i in range(69)] + [85.0]
    monkeypatch.setattr(flip_bot, "_intraday_bars", lambda symbol: _bars(closes))
    monkeypatch.setattr(flip_bot, "_atm_option", lambda sym, right: ("SPY260624P00730000", 730.0, 0.20, "2026-06-24"))

    assert flip_bot.find_bear_trend_day(5000.0) is None

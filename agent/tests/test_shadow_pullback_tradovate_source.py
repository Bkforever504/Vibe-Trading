from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from strategies.topstep_prop_bot import Candle


def test_fetch_today_1h_can_route_to_tradovate(monkeypatch) -> None:
    from strategies import shadow_pullback_signal as scanner

    expected = [Candle(datetime(2026, 6, 23, 10, 30), 1, 2, 0.5, 1.5, 10)]

    monkeypatch.setenv("MNQ_DATA_SOURCE", "tradovate")
    monkeypatch.setattr(scanner, "fetch_today_1h_tradovate", lambda symbol="MNQ": (expected, 20100.0))

    candles, prior_close = scanner.fetch_today_1h()

    assert candles == expected
    assert prior_close == 20100.0

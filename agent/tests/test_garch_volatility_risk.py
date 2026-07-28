from __future__ import annotations

import math
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def test_size_from_forecast_caps_and_never_levers_up() -> None:
    from scripts import garch_volatility_risk as risk

    assert risk.size_from_forecast(7.5, target_vol=15.0, max_multiplier=1.0) == 1.0
    assert risk.size_from_forecast(30.0, target_vol=15.0, max_multiplier=1.0) == 0.5
    assert risk.size_from_forecast(100.0, target_vol=15.0, min_multiplier=0.25) == 0.25


def test_size_from_forecast_invalid_values_return_minimum() -> None:
    from scripts import garch_volatility_risk as risk

    assert risk.size_from_forecast(None, min_multiplier=0.25) == 0.25
    assert risk.size_from_forecast(0.0, min_multiplier=0.25) == 0.25
    assert risk.size_from_forecast(math.nan, min_multiplier=0.25) == 0.25


def test_classify_regime() -> None:
    from scripts import garch_volatility_risk as risk

    assert risk.classify_regime(None) == "unknown"
    assert risk.classify_regime(20.0) == "calm"
    assert risk.classify_regime(50.0) == "normal"
    assert risk.classify_regime(80.0) == "storm"


def test_build_report_uses_scanner_without_order_side_effects(monkeypatch) -> None:
    from scripts import garch_volatility_risk as risk

    def fake_scan(symbol: str, **kwargs):
        return {
            "symbol": symbol,
            "status": "ok",
            "regime": "storm" if symbol == "SPY" else "normal",
            "position_size_multiplier": 0.4 if symbol == "SPY" else 0.8,
        }

    monkeypatch.setattr(risk, "scan_symbol", fake_scan)
    report = risk.build_report(symbols=["SPY", "IWM"])

    assert report["execution_enabled"] is False
    assert report["summary"]["ok_symbols"] == 2
    assert report["summary"]["storm_symbols"] == ["SPY"]
    assert report["summary"]["minimum_position_size_multiplier"] == 0.4

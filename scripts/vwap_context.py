"""VWAP deviation context for intraday SPY entries.

Fetches today's 1-min bars, computes VWAP and sigma bands.
Gate: SPY within ±0.75σ of VWAP = near fair value = safer for premium selling.

Returns context dict usable as a gate or diagnostic annotation.
"""
from __future__ import annotations

import math
from datetime import date, datetime, timezone
from typing import Any

try:
    import yfinance as yf
except ImportError:
    yf = None  # type: ignore[assignment]


def vwap_context(symbol: str = "SPY", sigma_threshold: float = 0.75) -> dict[str, Any]:
    """Return VWAP deviation context.

    Keys returned:
      vwap, spot, deviation_sigma, within_threshold, bands_1sigma, ok_to_sell
    """
    if yf is None:
        return {"error": "yfinance_unavailable", "ok_to_sell": None}

    try:
        bars = yf.Ticker(symbol).history(period="1d", interval="1m")
    except Exception as exc:
        return {"error": str(exc), "ok_to_sell": None}

    if bars is None or bars.empty:
        return {"error": "no_intraday_bars", "ok_to_sell": None}

    bars = bars.copy()
    typical = (bars["High"] + bars["Low"] + bars["Close"]) / 3.0
    cum_tpv = (typical * bars["Volume"]).cumsum()
    cum_vol = bars["Volume"].cumsum()
    bars["vwap"] = cum_tpv / cum_vol.replace(0, float("nan"))

    vwap = float(bars["vwap"].iloc[-1])
    spot = float(bars["Close"].iloc[-1])

    # Rolling std of typical price (proxy for intraday vol for bands)
    std = float(typical.std()) if len(typical) > 1 else 0.0

    if std <= 0 or not math.isfinite(vwap) or not math.isfinite(spot):
        return {
            "vwap": round(vwap, 2),
            "spot": round(spot, 2),
            "deviation_sigma": None,
            "within_threshold": None,
            "ok_to_sell": None,
            "note": "insufficient_data_for_bands",
        }

    dev = (spot - vwap) / std
    within = abs(dev) <= sigma_threshold

    return {
        "vwap": round(vwap, 2),
        "spot": round(spot, 2),
        "deviation_sigma": round(dev, 3),
        "within_threshold": within,
        "band_1sigma_upper": round(vwap + std, 2),
        "band_1sigma_lower": round(vwap - std, 2),
        "sigma_threshold": sigma_threshold,
        "ok_to_sell": within,
        "generated_at": datetime.now(tz=timezone.utc).isoformat(),
    }


if __name__ == "__main__":
    import json
    print(json.dumps(vwap_context(), indent=2))

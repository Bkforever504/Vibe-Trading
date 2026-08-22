"""IV term structure slope for 0DTE entry gating.

Edge: 0DTE IV > near-term IV means premium is elevated specifically
for same-day expiry — favorable for 0DTE credit spread sellers.

Slope > 0 (0DTE IV premium) = sell signal.
Slope < 0 (0DTE IV discount) = stand aside.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from typing import Any

try:
    import yfinance as yf
except ImportError:
    yf = None  # type: ignore[assignment]


def _atm_iv(symbol: str, expiry: str, spot: float) -> float | None:
    try:
        chain = yf.Ticker(symbol).option_chain(expiry)
        calls = chain.calls
        if calls.empty:
            return None
        strikes = calls["strike"].values
        atm = min(strikes, key=lambda k: abs(k - spot))
        row = calls[calls["strike"] == atm]
        if row.empty:
            return None
        iv = float(row.iloc[0].get("impliedVolatility", 0) or 0)
        return iv if iv > 0 else None
    except Exception:
        return None


def iv_term_structure_context(symbol: str = "SPY") -> dict[str, Any]:
    """Return IV term structure context for 0DTE gating.

    Keys: iv_0dte, iv_5day, slope, elevated_0dte_premium, ok_to_sell
    slope > 0 means 0DTE IV > 5-day IV (sell 0DTE premium).
    """
    if yf is None:
        return {"error": "yfinance_unavailable", "ok_to_sell": None}

    try:
        spot = float(yf.Ticker(symbol).fast_info["lastPrice"])
    except Exception as exc:
        return {"error": str(exc), "ok_to_sell": None}

    today = date.today().isoformat()
    opts = list(yf.Ticker(symbol).options)

    # 0DTE expiry
    if today not in opts:
        return {"error": "no_0dte_expiry", "ok_to_sell": None}

    # 5-day expiry (nearest expiry 4-8 days out)
    target = date.today() + timedelta(days=5)
    five_day_exp = next(
        (e for e in opts if abs((date.fromisoformat(e) - target).days) <= 3
         and e != today),
        None,
    )
    if five_day_exp is None:
        return {"error": "no_5day_expiry", "ok_to_sell": None}

    iv_0dte = _atm_iv(symbol, today, spot)
    iv_5day = _atm_iv(symbol, five_day_exp, spot)

    if iv_0dte is None or iv_5day is None:
        return {
            "iv_0dte": iv_0dte,
            "iv_5day": iv_5day,
            "error": "iv_fetch_incomplete",
            "ok_to_sell": None,
        }

    slope = round(iv_0dte - iv_5day, 4)
    elevated = slope > 0

    return {
        "iv_0dte": round(iv_0dte, 4),
        "iv_5day": round(iv_5day, 4),
        "expiry_0dte": today,
        "expiry_5day": five_day_exp,
        "slope": slope,
        "elevated_0dte_premium": elevated,
        "ok_to_sell": elevated,
        "generated_at": datetime.now(tz=timezone.utc).isoformat(),
    }


if __name__ == "__main__":
    import json
    print(json.dumps(iv_term_structure_context(), indent=2))

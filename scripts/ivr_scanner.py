"""
IV Rank (IVR) Scanner — computes from Alpaca options chain + rolling IV history log.

No trading. Prints IVR to console and appends daily ATM IV to data/iv_history_log.jsonl
IVR computed from rolling 252-day (or available) history of ATM IV readings.

IV Rank formula:
  IVR = (current_IV - IV_52w_low) / (IV_52w_high - IV_52w_low) * 100

  IVR < 25  → IV cheap → buy options (calls/puts)
  IVR 25-75 → neutral
  IVR > 75  → IV expensive → sell spreads / iron condors

Usage for our bots:
  - Flip Bot: prefer buying 0DTE calls when IVR < 50 (cheaper premium)
  - IWM Bot: prefer selling put spreads when IVR > 50 (rich premium)
  - Skip entries if IVR is extreme relative to strategy type

Symbols: SPY, QQQ, IWM (matches our active bots)

Run at market open (09:35 ET) after options chain is liquid.
Data accumulates daily — IVR meaningful after ~30 readings.
"""
from __future__ import annotations

import json
import os
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

LOG_PATH = ROOT / "data" / "iv_history_log.jsonl"
SYMBOLS = ["SPY", "QQQ", "IWM"]
LOOKBACK_DAYS = 252

_ALPACA_KEY: str | None = None
_ALPACA_SECRET: str | None = None


def _load_env() -> None:
    global _ALPACA_KEY, _ALPACA_SECRET
    _ALPACA_KEY = os.environ.get("ALPACA_API_KEY")
    _ALPACA_SECRET = os.environ.get("ALPACA_SECRET_KEY")
    if _ALPACA_KEY and _ALPACA_SECRET:
        return
    env_path = ROOT / "agent" / ".env"
    if env_path.exists():
        for line in env_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line.startswith("#") or "=" not in line:
                continue
            k, _, v = line.partition("=")
            if k.strip() == "ALPACA_API_KEY":
                _ALPACA_KEY = v.strip()
            elif k.strip() == "ALPACA_SECRET_KEY":
                _ALPACA_SECRET = v.strip()


def _fetch_atm_iv(symbol: str, spot: float) -> float | None:
    """Fetch ATM implied volatility from Alpaca 0DTE or nearest-expiry option chain."""
    try:
        from alpaca.data.historical.option import OptionHistoricalDataClient
        from alpaca.data.requests import OptionChainRequest
    except ImportError:
        raise ImportError("alpaca-py required")

    _load_env()
    client = OptionHistoricalDataClient(api_key=_ALPACA_KEY, secret_key=_ALPACA_SECRET)

    today = date.today().strftime("%Y-%m-%d")
    expiry_end = (date.today() + timedelta(days=14)).strftime("%Y-%m-%d")

    request = OptionChainRequest(
        underlying_symbol=symbol,
        expiration_date_gte=today,
        expiration_date_lte=expiry_end,
    )
    snapshot = client.get_option_chain(request)

    # Find ATM call closest to spot price in nearest expiry
    best: tuple[float, float] | None = None  # (distance_from_atm, iv)
    nearest_expiry: str | None = None

    for occ_symbol, snap in snapshot.items():
        greeks = getattr(snap, "greeks", None)
        if greeks is None:
            continue
        iv = getattr(snap, "implied_volatility", None)
        if iv is None or float(iv) <= 0:
            continue

        try:
            rest = occ_symbol[len(symbol):]
            expiry = datetime.strptime(rest[:6], "%y%m%d").date().isoformat()
            right = "call" if rest[6] == "C" else "put"
            strike = float(rest[7:]) / 1000.0
        except Exception:
            continue

        if right != "call":
            continue

        if nearest_expiry is None:
            nearest_expiry = expiry
        if expiry != nearest_expiry:
            continue

        dist = abs(strike - spot)
        if best is None or dist < best[0]:
            best = (dist, float(iv))

    return best[1] if best is not None else None


def _fetch_spot(symbol: str) -> float | None:
    """Fetch current spot price via Alpaca latest quote."""
    try:
        from alpaca.data.historical import StockHistoricalDataClient
        from alpaca.data.requests import StockLatestQuoteRequest
    except ImportError:
        return None

    _load_env()
    try:
        client = StockHistoricalDataClient(api_key=_ALPACA_KEY, secret_key=_ALPACA_SECRET)
        req = StockLatestQuoteRequest(symbol_or_symbols=symbol)
        quote = client.get_stock_latest_quote(req)
        q = quote.get(symbol)
        if q is None:
            return None
        ask = getattr(q, "ask_price", None)
        bid = getattr(q, "bid_price", None)
        if ask and bid:
            return float((ask + bid) / 2)
        return float(ask or bid or 0) or None
    except Exception:
        return None


def _load_iv_history(symbol: str, log_path: Path = LOG_PATH) -> list[float]:
    """Load historical ATM IV readings for a symbol from the log."""
    if not log_path.exists():
        return []
    ivs: list[float] = []
    cutoff = (date.today() - timedelta(days=LOOKBACK_DAYS)).isoformat()
    for line in log_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if row.get("date", "") < cutoff:
            continue
        for scan in row.get("scans", []):
            if scan.get("symbol") == symbol and scan.get("atm_iv") is not None:
                ivs.append(float(scan["atm_iv"]))
    return ivs


def compute_ivr(current_iv: float, history: list[float]) -> dict:
    if len(history) < 5:
        return {
            "ivr": None,
            "ivp": None,
            "history_days": len(history),
            "status": "accumulating",
            "note": f"Need more data ({len(history)}/30 min readings). IVR available after ~30 days.",
        }

    iv_high = max(history)
    iv_low = min(history)
    rng = iv_high - iv_low

    ivr = round((current_iv - iv_low) / rng * 100, 1) if rng > 0.001 else 50.0
    ivp = round(sum(1 for h in history if h < current_iv) / len(history) * 100, 1)

    if ivr < 25:
        regime = "cheap"
        bias = "buy_options"
    elif ivr > 75:
        regime = "expensive"
        bias = "sell_premium"
    else:
        regime = "neutral"
        bias = "neutral"

    return {
        "ivr": ivr,
        "ivp": ivp,
        "iv_52w_high": round(iv_high * 100, 2),
        "iv_52w_low": round(iv_low * 100, 2),
        "current_iv_pct": round(current_iv * 100, 2),
        "history_days": len(history),
        "status": "ok",
        "regime": regime,
        "bias": bias,
    }


def scan_symbol(symbol: str) -> dict:
    try:
        spot = _fetch_spot(symbol)
        if spot is None:
            return {"symbol": symbol, "status": "error", "error": "spot price unavailable"}

        atm_iv = _fetch_atm_iv(symbol, spot)
        if atm_iv is None:
            return {"symbol": symbol, "status": "error", "error": "ATM IV unavailable — market may be closed"}

        history = _load_iv_history(symbol)
        # Include current reading in history for IVR calc
        history_with_current = history + [atm_iv]
        ivr_data = compute_ivr(atm_iv, history_with_current)

        return {
            "symbol": symbol,
            "status": "ok",
            "spot": round(spot, 2),
            "atm_iv": round(atm_iv, 4),
            **ivr_data,
        }
    except Exception as exc:
        return {"symbol": symbol, "status": "error", "error": str(exc)[:200]}


def log_scan(results: list[dict], log_path: Path = LOG_PATH) -> None:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    today = date.today().isoformat()

    # Load existing, replace today's entry if present
    rows: list[dict] = []
    if log_path.exists():
        for line in log_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                r = json.loads(line)
                if r.get("date") != today:
                    rows.append(r)
            except json.JSONDecodeError:
                pass

    entry = {
        "date": today,
        "timestamp": datetime.utcnow().isoformat() + "Z",
        "scans": results,
    }
    rows.append(entry)
    log_path.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")


def print_report(results: list[dict]) -> None:
    print("\n" + "=" * 62)
    print(f"IV Rank (IVR) Scanner | {date.today().isoformat()}")
    print("=" * 62)
    for r in results:
        sym = r["symbol"]
        if r.get("status") == "error":
            print(f"\n{sym}: ERROR — {r.get('error')}")
            continue
        ivr = r.get("ivr")
        ivp = r.get("ivp")
        iv_pct = r.get("current_iv_pct")
        regime = r.get("regime", "?")
        bias = r.get("bias", "?")
        days = r.get("history_days", 0)
        spot = r.get("spot")

        print(f"\n{sym}: spot=${spot}  ATM IV={iv_pct}%")
        if ivr is not None:
            print(f"  IVR: {ivr:.1f}  IVP: {ivp:.1f}  regime={regime.upper()}  bias={bias}")
        else:
            print(f"  {r.get('note', 'accumulating...')} ({days} readings)")
        if r.get("iv_52w_high"):
            print(f"  Range: {r['iv_52w_low']:.1f}% - {r['iv_52w_high']:.1f}% ({days} days)")
    print("""
IVR Guide:
  < 25: Premium CHEAP  → favor buying options (calls/puts)
  > 75: Premium RICH   → favor selling spreads (IWM bot)
""")


def main() -> int:
    print("Scanning IV Rank from Alpaca options chain...")
    results = [scan_symbol(sym) for sym in SYMBOLS]
    print_report(results)
    log_scan(results)
    print(f"IV history logged to {LOG_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""
GEX (Gamma Exposure) Scanner — computes from Alpaca options chain.

No trading. Prints GEX levels to console and appends to data/gex_scan_log.jsonl

GEX formula:
  GEX per strike = gamma * open_interest * 100 (contract size)
  Call GEX = positive (market makers long gamma → stabilizing)
  Put GEX  = negative (market makers short gamma → amplifying)
  Net GEX at strike = call_GEX - put_GEX
  GEX wall = strike with largest |net GEX| = price magnet / bounce level
  Total net GEX sign:
    Positive = dealers long gamma → buy dips, sell rips → range-bound expected
    Negative = dealers short gamma → amplify moves → trending/volatile expected

Run at market open (09:35 ET) to get key intraday levels.
Symbols: SPY, QQQ, IWM

Requires: alpaca-py (already installed)
Keys: ALPACA_API_KEY, ALPACA_SECRET_KEY from agent/.env
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

LOG_PATH = ROOT / "data" / "gex_scan_log.jsonl"
SYMBOLS = ["SPY", "QQQ", "IWM"]

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


def _get_option_chain(symbol: str) -> list[dict]:
    """Fetch 0DTE options chain snapshot from Alpaca."""
    try:
        from alpaca.data.historical.option import OptionHistoricalDataClient
        from alpaca.data.requests import OptionChainRequest
    except ImportError:
        raise ImportError("alpaca-py required: uv add alpaca-py")

    _load_env()
    client = OptionHistoricalDataClient(api_key=_ALPACA_KEY, secret_key=_ALPACA_SECRET)

    today = date.today().strftime("%Y-%m-%d")
    # Get current + next 5 trading days of expirations (captures 0DTE + weeklies)
    expiry_end = (date.today() + timedelta(days=7)).strftime("%Y-%m-%d")

    request = OptionChainRequest(
        underlying_symbol=symbol,
        expiration_date_gte=today,
        expiration_date_lte=expiry_end,
    )
    snapshot = client.get_option_chain(request)

    contracts = []
    for occ_symbol, snap in snapshot.items():
        greeks = getattr(snap, "greeks", None)
        if greeks is None:
            continue
        gamma = getattr(greeks, "gamma", None)
        delta = getattr(greeks, "delta", None)
        if gamma is None:
            continue

        # Parse OCC symbol: SPY260702C00560000
        try:
            sym_part = occ_symbol[:len(symbol)]
            rest = occ_symbol[len(symbol):]
            expiry = datetime.strptime(rest[:6], "%y%m%d").date().isoformat()
            right = "call" if rest[6] == "C" else "put"
            strike = float(rest[7:]) / 1000.0
        except Exception:
            continue

        # Displayed quote size is not open interest and must not stand in for it.
        oi = getattr(snap, "open_interest", None) or 0
        size = oi if oi > 0 else 0

        contracts.append({
            "occ": occ_symbol,
            "expiry": expiry,
            "strike": strike,
            "right": right,
            "gamma": float(gamma),
            "delta": float(delta) if delta is not None else None,
            "open_interest": int(oi),
            "size_used": int(size),
            "size_source": "open_interest" if oi > 0 else "missing",
        })

    return contracts


def compute_gex(contracts: list[dict], *, as_of: date | None = None, min_oi_coverage: float = 0.60) -> dict:
    """Compute a 0DTE gamma/open-interest proxy with explicit provenance."""
    if not contracts:
        return {"status": "unavailable", "error": "no contracts", "gex_wall": None, "net_gex": 0.0}

    today = (as_of or date.today()).isoformat()
    # Prefer 0DTE; fall back to shortest available expiry (Alpaca often lacks 0DTE snapshots)
    zero_dte = [c for c in contracts if c["expiry"] == today]
    if not zero_dte:
        all_expiries = sorted({c["expiry"] for c in contracts if c["expiry"] >= today})
        if not all_expiries:
            return {
                "status": "unavailable",
                "error": "no near-term contracts",
                "expiry_filter": "shortest_available",
                "contract_count": 0,
                "gex_wall": None,
                "net_gex": 0.0,
                "dealer_positioning_observed": False,
            }
        nearest = all_expiries[0]
        zero_dte = [c for c in contracts if c["expiry"] == nearest]
    use = [
        contract for contract in zero_dte
        if contract.get("size_source") == "open_interest" and contract.get("size_used", 0) > 0
    ]
    oi_coverage = len(use) / len(zero_dte) if zero_dte else 0.0
    if not use or oi_coverage < min_oi_coverage:
        return {
            "status": "unavailable",
            "error": "insufficient open interest coverage",
            "expiry_filter": "0dte",
            "contract_count": len(zero_dte),
            "open_interest_contract_count": len(use),
            "open_interest_coverage": round(oi_coverage, 4),
            "minimum_open_interest_coverage": min_oi_coverage,
            "gex_wall": None,
            "net_gex": 0.0,
            "dealer_positioning_observed": False,
        }

    # Aggregate GEX by strike
    strike_gex: dict[float, float] = {}
    for c in use:
        gex = c["gamma"] * c["size_used"] * 100
        if c["right"] == "call":
            strike_gex[c["strike"]] = strike_gex.get(c["strike"], 0.0) + gex
        else:
            strike_gex[c["strike"]] = strike_gex.get(c["strike"], 0.0) - gex

    if not strike_gex:
        return {"status": "unavailable", "error": "no strike data", "gex_wall": None, "net_gex": 0.0}

    sorted_strikes = sorted(strike_gex.items(), key=lambda x: x[0])
    net_gex = sum(strike_gex.values())

    # GEX wall = strike with largest |net GEX|
    gex_wall_strike = max(strike_gex, key=lambda s: abs(strike_gex[s]))
    gex_wall_value = strike_gex[gex_wall_strike]

    # Top 5 levels by absolute GEX
    top_levels = sorted(
        [{"strike": s, "gex": round(g, 2)} for s, g in sorted_strikes],
        key=lambda x: abs(x["gex"]),
        reverse=True,
    )[:5]

    return {
        "status": "ok",
        "mode": "shadow_only_context",
        "execution_enabled": False,
        "can_submit_orders": False,
        "expiry_filter": "0dte",
        "contract_count": len(use),
        "zero_dte_contract_count": len(zero_dte),
        "open_interest_coverage": round(oi_coverage, 4),
        "size_source": "open_interest",
        "dealer_positioning_observed": False,
        "sign_assumption": "calls_positive_puts_negative",
        "net_gex": round(net_gex, 2),
        "net_gex_regime": "positive" if net_gex > 0 else "negative",
        "net_gex_interpretation": (
            "Positive call-minus-put gamma/OI proxy; test range damping in shadow"
            if net_gex > 0
            else "Negative call-minus-put gamma/OI proxy; test trend amplification in shadow"
        ),
        "gex_wall": {
            "strike": gex_wall_strike,
            "gex": round(gex_wall_value, 2),
            "bias": "support" if gex_wall_value > 0 else "resistance",
        },
        "top_levels": top_levels,
    }


def scan_symbol(symbol: str) -> dict:
    try:
        contracts = _get_option_chain(symbol)
        gex = compute_gex(contracts)
        return {"symbol": symbol, **gex}
    except Exception as exc:
        return {"symbol": symbol, "status": "error", "error": str(exc)[:200]}


def log_scan(entry: dict, log_path: Path = LOG_PATH) -> None:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(entry) + "\n")


def print_report(results: list[dict]) -> None:
    print("\n" + "=" * 62)
    print(f"GEX Scanner | {date.today().isoformat()}")
    print("=" * 62)
    for r in results:
        sym = r["symbol"]
        if r.get("status") != "ok":
            print(f"\n{sym}: UNAVAILABLE - {r.get('error')}")
            continue
        wall = r.get("gex_wall") or {}
        net = r.get("net_gex", 0)
        regime = r.get("net_gex_regime", "?")
        print(f"\n{sym}:")
        print(f"  Net GEX: {net:+,.0f} ({regime.upper()})")
        print(f"  Interpretation: {r.get('net_gex_interpretation', '')}")
        if wall:
            print(f"  GEX Wall: ${wall['strike']:.2f}  gex={wall['gex']:+,.0f}  ({wall['bias']})")
        if r.get("top_levels"):
            print(f"  Top levels:")
            for lvl in r["top_levels"][:3]:
                print(f"    ${lvl['strike']:.2f}  gex={lvl['gex']:+,.0f}")
    print()


def main() -> int:
    today = date.today().isoformat()
    print(f"Computing GEX from Alpaca options chain | {today}")
    results = [scan_symbol(sym) for sym in SYMBOLS]
    print_report(results)
    entry = {"date": today, "timestamp": datetime.utcnow().isoformat() + "Z", "scans": results}
    log_scan(entry)
    print(f"Logged to {LOG_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

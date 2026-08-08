#!/usr/bin/env python3
"""Shadow-only SPY/XSP/SPX instrument router.

The router verifies broker support, maps the latest SPY shadow contract by
moneyness, and compares conservative expected payoff after observable costs.
It has no order endpoint and cannot promote an instrument.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests
import yfinance as yf
from dotenv import load_dotenv


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from strategies.spy_spx_execution_policy import rank_instruments


load_dotenv(ROOT / "agent" / ".env")
SOURCE_PATH = ROOT / "data" / "flip_shadow_candidates_log.jsonl"
REPORT_PATH = Path.home() / ".vibe-trading" / "reports" / "sp500-instrument-router.json"
LOG_PATH = ROOT / "data" / "sp500_instrument_router_log.jsonl"
BASE = "https://paper-api.alpaca.markets"
DATA_BASE = "https://data.alpaca.markets"
HEADERS = {
    "APCA-API-KEY-ID": os.getenv("ALPACA_API_KEY", ""),
    "APCA-API-SECRET-KEY": os.getenv("ALPACA_SECRET_KEY", ""),
}
YF_SYMBOLS = {"SPY": "SPY", "XSP": "^XSP", "SPX": "^GSPC"}


def _number(value: Any) -> float | None:
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _latest_spy_candidate(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    latest = None
    for line in path.read_text(encoding="utf-8-sig").splitlines():
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if (
            isinstance(row, dict)
            and str(row.get("symbol") or "").upper() == "SPY"
            and row.get("event_type") in {"shadow_entry", "shadow_mark"}
            and row.get("option_symbol")
        ):
            latest = row
    return latest


def _spot(symbol: str) -> float | None:
    try:
        value = float(yf.Ticker(YF_SYMBOLS[symbol]).fast_info["last_price"])
        return value if value > 0 else None
    except Exception:
        return None


def _broker_asset(symbol: str) -> dict[str, Any] | None:
    try:
        response = requests.get(f"{BASE}/v2/assets/{symbol}", headers=HEADERS, timeout=10)
        if response.status_code != 200:
            return None
        value = response.json()
        return value if isinstance(value, dict) else None
    except requests.RequestException:
        return None


def _contracts(symbol: str, expiry: str, right: str) -> list[dict[str, Any]]:
    try:
        response = requests.get(
            f"{BASE}/v2/options/contracts",
            headers=HEADERS,
            params={
                "underlying_symbols": symbol,
                "expiration_date": expiry,
                "type": right.lower(),
                "status": "active",
                "limit": 1000,
            },
            timeout=15,
        )
        if response.status_code != 200:
            return []
        return list(response.json().get("option_contracts") or [])
    except requests.RequestException:
        return []


def _snapshot(option_symbol: str) -> dict[str, Any]:
    try:
        response = requests.get(
            f"{DATA_BASE}/v1beta1/options/snapshots",
            headers=HEADERS,
            params={"symbols": option_symbol},
            timeout=10,
        )
        if response.status_code != 200:
            return {}
        return response.json().get("snapshots", {}).get(option_symbol, {}) or {}
    except requests.RequestException:
        return {}


def _candidate(instrument: str, source: dict[str, Any]) -> dict[str, Any]:
    asset = _broker_asset(instrument)
    spot = _spot(instrument)
    spy_spot = _number(source.get("underlying_spot_at_selection")) or _number(source.get("underlying_close"))
    source_strike = _number(source.get("strike"))
    expiry = str(source.get("expiry") or "")
    right = str(source.get("right") or "").upper()
    supported = bool(asset and asset.get("tradable") and spot and spy_spot and source_strike and expiry and right in {"CALL", "PUT"})
    base = {
        "instrument": instrument,
        "broker_support_verified": supported,
        "asset_status": asset.get("status") if asset else "unavailable",
        "quote_authority": "unavailable",
    }
    if not supported:
        return base
    target_moneyness = source_strike / spy_spot
    target_strike = spot * target_moneyness
    contracts = _contracts(instrument, expiry, right)
    if not contracts:
        return {**base, "broker_support_verified": False, "asset_status": "options_contracts_unavailable"}
    contract = min(contracts, key=lambda row: abs((_number(row.get("strike_price")) or 0.0) - target_strike))
    option_symbol = str(contract.get("symbol") or "")
    snap = _snapshot(option_symbol)
    quote = snap.get("latestQuote") or {}
    greeks = snap.get("greeks") or {}
    bid = _number(quote.get("bp")) or 0.0
    ask = _number(quote.get("ap")) or 0.0
    delta = abs(_number(greeks.get("delta")) or 0.50)
    counterfactual = source.get("shadow_underlying_counterfactual") or {}
    source_entry = _number(counterfactual.get("entry_underlying")) or spy_spot
    source_target = _number(counterfactual.get("target_underlying"))
    expected_move_pct = abs(source_target - source_entry) / source_entry if source_target and source_entry else 0.005
    multiplier = int(_number(contract.get("size")) or 100)
    gross = delta * spot * expected_move_pct * multiplier
    spread_cost = max(0.0, ask - bid) * multiplier
    quote_ts = quote.get("t")
    age_seconds = None
    if quote_ts:
        try:
            parsed = datetime.fromisoformat(str(quote_ts).replace("Z", "+00:00"))
            age_seconds = max(0.0, (datetime.now(timezone.utc) - parsed.astimezone(timezone.utc)).total_seconds())
        except (TypeError, ValueError):
            pass
    return {
        **base,
        "option_symbol": option_symbol,
        "spot": round(spot, 4),
        "strike": _number(contract.get("strike_price")),
        "target_moneyness": round(target_moneyness, 6),
        "bid": bid or None,
        "ask": ask or None,
        "delta": round(delta, 4),
        "quote_timestamp": quote_ts,
        "quote_age_seconds": round(age_seconds, 3) if age_seconds is not None else None,
        # Alpaca's REST response does not attest which entitlement produced the
        # quote. Only the OPRA websocket cache may grant OPRA authority.
        "quote_authority": "unverified_rest_snapshot",
        "gross_expected_payoff": round(gross, 4),
        "spread_cost": round(spread_cost, 4),
        "fees": 0.06,
        "slippage": round(spread_cost * 0.5, 4),
        "staleness_penalty": round(gross * 0.25, 4) if age_seconds is None or age_seconds > 2 else 0.0,
        "model_uncertainty": round(gross * 0.25, 4),
        "expected_payoff_method": "linear_delta_target_move_proxy",
    }


def build_report(source_path: Path = SOURCE_PATH) -> dict[str, Any]:
    source = _latest_spy_candidate(source_path)
    candidates = [_candidate(symbol, source) for symbol in ("SPY", "XSP", "SPX")] if source else []
    ranking = rank_instruments(candidates)
    return {
        "provider": "sp500_instrument_router",
        "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "source_path": str(source_path),
        "source_lifecycle_id": source.get("lifecycle_id") if source else None,
        "source_status": "available" if source else "no_spy_shadow_candidate",
        **ranking,
        "warnings": [
            "Shadow-only comparison; this module has no order-submission code.",
            "REST snapshots remain unverified until matched to OPRA stream evidence.",
            "Index-option broker support must be verified on every run; unsupported instruments remain ineligible.",
        ],
    }


def _write(path: Path, value: dict[str, Any], *, append: bool = False) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if append:
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(value, sort_keys=True) + "\n")
    else:
        temp = path.with_suffix(path.suffix + ".tmp")
        temp.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        os.replace(temp, path)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=SOURCE_PATH)
    parser.add_argument("--output", type=Path, default=REPORT_PATH)
    parser.add_argument("--log", type=Path, default=LOG_PATH)
    parser.add_argument("--print", action="store_true", dest="print_report")
    args = parser.parse_args()
    report = build_report(args.source)
    _write(args.output, report)
    _write(args.log, report, append=True)
    if args.print_report:
        print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

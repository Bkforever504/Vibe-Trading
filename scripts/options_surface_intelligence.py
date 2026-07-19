#!/usr/bin/env python3
"""Read-only option-surface and unsigned-flow intelligence.

Public option-chain snapshots can describe volatility, skew, term structure,
open interest, and volume. They cannot prove whether trades were buyer- or
seller-initiated. This report keeps that distinction explicit.
"""
from __future__ import annotations

import argparse
import json
import math
import os
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Callable

import yfinance as yf


ROOT = Path(__file__).resolve().parent.parent
VIBE_HOME = Path.home() / ".vibe-trading"
REPORT_DIR = VIBE_HOME / "reports"
REPORT_PATH = REPORT_DIR / "options-surface-intelligence.json"
LOG_PATH = ROOT / "data" / "options_surface_intelligence_log.jsonl"
LIQUIDITY_PATH = REPORT_DIR / "options-liquidity-feasibility.json"
WEEKLY_PATH = REPORT_DIR / "weekly-hot-instruments.json"

DEFAULT_SYMBOLS = ["SPY", "QQQ", "IWM", "NVDA", "AAPL", "TSLA", "META", "RIVN"]
MAX_SYMBOLS = 8
MAX_EXPIRIES = 4
MAX_DTE = 60
LOW_PRICE_UNDERLYING = 25.0
CHEAP_PREMIUM_MAX = 0.50
HIGH_IV = 1.0
WIDE_SPREAD_PCT = 20.0
UNUSUAL_VOL_OI = 3.0
UNUSUAL_MIN_VOLUME = 100


def _read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def _number(value: Any, default: float = 0.0) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return default
    return result if math.isfinite(result) else default


def _integer(value: Any, default: int = 0) -> int:
    return int(_number(value, float(default)))


def _mid(row: dict[str, Any]) -> float:
    bid = _number(row.get("bid"))
    ask = _number(row.get("ask"))
    if bid > 0 and ask >= bid:
        return (bid + ask) / 2
    return _number(row.get("lastPrice"))


def _spread_pct(row: dict[str, Any]) -> float | None:
    bid = _number(row.get("bid"))
    ask = _number(row.get("ask"))
    mid = (bid + ask) / 2
    if bid <= 0 or ask <= 0 or ask < bid or mid <= 0:
        return None
    return round((ask - bid) / mid * 100, 2)


def _nearest(rows: list[dict[str, Any]], strike: float) -> dict[str, Any]:
    valid = [row for row in rows if _number(row.get("strike")) > 0]
    return min(valid, key=lambda row: abs(_number(row.get("strike")) - strike), default={})


def _sum(rows: list[dict[str, Any]], field: str) -> int:
    return sum(max(0, _integer(row.get(field))) for row in rows)


def _unusual_contracts(
    calls: list[dict[str, Any]],
    puts: list[dict[str, Any]],
    spot: float,
    expiry: str,
) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    for right, rows in (("CALL", calls), ("PUT", puts)):
        for row in rows:
            volume = _integer(row.get("volume"))
            oi = _integer(row.get("openInterest"))
            if volume < UNUSUAL_MIN_VOLUME or oi <= 0:
                continue
            ratio = volume / oi
            if ratio < UNUSUAL_VOL_OI:
                continue
            strike = _number(row.get("strike"))
            output.append({
                "contract_symbol": row.get("contractSymbol"),
                "right": right,
                "expiry": expiry,
                "strike": strike,
                "moneyness_pct": round((strike / spot - 1) * 100, 2) if spot else None,
                "volume": volume,
                "open_interest": oi,
                "volume_to_open_interest": round(ratio, 2),
                "implied_volatility": round(_number(row.get("impliedVolatility")), 4),
                "mid": round(_mid(row), 4),
                "spread_pct": _spread_pct(row),
                "trade_direction": "unknown_unsigned_snapshot",
            })
    output.sort(key=lambda row: (row["volume_to_open_interest"], row["volume"]), reverse=True)
    return output[:12]


def _lottery_contracts(
    calls: list[dict[str, Any]],
    puts: list[dict[str, Any]],
    spot: float,
    expiry: str,
) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    for right, rows in (("CALL", calls), ("PUT", puts)):
        for row in rows:
            ask = _number(row.get("ask"))
            iv = _number(row.get("impliedVolatility"))
            spread = _spread_pct(row)
            strike = _number(row.get("strike"))
            moneyness = abs((strike / spot - 1) * 100) if spot and strike else 0.0
            risk_signals = sum((
                0 < ask <= CHEAP_PREMIUM_MAX,
                iv >= HIGH_IV,
                spread is None or spread >= WIDE_SPREAD_PCT,
                moneyness >= 5,
            ))
            if risk_signals < 3:
                continue
            output.append({
                "contract_symbol": row.get("contractSymbol"),
                "right": right,
                "expiry": expiry,
                "strike": strike,
                "ask": round(ask, 4),
                "implied_volatility": round(iv, 4),
                "spread_pct": spread,
                "moneyness_pct_abs": round(moneyness, 2),
                "risk_signals": risk_signals,
            })
    output.sort(key=lambda row: (row["risk_signals"], row["implied_volatility"]), reverse=True)
    return output[:12]


def analyze_expiry(
    *,
    spot: float,
    expiry: str,
    calls: list[dict[str, Any]],
    puts: list[dict[str, Any]],
    today: date,
) -> dict[str, Any]:
    try:
        dte = max(0, (date.fromisoformat(expiry) - today).days)
    except ValueError:
        dte = 0
    atm_call = _nearest(calls, spot)
    atm_put = _nearest(puts, spot)
    put_90 = _nearest(puts, spot * 0.90)
    call_110 = _nearest(calls, spot * 1.10)
    atm_call_iv = _number(atm_call.get("impliedVolatility"))
    atm_put_iv = _number(atm_put.get("impliedVolatility"))
    atm_iv_values = [value for value in (atm_call_iv, atm_put_iv) if value > 0]
    atm_iv = sum(atm_iv_values) / len(atm_iv_values) if atm_iv_values else 0.0
    straddle_mid = _mid(atm_call) + _mid(atm_put)
    call_oi = _sum(calls, "openInterest")
    put_oi = _sum(puts, "openInterest")
    call_volume = _sum(calls, "volume")
    put_volume = _sum(puts, "volume")
    spreads = [value for value in (_spread_pct(atm_call), _spread_pct(atm_put)) if value is not None]
    unusual = _unusual_contracts(calls, puts, spot, expiry)
    lottery = _lottery_contracts(calls, puts, spot, expiry)
    return {
        "expiry": expiry,
        "dte": dte,
        "atm_strike": _number(atm_call.get("strike"), _number(atm_put.get("strike"))),
        "atm_iv": round(atm_iv, 4),
        "atm_call_iv": round(atm_call_iv, 4),
        "atm_put_iv": round(atm_put_iv, 4),
        "put_90_iv": round(_number(put_90.get("impliedVolatility")), 4),
        "call_110_iv": round(_number(call_110.get("impliedVolatility")), 4),
        "put_skew_vs_atm": round(_number(put_90.get("impliedVolatility")) - atm_put_iv, 4),
        "call_wing_vs_atm": round(_number(call_110.get("impliedVolatility")) - atm_call_iv, 4),
        "atm_put_minus_call_iv": round(atm_put_iv - atm_call_iv, 4),
        "straddle_mid": round(straddle_mid, 4),
        "implied_move_pct": round(straddle_mid / spot * 100, 3) if spot > 0 else None,
        "atm_max_spread_pct": round(max(spreads), 2) if spreads else None,
        "call_open_interest": call_oi,
        "put_open_interest": put_oi,
        "put_call_open_interest_ratio": round(put_oi / call_oi, 3) if call_oi else None,
        "call_volume": call_volume,
        "put_volume": put_volume,
        "put_call_volume_ratio": round(put_volume / call_volume, 3) if call_volume else None,
        "unusual_unsigned_contracts": unusual,
        "lottery_risk_contracts": lottery,
    }


def analyze_snapshot(snapshot: dict[str, Any], today: date | None = None) -> dict[str, Any]:
    today = today or date.today()
    symbol = str(snapshot.get("symbol") or "").upper()
    spot = _number(snapshot.get("spot"))
    if not symbol or spot <= 0:
        return {"symbol": symbol, "status": "unavailable", "reason": "missing_symbol_or_spot"}
    expiries = []
    for chain in snapshot.get("chains") or []:
        if not isinstance(chain, dict):
            continue
        calls = [row for row in chain.get("calls") or [] if isinstance(row, dict)]
        puts = [row for row in chain.get("puts") or [] if isinstance(row, dict)]
        if not calls or not puts:
            continue
        expiries.append(analyze_expiry(
            spot=spot,
            expiry=str(chain.get("expiry") or ""),
            calls=calls,
            puts=puts,
            today=today,
        ))
    expiries.sort(key=lambda row: row["dte"])
    if not expiries:
        return {"symbol": symbol, "status": "unavailable", "reason": "no_complete_expiry_pairs", "spot": spot}

    front = expiries[0]
    back = expiries[-1]
    lottery_count = sum(len(row["lottery_risk_contracts"]) for row in expiries)
    unusual_count = sum(len(row["unusual_unsigned_contracts"]) for row in expiries)
    risk_score = 0
    risk_reasons: list[str] = []
    if spot <= LOW_PRICE_UNDERLYING:
        risk_score += 2
        risk_reasons.append("low_price_underlying")
    if lottery_count:
        risk_score += min(4, 2 + lottery_count)
        risk_reasons.append("cheap_high_iv_wide_spread_wings")
    if _number(front.get("atm_max_spread_pct"), 999) >= WIDE_SPREAD_PCT:
        risk_score += 2
        risk_reasons.append("wide_atm_spread")
    if _number(front.get("atm_iv")) >= HIGH_IV:
        risk_score += 1
        risk_reasons.append("high_front_implied_volatility")
    retail_lottery_risk = risk_score >= 5
    front_iv = _number(front.get("atm_iv"))
    back_iv = _number(back.get("atm_iv"))
    dte_span = max(1, _integer(back.get("dte")) - _integer(front.get("dte")))
    return {
        "symbol": symbol,
        "status": "ok",
        "spot": round(spot, 4),
        "snapshot_at": snapshot.get("snapshot_at"),
        "expiry_count": len(expiries),
        "front_expiry": front["expiry"],
        "front_dte": front["dte"],
        "front_atm_iv": front_iv,
        "front_implied_move_pct": front.get("implied_move_pct"),
        "front_put_skew_vs_atm": front.get("put_skew_vs_atm"),
        "front_call_wing_vs_atm": front.get("call_wing_vs_atm"),
        "front_put_call_oi_ratio": front.get("put_call_open_interest_ratio"),
        "front_put_call_volume_ratio": front.get("put_call_volume_ratio"),
        "atm_iv_term_slope_per_30d": round((back_iv - front_iv) / dte_span * 30, 4),
        "term_structure": "backwardated" if front_iv > back_iv else "contango_or_flat",
        "unsigned_unusual_contract_count": unusual_count,
        "retail_lottery_risk": retail_lottery_risk,
        "retail_lottery_risk_score": risk_score,
        "retail_lottery_risk_reasons": risk_reasons,
        "lottery_contract_count": lottery_count,
        "surface_usable_for_shadow_research": len(expiries) >= 2 and _number(front.get("atm_max_spread_pct"), 999) <= WIDE_SPREAD_PCT,
        "institutional_flow_available": False,
        "flow_classification": "unsigned_public_chain_snapshot",
        "expiries": expiries,
    }


def fetch_snapshot(symbol: str, today: date | None = None) -> dict[str, Any]:
    today = today or date.today()
    ticker = yf.Ticker(symbol)
    info = ticker.fast_info
    spot = _number(getattr(info, "last_price", None))
    if spot <= 0:
        try:
            spot = _number(info["last_price"])
        except Exception:
            spot = 0.0
    expiries: list[str] = []
    for raw in ticker.options or ():
        try:
            dte = (date.fromisoformat(str(raw)) - today).days
        except ValueError:
            continue
        if 0 <= dte <= MAX_DTE:
            expiries.append(str(raw))
        if len(expiries) >= MAX_EXPIRIES:
            break
    chains = []
    for expiry in expiries:
        chain = ticker.option_chain(expiry)
        chains.append({
            "expiry": expiry,
            "calls": chain.calls.to_dict("records"),
            "puts": chain.puts.to_dict("records"),
        })
    return {
        "symbol": symbol.upper(),
        "spot": spot,
        "snapshot_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "chains": chains,
    }


def default_symbols(
    liquidity_path: Path = LIQUIDITY_PATH,
    weekly_path: Path = WEEKLY_PATH,
) -> list[str]:
    liquidity = _read_json(liquidity_path)
    eligible = {
        str(row.get("symbol") or "").upper()
        for row in liquidity.get("results") or []
        if isinstance(row, dict) and row.get("flip_shadow_eligible")
    }
    weekly = _read_json(weekly_path)
    hot = [
        str(row.get("symbol") or "").upper()
        for row in weekly.get("hot_instruments") or []
        if isinstance(row, dict)
    ]
    ordered = ["SPY"] + [symbol for symbol in hot if symbol in eligible and symbol != "SPY"]
    ordered += [symbol for symbol in DEFAULT_SYMBOLS if symbol not in ordered]
    return list(dict.fromkeys(ordered))[:MAX_SYMBOLS]


def build_report(
    symbols: list[str] | None = None,
    *,
    fetcher: Callable[[str, date | None], dict[str, Any]] = fetch_snapshot,
    today: date | None = None,
) -> dict[str, Any]:
    today = today or date.today()
    symbols = list(dict.fromkeys(symbol.upper() for symbol in (symbols or default_symbols())))[:MAX_SYMBOLS]
    results = []
    for symbol in symbols:
        try:
            results.append(analyze_snapshot(fetcher(symbol, today), today=today))
        except Exception as exc:
            results.append({"symbol": symbol, "status": "unavailable", "reason": str(exc)[:180]})
    return {
        "provider": "options_surface_intelligence",
        "mode": "read_only_shadow_research",
        "execution_enabled": False,
        "can_submit_orders": False,
        "date": today.isoformat(),
        "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "symbol_count": len(symbols),
        "ok_count": sum(1 for row in results if row.get("status") == "ok"),
        "retail_lottery_risk_count": sum(1 for row in results if row.get("retail_lottery_risk")),
        "institutional_flow_available": False,
        "results": results,
        "warnings": [
            "Public chain volume is unsigned and must not be labeled smart-money buying or selling.",
            "This report cannot submit orders, change symbols, or alter entry and exit thresholds.",
            "Cheap premium is not cheap volatility; low-price, high-IV, wide-spread wings are flagged as lottery risk.",
            "Snapshot open interest can be delayed and volume is not a substitute for OPRA trade classification.",
        ],
    }


def write_report(report: dict[str, Any], path: Path = REPORT_PATH) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(temp, path)


def append_log(report: dict[str, Any], path: Path = LOG_PATH) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(report, separators=(",", ":"), sort_keys=True) + "\n")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("symbols", nargs="*")
    parser.add_argument("--report-path", type=Path, default=REPORT_PATH)
    parser.add_argument("--log-path", type=Path, default=LOG_PATH)
    parser.add_argument("--print", action="store_true", dest="do_print")
    args = parser.parse_args()
    report = build_report(args.symbols or None)
    write_report(report, args.report_path)
    append_log(report, args.log_path)
    if args.do_print:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        print(f"Options surface intelligence wrote {args.report_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

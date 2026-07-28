#!/usr/bin/env python3
"""Read-only option-chain liquidation and heat-map proxy.

Public equity option chains do not expose true forced-liquidation books. This
scanner uses observable open-interest, volume, implied move, and optional GEX
levels to map likely pin/magnet/pressure zones for shadow research only.
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
REPORT_PATH = REPORT_DIR / "options-liquidation-heatmap.json"
LOG_PATH = ROOT / "data" / "options_liquidation_heatmap_log.jsonl"
GEX_LOG_PATH = ROOT / "data" / "gex_scan_log.jsonl"

DEFAULT_SYMBOLS = ["SPY", "QQQ", "IWM", "NVDA", "AAPL", "TSLA", "PLTR"]
MAX_SYMBOLS = 10
MAX_EXPIRIES = 3
MAX_DTE = 45
NEAR_ZONE_PCT = 1.5


def _number(value: Any, default: float = 0.0) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return default
    return parsed if math.isfinite(parsed) else default


def _integer(value: Any, default: int = 0) -> int:
    return int(_number(value, float(default)))


def _mid(row: dict[str, Any]) -> float:
    bid = _number(row.get("bid"))
    ask = _number(row.get("ask"))
    if bid > 0 and ask >= bid:
        return (bid + ask) / 2
    return _number(row.get("lastPrice"))


def _sum(rows: list[dict[str, Any]], field: str) -> int:
    return sum(max(0, _integer(row.get(field))) for row in rows)


def _read_jsonl_latest(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    latest: dict[str, Any] = {}
    try:
        for raw in path.read_text(encoding="utf-8-sig").splitlines():
            raw = raw.strip()
            if not raw:
                continue
            row = json.loads(raw)
            if isinstance(row, dict):
                latest = row
    except (OSError, json.JSONDecodeError):
        return latest
    return latest


def _latest_gex_by_symbol(log_path: Path = GEX_LOG_PATH) -> dict[str, dict[str, Any]]:
    row = _read_jsonl_latest(log_path)
    scans = row.get("scans") if isinstance(row, dict) else []
    if not isinstance(scans, list):
        return {}
    return {
        str(scan.get("symbol") or "").upper(): scan
        for scan in scans
        if isinstance(scan, dict) and scan.get("status") == "ok"
    }


def _nearest(rows: list[dict[str, Any]], strike: float) -> dict[str, Any]:
    valid = [row for row in rows if _number(row.get("strike")) > 0]
    return min(valid, key=lambda row: abs(_number(row.get("strike")) - strike), default={})


def _zone_bias(call_oi: int, put_oi: int, call_volume: int, put_volume: int, spot: float, strike: float) -> str:
    above = strike >= spot
    oi_imbalance = call_oi - put_oi
    vol_imbalance = call_volume - put_volume
    if abs(oi_imbalance) < max(50, 0.10 * max(call_oi + put_oi, 1)):
        return "pin_magnet"
    if above and oi_imbalance > 0:
        return "call_wall_resistance_proxy"
    if not above and put_oi > call_oi:
        return "put_wall_support_proxy"
    if vol_imbalance > 0:
        return "call_activity_heat"
    if vol_imbalance < 0:
        return "put_activity_heat"
    return "two_sided_heat"


def _strike_zones(calls: list[dict[str, Any]], puts: list[dict[str, Any]], spot: float) -> list[dict[str, Any]]:
    strikes = sorted({
        _number(row.get("strike"))
        for row in calls + puts
        if _number(row.get("strike")) > 0
    })
    zones: list[dict[str, Any]] = []
    calls_by_strike = {_number(row.get("strike")): row for row in calls}
    puts_by_strike = {_number(row.get("strike")): row for row in puts}
    for strike in strikes:
        call = calls_by_strike.get(strike, {})
        put = puts_by_strike.get(strike, {})
        call_oi = max(0, _integer(call.get("openInterest")))
        put_oi = max(0, _integer(put.get("openInterest")))
        call_volume = max(0, _integer(call.get("volume")))
        put_volume = max(0, _integer(put.get("volume")))
        total_oi = call_oi + put_oi
        total_volume = call_volume + put_volume
        heat = total_oi + 0.35 * total_volume
        if heat <= 0:
            continue
        distance_pct = (strike / spot - 1) * 100 if spot > 0 else 0.0
        zones.append({
            "strike": round(strike, 3),
            "distance_pct": round(distance_pct, 3),
            "call_open_interest": call_oi,
            "put_open_interest": put_oi,
            "total_open_interest": total_oi,
            "call_volume": call_volume,
            "put_volume": put_volume,
            "total_volume": total_volume,
            "heat_score": round(heat, 2),
            "bias": _zone_bias(call_oi, put_oi, call_volume, put_volume, spot, strike),
        })
    zones.sort(key=lambda row: row["heat_score"], reverse=True)
    return zones


def analyze_expiry(
    *,
    symbol: str,
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
    implied_move = _mid(atm_call) + _mid(atm_put)
    zones = _strike_zones(calls, puts, spot)
    near = [row for row in zones if abs(_number(row.get("distance_pct"))) <= NEAR_ZONE_PCT]
    nearest_above = min((row for row in zones if _number(row.get("strike")) >= spot), key=lambda row: row["strike"] - spot, default=None)
    nearest_below = min((row for row in zones if _number(row.get("strike")) <= spot), key=lambda row: spot - row["strike"], default=None)
    call_oi = _sum(calls, "openInterest")
    put_oi = _sum(puts, "openInterest")
    call_volume = _sum(calls, "volume")
    put_volume = _sum(puts, "volume")
    heat_total = sum(_number(row.get("heat_score")) for row in zones)
    top_heat = _number(zones[0].get("heat_score")) if zones else 0.0
    if not zones:
        state = "unavailable"
    elif near and _number(near[0].get("heat_score")) / max(heat_total, 1.0) >= 0.08:
        state = "near_major_heat_zone"
    elif call_oi > put_oi * 1.4:
        state = "call_wall_dominant"
    elif put_oi > call_oi * 1.4:
        state = "put_wall_dominant"
    else:
        state = "two_sided_heat"
    return {
        "symbol": symbol,
        "expiry": expiry,
        "dte": dte,
        "status": "ok" if zones else "unavailable",
        "spot": round(spot, 4),
        "atm_strike": _number(atm_call.get("strike"), _number(atm_put.get("strike"))),
        "implied_move": round(implied_move, 4),
        "implied_move_pct": round(implied_move / spot * 100, 3) if spot > 0 else None,
        "call_open_interest": call_oi,
        "put_open_interest": put_oi,
        "put_call_open_interest_ratio": round(put_oi / call_oi, 3) if call_oi else None,
        "call_volume": call_volume,
        "put_volume": put_volume,
        "put_call_volume_ratio": round(put_volume / call_volume, 3) if call_volume else None,
        "heat_state": state,
        "heat_concentration_top_zone_pct": round(top_heat / heat_total * 100, 2) if heat_total > 0 else 0.0,
        "nearest_heat_zone_above": nearest_above,
        "nearest_heat_zone_below": nearest_below,
        "near_spot_heat_zones": near[:5],
        "top_heat_zones": zones[:10],
    }


def analyze_snapshot(snapshot: dict[str, Any], *, today: date | None = None, gex: dict[str, Any] | None = None) -> dict[str, Any]:
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
            symbol=symbol,
            spot=spot,
            expiry=str(chain.get("expiry") or ""),
            calls=calls,
            puts=puts,
            today=today,
        ))
    expiries.sort(key=lambda row: row["dte"])
    ok_expiries = [row for row in expiries if row.get("status") == "ok"]
    if not ok_expiries:
        return {"symbol": symbol, "status": "unavailable", "reason": "no_heat_zones", "spot": round(spot, 4)}
    front = ok_expiries[0]
    gex_wall = gex.get("gex_wall") if isinstance(gex, dict) and isinstance(gex.get("gex_wall"), dict) else {}
    front_top = front.get("top_heat_zones") if isinstance(front.get("top_heat_zones"), list) else []
    nearest_above = front.get("nearest_heat_zone_above") if isinstance(front.get("nearest_heat_zone_above"), dict) else {}
    nearest_below = front.get("nearest_heat_zone_below") if isinstance(front.get("nearest_heat_zone_below"), dict) else {}
    labels: list[str] = [str(front.get("heat_state") or "unknown")]
    if gex_wall:
        labels.append("gex_wall_available")
    if _number(front.get("put_call_open_interest_ratio")) >= 1.3:
        labels.append("put_oi_pressure")
    elif 0 < _number(front.get("put_call_open_interest_ratio")) <= 0.75:
        labels.append("call_oi_pressure")
    near_zones = front.get("near_spot_heat_zones") if isinstance(front.get("near_spot_heat_zones"), list) else []
    if near_zones:
        labels.append("spot_inside_heat_band")
    return {
        "symbol": symbol,
        "status": "ok",
        "mode": "read_only_shadow_research",
        "execution_enabled": False,
        "can_submit_orders": False,
        "spot": round(spot, 4),
        "snapshot_at": snapshot.get("snapshot_at"),
        "front_expiry": front.get("expiry"),
        "front_dte": front.get("dte"),
        "front_implied_move_pct": front.get("implied_move_pct"),
        "front_heat_state": front.get("heat_state"),
        "front_put_call_open_interest_ratio": front.get("put_call_open_interest_ratio"),
        "nearest_heat_zone_above": nearest_above,
        "nearest_heat_zone_below": nearest_below,
        "top_heat_zones": front_top[:6],
        "gex_wall": gex_wall or None,
        "condition_labels": labels,
        "expiries": ok_expiries,
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


def build_report(
    symbols: list[str] | None = None,
    *,
    fetcher: Callable[[str, date | None], dict[str, Any]] = fetch_snapshot,
    today: date | None = None,
    gex_by_symbol: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    today = today or date.today()
    symbols = list(dict.fromkeys(symbol.upper() for symbol in (symbols or DEFAULT_SYMBOLS)))[:MAX_SYMBOLS]
    gex_by_symbol = gex_by_symbol if gex_by_symbol is not None else _latest_gex_by_symbol()
    results = []
    for symbol in symbols:
        try:
            results.append(analyze_snapshot(
                fetcher(symbol, today),
                today=today,
                gex=gex_by_symbol.get(symbol, {}),
            ))
        except Exception as exc:
            results.append({"symbol": symbol, "status": "unavailable", "reason": str(exc)[:180]})
    ok = [row for row in results if row.get("status") == "ok"]
    return {
        "provider": "options_liquidation_heatmap",
        "mode": "read_only_shadow_research",
        "execution_enabled": False,
        "can_submit_orders": False,
        "institutional_liquidation_book_available": False,
        "date": today.isoformat(),
        "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "symbol_count": len(symbols),
        "ok_count": len(ok),
        "near_major_heat_zone_count": sum(1 for row in ok if row.get("front_heat_state") == "near_major_heat_zone"),
        "results": results,
        "warnings": [
            "This is a public option-chain proxy, not a true broker liquidation map.",
            "Open interest can be delayed; volume is unsigned and cannot prove buyer/seller initiation.",
            "Use heat zones as context for strike selection, pin risk, and sizing review only.",
            "This report cannot submit orders or change execution thresholds.",
        ],
    }


def write_report(report: dict[str, Any], path: Path = REPORT_PATH) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + f".tmp-{os.getpid()}-{datetime.now(timezone.utc).timestamp()}")
    temp.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(temp, path)


def append_log(report: dict[str, Any], path: Path = LOG_PATH) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(report, separators=(",", ":"), sort_keys=True) + "\n")


def print_report(report: dict[str, Any]) -> None:
    print(json.dumps(report, indent=2, sort_keys=True))


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
        print_report(report)
    else:
        print(f"Options liquidation heatmap wrote {args.report_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Shadow-only 0DTE expected-move context.

Normalizes the opening range and current displacement by the ATM implied
daily move. The output is research telemetry only and cannot place orders or
change execution gates.
"""
from __future__ import annotations

import argparse
import json
import math
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
VIBE_HOME = Path.home() / ".vibe-trading"
IVR_LOG_PATH = ROOT / "data" / "iv_history_log.jsonl"
OPENING_RANGE_LOG_PATH = ROOT / "data" / "opening_range_breadth_log.jsonl"
LOG_PATH = ROOT / "data" / "zero_dte_expected_move_context_log.jsonl"
REPORT_PATH = VIBE_HOME / "reports" / "zero-dte-expected-move-context.json"
DEFAULT_SYMBOLS = ["SPY", "QQQ", "IWM"]


def _safe_float(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    for raw in path.read_text(encoding="utf-8-sig").splitlines():
        try:
            row = json.loads(raw)
        except json.JSONDecodeError:
            continue
        if isinstance(row, dict):
            rows.append(row)
    return rows


def _latest_for_day(path: Path, day: str) -> dict[str, Any]:
    rows = [row for row in _read_jsonl(path) if str(row.get("date") or "")[:10] == day]
    return rows[-1] if rows else {}


def daily_expected_move(spot: float, annualized_iv: float) -> float | None:
    """One-standard-deviation daily move from annualized implied volatility."""
    if spot <= 0 or annualized_iv <= 0:
        return None
    return spot * annualized_iv / math.sqrt(252.0)


def classify_opening_range_fraction(fraction: float | None) -> str:
    """Research bins only; these labels are not execution thresholds."""
    if fraction is None:
        return "unavailable"
    if fraction < 0.20:
        return "compressed_under_20pct"
    if fraction <= 0.45:
        return "balanced_20_to_45pct"
    return "expanded_over_45pct"


def _scan_map(row: dict[str, Any]) -> dict[str, dict[str, Any]]:
    scans = row.get("scans") if isinstance(row, dict) else []
    if not isinstance(scans, list):
        return {}
    return {
        str(scan.get("symbol") or "").upper(): scan
        for scan in scans
        if isinstance(scan, dict) and scan.get("symbol")
    }


def build_symbol_context(symbol: str, iv_scan: dict[str, Any], orb_scan: dict[str, Any]) -> dict[str, Any]:
    symbol = symbol.upper()
    spot = _safe_float(iv_scan.get("spot"))
    iv = _safe_float(iv_scan.get("atm_iv"))
    high = _safe_float(orb_scan.get("opening_range_high"))
    low = _safe_float(orb_scan.get("opening_range_low"))
    latest = _safe_float(orb_scan.get("latest_close"))
    if None in {spot, iv, high, low, latest} or high < low:
        return {
            "symbol": symbol,
            "status": "unavailable",
            "reason": "missing_or_invalid_iv_or_opening_range",
        }

    expected = daily_expected_move(spot, iv)
    if expected is None or expected <= 0:
        return {"symbol": symbol, "status": "unavailable", "reason": "invalid_expected_move"}

    opening_width = high - low
    midpoint = (high + low) / 2.0
    displacement = abs(latest - midpoint)
    breakout_overshoot = max(latest - high, low - latest, 0.0)
    opening_fraction = opening_width / expected
    displacement_fraction = displacement / expected
    overshoot_fraction = breakout_overshoot / expected
    return {
        "symbol": symbol,
        "status": "ok",
        "source": "atm_iv_and_opening_range_logs",
        "spot": round(spot, 4),
        "atm_iv": round(iv, 6),
        "expected_move_points": round(expected, 4),
        "expected_move_pct": round(expected / spot * 100.0, 4),
        "opening_range_points": round(opening_width, 4),
        "opening_range_fraction": round(opening_fraction, 4),
        "opening_range_bucket": classify_opening_range_fraction(opening_fraction),
        "latest_close": round(latest, 4),
        "displacement_from_orb_midpoint_points": round(displacement, 4),
        "expected_move_consumed_fraction": round(displacement_fraction, 4),
        "breakout_overshoot_fraction": round(overshoot_fraction, 4),
        "opening_range_state": orb_scan.get("state"),
    }


def build_report(
    symbols: list[str] | None = None,
    *,
    day: str | None = None,
    ivr_path: Path = IVR_LOG_PATH,
    opening_range_path: Path = OPENING_RANGE_LOG_PATH,
) -> dict[str, Any]:
    day = day or date.today().isoformat()
    symbols = [symbol.upper() for symbol in (symbols or DEFAULT_SYMBOLS)]
    iv_row = _latest_for_day(ivr_path, day)
    orb_row = _latest_for_day(opening_range_path, day)
    iv_by_symbol = _scan_map(iv_row)
    orb_by_symbol = _scan_map(orb_row)
    scans = [
        build_symbol_context(symbol, iv_by_symbol.get(symbol, {}), orb_by_symbol.get(symbol, {}))
        for symbol in symbols
    ]
    return {
        "date": day,
        "timestamp": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "provider": "zero_dte_expected_move_context",
        "mode": "shadow_only_research",
        "execution_enabled": False,
        "can_submit_orders": False,
        "method": "spot * atm_iv / sqrt(252)",
        "symbols": symbols,
        "ok_count": sum(scan.get("status") == "ok" for scan in scans),
        "scans": scans,
        "source_paths": {"ivr": str(ivr_path), "opening_range": str(opening_range_path)},
        "warnings": [
            "Research context only. No orders or live gates are wired.",
            "Expected move is a one-standard-deviation estimate, not a price target or hard boundary.",
            "Opening-range buckets are preregistered hypotheses and require forward evidence before promotion.",
        ],
    }


def write_outputs(report: dict[str, Any], report_path: Path = REPORT_PATH, log_path: Path = LOG_PATH) -> None:
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(report, separators=(",", ":")) + "\n")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--symbols", default=",".join(DEFAULT_SYMBOLS))
    parser.add_argument("--day", default=date.today().isoformat())
    parser.add_argument("--print", action="store_true", dest="print_report")
    args = parser.parse_args()
    report = build_report([part.strip() for part in args.symbols.split(",") if part.strip()], day=args.day)
    write_outputs(report)
    if args.print_report:
        print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

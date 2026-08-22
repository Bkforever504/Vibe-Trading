#!/usr/bin/env python3
"""Observe NQ/MNQ 5-minute late opening-range break/retest sequences.

Research only. This module has no broker adapter and cannot submit orders.
The candidate is deliberately separate from the legacy 1-hour pullback log
because its short development sample is negative despite a positive recent
holdout.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, time, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from strategies.topstep_prop_bot import Candle, OpeningRangeConfig, build_late_orb_retest_signal, session_vwap

ET = ZoneInfo("America/New_York")
RTH_OPEN = time(9, 30)
RTH_CLOSE = time(16, 0)
LOG_PATH = ROOT / "data" / "nq_late_orb_retest_shadow_log.jsonl"
REPORT_PATH = Path.home() / ".vibe-trading" / "reports" / "nq-late-orb-retest-shadow.json"
CONFIG = OpeningRangeConfig(range_minutes=3, min_breakout_points=10.0, reward_risk=2.0)
TOLERANCE_TICKS = 8
STOP_TICKS = 80


def fetch_candles(ticker: str = "NQ=F") -> tuple[list[Candle], float | None]:
    try:
        import yfinance as yf
    except ImportError as exc:
        raise ImportError("yfinance is required for NQ shadow bars") from exc

    frame = yf.Ticker(ticker).history(period="5d", interval="5m", auto_adjust=True)
    if frame.empty:
        return [], None
    if frame.index.tz is None:
        frame.index = frame.index.tz_localize("UTC")
    frame.index = frame.index.tz_convert(ET)
    today = datetime.now(ET).date()
    prior = frame[frame.index.map(lambda ts: ts.date() < today and RTH_OPEN <= ts.time() < RTH_CLOSE)]
    prior_close = float(prior.iloc[-1]["Close"]) if not prior.empty else None
    current = frame[frame.index.map(lambda ts: ts.date() == today and RTH_OPEN <= ts.time() < RTH_CLOSE)]
    candles = [
        Candle(
            timestamp=ts.to_pydatetime().replace(tzinfo=None),
            open=float(row["Open"]),
            high=float(row["High"]),
            low=float(row["Low"]),
            close=float(row["Close"]),
            volume=int(row.get("Volume") or 0),
        )
        for ts, row in current.iterrows()
    ]
    return candles, prior_close


def build_snapshot(
    candles: list[Candle],
    prior_close: float | None,
    *,
    symbol: str = "MNQ",
    observed_at: datetime | None = None,
) -> dict[str, Any]:
    observed_at = observed_at or datetime.now(timezone.utc)
    report: dict[str, Any] = {
        "schema_version": 1,
        "provider": "nq_late_orb_retest_shadow",
        "timestamp": observed_at.isoformat().replace("+00:00", "Z"),
        "symbol": symbol,
        "timeframe": "5m",
        "mode": "shadow_only",
        "execution_enabled": False,
        "can_submit_orders": False,
        "bars": len(candles),
        "state": "insufficient_data",
        "signal": None,
        "evidence_status": "recent_holdout_candidate_not_validated",
    }
    if len(candles) <= CONFIG.range_minutes + 1 or prior_close is None or prior_close <= 0:
        return report

    gap_pct = (candles[0].open - prior_close) / prior_close
    gap_side = "buy" if gap_pct > 0 else "sell" if gap_pct < 0 else None
    report["prior_close"] = round(prior_close, 2)
    report["gap_pct"] = round(gap_pct, 6)
    report["gap_side"] = gap_side
    result = build_late_orb_retest_signal(
        candles,
        CONFIG,
        symbol=symbol,
        pullback_tolerance_ticks=TOLERANCE_TICKS,
        pullback_stop_ticks=STOP_TICKS,
    )
    if result is None:
        opening = candles[: CONFIG.range_minutes]
        range_high = max(bar.high for bar in opening)
        range_low = min(bar.low for bar in opening)
        report["opening_range_high"] = round(range_high, 2)
        report["opening_range_low"] = round(range_low, 2)
        for index in range(CONFIG.range_minutes, len(candles)):
            bar = candles[index]
            vwap = session_vwap(candles[: index + 1])
            side = None
            level = None
            if bar.close >= range_high + CONFIG.min_breakout_points and bar.close > vwap:
                side, level = "buy", range_high
            elif bar.close <= range_low - CONFIG.min_breakout_points and bar.close < vwap:
                side, level = "sell", range_low
            if side is None or level is None:
                continue
            future = candles[index + 1 :]
            excursion = (
                max((row.high for row in future), default=bar.close) - bar.close
                if side == "buy"
                else bar.close - min((row.low for row in future), default=bar.close)
            )
            closest_retest = (
                min((row.low - level for row in future), default=None)
                if side == "buy"
                else min((level - row.high for row in future), default=None)
            )
            report["state"] = "breakout_without_qualified_retest"
            report["missed_move_diagnostic"] = {
                "side": side,
                "breakout_time": bar.timestamp.isoformat(),
                "breakout_close": round(bar.close, 2),
                "level": round(level, 2),
                "gap_aligned": side == gap_side,
                "max_favorable_excursion_points": round(max(0.0, excursion), 2),
                "closest_retest_distance_points": (
                    round(closest_retest, 2) if closest_retest is not None else None
                ),
                "note": "Diagnostic only; no chase entry is authorized.",
            }
            return report
        report["state"] = "no_completed_breakout"
        return report

    signal, entry_idx = result
    if gap_side is None or signal.side != gap_side:
        report["state"] = "gap_direction_not_aligned"
        report["detected_side"] = signal.side
        return report

    report["state"] = "candidate_observed"
    report["signal"] = {
        "strategy": signal.strategy,
        "side": signal.side,
        "entry": round(signal.entry, 2),
        "stop": round(signal.stop, 2),
        "target": round(signal.target, 2),
        "entry_time": candles[entry_idx].timestamp.isoformat(),
        "entry_bar_index": entry_idx,
        "opening_range_high": round(signal.opening_range_high, 2),
        "opening_range_low": round(signal.opening_range_low, 2),
        "vwap": signal.vwap,
        "gap_aligned": True,
    }
    return report


def append_log(report: dict[str, Any], path: Path = LOG_PATH) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(report, separators=(",", ":")) + "\n")


def main() -> int:
    parser = argparse.ArgumentParser(description="NQ late ORB retest shadow scanner; no orders")
    parser.add_argument("--ticker", default="NQ=F")
    parser.add_argument("--symbol", default="MNQ")
    parser.add_argument("--log-path", type=Path, default=LOG_PATH)
    parser.add_argument("--report-path", type=Path, default=REPORT_PATH)
    parser.add_argument("--print", action="store_true", dest="print_output")
    args = parser.parse_args()
    candles, prior_close = fetch_candles(args.ticker)
    report = build_snapshot(candles, prior_close, symbol=args.symbol)
    append_log(report, args.log_path)
    args.report_path.parent.mkdir(parents=True, exist_ok=True)
    args.report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    if args.print_output:
        print(json.dumps(report, indent=2))
    else:
        print(f"NQ late ORB retest shadow: {report['state']} (no orders)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

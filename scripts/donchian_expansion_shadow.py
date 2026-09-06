#!/usr/bin/env python3
"""Completed-bar Donchian expansion observation lane.

This is an isolated U.S. shadow challenger inspired by the explicitly stated
candidate filter in Elicherla01/breakoutscanner. It is deliberately not a
trade strategy: it has no entry order, stop, target, sizing, alert, rank, or
execution authority. It only records a reproducible completed-RTH-bar event
for later point-in-time and walk-forward evaluation.
"""
from __future__ import annotations

import argparse
import sys
from datetime import datetime, time, timezone
from pathlib import Path
from typing import Any

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.intraday_opportunity_radar import CORE_LIQUID_SYMBOLS, MARKET_TZ, _finite, _read_json
from scripts.premarket_opportunity_radar import _atomic_json
from scripts.wolves_bbr_shadow import _fetch_bars, _parse_time

VIBE_HOME = Path.home() / ".vibe-trading"
RADAR_PATH = VIBE_HOME / "reports" / "intraday-opportunity-radar.json"
REPORT_PATH = VIBE_HOME / "reports" / "donchian-expansion-shadow.json"
MAX_SYMBOLS = 80
LOOKBACK_BARS = 20
VOLUME_MULTIPLE = 1.25
CLOSE_LOCATION_MIN = 0.60
ATR_PERIOD = 14
ATR_MULTIPLE = 1.20


def _frame(rows: list[dict[str, Any]]) -> pd.DataFrame:
    parsed: list[dict[str, Any]] = []
    for row in rows:
        stamp = _parse_time(row.get("t"))
        values = {key: _finite(row.get(key)) for key in ("o", "h", "l", "c", "v")}
        if stamp and all(value is not None for value in values.values()):
            parsed.append({"dt": stamp, **values})
    return pd.DataFrame(parsed).sort_values("dt").drop_duplicates("dt") if parsed else pd.DataFrame()


def assess_symbol(symbol: str, rows: list[dict[str, Any]], now_et: datetime) -> dict[str, Any]:
    """Evaluate only the latest fully completed regular-session five-minute bar."""
    frame = _frame(rows)
    if frame.empty:
        return {"symbol": symbol, "status": "unavailable", "reason": "no_completed_bars"}
    rth = frame[(frame.dt.dt.time >= time(9, 30)) & (frame.dt.dt.time < time(16, 0))].copy()
    rth["date"] = rth.dt.dt.date
    current = rth[rth.date == now_et.date()].copy()
    required = max(LOOKBACK_BARS, ATR_PERIOD) + 1
    if len(current) < required:
        return {"symbol": symbol, "status": "unavailable", "reason": "insufficient_completed_current_rth_bars", "completed_current_rth_bars": len(current), "required": required}
    last = current.iloc[-1]
    history = current.iloc[-(required + 1):-1].copy()
    if len(history) < required:
        return {"symbol": symbol, "status": "unavailable", "reason": "insufficient_prior_completed_bars"}
    donchian = history.iloc[-LOOKBACK_BARS:]
    prior_close = float(history.iloc[-1].c)
    bar_range = float(last.h) - float(last.l)
    if bar_range <= 0:
        return {"symbol": symbol, "status": "unavailable", "reason": "zero_range_completed_bar"}
    resistance, support = float(donchian.h.max()), float(donchian.l.min())
    avg_volume = float(donchian.v.mean())
    volume_multiple = float(last.v) / avg_volume if avg_volume > 0 else None
    close_location = (float(last.c) - float(last.l)) / bar_range
    true_range = max(bar_range, abs(float(last.h) - prior_close), abs(float(last.l) - prior_close))
    prior_true_ranges = [max(float(row.h) - float(row.l), abs(float(row.h) - float(prev.c)), abs(float(row.l) - float(prev.c))) for prev, row in zip(history.iloc[-(ATR_PERIOD + 1):-1].itertuples(), history.iloc[-ATR_PERIOD:].itertuples())]
    atr = sum(prior_true_ranges) / len(prior_true_ranges) if len(prior_true_ranges) == ATR_PERIOD else None
    atr_multiple = true_range / atr if atr and atr > 0 else None
    volume_pass = bool(volume_multiple is not None and volume_multiple >= VOLUME_MULTIPLE)
    range_pass = bool(atr_multiple is not None and atr_multiple > ATR_MULTIPLE)
    bullish_standard = float(last.c) > resistance and volume_pass and close_location >= CLOSE_LOCATION_MIN
    bearish_standard = float(last.c) < support and volume_pass and close_location <= 1 - CLOSE_LOCATION_MIN
    direction = "bullish" if bullish_standard and range_pass else "bearish" if bearish_standard and range_pass else "none"
    standard_direction = "bullish" if bullish_standard else "bearish" if bearish_standard else "none"
    blockers: list[str] = []
    if standard_direction == "none": blockers.append("no_prior_20_bar_close_break")
    if not volume_pass: blockers.append("relative_volume_below_1_25")
    if standard_direction == "bullish" and close_location < CLOSE_LOCATION_MIN: blockers.append("bullish_close_location_below_0_60")
    if standard_direction == "bearish" and close_location > 1 - CLOSE_LOCATION_MIN: blockers.append("bearish_close_location_above_0_40")
    if not range_pass: blockers.append("true_range_not_above_1_20x_prior_atr")
    return {"symbol": symbol, "status": "observed", "direction": direction, "standard_direction": standard_direction, "strict_expansion_hit": direction != "none", "candidate_coverage_only": direction != "none", "last_completed_bar_at": last["dt"].isoformat(), "signal_bar": {"open": round(float(last.o), 4), "high": round(float(last.h), 4), "low": round(float(last.l), 4), "close": round(float(last.c), 4)}, "levels": {"prior_20_bar_high": round(resistance, 4), "prior_20_bar_low": round(support, 4)}, "evidence": {"close": round(float(last.c), 4), "volume_multiple_vs_prior_20_completed_bars": round(volume_multiple, 4) if volume_multiple is not None else None, "close_location": round(close_location, 4), "true_range": round(true_range, 4), "prior_atr_14": round(atr, 4) if atr is not None else None, "true_range_multiple_vs_prior_atr_14": round(atr_multiple, 4) if atr_multiple is not None else None}, "thresholds": {"donchian_lookback_completed_bars": LOOKBACK_BARS, "relative_volume_min": VOLUME_MULTIPLE, "bullish_close_location_min": CLOSE_LOCATION_MIN, "bearish_close_location_max": 1 - CLOSE_LOCATION_MIN, "true_range_strictly_greater_than_prior_atr_multiple": ATR_MULTIPLE}, "blockers": blockers, "definition": "completed_rth_5m_prior_20_bar_donchian_break_relative_volume_close_location_true_range_expansion", "authority": "shadow_candidate_coverage_only_no_rank_alert_sizing_or_execution", "execution_enabled": False, "can_submit_orders": False}


def build_report(now_et: datetime | None = None, radar_path: Path = RADAR_PATH) -> dict[str, Any]:
    now_et = (now_et or datetime.now(timezone.utc).astimezone(MARKET_TZ)).astimezone(MARKET_TZ)
    radar = _read_json(radar_path)
    ranked = [str(row.get("symbol") or "").upper() for row in radar.get("ranked_candidates") or [] if isinstance(row, dict)]
    symbols = list(dict.fromkeys([*CORE_LIQUID_SYMBOLS, *ranked]))[:MAX_SYMBOLS]
    bars, errors = _fetch_bars(symbols, now_et)
    observations = [assess_symbol(symbol, bars.get(symbol, []), now_et) for symbol in symbols]
    hits = [row for row in observations if row.get("strict_expansion_hit")]
    unavailable = [row for row in observations if row.get("status") != "observed"]
    return {"schema_version": 1, "date": now_et.date().isoformat(), "as_of_et": now_et.isoformat(), "mode": "shadow_observation", "strategy_status": "unvalidated", "source": "Elicherla01_breakoutscanner_explicit_detection_logic_adapted_as_us_completed_bar_challenger", "coverage": {"symbols_requested": len(symbols), "observed": len(observations) - len(unavailable), "strict_hits": len(hits), "unavailable": len(unavailable), "unavailable_symbols": unavailable}, "rankings": hits, "observations": observations, "errors": errors, "execution_enabled": False, "can_submit_orders": False, "warning": "Candidate coverage only. This records a completed-bar signal without a claimed entry, stop, target, sizing, cost model, alert, ranking, or execution authority. Promotion requires a separate preregistered, cost-aware walk-forward and shadow evaluation."}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report-path", type=Path, default=REPORT_PATH)
    args = parser.parse_args()
    report = build_report()
    _atomic_json(args.report_path, report)
    print(f"Donchian expansion shadow: observed={report['coverage']['observed']} hits={report['coverage']['strict_hits']} errors={len(report['errors'])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

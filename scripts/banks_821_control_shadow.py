#!/usr/bin/env python3
"""Banks-style 8/21 control + level break/retest shadow observation.

This is a declared mechanical proxy for the public checklist, not a claim that
it reproduces any commercial product. It has no ranking, alert, sizing, or
order authority until separately validated.
"""
from __future__ import annotations

import argparse
import json
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
REPORT_PATH = VIBE_HOME / "reports" / "banks-821-control-shadow.json"
MAX_SYMBOLS = 80
EMA_RANGE_FRACTION = 0.0005
MOMENTUM_MULTIPLE = 1.25


def assess_symbol(symbol: str, rows: list[dict[str, Any]], now_et: datetime) -> dict[str, Any]:
    parsed = []
    for row in rows:
        stamp = _parse_time(row.get("t"))
        values = {key: _finite(row.get(key)) for key in ("o", "h", "l", "c", "v")}
        if stamp and all(value is not None for value in values.values()):
            parsed.append({"dt": stamp, **values})
    frame = pd.DataFrame(parsed).sort_values("dt").drop_duplicates("dt") if parsed else pd.DataFrame()
    if frame.empty:
        return {"symbol": symbol, "status": "unavailable", "reason": "no_completed_bars"}
    rth = frame[(frame.dt.dt.time >= time(9, 30)) & (frame.dt.dt.time < time(16))].copy()
    if len(rth) < 80:
        return {"symbol": symbol, "status": "unavailable", "reason": "insufficient_rth_history"}
    rth["date"] = rth.dt.dt.date
    prior_dates = sorted(day for day in rth.date.unique() if day < now_et.date())
    current = rth[rth.date == now_et.date()].copy()
    if not prior_dates or len(current) < 5:
        return {"symbol": symbol, "status": "unavailable", "reason": "prior_or_current_session_missing"}
    prior = rth[rth.date == prior_dates[-1]]
    current["ema8"] = rth.c.ewm(span=8, adjust=False).mean().tail(len(current)).to_numpy()
    current["ema21"] = rth.c.ewm(span=21, adjust=False).mean().tail(len(current)).to_numpy()
    last, previous = current.iloc[-1], current.iloc[-2]
    control_gap = abs(float(last.ema8) - float(last.ema21)) / max(float(last.c), 1e-9)
    long_control = float(last.c) > float(last.ema8) > float(last.ema21) and float(last.ema8) > float(previous.ema8)
    short_control = float(last.c) < float(last.ema8) < float(last.ema21) and float(last.ema8) < float(previous.ema8)
    levels = {"prior_day_high": float(prior.h.max()), "prior_day_low": float(prior.l.min()), "opening_range_high": float(current.iloc[:3].h.max()), "opening_range_low": float(current.iloc[:3].l.min())}
    long_level, short_level = max(levels["prior_day_high"], levels["opening_range_high"]), min(levels["prior_day_low"], levels["opening_range_low"])
    tolerance = max(float(last.c) * 0.0015, (long_level - short_level) * 0.05)
    recent = current.iloc[max(0, len(current) - 7):-1]
    long_retest = bool((recent.c > long_level).any() and float(last.l) <= long_level + tolerance and float(last.c) > long_level)
    short_retest = bool((recent.c < short_level).any() and float(last.h) >= short_level - tolerance and float(last.c) < short_level)
    prior_volume = float(current.iloc[max(0, len(current) - 4):-1].v.mean())
    momentum = float(last.v) >= prior_volume * MOMENTUM_MULTIPLE and abs(float(last.c) - float(last.o)) >= (float(last.h) - float(last.l)) * 0.45
    ema_crosses = sum((float(row.c) - float(row.ema8)) * (float(prev.c) - float(prev.ema8)) < 0 for prev, row in zip(current.iloc[-7:-1].itertuples(), current.iloc[-6:].itertuples()))
    no_trade = []
    if control_gap < EMA_RANGE_FRACTION: no_trade.append("8_21_range")
    if not momentum: no_trade.append("weak_momentum")
    if ema_crosses >= 3: no_trade.append("repeated_ema_chop")
    direction = "bullish" if long_control and long_retest and momentum and not no_trade else "bearish" if short_control and short_retest and momentum and not no_trade else "none"
    return {"symbol": symbol, "status": "observed", "direction": direction, "setup": "8_21_control_level_retest" if direction != "none" else "no_trade", "source_matched_proxy": direction != "none", "ema": {"ema8": round(float(last.ema8),4), "ema21": round(float(last.ema21),4), "gap_fraction": round(control_gap,6)}, "levels": {key: round(value,4) for key,value in levels.items()}, "momentum": {"passed": momentum, "volume_multiple": round(float(last.v)/prior_volume,3) if prior_volume else None}, "retest": {"long": long_retest, "short": short_retest, "tolerance": round(tolerance,4)}, "no_trade_reasons": no_trade, "last_completed_bar_at": last["dt"].isoformat(), "definition": "completed_5m_ema8_ema21_control_prior_day_or_opening_range_break_then_retest_with_volume_and_body_momentum", "authority": "shadow_only_no_rank_alert_sizing_or_execution", "execution_enabled": False, "can_submit_orders": False}


def build_report(now_et: datetime | None = None, radar_path: Path = RADAR_PATH) -> dict[str, Any]:
    now_et = (now_et or datetime.now(timezone.utc).astimezone(MARKET_TZ)).astimezone(MARKET_TZ)
    radar = _read_json(radar_path)
    ranked = [str(row.get("symbol") or "").upper() for row in radar.get("ranked_candidates") or [] if isinstance(row, dict)]
    symbols = list(dict.fromkeys([*CORE_LIQUID_SYMBOLS, *ranked]))[:MAX_SYMBOLS]
    bars, errors = _fetch_bars(symbols, now_et)
    observations = [assess_symbol(symbol, bars.get(symbol, []), now_et) for symbol in symbols]
    hits = [row for row in observations if row.get("source_matched_proxy")]
    return {"schema_version": 1, "date": now_et.date().isoformat(), "as_of_et": now_et.isoformat(), "mode": "shadow_observation", "strategy_status": "unvalidated", "source": "Banks_public_top_down_checklist_mechanical_proxy", "assumptions": ["8/21 is EMA8 versus EMA21 on completed 5-minute RTH bars", "key levels are prior-day high/low plus first-15-minute range", "momentum is 1.25x prior-three-bar volume plus a 45% body/range threshold"], "coverage": {"symbols_requested": len(symbols), "observed": sum(row.get("status") == "observed" for row in observations), "hits": len(hits)}, "observations": observations, "confluence_hits": hits, "errors": errors, "execution_enabled": False, "can_submit_orders": False, "warning": "This is a preregistered proxy derived from incomplete public descriptions. It must be tested independently and does not reproduce or validate any third-party performance claim."}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report-path", type=Path, default=REPORT_PATH)
    args = parser.parse_args()
    report = build_report()
    _atomic_json(args.report_path, report)
    print(f"Banks 8/21 shadow: observed={report['coverage']['observed']} hits={report['coverage']['hits']} errors={len(report['errors'])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

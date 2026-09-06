#!/usr/bin/env python3
"""Shadow-observe a scheduled JOLTS + ISM 10:00 ET reaction to a 30m SPY OR.

This is deliberately separate from ordinary ORB scanners, which retain their
macro-event protections.  It records only completed bars and has no ranking,
alert, sizing, broker, or option-contract authority.
"""
from __future__ import annotations

import argparse
import json
from datetime import date, datetime, time, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping
from zoneinfo import ZoneInfo

import pandas as pd
import requests
import yfinance as yf

try:
    from scripts.market_catalyst_calendar import events_for_date
    from scripts.intraday_opportunity_radar import _credentials
except ModuleNotFoundError:
    from market_catalyst_calendar import events_for_date
    from intraday_opportunity_radar import _credentials


ROOT = Path(__file__).resolve().parents[1]
VIBE_HOME = Path.home() / ".vibe-trading"
REPORT_PATH = VIBE_HOME / "reports" / "macro-release-30m-orb-shadow.json"
LOG_PATH = ROOT / "data" / "macro_release_30m_orb_shadow_log.jsonl"
ET = ZoneInfo("America/New_York")
SYMBOL = "SPY"
BUFFER_DOLLARS = 0.05
BUFFER_FRACTION = 0.0002
VOLUME_MULTIPLE = 1.20
TARGET_R = 1.5
TIME_EXIT = time(11, 30)


def _prepared(frame: pd.DataFrame, session: date) -> pd.DataFrame:
    required = {"Open", "High", "Low", "Close", "Volume"}
    if frame is None or frame.empty or not required.issubset(frame.columns):
        return pd.DataFrame(columns=sorted(required))
    output = frame.loc[:, sorted(required)].copy()
    index = pd.to_datetime(output.index, errors="coerce", utc=True)
    output = output.loc[index.notna()].copy()
    output.index = index[index.notna()].tz_convert(ET)
    output = output[output.index.date == session].sort_index()
    return output


def dual_release(events: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    rows = [dict(row) for row in events if str(row.get("time_et")) == "10:00"]
    names = " ".join(str(row.get("name") or "").lower() for row in rows)
    return rows if "jolts" in names and "ism manufacturing" in names else []


def evaluate_session(
    frame: pd.DataFrame,
    session: date,
    events: Iterable[Mapping[str, Any]],
    *,
    prior_release_volumes: Iterable[float] = (),
) -> dict[str, Any]:
    releases = dual_release(events)
    base = {
        "strategy_id": "macro_dual_release_30m_orb_v1",
        "symbol": SYMBOL,
        "session_date": session.isoformat(),
        "mode": "shadow_only",
        "execution_enabled": False,
        "can_submit_orders": False,
        "rank_effect": "none",
        "promotion_eligible": False,
        "release_events": releases,
    }
    if not releases:
        return base | {"should_observe": False, "reason": "dual_10am_primary_release_not_scheduled"}
    bars = _prepared(frame, session)
    if bars.empty or not isinstance(bars.index, pd.DatetimeIndex):
        return base | {"should_observe": False, "reason": "incomplete_completed_1m_bars", "opening_bars": 0, "reaction_bars": 0}
    opening = bars.between_time("09:30", "09:59")
    reaction = bars.between_time("10:00", "10:04")
    if len(opening) != 30 or len(reaction) != 5:
        return base | {"should_observe": False, "reason": "incomplete_completed_1m_bars", "opening_bars": len(opening), "reaction_bars": len(reaction)}
    or_high, or_low = float(opening["High"].max()), float(opening["Low"].min())
    close = float(reaction.iloc[-1]["Close"])
    volume = float(reaction["Volume"].sum())
    baseline_values = [float(value) for value in prior_release_volumes if float(value) > 0]
    baseline = float(pd.Series(baseline_values).median()) if len(baseline_values) >= 20 else None
    buffer = max(BUFFER_DOLLARS, or_high * BUFFER_FRACTION)
    direction = "long" if close >= or_high + buffer else "short" if close <= or_low - buffer else None
    volume_pass = baseline is not None and volume >= baseline * VOLUME_MULTIPLE
    result = base | {
        "should_observe": True,
        "reason": "awaiting_volume_baseline" if baseline is None else "qualified_shadow_candidate" if direction and volume_pass else "release_reaction_not_confirmed",
        "opening_range": {"high": round(or_high, 4), "low": round(or_low, 4), "width": round(or_high - or_low, 4)},
        "reaction_bar": {"start_et": "10:00", "completed_at_et": "10:05", "close": round(close, 4), "volume": round(volume, 2)},
        "breakout_buffer": round(buffer, 4),
        "volume_baseline": round(baseline, 2) if baseline is not None else None,
        "volume_pass": volume_pass,
        "direction": direction,
        "entry_assumption": "next_completed_1m_bar_open_at_10_05_et_only_if_all_frozen_gates_pass",
        "stop_assumption": "opposite_30m_opening_range_boundary",
        "target_assumption_r": TARGET_R,
        "time_exit_et": TIME_EXIT.strftime("%H:%M"),
        "intrabar_ambiguity": "stop_first",
    }
    return result


def fetch_spy_1m(now: datetime) -> tuple[pd.DataFrame, str]:
    """Prefer the radar's authenticated IEX minute feed; yfinance is fallback."""
    now_et = now.astimezone(ET)
    alpaca_status = "not_attempted"
    session_start = datetime.combine(now_et.date(), time(9, 30), ET)
    session_end = min(
        now_et.replace(second=0, microsecond=0),
        datetime.combine(now_et.date(), time(16, 0), ET),
    )
    if session_end > session_start:
        try:
            response = requests.get(
                "https://data.alpaca.markets/v2/stocks/bars",
                headers=_credentials(),
                params={
                    "symbols": SYMBOL,
                    "timeframe": "1Min",
                    "start": session_start.astimezone(timezone.utc).isoformat().replace("+00:00", "Z"),
                    "end": session_end.astimezone(timezone.utc).isoformat().replace("+00:00", "Z"),
                    "adjustment": "raw",
                    "feed": "iex",
                    "limit": 10000,
                    "sort": "asc",
                },
                timeout=20,
            )
            response.raise_for_status()
            rows = (response.json().get("bars") or {}).get(SYMBOL) or []
            if rows:
                frame = pd.DataFrame(rows).rename(columns={"o": "Open", "h": "High", "l": "Low", "c": "Close", "v": "Volume", "t": "timestamp"})
                frame.index = pd.to_datetime(frame.pop("timestamp"), utc=True)
                return frame, "alpaca_iex_1m_completed_bar_proxy"
        except Exception as exc:
            alpaca_status = f"unavailable_{type(exc).__name__}"
    try:
        return (
            yf.Ticker(SYMBOL).history(period="5d", interval="1m", auto_adjust=False),
            f"yfinance_1m_proxy_non_executable_alpaca_iex_{alpaca_status}",
        )
    except Exception as exc:
        return pd.DataFrame(), f"minute_bar_providers_unavailable_alpaca_iex_{alpaca_status}_yfinance_{type(exc).__name__}"


def build_report(*, now: datetime | None = None, frame: pd.DataFrame | None = None) -> dict[str, Any]:
    now = now or datetime.now(timezone.utc)
    session = now.astimezone(ET).date()
    if frame is None:
        bars, data_source = fetch_spy_1m(now)
    else:
        bars, data_source = frame, "injected_test_frame"
    # The first version cannot fabricate the required 20 historical dual-release
    # baselines from a five-day proxy download. It records this as a blocker.
    decision = evaluate_session(bars, session, events_for_date(session))
    return {
        "schema_version": 1,
        "generated_at": now.astimezone(timezone.utc).isoformat().replace("+00:00", "Z"),
        "preregistration": "research/MACRO_RELEASE_30M_ORB_RESEARCH_2026-09-01.md",
        "data_source": data_source,
        "decision": decision,
        "execution_enabled": False,
        "can_submit_orders": False,
        "rank_effect": "none",
        "promotion_eligible": False,
        "warning": "SPY underlying shadow observation only; it does not imply an SPX/SPXW option fill or return.",
    }


def _append(report: Mapping[str, Any], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(dict(report), sort_keys=True, separators=(",", ":")) + "\n")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=REPORT_PATH)
    parser.add_argument("--log", type=Path, default=LOG_PATH)
    args = parser.parse_args()
    report = build_report()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    _append(report, args.log)
    decision = report["decision"]
    print(f"Macro 30m ORB shadow: {decision['reason']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Dynamic large-event-gap continuation scanner (shadow only).

Premarket-radar, social, and deep-universe reports are used only to discover symbols. A candidate
exists only when completed intraday price/volume bars satisfy the mechanical
sequence. This module has no broker imports and no order authority.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import re
import sys
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from typing import Any

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

VIBE_HOME = Path.home() / ".vibe-trading"
REPORT_PATH = VIBE_HOME / "reports" / "event-gap-continuation-shadow.json"
LOG_PATH = ROOT / "data" / "event_gap_continuation_shadow_log.jsonl"
SOCIAL_LOG_PATH = ROOT / "data" / "social_trending_symbols_log.jsonl"
DEEP_LOG_PATH = ROOT / "data" / "deep_liquid_universe_scan_log.jsonl"
PREMARKET_RADAR_PATH = VIBE_HOME / "reports" / "premarket-opportunity-radar.json"

MIN_GAP_PCT = 0.06
MAX_GAP_PCT = 2.00
MIN_BREAKOUT_VOLUME_RATIO = 1.35
MIN_DIRECTIONAL_RELATIVE_PCT = 0.02
MAX_VWAP_EXTENSION_PCT = 0.08
OPENING_RANGE_BARS = 3
TARGET_R = 2.0


def _valid_equity_symbol(value: Any) -> str | None:
    symbol = str(value or "").upper().strip()
    return symbol if re.fullmatch(r"[A-Z]{1,5}", symbol) else None


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    try:
        lines = path.read_text(encoding="utf-8-sig").splitlines()
    except OSError:
        return []
    rows: list[dict[str, Any]] = []
    for raw in lines:
        try:
            row = json.loads(raw)
        except json.JSONDecodeError:
            continue
        if isinstance(row, dict):
            rows.append(row)
    return rows


def _read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def dynamic_symbol_discovery(
    *,
    as_of: date,
    social_path: Path = SOCIAL_LOG_PATH,
    deep_path: Path = DEEP_LOG_PATH,
    radar_path: Path = PREMARKET_RADAR_PATH,
    limit: int = 24,
) -> list[dict[str, Any]]:
    """Return same-session symbol nominations with explicit source provenance.

    Discovery sources may nominate attention only. Price/volume confirmation in
    ``evaluate_event_gap`` remains the sole creator of a shadow candidate.
    """
    scored: dict[str, float] = {}
    sources: dict[str, set[str]] = {}
    today = as_of.isoformat()

    def nominate(symbol: str, score: float, source: str) -> None:
        scored[symbol] = max(scored.get(symbol, 0.0), score)
        sources.setdefault(symbol, set()).add(source)

    radar = _read_json(radar_path)
    if str(radar.get("date") or "") == today and radar.get("session_status") == "premarket_scan_window":
        for item in radar.get("observations") or []:
            if not isinstance(item, dict) or item.get("lane") != "event_gap":
                continue
            symbol = _valid_equity_symbol(item.get("symbol"))
            if symbol:
                priority = {"high": 300.0, "medium": 250.0, "observe": 200.0}.get(str(item.get("priority")), 0.0)
                nominate(symbol, priority + float(item.get("score") or 0.0), "premarket_radar")
    social_rows = _read_jsonl(social_path)
    for row in reversed(social_rows):
        if str(row.get("date") or "")[:10] != today:
            continue
        for item in row.get("symbols") or []:
            if not isinstance(item, dict):
                continue
            symbol = _valid_equity_symbol(item.get("symbol"))
            if symbol:
                rank = float(item.get("rank") or 999)
                nominate(symbol, 100.0 - rank, "social_trending")
        break

    deep_rows = _read_jsonl(deep_path)
    for row in reversed(deep_rows):
        if str(row.get("date") or row.get("timestamp") or "")[:10] != today:
            continue
        for item in row.get("top_candidates") or row.get("scans") or []:
            if not isinstance(item, dict):
                continue
            symbol = _valid_equity_symbol(item.get("symbol"))
            if symbol:
                nominate(symbol, float(item.get("deep_score") or 0.0), "deep_liquid_universe")
        break
    return [
        {
            "symbol": symbol,
            "score": round(score, 4),
            "sources": sorted(sources.get(symbol, set())),
            "as_of": today,
            "authority": "discovery_only_no_directional_or_execution_authority",
        }
        for symbol, score in sorted(scored.items(), key=lambda item: (-item[1], item[0]))[:limit]
    ]


def dynamic_symbols(
    *,
    as_of: date,
    social_path: Path = SOCIAL_LOG_PATH,
    deep_path: Path = DEEP_LOG_PATH,
    radar_path: Path = PREMARKET_RADAR_PATH,
    limit: int = 24,
) -> list[str]:
    """Compatibility wrapper returning only the ranked ticker list."""
    return [
        row["symbol"]
        for row in dynamic_symbol_discovery(
            as_of=as_of,
            social_path=social_path,
            deep_path=deep_path,
            radar_path=radar_path,
            limit=limit,
        )
    ]


def _normalize(frame: pd.DataFrame) -> pd.DataFrame:
    if frame is None or frame.empty:
        return pd.DataFrame()
    out = frame.copy()
    out.columns = [str(column).lower() for column in out.columns]
    required = ["open", "high", "low", "close", "volume"]
    if not set(required).issubset(out.columns):
        return pd.DataFrame()
    out = out[required].apply(pd.to_numeric, errors="coerce").dropna()
    out.index = pd.to_datetime(out.index)
    return out.sort_index()


def _post_entry_outcome(
    frame: pd.DataFrame,
    *,
    entry_index: int,
    direction: str,
    entry: float,
    stop: float,
    target: float,
) -> dict[str, Any]:
    """Resolve only bars after entry; same-bar ambiguity is stop-first."""
    for index in range(entry_index + 1, len(frame)):
        bar = frame.iloc[index]
        stop_hit = float(bar["low"]) <= stop if direction == "bull" else float(bar["high"]) >= stop
        target_hit = float(bar["high"]) >= target if direction == "bull" else float(bar["low"]) <= target
        if stop_hit:
            return {"status": "stop", "time": str(frame.index[index]), "exit": round(stop, 4), "realized_r": -1.0}
        if target_hit:
            return {"status": "target", "time": str(frame.index[index]), "exit": round(target, 4), "realized_r": TARGET_R}
    mark = float(frame["close"].iloc[-1])
    risk = abs(entry - stop)
    open_r = ((mark - entry) if direction == "bull" else (entry - mark)) / risk if risk > 0 else 0.0
    return {"status": "open", "time": str(frame.index[-1]), "mark": round(mark, 4), "open_r": round(open_r, 4)}


def evaluate_event_gap(
    bars: pd.DataFrame,
    *,
    previous_close: float,
    benchmark_bars: pd.DataFrame,
    symbol: str,
) -> dict[str, Any]:
    """Evaluate a causal 15-minute event-gap breakout using completed bars."""
    same_slot_volume = dict(getattr(bars, "attrs", {}).get("same_slot_volume_baseline") or {})
    base = {
        "symbol": symbol,
        "eligible": False,
        "execution_enabled": False,
        "can_submit_orders": False,
        "formula_version": "event_gap_or15_break_vwap_same_slot_volume_v2",
    }
    frame = _normalize(bars)
    benchmark = _normalize(benchmark_bars)
    if previous_close <= 0 or len(frame) < OPENING_RANGE_BARS + 1 or len(benchmark) < OPENING_RANGE_BARS + 1:
        return {**base, "state": "insufficient_completed_bars"}

    opening = frame.iloc[:OPENING_RANGE_BARS]
    opening_high = float(opening["high"].max())
    opening_low = float(opening["low"].min())
    session_open = float(frame["open"].iloc[0])
    gap_return = session_open / previous_close - 1.0
    gap_magnitude = abs(gap_return)
    direction = "bull" if gap_return > 0 else "bear"
    sign = 1.0 if direction == "bull" else -1.0
    if not MIN_GAP_PCT <= gap_magnitude <= MAX_GAP_PCT:
        return {
            **base,
            "state": "gap_outside_event_band",
            "direction": direction,
            "gap_pct": round(gap_return * 100.0, 3),
            "opening_range_high": round(opening_high, 4),
            "opening_range_low": round(opening_low, 4),
        }

    typical = (frame["high"] + frame["low"] + frame["close"]) / 3.0
    cumulative_volume = frame["volume"].cumsum().replace(0, float("nan"))
    vwap = (typical * frame["volume"]).cumsum() / cumulative_volume
    baseline_volume = float(opening["volume"].median())
    benchmark_open = float(benchmark["open"].iloc[0])

    observations: list[dict[str, Any]] = []
    for index in range(OPENING_RANGE_BARS, len(frame)):
        bar = frame.iloc[index]
        bar_vwap = float(vwap.iloc[index])
        close = float(bar["close"])
        benchmark_index = min(index, len(benchmark) - 1)
        benchmark_return = float(benchmark["close"].iloc[benchmark_index]) / benchmark_open - 1.0
        symbol_return = close / session_open - 1.0
        directional_relative = sign * (symbol_return - benchmark_return)
        slot_key = frame.index[index].strftime("%H:%M")
        slot_volume = float(same_slot_volume.get(slot_key) or baseline_volume)
        volume_ratio = float(bar["volume"]) / slot_volume if slot_volume > 0 else 0.0
        vwap_extension = abs(close - bar_vwap) / bar_vwap if bar_vwap > 0 else math.inf
        breakout = close > opening_high if direction == "bull" else close < opening_low
        vwap_aligned = close > bar_vwap if direction == "bull" else close < bar_vwap
        observations.append(
            {
                "time": str(frame.index[index]),
                "breakout": breakout,
                "vwap_aligned": vwap_aligned,
                "volume_ratio": round(volume_ratio, 3),
                "directional_relative_pct": round(directional_relative * 100.0, 3),
                "vwap_extension_pct": round(vwap_extension * 100.0, 3),
            }
        )
        if not (
            breakout
            and vwap_aligned
            and volume_ratio >= MIN_BREAKOUT_VOLUME_RATIO
            and directional_relative >= MIN_DIRECTIONAL_RELATIVE_PCT
            and vwap_extension <= MAX_VWAP_EXTENSION_PCT
        ):
            continue

        entry = close
        stop = min(float(bar["low"]), opening_high) if direction == "bull" else max(float(bar["high"]), opening_low)
        risk = entry - stop if direction == "bull" else stop - entry
        if risk <= 0:
            continue
        target = entry + TARGET_R * risk if direction == "bull" else entry - TARGET_R * risk
        post_entry_outcome = _post_entry_outcome(
            frame,
            entry_index=index,
            direction=direction,
            entry=entry,
            stop=stop,
            target=target,
        )
        return {
            **base,
            "eligible": True,
            "state": "shadow_candidate",
            "variant": "event_gap_and_go_or15_break",
            "direction": direction,
            "gap_pct": round(gap_return * 100.0, 3),
            "opening_range_high": round(opening_high, 4),
            "opening_range_low": round(opening_low, 4),
            "entry_time": str(frame.index[index]),
            "entry": round(entry, 4),
            "stop": round(stop, 4),
            "target": round(target, 4),
            "risk_points": round(risk, 4),
            "volume_ratio": round(volume_ratio, 3),
            "directional_relative_pct": round(directional_relative * 100.0, 3),
            "vwap": round(bar_vwap, 4),
            "vwap_extension_pct": round(vwap_extension * 100.0, 3),
            "post_entry_outcome": post_entry_outcome,
            "post_entry_outcome_uses_future_bars_for_evaluation_only": True,
            "evidence_status": "unvalidated_shadow_hypothesis",
        }

    breakout_seen = any(row["breakout"] for row in observations)
    breakout_observations = [row for row in observations if row["breakout"]]
    return {
        **base,
        "state": "breakout_without_confluence" if breakout_seen else "no_completed_opening_range_breakout",
        "direction": direction,
        "gap_pct": round(gap_return * 100.0, 3),
        "opening_range_high": round(opening_high, 4),
        "opening_range_low": round(opening_low, 4),
        "breakout_observations": breakout_observations[:12],
        "last_observation": observations[-1] if observations else None,
    }


def _completed_rth_sessions(raw: pd.DataFrame, now_et: datetime) -> tuple[pd.DataFrame, float]:
    frame = _normalize(raw)
    if frame.empty:
        return pd.DataFrame(), 0.0
    if frame.index.tz is None:
        frame.index = frame.index.tz_localize("America/New_York")
    else:
        frame.index = frame.index.tz_convert("America/New_York")
    complete = frame[frame.index + pd.Timedelta(minutes=5) <= now_et]
    rth = complete.between_time("09:30", "15:59")
    prior = rth[rth.index.date < now_et.date()]
    today = rth[rth.index.date == now_et.date()]
    if not prior.empty:
        slot_keys = prior.index.strftime("%H:%M")
        slot_baseline = prior.assign(_slot=slot_keys).groupby("_slot")["volume"].median().to_dict()
        today.attrs["same_slot_volume_baseline"] = {
            str(key): float(value) for key, value in slot_baseline.items()
        }
    return today, float(prior["close"].iloc[-1]) if not prior.empty else 0.0


def fetch_intraday(symbol: str, now_et: datetime) -> tuple[pd.DataFrame, float]:
    import yfinance as yf

    raw = yf.Ticker(symbol).history(period="5d", interval="5m", auto_adjust=False, prepost=False)
    return _completed_rth_sessions(raw, now_et)


def build_report(
    symbols: list[str],
    *,
    now_et: datetime | None = None,
    discovery: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    now_et = now_et or datetime.now(timezone.utc).astimezone()
    if now_et.tzinfo is None:
        raise ValueError("now_et must be timezone-aware")
    try:
        from zoneinfo import ZoneInfo

        now_et = now_et.astimezone(ZoneInfo("America/New_York"))
    except Exception:
        pass
    benchmark, _benchmark_previous = fetch_intraday("SPY", now_et)
    discovery_by_symbol = {
        str(row.get("symbol") or "").upper(): row
        for row in (discovery or [])
        if isinstance(row, dict) and row.get("symbol")
    }
    observations: list[dict[str, Any]] = []
    failures: dict[str, str] = {}
    for symbol in symbols:
        if symbol == "SPY":
            continue
        try:
            bars, previous_close = fetch_intraday(symbol, now_et)
            result = evaluate_event_gap(
                bars,
                previous_close=previous_close,
                benchmark_bars=benchmark,
                symbol=symbol,
            )
            provenance = discovery_by_symbol.get(symbol)
            if provenance:
                result["discovery_provenance"] = provenance
            observations.append(result)
        except Exception as exc:
            failures[symbol] = str(exc)[:180]
    return {
        "schema_version": 1,
        "provider": "event_gap_continuation_shadow",
        "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "date": now_et.date().isoformat(),
        "mode": "shadow_only",
        "execution_enabled": False,
        "can_submit_orders": False,
        "symbol_discovery_only": True,
        "social_can_create_trade": False,
        "symbols": symbols,
        "discovery": discovery or [],
        "candidates": [row for row in observations if row.get("eligible")],
        "observations": observations,
        "fetch_failures": failures,
        "warnings": [
            "No broker imports and no order authority.",
            "Large gaps are event risk; this lane is not promoted.",
            "Options marks are not used because extreme gaps can leave stale or non-executable quotes.",
        ],
    }


def write_report(report: dict[str, Any], report_path: Path, log_path: Path) -> None:
    report_path.parent.mkdir(parents=True, exist_ok=True)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    temp = report_path.with_suffix(report_path.suffix + ".tmp")
    temp.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(temp, report_path)
    with log_path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(report, separators=(",", ":"), sort_keys=True) + "\n")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--symbols", default="")
    parser.add_argument("--report-path", type=Path, default=REPORT_PATH)
    parser.add_argument("--log-path", type=Path, default=LOG_PATH)
    parser.add_argument("--print", action="store_true", dest="print_report")
    args = parser.parse_args()
    try:
        from zoneinfo import ZoneInfo

        today = datetime.now(timezone.utc).astimezone(ZoneInfo("America/New_York")).date()
    except Exception:
        today = date.today()
    symbols = [part.strip().upper() for part in args.symbols.split(",") if part.strip()]
    discovery: list[dict[str, Any]] = []
    if not symbols:
        discovery = dynamic_symbol_discovery(as_of=today)
        symbols = [row["symbol"] for row in discovery]
    report = build_report(list(dict.fromkeys(symbols)), discovery=discovery)
    write_report(report, args.report_path, args.log_path)
    if args.print_report:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        print(f"Event-gap shadow report wrote {args.report_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

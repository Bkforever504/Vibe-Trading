#!/usr/bin/env python3
"""Resolve completed pattern-grader horizons into an append-only companion ledger."""
from __future__ import annotations

import argparse
import json
import math
import sys
from datetime import datetime, time as wall_time, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Iterable
from zoneinfo import ZoneInfo

import requests

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.premarket_opportunity_radar import _credentials

MARKET_TZ = ZoneInfo("America/New_York")
SOURCE_LEDGER = ROOT / "data" / "pattern_grader_log.jsonl"
OUTCOME_LEDGER = ROOT / "data" / "pattern_grader_outcomes.jsonl"
HORIZONS = {"outcome_5m": timedelta(minutes=5), "outcome_15m": timedelta(minutes=15), "outcome_60m": timedelta(minutes=60)}
BarLoader = Callable[[str, datetime, datetime], list[dict[str, Any]]]
GRADE_PRIORITY = {"A+": 5, "A": 4, "B": 3, "C": 2, "D": 1}


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    try:
        lines = path.read_text(encoding="utf-8-sig").splitlines()
    except OSError:
        return []
    output: list[dict[str, Any]] = []
    for line in lines:
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(row, dict):
            output.append(row)
    return output


def _dt(value: Any) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _number(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _detection_id(row: dict[str, Any]) -> str:
    explicit = row.get("detection_id") or row.get("event_id") or row.get("candidate_id")
    if explicit:
        return str(explicit)
    return "|".join(str(row.get(key) or "") for key in ("pattern_id", "symbol", "direction", "trigger_bar_ts"))


def _geometry(row: dict[str, Any]) -> tuple[str, float, float] | None:
    nested = row.get("pattern") if isinstance(row.get("pattern"), dict) else {}
    direction = str(row.get("direction") or nested.get("direction") or "").lower()
    entry = _number(row.get("trigger") if row.get("trigger") is not None else row.get("entry"))
    stop = _number(row.get("invalidation") if row.get("invalidation") is not None else row.get("stop"))
    if direction not in {"bullish", "bearish", "long", "short"} or entry is None or stop is None or entry == stop:
        return None
    return ("bullish" if direction in {"bullish", "long"} else "bearish", entry, stop)


def _bar_close(row: dict[str, Any]) -> datetime | None:
    explicit = _dt(row.get("bar_close_ts") or row.get("close_ts"))
    if explicit is not None:
        return explicit
    start = _dt(row.get("t") or row.get("timestamp"))
    return start + timedelta(minutes=5) if start is not None else None


def _eod_deadline(trigger: datetime) -> datetime:
    local = trigger.astimezone(MARKET_TZ)
    return datetime.combine(local.date(), wall_time(16, 0), MARKET_TZ).astimezone(timezone.utc)


def _simulate(bars: Iterable[dict[str, Any]], *, direction: str, entry: float, stop: float, deadline: datetime, trigger: datetime) -> dict[str, Any] | None:
    risk = abs(entry - stop)
    sign = 1.0 if direction == "bullish" else -1.0
    t1, t2 = entry + sign * risk, entry + sign * risk * 2.0
    eligible = sorted(
        ((stamp, row) for row in bars if (stamp := _bar_close(row)) is not None and trigger < stamp <= deadline),
        key=lambda item: item[0],
    )
    if not eligible:
        return None
    entry_index = next((
        index
        for index, (_stamp, row) in enumerate(eligible)
        if (
            (low := _number(row.get("l") if row.get("l") is not None else row.get("low"))) is not None
            and (high := _number(row.get("h") if row.get("h") is not None else row.get("high"))) is not None
            and low <= entry <= high
        )
    ), None)
    if entry_index is None:
        return {
            "status": "unfilled",
            "realized_r": None,
            "won": False,
            "hit_t1": False,
            "hit_t2": False,
            "stopped": False,
            "expired": True,
            "entry_touched": False,
            "entry_fill_assumption": "trigger_not_touched_by_completed_ohlc",
            "mfe_r": None,
            "mae_r": None,
            "bars_observed": len(eligible),
            "horizon_end_utc": deadline.isoformat().replace("+00:00", "Z"),
            "execution_enabled": False,
            "can_submit_orders": False,
        }
    eligible = eligible[entry_index:]
    hit_t1 = False
    hit_t2 = False
    stopped = False
    realized_r: float | None = None
    mfe_r = 0.0
    mae_r = 0.0
    for _stamp, row in eligible:
        high = _number(row.get("h") if row.get("h") is not None else row.get("high"))
        low = _number(row.get("l") if row.get("l") is not None else row.get("low"))
        if high is None or low is None:
            continue
        favorable = (high - entry) / risk if direction == "bullish" else (entry - low) / risk
        adverse = (low - entry) / risk if direction == "bullish" else (entry - high) / risk
        mfe_r = max(mfe_r, favorable)
        mae_r = min(mae_r, adverse)
        # Stop priority on an ambiguous same bar is deliberately conservative.
        stop_hit = low <= stop if direction == "bullish" else high >= stop
        if stop_hit:
            stopped, realized_r = True, -1.0
            break
        hit_t1 = hit_t1 or (high >= t1 if direction == "bullish" else low <= t1)
        hit_t2 = hit_t2 or (high >= t2 if direction == "bullish" else low <= t2)
        if hit_t2:
            realized_r = 2.0
            break
    if realized_r is None:
        final_close = _number(eligible[-1][1].get("c") if eligible[-1][1].get("c") is not None else eligible[-1][1].get("close"))
        if final_close is None:
            return None
        realized_r = sign * (final_close - entry) / risk
    return {
        "status": "resolved",
        "realized_r": round(realized_r, 6),
        "won": realized_r > 0,
        "hit_t1": hit_t1,
        "hit_t2": hit_t2,
        "stopped": stopped,
        "expired": not stopped and not hit_t2,
        "entry_touched": True,
        "entry_fill_assumption": "trigger_touch_from_completed_ohlc_not_executable_quote",
        "mfe_r": round(mfe_r, 6),
        "mae_r": round(mae_r, 6),
        "bars_observed": len(eligible),
        "horizon_end_utc": deadline.isoformat().replace("+00:00", "Z"),
        "execution_enabled": False,
        "can_submit_orders": False,
    }


def _alpaca_loader(symbol: str, start: datetime, end: datetime) -> list[dict[str, Any]]:
    params: dict[str, Any] = {
        "symbols": symbol.upper(),
        "timeframe": "5Min",
        "start": start.astimezone(timezone.utc).isoformat().replace("+00:00", "Z"),
        "end": end.astimezone(timezone.utc).isoformat().replace("+00:00", "Z"),
        "adjustment": "raw",
        "feed": "iex",
        "limit": 10_000,
        "sort": "asc",
    }
    rows: list[dict[str, Any]] = []
    token: str | None = None
    for _ in range(4):
        if token:
            params["page_token"] = token
        response = requests.get(
            "https://data.alpaca.markets/v2/stocks/bars",
            headers=_credentials(),
            params=params,
            timeout=25,
        )
        response.raise_for_status()
        payload = response.json()
        rows.extend(
            row
            for row in (payload.get("bars") or {}).get(symbol.upper(), [])
            if isinstance(row, dict)
        )
        token = str(payload.get("next_page_token") or "") or None
        if not token:
            break
    return rows


def resolve_rows(
    detections: Iterable[dict[str, Any]],
    existing_outcomes: Iterable[dict[str, Any]],
    *,
    now: datetime,
    bar_loader: BarLoader = _alpaca_loader,
    max_due_detections: int | None = None,
    session_bar_cache: dict[tuple[str, str], list[dict[str, Any]]] | None = None,
    attempted_detection_ids: set[str] | None = None,
    on_addition: Callable[[dict[str, Any]], None] | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    now = now.astimezone(timezone.utc)
    latest = {_detection_id(row): row for row in existing_outcomes if isinstance(row, dict)}
    additions: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []
    latest_detections: dict[str, dict[str, Any]] = {}
    for detection in detections:
        if isinstance(detection, dict):
            latest_detections[_detection_id(detection)] = detection
    ordered = sorted(
        latest_detections.values(),
        key=lambda row: (
            -GRADE_PRIORITY.get(str(row.get("grade") or "").upper(), 0),
            bool(row.get("blockers")),
            str(row.get("trigger_bar_ts") or row.get("triggered_at") or row.get("bar_close_ts") or ""),
            _detection_id(row),
        ),
    )
    session_bar_cache = session_bar_cache if session_bar_cache is not None else {}
    attempted_detection_ids = attempted_detection_ids if attempted_detection_ids is not None else set()
    due_processed = 0
    for detection in ordered:
        detection_id = _detection_id(detection)
        if detection_id in attempted_detection_ids:
            continue
        trigger = _dt(detection.get("trigger_bar_ts") or detection.get("triggered_at") or detection.get("bar_close_ts"))
        symbol = str(detection.get("symbol") or detection.get("instrument") or "").upper()
        geometry = _geometry(detection)
        if trigger is None or not symbol or geometry is None:
            warnings.append({"detection_id": detection_id, "reason": "missing_trigger_symbol_or_geometry"})
            continue
        deadlines = {**{name: trigger + span for name, span in HORIZONS.items()}, "outcome_eod": _eod_deadline(trigger)}
        due = [name for name, deadline in deadlines.items() if deadline <= now and detection.get(name) is None and (latest.get(detection_id) or {}).get(name) is None]
        if not due:
            continue
        if max_due_detections is not None and due_processed >= max_due_detections:
            continue
        due_processed += 1
        attempted_detection_ids.add(detection_id)
        market_date = trigger.astimezone(MARKET_TZ).date()
        cache_key = (symbol, market_date.isoformat())
        if cache_key not in session_bar_cache:
            session_start = datetime.combine(market_date, wall_time(4, 0), MARKET_TZ).astimezone(timezone.utc)
            session_end = datetime.combine(market_date, wall_time(20, 0), MARKET_TZ).astimezone(timezone.utc)
            session_end = min(session_end, now)
            try:
                session_bar_cache[cache_key] = bar_loader(symbol, session_start, session_end)
            except Exception as exc:  # noqa: BLE001 - one bad symbol must not abort the outcome batch
                session_bar_cache[cache_key] = []
                warnings.append({
                    "detection_id": detection_id,
                    "symbol": symbol,
                    "reason": "bar_loader_error",
                    "error_type": type(exc).__name__,
                })
        bars = session_bar_cache[cache_key]
        if not bars:
            warnings.append({"detection_id": detection_id, "symbol": symbol, "reason": "forward_bars_unavailable"})
            continue
        prior = latest.get(detection_id, {})
        snapshot = {
            **{name: prior.get(name) for name in (*HORIZONS, "outcome_eod")},
            "schema_version": 1,
            "detection_id": detection_id,
            "pattern_id": detection.get("pattern_id"),
            "setup_family": detection.get("setup_family") or detection.get("pattern_id"),
            "grade": detection.get("grade"),
            "regime": detection.get("regime"),
            "asset_class": detection.get("asset_class"),
            "trigger_timeframe": detection.get("trigger_timeframe"),
            "detector_version": detection.get("detector_version"),
            "spec_hash": detection.get("spec_hash"),
            "plan_hash": detection.get("plan_hash"),
            "symbol": symbol,
            "direction": geometry[0],
            "trigger_bar_ts": trigger.isoformat().replace("+00:00", "Z"),
            "probability": detection.get("probability"),
            "resolved_at": now.isoformat().replace("+00:00", "Z"),
            "source_ledger": "data/pattern_grader_log.jsonl",
            "execution_enabled": False,
            "can_submit_orders": False,
        }
        changed = False
        for name in due:
            result = _simulate(bars, direction=geometry[0], entry=geometry[1], stop=geometry[2], deadline=deadlines[name], trigger=trigger)
            if result is not None:
                snapshot[name] = result
                changed = True
        if changed:
            for primary_name in ("outcome_eod", "outcome_60m", "outcome_15m", "outcome_5m"):
                primary = snapshot.get(primary_name)
                if isinstance(primary, dict) and primary.get("status") == "resolved":
                    snapshot["calibration_horizon"] = primary_name
                    snapshot["outcome_r"] = primary.get("realized_r")
                    snapshot["won"] = primary.get("won")
                    snapshot["mfe_r"] = primary.get("mfe_r")
                    snapshot["mae_r"] = primary.get("mae_r")
                    break
            additions.append(snapshot)
            latest[detection_id] = snapshot
            if on_addition is not None:
                on_addition(snapshot)
        else:
            warnings.append({"detection_id": detection_id, "symbol": symbol, "reason": "no_completed_forward_bars_inside_due_horizon"})
    return additions, warnings


def _append(path: Path, rows: Iterable[dict[str, Any]]) -> None:
    values = list(rows)
    if not values:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        for row in values:
            handle.write(json.dumps(row, separators=(",", ":"), sort_keys=True) + "\n")


def _durable_appender(path: Path) -> Callable[[dict[str, Any]], None]:
    """Return a callback that fsyncs each snapshot so crashes cannot lose resolved outcomes."""
    path.parent.mkdir(parents=True, exist_ok=True)

    def _write(row: dict[str, Any]) -> None:
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(row, separators=(",", ":"), sort_keys=True) + "\n")
            handle.flush()
            import os
            os.fsync(handle.fileno())

    return _write


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=SOURCE_LEDGER)
    parser.add_argument("--outcomes", type=Path, default=OUTCOME_LEDGER)
    parser.add_argument("--now")
    parser.add_argument(
        "--max-due-detections",
        type=int,
        default=5000,
        help="Maximum unresolved detections attempted per run, highest grades first.",
    )
    parser.add_argument(
        "--checkpoint-size",
        type=int,
        default=500,
        help="Append completed snapshots after each batch so interruption cannot erase the whole run.",
    )
    args = parser.parse_args()
    now = _dt(args.now) if args.now else datetime.now(timezone.utc)
    assert now is not None
    detections = _read_jsonl(args.source)
    outcomes = _read_jsonl(args.outcomes)
    attempted: set[str] = set()
    session_cache: dict[tuple[str, str], list[dict[str, Any]]] = {}
    warning_rows: list[dict[str, Any]] = []
    appended = 0
    maximum = max(1, args.max_due_detections)
    checkpoint = max(1, min(args.checkpoint_size, maximum))
    durable_writer = _durable_appender(args.outcomes)
    while len(attempted) < maximum:
        before = len(attempted)
        additions, warnings = resolve_rows(
            detections,
            outcomes,
            now=now,
            max_due_detections=min(checkpoint, maximum - len(attempted)),
            session_bar_cache=session_cache,
            attempted_detection_ids=attempted,
            on_addition=durable_writer,
        )
        outcomes.extend(additions)
        appended += len(additions)
        warning_rows.extend(warnings)
        if len(attempted) == before:
            break
    print(json.dumps({
        "resolved_snapshots_appended": appended,
        "attempted_detections": len(attempted),
        "warning_count": len(warning_rows),
        "warning_sample": warning_rows[:25],
        "execution_enabled": False,
        "can_submit_orders": False,
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

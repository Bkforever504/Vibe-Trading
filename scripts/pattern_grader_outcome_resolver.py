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

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.intraday_opportunity_radar import fetch_intraday_bars

MARKET_TZ = ZoneInfo("America/New_York")
SOURCE_LEDGER = ROOT / "data" / "pattern_grader_log.jsonl"
OUTCOME_LEDGER = ROOT / "data" / "pattern_grader_outcomes.jsonl"
HORIZONS = {"outcome_5m": timedelta(minutes=5), "outcome_15m": timedelta(minutes=15), "outcome_60m": timedelta(minutes=60)}
BarLoader = Callable[[str, datetime, datetime], list[dict[str, Any]]]


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
    hit_t1 = False
    hit_t2 = False
    stopped = False
    realized_r: float | None = None
    for _stamp, row in eligible:
        high = _number(row.get("h") if row.get("h") is not None else row.get("high"))
        low = _number(row.get("l") if row.get("l") is not None else row.get("low"))
        if high is None or low is None:
            continue
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
        "bars_observed": len(eligible),
        "horizon_end_utc": deadline.isoformat().replace("+00:00", "Z"),
        "execution_enabled": False,
        "can_submit_orders": False,
    }


def _alpaca_loader(symbol: str, start: datetime, end: datetime) -> list[dict[str, Any]]:
    del start
    rows, errors = fetch_intraday_bars([symbol], end.astimezone(MARKET_TZ))
    return [] if errors else rows.get(symbol.upper(), [])


def resolve_rows(
    detections: Iterable[dict[str, Any]],
    existing_outcomes: Iterable[dict[str, Any]],
    *,
    now: datetime,
    bar_loader: BarLoader = _alpaca_loader,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    now = now.astimezone(timezone.utc)
    latest = {_detection_id(row): row for row in existing_outcomes if isinstance(row, dict)}
    additions: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []
    for detection in detections:
        detection_id = _detection_id(detection)
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
        bars = bar_loader(symbol, trigger, max(deadlines[name] for name in due))
        if not bars:
            warnings.append({"detection_id": detection_id, "symbol": symbol, "reason": "forward_bars_unavailable"})
            continue
        prior = latest.get(detection_id, {})
        snapshot = {
            **{name: prior.get(name) for name in (*HORIZONS, "outcome_eod")},
            "schema_version": 1,
            "detection_id": detection_id,
            "pattern_id": detection.get("pattern_id"),
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
            additions.append(snapshot)
            latest[detection_id] = snapshot
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


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=SOURCE_LEDGER)
    parser.add_argument("--outcomes", type=Path, default=OUTCOME_LEDGER)
    parser.add_argument("--now")
    args = parser.parse_args()
    now = _dt(args.now) if args.now else datetime.now(timezone.utc)
    assert now is not None
    additions, warnings = resolve_rows(_read_jsonl(args.source), _read_jsonl(args.outcomes), now=now)
    _append(args.outcomes, additions)
    print(json.dumps({"resolved_snapshots_appended": len(additions), "warnings": warnings, "execution_enabled": False, "can_submit_orders": False}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

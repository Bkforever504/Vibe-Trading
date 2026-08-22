"""Causal GEX-level reaction shadow logger.

This module tests whether a level published before price interaction predicts a
rejection or an accepted break/retest. It never labels a GEX level as support or
resistance in advance and has no execution authority.
"""
from __future__ import annotations

import argparse
import json
import math
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Iterable


ROOT = Path(__file__).resolve().parent.parent
GEX_LOG = ROOT / "data" / "gex_scan_log.jsonl"
EXTERNAL_LOG = ROOT / "data" / "gex_external_level_snapshots.jsonl"
EVENT_LOG = ROOT / "data" / "gex_level_reaction_ledger.jsonl"
STATUS_PATH = ROOT / "data" / "gex_level_reaction_status.json"
SYMBOLS = ("SPY", "QQQ", "IWM")


@dataclass(frozen=True)
class ReactionConfig:
    zone_fraction: float = 0.00025
    atr_zone_fraction: float = 0.15
    min_volume_ratio: float = 1.0
    outcome_bars: int = 6
    target_r: float = 2.0
    max_snapshot_age_hours: float = 8.0


def _utc(value: str | datetime) -> datetime:
    if isinstance(value, datetime):
        parsed = value
    else:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def validate_snapshot(snapshot: dict, *, now: datetime | None = None) -> tuple[bool, str]:
    """Reject non-causal, stale, or provenance-incomplete level snapshots."""
    if snapshot.get("status") != "ok":
        return False, str(snapshot.get("reason") or snapshot.get("error") or "source_unavailable")
    if snapshot.get("point_in_time") is not True:
        return False, "point_in_time_not_attested"
    if not snapshot.get("timestamp"):
        return False, "missing_snapshot_timestamp"
    if snapshot.get("dealer_positioning_observed") is not False:
        return False, "dealer_positioning_claim_not_supported"
    if snapshot.get("expiry_filter") != "0dte":
        return False, "requires_exact_0dte"
    if snapshot.get("size_source") != "open_interest":
        return False, "requires_open_interest"
    if float(snapshot.get("open_interest_coverage") or 0.0) < 0.60:
        return False, "insufficient_open_interest_coverage"
    if not snapshot.get("levels"):
        return False, "missing_levels"
    observed = _utc(snapshot["timestamp"])
    clock = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    age = (clock - observed).total_seconds() / 3600.0
    if age < 0:
        return False, "snapshot_from_future"
    if age > float(snapshot.get("max_snapshot_age_hours", 8.0)):
        return False, "snapshot_stale"
    return True, "ok"


def normalize_internal_entry(entry: dict, symbol: str) -> dict:
    scan = next((row for row in entry.get("scans", []) if row.get("symbol") == symbol), None)
    if not scan:
        return {"status": "unavailable", "symbol": symbol, "reason": "symbol_missing"}
    levels = [
        {
            "strike": float(level["strike"]),
            "gex": float(level["gex"]),
            "rank": rank,
        }
        for rank, level in enumerate(scan.get("top_levels") or [], start=1)
        if level.get("strike") is not None and level.get("gex") is not None
    ]
    return {
        "status": scan.get("status"),
        "reason": scan.get("error"),
        "symbol": symbol,
        "timestamp": entry.get("timestamp"),
        "data_source": "alpaca_option_chain_proxy",
        "point_in_time": True,
        "expiry_filter": scan.get("expiry_filter"),
        "selected_expiry": scan.get("selected_expiry"),
        "size_source": scan.get("size_source"),
        "open_interest_coverage": scan.get("open_interest_coverage"),
        "dealer_positioning_observed": False,
        "sign_assumption": scan.get("sign_assumption"),
        "levels": levels,
        "max_snapshot_age_hours": 8.0,
        "execution_enabled": False,
        "can_submit_orders": False,
    }


def load_latest_snapshot(symbol: str, *, now: datetime | None = None) -> tuple[dict | None, str]:
    """Load the latest valid internal or normalized external snapshot."""
    candidates: list[dict] = []
    if GEX_LOG.exists():
        for line in GEX_LOG.read_text(encoding="utf-8").splitlines():
            if line.strip():
                candidates.append(normalize_internal_entry(json.loads(line), symbol))
    if EXTERNAL_LOG.exists():
        for line in EXTERNAL_LOG.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            row = json.loads(line)
            if row.get("symbol") == symbol:
                candidates.append(row)
    candidates = [row for row in candidates if row.get("timestamp")]
    candidates.sort(key=lambda row: _utc(row["timestamp"]), reverse=True)
    reasons: list[str] = []
    for candidate in candidates:
        valid, reason = validate_snapshot(candidate, now=now)
        if valid:
            return candidate, "ok"
        reasons.append(reason)
    return None, reasons[0] if reasons else "no_snapshot"


def _atr(bars: list[dict], index: int, window: int = 14) -> float:
    start = max(1, index - window + 1)
    ranges = []
    for i in range(start, index + 1):
        prior_close = float(bars[i - 1]["close"])
        high = float(bars[i]["high"])
        low = float(bars[i]["low"])
        ranges.append(max(high - low, abs(high - prior_close), abs(low - prior_close)))
    return sum(ranges) / len(ranges) if ranges else 0.0


def _volume_ratio(bars: list[dict], index: int, window: int = 20) -> float:
    start = max(0, index - window)
    history = [float(row.get("volume") or 0.0) for row in bars[start:index]]
    positive = [value for value in history if value > 0]
    baseline = sum(positive) / len(positive) if positive else 0.0
    current = float(bars[index].get("volume") or 0.0)
    return current / baseline if baseline > 0 else 1.0


def _outcome(
    bars: list[dict], confirmation_index: int, level: float, zone: float, direction: int,
    config: ReactionConfig,
) -> dict:
    entry_index = confirmation_index + 1
    if entry_index >= len(bars):
        return {"status": "pending", "reason": "no_next_bar_for_causal_entry"}
    entry = float(bars[entry_index]["open"])
    risk = max(abs(entry - level) + zone, zone * 2.0)
    stop = entry - direction * risk
    target = entry + direction * config.target_r * risk
    path = bars[entry_index: entry_index + config.outcome_bars]
    if not path:
        return {"status": "pending", "reason": "no_outcome_bars"}
    best_r = -math.inf
    worst_r = math.inf
    exit_price = float(path[-1]["close"])
    resolution = "time_exit"
    for row in path:
        favorable = (float(row["high"]) - entry) if direction > 0 else (entry - float(row["low"]))
        adverse = (float(row["low"]) - entry) if direction > 0 else (entry - float(row["high"]))
        best_r = max(best_r, favorable / risk)
        worst_r = min(worst_r, adverse / risk)
        stop_hit = float(row["low"]) <= stop if direction > 0 else float(row["high"]) >= stop
        target_hit = float(row["high"]) >= target if direction > 0 else float(row["low"]) <= target
        # Conservative ordering when both occur in one OHLC bar.
        if stop_hit:
            exit_price, resolution = stop, "stop"
            break
        if target_hit:
            exit_price, resolution = target, "target"
            break
    gross_r = direction * (exit_price - entry) / risk
    return {
        "status": "resolved",
        "entry_timestamp": bars[entry_index]["timestamp"],
        "entry_price": round(entry, 4),
        "stop_price": round(stop, 4),
        "target_price": round(target, 4),
        "resolution": resolution,
        "gross_r": round(gross_r, 4),
        "mfe_r": round(best_r, 4),
        "mae_r": round(worst_r, 4),
        "friction_included": False,
        "friction_note": "underlying reaction study; options execution evaluated separately",
    }


def detect_reactions(
    bars: Iterable[dict], snapshot: dict, *, config: ReactionConfig | None = None,
) -> list[dict]:
    """Detect completed-bar rejection and accepted break/retest sequences."""
    cfg = config or ReactionConfig()
    ordered = sorted((dict(row) for row in bars), key=lambda row: _utc(row["timestamp"]))
    snapshot_time = _utc(snapshot["timestamp"])
    ordered = [row for row in ordered if _utc(row["timestamp"]) > snapshot_time]
    events: list[dict] = []
    if len(ordered) < 4:
        return events
    for level_row in snapshot["levels"]:
        level = float(level_row["strike"])
        for i in range(1, len(ordered) - 1):
            prior, touch, confirm = ordered[i - 1], ordered[i], ordered[i + 1]
            atr = _atr(ordered, i)
            zone = max(level * cfg.zone_fraction, atr * cfg.atr_zone_fraction)
            volume_ratio = _volume_ratio(ordered, i + 1)
            if volume_ratio < cfg.min_volume_ratio:
                continue
            prior_close = float(prior["close"])
            touch_close = float(touch["close"])
            confirm_close = float(confirm["close"])
            sequence = None
            direction = 0
            # Approach from below, reject down or accept above on a retest.
            if prior_close < level - zone and float(touch["high"]) >= level - zone:
                if touch_close < level - zone and confirm_close < touch_close:
                    sequence, direction = "rejection_from_below", -1
                elif touch_close > level + zone and float(confirm["low"]) <= level + zone and confirm_close > level + zone:
                    sequence, direction = "accepted_break_up", 1
            # Approach from above, reject up or accept below on a retest.
            elif prior_close > level + zone and float(touch["low"]) <= level + zone:
                if touch_close > level + zone and confirm_close > touch_close:
                    sequence, direction = "rejection_from_above", 1
                elif touch_close < level - zone and float(confirm["high"]) >= level - zone and confirm_close < level - zone:
                    sequence, direction = "accepted_break_down", -1
            if not sequence:
                continue
            outcome = _outcome(ordered, i + 1, level, zone, direction, cfg)
            events.append({
                "event_id": f"{snapshot['symbol']}|{snapshot['timestamp']}|{level}|{touch['timestamp']}|{sequence}",
                "symbol": snapshot["symbol"],
                "snapshot_timestamp": snapshot["timestamp"],
                "data_source": snapshot["data_source"],
                "point_in_time": True,
                "dealer_positioning_observed": False,
                "level": level,
                "level_rank": int(level_row["rank"]),
                "level_gex": float(level_row["gex"]),
                "sequence": sequence,
                "direction": direction,
                "touch_timestamp": touch["timestamp"],
                "confirmation_timestamp": confirm["timestamp"],
                "zone": round(zone, 4),
                "confirmation_volume_ratio": round(volume_ratio, 4),
                "execution_enabled": False,
                "can_submit_orders": False,
                "outcome": outcome,
            })
            break
    return events


def _fetch_alpaca_bars(symbol: str, start: datetime, end: datetime) -> list[dict]:
    from scripts.gex_scanner import _load_env, _ALPACA_KEY, _ALPACA_SECRET
    from alpaca.data.historical.stock import StockHistoricalDataClient
    from alpaca.data.requests import StockBarsRequest
    from alpaca.data.timeframe import TimeFrame, TimeFrameUnit

    _load_env()
    # Import again after _load_env updates module globals.
    from scripts import gex_scanner
    client = StockHistoricalDataClient(gex_scanner._ALPACA_KEY, gex_scanner._ALPACA_SECRET)
    request = StockBarsRequest(
        symbol_or_symbols=symbol,
        timeframe=TimeFrame(5, TimeFrameUnit.Minute),
        start=start,
        end=end,
    )
    frame = client.get_stock_bars(request).df
    if frame.empty:
        return []
    if getattr(frame.index, "nlevels", 1) > 1:
        frame = frame.xs(symbol)
    return [
        {
            "timestamp": index.to_pydatetime().astimezone(timezone.utc).isoformat(),
            "open": float(row.open), "high": float(row.high), "low": float(row.low),
            "close": float(row.close), "volume": float(row.volume),
        }
        for index, row in frame.iterrows()
    ]


def append_unique(events: list[dict], path: Path = EVENT_LOG) -> int:
    existing = set()
    if path.exists():
        existing = {
            json.loads(line)["event_id"] for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        }
    new = [event for event in events if event["event_id"] not in existing]
    if new:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            for event in new:
                handle.write(json.dumps(event, sort_keys=True) + "\n")
    return len(new)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--symbol", choices=SYMBOLS, default="SPY")
    parser.add_argument("--print", action="store_true")
    args = parser.parse_args()
    now = datetime.now(timezone.utc)
    snapshot, reason = load_latest_snapshot(args.symbol, now=now)
    status = {
        "timestamp": now.isoformat(), "symbol": args.symbol, "mode": "shadow_only",
        "execution_enabled": False, "can_submit_orders": False,
    }
    if snapshot is None:
        status.update({"status": "blocked", "reason": reason, "new_events": 0})
    else:
        bars = _fetch_alpaca_bars(args.symbol, _utc(snapshot["timestamp"]), now)
        events = detect_reactions(bars, snapshot)
        status.update({
            "status": "ok", "snapshot_timestamp": snapshot["timestamp"],
            "data_source": snapshot["data_source"], "bars": len(bars),
            "detected_events": len(events), "new_events": append_unique(events),
        })
    STATUS_PATH.parent.mkdir(parents=True, exist_ok=True)
    STATUS_PATH.write_text(json.dumps(status, indent=2) + "\n", encoding="utf-8")
    if args.print:
        print(json.dumps(status, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Build research-only MES microstructure windows from ProjectX market events."""
from __future__ import annotations

import argparse
import json
import math
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable


TICK_SIZE = 0.25


def _finite(value: Any) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if math.isfinite(parsed) else None


def _timestamp(row: dict[str, Any]) -> datetime:
    raw = row.get("source_timestamp") or row.get("received_at_utc")
    if not raw:
        raise ValueError("market event has no timestamp")
    parsed = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("market event timestamp must be timezone-aware")
    return parsed.astimezone(timezone.utc)


def _bucket_start(value: datetime, seconds: int) -> datetime:
    epoch = int(value.timestamp())
    return datetime.fromtimestamp(epoch - epoch % seconds, tz=timezone.utc)


def _new_window(start: datetime) -> dict[str, Any]:
    return {
        "window_start_utc": start.isoformat().replace("+00:00", "Z"),
        "quote_count": 0,
        "trade_count": 0,
        "depth_event_count": 0,
        "trade_volume": 0.0,
        "signed_trade_volume": 0.0,
        "first_mid": None,
        "last_mid": None,
        "last_bid": None,
        "last_ask": None,
        "spread_ticks_sum": 0.0,
        "spread_observations": 0,
    }


def _finalize_window(window: dict[str, Any], bids: dict[float, float], asks: dict[float, float]) -> dict[str, Any]:
    first_mid = window.pop("first_mid")
    last_mid = window.pop("last_mid")
    spread_sum = window.pop("spread_ticks_sum")
    spread_observations = window.pop("spread_observations")
    bid_levels = sorted(bids.items(), reverse=True)[:5]
    ask_levels = sorted(asks.items())[:5]
    bid_depth = sum(volume for _, volume in bid_levels)
    ask_depth = sum(volume for _, volume in ask_levels)
    depth_total = bid_depth + ask_depth
    trade_volume = float(window["trade_volume"])
    signed_volume = float(window["signed_trade_volume"])
    window.update({
        "avg_spread_ticks": round(spread_sum / spread_observations, 4) if spread_observations else None,
        "mid_move_ticks": round((last_mid - first_mid) / TICK_SIZE, 4) if first_mid is not None and last_mid is not None else None,
        "aggressor_imbalance": round(signed_volume / trade_volume, 4) if trade_volume else None,
        "top5_bid_depth": round(bid_depth, 4) if bid_levels else None,
        "top5_ask_depth": round(ask_depth, 4) if ask_levels else None,
        "top5_depth_imbalance": round((bid_depth - ask_depth) / depth_total, 4) if depth_total else None,
        "data_complete": bool(window["quote_count"] and window["trade_count"] and window["depth_event_count"]),
    })
    return window


def build_feature_windows(events: Iterable[dict[str, Any]], *, window_seconds: int = 5) -> list[dict[str, Any]]:
    if window_seconds <= 0:
        raise ValueError("window_seconds must be positive")
    ordered = sorted(events, key=_timestamp)
    bids: dict[float, float] = {}
    asks: dict[float, float] = {}
    current_start: datetime | None = None
    window: dict[str, Any] | None = None
    rows: list[dict[str, Any]] = []

    for event in ordered:
        timestamp = _timestamp(event)
        start = _bucket_start(timestamp, window_seconds)
        if current_start != start:
            if window is not None:
                rows.append(_finalize_window(window, bids, asks))
            current_start = start
            window = _new_window(start)
        assert window is not None
        payload = event.get("payload")
        if not isinstance(payload, dict):
            continue
        event_type = event.get("event_type")
        if event_type == "quote":
            bid = _finite(payload.get("bestBid"))
            ask = _finite(payload.get("bestAsk"))
            if bid is None or ask is None or ask < bid:
                continue
            mid = (bid + ask) / 2.0
            window["quote_count"] += 1
            window["last_bid"] = bid
            window["last_ask"] = ask
            window["first_mid"] = mid if window["first_mid"] is None else window["first_mid"]
            window["last_mid"] = mid
            window["spread_ticks_sum"] += (ask - bid) / TICK_SIZE
            window["spread_observations"] += 1
        elif event_type == "trade":
            volume = _finite(payload.get("volume"))
            side = payload.get("type")
            if volume is None or volume <= 0 or side not in (0, 1, "0", "1"):
                continue
            signed = volume if int(side) == 0 else -volume
            window["trade_count"] += 1
            window["trade_volume"] += volume
            window["signed_trade_volume"] += signed
        elif event_type == "depth":
            price = _finite(payload.get("price"))
            volume = _finite(payload.get("currentVolume"))
            side = payload.get("type")
            if price is None or volume is None or side not in (0, 1, "0", "1"):
                continue
            book = asks if int(side) == 1 else bids
            if volume <= 0:
                book.pop(price, None)
            else:
                book[price] = volume
            window["depth_event_count"] += 1

    if window is not None:
        rows.append(_finalize_window(window, bids, asks))
    return rows


def load_events(path: Path) -> tuple[list[dict[str, Any]], int]:
    events: list[dict[str, Any]] = []
    malformed = 0
    for line in path.read_text(encoding="utf-8-sig").splitlines():
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            malformed += 1
            continue
        if isinstance(row, dict):
            events.append(row)
        else:
            malformed += 1
    return events, malformed


def latency_audit(events: list[dict[str, Any]]) -> dict[str, Any]:
    latencies: list[float] = []
    negative = 0
    for row in events:
        source_raw = row.get("source_timestamp")
        receipt_raw = row.get("received_at_utc")
        if not source_raw or not receipt_raw:
            continue
        try:
            source = datetime.fromisoformat(str(source_raw).replace("Z", "+00:00"))
            receipt = datetime.fromisoformat(str(receipt_raw).replace("Z", "+00:00"))
            if source.tzinfo is None or receipt.tzinfo is None:
                continue
            milliseconds = (receipt.astimezone(timezone.utc) - source.astimezone(timezone.utc)).total_seconds() * 1000
        except (TypeError, ValueError):
            continue
        if milliseconds < 0:
            negative += 1
        else:
            latencies.append(milliseconds)

    def percentile(pct: float) -> float | None:
        if not latencies:
            return None
        ordered = sorted(latencies)
        index = min(len(ordered) - 1, math.ceil(pct * len(ordered)) - 1)
        return round(ordered[index], 3)

    return {
        "paired_timestamp_count": len(latencies) + negative,
        "nonnegative_latency_count": len(latencies),
        "negative_latency_count": negative,
        "receipt_latency_ms_p50": percentile(0.50),
        "receipt_latency_ms_p99": percentile(0.99),
    }


def build_report(path: Path, *, window_seconds: int = 5) -> dict[str, Any]:
    events, malformed = load_events(path)
    windows = build_feature_windows(events, window_seconds=window_seconds)
    complete = sum(bool(row["data_complete"]) for row in windows)
    event_counts = Counter(str(row.get("event_type") or "unknown") for row in events)
    return {
        "schema_version": 1,
        "provider": "topstepx_microstructure_features",
        "mode": "research_only",
        "execution_enabled": False,
        "can_submit_orders": False,
        "source": str(path),
        "window_seconds": window_seconds,
        "event_count": len(events),
        "event_type_counts": dict(sorted(event_counts.items())),
        "malformed_line_count": malformed,
        "latency_audit": latency_audit(events),
        "window_count": len(windows),
        "complete_window_count": complete,
        "complete_window_rate": round(complete / len(windows), 4) if windows else 0.0,
        "feature_definitions": {
            "aggressor_imbalance": "(buy_volume-sell_volume)/(buy_volume+sell_volume); ProjectX type 0 buy, type 1 sell",
            "top5_depth_imbalance": "(bid_depth-ask_depth)/(bid_depth+ask_depth)",
            "mid_move_ticks": "last_quote_mid-minus-first_quote_mid in MES ticks",
        },
        "warnings": [
            "Features are not trade signals.",
            "No thresholds may be selected until data-completeness and timestamp-lag audits pass.",
        ],
        "windows": windows,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--window-seconds", type=int, default=5)
    args = parser.parse_args()
    report = build_report(args.input, window_seconds=args.window_seconds)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({key: value for key, value in report.items() if key != "windows"}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Outcome-blind integrity and feature audit for the MES MBO pilot session."""
from __future__ import annotations

import argparse
import hashlib
import heapq
import json
import math
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_INPUT = ROOT / "data" / "databento" / "mes_v0_mbo_2026-07-15.dbn.zst"
DEFAULT_OUTPUT = ROOT / "data" / "mes_mbo_phase_a.json"
RTH_START_NS = 13 * 3_600_000_000_000 + 30 * 60_000_000_000
RTH_END_NS = 20 * 3_600_000_000_000
WINDOW_NS = 5_000_000_000
F_LAST = 128
F_SNAPSHOT = 32
F_BAD_TS_RECV = 8
F_MAYBE_BAD_BOOK = 4
VALID_ACTIONS = frozenset("ACMFNRT")
VALID_SIDES = frozenset("ABN")


@dataclass(slots=True)
class Order:
    side: str
    price: int
    size: int


class BookState:
    """Minimal single-instrument book using Databento's documented semantics."""

    def __init__(self) -> None:
        self.orders: dict[int, Order] = {}
        self.levels: dict[str, dict[int, int]] = {"B": {}, "A": {}}
        self.heaps: dict[str, list[int]] = {"B": [], "A": []}
        self.missing_order_events = 0
        self.duplicate_adds = 0
        self.oversize_cancels = 0

    def clear(self) -> None:
        self.orders.clear()
        self.levels = {"B": {}, "A": {}}
        self.heaps = {"B": [], "A": []}

    def _level_delta(self, side: str, price: int, delta: int) -> None:
        levels = self.levels[side]
        updated = levels.get(price, 0) + delta
        if updated <= 0:
            levels.pop(price, None)
        else:
            if price not in levels:
                heapq.heappush(self.heaps[side], -price if side == "B" else price)
            levels[price] = updated

    def _remove(self, order_id: int) -> None:
        prior = self.orders.pop(order_id, None)
        if prior is not None:
            self._level_delta(prior.side, prior.price, -prior.size)

    def apply(self, action: str, side: str, order_id: int, price: int, size: int) -> None:
        if action in ("T", "F", "N"):
            return
        if action == "R":
            self.clear()
            return
        if side not in ("A", "B"):
            return
        if action == "A":
            if order_id in self.orders:
                self.duplicate_adds += 1
                self._remove(order_id)
            self.orders[order_id] = Order(side, price, size)
            self._level_delta(side, price, size)
            return
        prior = self.orders.get(order_id)
        if prior is None:
            self.missing_order_events += 1
            return
        if action == "C":
            removed = min(size, prior.size)
            if size > prior.size:
                self.oversize_cancels += 1
            prior.size -= removed
            self._level_delta(prior.side, prior.price, -removed)
            if prior.size == 0:
                self.orders.pop(order_id, None)
        elif action == "M":
            self._level_delta(prior.side, prior.price, -prior.size)
            prior.side = side
            prior.price = price
            prior.size = size
            self._level_delta(side, price, size)

    def best(self, side: str) -> tuple[int, int] | None:
        heap = self.heaps[side]
        levels = self.levels[side]
        while heap:
            raw = heap[0]
            price = -raw if side == "B" else raw
            size = levels.get(price, 0)
            if size > 0:
                return price, size
            heapq.heappop(heap)
        return None


def _quantiles(values: list[float]) -> dict[str, float | None]:
    if not values:
        return {key: None for key in ("p10", "p25", "p50", "p75", "p90", "mean")}
    ordered = sorted(values)

    def at(fraction: float) -> float:
        return ordered[min(len(ordered) - 1, round((len(ordered) - 1) * fraction))]

    return {
        "p10": round(at(0.10), 6),
        "p25": round(at(0.25), 6),
        "p50": round(at(0.50), 6),
        "p75": round(at(0.75), 6),
        "p90": round(at(0.90), 6),
        "mean": round(sum(ordered) / len(ordered), 6),
    }


def _new_window(bucket: int) -> dict[str, Any]:
    return {
        "bucket": bucket,
        "add_bid": 0,
        "add_ask": 0,
        "cancel_bid": 0,
        "cancel_ask": 0,
        "fill_bid": 0,
        "fill_ask": 0,
        "trade_buy": 0,
        "trade_sell": 0,
        "valid_book": False,
        "crossed_book": False,
        "spread_ticks": None,
        "depth_imbalance": None,
    }


def _finalize_window(window: dict[str, Any], book: BookState) -> dict[str, Any]:
    bid = book.best("B")
    ask = book.best("A")
    window["best_bid"] = bid[0] if bid is not None else None
    window["best_ask"] = ask[0] if ask is not None else None
    if bid is not None and ask is not None:
        window["crossed_book"] = bid[0] >= ask[0]
        window["valid_book"] = not window["crossed_book"]
        if window["valid_book"]:
            window["spread_ticks"] = (ask[0] - bid[0]) / 250_000_000
            total = bid[1] + ask[1]
            window["depth_imbalance"] = (bid[1] - ask[1]) / total if total else None
    added = window["add_bid"] + window["add_ask"]
    cancelled = window["cancel_bid"] + window["cancel_ask"]
    pressure_total = added + cancelled
    window["cancel_add_pressure"] = (
        (
            window["add_bid"]
            + window["cancel_ask"]
            - window["add_ask"]
            - window["cancel_bid"]
        )
        / pressure_total
        if pressure_total
        else None
    )
    fill_total = window["fill_bid"] + window["fill_ask"]
    window["passive_fill_imbalance"] = (
        (window["fill_bid"] - window["fill_ask"]) / fill_total if fill_total else None
    )
    return window


def audit_records(records: Iterable[Any], *, include_windows: bool = False) -> dict[str, Any]:
    book = BookState()
    action_counts: Counter[str] = Counter()
    side_counts: Counter[str] = Counter()
    bad_book_flags = 0
    bad_ts_flags = 0
    snapshot_records = 0
    snapshot_clear_seen = False
    event_count = 0
    rth_event_count = 0
    current_bucket: int | None = None
    window: dict[str, Any] | None = None
    windows: list[dict[str, Any]] = []

    for mbo in records:
        event_count += 1
        action = str(mbo.action)
        side = str(mbo.side)
        flags = int(mbo.flags)
        action_counts[action] += 1
        side_counts[side] += 1
        bad_book_flags += bool(flags & F_MAYBE_BAD_BOOK)
        bad_ts_flags += bool(flags & F_BAD_TS_RECV)
        if flags & F_SNAPSHOT:
            snapshot_records += 1
            snapshot_clear_seen |= action == "R"

        day_ns = int(mbo.ts_recv) % 86_400_000_000_000
        in_rth = RTH_START_NS <= day_ns < RTH_END_NS
        if not in_rth:
            book.apply(action, side, int(mbo.order_id), int(mbo.price), int(mbo.size))
            continue
        rth_event_count += 1
        bucket = day_ns // WINDOW_NS
        if current_bucket != bucket:
            if window is not None:
                windows.append(_finalize_window(window, book))
            current_bucket = bucket
            window = _new_window(bucket)
        assert window is not None
        book.apply(action, side, int(mbo.order_id), int(mbo.price), int(mbo.size))
        size = int(mbo.size)
        if action == "A":
            window["add_bid" if side == "B" else "add_ask"] += size
        elif action == "C":
            window["cancel_bid" if side == "B" else "cancel_ask"] += size
        elif action == "F":
            if side in ("A", "B"):
                window["fill_bid" if side == "B" else "fill_ask"] += size
        elif action == "T":
            if side in ("A", "B"):
                window["trade_buy" if side == "B" else "trade_sell"] += size
    if window is not None:
        windows.append(_finalize_window(window, book))

    valid_windows = sum(bool(row["valid_book"]) for row in windows)
    crossed_windows = sum(bool(row["crossed_book"]) for row in windows)
    recognized_actions = sum(count for key, count in action_counts.items() if key in VALID_ACTIONS)
    recognized_sides = sum(count for key, count in side_counts.items() if key in VALID_SIDES)
    action_rate = recognized_actions / event_count if event_count else 0.0
    side_rate = recognized_sides / event_count if event_count else 0.0
    valid_rate = valid_windows / len(windows) if windows else 0.0
    gates = {
        "snapshot_clear_seen": snapshot_clear_seen and snapshot_records > 0,
        "recognized_action_rate_gte_99pct": action_rate >= 0.99,
        "recognized_side_rate_gte_99pct": side_rate >= 0.99,
        "no_maybe_bad_book_flags": bad_book_flags == 0,
        "valid_book_window_rate_gte_95pct": valid_rate >= 0.95,
        "no_crossed_book_windows": crossed_windows == 0,
    }
    numeric = lambda key: [float(row[key]) for row in windows if row.get(key) is not None and math.isfinite(float(row[key]))]
    result = {
        "event_count": event_count,
        "rth_event_count": rth_event_count,
        "action_counts": dict(sorted(action_counts.items())),
        "side_counts": dict(sorted(side_counts.items())),
        "recognized_action_rate": round(action_rate, 8),
        "recognized_side_rate": round(side_rate, 8),
        "snapshot_record_count": snapshot_records,
        "snapshot_clear_seen": snapshot_clear_seen,
        "bad_timestamp_flag_count": bad_ts_flags,
        "maybe_bad_book_flag_count": bad_book_flags,
        "book_state": {
            "resting_order_count_at_end": len(book.orders),
            "missing_order_event_count": book.missing_order_events,
            "duplicate_add_count": book.duplicate_adds,
            "oversize_cancel_count": book.oversize_cancels,
        },
        "windows": {
            "window_seconds": 5,
            "count": len(windows),
            "valid_book_count": valid_windows,
            "valid_book_rate": round(valid_rate, 8),
            "crossed_book_count": crossed_windows,
        },
        "feature_distributions": {
            "cancel_add_pressure": _quantiles(numeric("cancel_add_pressure")),
            "passive_fill_imbalance": _quantiles(numeric("passive_fill_imbalance")),
            "top_of_book_depth_imbalance": _quantiles(numeric("depth_imbalance")),
            "spread_ticks": _quantiles(numeric("spread_ticks")),
        },
        "quality_gates": {**gates, "all_pass": all(gates.values())},
    }
    if include_windows:
        result["window_rows"] = windows
    return result


def build_report(path: Path) -> dict[str, Any]:
    import databento as db

    store = db.DBNStore.from_file(path)
    audit = audit_records(iter(store))
    return {
        "schema_version": 1,
        "provider": "databento",
        "protocol": "MES_MBO_DISCOVERY_PREREGISTRATION_2026-08-12",
        "phase": "A_outcome_blind",
        "mode": "research_only",
        "execution_enabled": False,
        "can_submit_orders": False,
        "source": {
            "path": str(path),
            "bytes": path.stat().st_size,
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest().upper(),
            "dataset": str(store.dataset),
            "schema": str(store.schema),
        },
        **audit,
        "warnings": [
            "This report contains no future returns, P&L, or strategy thresholds.",
            "One session can validate mechanics but cannot establish a trading edge.",
            "Trade and fill records do not update the resting book; associated cancel records do.",
        ],
        "next_boundary": "freeze_one_outcome_hypothesis_before_acquiring_a_separate_discovery_sample",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    report = build_report(args.input)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

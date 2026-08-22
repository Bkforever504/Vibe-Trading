"""Daily read-only fill-quality and slippage decomposition report."""
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from statistics import mean
from typing import Any, Iterable, Mapping


ROOT = Path(__file__).resolve().parents[1]
EVENT_LOG = ROOT / "data" / "reconciliation_events.jsonl"
OUTPUT_PATH = ROOT / "data" / "fill_quality_report.json"


def _number(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def decompose_slippage(row: Mapping[str, Any]) -> dict[str, Any]:
    side = str(row.get("side") or "buy").lower()
    adverse_sign = 1.0 if side in {"buy", "buy_to_open", "buy_to_close"} else -1.0
    intent = _number(row.get("intent_price"))
    arrival = _number(row.get("arrival_price"))
    fill = _number(row.get("fill_price"))
    realized = _number(row.get("realized_price"))

    def component(start: float | None, end: float | None) -> float | None:
        return adverse_sign * (end - start) if start is not None and end is not None else None

    return {
        "trade_id": row.get("trade_id") or row.get("client_order_id") or row.get("order_id"),
        "symbol": row.get("symbol"),
        "side": side,
        "intent_to_arrival": component(intent, arrival),
        "arrival_to_fill": component(arrival, fill),
        "fill_to_realized": component(fill, realized),
        "complete": all(value is not None for value in (intent, arrival, fill, realized)),
    }


def build_report(rows: Iterable[Mapping[str, Any]], *, generated_at: datetime | None = None) -> dict[str, Any]:
    generated_at = (generated_at or datetime.now(timezone.utc)).astimezone(timezone.utc)
    decomposed = [decompose_slippage(row) for row in rows]

    def average(key: str) -> float | None:
        values = [_number(row.get(key)) for row in decomposed]
        present = [value for value in values if value is not None]
        return mean(present) if present else None

    return {
        "schema_version": 1,
        "generated_at": generated_at.isoformat(),
        "status": "ok" if decomposed and all(row["complete"] for row in decomposed) else "incomplete" if decomposed else "unavailable",
        "sample_count": len(decomposed),
        "complete_sample_count": sum(bool(row["complete"]) for row in decomposed),
        "averages": {
            "intent_to_arrival": average("intent_to_arrival"),
            "arrival_to_fill": average("arrival_to_fill"),
            "fill_to_realized": average("fill_to_realized"),
        },
        "rows": decomposed,
        "execution_enabled": False,
        "can_submit_orders": False,
    }


def _read_events(path: Path) -> list[dict[str, Any]]:
    try:
        lines = path.read_text(encoding="utf-8-sig").splitlines()
    except OSError:
        return []
    fills: list[dict[str, Any]] = []
    for line in lines:
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        snapshot = event.get("broker_snapshot") if isinstance(event, dict) else None
        if not isinstance(snapshot, dict):
            continue
        orders = snapshot.get("orders") if isinstance(snapshot.get("orders"), list) else []
        for order in orders:
            if not isinstance(order, dict) or not order.get("filled_avg_price"):
                continue
            fills.append(
                {
                    "trade_id": order.get("client_order_id") or order.get("id"),
                    "symbol": order.get("symbol"),
                    "side": order.get("side"),
                    "intent_price": order.get("limit_price"),
                    "arrival_price": order.get("arrival_price"),
                    "fill_price": order.get("filled_avg_price"),
                    "realized_price": order.get("realized_price"),
                }
            )
    unique: dict[str, dict[str, Any]] = {}
    for row in fills:
        unique[str(row.get("trade_id"))] = row
    return [unique[key] for key in sorted(unique)]


def run_once(*, event_log: Path = EVENT_LOG, output_path: Path = OUTPUT_PATH, now: datetime | None = None) -> dict[str, Any]:
    report = build_report(_read_events(event_log), generated_at=now)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    temp = output_path.with_suffix(output_path.suffix + ".tmp")
    temp.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temp.replace(output_path)
    return report


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--events", type=Path, default=EVENT_LOG)
    parser.add_argument("--output", type=Path, default=OUTPUT_PATH)
    args = parser.parse_args()
    print(json.dumps(run_once(event_log=args.events, output_path=args.output), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


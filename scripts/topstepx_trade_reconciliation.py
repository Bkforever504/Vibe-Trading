#!/usr/bin/env python3
"""Read-only TopstepX MES fill reconciliation and executable trade-shape report.

Only ProjectX ``Trade/search`` rows are allowed to become resolved trades. Local
order journals and bar-replay exits are context, never authoritative outcomes.
The module has no order endpoint and cannot submit, cancel, or modify orders.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import sys
from collections import deque
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import quote


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.topstepx_practice_probe import load_agent_env
from strategies.topstepx_market_recorder import default_output
from strategies.topstepx_practice_adapter import PracticeExecutionConfig, TopstepXPracticeAdapter


MES_POINT_VALUE = 5.0
MES_TICK_SIZE = 0.25
DEFAULT_OUTPUT = Path.home() / ".vibe-trading" / "reports" / "topstepx-practice-reconciliation.json"


def redact_error(value: BaseException, secrets: Iterable[str]) -> str:
    message = f"{type(value).__name__}: {value}"
    for secret in secrets:
        if secret:
            message = message.replace(secret, "[REDACTED]")
            message = message.replace(quote(secret, safe=""), "[REDACTED]")
    return message


def _finite(value: Any) -> float | None:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def _timestamp(value: Any) -> datetime:
    parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("ProjectX timestamps must be timezone-aware")
    return parsed.astimezone(timezone.utc)


def _is_mes_contract(value: Any) -> bool:
    return str(value or "").upper().startswith("CON.F.US.MES.")


def _order_tags(orders: Iterable[dict[str, Any]]) -> dict[int, str]:
    tags: dict[int, str] = {}
    for row in orders:
        try:
            order_id = int(row["id"])
        except (KeyError, TypeError, ValueError):
            continue
        tag = str(row.get("customTag") or "").strip()
        if tag:
            tags[order_id] = tag
    return tags


def pair_mes_round_trips(
    trades: Iterable[dict[str, Any]],
    *,
    orders: Iterable[dict[str, Any]] = (),
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """FIFO-pair authoritative half-turn fills into MES round trips.

    The practice adapter caps entries at one MES, but this remains correct for
    partial fills by splitting each fill into one-contract units.
    """
    tags = _order_tags(orders)
    fills = [row for row in trades if not row.get("voided") and _is_mes_contract(row.get("contractId"))]
    fills.sort(key=lambda row: _timestamp(row.get("creationTimestamp")))
    open_units: deque[dict[str, Any]] = deque()
    closed: list[dict[str, Any]] = []
    malformed: list[dict[str, Any]] = []

    for fill in fills:
        try:
            side = int(fill["side"])
            size = int(fill["size"])
            price = float(fill["price"])
            created = _timestamp(fill["creationTimestamp"])
            fill_id = int(fill["id"])
            order_id = int(fill["orderId"])
        except (KeyError, TypeError, ValueError) as exc:
            malformed.append({"reason": f"invalid_fill:{type(exc).__name__}", "fill": fill})
            continue
        if side not in (0, 1) or size <= 0 or not math.isfinite(price):
            malformed.append({"reason": "invalid_side_size_or_price", "fill": fill})
            continue

        direction = 1 if side == 0 else -1
        fee_per_unit = (_finite(fill.get("fees")) or 0.0) / size
        reported_per_unit = None
        reported = _finite(fill.get("profitAndLoss"))
        if reported is not None:
            reported_per_unit = reported / size

        for unit_index in range(size):
            unit = {
                "fill_id": fill_id,
                "order_id": order_id,
                "custom_tag": tags.get(order_id),
                "contract_id": str(fill.get("contractId")),
                "timestamp": created,
                "price": price,
                "fee": fee_per_unit,
                "direction": direction,
                "unit_index": unit_index,
            }
            if not open_units or open_units[0]["direction"] == direction:
                open_units.append(unit)
                continue

            entry = open_units.popleft()
            gross = (price - float(entry["price"])) * float(entry["direction"]) * MES_POINT_VALUE
            fees = float(entry["fee"]) + fee_per_unit
            closed.append({
                "round_trip_id": f"{entry['fill_id']}:{fill_id}:{unit_index}",
                "provider": "projectx_trade_search",
                "broker_confirmed": True,
                "contract_id": entry["contract_id"],
                "side": "long" if entry["direction"] == 1 else "short",
                "contracts": 1,
                "entry_fill_id": entry["fill_id"],
                "exit_fill_id": fill_id,
                "entry_order_id": entry["order_id"],
                "exit_order_id": order_id,
                "custom_tag": entry.get("custom_tag"),
                "entry_time_utc": entry["timestamp"].isoformat().replace("+00:00", "Z"),
                "exit_time_utc": created.isoformat().replace("+00:00", "Z"),
                "entry_price": float(entry["price"]),
                "exit_price": price,
                "calculated_gross_pnl": round(gross, 2),
                "fees_dollars": round(fees, 4),
                "calculated_net_pnl": round(gross - fees, 2),
                "broker_reported_exit_pnl": reported_per_unit,
            })

    unresolved = [
        {
            "fill_id": row["fill_id"],
            "order_id": row["order_id"],
            "contract_id": row["contract_id"],
            "side": "long" if row["direction"] == 1 else "short",
            "entry_time_utc": row["timestamp"].isoformat().replace("+00:00", "Z"),
            "entry_price": row["price"],
            "reason": "unmatched_open_fill",
        }
        for row in open_units
    ]
    unresolved.extend(malformed)
    return closed, unresolved


def load_market_events(paths: Iterable[Path]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    seen: set[tuple[Any, ...]] = set()
    for path in paths:
        if not path.exists():
            continue
        for line in path.read_text(encoding="utf-8-sig").splitlines():
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(row, dict):
                continue
            key = (row.get("event_type"), row.get("contract_id"), row.get("source_timestamp"), line)
            if key not in seen:
                seen.add(key)
                rows.append(row)
    rows.sort(key=lambda row: _timestamp(row.get("source_timestamp") or row.get("received_at_utc")))
    return rows


def default_market_paths(path: Path | None = None) -> list[Path]:
    base = path or default_output()
    return [base, *(base.with_name(f"{base.name}.{index}") for index in range(1, 4))]


def attach_executable_trade_shape(
    round_trip: dict[str, Any],
    market_events: Iterable[dict[str, Any]],
    *,
    confirmation_ticks: float = 1.0,
    meaningful_ticks: float = 4.0,
) -> dict[str, Any]:
    """Measure MFE/MAE at the executable liquidation side of the quote."""
    entry_time = _timestamp(round_trip["entry_time_utc"])
    exit_time = _timestamp(round_trip["exit_time_utc"])
    entry_price = float(round_trip["entry_price"])
    direction = 1.0 if round_trip["side"] == "long" else -1.0
    marks: list[tuple[datetime, float]] = []

    for event in market_events:
        if event.get("event_type") != "quote" or event.get("contract_id") != round_trip["contract_id"]:
            continue
        timestamp = _timestamp(event.get("source_timestamp") or event.get("received_at_utc"))
        if timestamp < entry_time or timestamp > exit_time:
            continue
        payload = event.get("payload") or {}
        mark = _finite(payload.get("bestBid" if direction > 0 else "bestAsk"))
        if mark is None:
            continue
        marks.append((timestamp, (mark - entry_price) * direction / MES_TICK_SIZE))

    realized_ticks = (float(round_trip["exit_price"]) - entry_price) * direction / MES_TICK_SIZE
    if not marks:
        return {
            **round_trip,
            "trade_shape_status": "incomplete_no_executable_quotes",
            "executable_mark_count": 0,
            "realized_ticks": round(realized_ticks, 4),
            "mfe_ticks": None,
            "mae_ticks": None,
        }

    values = [value for _, value in marks]
    mfe = max(values)
    mae = min(values)
    first_confirmation = next((timestamp for timestamp, value in marks if value >= confirmation_ticks), None)
    first_adverse = next((timestamp for timestamp, value in marks if value <= -meaningful_ticks), None)
    never_confirmed = mfe < confirmation_ticks
    recovered_after_adverse = bool(
        first_adverse is not None
        and first_confirmation is not None
        and first_confirmation > first_adverse
    )
    winner_giveback = realized_ticks > 0 and mfe - realized_ticks >= meaningful_ticks
    failed_after_profit = realized_ticks <= 0 and mfe >= meaningful_ticks
    if never_confirmed:
        label = "never_confirmed"
    elif failed_after_profit:
        label = "failed_after_profit"
    elif winner_giveback:
        label = "winner_giveback"
    elif recovered_after_adverse and realized_ticks > 0:
        label = "recovered_and_won"
    elif realized_ticks > 0:
        label = "clean_winner"
    else:
        label = "confirmed_then_lost"

    return {
        **round_trip,
        "trade_shape_status": "complete",
        "trade_shape": label,
        "executable_mark_count": len(marks),
        "realized_ticks": round(realized_ticks, 4),
        "mfe_ticks": round(mfe, 4),
        "mae_ticks": round(mae, 4),
        "giveback_from_mfe_ticks": round(mfe - realized_ticks, 4),
        "never_confirmed": never_confirmed,
        "recovered_after_adverse": recovered_after_adverse,
        "winner_giveback": winner_giveback,
        "failed_after_profit": failed_after_profit,
        "first_confirmation_utc": first_confirmation.isoformat().replace("+00:00", "Z") if first_confirmation else None,
    }


def build_report(
    trades: Iterable[dict[str, Any]],
    orders: Iterable[dict[str, Any]],
    market_events: Iterable[dict[str, Any]],
    *,
    generated_at: datetime | None = None,
) -> dict[str, Any]:
    closed, unresolved = pair_mes_round_trips(trades, orders=orders)
    events = list(market_events)
    resolved = [attach_executable_trade_shape(row, events) for row in closed]
    complete = [row for row in resolved if row["trade_shape_status"] == "complete"]
    shape_counts: dict[str, int] = {}
    for row in complete:
        label = str(row["trade_shape"])
        shape_counts[label] = shape_counts.get(label, 0) + 1
    now = generated_at or datetime.now(timezone.utc)
    return {
        "schema_version": 1,
        "provider": "topstepx_practice_reconciliation",
        "generated_at_utc": now.astimezone(timezone.utc).isoformat().replace("+00:00", "Z"),
        "mode": "read_only_broker_reconciliation",
        "execution_enabled": False,
        "can_submit_orders": False,
        "outcome_authority": "projectx_trade_search_only",
        "round_trip_count": len(resolved),
        "unresolved_fill_count": len(unresolved),
        "trade_shape_complete_count": len(complete),
        "trade_shape_complete_rate": round(len(complete) / len(resolved), 4) if resolved else 0.0,
        "calculated_net_pnl": round(sum(float(row["calculated_net_pnl"]) for row in resolved), 2),
        "shape_counts": dict(sorted(shape_counts.items())),
        "warnings": [
            "Only broker-returned fills are resolved outcomes; local journals and replay exits are excluded.",
            "Trade shape uses executable bid for long liquidation and executable ask for short liquidation.",
            "Missing quote coverage remains incomplete and cannot be promoted as favorable evidence.",
            "The ProjectX profitAndLoss field is retained separately from independently calculated gross-minus-fees P&L.",
        ],
        "trades": resolved,
        "unresolved": unresolved,
    }


def run_live_read_only(*, output: Path, days: int, market_path: Path | None = None) -> dict[str, Any]:
    load_agent_env()
    username = os.environ.get("TOPSTEPX_USERNAME", "").strip()
    api_key = os.environ.get("TOPSTEPX_API_KEY", "").strip()
    adapter = TopstepXPracticeAdapter(
        username=username,
        api_key=api_key,
        config=PracticeExecutionConfig.from_env(),
    )
    try:
        adapter.login()
        account = adapter.allowed_practice_account()
        end = datetime.now(timezone.utc)
        start = end - timedelta(days=max(1, days))
        orders = adapter.search_orders(account, start=start, end=end)
        trades = adapter.search_trades(account, start=start, end=end)
        events = load_market_events(default_market_paths(market_path))
        report = build_report(trades, orders, events, generated_at=end)
        report["status"] = "ok" if report["round_trip_count"] else "no_broker_confirmed_round_trips"
        report["lookback_days"] = max(1, days)
        report["market_event_count"] = len(events)
    except Exception as exc:
        report = {
            "schema_version": 1,
            "provider": "topstepx_practice_reconciliation",
            "generated_at_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "mode": "read_only_broker_reconciliation",
            "execution_enabled": False,
            "can_submit_orders": False,
            "status": "blocked",
            "error": redact_error(exc, [username, api_key]),
        }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--days", type=int, default=30)
    parser.add_argument("--market-events", type=Path, default=None)
    args = parser.parse_args()
    report = run_live_read_only(output=args.output, days=args.days, market_path=args.market_events)
    print(json.dumps({key: value for key, value in report.items() if key not in {"trades", "unresolved"}}, indent=2))
    return 0 if report.get("status") in {"ok", "no_broker_confirmed_round_trips"} else 2


if __name__ == "__main__":
    raise SystemExit(main())

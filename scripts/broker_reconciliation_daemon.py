"""Read-only Alpaca-to-local-state reconciliation daemon."""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping

import requests


ROOT = Path(__file__).resolve().parents[1]
VIBE_HOME = Path.home() / ".vibe-trading"
EVENT_LOG = ROOT / "data" / "reconciliation_events.jsonl"
REPORT_PATH = VIBE_HOME / "reports" / "broker-reconciliation.json"
LOCAL_STATE_FILES = (
    VIBE_HOME / "options-trades.json",
    VIBE_HOME / "flip-trades.json",
    VIBE_HOME / "flip-exploration-trades.json",
)


def _read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        return None


def _atomic_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(dict(payload), indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temp.replace(path)


def _append_jsonl(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(dict(payload), sort_keys=True, separators=(",", ":")) + "\n")


def _walk(value: Any) -> Iterable[Mapping[str, Any]]:
    if isinstance(value, Mapping):
        yield value
        for child in value.values():
            yield from _walk(child)
    elif isinstance(value, list):
        for child in value:
            yield from _walk(child)


def local_inventory(states: Iterable[Any]) -> dict[str, Any]:
    order_ids: set[str] = set()
    positions: dict[str, float] = {}
    pending_order_states = {"new", "accepted", "submitted", "partially_filled", "pending_exit"}
    for state in states:
        for row in _walk(state):
            symbol = row.get("symbol") or row.get("option_symbol")
            status = str(row.get("status") or row.get("state") or "").lower()
            if status in pending_order_states:
                for key in ("client_order_id", "order_id", "entry_order_id", "exit_order_id"):
                    if row.get(key):
                        order_ids.add(str(row[key]))
            if symbol and status in {"open", "active", "pending_exit"}:
                try:
                    quantity = row.get("qty") if row.get("qty") is not None else row.get("quantity")
                    if quantity is not None:
                        positions[str(symbol)] = float(quantity)
                except (TypeError, ValueError):
                    continue
    return {"order_ids": sorted(order_ids), "positions": positions}


def reconcile(
    *,
    broker_orders: Iterable[Mapping[str, Any]],
    broker_fills: Iterable[Mapping[str, Any]],
    broker_positions: Iterable[Mapping[str, Any]],
    local: Mapping[str, Any],
) -> list[dict[str, Any]]:
    del broker_fills  # retained in snapshots for fill-quality analysis
    diffs: list[dict[str, Any]] = []
    local_ids = {str(value) for value in local.get("order_ids", [])}
    pending_broker_states = {
        "new", "accepted", "pending_new", "partially_filled", "held",
        "pending_cancel", "pending_replace", "accepted_for_bidding",
        "stopped", "calculated", "suspended",
    }
    broker_ids = {
        str(row.get("client_order_id") or row.get("id"))
        for row in broker_orders
        if row.get("client_order_id") or row.get("id")
        if not row.get("status") or str(row.get("status")).lower() in pending_broker_states
    }
    for order_id in sorted(local_ids - broker_ids):
        diffs.append({"class": "missing_broker_order", "identifier": order_id})
    for order_id in sorted(value for value in broker_ids - local_ids if value.startswith(("vt-", "vibe-"))):
        diffs.append({"class": "untracked_broker_order", "identifier": order_id})

    local_positions = {str(k): float(v) for k, v in dict(local.get("positions", {})).items()}
    broker_position_map: dict[str, float] = {}
    for row in broker_positions:
        symbol = str(row.get("symbol") or "")
        if not symbol:
            continue
        try:
            broker_position_map[symbol] = float(row.get("qty") or 0)
        except (TypeError, ValueError):
            continue
    for symbol in sorted(set(local_positions) | set(broker_position_map)):
        local_qty = local_positions.get(symbol, 0.0)
        broker_qty = broker_position_map.get(symbol, 0.0)
        if local_qty != broker_qty:
            diffs.append(
                {
                    "class": "position_quantity_mismatch",
                    "identifier": symbol,
                    "local_qty": local_qty,
                    "broker_qty": broker_qty,
                }
            )
    return diffs


def _alpaca_snapshot() -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    # Runtime import reuses flip_bot's existing dotenv/auth/base-url path.
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))
    from strategies import flip_bot

    if not flip_bot.KEY or not flip_bot.SECRET:
        raise RuntimeError("alpaca_auth_unavailable")
    headers = {"APCA-API-KEY-ID": flip_bot.KEY, "APCA-API-SECRET-KEY": flip_bot.SECRET}
    after = (datetime.now(timezone.utc) - timedelta(days=7)).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    session = requests.Session()

    def get(path: str, params: Mapping[str, Any] | None = None) -> list[dict[str, Any]]:
        response = session.get(f"{flip_bot.BASE}{path}", headers=headers, params=params, timeout=25)
        response.raise_for_status()
        payload = response.json()
        return payload if isinstance(payload, list) else []

    orders = get("/v2/orders", {"status": "all", "after": after, "limit": 500, "direction": "desc", "nested": "true"})
    fills: list[dict[str, Any]] = []
    activity_params: dict[str, Any] = {"after": after, "direction": "desc", "page_size": 100}
    for _ in range(10):  # bounded pagination: at most 1,000 recent fills
        page = get("/v2/account/activities/FILL", activity_params)
        fills.extend(page)
        if len(page) < 100 or not page[-1].get("id"):
            break
        activity_params["page_token"] = page[-1]["id"]
    positions = get("/v2/positions")
    return orders, fills, positions


def run_once(
    *,
    event_log: Path = EVENT_LOG,
    report_path: Path = REPORT_PATH,
    state_files: Iterable[Path] = LOCAL_STATE_FILES,
    snapshot: tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]] | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    now = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    try:
        orders, fills, positions = snapshot if snapshot is not None else _alpaca_snapshot()
        local = local_inventory(_read_json(path) for path in state_files)
        diffs = reconcile(broker_orders=orders, broker_fills=fills, broker_positions=positions, local=local)
        status = "diff" if diffs else "ok"
        error = None
    except Exception as exc:  # daemon must publish the failure, not silently die
        orders, fills, positions, diffs = [], [], [], [{"class": "broker_snapshot_unavailable", "identifier": type(exc).__name__}]
        status = "unavailable"
        error = str(exc)
    payload = {
        "schema_version": 1,
        "event_type": "reconciliation_run",
        "run_at": now.isoformat(),
        "status": status,
        "diff_count": len(diffs),
        "diffs": diffs,
        "broker_snapshot": {"orders": orders, "fills": fills, "positions": positions},
        "error": error,
        "issues": [f"reconciliation:{row['class']}:{row['identifier']}" for row in diffs],
        "execution_enabled": False,
        "can_submit_orders": False,
    }
    _append_jsonl(event_log, payload)
    _atomic_json(report_path, payload)
    return payload


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--event-log", type=Path, default=EVENT_LOG)
    parser.add_argument("--report", type=Path, default=REPORT_PATH)
    args = parser.parse_args()
    result = run_once(event_log=args.event_log, report_path=args.report)
    print(json.dumps({"status": result["status"], "diff_count": result["diff_count"]}, sort_keys=True))
    return 0 if result["status"] != "unavailable" else 1


if __name__ == "__main__":
    raise SystemExit(main())

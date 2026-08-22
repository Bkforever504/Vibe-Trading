from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from scripts.topstepx_trade_reconciliation import (
    attach_executable_trade_shape,
    build_report,
    pair_mes_round_trips,
)
from strategies.topstepx_practice_adapter import PracticeAccount, TopstepXPracticeAdapter


def _fill(
    fill_id: int,
    *,
    side: int,
    price: float,
    timestamp: str,
    order_id: int,
    pnl: float | None,
) -> dict[str, Any]:
    return {
        "id": fill_id,
        "accountId": 42,
        "contractId": "CON.F.US.MES.U26",
        "creationTimestamp": timestamp,
        "price": price,
        "profitAndLoss": pnl,
        "fees": 0.61,
        "side": side,
        "size": 1,
        "voided": False,
        "orderId": order_id,
    }


def test_broker_fills_pair_fifo_and_preserve_entry_candidate_tag() -> None:
    trades = [
        _fill(1, side=0, price=6000.0, timestamp="2026-08-17T14:00:00Z", order_id=10, pnl=None),
        _fill(2, side=1, price=6002.0, timestamp="2026-08-17T14:05:00Z", order_id=11, pnl=10.0),
    ]
    orders = [{"id": 10, "customTag": "candidate-gap-fade-v1"}]

    closed, unresolved = pair_mes_round_trips(trades, orders=orders)

    assert unresolved == []
    assert len(closed) == 1
    assert closed[0]["broker_confirmed"] is True
    assert closed[0]["custom_tag"] == "candidate-gap-fade-v1"
    assert closed[0]["calculated_gross_pnl"] == 10.0
    assert closed[0]["calculated_net_pnl"] == 8.78


def test_trade_shape_uses_bid_for_long_liquidation_and_detects_giveback() -> None:
    round_trip = {
        "round_trip_id": "1:2:0",
        "contract_id": "CON.F.US.MES.U26",
        "side": "long",
        "entry_time_utc": "2026-08-17T14:00:00Z",
        "exit_time_utc": "2026-08-17T14:05:00Z",
        "entry_price": 6000.0,
        "exit_price": 6000.5,
    }
    events = [
        {
            "event_type": "quote",
            "contract_id": "CON.F.US.MES.U26",
            "source_timestamp": "2026-08-17T14:01:00Z",
            "payload": {"bestBid": 6002.0, "bestAsk": 6002.25},
        },
        {
            "event_type": "quote",
            "contract_id": "CON.F.US.MES.U26",
            "source_timestamp": "2026-08-17T14:04:00Z",
            "payload": {"bestBid": 6000.5, "bestAsk": 6000.75},
        },
    ]

    shaped = attach_executable_trade_shape(round_trip, events)

    assert shaped["mfe_ticks"] == 8.0
    assert shaped["realized_ticks"] == 2.0
    assert shaped["winner_giveback"] is True
    assert shaped["trade_shape"] == "winner_giveback"


def test_report_excludes_unmatched_and_non_broker_outcomes() -> None:
    trades = [_fill(1, side=0, price=6000.0, timestamp="2026-08-17T14:00:00Z", order_id=10, pnl=None)]

    report = build_report(trades, [], [], generated_at=datetime(2026, 8, 17, tzinfo=timezone.utc))

    assert report["round_trip_count"] == 0
    assert report["unresolved_fill_count"] == 1
    assert report["outcome_authority"] == "projectx_trade_search_only"
    assert report["can_submit_orders"] is False


class _Transport:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def post(self, url: str, payload: dict[str, Any], headers: dict[str, str]) -> dict[str, Any]:
        self.calls.append({"url": url, "payload": payload, "headers": headers})
        key = "orders" if url.endswith("/api/Order/search") else "trades"
        return {"success": True, key: []}


def test_adapter_history_searches_are_read_only_and_use_utc_bounds(tmp_path: Path) -> None:
    transport = _Transport()
    adapter = TopstepXPracticeAdapter(username="u", api_key="k", transport=transport)
    adapter._token = "session"  # authenticated fixture; no network call
    account = PracticeAccount(42, "PRACTICE", 150000.0, True, True)
    start = datetime(2026, 8, 1, tzinfo=timezone.utc)
    end = datetime(2026, 8, 2, tzinfo=timezone.utc)

    assert adapter.search_orders(account, start=start, end=end) == []
    assert adapter.search_trades(account, start=start, end=end) == []

    assert [call["url"].rsplit("/", 2)[-2:] for call in transport.calls] == [
        ["Order", "search"],
        ["Trade", "search"],
    ]
    assert all(call["payload"]["accountId"] == 42 for call in transport.calls)


from __future__ import annotations

from scripts.options_reporting import dedupe_options_trade_records


def test_closed_duplicates_use_most_complete_order_lifecycle() -> None:
    recovered = {
        "id": "recovered-o1", "order_id": "o1", "status": "closed",
        "opened_at": "2026-07-01T14:00:00Z", "net_credit": 0.5,
    }
    original = {
        "id": "original", "order_id": "o1", "status": "closed",
        "opened_at": "2026-07-01T14:00:00Z", "closed_at": "2026-07-02T14:00:00Z",
        "closing_reason": "profit target", "net_credit": 0.5, "pnl": 50,
    }

    rows = dedupe_options_trade_records([recovered, original])

    assert rows == [original]


def test_open_and_missing_order_id_records_are_never_collapsed() -> None:
    rows = [
        {"id": "open-a", "order_id": "o1", "status": "open"},
        {"id": "open-b", "order_id": "o1", "status": "open"},
        {"id": "legacy-a", "status": "closed"},
        {"id": "legacy-b", "status": "closed"},
    ]

    assert dedupe_options_trade_records(rows) == rows


def test_tie_prefers_non_recovered_record() -> None:
    recovered = {"id": "recovered-o2", "order_id": "o2", "status": "closed", "net_credit": 0.4}
    original = {"id": "original-o2", "order_id": "o2", "status": "closed", "net_credit": 0.4}

    assert dedupe_options_trade_records([recovered, original]) == [original]

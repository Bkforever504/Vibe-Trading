from __future__ import annotations

from dataclasses import dataclass

from research.mes_mbo_phase_a import BookState, audit_records


@dataclass
class Event:
    ts_recv: int
    action: str
    side: str
    order_id: int
    price: int
    size: int
    flags: int = 128


def test_book_applies_databento_resting_order_semantics() -> None:
    book = BookState()
    book.apply("A", "B", 1, 100, 10)
    book.apply("A", "A", 2, 102, 8)
    assert book.best("B") == (100, 10)
    assert book.best("A") == (102, 8)
    book.apply("C", "B", 1, 100, 4)
    book.apply("M", "A", 2, 101, 6)
    assert book.best("B") == (100, 6)
    assert book.best("A") == (101, 6)
    book.apply("F", "B", 1, 100, 3)
    assert book.best("B") == (100, 6)


def test_phase_a_report_is_outcome_blind_and_has_quality_gates() -> None:
    start = 13 * 3_600_000_000_000 + 30 * 60_000_000_000
    events = [
        Event(0, "R", "N", 0, 0, 0, flags=32),
        Event(0, "A", "B", 1, 100_000_000_000, 10, flags=32),
        Event(0, "A", "A", 2, 100_250_000_000, 10, flags=32 | 128),
        Event(start, "A", "B", 3, 100_000_000_000, 2),
        Event(start + 1, "C", "B", 3, 100_000_000_000, 2),
        Event(start + 5_000_000_000, "N", "N", 0, 0, 0),
    ]
    report = audit_records(events)
    assert report["snapshot_clear_seen"] is True
    assert report["windows"]["count"] == 2
    assert report["quality_gates"]["all_pass"] is True
    rendered = str(report).lower()
    assert "profit" not in rendered
    assert "pnl" not in rendered

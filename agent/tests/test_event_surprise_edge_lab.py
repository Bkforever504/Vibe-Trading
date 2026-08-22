from __future__ import annotations

from research import event_surprise_edge_lab as lab


def valid_row(index: int = 0) -> dict[str, str]:
    return {
        "event_id": f"cpi-{index}", "event_name": "cpi_yoy",
        "released_at_utc": "2026-01-10T13:30:00Z", "consensus": "2.8",
        "consensus_asof_utc": "2026-01-10T13:29:00Z", "actual_first_release": "3.0",
        "actual_vintage": "first_release", "entry_at_utc": "2026-01-10T13:30:01Z",
        "entry_bid": "6000.00", "entry_ask": "6000.25", "exit_at_utc": "2026-01-10T13:45:00Z",
        "exit_bid": "5998.00", "exit_ask": "5998.25", "source": "fixture",
    }


def test_rejects_consensus_captured_after_release() -> None:
    row = valid_row()
    row["consensus_asof_utc"] = "2026-01-10T13:31:00Z"
    assert "row_1:consensus_not_point_in_time" in lab.validate_rows([row])


def test_rejects_revised_actual() -> None:
    row = valid_row()
    row["actual_vintage"] = "latest_revised"
    assert "row_1:actual_not_first_release" in lab.validate_rows([row])


def test_valid_point_in_time_row_passes_integrity() -> None:
    assert lab.validate_rows([valid_row()]) == []


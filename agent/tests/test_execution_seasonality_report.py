from scripts.execution_seasonality_report import build_report


def test_execution_friction_reconciles_midpoint_and_executable_pnl():
    rows = []
    for index in range(10):
        candidate_id = f"candidate-{index}"
        rows.extend([
            {
                "type": "candidate",
                "candidate_id": candidate_id,
                "created_at": f"2026-08-{3 + index:02d}T14:00:00Z",
                "expiry": "2026-08-21",
                "strategy": "put_spread",
                "effective_qty": 1,
                "quoted_mid_credit": 1.20,
                "executable_entry_credit": 1.00,
                "entry_quote_complete": True,
            },
            {
                "type": "mark",
                "candidate_id": candidate_id,
                "marked_at": f"2026-08-{3 + index:02d}T15:00:00Z",
                "executable_close_debit": 0.60,
                "legs": [
                    {"side": "sell", "bid": 1.00, "ask": 1.20, "ratio_qty": 1},
                    {"side": "buy", "bid": 0.50, "ask": 0.70, "ratio_qty": 1},
                ],
            },
            {
                "type": "outcome",
                "candidate_id": candidate_id,
                "resolved_at": f"2026-08-{3 + index:02d}T15:00:00Z",
                "quantity": 1,
                "pnl_before_fees": 40.0,
            },
        ])

    report = build_report(rows)

    overall = report["overall"]
    assert overall["count"] == 10
    assert overall["average_executable_pnl_before_fees"] == 40.0
    assert overall["average_round_trip_friction_dollars"] == 30.0
    assert overall["average_midpoint_benchmark_pnl"] == 70.0
    assert overall["status"] == "rankable"
    assert report["buckets"]["entry_window_et"]["open_0930_1030"]["count"] == 10
    assert report["execution_enabled"] is False

from scripts.flip_paper_operations_readiness import CORE_TASKS, build_report


def test_ready_report_has_no_order_authority(monkeypatch) -> None:
    tasks = [
        {
            "name": name,
            "enabled": True,
            "wake_to_run": True,
            "start_when_available": True,
        }
        for name in CORE_TASKS
    ]
    report = build_report(
        {
            "status": "ACTIVE",
            "trading_blocked": False,
            "account_blocked": False,
            "options_trading_level": 3,
        },
        {"is_open": False, "next_open": "2026-08-17T13:30:00Z"},
        tasks,
        [],
    )

    assert report["status"] == "ready_but_inactive"
    assert report["activity_status"] == "no_orders_in_21_days"
    assert report["can_submit_orders"] is False
    assert report["orders_submitted_by_report"] == 0


def test_missing_task_blocks_readiness() -> None:
    report = build_report(
        {
            "status": "ACTIVE",
            "trading_blocked": False,
            "account_blocked": False,
            "options_trading_level": 3,
        },
        {},
        [],
        [],
    )

    assert report["status"] == "blocked"
    assert report["checks"]["core_tasks_present"] is False

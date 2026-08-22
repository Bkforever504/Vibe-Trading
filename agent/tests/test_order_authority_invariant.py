from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from scripts.live_trading_cockpit import build_cockpit
from scripts.order_authority_invariant import runtime_violations, static_violations


def test_dashboard_runtime_contains_no_true_authority_flag(tmp_path: Path) -> None:
    payload = build_cockpit(report_dir=tmp_path, now=datetime(2026, 8, 22, tzinfo=timezone.utc))
    assert runtime_violations(payload) == []


def test_dashboard_source_has_no_true_authority_literal() -> None:
    assert static_violations() == []


def test_runtime_guard_detects_nested_violation() -> None:
    assert runtime_violations({"nested": [{"can_submit_orders": True}]}) == ["$.nested[0].can_submit_orders"]

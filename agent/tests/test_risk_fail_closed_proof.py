from __future__ import annotations

from scripts import risk_fail_closed_proof as proof


def test_risk_fail_closed_proof_passes_dirty_reconciliation_cases() -> None:
    report = proof.build_report()
    cases = {case["name"]: case for case in report["cases"]}

    assert report["execution_enabled"] is False
    assert report["can_submit_orders"] is False
    assert report["passed"] is True
    assert cases["clean_book_allows_entries"]["actual_entries_allowed"] is True
    assert cases["missing_active_leg_blocks_entries"]["actual_entries_allowed"] is False
    assert cases["unexplained_extra_leg_blocks_entries"]["actual_entries_allowed"] is False
    assert cases["closed_group_still_open_blocks_entries"]["actual_entries_allowed"] is False

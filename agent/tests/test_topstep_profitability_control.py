from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from strategies.topstep_prop_bot import apply_profitability_control


NOW = datetime(2026, 8, 19, 15, 0, tzinfo=timezone.utc)


def test_cash_vote_demotes_topstep_paper_candidate_to_shadow() -> None:
    result = apply_profitability_control(
        {"status": "paper_candidate", "recommendation": "eligible_for_existing_paper_gates", "reasons": []},
        lane="topstep_intraday_futures",
        report={
            "generated_at": "2026-08-19T14:00:00Z",
            "capital_decision": {"action": "hold_cash_collect_counterfactuals", "selected": []},
        },
        now=NOW,
    )

    assert result["status"] == "shadow_observe"
    assert result["profitability_control"]["allows_practice"] is False
    assert result["can_submit_orders"] is False


def test_selected_lane_can_only_preserve_an_existing_paper_candidate() -> None:
    report = {
        "generated_at": "2026-08-19T14:00:00Z",
        "capital_decision": {
            "action": "paper_candidates_available",
            "selected": [{"lane": "topstep_intraday_futures"}],
        },
    }
    eligible = apply_profitability_control(
        {"status": "paper_candidate", "recommendation": "eligible", "reasons": []},
        lane="topstep_intraday_futures",
        report=report,
        now=NOW,
    )
    unproven = apply_profitability_control(
        {"status": "shadow_observe", "recommendation": "observe", "reasons": []},
        lane="topstep_intraday_futures",
        report=report,
        now=NOW,
    )

    assert eligible["status"] == "paper_candidate"
    assert unproven["status"] == "shadow_observe"
    assert eligible["can_submit_orders"] is False


def test_stale_control_report_fails_closed_for_practice() -> None:
    result = apply_profitability_control(
        {"status": "paper_candidate", "recommendation": "eligible", "reasons": []},
        lane="topstep_intraday_futures",
        report={
            "generated_at": "2026-08-17T10:00:00Z",
            "capital_decision": {
                "action": "paper_candidates_available",
                "selected": [{"lane": "topstep_intraday_futures"}],
            },
        },
        now=NOW,
    )

    assert result["status"] == "shadow_observe"
    assert result["profitability_control"]["source_status"] == "stale_or_missing"


from __future__ import annotations

import json

from research import novel_information_edge_report as report


def test_report_never_grants_execution_and_requires_real_survivor(tmp_path, monkeypatch) -> None:
    payloads = {
        "options": {"resolved_count": 2, "review_gate": {"passed": False}},
        "flow": {"verdict": "rejected_infeasible_zero_candidate_windows", "candidate_windows": 0},
        "lead": {"common_session_count": 61, "survivor_count": 0},
        "events": {"status": "missing_point_in_time_consensus_data", "resolved_count": 0},
    }
    paths = {}
    for name, payload in payloads.items():
        path = tmp_path / f"{name}.json"
        path.write_text(json.dumps(payload), encoding="utf-8")
        paths[name] = path
    monkeypatch.setattr(report, "SOURCES", {
        "options_microstructure": paths["options"], "signed_order_flow": paths["flow"],
        "cross_asset_lead_lag": paths["lead"], "event_surprises": paths["events"],
    })
    result = report.build_report()
    assert result["decision"] == "no_new_information_edge_qualified"
    assert result["promotable_track_count"] == 0
    assert result["execution_enabled"] is False
    assert result["can_submit_orders"] is False


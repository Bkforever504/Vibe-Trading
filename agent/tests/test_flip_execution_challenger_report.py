from __future__ import annotations

import json
from pathlib import Path

from scripts.flip_execution_challenger_report import build_report


def test_execution_report_scores_delta_and_passive_fill_opportunities(tmp_path: Path) -> None:
    source = tmp_path / "shadow.jsonl"
    row = {
        "action": "exit_shadow",
        "contract_selection_challengers": [
            {
                "variant": "itm_delta_60",
                "selection_delta": 0.61,
                "passive_limit_mid": 2.05,
                "passive_limit_mid_plus_tick": 2.06,
                "marketable_limit_ask": 2.10,
                "passive_mid_fill_observed": True,
                "passive_plus_tick_fill_observed": True,
                "executable_return_pct": 20.0,
            },
            {
                "variant": "atm",
                "passive_limit_mid": 1.00,
                "passive_limit_mid_plus_tick": 1.01,
                "marketable_limit_ask": 1.05,
                "passive_mid_fill_observed": False,
                "passive_plus_tick_fill_observed": True,
                "executable_return_pct": 10.0,
            },
        ],
    }
    source.write_text(json.dumps(row) + "\n", encoding="utf-8")

    report = build_report(source)
    by_variant = {row["variant"]: row for row in report["variants"]}

    assert report["read_only"] is True
    assert report["can_submit_orders"] is False
    assert by_variant["itm_delta_60"]["delta_observations"] == 1
    assert by_variant["itm_delta_60"]["passive_mid_fill_opportunity_rate"] == 1.0
    assert by_variant["atm"]["passive_mid_fill_opportunity_rate"] == 0.0
    assert by_variant["atm"]["passive_plus_tick_fill_opportunity_rate"] == 1.0
    assert report["promotion_ready"] is False

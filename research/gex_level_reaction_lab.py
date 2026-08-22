"""Evidence report for causal GEX level reactions. Research only."""
from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LEDGER = ROOT / "data" / "gex_level_reaction_ledger.jsonl"
OUT = ROOT / "data" / "gex_level_reaction_report.json"


def _summary(rows: list[dict]) -> dict:
    resolved = [row for row in rows if row.get("outcome", {}).get("status") == "resolved"]
    values = [float(row["outcome"]["gross_r"]) for row in resolved]
    dates = {row["confirmation_timestamp"][:10] for row in resolved}
    return {
        "resolved_events": len(resolved),
        "independent_dates": len(dates),
        "win_rate": round(sum(value > 0 for value in values) / len(values), 4) if values else None,
        "average_gross_r": round(sum(values) / len(values), 4) if values else None,
        "profit_factor_r": (
            round(sum(value for value in values if value > 0) / abs(sum(value for value in values if value < 0)), 4)
            if any(value < 0 for value in values) else None
        ),
    }


def build_report(rows: list[dict]) -> dict:
    groups: dict[str, list[dict]] = defaultdict(list)
    for row in rows:
        groups["rank_1_wall" if int(row["level_rank"]) == 1 else "rank_2_to_5_controls"].append(row)
        groups[f"sequence:{row['sequence']}"] .append(row)
        groups[f"symbol:{row['symbol']}"] .append(row)
    summaries = {name: _summary(group) for name, group in sorted(groups.items())}
    wall = summaries.get("rank_1_wall", {})
    controls = summaries.get("rank_2_to_5_controls", {})
    eligible = (
        int(wall.get("resolved_events") or 0) >= 30
        and int(wall.get("independent_dates") or 0) >= 20
        and int(controls.get("resolved_events") or 0) >= 30
    )
    wall_r = wall.get("average_gross_r")
    control_r = controls.get("average_gross_r")
    return {
        "research_question": "Do point-in-time rank-1 GEX levels predict completed-bar reactions better than ranks 2-5?",
        "execution_enabled": False,
        "can_submit_orders": False,
        "method": "snapshot_before_touch_then_completed_bar_rejection_or_break_retest",
        "friction_status": "underlying_reaction_only_options_friction_not_yet_measured",
        "groups": summaries,
        "review_gate": {
            "eligible": eligible,
            "requirements": "30 resolved rank-1, 30 resolved controls, 20 independent dates",
            "wall_minus_control_average_r": (
                round(float(wall_r) - float(control_r), 4)
                if wall_r is not None and control_r is not None else None
            ),
            "promotion_allowed": False,
            "note": "Eligibility triggers review only; this report cannot change execution or sizing.",
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--print", action="store_true")
    args = parser.parse_args()
    rows = []
    if LEDGER.exists():
        rows = [json.loads(line) for line in LEDGER.read_text(encoding="utf-8").splitlines() if line.strip()]
    report = build_report(rows)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    if args.print:
        print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

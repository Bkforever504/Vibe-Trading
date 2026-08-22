#!/usr/bin/env python3
"""Aggregate the four new-information edge tracks without execution authority."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "data" / "novel_information_edge_report.json"
SOURCES = {
    "options_microstructure": ROOT / "data" / "options_nbbo_curriculum_results.json",
    "signed_order_flow": ROOT / "data" / "mes_absorption_phase_b_results.json",
    "cross_asset_lead_lag": ROOT / "data" / "cross_asset_lead_lag_results.json",
    "event_surprises": ROOT / "data" / "event_surprise_edge_results.json",
}


def _read(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def build_report() -> dict[str, Any]:
    options = _read(SOURCES["options_microstructure"])
    flow = _read(SOURCES["signed_order_flow"])
    lead_lag = _read(SOURCES["cross_asset_lead_lag"])
    events = _read(SOURCES["event_surprises"])
    tracks = {
        "options_microstructure": {
            "status": "insufficient_n" if options.get("resolved_count", 0) < 30 else options.get("status"),
            "resolved": options.get("resolved_count", 0), "required": 30,
            "review_gate_passed": bool(options.get("review_gate", {}).get("passed")),
        },
        "signed_order_flow": {
            "status": flow.get("verdict", "missing_result"),
            "candidate_windows": flow.get("candidate_windows", 0),
            "development_pass": bool(flow.get("development_pass")),
        },
        "cross_asset_lead_lag": {
            "status": "development_survivors" if lead_lag.get("survivor_count") else "rejected_development",
            "session_count": lead_lag.get("common_session_count", 0),
            "survivor_count": lead_lag.get("survivor_count", 0),
        },
        "event_surprises": {
            "status": events.get("status", "missing_result"),
            "resolved": events.get("resolved_count", 0),
        },
    }
    promotable = [name for name, value in tracks.items() if value.get("review_gate_passed") or value.get("survivor_count", 0) > 0 or value.get("status") == "eligible_for_review"]
    return {
        "provider": "novel_information_edge_report", "mode": "read_only_research",
        "execution_enabled": False, "can_submit_orders": False,
        "tracks": tracks, "promotable_track_count": len(promotable), "promotable_tracks": promotable,
        "decision": "no_new_information_edge_qualified" if not promotable else "human_review_required",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=OUTPUT)
    parser.add_argument("--print", action="store_true", dest="print_report")
    args = parser.parse_args()
    report = build_report()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    temp = args.output.with_suffix(args.output.suffix + ".tmp")
    temp.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(temp, args.output)
    print(json.dumps(report, indent=2, sort_keys=True) if args.print_report else report["decision"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


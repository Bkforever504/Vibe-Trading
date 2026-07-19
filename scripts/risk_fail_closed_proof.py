#!/usr/bin/env python3
"""Read-only proof that dirty options reconciliation fails closed."""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from strategies import options_state


VIBE_HOME = Path.home() / ".vibe-trading"
REPORT_PATH = VIBE_HOME / "reports" / "risk-fail-closed-proof.json"
LOG_PATH = ROOT / "data" / "risk_fail_closed_proof_log.jsonl"


def _trade(status: str = "open") -> dict[str, Any]:
    return {
        "id": "proof-condor",
        "label": "Proof Condor",
        "strategy": "iron_condor",
        "status": status,
        "qty": 1,
        "legs": [
            "IWM260807P00275000",
            "IWM260807P00277000",
            "IWM260807C00313000",
            "IWM260807C00315000",
        ],
    }


def _positions(*, missing_leg: bool = False, extra_leg: bool = False) -> list[dict[str, Any]]:
    rows = [
        {"symbol": "IWM260807P00275000", "qty": -1},
        {"symbol": "IWM260807P00277000", "qty": 1},
        {"symbol": "IWM260807C00313000", "qty": -1},
        {"symbol": "IWM260807C00315000", "qty": 1},
    ]
    if missing_leg:
        rows = [row for row in rows if row["symbol"] != "IWM260807P00275000"]
    if extra_leg:
        rows.append({"symbol": "IWM260807P00290000", "qty": 1})
    return rows


def _case(name: str, trades: list[dict[str, Any]], positions: list[dict[str, Any]], expected_allowed: bool) -> dict[str, Any]:
    rec = options_state.reconcile(trades, positions)
    passed = rec.get("entries_allowed") is expected_allowed
    return {
        "name": name,
        "passed": passed,
        "expected_entries_allowed": expected_allowed,
        "actual_entries_allowed": rec.get("entries_allowed"),
        "status": rec.get("status"),
        "findings": rec.get("findings") or [],
        "unexplained_residual": rec.get("unexplained_residual") or {},
        "closed_groups_still_open": rec.get("closed_groups_still_open") or [],
    }


def build_report() -> dict[str, Any]:
    cases = [
        _case("clean_book_allows_entries", [_trade("open")], _positions(), True),
        _case("missing_active_leg_blocks_entries", [_trade("open")], _positions(missing_leg=True), False),
        _case("unexplained_extra_leg_blocks_entries", [_trade("open")], _positions(extra_leg=True), False),
        _case("closed_group_still_open_blocks_entries", [_trade("closed")], _positions(), False),
    ]
    return {
        "provider": "risk_fail_closed_proof",
        "mode": "read_only",
        "execution_enabled": False,
        "can_submit_orders": False,
        "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "passed": all(case["passed"] for case in cases),
        "case_count": len(cases),
        "cases": cases,
        "warnings": [
            "Read-only deterministic proof. This report cannot submit orders.",
            "Dirty reconciliation must keep entries_allowed=false before scorecard risk can reach 10.",
        ],
    }


def write_report(report: dict[str, Any], path: Path = REPORT_PATH) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(temp, path)


def append_log(report: dict[str, Any], path: Path = LOG_PATH) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(report, separators=(",", ":"), sort_keys=True) + "\n")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report-path", type=Path, default=REPORT_PATH)
    parser.add_argument("--log-path", type=Path, default=LOG_PATH)
    parser.add_argument("--print", action="store_true", dest="do_print")
    args = parser.parse_args()
    report = build_report()
    write_report(report, args.report_path)
    append_log(report, args.log_path)
    if args.do_print:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        print(f"Risk fail-closed proof written to {args.report_path}")
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

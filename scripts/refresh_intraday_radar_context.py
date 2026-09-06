#!/usr/bin/env python3
"""Attach freshly fetched context to the current read-only radar snapshot.

The radar discovers and ranks only from its completed-bar inputs.  SEC filing
provenance and same-clock IEX relative volume are fetched immediately after
that discovery pass.  This narrow refresh keeps the dashboard on the same
snapshot while preserving the original rank, confirmation, and zero-order
authority.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping
from zoneinfo import ZoneInfo

# Scheduled-task runners invoke this file by path (``python scripts\\...``),
# which otherwise puts only ``scripts`` on ``sys.path`` rather than the repo
# root needed for the package import below.
REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.intraday_opportunity_radar import (
    MARKET_TZ,
    attach_aplus_evidence,
    attach_primary_catalysts,
    attach_time_matched_rvol,
)

VIBE_HOME = Path.home() / ".vibe-trading"
REPORT_PATH = VIBE_HOME / "reports" / "intraday-opportunity-radar.json"
RVOL_PATH = VIBE_HOME / "reports" / "intraday-rvol-baseline.json"
SEC_PATH = VIBE_HOME / "reports" / "sec-catalyst-feed.json"


def _read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def _parse_observed_at(value: Any) -> datetime:
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).astimezone(MARKET_TZ)
    except ValueError:
        return datetime.now(timezone.utc).astimezone(MARKET_TZ)


def _atomic_json(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    handle, temporary = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(handle, "w", encoding="utf-8") as output:
            json.dump(value, output, indent=2, sort_keys=True)
            output.write("\n")
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def refresh_report(
    radar: dict[str, Any], rvol: Mapping[str, Any], sec: Mapping[str, Any], observed_at: datetime
) -> dict[str, Any]:
    """Refresh evidence fields without changing discovery, score, or rank."""
    ranked = radar.get("ranked_candidates")
    if not isinstance(ranked, list):
        return radar
    candidates = [row for row in ranked if isinstance(row, dict)]
    attach_time_matched_rvol(candidates, rvol)
    attach_primary_catalysts(candidates, sec, observed_at)
    attach_aplus_evidence(candidates, observed_at)
    radar["ranked_candidates"] = candidates

    actionable_symbols = {
        str(row.get("symbol") or "").upper()
        for row in radar.get("actionable_ranked_candidates") or []
        if isinstance(row, Mapping)
    }
    radar["actionable_ranked_candidates"] = [
        row for row in candidates if str(row.get("symbol") or "").upper() in actionable_symbols
    ]
    coverage = radar.get("coverage")
    if isinstance(coverage, dict):
        coverage["a_plus_process_candidate_count"] = sum(
            (row.get("a_plus_evidence") or {}).get("eligible_for_a_plus_label") is True for row in candidates
        )
        coverage["a_plus_evidence_incomplete_count"] = sum(
            (row.get("a_plus_evidence") or {}).get("classification") == "evidence_incomplete" for row in candidates
        )
        coverage["time_matched_rvol_available_count"] = sum(
            (row.get("time_matched_rvol") or {}).get("status") == "available_iex_relative" for row in candidates
        )
        coverage["time_matched_rvol_baseline"] = {
            "status": "available" if rvol else "unavailable",
            "generated_at": rvol.get("generated_at"),
            "source": rvol.get("provider"),
            "errors": len(rvol.get("errors") or []),
            "authority": "context_only_no_gate_or_sizing_effect",
        }
        coverage["primary_catalyst_feed"] = {
            "status": sec.get("status") or "unavailable",
            "generated_at": sec.get("generated_at"),
            "matched_candidate_count": sum(
                (row.get("primary_catalyst") or {}).get("status") == "verified_primary_sec" for row in candidates
            ),
            "authority": "provenance_only_no_rank_or_execution_effect",
        }
    radar["context_refreshed_at"] = observed_at.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
    radar["context_refresh_authority"] = "context_and_provenance_only_no_rank_alert_sizing_or_execution_effect"
    radar["execution_enabled"] = False
    radar["can_submit_orders"] = False
    return radar


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--radar-path", type=Path, default=REPORT_PATH)
    parser.add_argument("--rvol-path", type=Path, default=RVOL_PATH)
    parser.add_argument("--sec-path", type=Path, default=SEC_PATH)
    args = parser.parse_args()
    radar = _read_json(args.radar_path)
    if not radar:
        print("Radar context refresh: skipped (radar snapshot unavailable)")
        return 0
    refreshed = refresh_report(radar, _read_json(args.rvol_path), _read_json(args.sec_path), _parse_observed_at(radar.get("as_of_et")))
    _atomic_json(args.radar_path, refreshed)
    print(f"Radar context refresh: candidates={len(refreshed.get('ranked_candidates') or [])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

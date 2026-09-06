#!/usr/bin/env python3
"""Summarize the radar's same-snapshot intraday sector posture.

This is deliberately descriptive: it turns the already timestamped sector ETF
returns in the radar into breadth and concentration context.  It is not a
directional signal, a rank override, or an order interface.
"""
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from statistics import median
from typing import Any, Mapping

VIBE_HOME = Path.home() / ".vibe-trading"
RADAR_PATH = VIBE_HOME / "reports" / "intraday-opportunity-radar.json"
REPORT_PATH = VIBE_HOME / "reports" / "intraday-sector-posture.json"


def _finite(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number


def build_posture(snapshot: Mapping[str, Any]) -> dict[str, Any]:
    sectors = [row for row in snapshot.get("sector_leaders") or [] if isinstance(row, Mapping)]
    sectors += [row for row in snapshot.get("sector_laggards") or [] if isinstance(row, Mapping)]
    unique = {str(row.get("etf") or "").upper(): dict(row) for row in sectors if str(row.get("etf") or "")}
    rows = list(unique.values())
    returns = [_finite(row.get("session_return_pct")) for row in rows]
    values = [value for value in returns if value is not None]
    if len(values) < 2:
        return {
            "status": "unavailable",
            "reason": "insufficient_same_snapshot_sector_returns",
            "execution_enabled": False,
            "can_submit_orders": False,
        }
    positive = sum(value > 0 for value in values)
    negative = sum(value < 0 for value in values)
    flat = len(values) - positive - negative
    spy_return = _finite(snapshot.get("spy_session_return_pct"))
    share_positive = positive / len(values)
    if positive >= max(4, int(len(values) * 0.7)) and (spy_return or 0.0) > 0:
        state = "broad_positive_participation"
    elif negative >= max(4, int(len(values) * 0.7)) and (spy_return or 0.0) < 0:
        state = "broad_negative_participation"
    elif positive <= max(1, int(len(values) * 0.3)) or negative <= max(1, int(len(values) * 0.3)):
        state = "narrow_or_concentrated_participation"
    else:
        state = "mixed_participation"
    ordered = sorted(rows, key=lambda row: _finite(row.get("session_return_pct")) or 0.0, reverse=True)
    return {
        "status": "available",
        "state": state,
        "sector_count_observed": len(values),
        "positive_count": positive,
        "negative_count": negative,
        "flat_count": flat,
        "positive_share": round(share_positive, 3),
        "median_sector_return_pct": round(median(values), 3),
        "spy_session_return_pct": spy_return,
        "qqq_spy_regime": snapshot.get("qqq_spy_regime"),
        "leaders": ordered[:3],
        "laggards": list(reversed(ordered[-3:])),
        "return_basis": "same_radar_snapshot_session_return_proxy",
        "authority": "context_only_no_rank_gate_sizing_or_execution_effect",
        "execution_enabled": False,
        "can_submit_orders": False,
    }


def build_report(radar: Mapping[str, Any]) -> dict[str, Any]:
    coverage = radar.get("coverage") if isinstance(radar.get("coverage"), Mapping) else {}
    snapshot = coverage.get("market_context_snapshot") if isinstance(coverage.get("market_context_snapshot"), Mapping) else {}
    return {
        "schema_version": 1,
        "provider": "intraday_sector_posture",
        "mode": "read_only_context",
        "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "radar_date": radar.get("date"),
        "radar_as_of_et": radar.get("as_of_et"),
        "posture": build_posture(snapshot),
        "execution_enabled": False,
        "can_submit_orders": False,
        "warning": "Sector posture describes participation breadth from the current radar snapshot; it does not predict a trade or authorize an order.",
    }


def _read(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--radar-path", type=Path, default=RADAR_PATH)
    parser.add_argument("--report-path", type=Path, default=REPORT_PATH)
    args = parser.parse_args()
    report = build_report(_read(args.radar_path))
    args.report_path.parent.mkdir(parents=True, exist_ok=True)
    args.report_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"Intraday sector posture: {report['posture'].get('state', 'unavailable')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

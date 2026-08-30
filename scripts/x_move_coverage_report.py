#!/usr/bin/env python3
"""X-vs-ground-truth coverage report.

Joins X intake observations against move-ground-truth-summary.json to measure
whether X flagged a symbol BEFORE / DURING a resolved ground-truth move.

Emits ~/.vibe-trading/reports/x-move-coverage.json with:
  - hit_count / miss_count per direction
  - median lead-time (minutes before move start)
  - top hits (symbol, date, X handles that flagged, lead-time)

Context-only. No execution authority.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from statistics import median
from typing import Any

VIBE_HOME = Path.home() / ".vibe-trading"
OBSERVATIONS_PATH = VIBE_HOME / "social-arb-observations.json"
GROUND_TRUTH_PATH = VIBE_HOME / "reports" / "move-ground-truth-summary.json"
REPORT_PATH = VIBE_HOME / "reports" / "x-move-coverage.json"


def _parse_iso(value: Any) -> datetime | None:
    if not value:
        return None
    text = str(value).replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _load(path: Path, fallback: Any) -> Any:
    if not path.exists():
        return fallback
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except json.JSONDecodeError:
        return fallback


def _x_index(observations: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    """symbol -> list of (observed_at, handle, url, lane)"""
    idx: dict[str, list[dict[str, Any]]] = {}
    for row in observations:
        if not isinstance(row, dict):
            continue
        if str(row.get("platform") or "").lower() != "x":
            continue
        symbol = str(row.get("keyword") or "").lstrip("$").upper()
        if not symbol:
            continue
        idx.setdefault(symbol, []).append({
            "observed_at": _parse_iso(row.get("observed_at")),
            "handle": row.get("handle"),
            "url": row.get("url"),
            "lane": row.get("source"),
            "likes": row.get("likes") or 0,
            "views": row.get("views") or 0,
        })
    return idx


def build_report() -> dict[str, Any]:
    observations = _load(OBSERVATIONS_PATH, [])
    ground_truth = _load(GROUND_TRUTH_PATH, {})
    moves = ground_truth.get("moves") or []
    x_idx = _x_index(observations if isinstance(observations, list) else [])

    hits: list[dict[str, Any]] = []
    misses: list[dict[str, Any]] = []
    lead_minutes: list[float] = []

    for move in moves:
        symbol = str(move.get("symbol") or "").upper()
        if not symbol:
            continue
        move_start = _parse_iso(move.get("window_start") or move.get("start_at") or move.get("date"))
        move_end = _parse_iso(move.get("window_end") or move.get("end_at")) or move_start
        direction = move.get("direction")
        candidates = x_idx.get(symbol) or []
        matched = [
            c for c in candidates
            if c["observed_at"] and move_start and c["observed_at"] <= (move_end or move_start)
        ]
        if not matched:
            misses.append({"symbol": symbol, "date": move.get("date"), "direction": direction})
            continue
        matched.sort(key=lambda c: c["observed_at"])
        first = matched[0]
        lead = None
        if move_start and first["observed_at"]:
            lead = (move_start - first["observed_at"]).total_seconds() / 60.0
            lead_minutes.append(lead)
        hits.append({
            "symbol": symbol,
            "date": move.get("date"),
            "direction": direction,
            "lead_minutes": round(lead, 2) if lead is not None else None,
            "flagged_by": sorted({str(c["handle"]) for c in matched if c.get("handle")})[:10],
            "lanes": sorted({str(c["lane"]) for c in matched if c.get("lane")}),
            "flag_count": len(matched),
        })

    total = len(hits) + len(misses)
    coverage_pct = round(100.0 * len(hits) / total, 2) if total else 0.0
    lead_median = round(median(lead_minutes), 2) if lead_minutes else None

    hits.sort(key=lambda h: (h.get("lead_minutes") or -1e9), reverse=True)

    report = {
        "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "provider": "x_move_coverage_report",
        "mode": "context_only",
        "execution_enabled": False,
        "ground_truth_moves": total,
        "x_observations": sum(len(v) for v in x_idx.values()),
        "hit_count": len(hits),
        "miss_count": len(misses),
        "coverage_pct": coverage_pct,
        "median_lead_minutes": lead_median,
        "top_hits": hits[:25],
        "top_misses": misses[:25],
    }
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(json.dumps(report, indent=2), encoding="utf-8")
    return report


def main() -> int:
    report = build_report()
    print(json.dumps({
        "coverage_pct": report["coverage_pct"],
        "hit_count": report["hit_count"],
        "miss_count": report["miss_count"],
        "median_lead_minutes": report["median_lead_minutes"],
        "x_observations": report["x_observations"],
        "ground_truth_moves": report["ground_truth_moves"],
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

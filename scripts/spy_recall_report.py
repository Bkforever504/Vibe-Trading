#!/usr/bin/env python3
"""SPY move recall report.

Denominator = spy_move_ledger.jsonl (independent, pre-outcome).
Numerator   = per-stage detection evidence from the live pipeline.

Stages tracked per move:
    1. market_move           - the move was recorded in the ledger.
    2. radar_snapshot_present - a radar snapshot exists in the lead window.
    3. radar_saw_spy          - SPY appeared in that snapshot's candidates.
    4. radar_ranked_topN      - SPY was in the top-N ranked_candidates.
    5. pattern_grader_hit     - pattern grader emitted an SPY row (dir match) in the lead window.
    6. setup_confirmed        - that hit had blockers empty AND grade >= B.
    7. contract_feasible      - optional; read from sidecar file if present, else null.
    8. x_intake_hit           - X intake observation for SPY inside the lead window.

Recall is reported per stage (not just profitable trades). Setups only earn
promotion when they repeatedly clear these stages before spread and slippage
costs.

Context-only. No execution authority.

Usage:
    python scripts/spy_recall_report.py                 # today
    python scripts/spy_recall_report.py --date 2026-08-29
    python scripts/spy_recall_report.py --days 5        # last 5 sessions in ledger
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

MARKET_TZ = ZoneInfo("America/New_York")
UTC = timezone.utc
SPEC_VERSION = "2026-08-30"

LEDGER_PATH = ROOT / "data" / "spy_move_ledger.jsonl"
RADAR_LOG = ROOT / "data" / "intraday_opportunity_radar_log.jsonl"
PATTERN_LOG = ROOT / "data" / "pattern_grader_log.jsonl"
CONTRACT_FEASIBILITY_SIDECAR = ROOT / "data" / "spy_contract_feasibility.jsonl"

VIBE_HOME = Path.home() / ".vibe-trading"
X_OBSERVATIONS_PATH = VIBE_HOME / "social-arb-observations.json"
REPORT_PATH = VIBE_HOME / "reports" / "spy_recall_report.json"

LEAD_WINDOW_MINUTES = 20
POST_WINDOW_MINUTES = 5
RANK_TOP_N = 10
CONFIRMED_GRADES = {"A+", "A", "A-", "B+", "B"}


def _parse_iso(value: Any) -> datetime | None:
    if value in (None, ""):
        return None
    text = str(value).replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)


def _load_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    out: list[dict[str, Any]] = []
    for raw in path.read_text(encoding="utf-8-sig").splitlines():
        raw = raw.strip()
        if not raw:
            continue
        try:
            row = json.loads(raw)
        except json.JSONDecodeError:
            continue
        if isinstance(row, dict):
            out.append(row)
    return out


def _load_json(path: Path, fallback: Any) -> Any:
    if not path.exists():
        return fallback
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except json.JSONDecodeError:
        return fallback


def _dir_match(move_dir: str, cand_dir: Any) -> bool:
    if not cand_dir:
        return False
    text = str(cand_dir).lower()
    up_words = {"long", "bull", "bullish", "up", "1", "+1"}
    down_words = {"short", "bear", "bearish", "down", "-1"}
    if move_dir == "up":
        return text in up_words
    if move_dir == "down":
        return text in down_words
    return False


def _spy_candidates(snapshot: dict[str, Any]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    ranked = [c for c in (snapshot.get("ranked_candidates") or []) if str(c.get("symbol", "")).upper() == "SPY"]
    filtered = [c for c in (snapshot.get("filtered_candidates") or []) if str(c.get("symbol", "")).upper() == "SPY"]
    return ranked, filtered


def _radar_rank(snapshot: dict[str, Any]) -> int | None:
    ranked = snapshot.get("ranked_candidates") or []
    for idx, cand in enumerate(ranked, start=1):
        if str(cand.get("symbol", "")).upper() == "SPY":
            return idx
    return None


def _radar_snapshot_time(snapshot: dict[str, Any]) -> datetime | None:
    return _parse_iso(snapshot.get("as_of_et") or snapshot.get("generated_at"))


def _in_window(ts: datetime | None, move_start: datetime, lead_minutes: int, post_minutes: int) -> bool:
    if ts is None:
        return False
    return (move_start - timedelta(minutes=lead_minutes)) <= ts <= (move_start + timedelta(minutes=post_minutes))


def _load_ledger(target_dates: set[str] | None) -> list[dict[str, Any]]:
    rows = _load_jsonl(LEDGER_PATH)
    if target_dates is None:
        return rows
    return [r for r in rows if r.get("date") in target_dates]


def _load_radar_relevant(target_dates: set[str]) -> list[dict[str, Any]]:
    if not RADAR_LOG.exists():
        return []
    kept: list[dict[str, Any]] = []
    with RADAR_LOG.open("r", encoding="utf-8-sig") as fh:
        for raw in fh:
            raw = raw.strip()
            if not raw:
                continue
            try:
                snap = json.loads(raw)
            except json.JSONDecodeError:
                continue
            if str(snap.get("date")) in target_dates:
                kept.append(snap)
    return kept


def _load_pattern_relevant(target_dates: set[str]) -> list[dict[str, Any]]:
    if not PATTERN_LOG.exists():
        return []
    kept: list[dict[str, Any]] = []
    with PATTERN_LOG.open("r", encoding="utf-8-sig") as fh:
        for raw in fh:
            raw = raw.strip()
            if not raw:
                continue
            try:
                row = json.loads(raw)
            except json.JSONDecodeError:
                continue
            if str(row.get("date")) not in target_dates:
                continue
            sym = str(row.get("instrument") or row.get("symbol") or "").upper()
            if sym != "SPY":
                continue
            kept.append(row)
    return kept


def _load_x_relevant(target_dates: set[str]) -> list[dict[str, Any]]:
    obs = _load_json(X_OBSERVATIONS_PATH, [])
    if not isinstance(obs, list):
        return []
    kept: list[dict[str, Any]] = []
    for row in obs:
        if not isinstance(row, dict):
            continue
        if str(row.get("platform") or "").lower() != "x":
            continue
        if str(row.get("keyword") or "").lstrip("$").upper() != "SPY":
            continue
        ts = _parse_iso(row.get("observed_at"))
        if ts is None:
            continue
        if ts.astimezone(MARKET_TZ).date().isoformat() in target_dates:
            kept.append(row)
    return kept


def _load_contract_feasibility(target_dates: set[str]) -> dict[str, dict[str, Any]]:
    rows = _load_jsonl(CONTRACT_FEASIBILITY_SIDECAR)
    out: dict[str, dict[str, Any]] = {}
    for row in rows:
        mid = row.get("move_id")
        if isinstance(mid, str) and row.get("date") in target_dates:
            out[mid] = row
    return out


def evaluate_move(
    move: dict[str, Any],
    radar_snaps: list[dict[str, Any]],
    pattern_rows: list[dict[str, Any]],
    x_rows: list[dict[str, Any]],
    contract_feasibility: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    move_start = _parse_iso(move.get("window_start_et"))
    move_dir = str(move.get("direction") or "").lower()
    stages = {
        "market_move": True,
        "radar_snapshot_present": False,
        "radar_saw_spy": False,
        "radar_ranked_topN": False,
        "pattern_grader_hit": False,
        "setup_confirmed": False,
        "contract_feasible": None,
        "x_intake_hit": False,
    }
    evidence: dict[str, Any] = {
        "radar_snapshots_in_window": 0,
        "radar_best_rank": None,
        "radar_blockers": [],
        "pattern_hits": 0,
        "pattern_best_grade": None,
        "x_observations": 0,
    }
    rejection_reasons: list[str] = []

    if move_start is None:
        return {"stages": stages, "evidence": evidence, "rejection_reasons": ["move_missing_window_start"]}

    # Radar.
    relevant_snaps = [
        s for s in radar_snaps
        if _in_window(_radar_snapshot_time(s), move_start, LEAD_WINDOW_MINUTES, POST_WINDOW_MINUTES)
    ]
    evidence["radar_snapshots_in_window"] = len(relevant_snaps)
    if relevant_snaps:
        stages["radar_snapshot_present"] = True

    best_rank: int | None = None
    for snap in relevant_snaps:
        ranked, filtered = _spy_candidates(snap)
        if ranked or filtered:
            stages["radar_saw_spy"] = True
        rank = _radar_rank(snap)
        if rank is not None and (best_rank is None or rank < best_rank):
            best_rank = rank
        for cand in (ranked + filtered):
            blockers = cand.get("blockers") or []
            if isinstance(blockers, list):
                for b in blockers:
                    if b and b not in evidence["radar_blockers"]:
                        evidence["radar_blockers"].append(b)
    if best_rank is not None:
        evidence["radar_best_rank"] = best_rank
        if best_rank <= RANK_TOP_N:
            stages["radar_ranked_topN"] = True

    # Pattern grader.
    pat_hits = [
        r for r in pattern_rows
        if _in_window(_parse_iso(r.get("observed_at") or r.get("bar_close_ts")), move_start, LEAD_WINDOW_MINUTES, POST_WINDOW_MINUTES)
        and _dir_match(move_dir, r.get("direction"))
    ]
    evidence["pattern_hits"] = len(pat_hits)
    if pat_hits:
        stages["pattern_grader_hit"] = True
        grade_order = ["A+", "A", "A-", "B+", "B", "B-", "C+", "C", "C-", "D", "F"]

        def grade_key(row: dict[str, Any]) -> int:
            g = str(row.get("grade") or row.get("pattern_grade") or "").upper()
            return grade_order.index(g) if g in grade_order else len(grade_order)

        best = sorted(pat_hits, key=grade_key)[0]
        best_grade = str(best.get("grade") or best.get("pattern_grade") or "").upper()
        evidence["pattern_best_grade"] = best_grade or None
        blockers = best.get("blockers") or []
        blockers = blockers if isinstance(blockers, list) else []
        if best_grade in CONFIRMED_GRADES and not blockers:
            stages["setup_confirmed"] = True
        elif blockers:
            for b in blockers:
                reason = f"pattern_blocker:{b}"
                if reason not in rejection_reasons:
                    rejection_reasons.append(reason)
        elif best_grade and best_grade not in CONFIRMED_GRADES:
            rejection_reasons.append(f"pattern_grade_below_B:{best_grade}")
    else:
        rejection_reasons.append("no_pattern_grader_hit")

    if not stages["radar_saw_spy"]:
        rejection_reasons.append("radar_missed_spy")
    elif not stages["radar_ranked_topN"]:
        rejection_reasons.append(f"radar_rank_below_top{RANK_TOP_N}")

    # Contract feasibility sidecar.
    cf = contract_feasibility.get(move.get("move_id") or "")
    if cf is not None:
        stages["contract_feasible"] = bool(cf.get("feasible"))
        if not cf.get("feasible"):
            reason = cf.get("reason")
            if reason:
                rejection_reasons.append(f"contract:{reason}")

    # X intake.
    x_hits = [
        r for r in x_rows
        if _in_window(_parse_iso(r.get("observed_at")), move_start, LEAD_WINDOW_MINUTES, POST_WINDOW_MINUTES)
    ]
    evidence["x_observations"] = len(x_hits)
    if x_hits:
        stages["x_intake_hit"] = True

    return {"stages": stages, "evidence": evidence, "rejection_reasons": rejection_reasons}


def _resolve_dates(explicit_date: str | None, days: int) -> set[str]:
    ledger_rows = _load_jsonl(LEDGER_PATH)
    all_dates = sorted({str(r.get("date")) for r in ledger_rows if r.get("date")}, reverse=True)
    if explicit_date:
        return {explicit_date}
    if days > 0:
        return set(all_dates[:days])
    today = datetime.now(MARKET_TZ).date().isoformat()
    return {today}


def build_report(explicit_date: str | None, days: int) -> dict[str, Any]:
    target_dates = _resolve_dates(explicit_date, days)
    moves = _load_ledger(target_dates)
    radar_snaps = _load_radar_relevant(target_dates)
    pattern_rows = _load_pattern_relevant(target_dates)
    x_rows = _load_x_relevant(target_dates)
    contract_feas = _load_contract_feasibility(target_dates)

    per_move: list[dict[str, Any]] = []
    for move in moves:
        result = evaluate_move(move, radar_snaps, pattern_rows, x_rows, contract_feas)
        per_move.append({
            "move_id": move.get("move_id"),
            "date": move.get("date"),
            "direction": move.get("direction"),
            "trigger_timeframe": move.get("trigger_timeframe"),
            "magnitude_pct": move.get("magnitude_pct"),
            "r_multiple": move.get("r_multiple"),
            "window_start_et": move.get("window_start_et"),
            "stages": result["stages"],
            "evidence": result["evidence"],
            "rejection_reasons": result["rejection_reasons"],
        })

    stage_names = [
        "market_move",
        "radar_snapshot_present",
        "radar_saw_spy",
        "radar_ranked_topN",
        "pattern_grader_hit",
        "setup_confirmed",
        "contract_feasible",
        "x_intake_hit",
    ]
    total = len(per_move)
    stage_counts = {name: 0 for name in stage_names}
    for row in per_move:
        for name in stage_names:
            val = row["stages"].get(name)
            if val is True:
                stage_counts[name] += 1
    stage_recall_pct = {
        name: (round(100.0 * count / total, 2) if total else 0.0)
        for name, count in stage_counts.items()
    }
    by_direction = {
        "up": sum(1 for r in per_move if r["direction"] == "up"),
        "down": sum(1 for r in per_move if r["direction"] == "down"),
    }

    worst_misses = sorted(
        [r for r in per_move if not r["stages"].get("setup_confirmed")],
        key=lambda r: (r.get("magnitude_pct") or 0.0),
        reverse=True,
    )[:10]

    report = {
        "generated_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "spec_version": SPEC_VERSION,
        "provider": "spy_recall_report",
        "mode": "context_only",
        "execution_enabled": False,
        "dates_covered": sorted(target_dates),
        "lead_window_minutes": LEAD_WINDOW_MINUTES,
        "post_window_minutes": POST_WINDOW_MINUTES,
        "rank_top_n": RANK_TOP_N,
        "confirmed_grades": sorted(CONFIRMED_GRADES),
        "total_moves": total,
        "by_direction": by_direction,
        "stage_counts": stage_counts,
        "stage_recall_pct": stage_recall_pct,
        "worst_misses": worst_misses,
        "per_move": per_move,
        "inputs": {
            "ledger_path": str(LEDGER_PATH),
            "radar_log": str(RADAR_LOG),
            "pattern_log": str(PATTERN_LOG),
            "contract_feasibility_sidecar": str(CONTRACT_FEASIBILITY_SIDECAR),
            "x_observations_path": str(X_OBSERVATIONS_PATH),
        },
    }
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(json.dumps(report, indent=2), encoding="utf-8")
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--date", help="ET session date YYYY-MM-DD.")
    parser.add_argument("--days", type=int, default=1, help="Report over last N session dates present in the ledger (ignored if --date given).")
    parser.add_argument("--print-misses", action="store_true", help="Print worst-miss table to stdout.")
    args = parser.parse_args()

    report = build_report(args.date, args.days)
    summary = {
        "dates_covered": report["dates_covered"],
        "total_moves": report["total_moves"],
        "by_direction": report["by_direction"],
        "stage_recall_pct": report["stage_recall_pct"],
        "report_path": str(REPORT_PATH),
    }
    print(json.dumps(summary, indent=2))
    if args.print_misses and report["worst_misses"]:
        print("\nWorst misses (not confirmed):")
        for m in report["worst_misses"]:
            print(f"  {m['date']} {m['direction']:<4} mag={m['magnitude_pct']}%  reasons={m['rejection_reasons']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

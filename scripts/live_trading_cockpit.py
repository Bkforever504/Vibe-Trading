#!/usr/bin/env python3
"""Normalize existing trading artifacts for the read-only live cockpit.

The cockpit is a decision-support surface. It does not call brokers, change bot
configuration, promote strategies, or submit orders. Source scores remain
source scores; ``routing_priority`` only determines display order.
"""
from __future__ import annotations

import json
import hashlib
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from scripts.dashboard_readiness import build_readiness


VIBE_HOME = Path.home() / ".vibe-trading"
REPORT_DIR = VIBE_HOME / "reports"

REPORT_FILES: dict[str, str] = {
    "bot_status": "bot-status-snapshot.json",
    "daily_edge": "daily-edge-orchestrator.json",
    "stock_screener": "daily-stock-screener.json",
    "options_universe": "daily-options-universe-ranker.json",
    "trade_signals": "trade-signal-generator.json",
    "premarket_radar": "premarket-opportunity-radar.json",
    "intraday_radar": "intraday-opportunity-radar.json",
    "detection_scorecard": "detection-scorecard-rolling.json",
    "cisd_promotion": "cisd-promotion-status.json",
    "pattern_grades": "pattern-grader-grades.json",
    "grade_calibration": "grade-probability-calibration.json",
    "live_opportunities": "live-opportunity-engine.json",
    "sec_catalysts": "sec-catalyst-feed.json",
    "simple_price_action": "simple-price-action-alerts.json",
    "move_coverage": "daily-move-coverage-review.json",
    "bottom_reversals": "bottom-reversal-investigator.json",
    "bottom_evidence": "bottom-reversal-forward-evidence.json",
    "market_force": "market-force-score.json",
    "market_breadth": "market-breadth-uptrend.json",
    "sector_rotation": "sector-rotation-rank.json",
    "higher_timeframe": "higher-timeframe-market-map.json",
    "candlestick_context": "candlestick-context.json",
    "kronos": "kronos-market-forecast.json",
    "garch_risk": "garch-volatility-risk.json",
    "catalysts": "market-catalyst-calendar.json",
    "daily_eod": "daily-eod-summary.json",
    "daily_outcome": "daily-outcome-review.json",
    "aplus_review": "daily-aplus-review.json",
    "closed_postmortem": "closed-trade-postmortem.json",
    "missed_banger": "flip-decision-missed-banger-review.json",
    "rejected_intel": "rejected-trade-intelligence.json",
    "lesson_ledger": "trade-lesson-ledger.json",
    "needs_review": "needs-review-queue.json",
    "verified_trader": "verified-trader-evidence.json",
    "public_intake": "public-social-intake.json",
    "trending_symbols": "social-trending-symbols.json",
    "signal_health": "signal-stack-health.json",
    "execution_audit": "execution-gate-audit.json",
    "paper_readiness": "flip-paper-operations-readiness.json",
    "live_readiness": "flip-live-readiness.json",
    "position_reconciliation": "options-position-reconciliation.json",
    "portfolio_risk": "portfolio-concentration.json",
    "quant_risk": "options-quant-risk-budget.json",
    "options_liquidity": "options-liquidity-feasibility.json",
    "options_surface": "options-surface-intelligence.json",
    "options_heatmap": "options-liquidation-heatmap.json",
    "options_feed_qualification": "options-feed-qualification.json",
    "move_ground_truth": "move-ground-truth-summary.json",
    "manual_execution_quality": "manual-execution-quality.json",
    "broker_fill_observer": "broker-fill-observer.json",
    "options_playbook": "adaptive-options-shadow-playbook.json",
    "premium_levels": "option-premium-levels.json",
    "vol_premium": "options-vol-premium.json",
    "shadow_consensus": "shadow-consensus-gate.json",
    "shadow_audit": "shadow-logger-audit.json",
    "daily_plan": "daily-trade-plan.json",
}

ROOT = Path(__file__).resolve().parents[1]
MES_HOLDOUT_FILE = ROOT / "data" / "mes_reopen_vix_holdout.json"
FAILURE_TAXONOMY_FILE = ROOT / "data" / "failure-taxonomy.json"
RECONCILIATION_EVENTS_FILE = ROOT / "data" / "reconciliation_events.jsonl"
BROKER_RECONCILIATION_REPORT = "broker-reconciliation.json"


def _load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def _load_jsonl(path: Path) -> list[dict[str, Any]]:
    try:
        lines = path.read_text(encoding="utf-8-sig").splitlines()
    except OSError:
        return []
    rows: list[dict[str, Any]] = []
    for line in lines:
        try:
            value = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            rows.append(value)
    return rows


def _failure_taxonomy_week(report: dict[str, Any], now: datetime) -> dict[str, int]:
    cutoff = now - timedelta(days=7)
    counts: dict[str, int] = {}
    for row in _list(report.get("records")):
        item = _dict(row)
        stamp = _parse_time(item.get("date") or item.get("timestamp") or item.get("closed_at"))
        if stamp is None or stamp < cutoff:
            continue
        category = _text(item.get("category") or "UNKNOWN_LOSS")
        counts[category] = counts.get(category, 0) + 1
    return dict(sorted(counts.items()))


def _reconciliation_status(
    report: dict[str, Any], events: list[dict[str, Any]], now: datetime
) -> dict[str, Any]:
    cutoff = now - timedelta(hours=24)
    recent = []
    for row in events:
        stamp = _parse_time(row.get("run_at") or row.get("generated_at"))
        if stamp is not None and stamp >= cutoff:
            recent.append((stamp, row))
    report_time = _parse_time(report.get("run_at") or report.get("generated_at"))
    if report_time is not None and not recent:
        recent.append((report_time, report))
    recent.sort(key=lambda item: item[0])
    diff_rows = [(stamp, row) for stamp, row in recent if int(_number(row.get("diff_count")) or 0) > 0]
    return {
        "last_run_at": recent[-1][0].isoformat() if recent else None,
        "diff_count_24h": sum(int(_number(row.get("diff_count")) or 0) for _, row in recent),
        "last_diff_at": diff_rows[-1][0].isoformat() if diff_rows else None,
        "status": report.get("status") or (recent[-1][1].get("status") if recent else "unavailable"),
    }


def _number(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if number == number and abs(number) != float("inf") else None


def _text(value: Any, default: str = "") -> str:
    return str(value) if value not in (None, "") else default


def _list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _clamp(value: Any, low: float = 0.0, high: float = 100.0) -> float:
    number = _number(value)
    return round(min(max(number if number is not None else low, low), high), 1)


def _grade(score: Any) -> str:
    value = _clamp(score)
    if value >= 93:
        return "A+"
    if value >= 87:
        return "A"
    if value >= 80:
        return "A-"
    if value >= 73:
        return "B+"
    if value >= 67:
        return "B"
    if value >= 60:
        return "B-"
    if value >= 50:
        return "C"
    return "D"


def _direction_family(value: Any) -> str:
    direction = _text(value).lower()
    if direction in {"bull", "bullish", "long", "call"}:
        return "bullish"
    if direction in {"bear", "bearish", "short", "put"}:
        return "bearish"
    return "neutral"


def _decision_state(
    row: dict[str, Any],
    *,
    current_price: float | None,
    contract_ready: bool,
) -> dict[str, Any]:
    """Separate a good setup from a timely, executable shadow decision."""
    direction = _direction_family(row.get("direction"))
    entry = _number(row.get("entry"))
    stop = _number(row.get("stop"))
    target = _number(row.get("target"))
    levels_complete = entry is not None and stop is not None and target is not None
    geometry_valid = bool(
        levels_complete
        and (
            (direction == "bullish" and stop < entry < target)
            or (direction == "bearish" and stop > entry > target)
        )
    )

    confirmation = _dict(_dict(row.get("evidence")).get("price_action_confirmation"))
    confirmation_state = _text(confirmation.get("state")).lower()
    confirmed = "confirmed" in confirmation_state
    waiting = confirmation_state in {"waiting", "wait", "pending"}
    if row.get("paper_consumable"):
        confirmed = True
        waiting = False

    invalid = False
    move_consumed_pct: float | None = None
    reward_remaining_r: float | None = None
    if geometry_valid and current_price is not None:
        if direction == "bullish":
            invalid = current_price <= stop
            move_consumed_pct = 100.0 * (current_price - entry) / (target - entry)
            live_risk = current_price - stop
            reward_remaining_r = (target - current_price) / live_risk if live_risk > 0 else None
        elif direction == "bearish":
            invalid = current_price >= stop
            move_consumed_pct = 100.0 * (entry - current_price) / (entry - target)
            live_risk = stop - current_price
            reward_remaining_r = (current_price - target) / live_risk if live_risk > 0 else None
        move_consumed_pct = round(min(max(move_consumed_pct, 0.0), 200.0), 1)
        if reward_remaining_r is not None:
            reward_remaining_r = round(reward_remaining_r, 2)

    too_late = bool(
        geometry_valid
        and current_price is not None
        and not invalid
        and (
            (move_consumed_pct is not None and move_consumed_pct >= 50.0)
            or (reward_remaining_r is not None and reward_remaining_r < 1.25)
        )
    )
    if invalid:
        lifecycle = "invalid"
        actionability = "invalid"
        next_action = "Discard the setup. Price crossed the mechanical invalidation."
        timing_score = 0.0
    elif too_late:
        lifecycle = "too_late"
        actionability = "late_no_chase"
        next_action = "Do not chase. Log the move and wait for a new base, pullback, or setup."
        timing_score = 20.0
    elif confirmed and geometry_valid:
        lifecycle = "confirmed"
        actionability = "shadow_ready"
        next_action = "Shadow now only after a fresh quote confirms the trigger, spread, and stop."
        timing_score = 92.0
    elif (waiting or row.get("lane") in {"armed", "precision_watch", "event_watch"}) and geometry_valid:
        lifecycle = "armed"
        actionability = "wait"
        next_action = "Wait for a completed bar to confirm the trigger; do not anticipate it."
        timing_score = 74.0
    else:
        lifecycle = "research_only"
        actionability = "research_only"
        next_action = "Research candidate only. A complete trigger, stop, and target are not ready."
        timing_score = 35.0 if levels_complete else 20.0

    if geometry_valid:
        execution_score = 88.0
    elif levels_complete:
        execution_score = 20.0
    else:
        execution_score = 25.0
    instrument_status = "underlying_ready"
    if row.get("asset_class") in {"option", "equity_option", "equity_or_option"}:
        if contract_ready:
            instrument_status = "contract_ready"
        else:
            instrument_status = "underlying_ready_contract_pending"
            execution_score = min(execution_score, 58.0)
    elif row.get("asset_class") == "future" and entry is None:
        instrument_status = "scheduled_rule_only"
        execution_score = min(execution_score, 45.0)

    return {
        "lifecycle": lifecycle,
        "actionability": actionability,
        "next_action": next_action,
        "timing_score": timing_score,
        "execution_score": execution_score,
        "instrument_status": instrument_status,
        "levels_complete": levels_complete,
        "geometry_valid": geometry_valid,
        "current_price": current_price,
        "move_consumed_pct": move_consumed_pct,
        "reward_remaining_r": reward_remaining_r,
        "confirmation_state": confirmation_state or None,
    }


def _factor(score: Any, reason: str, *, available: bool = True) -> dict[str, Any]:
    value = _clamp(score) if available else None
    return {
        "score": value,
        "grade": _grade(value) if value is not None else "--",
        "available": available,
        "reason": reason,
    }


def _occ_contract(value: Any, now: datetime) -> dict[str, Any] | None:
    raw = _text(value).upper()
    match = re.fullmatch(r"([A-Z]{1,6})(\d{6})([CP])(\d{8})", raw)
    if not match:
        return None
    expiry_raw = match.group(2)
    try:
        expiry = datetime.strptime(expiry_raw, "%y%m%d").date()
    except ValueError:
        return None
    return {
        "symbol": raw,
        "underlying": match.group(1),
        "expiry": expiry.isoformat(),
        "right": "call" if match.group(3) == "C" else "put",
        "strike": int(match.group(4)) / 1000.0,
        "expired": expiry < now.date(),
    }


def _plan_id(row: dict[str, Any]) -> str:
    """Return a source-event-stable plan identity, independent of display day."""
    evidence = _dict(row.get("evidence"))
    confirmation = _dict(evidence.get("price_action_confirmation"))
    identity = {
        "symbol": _text(row.get("symbol")),
        "asset_class": _text(row.get("asset_class")),
        "source": _text(row.get("source")),
        "setup": _text(row.get("setup")),
        "direction": _text(row.get("direction")),
        "producer_id": _text(
            evidence.get("detection_id")
            or evidence.get("candidate_id")
            or evidence.get("signal_id")
            or row.get("candidate_id")
        ),
        "trigger_bar_ts": _text(
            row.get("generated_at")
            or evidence.get("bar_completed_at")
            or confirmation.get("bar_completed_at")
            or evidence.get("trigger_bar_ts")
            or evidence.get("generated_at")
        ),
        "entry": _number(row.get("entry")),
        "stop": _number(row.get("stop")),
        "target": _number(row.get("target")),
    }
    raw = json.dumps(identity, sort_keys=True, separators=(",", ":"))
    return "plan-" + hashlib.sha256(raw.encode("utf-8")).hexdigest()[:20]


def _parse_time(value: Any) -> datetime | None:
    if not value:
        return None
    raw = str(value).strip().replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(raw)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _source_time(report: dict[str, Any], path: Path) -> datetime | None:
    for key in ("generated_at", "timestamp", "as_of_et", "data_cutoff", "date"):
        parsed = _parse_time(report.get(key))
        if parsed is not None:
            return parsed
    try:
        return datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)
    except OSError:
        return None


def _freshness(age_seconds: float | None) -> str:
    if age_seconds is None:
        return "missing"
    if age_seconds <= 15 * 60:
        return "live"
    if age_seconds <= 6 * 60 * 60:
        return "recent"
    if age_seconds <= 36 * 60 * 60:
        return "prior_session"
    return "stale"


def _source_inventory(
    reports: dict[str, dict[str, Any]],
    report_dir: Path,
    now: datetime,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for name, filename in REPORT_FILES.items():
        path = report_dir / filename
        report = reports.get(name, {})
        generated = _source_time(report, path) if report else None
        explicit_generated = next(
            (
                parsed
                for key in ("generated_at", "timestamp", "as_of_et", "data_cutoff", "date")
                if (parsed := _parse_time(report.get(key))) is not None
            ),
            None,
        )
        raw_age = (now - generated).total_seconds() if generated else None
        clock_skew = (
            max(0.0, -(now - explicit_generated).total_seconds())
            if explicit_generated is not None and (now - explicit_generated).total_seconds() < -300
            else 0.0
        )
        age = max(0.0, raw_age) if raw_age is not None else None
        report_hash = (
            "sha256:" + hashlib.sha256(json.dumps(report, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")).hexdigest()
            if report
            else None
        )
        rows.append(
            {
                "name": name,
                "filename": filename,
                "path": str(path),
                "line_reference": 1 if report else None,
                "report_hash": report_hash,
                "spec_hash": report.get("spec_hash"),
                "available": bool(report),
                "generated_at": generated.isoformat() if generated else None,
                "age_seconds": round(age, 1) if age is not None else None,
                "freshness": "clock_skew" if clock_skew else _freshness(age),
                "clock_skew_seconds": round(clock_skew, 1),
                "provider": report.get("provider"),
                "mode": report.get("mode"),
                "execution_enabled": False,
                "can_submit_orders": False,
            }
        )
    return rows


def _quarantined_sources(sources: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Expose fail-closed source quarantine without changing any upstream report."""
    return [
        {
            "name": str(row.get("name") or "unknown"),
            "freshness": str(row.get("freshness") or "missing"),
            "reason": (
                "source_missing"
                if not row.get("available")
                else "source_timestamp_in_future"
                if row.get("freshness") == "clock_skew"
                else "source_older_than_24h"
            ),
            "source_label": str(row.get("filename") or row.get("path") or row.get("name") or "unknown"),
            "execution_enabled": False,
            "can_submit_orders": False,
        }
        for row in sources
        if not row.get("available")
        or not isinstance(row.get("age_seconds"), (int, float))
        or float(row["age_seconds"]) > 24 * 60 * 60
        or row.get("freshness") == "clock_skew"
    ]


def _source_surface(
    name: str,
    reports: dict[str, dict[str, Any]],
    sources_by_name: dict[str, dict[str, Any]],
    *,
    require_provenance: bool = False,
) -> dict[str, Any]:
    report = reports.get(name, {})
    source = sources_by_name.get(name, {})
    provenance_qualified = bool(report) and (
        not require_provenance or bool(report.get("provider") and report.get("mode"))
    )
    safe_data = (
        {**report, "execution_enabled": False, "can_submit_orders": False}
        if provenance_qualified
        else {}
    )
    return {
        "source": name,
        "filename": source.get("filename"),
        "path": source.get("path"),
        "line_reference": source.get("line_reference"),
        "report_hash": source.get("report_hash"),
        "spec_hash": source.get("spec_hash"),
        "provider": source.get("provider"),
        "mode": source.get("mode"),
        "generated_at": source.get("generated_at"),
        "age_seconds": source.get("age_seconds"),
        "freshness": source.get("freshness", "missing"),
        "available": bool(report),
        "provenance_qualified": provenance_qualified,
        "data": safe_data,
        "execution_enabled": False,
        "can_submit_orders": False,
    }


def _research_governance(report_dir: Path, now: datetime) -> dict[str, Any]:
    data_dir = ROOT / "data" if report_dir.resolve() == REPORT_DIR.resolve() else report_dir
    family_path = data_dir / "experiment_family.jsonl"
    hypothesis_path = data_dir / "hypothesis_ledger.jsonl"
    family_rows = _load_jsonl(family_path)
    hypotheses = _load_jsonl(hypothesis_path)
    week = now.isocalendar()[:2]

    def same_week(value: Any) -> bool:
        parsed = _parse_time(value)
        return parsed is not None and parsed.isocalendar()[:2] == week

    hashes = {str(row.get("spec_hash")) for row in family_rows if row.get("spec_hash")}
    tested = {
        str(row.get("candidate_id"))
        for row in family_rows
        if row.get("candidate_id") and same_week(row.get("recorded_at"))
    }
    rejected = {
        str(row.get("id"))
        for row in hypotheses
        if row.get("id") and row.get("status") == "rejected" and same_week(row.get("event_at"))
    }
    family_size = len(hashes)
    return {
        "tested_this_week": len(tested),
        "rejected_this_week": len(rejected),
        "bonferroni_denominator": family_size,
        "effective_alpha": round(0.05 / family_size, 8) if family_size else None,
        "status": "active_family" if family_size else "no_frozen_candidates",
        "provenance": [
            {"path": str(family_path), "line_reference": 1 if family_rows else None},
            {"path": str(hypothesis_path), "line_reference": 1 if hypotheses else None},
        ],
        "execution_enabled": False,
        "can_submit_orders": False,
    }


def _evidence_group(
    names: tuple[str, ...],
    reports: dict[str, dict[str, Any]],
    sources_by_name: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    return {
        **{name: _source_surface(name, reports, sources_by_name) for name in names},
        "execution_enabled": False,
        "can_submit_orders": False,
    }


def _catalysts_today(
    report: dict[str, Any],
    source: dict[str, Any],
    *,
    now: datetime,
) -> dict[str, Any]:
    market_today = now.astimezone(ZoneInfo("America/New_York")).date()
    allowed_dates = {market_today.isoformat(), (market_today + timedelta(days=1)).isoformat()}
    candidates = [_dict(report.get("today")), *[_dict(row) for row in _list(report.get("upcoming"))]]
    days = []
    seen: set[str] = set()
    for row in candidates:
        day = _text(row.get("date"))
        if day not in allowed_dates or day in seen:
            continue
        seen.add(day)
        days.append({**row, "execution_enabled": False, "can_submit_orders": False})
    days.sort(key=lambda row: _text(row.get("date")))
    return {
        "source": "catalysts",
        "provider": source.get("provider"),
        "mode": source.get("mode"),
        "generated_at": source.get("generated_at"),
        "age_seconds": source.get("age_seconds"),
        "freshness": source.get("freshness", "missing"),
        "days": days,
        "execution_enabled": False,
        "can_submit_orders": False,
    }


def _options_context(
    reports: dict[str, dict[str, Any]],
    sources_by_name: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    surfaces = {
        "surface": _source_surface(
            "options_surface", reports, sources_by_name, require_provenance=True
        ),
        "heatmap": _source_surface(
            "options_heatmap", reports, sources_by_name, require_provenance=True
        ),
        "vol_premium": _source_surface(
            "vol_premium", reports, sources_by_name, require_provenance=True
        ),
        "feed_qualification": _source_surface(
            "options_feed_qualification", reports, sources_by_name, require_provenance=True
        ),
    }
    research_surfaces = [surfaces[key] for key in ("surface", "heatmap", "vol_premium")]
    qualified = [row for row in research_surfaces if row["provenance_qualified"]]
    if len(qualified) == len(research_surfaces):
        completeness = "complete"
    elif qualified:
        completeness = "partial"
    else:
        completeness = "unavailable"
    feed_report = reports.get("options_feed_qualification", {})
    feed_summary = _dict(feed_report.get("summary"))
    feed_source = sources_by_name.get("options_feed_qualification", {})
    feed_current = feed_source.get("freshness") in {"live", "prior_session"}
    manual_execution_reference_available = (
        feed_current and int(_number(feed_summary.get("manual_execution_qualified")) or 0) > 0
    )
    return {
        "status": "context_available" if qualified else "unavailable",
        "completeness": completeness,
        **surfaces,
        "manual_execution_reference_available": manual_execution_reference_available,
        "price_discovery_qualified_count": int(_number(feed_summary.get("price_discovery_qualified")) or 0),
        "reason": (
            "Research context is available and a current OPRA-qualified manual execution reference is present."
            if qualified and manual_execution_reference_available
            else "Research context is available, but no current OPRA-qualified manual execution reference is present."
            if qualified
            else "No provenance-qualified options context is available."
        ),
        "execution_enabled": False,
        "can_submit_orders": False,
    }


def _signal_candidate(row: dict[str, Any]) -> dict[str, Any]:
    targets = _list(row.get("targets"))
    first_target = _dict(targets[0]) if targets else {}
    blockers = [str(item) for item in _list(row.get("blockers"))]
    consumable = bool(row.get("paper_consumable")) and not blockers
    status = "ready" if consumable else _text(row.get("status"), "blocked")
    instrument = _text(row.get("instrument_preference"))
    if re.fullmatch(r"[A-Z]{1,6}\d{6}[CP]\d{8}", instrument.upper()):
        asset_class = "option"
    elif any(token in instrument.lower() for token in ("option", "spread", "call", "put")):
        asset_class = "equity_or_option"
    else:
        asset_class = "equity"
    return {
        "symbol": _text(row.get("symbol"), "UNKNOWN"),
        "asset_class": asset_class,
        "source": "trade_signals",
        "setup": _text(row.get("setup"), "mechanical_signal"),
        "direction": _text(row.get("direction"), "neutral"),
        "status": status,
        "lane": "paper_ready" if consumable else "blocked",
        "source_score": None,
        "routing_priority": 100.0 if consumable else 35.0,
        "paper_consumable": consumable,
        "entry": _number(row.get("entry")),
        "stop": _number(row.get("stop")),
        "target": _number(first_target.get("price")),
        "reward_risk": _number(row.get("reward_risk")),
        "instrument": instrument,
        "order_style": _text(row.get("order_style")),
        "blockers": blockers,
        "reasons": [],
        "evidence": _dict(row.get("source_candidate")),
        "generated_at": row.get("generated_at"),
    }


def _bottom_candidate(row: dict[str, Any]) -> dict[str, Any]:
    plan = _dict(row.get("next_session_plan"))
    blockers = [str(item) for item in _list(row.get("blockers"))]
    consumable = bool(row.get("paper_consumable")) and not blockers
    armed = plan.get("status") == "armed"
    priority = 90.0 if consumable else 72.0 if armed else 52.0
    return {
        "symbol": _text(row.get("symbol"), "UNKNOWN"),
        "asset_class": "equity",
        "source": "bottom_reversals",
        "setup": "capitulation_demand_confirmation",
        "direction": "bullish",
        "status": "ready" if consumable else _text(row.get("stage"), "watch"),
        "lane": "paper_ready" if consumable else "armed" if armed else "watch",
        "source_score": None,
        "routing_priority": priority,
        "paper_consumable": consumable,
        "entry": _number(plan.get("entry_trigger")),
        "stop": _number(plan.get("invalidation")),
        "target": _number(plan.get("target_2r")),
        "reward_risk": 2.0 if plan.get("target_2r") is not None else None,
        "instrument": "shares_or_defined_risk_debit_spread",
        "order_style": _text(plan.get("order_style")),
        "blockers": blockers,
        "reasons": [
            f"drawdown_63d={row.get('drawdown_from_63d_high_pct')}%",
            f"rsi2={row.get('rsi2')}",
            f"volume_ratio={row.get('volume_ratio')}",
        ],
        "evidence": {
            "drawdown_from_63d_high_pct": row.get("drawdown_from_63d_high_pct"),
            "rsi2": row.get("rsi2"),
            "volume_ratio": row.get("volume_ratio"),
            "relative_strength_vs_spy_1d_pct": row.get("relative_strength_vs_spy_1d_pct"),
        },
        "generated_at": None,
    }


def _edge_candidate(row: dict[str, Any]) -> dict[str, Any]:
    blockers = [str(item) for item in _list(row.get("blockers"))]
    lane = _text(row.get("lane"), "watch")
    score = _number(row.get("score"))
    lane_base = {"paper_ready": 82.0, "precision_watch": 66.0, "watchlist": 58.0,
                 "avoid_or_wait": 38.0, "blocked": 20.0}.get(lane, 45.0)
    priority = lane_base + min(max(score or 0.0, 0.0), 10.0)
    return {
        "symbol": _text(row.get("symbol"), "UNKNOWN"),
        "asset_class": "option",
        "source": "daily_edge",
        "setup": ", ".join(_list(row.get("allowed_playbooks"))) or "stand_aside",
        "direction": "mixed",
        "status": lane,
        "lane": lane,
        "source_score": score,
        "routing_priority": round(priority, 2),
        "paper_consumable": lane == "paper_ready" and not blockers,
        "entry": None,
        "stop": None,
        "target": None,
        "reward_risk": None,
        "instrument": _text(row.get("option_symbol")),
        "order_style": "revalidate_at_entry",
        "blockers": blockers,
        "reasons": [str(item) for item in _list(row.get("reasons"))],
        "evidence": _dict(row.get("kronos_forecast")),
        "generated_at": None,
    }


def _stock_candidate(row: dict[str, Any]) -> dict[str, Any]:
    blockers = [str(item) for item in _list(row.get("blockers"))]
    eligible = bool(row.get("long_eligible") or row.get("short_eligible")) and not blockers
    score = _number(row.get("score"))
    return {
        "symbol": _text(row.get("symbol"), "UNKNOWN"),
        "asset_class": "equity",
        "source": "stock_screener",
        "setup": "trend_relative_strength_liquidity",
        "direction": _text(row.get("direction"), "neutral"),
        "status": _text(row.get("status"), "watch"),
        "lane": "qualified_scan" if eligible else "watch",
        "source_score": score,
        "routing_priority": round(45.0 + min(max(score or 0.0, 0.0), 100.0) * 0.2, 2),
        "paper_consumable": False,
        "entry": None,
        "stop": None,
        "target": None,
        "reward_risk": None,
        "instrument": "shares_or_liquid_defined_risk_option",
        "order_style": "wait_for_strategy_trigger",
        "blockers": blockers + ["strategy_trigger_not_present"],
        "reasons": [
            f"rs_vs_spy_20d={row.get('relative_strength_vs_spy_20d_pct')}%",
            f"avg_dollar_volume_20d={row.get('avg_dollar_volume_20d', row.get('average_dollar_volume_20d'))}",
        ],
        "evidence": {
            "price": row.get("price"),
            "return_20d_pct": row.get("return_20d_pct"),
            "relative_strength_vs_spy_20d_pct": row.get("relative_strength_vs_spy_20d_pct"),
            "average_dollar_volume_20d": row.get("avg_dollar_volume_20d", row.get("average_dollar_volume_20d")),
            "atr14_pct": row.get("atr14_pct"),
            "relative_volume_completed_day": row.get("relative_volume_completed_day"),
            "rsi14": row.get("rsi14"),
        },
        "generated_at": None,
    }


def _radar_candidate(row: dict[str, Any]) -> dict[str, Any]:
    premarket = _dict(row.get("premarket"))
    gates = _dict(row.get("hard_gates"))
    failed = [key for key, passed in gates.items() if not bool(passed)]
    ready = bool(row.get("paper_signal_eligible")) and not failed
    direction = _text(row.get("direction"), "neutral")
    high = _number(premarket.get("premarket_high"))
    low = _number(premarket.get("premarket_low"))
    has_range = high is not None and low is not None and high > low
    entry = high if ready and direction in {"bull", "bullish", "long"} and has_range else low if ready and has_range else None
    stop = low if entry is not None and direction in {"bull", "bullish", "long"} else high if entry is not None else None
    risk = abs(entry - stop) if entry is not None and stop is not None else None
    target = entry + 2 * risk if risk and direction in {"bull", "bullish", "long"} else entry - 2 * risk if risk else None
    headlines = [_dict(item).get("headline") for item in _list(row.get("catalyst_headlines"))]
    blockers = failed[:]
    if not has_range:
        blockers.append("completed_premarket_range_not_available")
    if not ready:
        blockers.append("price_volume_confirmation_not_complete")
    return {
        "symbol": _text(row.get("symbol"), "UNKNOWN"),
        "asset_class": "equity",
        "source": "premarket_radar",
        "setup": f"{_text(row.get('lane'), 'premarket')}_continuation",
        "direction": direction,
        "status": "ready" if ready and has_range else _text(row.get("state"), "watch"),
        "lane": "paper_ready" if ready and has_range else "event_watch",
        "source_score": _number(row.get("score")),
        "routing_priority": 92.0 if ready and has_range else 58.0 + min(_number(row.get("score")) or 0.0, 10.0),
        "paper_consumable": ready and has_range,
        "entry": entry,
        "stop": stop,
        "target": target,
        "reward_risk": 2.0 if target is not None else None,
        "instrument": "shares_or_defined_risk_debit_spread",
        "order_style": "stop_limit_after_completed_5m_confirmation" if ready else "wait_for_completed_price_volume_confirmation",
        "blockers": sorted(set(blockers)),
        "reasons": [
            f"gap={row.get('gap_pct')}%",
            f"premarket_rvol={row.get('premarket_rvol')}",
            f"sector={row.get('sector_etf')}",
            *[str(item) for item in headlines if item][:2],
        ],
        "evidence": row,
        "generated_at": row.get("latest_trade_at"),
    }


def _intraday_candidate(row: dict[str, Any]) -> dict[str, Any]:
    levels = _dict(row.get("trade_levels"))
    gates = _dict(row.get("hard_gates"))
    consensus = _dict(row.get("factor_consensus"))
    failed = [name for name, passed in gates.items() if not bool(passed)]
    headlines = [_dict(item).get("headline") for item in _list(row.get("catalyst_headlines"))]
    return {
        "symbol": _text(row.get("symbol"), "UNKNOWN"),
        "asset_class": "equity",
        "source": "intraday_radar",
        "setup": _text(row.get("setup"), "marketwide_discovery"),
        "direction": _text(row.get("direction"), "neutral"),
        "status": _text(row.get("state"), "watch"),
        "lane": _text(row.get("state"), "watch"),
        "source_score": _number(row.get("score")),
        "routing_priority": 88.0 if row.get("state") == "precision_watch" else 64.0,
        "paper_consumable": False,
        "entry": _number(levels.get("confirmation_trigger")),
        "stop": _number(levels.get("invalidation")),
        "target": _number(levels.get("target_2r")),
        "reward_risk": 2.0 if levels.get("target_2r") is not None else None,
        "instrument": "shares_or_liquid_defined_risk_option",
        "order_style": _text(levels.get("instruction"), "wait_for_completed_5m_confirmation"),
        "blockers": sorted(set(failed + [str(item) for item in _list(row.get("blockers"))])),
        "reasons": [
            f"change={row.get('change_pct')}%",
            f"volume_pace={row.get('volume_pace_rvol_proxy')}x",
            f"factor_consensus={consensus.get('grade', '--')} {consensus.get('score', '--')}",
            f"sources={','.join(str(item) for item in _list(row.get('discovery_sources')))}",
            *[str(item) for item in headlines if item][:1],
        ],
        "evidence": row,
        "generated_at": None,
    }


def _live_opportunity_candidate(row: dict[str, Any]) -> dict[str, Any]:
    targets = [_dict(item) for item in _list(row.get("targets"))]
    target = _number(targets[0].get("price")) if targets else None
    quote = _dict(row.get("quote"))
    evidence = {
        **row,
        "price": _number(quote.get("midpoint")) or _number(row.get("entry")),
        "price_action_confirmation": {
            "state": "confirmed" if row.get("state") == "READY_TO_REVIEW" else "waiting",
            "bar_completed_at": row.get("bar_completed_at"),
        },
        "catalyst_available": bool(row.get("catalyst")),
    }
    return {
        "symbol": _text(row.get("symbol"), "UNKNOWN"),
        "asset_class": "equity",
        "source": "live_opportunities",
        "setup": _text(row.get("setup_family"), "streaming_setup"),
        "direction": _text(row.get("direction"), "neutral"),
        "status": _text(row.get("state"), "WATCH"),
        "lane": "precision_watch" if row.get("state") == "READY_TO_REVIEW" else "watch",
        "source_score": _number(row.get("decision_score")),
        "routing_priority": 96.0 if row.get("state") == "READY_TO_REVIEW" else 72.0,
        "paper_consumable": False,
        "entry": _number(row.get("entry")),
        "stop": _number(row.get("invalidation")),
        "target": target,
        "reward_risk": _number(row.get("reward_risk_after_friction")),
        "instrument": "shares_or_liquid_defined_risk_option",
        "order_style": "manual_review_after_fresh_quote_and_completed_bar_revalidation",
        "blockers": sorted(set(str(item) for item in _list(row.get("blockers")))),
        "reasons": [
            _text(row.get("reason"), "streaming setup detector"),
            f"feed_sources={','.join(str(item) for item in _list(row.get('source_labels')))}",
            f"rvol={row.get('rvol_time_of_day')}",
            f"post_cost_rr={row.get('reward_risk_after_friction')}",
        ],
        "evidence": evidence,
        "generated_at": row.get("bar_completed_at"),
        "execution_enabled": False,
        "can_submit_orders": False,
    }


def _probability_contract(raw: Any) -> dict[str, Any]:
    source = _dict(raw)
    value = _number(source.get("value"))
    lower_bound = _number(source.get("lower_bound"))
    if value is not None and 0.0 <= value <= 1.0:
        value *= 100.0
    if lower_bound is not None and 0.0 <= lower_bound <= 1.0:
        lower_bound *= 100.0
    sample_size = int(_number(source.get("sample_size")) or 0)
    independent_dates = int(_number(source.get("independent_dates")) or 0)
    brier_skill = _number(source.get("brier_skill_vs_expanding_base_rate"))
    status = _text(source.get("status"), "not_calibrated")
    failures: list[str] = []
    if status not in {"calibrated_holdout", "local_forward_validated"}:
        failures.append("status_not_forward_calibrated")
    if value is None or not 0.0 <= value <= 100.0:
        failures.append("probability_value_unavailable")
    if lower_bound is None or not 0.0 <= lower_bound <= 100.0:
        failures.append("conservative_lower_bound_unavailable")
    if sample_size < 100:
        failures.append("fewer_than_100_samples")
    if independent_dates < 30:
        failures.append("fewer_than_30_independent_dates")
    if brier_skill is None or brier_skill <= 0.0:
        failures.append("no_positive_brier_skill_vs_expanding_base_rate")
    calibrated = not failures
    return {
        "value": round(value, 1) if value is not None else None,
        "lower_bound": round(lower_bound, 1) if lower_bound is not None else None,
        "status": "calibrated_conditional_probability" if calibrated else status,
        "label": "Locally forward-calibrated conditional probability" if calibrated else _text(source.get("label"), "No qualified calibrated probability"),
        "sample_size": sample_size or None,
        "independent_dates": independent_dates or None,
        "brier_skill_vs_expanding_base_rate": round(brier_skill, 4) if brier_skill is not None else None,
        "calibration_qualified": calibrated,
        "ranking_eligible": False,
        "qualification_failures": failures,
    }


def _apply_grade_calibration(
    row: dict[str, Any], calibration: dict[str, Any], *, regime: str
) -> dict[str, Any]:
    """Attach only the exact family/regime/grade calibration bucket.

    The probability contract remains the authority gate: a display-calibrated
    bucket may be shown on the Calibration page, but it cannot rank a trade.
    """
    family = _text(row.get("setup_family") or row.get("setup"))
    grade = _text(row.get("grade")).upper()[:1]
    normalized_regime = _text(regime, "unavailable")
    matches = [
        _dict(bucket)
        for bucket in _list(calibration.get("buckets"))
        if _text(_dict(bucket).get("setup_family")) == family
        and _text(_dict(bucket).get("grade")).upper()[:1] == grade
        and _text(_dict(bucket).get("regime")) in {normalized_regime, "all"}
    ]
    if not matches:
        return row
    matches.sort(key=lambda bucket: _text(bucket.get("regime")) != normalized_regime)
    bucket = matches[0]
    probability = _probability_contract(bucket.get("probability"))
    probability["ranking_eligible"] = (
        bool(probability.get("calibration_qualified"))
        and row.get("actionability") == "shadow_ready"
        and not _list(row.get("blockers"))
    )
    return {
        **row,
        "probability": probability,
        "probability_source": {
            "provider": calibration.get("provider"),
            "generated_at": calibration.get("generated_at"),
            "bucket_id": bucket.get("bucket_id"),
            "method": calibration.get("method"),
            "execution_enabled": False,
            "can_submit_orders": False,
        },
    }


def _quarantine_stale_candidate(
    row: dict[str, Any], sources_by_name: dict[str, dict[str, Any]]
) -> dict[str, Any]:
    source_map = {
        "trade_signal": "trade_signals",
        "trade_signals": "trade_signals",
        "bottom_reversal": "bottom_reversals",
        "daily_edge": "daily_edge",
        "stock_screener": "stock_screener",
        "premarket_radar": "premarket_radar",
        "intraday_radar": "intraday_radar",
        "live_opportunities": "live_opportunities",
    }
    source_name = source_map.get(_text(row.get("source")))
    if not source_name:
        return row
    source = sources_by_name.get(source_name, {})
    age = _number(source.get("age_seconds"))
    max_age_by_source = {
        "live_opportunities": 20 * 60,
        "trade_signals": 20 * 60,
        "intraday_radar": 30 * 60,
        "premarket_radar": 8 * 60 * 60,
        "stock_screener": 8 * 60 * 60,
        "daily_edge": 36 * 60 * 60,
        "bottom_reversals": 36 * 60 * 60,
    }
    max_age = max_age_by_source.get(source_name, 24 * 60 * 60)
    source_qualified = (
        source.get("available")
        and source.get("freshness") != "clock_skew"
        and age is not None
        and age <= max_age
    )
    if source_qualified:
        return row
    failure = (
        "source_timestamp_in_future"
        if source.get("freshness") == "clock_skew"
        else "source_exceeds_live_sla"
        if max_age <= 60 * 60
        else "source_exceeds_report_sla_or_missing"
    )
    failures = {failure, "source_older_than_24h_or_missing"}
    probability = {**_dict(row.get("probability")), "ranking_eligible": False}
    probability.setdefault("qualification_failures", [])
    probability["qualification_failures"] = sorted(
        {*_list(probability["qualification_failures"]), *failures}
    )
    return {
        **row,
        "paper_consumable": False,
        "blockers": sorted({*_list(row.get("blockers")), *failures}),
        "lifecycle": "research_only",
        "actionability": "research_only",
        "next_action": f"STAND_ASIDE until the source refreshes within its {int(max_age / 60)} minute SLA.",
        "decision_score": min(float(row.get("decision_score") or 0), 20.0),
        "probability": probability,
    }


def _mes_candidate(holdout: dict[str, Any]) -> dict[str, Any] | None:
    test = _dict(holdout.get("test_2025_2026"))
    rule = _dict(holdout.get("rule"))
    if not test or not rule:
        return None
    eligible = bool(holdout.get("practice_promotion_eligible"))
    return {
        "symbol": "MES",
        "asset_class": "future",
        "source": "mes_reopen_holdout",
        "setup": "overnight_reopen_drift_vix_filter",
        "direction": "long",
        "status": "practice_ready" if eligible else "shadow_validated",
        "lane": "practice_ready" if eligible else "research_edge",
        "source_score": None,
        "routing_priority": 78.0,
        "paper_consumable": False,
        "entry": None,
        "stop": None,
        "target": None,
        "reward_risk": None,
        "instrument": "front_month_MES_future",
        "order_style": "18:00_ET_entry;09:30_ET_time_exit",
        "blockers": [] if eligible else ["forward_shadow_gate_not_complete", "practice_promotion_not_approved"],
        "reasons": [
            f"VIX <= {rule.get('vix_cap')}",
            f"prior-day move >= {rule.get('prior_move_floor')}",
            f"holdout Sharpe={test.get('sharpe_annual')}",
            f"holdout PF={test.get('profit_factor')}",
        ],
        "evidence": holdout,
        "generated_at": None,
    }


def _enrich_candidate(
    row: dict[str, Any],
    *,
    now: datetime,
    market_force: dict[str, Any],
    liquidity_by_symbol: dict[str, dict[str, Any]],
    surface_by_symbol: dict[str, dict[str, Any]],
    radar_by_symbol: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    symbol = _text(row.get("symbol"), "UNKNOWN")
    evidence = _dict(row.get("evidence"))
    liquidity = liquidity_by_symbol.get(symbol, {})
    surface = surface_by_symbol.get(symbol, {})
    radar = radar_by_symbol.get(symbol, {})
    source_score = _number(row.get("source_score"))

    if row.get("source") == "stock_screener":
        setup_score = _clamp(source_score)
        avg_dollar = _number(evidence.get("average_dollar_volume_20d")) or 0.0
        liquidity_score = 90 if avg_dollar >= 1_000_000_000 else 78 if avg_dollar >= 100_000_000 else 55
        rs = _number(evidence.get("relative_strength_vs_spy_20d_pct"))
        trend_score = _clamp(50 + (rs or 0) * 4)
    elif row.get("source") == "premarket_radar":
        gates = _dict(evidence.get("hard_gates"))
        setup_score = _clamp(35 + 13 * sum(bool(value) for value in gates.values()))
        liquidity_score = 85 if gates.get("executable_underlying_spread") and gates.get("historical_dollar_liquidity") else 35
        trend_score = _clamp(50 + min(abs(_number(evidence.get("gap_pct")) or 0), 20) * 2)
    elif row.get("source") == "intraday_radar":
        direct = _dict(evidence.get("factor_scores"))
        consensus = _dict(evidence.get("factor_consensus"))
        setup_score = _number(evidence.get("score")) or 0.0
        liquidity_score = _number(direct.get("liquidity")) or 0.0
        trend_score = _number(direct.get("magnitude")) or 0.0
    elif row.get("source") == "live_opportunities":
        direct = _dict(evidence.get("factor_scores"))
        setup_score = _number(row.get("source_score")) or 0.0
        liquidity_score = _number(direct.get("liquidity")) or 0.0
        trend_score = _number(direct.get("relative_strength")) or 0.0
    elif row.get("source") == "mes_reopen_holdout":
        setup_score = 84
        liquidity_score = 82
        trend_score = 70
    else:
        setup_score = 92 if row.get("paper_consumable") else _clamp(45 + (source_score or 0) * 4)
        liquidity_score = _clamp((_number(liquidity.get("score")) or 0) * 20) if liquidity else 45
        trend_score = 70 if row.get("direction") not in {"mixed", "neutral"} else 48

    catalyst_score = 78 if radar.get("catalyst_available") or evidence.get("catalyst_available") else 48
    structure_score = (
        _number(_dict(evidence.get("factor_scores")).get("structure"))
        if row.get("source") == "intraday_radar"
        else 88 if row.get("entry") is not None and row.get("stop") is not None else 52
    )
    regime_confidence = _number(market_force.get("confidence"))
    if regime_confidence is not None and regime_confidence <= 1.0:
        regime_confidence *= 100.0
    regime_score = _clamp(regime_confidence if regime_confidence is not None else 50)
    evidence_score = 86 if row.get("paper_consumable") else 78 if row.get("source") == "live_opportunities" else 62 if row.get("source") == "intraday_radar" else 74 if row.get("source") == "mes_reopen_holdout" else 42
    option_quality = 82 if liquidity.get("verdict") == "qualified" else 35 if liquidity else None
    factors = {
        "setup": _factor(setup_score, "Source setup quality and gate completion"),
        "trend": _factor(trend_score, "Direction, momentum, and relative-strength alignment"),
        "market_structure": _factor(structure_score, "Mechanical trigger and invalidation quality"),
        "liquidity": _factor(liquidity_score, "Underlying/contract spread, volume, and open interest"),
        "news_catalyst": _factor(catalyst_score, "Fresh catalyst or sector confirmation"),
        "market_regime": _factor(regime_score, "Market-force confidence and regime compatibility"),
        "evidence": _factor(evidence_score, "Forward evidence and execution authority"),
        "options_quality": _factor(option_quality, "Option-chain feasibility", available=option_quality is not None),
    }
    if row.get("source") == "intraday_radar":
        consensus_score = _number(_dict(evidence.get("factor_consensus")).get("score"))
        factors["cross_sectional_consensus"] = _factor(
            consensus_score,
            "Same-snapshot factor agreement; observe-only and excluded from execution scoring",
            available=consensus_score is not None,
        )
    weights = {
        "setup": 0.25,
        "trend": 0.14,
        "market_structure": 0.17,
        "liquidity": 0.15,
        "news_catalyst": 0.08,
        "market_regime": 0.10,
        "evidence": 0.11,
        "options_quality": 0.10,
        "cross_sectional_consensus": 0.0,
    }
    available = [(name, item) for name, item in factors.items() if item["available"]]
    denominator = sum(weights[name] for name, _ in available)
    score = round(sum(float(item["score"]) * weights[name] for name, item in available) / denominator, 1) if denominator else 0.0
    if row.get("blockers") and row.get("source") != "intraday_radar":
        score = min(score, 69.0)
    if not row.get("paper_consumable") and row.get("source") not in {"mes_reopen_holdout", "intraday_radar", "live_opportunities"}:
        score = min(score, 74.0)

    contract = _occ_contract(row.get("instrument"), now)
    blockers = [str(item) for item in _list(row.get("blockers"))]
    if contract and contract["expired"]:
        blockers.append("option_contract_expired")
        contract = None
    is_option_plan = row.get("asset_class") in {"option", "equity_option", "equity_or_option"}
    if is_option_plan and contract is None:
        blockers.append("live_option_contract_not_confirmed")

    probability = _probability_contract(evidence.get("probability"))
    if row.get("source") == "mes_reopen_holdout":
        test = _dict(evidence.get("test_2025_2026"))
        probability = {
            "value": round((_number(test.get("win_rate")) or 0) * 100, 1),
            "lower_bound": None,
            "status": "historical_reference_only",
            "label": "Holdout win rate, not a forecast",
            "sample_size": test.get("trades"),
            "independent_dates": None,
            "brier_skill_vs_expanding_base_rate": None,
            "calibration_qualified": False,
            "ranking_eligible": False,
            "qualification_failures": ["historical_reference_not_live_conditional_calibration"],
        }

    entry = _number(row.get("entry"))
    stop = _number(row.get("stop"))
    target = _number(row.get("target"))
    current_price = (
        _number(evidence.get("price"))
        or _number(radar.get("price"))
        or _number(surface.get("spot"))
    )
    decision = _decision_state(row, current_price=current_price, contract_ready=contract is not None)
    if decision["actionability"] == "shadow_ready":
        blockers = [item for item in blockers if item != "strategy_confirmation_and_revalidation_required"]
    if decision["actionability"] == "late_no_chase":
        blockers.append("minimum_remaining_reward_not_met")
    if decision["actionability"] == "invalid":
        blockers.append("mechanical_invalidation_crossed")
    decision_score = round(
        score * 0.55 + float(decision["timing_score"]) * 0.25 + float(decision["execution_score"]) * 0.20,
        1,
    )
    decision_caps = {"armed": 84.0, "too_late": 49.0, "invalid": 20.0, "research_only": 59.0}
    decision_score = min(decision_score, decision_caps.get(str(decision["lifecycle"]), 100.0))
    if contract:
        display_instrument = contract["symbol"]
    elif row.get("asset_class") == "future":
        display_instrument = _text(row.get("instrument"), symbol)
    elif row.get("asset_class") == "equity":
        display_instrument = f"{symbol} shares"
    elif is_option_plan:
        display_instrument = "Pending live option contract"
    else:
        display_instrument = symbol

    plan = {
        "instrument": display_instrument,
        "contract": contract,
        "underlying_price": current_price,
        "entry_trigger": entry,
        "entry_instruction": _text(row.get("order_style"), "revalidate_before_entry"),
        "invalidation": stop,
        "targets": ([{"name": "target_1", "price": target}] if target is not None else []),
        "reward_risk": _number(row.get("reward_risk")),
        "time_window": "18:00 ET to 09:30 ET" if row.get("source") == "mes_reopen_holdout" else "regular session; revalidate immediately before entry",
        "risk_note": "Defined by stop/invalidation; position size is intentionally not inferred" if stop is not None else "No executable risk amount until trigger and contract are confirmed",
    }
    row = {**row}
    row["blockers"] = sorted(set(blockers))
    row["paper_consumable"] = bool(row.get("paper_consumable")) and not row["blockers"]
    probability["ranking_eligible"] = bool(probability.get("calibration_qualified")) and decision["actionability"] == "shadow_ready" and not row["blockers"]
    row.update(
        {
            "plan_id": _plan_id(row),
            "setup_score": score,
            "setup_grade": _grade(score),
            "timing_score": decision["timing_score"],
            "execution_score": decision["execution_score"],
            "decision_score": decision_score,
            "grade": _grade(decision_score),
            "score_label": "decision quality score",
            **decision,
            "probability": probability,
            "factors": factors,
            "trade_plan": plan,
        }
    )
    return row


def _dedupe_candidates(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[tuple[str, str, str]] = set()
    result: list[dict[str, Any]] = []
    for row in sorted(rows, key=lambda item: (-float(item.get("routing_priority") or 0), item["symbol"])):
        key = (row["symbol"], row["source"], row["setup"])
        if key in seen:
            continue
        seen.add(key)
        result.append(row)
    return result


def _best_candidate_per_symbol(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Keep one dominant plan per symbol on the simplified decision surface."""
    selected: dict[str, dict[str, Any]] = {}
    for row in rows:
        symbol = _text(row.get("symbol"))
        if symbol and symbol not in selected:
            selected[symbol] = row
    return list(selected.values())


def _explicit_no_trade_zone(row: dict[str, Any]) -> dict[str, Any]:
    """Carry a source-defined zone without manufacturing one from unrelated levels."""
    evidence = _dict(row.get("evidence"))
    containers = (row, evidence, _dict(evidence.get("trade_levels")), _dict(evidence.get("next_session_plan")))
    for container in containers:
        raw = container.get("no_trade_zone")
        if isinstance(raw, dict):
            low = _number(raw.get("low") or raw.get("lower"))
            high = _number(raw.get("high") or raw.get("upper"))
        elif isinstance(raw, (list, tuple)) and len(raw) == 2:
            low, high = _number(raw[0]), _number(raw[1])
        else:
            continue
        if low is not None and high is not None and low < high:
            return {
                "status": "available",
                "low": low,
                "high": high,
                "instruction": f"Stand aside while price remains between {low:g} and {high:g}.",
            }
    return {
        "status": "not_supplied",
        "low": None,
        "high": None,
        "instruction": "No source-defined two-sided no-trade zone is available; none was inferred.",
    }


def _command_card(
    row: dict[str, Any] | None, *, now: datetime | None = None
) -> dict[str, Any]:
    now = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    if not row:
        return {
            "state": "STAND_ASIDE",
            "color": "RED",
            "symbol": None,
            "direction": "neutral",
            "setup": None,
            "grade": "--",
            "decision_score": None,
            "trigger": None,
            "confirmation_required": "Wait for a complete trigger, invalidation, target, and fresh quote.",
            "invalidation": None,
            "target": None,
            "instrument": None,
            "no_trade_zone": {
                "status": "not_supplied",
                "low": None,
                "high": None,
                "instruction": "No active plan is available.",
            },
            "next_action": "Stand aside. Do not manufacture a trade.",
            "evidence_fresh": False,
            "evidence_age_seconds": None,
            "plan_id": None,
            "execution_enabled": False,
            "can_submit_orders": False,
        }

    actionability = _text(row.get("actionability"), "research_only")
    state, color = {
        "shadow_ready": ("READY_TO_REVIEW", "GREEN"),
        "wait": ("WAIT", "YELLOW"),
        "late_no_chase": ("NO_CHASE", "RED"),
        "invalid": ("INVALID", "RED"),
        "research_only": ("RESEARCH_ONLY", "YELLOW"),
    }.get(actionability, ("STAND_ASIDE", "RED"))
    plan = _dict(row.get("trade_plan"))
    evidence = _dict(row.get("evidence"))
    confirmation = _dict(evidence.get("price_action_confirmation"))
    bar_at = confirmation.get("bar_completed_at")
    evaluated_at = _parse_time(bar_at or row.get("generated_at"))
    evidence_age_seconds = (
        max(0.0, (now - evaluated_at).total_seconds()) if evaluated_at else None
    )
    evidence_fresh = bool(
        evidence_age_seconds is not None and evidence_age_seconds <= 20 * 60
    )
    if actionability in {"shadow_ready", "wait"} and not evidence_fresh:
        state, color = "STAND_ASIDE", "RED"
    confirmation_required = (
        "Completed 5-minute close, hold/retest, fresh quote, and liquidity revalidation."
        if row.get("asset_class") != "future"
        else "Scheduled rule eligibility and a fresh tradable quote at the defined window."
    )
    if bar_at:
        confirmation_required += f" Last evaluated bar: {bar_at}."
    targets = _list(plan.get("targets"))
    target = _number(_dict(targets[0]).get("price")) if targets else _number(row.get("target"))
    return {
        "state": state,
        "color": color,
        "symbol": row.get("symbol"),
        "direction": _direction_family(row.get("direction")),
        "setup": row.get("setup"),
        "grade": row.get("grade"),
        "decision_score": row.get("decision_score"),
        "trigger": _number(plan.get("entry_trigger")) or _number(row.get("entry")),
        "confirmation_required": confirmation_required,
        "invalidation": _number(plan.get("invalidation")) or _number(row.get("stop")),
        "target": target,
        "instrument": plan.get("instrument") or row.get("instrument"),
        "no_trade_zone": _explicit_no_trade_zone(row),
        "next_action": (
            row.get("next_action")
            if evidence_fresh or actionability not in {"shadow_ready", "wait"}
            else "Stand aside. Completed-bar evidence is stale or unavailable; refresh the scanners."
        ),
        "evidence_fresh": evidence_fresh,
        "evidence_age_seconds": round(evidence_age_seconds, 1) if evidence_age_seconds is not None else None,
        "plan_id": row.get("plan_id"),
        "execution_enabled": False,
        "can_submit_orders": False,
    }


def _dealer_gamma_regime(market_force: dict[str, Any]) -> dict[str, Any]:
    force = next(
        (_dict(row) for row in _list(market_force.get("forces")) if _dict(row).get("name") == "levels_gex"),
        {},
    )
    status = _text(force.get("status"), "missing")
    evidence = _dict(force.get("evidence"))
    negative = int(_number(evidence.get("negative_gamma")) or 0)
    positive = int(_number(evidence.get("positive_gamma")) or 0)
    net_state = "negative" if negative > positive else "positive" if positive > negative else "unavailable"
    qualified = status not in {"missing", "unavailable"} and net_state != "unavailable"
    if not qualified:
        route = "No gamma route. Use price action and the ordinary risk gates only."
    elif net_state == "negative":
        route = "Momentum context only; wait for price-action confirmation and use smaller defined risk."
    else:
        route = "Range-damping context only; do not fade without a confirmed rejection at a mechanical level."
    return {
        "status": "context_available" if qualified else "unavailable",
        "source_status": status,
        "net_gex_state": net_state,
        "spot_vs_flip": "unavailable",
        "quadrant": None,
        "strategy_route": route,
        "reason": evidence.get("reason") or "A spot-revalued gamma flip is not available from the current proxy.",
        "execution_authority": False,
    }


def _daily_review_gate(report: dict[str, Any], source: dict[str, Any]) -> dict[str, Any]:
    """Summarize whether the daily top-tier evidence denominator is complete."""
    summary = _dict(report.get("summary"))
    failed_sources = sorted({
        _text(_dict(row).get("source"), "unknown")
        for row in _list(report.get("source_inventory"))
        if _text(_dict(row).get("status"), "missing") != "reviewed"
    })
    overall = _number(
        summary.get("overall_review_coverage_pct")
        if summary.get("overall_review_coverage_pct") is not None
        else summary.get("system_review_coverage_pct")
    )
    reported_status = _text(report.get("review_status"), "missing")
    complete = bool(report) and reported_status == "complete" and overall == 100.0 and not failed_sources
    return {
        "status": "complete" if complete else "attention_required" if report else "missing",
        "date": report.get("date"),
        "generated_at": report.get("timestamp") or report.get("generated_at"),
        "source": source,
        "reviewed_setup_count": int(_number(summary.get("system_reviewed_setup_count")) or 0),
        "outcome_followup_count": int(_number(summary.get("outcome_followup_count")) or 0),
        "source_coverage_pct": _number(summary.get("source_coverage_pct")),
        "overall_review_coverage_pct": overall,
        "failed_sources": failed_sources,
        "message": (
            "All declared evidence producers and enumerated top-tier setups were reviewed."
            if complete
            else "Daily review is incomplete; missing producers or open evidence coverage must be resolved."
        ),
        "execution_enabled": False,
        "can_submit_orders": False,
    }


def _execution_quality(
    reports: dict[str, dict[str, Any]], sources_by_name: dict[str, dict[str, Any]]
) -> dict[str, Any]:
    manual = reports.get("manual_execution_quality", {})
    broker = reports.get("broker_fill_observer", {})
    manual_summary = _dict(manual.get("summary"))
    broker_summary = _dict(broker.get("summary"))
    followups = int(_number(manual_summary.get("missing_followup_count")) or 0)
    linkage_issues = int(_number(broker_summary.get("ambiguous_count")) or 0) + int(
        _number(broker_summary.get("unmatched_count")) or 0
    )
    if followups or linkage_issues:
        status = "followup_required"
    elif manual or broker:
        status = "available"
    else:
        status = "missing"
    return {
        "status": status,
        "manual": _source_surface("manual_execution_quality", reports, sources_by_name),
        "broker": _source_surface("broker_fill_observer", reports, sources_by_name),
        "manual_observations": int(_number(manual_summary.get("observation_count")) or 0),
        "manual_followups": followups,
        "broker_fills": int(_number(broker_summary.get("fill_count")) or 0),
        "broker_matched": int(_number(broker_summary.get("matched_count")) or 0),
        "broker_linkage_issues": linkage_issues,
        "message": (
            "Resolve manual outcome follow-ups and ambiguous broker-fill linkage."
            if status == "followup_required"
            else "Execution-quality evidence is available for review."
            if status == "available"
            else "Execution-quality producers have not emitted evidence yet."
        ),
        "execution_enabled": False,
        "can_submit_orders": False,
    }


def build_cockpit(
    *, report_dir: Path = REPORT_DIR, now: datetime | None = None
) -> dict[str, Any]:
    now = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    reports = {name: _load_json(report_dir / filename) for name, filename in REPORT_FILES.items()}
    failure_path = FAILURE_TAXONOMY_FILE if report_dir.resolve() == REPORT_DIR.resolve() else report_dir / "failure-taxonomy.json"
    reconciliation_events_path = (
        RECONCILIATION_EVENTS_FILE
        if report_dir.resolve() == REPORT_DIR.resolve()
        else report_dir / "reconciliation_events.jsonl"
    )
    failure_taxonomy = _load_json(failure_path)
    if not failure_taxonomy:
        failure_taxonomy = _load_json(report_dir / "failure-taxonomy.json")
    broker_reconciliation = _load_json(report_dir / BROKER_RECONCILIATION_REPORT)
    reconciliation_events = _load_jsonl(reconciliation_events_path)
    sources = _source_inventory(reports, report_dir, now)
    sources_by_name = {row["name"]: row for row in sources}

    signals = reports["trade_signals"]
    bottoms = reports["bottom_reversals"]
    daily_edge = reports["daily_edge"]
    stock_screen = reports["stock_screener"]
    radar = reports["premarket_radar"]
    intraday = reports["intraday_radar"]
    live_opportunities = reports["live_opportunities"]
    simple_price_action = reports["simple_price_action"]
    market_force = reports["market_force"]

    liquidity_by_symbol = {
        _text(row.get("symbol")): row
        for row in _list(reports["options_liquidity"].get("results"))
        if isinstance(row, dict) and row.get("symbol")
    }
    surface_by_symbol = {
        _text(row.get("symbol")): row
        for row in _list(reports["options_surface"].get("results"))
        if isinstance(row, dict) and row.get("symbol")
    }
    radar_by_symbol = {
        _text(row.get("symbol")): row
        for row in _list(radar.get("observations"))
        if isinstance(row, dict) and row.get("symbol")
    }
    radar_by_symbol.update(
        {
            _text(row.get("symbol")): row
            for row in _list(intraday.get("ranked_candidates"))
            if isinstance(row, dict) and row.get("symbol")
        }
    )

    candidates: list[dict[str, Any]] = []
    candidates.extend(_signal_candidate(row) for row in _list(signals.get("signals")) if isinstance(row, dict))
    candidates.extend(_bottom_candidate(row) for row in _list(bottoms.get("candidates")) if isinstance(row, dict))
    candidates.extend(_edge_candidate(row) for row in _list(daily_edge.get("morning_targets")) if isinstance(row, dict))
    candidates.extend(_stock_candidate(row) for row in _list(stock_screen.get("rankings"))[:12] if isinstance(row, dict))
    candidates.extend(_radar_candidate(row) for row in _list(radar.get("observations"))[:16] if isinstance(row, dict))
    candidates.extend(_intraday_candidate(row) for row in _list(intraday.get("ranked_candidates"))[:24] if isinstance(row, dict))
    candidates.extend(
        _live_opportunity_candidate(row)
        for row in _list(live_opportunities.get("candidates"))[:24]
        if isinstance(row, dict)
    )
    research_file = MES_HOLDOUT_FILE if report_dir.resolve() == REPORT_DIR.resolve() else report_dir / "mes_reopen_vix_holdout.json"
    mes_candidate = _mes_candidate(_load_json(research_file))
    if mes_candidate:
        candidates.append(mes_candidate)
    candidates = _dedupe_candidates(candidates)
    candidates = [
        _enrich_candidate(
            row,
            now=now,
            market_force=market_force,
            liquidity_by_symbol=liquidity_by_symbol,
            surface_by_symbol=surface_by_symbol,
            radar_by_symbol=radar_by_symbol,
        )
        for row in candidates
    ]
    candidates = [
        _apply_grade_calibration(
            row,
            reports["grade_calibration"],
            regime=_text(market_force.get("classification"), "unavailable"),
        )
        for row in candidates
    ]
    candidates = [_quarantine_stale_candidate(row, sources_by_name) for row in candidates]
    candidates.sort(
        key=lambda item: (
            0 if _dict(item.get("probability")).get("ranking_eligible") else 1,
            -float(_dict(item.get("probability")).get("lower_bound") or 0),
            -float(item.get("decision_score") or 0),
            -float(item.get("setup_score") or 0),
            item["symbol"],
        )
    )
    desk_candidates = _best_candidate_per_symbol(candidates)

    eligible = [row for row in candidates if row["paper_consumable"] and not row["blockers"]]
    shadow_ready = [row for row in desk_candidates if row.get("actionability") == "shadow_ready"]
    armed = [row for row in desk_candidates if row.get("actionability") == "wait"]
    late = [row for row in desk_candidates if row.get("actionability") == "late_no_chase"]
    invalid = [row for row in desk_candidates if row.get("actionability") == "invalid"]
    probability_ranked = [row for row in shadow_ready if _dict(row.get("probability")).get("ranking_eligible")]
    best_setup = probability_ranked[0] if probability_ranked else eligible[0] if eligible else shadow_ready[0] if shadow_ready else None
    primary_decision = (
        probability_ranked[0] if probability_ranked else shadow_ready[0] if shadow_ready else armed[0] if armed else late[0] if late else invalid[0] if invalid else None
    )

    bot_status = reports["bot_status"]
    breadth = _dict(reports["market_breadth"].get("breadth"))
    rotation = _dict(reports["sector_rotation"].get("rotation"))
    catalyst = reports["catalysts"]
    reconciliation = reports["position_reconciliation"]
    health = reports["signal_health"]
    audit = reports["execution_audit"]
    daily_review_gate = _daily_review_gate(
        reports["aplus_review"], sources_by_name.get("aplus_review", {})
    )
    system_readiness = build_readiness(root=ROOT, report_dir=report_dir, now=now)

    stale_sources = [row["name"] for row in sources if row["freshness"] in {"stale", "missing"}]
    risk_blockers = []
    risk_blockers.extend(str(item) for item in _list(daily_edge.get("global_blockers")))
    risk_blockers.extend(str(item) for item in _list(audit.get("issues")))
    risk_blockers.extend(str(item) for item in _list(reconciliation.get("issues")))
    risk_blockers.extend(str(item) for item in _list(broker_reconciliation.get("issues")))
    command_card = _command_card(primary_decision, now=now)
    if broker_reconciliation.get("issues"):
        command_card = {
            **command_card,
            "state": "STAND_ASIDE",
            "color": "RED",
            "next_action": "Broker reconciliation differs from local state. Resolve the mismatch before review.",
            "execution_enabled": False,
            "can_submit_orders": False,
        }

    return {
        "schema_version": 11,
        "generated_at": now.isoformat(),
        "refresh_seconds": 15,
        "mode": "read_only_decision_support",
        "authority": {
            "execution_enabled": False,
            "can_submit_orders": False,
            "live_capital_enabled": False,
            "paper_signal_count": len(eligible),
            "message": "Cockpit ranks evidence; each paper consumer must revalidate every execution gate.",
        },
        "headline": {
            "best_setup": best_setup,
            "state": "shadow_setup_ready" if best_setup and not best_setup.get("paper_consumable") else "paper_setup_available" if best_setup else "no_eligible_setup",
            "message": (
                f"{best_setup['symbol']} has the highest qualified conditional probability ({_dict(best_setup.get('probability')).get('value')}%; conservative bound {_dict(best_setup.get('probability')).get('lower_bound')}%) among timely setups; revalidate before any manual action."
                if best_setup and _dict(best_setup.get("probability")).get("ranking_eligible")
                else f"{best_setup['symbol']} is the highest evidence-adjusted timely setup; no qualified calibrated probability is available. Revalidate before any manual action."
                if best_setup
                else "No setup is timely and confirmed now. Review the armed list and do not chase extended moves."
            ),
        },
        "ranking_policy": {
            "mode": "conditional_probability_first" if probability_ranked else "decision_quality_fallback_no_qualified_probability",
            "qualified_candidate_count": len(probability_ranked),
            "minimum_samples": 100,
            "minimum_independent_dates": 30,
            "requires_positive_brier_skill_vs_expanding_base_rate": True,
            "uses_conservative_lower_bound": True,
            "fallback": "Evidence-adjusted decision quality is used only when no current candidate has qualified calibration.",
            "execution_enabled": False,
            "can_submit_orders": False,
        },
        "command_card": command_card,
        "daily_review_gate": daily_review_gate,
        "system_readiness": system_readiness,
        "execution_quality": _execution_quality(reports, sources_by_name),
        "dealer_regime": _dealer_gamma_regime(market_force),
        "options_context": _options_context(reports, sources_by_name),
        "decision_desk": {
            "state_definitions": {
                "shadow_ready": "Confirmed geometry with at least 1.25R reward remaining; still requires a fresh quote.",
                "wait": "Quality setup is armed but the completed-bar trigger has not confirmed.",
                "late_no_chase": "The move consumed at least half the planned path or offers less than 1.25R remaining.",
                "invalid": "Price crossed the planned invalidation.",
                "research_only": "Useful context without a complete executable plan.",
            },
            "counts": {
                "shadow_ready": len(shadow_ready),
                "wait": len(armed),
                "late_no_chase": len(late),
                "invalid": len(invalid),
                "research_only": sum(row.get("actionability") == "research_only" for row in desk_candidates),
            },
            "best_now": shadow_ready[:5],
            "next_up": armed[:8],
            "no_chase": late[:8],
            "invalid": invalid[:8],
            "method": "Qualified conditional probability ranks first; otherwise setup quality, timing, remaining reward, mechanical geometry, and instrument readiness are scored separately.",
        },
        "market": {
            "classification": market_force.get("classification") or _dict(bot_status.get("market_force")).get("classification"),
            "force_score": _number(market_force.get("total_score")),
            "confidence": _number(market_force.get("confidence")),
            "risk_veto": _dict(market_force.get("risk_veto")),
            "breadth_status": breadth.get("uptrend_status") or reports["market_breadth"].get("status"),
            "pct_above_50dma": _number(breadth.get("pct_above_50dma")),
            "sector_leadership": rotation.get("leadership"),
            "leading_sectors": [
                _dict(row).get("symbol") for row in _list(rotation.get("rankings"))[:5] if _dict(row).get("symbol")
            ],
            "high_impact_days_ahead": _list(catalyst.get("high_impact_days_ahead")),
            "warnings": _list(market_force.get("warnings")) + _list(catalyst.get("warnings")),
        },
        "account": _dict(bot_status.get("account")),
        "portfolio": {
            **_dict(bot_status.get("portfolio_concentration")),
            "open_trades": _dict(bot_status.get("open_trades")),
            "position_integrity": _dict(bot_status.get("option_position_integrity")),
        },
        "operations": {
            "health": _dict(bot_status.get("health")),
            "status": bot_status.get("status"),
            "signal_stack_summary": _dict(health.get("summary")),
            "task_count": len(_list(health.get("items"))),
            "tasks": _list(health.get("items")),
            "audit_issue_count": audit.get("issue_count", len(_list(audit.get("issues")))),
            "risk_blockers": sorted(set(risk_blockers)),
            "stale_source_count": len(stale_sources),
            "stale_sources": stale_sources,
            "quarantined_sources": _quarantined_sources(sources),
            "failure_taxonomy_week": _failure_taxonomy_week(failure_taxonomy, now),
            "reconciliation_status": _reconciliation_status(
                broker_reconciliation, reconciliation_events, now
            ),
        },
        "evidence": {
            "shadow_consensus": reports["shadow_consensus"],
            "shadow_audit": reports["shadow_audit"],
            "bottom_reversal": reports["bottom_evidence"],
            "scanner_leadership": _list(daily_edge.get("scanner_leadership")),
            "exit_accountability": _list(daily_edge.get("exit_accountability")),
            "move_coverage": reports["move_coverage"],
            "retro": _evidence_group(
                ("daily_eod", "daily_outcome", "aplus_review", "closed_postmortem", "missed_banger"),
                reports,
                sources_by_name,
            ),
            "journal": _evidence_group(
                ("rejected_intel", "lesson_ledger", "needs_review"),
                reports,
                sources_by_name,
            ),
            "social": _evidence_group(
                ("verified_trader", "public_intake", "trending_symbols"),
                reports,
                sources_by_name,
            ),
            "catalysts_today": _catalysts_today(
                catalyst,
                sources_by_name.get("catalysts", {}),
                now=now,
            ),
            "sec_catalysts": _source_surface(
                "sec_catalysts",
                reports,
                sources_by_name,
            ),
        },
        "research_governance": _research_governance(report_dir, now),
        "discovery": {
            "coverage": _dict(intraday.get("coverage")),
            "health": intraday.get("operational_health"),
            "session_status": intraday.get("session_status"),
            "top_precision_watches": _list(intraday.get("precision_watch"))[:8],
            "move_coverage": _dict(reports["move_coverage"].get("summary")),
            "scorecard_rolling": reports["detection_scorecard"],
            "cisd_promotion_status": reports["cisd_promotion"],
            "pattern_grader": {
                **reports["pattern_grades"],
                "source": sources_by_name.get("pattern_grades", {}),
                "execution_enabled": False,
                "can_submit_orders": False,
            },
            "execution_enabled": False,
            "can_submit_orders": False,
        },
        "calibration": {
            **reports["grade_calibration"],
            "source": sources_by_name.get("grade_calibration", {}),
            "execution_enabled": False,
            "can_submit_orders": False,
        },
        "live_opportunities": {
            "generated_at": live_opportunities.get("generated_at"),
            "decision_state": live_opportunities.get("decision_state", "STAND_ASIDE"),
            "ready_count": live_opportunities.get("ready_count", 0),
            "candidate_count": live_opportunities.get("candidate_count", 0),
            "feed": _dict(live_opportunities.get("feed")),
            "providers": _dict(live_opportunities.get("providers")),
            "validation": _dict(live_opportunities.get("validation")),
            "top_candidates": _list(live_opportunities.get("top_candidates"))[:3],
            "market_structure_patterns": _list(live_opportunities.get("market_structure_patterns")),
            "market_structure_watchlist": _list(live_opportunities.get("market_structure_watchlist"))[:24],
            "execution_enabled": False,
            "can_submit_orders": False,
        },
        "simple_signals": {
            "definitions": _dict(simple_price_action.get("definitions")),
            "counts": _dict(simple_price_action.get("counts")),
            "signals": _list(simple_price_action.get("signals"))[:12],
            "generated_at": simple_price_action.get("generated_at"),
            "execution_enabled": False,
            "can_submit_orders": False,
        },
        "trade_board": {
            "score_definition": "Highest qualified conditional probability ranks first; decision quality is the explicit fallback and is not probability of profit.",
            "probability_policy": "Probability requires at least 100 samples, 30 independent dates, a conservative bound, and positive Brier skill versus an expanding base rate.",
            "stocks": [row for row in desk_candidates if row["asset_class"] == "equity"][:10],
            "options": [row for row in desk_candidates if row["asset_class"] in {"option", "equity_option", "equity_or_option"}][:10],
            "futures": [row for row in desk_candidates if row["asset_class"] == "future"][:6],
            "review_fields": ["plan_id", "triggered", "entry_fill", "max_favorable_excursion", "max_adverse_excursion", "exit_fill", "outcome_r", "lesson"],
        },
        "candidates": candidates,
        "sources": sources,
        "warnings": [
            "Routing priority is not a probability of profit.",
            "Watchlists and scanner ranks are not entries.",
            "A strong setup is not actionable when timing or remaining reward fails.",
            "No live or paper order can originate from this endpoint.",
        ],
    }


def load_source(name: str, *, report_dir: Path = REPORT_DIR) -> dict[str, Any]:
    filename = REPORT_FILES.get(name)
    if filename is None:
        raise KeyError(name)
    return _load_json(report_dir / filename)


if __name__ == "__main__":
    print(json.dumps(build_cockpit(), indent=2, default=str))

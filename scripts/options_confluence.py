"""Read-only options timeframe and confluence attribution helpers.

These helpers label observations for forward shadow analysis. They do not
score setups, change strategy gates, size positions, or submit orders.
"""
from __future__ import annotations

import math
import json
from collections import defaultdict
from datetime import date, datetime, timezone
from pathlib import Path
from statistics import mean
from typing import Any, Iterable, Mapping, Optional
from zoneinfo import ZoneInfo


NY = ZoneInfo("America/New_York")
MIN_REVIEW_RESOLVED = 30
MIN_REVIEW_DATES = 20


def _number(value: Any) -> Optional[float]:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def _parse_timestamp(value: Any) -> Optional[datetime]:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def dte_bucket(days: Optional[int]) -> str:
    if days is None or days < 0:
        return "unknown"
    if days == 0:
        return "0dte"
    if days <= 4:
        return "1-4dte"
    if days <= 7:
        return "5-7dte"
    if days <= 20:
        return "8-20dte"
    if days <= 30:
        return "21-30dte"
    if days <= 45:
        return "31-45dte"
    return "46plus_dte"


def entry_time_bucket(timestamp: Any) -> str:
    parsed = _parse_timestamp(timestamp)
    if parsed is None:
        return "unknown"
    local = parsed.astimezone(NY)
    minute = local.hour * 60 + local.minute
    if minute < 9 * 60 + 30 or minute >= 16 * 60:
        return "outside_rth"
    if minute < 10 * 60:
        return "09:30-10:00"
    if minute < 11 * 60 + 30:
        return "10:00-11:30"
    if minute < 14 * 60:
        return "11:30-14:00"
    if minute < 15 * 60 + 30:
        return "14:00-15:30"
    return "15:30-16:00"


def _candidate_dte(candidate: Mapping[str, Any]) -> Optional[int]:
    created = _parse_timestamp(candidate.get("created_at"))
    try:
        expiry = date.fromisoformat(str(candidate.get("expiry") or ""))
    except ValueError:
        return None
    return (expiry - created.astimezone(NY).date()).days if created else None


def _ivr_band(value: Any) -> str:
    number = _number(value)
    if number is None:
        return "unavailable"
    if number < 30:
        return "below_30"
    if number < 50:
        return "30_to_49_99"
    if number < 75:
        return "50_to_74_99"
    return "75_or_higher"


def _vrp_band(edge: Mapping[str, Any]) -> str:
    value = _number(edge.get("net_vol_premium_ex_event_pct"))
    if value is None or str(edge.get("status") or "").lower() not in {
        "complete_ex_event",
        "complete",
    }:
        return "unavailable"
    if value <= 0:
        return "non_positive"
    if value < 2:
        return "positive_below_2pct"
    if value < 5:
        return "2_to_4_99pct"
    return "5pct_or_higher"


def _term_structure_band(value: Any) -> str:
    ratio = _number(value)
    if ratio is None or ratio <= 0:
        return "unavailable"
    if ratio < 1.0:
        return "contango"
    if ratio <= 1.05:
        return "flat_or_mild_backwardation"
    return "backwardation_over_5pct"


def _event_band(edge: Mapping[str, Any]) -> str:
    if edge.get("event_data_complete") is not True:
        return "incomplete"
    event_rows = edge.get("macro_events_within_horizon")
    has_macro = isinstance(event_rows, list) and bool(event_rows)
    has_flag = edge.get("earnings_within_horizon") is True or edge.get("fomc_within_horizon") is True
    return "event_within_horizon" if has_macro or has_flag else "clear_horizon"


def _trend_alignment(candidate: Mapping[str, Any]) -> str:
    consensus = candidate.get("shadow_consensus")
    if not isinstance(consensus, Mapping):
        return "unavailable"
    decision = consensus.get("decision")
    source = decision if isinstance(decision, Mapping) else consensus
    direction = str(source.get("market_direction") or "").lower()
    strategy = str(candidate.get("strategy") or "").lower()
    if direction not in {"bullish", "bearish", "neutral", "mixed", "unclear"}:
        return "unavailable"
    if strategy == "put_spread":
        return "aligned" if direction == "bullish" else "conflicted"
    if strategy == "call_spread":
        return "aligned" if direction == "bearish" else "conflicted"
    if strategy == "iron_condor":
        return "aligned" if direction in {"neutral", "mixed", "unclear"} else "conflicted"
    return "unavailable"


def _entry_friction_band(candidate: Mapping[str, Any]) -> str:
    midpoint = _number(candidate.get("quoted_mid_credit"))
    executable = _number(candidate.get("executable_entry_credit"))
    if midpoint is None or midpoint <= 0 or executable is None:
        return "unavailable"
    loss_fraction = max(0.0, midpoint - executable) / midpoint
    if loss_fraction <= 0.05:
        return "low_0_to_5pct"
    if loss_fraction <= 0.15:
        return "watch_5_to_15pct"
    return "high_over_15pct"


def candidate_dimensions(candidate: Mapping[str, Any]) -> dict[str, str]:
    """Return stable labels for a candidate without making a trade decision."""
    edge = candidate.get("volatility_edge")
    edge = edge if isinstance(edge, Mapping) else {}
    return {
        "strategy": str(candidate.get("strategy") or "unknown"),
        "dte_bucket": dte_bucket(_candidate_dte(candidate)),
        "entry_time_et": entry_time_bucket(candidate.get("created_at")),
        "ivr_band": _ivr_band(candidate.get("iv_rank_at_entry")),
        "maturity_matched_vrp_band": _vrp_band(edge),
        "vix_term_structure": _term_structure_band(candidate.get("vix_term_ratio")),
        "event_context": _event_band(edge),
        "trend_alignment": _trend_alignment(candidate),
        "entry_friction": _entry_friction_band(candidate),
    }


def latest_iv_rank_context(
    symbol: str,
    *,
    as_of: date,
    log_path: Path,
) -> dict[str, Any]:
    """Read the latest point-in-time IVR/IVP row without fetching or backfilling."""
    selected: Optional[dict[str, Any]] = None
    selected_date: Optional[date] = None
    try:
        lines = log_path.read_text(encoding="utf-8", errors="ignore").splitlines()
    except OSError:
        lines = []
    for raw in lines:
        try:
            row = json.loads(raw)
            row_date = date.fromisoformat(str(row.get("date") or ""))
        except (json.JSONDecodeError, TypeError, ValueError):
            continue
        if row_date > as_of or (selected_date is not None and row_date < selected_date):
            continue
        for scan in row.get("scans") or []:
            if isinstance(scan, dict) and str(scan.get("symbol") or "").upper() == symbol.upper():
                selected = scan
                selected_date = row_date
                break
    if selected is None or selected_date is None:
        return {
            "available": False,
            "status": "missing",
            "as_of_date": None,
            "ivr": None,
            "ivp": None,
            "history_days": 0,
        }
    ivr = _number(selected.get("ivr"))
    ivp = _number(selected.get("ivp"))
    ready = str(selected.get("ivr_status") or "").lower() == "ok" and ivr is not None and ivp is not None
    return {
        "available": ready,
        "status": "ready" if ready else str(selected.get("ivr_status") or "unavailable"),
        "as_of_date": selected_date.isoformat(),
        "ivr": ivr if ready else None,
        "ivp": ivp if ready else None,
        "history_days": int(_number(selected.get("history_days")) or 0),
        "atm_iv_method": selected.get("atm_iv_method"),
        "authority": "descriptive_context_only_no_execution",
    }


def _summarize(
    candidate_ids: Iterable[str],
    candidates: Mapping[str, Mapping[str, Any]],
    outcomes: Mapping[str, Mapping[str, Any]],
) -> dict[str, Any]:
    ids = list(candidate_ids)
    resolved = [
        (candidate_id, outcomes[candidate_id])
        for candidate_id in ids
        if candidate_id in outcomes and _number(outcomes[candidate_id].get("pnl_before_fees")) is not None
    ]
    pnls = [float(outcome["pnl_before_fees"]) for _, outcome in resolved]
    wins = sum(value > 0 for value in pnls)
    dates = {
        parsed.astimezone(NY).date().isoformat()
        for parsed in (_parse_timestamp(candidates[candidate_id].get("created_at")) for candidate_id, _ in resolved)
        if parsed is not None
    }
    ready = len(resolved) >= MIN_REVIEW_RESOLVED and len(dates) >= MIN_REVIEW_DATES
    blockers: list[str] = ["human_review_required", "forward_shadow_only"]
    if len(resolved) < MIN_REVIEW_RESOLVED:
        blockers.append("fewer_than_30_resolved_outcomes")
    if len(dates) < MIN_REVIEW_DATES:
        blockers.append("fewer_than_20_distinct_entry_dates")
    return {
        "candidate_count": len(ids),
        "resolved_count": len(resolved),
        "open_count": len(ids) - len(resolved),
        "distinct_resolved_entry_dates": len(dates),
        "win_rate": round(wins / len(pnls), 4) if pnls else None,
        "expectancy_before_fees": round(mean(pnls), 2) if pnls else None,
        "net_pnl_before_fees": round(sum(pnls), 2),
        "fees_included": False,
        "statistical_review_ready": ready,
        "promotion_eligible": False,
        "promotion_blockers": blockers,
    }


def build_confluence_analysis(
    candidates: Mapping[str, Mapping[str, Any]],
    outcomes: Mapping[str, Mapping[str, Any]],
) -> dict[str, Any]:
    """Group options shadows by individual dimensions and exact signatures."""
    dimensions_by_id = {
        candidate_id: candidate_dimensions(candidate)
        for candidate_id, candidate in candidates.items()
    }
    by_dimension: dict[str, dict[str, list[str]]] = defaultdict(lambda: defaultdict(list))
    by_signature: dict[str, list[str]] = defaultdict(list)
    for candidate_id, dimensions in dimensions_by_id.items():
        for name, value in dimensions.items():
            by_dimension[name][value].append(candidate_id)
        signature = "|".join(f"{name}={dimensions[name]}" for name in sorted(dimensions))
        by_signature[signature].append(candidate_id)

    dimension_rows = {
        name: [
            {"value": value, **_summarize(ids, candidates, outcomes)}
            for value, ids in sorted(values.items())
        ]
        for name, values in sorted(by_dimension.items())
    }
    signature_rows = [
        {
            "signature": signature,
            "dimensions": dimensions_by_id[ids[0]],
            **_summarize(ids, candidates, outcomes),
        }
        for signature, ids in sorted(by_signature.items())
    ]
    signature_rows.sort(
        key=lambda row: (
            int(row["resolved_count"]),
            float(row["expectancy_before_fees"] or -math.inf),
        ),
        reverse=True,
    )
    return {
        "authority": "read_only_attribution_no_execution",
        "execution_enabled": False,
        "can_submit_orders": False,
        "candidate_count": len(candidates),
        "resolved_count": sum(candidate_id in outcomes for candidate_id in candidates),
        "review_requirements": {
            "resolved_outcomes_per_cohort": MIN_REVIEW_RESOLVED,
            "distinct_entry_dates_per_cohort": MIN_REVIEW_DATES,
            "human_review": True,
            "fees_and_slippage_required": True,
        },
        "by_dimension": dimension_rows,
        "exact_confluence_cohorts": signature_rows,
        "warnings": [
            "Confluence labels are attribution variables, not independent probabilities.",
            "Selecting the best observed combination creates multiple-testing bias.",
            "No cohort can change gates, sizing, schedules, or execution settings automatically.",
            "IV rank and IV percentile are descriptive and do not replace maturity-matched IV versus realized volatility.",
        ],
    }

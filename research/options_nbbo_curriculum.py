#!/usr/bin/env python3
"""Point-in-time executable-quote replay for multi-leg option candidates."""
from __future__ import annotations

import argparse
import bisect
import hashlib
import json
import math
import os
import re
import sys
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass
from datetime import datetime, time, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.options_shadow_twin import executable_close_debit, executable_entry_credit


NY = ZoneInfo("America/New_York")
CHICAGO = ZoneInfo("America/Chicago")
DEFAULT_CANDIDATES_PATH = ROOT / "data" / "options_shadow_twin_log.jsonl"
DEFAULT_QUOTES_PATH = ROOT / "data" / "databento" / "options_nbbo_candidate_quotes.jsonl"
OUTPUT_PATH = ROOT / "data" / "options_nbbo_curriculum_results.json"
SUPPORTED_STRATEGIES = {"put_spread", "call_spread", "iron_condor", "iron_fly"}
ACCEPTED_NBBO_SCOPES = {
    "opra_nbbo",
    "licensed_opra_nbbo",
    "consolidated_opra_nbbo",
    "licensed_consolidated_nbbo",
    "databento_opra_cbbo_1s",
    "synthetic_opra_nbbo",  # deterministic tests only
}
OCC_PATTERN = re.compile(r"^[A-Z]{1,6}(\d{6})[CP]\d{8}$")
POLLING_SCHEDULES = {
    "one_minute": {"interval_seconds": 60, "start_ct": "08:45", "end_ct": "14:59"},
    "five_minute": {"interval_seconds": 300, "start_ct": "08:45", "end_ct": "14:55"},
    "legacy_thirty_minute": {"interval_seconds": 1800, "start_ct": "08:45", "end_ct": "14:45"},
}


@dataclass(frozen=True)
class OptionsNbboConfig:
    max_entry_delay_seconds: float = 60.0
    max_quote_age_seconds: float = 2.0
    max_leg_skew_seconds: float = 2.0
    max_relative_spread: float = 0.25
    fee_per_contract_leg_side: float = 0.66
    locked_holdout_fraction: float = 0.20
    chronological_blocks: int = 5
    minimum_review_resolved: int = 30
    minimum_lifecycle_coverage: float = 0.80
    minimum_review_blocks: int = 3
    minimum_profitable_block_rate: float = 0.60
    minimum_holdout_resolved: int = 10


def _number(value: Any) -> float | None:
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    return out if math.isfinite(out) else None


def _parse_ts(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _read_rows(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    suffix = path.suffix.lower()
    if suffix == ".jsonl":
        rows = []
        for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(row, dict):
                rows.append(row)
        return rows
    if suffix == ".json":
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
        if isinstance(payload, list):
            return [row for row in payload if isinstance(row, dict)]
        if isinstance(payload, dict):
            rows = payload.get("rows") or payload.get("quotes") or payload.get("candidates") or []
            return [row for row in rows if isinstance(row, dict)]
        return []
    if suffix in {".parquet", ".pq"}:
        import pandas as pd

        return pd.read_parquet(path).to_dict(orient="records")
    raise ValueError(f"unsupported input format: {path}")


def _scope(value: Any) -> str:
    return str(value or "unknown").strip().lower().replace("-", "_")


def normalize_quote_rows(rows: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    """Normalize flat quote rows and shadow-twin candidate/mark leg snapshots."""
    normalized: list[dict[str, Any]] = []
    for row in rows:
        observed = _parse_ts(
            row.get("observed_at") or row.get("captured_at") or row.get("marked_at")
            or row.get("created_at") or row.get("timestamp")
        )
        legs = row.get("legs") if isinstance(row.get("legs"), list) else None
        if legs is not None:
            for leg in legs:
                if not isinstance(leg, dict):
                    continue
                quote_at = _parse_ts(leg.get("quote_timestamp")) or observed
                normalized.append({
                    "symbol": str(leg.get("symbol") or leg.get("contract") or ""),
                    "observed_at": observed,
                    "quote_at": quote_at,
                    "bid": _number(leg.get("bid")),
                    "ask": _number(leg.get("ask")),
                    "scope": _scope(leg.get("quote_scope") or row.get("quote_scope")),
                })
            continue
        quote = row.get("quote") if isinstance(row.get("quote"), dict) else row
        quote_at = _parse_ts(quote.get("quote_timestamp") or row.get("quote_timestamp")) or observed
        normalized.append({
            "symbol": str(row.get("symbol") or row.get("contract") or quote.get("symbol") or ""),
            "observed_at": observed,
            "quote_at": quote_at,
            "bid": _number(quote.get("bid")),
            "ask": _number(quote.get("ask")),
            "scope": _scope(
                row.get("quote_scope")
                or ((row.get("provenance") or {}).get("quote_scope") if isinstance(row.get("provenance"), dict) else None)
                or ((row.get("provenance") or {}).get("feed") if isinstance(row.get("provenance"), dict) else None)
            ),
        })
    return [row for row in normalized if row["symbol"] and row["observed_at"] and row["quote_at"]]


def build_quote_index(rows: Iterable[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    index: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        if row.get("symbol") and isinstance(row.get("observed_at"), datetime):
            index[str(row["symbol"])].append(row)
    for values in index.values():
        values.sort(key=lambda row: row["observed_at"])
    return dict(index)


def _latest_observed(rows: list[dict[str, Any]], stamp: datetime) -> dict[str, Any] | None:
    index = bisect.bisect_right(rows, stamp, key=lambda row: row["observed_at"]) - 1
    return rows[index] if index >= 0 else None


def executable_snapshot(
    quote_index: dict[str, list[dict[str, Any]]],
    symbols: Iterable[str],
    stamp: datetime,
    config: OptionsNbboConfig,
) -> tuple[dict[str, dict[str, Any]] | None, str | None]:
    selected: dict[str, dict[str, Any]] = {}
    for symbol in symbols:
        quote = _latest_observed(quote_index.get(symbol, []), stamp)
        if quote is None:
            return None, "missing_leg_quote"
        quote_at = quote["quote_at"]
        observed_at = quote["observed_at"]
        if quote_at > observed_at or observed_at > stamp:
            return None, "lookahead_quote"
        age = (stamp - quote_at).total_seconds()
        if age < 0:
            return None, "lookahead_quote"
        if age > config.max_quote_age_seconds:
            return None, "stale_quote"
        if quote["scope"] not in ACCEPTED_NBBO_SCOPES:
            return None, "non_nbbo_scope"
        bid = quote.get("bid")
        ask = quote.get("ask")
        if bid is None or ask is None or bid <= 0 or ask < bid:
            return None, "invalid_or_crossed_market"
        mid = (bid + ask) / 2.0
        if mid <= 0 or (ask - bid) / mid > config.max_relative_spread:
            return None, "quote_width_veto"
        selected[symbol] = quote
    quote_times = [row["quote_at"] for row in selected.values()]
    if quote_times and (max(quote_times) - min(quote_times)).total_seconds() > config.max_leg_skew_seconds:
        return None, "inter_leg_quote_skew"
    return selected, None


def _snapshot_legs(candidate: dict[str, Any], snapshot: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "symbol": str(leg.get("symbol") or ""),
            "side": str(leg.get("side") or "").lower(),
            "ratio_qty": int(_number(leg.get("ratio_qty")) or 1),
            "bid": snapshot[str(leg.get("symbol") or "")]["bid"],
            "ask": snapshot[str(leg.get("symbol") or "")]["ask"],
        }
        for leg in candidate.get("legs") or []
    ]


def _candidate_end(candidate: dict[str, Any]) -> datetime | None:
    explicit = _parse_ts(candidate.get("evaluation_end_at") or candidate.get("exit_deadline"))
    if explicit:
        return explicit
    expiry = str(candidate.get("expiry") or "")
    try:
        local = datetime.combine(datetime.fromisoformat(expiry).date(), time(15, 45), tzinfo=NY)
    except ValueError:
        return None
    return local.astimezone(timezone.utc)


def _candidate_audit(candidate: dict[str, Any]) -> tuple[dict[str, Any] | None, str | None]:
    created = _parse_ts(candidate.get("created_at") or candidate.get("decision_at") or candidate.get("timestamp"))
    selected = _parse_ts(candidate.get("contract_selected_at")) or created
    strategy = str(candidate.get("strategy") or "")
    legs = candidate.get("legs") if isinstance(candidate.get("legs"), list) else []
    qty = int(_number(candidate.get("effective_qty") or candidate.get("qty")) or 0)
    max_risk = _number(candidate.get("max_risk_per_contract"))
    profit_pct = _number(candidate.get("profit_close_pct"))
    stop_pct = _number(candidate.get("stop_loss_pct"))
    if not created or not selected or selected > created:
        return None, "contract_selection_not_point_in_time"
    if strategy not in SUPPORTED_STRATEGIES:
        return None, "unsupported_strategy"
    if not legs or any(not str(leg.get("symbol") or "") for leg in legs):
        return None, "missing_concrete_contracts"
    occ_matches = [OCC_PATTERN.fullmatch(str(leg.get("symbol") or "").upper()) for leg in legs]
    if any(match is None for match in occ_matches):
        return None, "invalid_occ_contract"
    if any(
        datetime.strptime(match.group(1), "%y%m%d").date() < created.astimezone(NY).date()
        for match in occ_matches if match is not None
    ):
        return None, "contract_expired_before_candidate"
    if any(str(leg.get("side") or "").lower() not in {"buy", "sell"} for leg in legs):
        return None, "invalid_leg_side"
    if qty <= 0 or max_risk is None or max_risk <= 0:
        return None, "missing_quantity_or_max_risk"
    if profit_pct is None or not 0 <= profit_pct <= 1 or stop_pct is None or stop_pct > 0:
        return None, "missing_or_invalid_exit_policy"
    end = _candidate_end(candidate)
    if not end or end <= created:
        return None, "missing_or_invalid_evaluation_end"
    return {
        "created": created,
        "selected": selected,
        "end": end,
        "qty": qty,
        "max_risk": max_risk,
        "profit_pct": profit_pct,
        "stop_pct": stop_pct,
        "symbols": [str(leg["symbol"]) for leg in legs],
    }, None


def _session_poll_times(
    start: datetime,
    end: datetime,
    *,
    interval_seconds: int,
    start_ct: str,
    end_ct: str,
) -> Iterable[datetime]:
    start_hour, start_minute = (int(value) for value in start_ct.split(":"))
    end_hour, end_minute = (int(value) for value in end_ct.split(":"))
    current_date = start.astimezone(CHICAGO).date()
    end_date = end.astimezone(CHICAGO).date()
    while current_date <= end_date:
        if current_date.weekday() < 5:
            stamp = datetime.combine(current_date, time(start_hour, start_minute), tzinfo=CHICAGO)
            session_end = datetime.combine(current_date, time(end_hour, end_minute), tzinfo=CHICAGO)
            while stamp <= session_end:
                utc_stamp = stamp.astimezone(timezone.utc)
                if start < utc_stamp <= end:
                    yield utc_stamp
                stamp += timedelta(seconds=interval_seconds)
        current_date += timedelta(days=1)


def _polling_replay(
    candidate: dict[str, Any],
    quote_index: dict[str, list[dict[str, Any]]],
    audit: dict[str, Any],
    entry_at: datetime,
    entry_credit: float,
    config: OptionsNbboConfig,
    schedule: dict[str, Any],
) -> dict[str, Any]:
    symbols = audit["symbols"]
    available_ends = [quote_index[symbol][-1]["observed_at"] for symbol in symbols if quote_index.get(symbol)]
    if len(available_ends) != len(symbols):
        return {"status": "unavailable", "reason": "missing_leg_quote_history"}
    replay_end = min(audit["end"], min(available_ends))
    target = entry_credit * (1.0 - audit["profit_pct"])
    stop = entry_credit * (1.0 - audit["stop_pct"])
    complete_polls = 0
    rejection_counts: Counter[str] = Counter()
    for stamp in _session_poll_times(entry_at, replay_end, **schedule):
        snapshot, rejection = executable_snapshot(quote_index, symbols, stamp, config)
        if rejection:
            rejection_counts[rejection] += 1
            continue
        debit = executable_close_debit(_snapshot_legs(candidate, snapshot or {}))
        if debit is None:
            rejection_counts["invalid_close_debit"] += 1
            continue
        complete_polls += 1
        reason = "profit_target" if debit <= target else "stop" if debit >= stop else None
        if reason:
            return {
                "status": "resolved",
                "reason": reason,
                "resolved_at": _iso(stamp),
                "closing_debit": round(debit, 6),
                "complete_poll_count": complete_polls,
                "quote_rejections": dict(rejection_counts),
            }
    return {
        "status": "open_through_available_data",
        "available_through": _iso(replay_end),
        "complete_poll_count": complete_polls,
        "quote_rejections": dict(rejection_counts),
    }


def replay_candidate(
    candidate: dict[str, Any],
    quote_index: dict[str, list[dict[str, Any]]],
    config: OptionsNbboConfig = OptionsNbboConfig(),
) -> dict[str, Any]:
    candidate_id = str(candidate.get("candidate_id") or candidate.get("id") or "unknown")
    base = {"candidate_id": candidate_id, "strategy": candidate.get("strategy"), "status": "unavailable"}
    audit, error = _candidate_audit(candidate)
    if error or audit is None:
        return {**base, "reason": error}
    symbols = audit["symbols"]
    event_times = {audit["created"], audit["end"]}
    for symbol in symbols:
        event_times.update(
            row["observed_at"] for row in quote_index.get(symbol, [])
            if audit["created"] <= row["observed_at"] <= audit["end"]
        )
    ordered_times = sorted(event_times)
    entry = None
    entry_at = None
    rejection_counts: Counter[str] = Counter()
    entry_deadline = min(audit["end"], audit["created"] + timedelta(seconds=config.max_entry_delay_seconds))
    for stamp in ordered_times:
        if stamp < audit["created"] or stamp > entry_deadline:
            continue
        snapshot, rejection = executable_snapshot(quote_index, symbols, stamp, config)
        if rejection:
            rejection_counts[rejection] += 1
            continue
        legs = _snapshot_legs(candidate, snapshot or {})
        credit = executable_entry_credit(legs)
        if credit is not None and credit > 0:
            entry = credit
            entry_at = stamp
            break
        rejection_counts["non_credit_entry"] += 1
    if entry is None or entry_at is None:
        reason = rejection_counts.most_common(1)[0][0] if rejection_counts else "no_complete_entry_snapshot"
        return {**base, "reason": reason, "quote_rejections": dict(rejection_counts)}

    target = entry * (1.0 - audit["profit_pct"])
    stop = entry * (1.0 - audit["stop_pct"])
    closing = None
    resolved_at = None
    exit_reason = None
    for stamp in ordered_times:
        if stamp <= entry_at or stamp > audit["end"]:
            continue
        snapshot, rejection = executable_snapshot(quote_index, symbols, stamp, config)
        if rejection:
            rejection_counts[rejection] += 1
            continue
        debit = executable_close_debit(_snapshot_legs(candidate, snapshot or {}))
        if debit is None:
            rejection_counts["invalid_close_debit"] += 1
            continue
        if debit <= target:
            closing, resolved_at, exit_reason = debit, stamp, "profit_target"
            break
        if debit >= stop:
            closing, resolved_at, exit_reason = debit, stamp, "stop"
            break
        if stamp == audit["end"]:
            closing, resolved_at, exit_reason = debit, stamp, "evaluation_end"
            break
    if closing is None or resolved_at is None:
        reason = "no_complete_exit_snapshot"
        if rejection_counts:
            reason = rejection_counts.most_common(1)[0][0]
        return {
            **base,
            "reason": reason,
            "entry_at": _iso(entry_at),
            "entry_credit": entry,
            "quote_rejections": dict(rejection_counts),
        }

    leg_units = sum(max(1, int(_number(leg.get("ratio_qty")) or 1)) for leg in candidate.get("legs") or [])
    base_fees = config.fee_per_contract_leg_side * 2 * leg_units * audit["qty"]
    gross = (entry - closing) * 100.0 * audit["qty"]
    max_risk_total = audit["max_risk"] * audit["qty"]
    pnl_base = gross - base_fees
    pnl_double = gross - 2 * base_fees
    pnl_triple = gross - 3 * base_fees
    cadence_sensitivity = {
        name: _polling_replay(
            candidate,
            quote_index,
            audit,
            entry_at,
            entry,
            config,
            schedule,
        )
        for name, schedule in POLLING_SCHEDULES.items()
    }
    return {
        **base,
        "status": "resolved",
        "reason": exit_reason,
        "candidate_at": _iso(audit["created"]),
        "contract_selected_at": _iso(audit["selected"]),
        "entry_at": _iso(entry_at),
        "resolved_at": _iso(resolved_at),
        "entry_delay_seconds": round((entry_at - audit["created"]).total_seconds(), 6),
        "entry_credit": round(entry, 6),
        "closing_debit": round(closing, 6),
        "quantity": audit["qty"],
        "max_risk_total": round(max_risk_total, 2),
        "gross_pnl_before_fees": round(gross, 2),
        "base_fees": round(base_fees, 2),
        "pnl_base": round(pnl_base, 2),
        "pnl_double_fees": round(pnl_double, 2),
        "pnl_triple_fees": round(pnl_triple, 2),
        "return_on_risk_pct": round(pnl_base / max_risk_total * 100.0, 6),
        "monitoring_cadence_sensitivity": cadence_sensitivity,
        "quote_rejections": dict(rejection_counts),
        "lookahead_violation": False,
    }


def _trim_top(values: list[float], fraction: float = 0.05) -> list[float]:
    if not values:
        return []
    return sorted(values)[:-max(1, math.ceil(len(values) * fraction))]


def _metrics(rows: list[dict[str, Any]], field: str) -> dict[str, Any]:
    values = [float(row[field]) for row in rows]
    if not values:
        return {"count": 0, "expectancy_dollars": None, "win_rate": None, "profit_factor": None, "max_drawdown_dollars": None, "top5_removed_expectancy_dollars": None}
    winners = [value for value in values if value > 0]
    losers = [-value for value in values if value < 0]
    equity = peak = drawdown = 0.0
    for value in values:
        equity += value
        peak = max(peak, equity)
        drawdown = max(drawdown, peak - equity)
    trimmed = _trim_top(values)
    return {
        "count": len(values),
        "expectancy_dollars": round(sum(values) / len(values), 4),
        "win_rate": round(len(winners) / len(values), 4),
        "profit_factor": round(sum(winners) / sum(losers), 4) if losers else (None if not winners else "inf"),
        "max_drawdown_dollars": round(drawdown, 4),
        "top5_removed_expectancy_dollars": round(sum(trimmed) / len(trimmed), 4) if trimmed else None,
    }


def _summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    ordered = sorted(rows, key=lambda row: str(row.get("candidate_at") or ""))
    return {
        "base": _metrics(ordered, "pnl_base"),
        "double_fees": _metrics(ordered, "pnl_double_fees"),
        "triple_fees": _metrics(ordered, "pnl_triple_fees"),
        "by_strategy": {
            strategy: {
                "base": _metrics([row for row in ordered if row.get("strategy") == strategy], "pnl_base"),
                "double_fees": _metrics([row for row in ordered if row.get("strategy") == strategy], "pnl_double_fees"),
            }
            for strategy in sorted({str(row.get("strategy")) for row in ordered})
        },
    }


def _chronological_blocks(rows: list[dict[str, Any]], count: int) -> list[dict[str, Any]]:
    if not rows:
        return []
    ordered = sorted(rows, key=lambda row: str(row.get("candidate_at") or ""))
    size = max(1, math.ceil(len(ordered) / count))
    blocks = []
    for start in range(0, len(ordered), size):
        chunk = ordered[start:start + size]
        blocks.append({
            "block": len(blocks) + 1,
            "start": chunk[0]["candidate_at"],
            "end": chunk[-1]["candidate_at"],
            "result": _summary(chunk),
        })
    return blocks


def run_curriculum(
    candidates: Iterable[dict[str, Any]],
    quotes: Iterable[dict[str, Any]],
    config: OptionsNbboConfig = OptionsNbboConfig(),
) -> dict[str, Any]:
    candidate_rows = [row for row in candidates if row.get("type") in (None, "candidate")]
    normalized_quotes = normalize_quote_rows(quotes)
    quote_index = build_quote_index(normalized_quotes)
    outcomes = [replay_candidate(row, quote_index, config) for row in candidate_rows]
    resolved = [row for row in outcomes if row.get("status") == "resolved"]
    dates = sorted({str((_parse_ts(row.get("created_at") or row.get("decision_at")) or datetime.min.replace(tzinfo=timezone.utc)).date()) for row in candidate_rows})
    holdout_date_count = max(1, math.ceil(len(dates) * config.locked_holdout_fraction)) if dates else 0
    holdout_dates = set(dates[-holdout_date_count:]) if holdout_date_count else set()
    development = [row for row in resolved if str(_parse_ts(row["candidate_at"]).date()) not in holdout_dates]
    holdout = [row for row in resolved if str(_parse_ts(row["candidate_at"]).date()) in holdout_dates]
    blocks = _chronological_blocks(development, config.chronological_blocks)
    development_summary = _summary(development)
    holdout_summary = _summary(holdout)
    profitable_blocks = sum((block["result"]["base"]["expectancy_dollars"] or 0.0) > 0 for block in blocks)
    profitable_block_rate = profitable_blocks / len(blocks) if blocks else 0.0
    rejection_counts: Counter[str] = Counter(
        str(row.get("reason") or "unknown") for row in outcomes if row.get("status") != "resolved"
    )
    lifecycle_coverage = len(resolved) / len(candidate_rows) if candidate_rows else 0.0
    accepted_quote_count = sum(row.get("scope") in ACCEPTED_NBBO_SCOPES for row in normalized_quotes)
    scope_counts = Counter(str(row.get("scope") or "unknown") for row in normalized_quotes)
    lookahead_violations = sum(
        row.get("reason") == "lookahead_quote"
        or _number((row.get("quote_rejections") or {}).get("lookahead_quote", 0)) > 0
        for row in outcomes
    )
    selection_failures = sum(row.get("reason") == "contract_selection_not_point_in_time" for row in outcomes)
    checks = {
        "minimum_resolved": len(resolved) >= config.minimum_review_resolved,
        "minimum_lifecycle_coverage": lifecycle_coverage >= config.minimum_lifecycle_coverage,
        "minimum_chronological_blocks": len(blocks) >= config.minimum_review_blocks,
        "profitable_block_rate": profitable_block_rate >= config.minimum_profitable_block_rate,
        "development_base_positive": (development_summary["base"]["expectancy_dollars"] or 0.0) > 0,
        "development_double_fees_positive": (development_summary["double_fees"]["expectancy_dollars"] or 0.0) > 0,
        "development_top5_removed_positive": (development_summary["base"]["top5_removed_expectancy_dollars"] or 0.0) > 0,
        "minimum_holdout_resolved": len(holdout) >= config.minimum_holdout_resolved,
        "holdout_base_positive": (holdout_summary["base"]["expectancy_dollars"] or 0.0) > 0,
        "holdout_double_fees_positive": (holdout_summary["double_fees"]["expectancy_dollars"] or 0.0) > 0,
        "all_quote_inputs_nbbo": bool(normalized_quotes) and accepted_quote_count == len(normalized_quotes),
        "no_lookahead_violations": lookahead_violations == 0,
        "contract_selection_audit_complete": selection_failures == 0,
    }
    passed = all(checks.values())
    cadence_sensitivity = {
        name: {
            "interval_seconds": schedule["interval_seconds"],
            "resolved_count": sum(
                (row.get("monitoring_cadence_sensitivity") or {}).get(name, {}).get("status") == "resolved"
                for row in resolved
            ),
            "profit_target_count": sum(
                (row.get("monitoring_cadence_sensitivity") or {}).get(name, {}).get("reason") == "profit_target"
                for row in resolved
            ),
            "stop_count": sum(
                (row.get("monitoring_cadence_sensitivity") or {}).get(name, {}).get("reason") == "stop"
                for row in resolved
            ),
        }
        for name, schedule in POLLING_SCHEDULES.items()
    }
    return {
        "provider": "options_nbbo_curriculum",
        "schema_version": 1,
        "mode": "read_only_historical_executable_quote_replay",
        "execution_enabled": False,
        "can_submit_orders": False,
        "promotion_authority": "human_review_only" if passed else "blocked",
        "status": "review_gate_passed" if passed else ("coverage_unavailable" if not resolved else "review_gate_failed"),
        "config": asdict(config),
        "execution_model": {
            "entry": "sell_bid_buy_ask",
            "exit": "buy_short_ask_sell_long_bid",
            "midpoint_fills_allowed": False,
            "underlying_return_substitution_allowed": False,
            "option_bar_spread_proxy_allowed": False,
            "fees": "per_contract_per_leg_per_side",
        },
        "candidate_count": len(candidate_rows),
        "resolved_count": len(resolved),
        "lifecycle_coverage": round(lifecycle_coverage, 4),
        "quote_observation_count": len(normalized_quotes),
        "accepted_nbbo_quote_count": accepted_quote_count,
        "quote_scope_counts": dict(sorted(scope_counts.items())),
        "unavailable_reason_counts": dict(sorted(rejection_counts.items())),
        "contract_selection_audit": {
            "method": "concrete_occ_legs_frozen_at_or_before_candidate_timestamp",
            "failure_count": selection_failures,
        },
        "lookahead_audit": {"violation_count": lookahead_violations, "passed": lookahead_violations == 0},
        "monitoring_cadence_sensitivity": {
            "method": "scheduled_observation_only_not_resting_limit_order_or_fill_claim",
            "schedules": cadence_sensitivity,
        },
        "development": {
            "candidate_date_count": len(set(dates) - holdout_dates),
            "resolved_count": len(development),
            "summary": development_summary,
            "chronological_blocks": blocks,
            "profitable_block_count": profitable_blocks,
            "profitable_block_rate": round(profitable_block_rate, 4),
        },
        "locked_holdout": {
            "candidate_date_count": len(holdout_dates),
            "dates": sorted(holdout_dates),
            "resolved_count": len(holdout),
            "summary": holdout_summary,
        },
        "review_gate": {"passed": passed, "checks": checks},
        "outcomes": outcomes,
        "warnings": [
            "This report cannot submit orders, alter thresholds, change sizing, or promote a strategy.",
            "Indicative or modified quotes are diagnostics only and cannot satisfy the NBBO evidence gate.",
            "Missing option quotes are unavailable; underlying returns, trades, bars, and midpoint fills are never substituted.",
            "A passing historical replay permits human review only and still requires forward broker-fill evidence.",
        ],
    }


def _sha256(path: Path) -> str | None:
    if not path.exists():
        return None
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(payload, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")
    os.replace(temp, path)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidates", type=Path, default=DEFAULT_CANDIDATES_PATH)
    parser.add_argument("--quotes", type=Path, default=DEFAULT_QUOTES_PATH)
    parser.add_argument("--output", type=Path, default=OUTPUT_PATH)
    parser.add_argument("--print", action="store_true", dest="print_report")
    args = parser.parse_args()
    candidate_rows = _read_rows(args.candidates)
    quote_rows = candidate_rows if args.quotes.resolve() == args.candidates.resolve() else _read_rows(args.quotes)
    report = run_curriculum(candidate_rows, quote_rows)
    report["datasets"] = {
        "candidates": {"path": str(args.candidates), "sha256": _sha256(args.candidates)},
        "quotes": {"path": str(args.quotes), "sha256": _sha256(args.quotes)},
    }
    _write_json(args.output, report)
    if args.print_report:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        print(
            f"candidates={report['candidate_count']} resolved={report['resolved_count']} "
            f"coverage={report['lifecycle_coverage']:.1%} status={report['status']} "
            f"gate={report['review_gate']['passed']}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

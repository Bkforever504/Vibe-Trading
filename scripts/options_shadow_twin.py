#!/usr/bin/env python3
"""Forward-only counterfactual lifecycle for multi-leg options candidates.

This module is telemetry and governance only. It has no broker trading imports
and cannot submit, replace, or cancel orders.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import sys
import threading
from datetime import date, datetime, time, timezone
from pathlib import Path
from statistics import mean
from typing import Any, Callable, Iterable, Optional
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from scripts.point_in_time_quotes import (
    ALPACA_OPTIONS_FEED,
    ALPACA_OPTIONS_SNAPSHOT_URL,
    parse_alpaca_option_snapshot,
)


VIBE_HOME = Path.home() / ".vibe-trading"
DEFAULT_LOG_PATH = ROOT / "data" / "options_shadow_twin_log.jsonl"
DEFAULT_REPORT_PATH = VIBE_HOME / "reports" / "options-shadow-twin.json"
ENV_PATH = ROOT / "agent" / ".env"
NY = ZoneInfo("America/New_York")
SCHEMA_VERSION = 1
SUPPORTED_STRATEGIES = {"put_spread", "call_spread", "iron_condor"}
_APPEND_LOCK = threading.Lock()


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _parse_ts(value: Any) -> Optional[datetime]:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _number(value: Any) -> Optional[float]:
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    return out if math.isfinite(out) else None


def _load_env(path: Path = ENV_PATH) -> None:
    if not path.exists():
        return
    for raw in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip("\"'"))


def _headers() -> dict[str, str]:
    _load_env()
    return {
        "APCA-API-KEY-ID": os.getenv("ALPACA_API_KEY", ""),
        "APCA-API-SECRET-KEY": os.getenv("ALPACA_SECRET_KEY", ""),
    }


def _valid_market(bid: Any, ask: Any) -> bool:
    bid_n = _number(bid)
    ask_n = _number(ask)
    return bool(bid_n is not None and ask_n is not None and bid_n > 0 and ask_n >= bid_n)


def executable_entry_credit(legs: Iterable[dict[str, Any]]) -> Optional[float]:
    """Credit using sell-at-bid and buy-at-ask executable sides."""
    total = 0.0
    found = False
    for leg in legs:
        if not _valid_market(leg.get("bid"), leg.get("ask")):
            return None
        ratio = max(1, int(_number(leg.get("ratio_qty")) or 1))
        side = str(leg.get("side") or "").lower()
        if side == "sell":
            total += float(leg["bid"]) * ratio
        elif side == "buy":
            total -= float(leg["ask"]) * ratio
        else:
            return None
        found = True
    return round(total, 4) if found and total > 0 else None


def executable_close_debit(legs: Iterable[dict[str, Any]]) -> Optional[float]:
    """Debit using buy-short-at-ask and sell-long-at-bid executable sides."""
    total = 0.0
    found = False
    for leg in legs:
        if not _valid_market(leg.get("bid"), leg.get("ask")):
            return None
        ratio = max(1, int(_number(leg.get("ratio_qty")) or 1))
        side = str(leg.get("side") or "").lower()
        if side == "sell":
            total += float(leg["ask"]) * ratio
        elif side == "buy":
            total -= float(leg["bid"]) * ratio
        else:
            return None
        found = True
    return round(max(0.0, total), 4) if found else None


def _candidate_fingerprint(strategy: str, underlying: str, legs: list[dict[str, Any]]) -> str:
    structure = [
        {
            "symbol": str(leg.get("symbol") or ""),
            "side": str(leg.get("side") or "").lower(),
            "ratio_qty": int(_number(leg.get("ratio_qty")) or 1),
        }
        for leg in legs
    ]
    payload = json.dumps(
        {"strategy": strategy, "underlying": underlying, "legs": structure},
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _append(record: dict[str, Any], path: Path = DEFAULT_LOG_PATH) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with _APPEND_LOCK:
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, sort_keys=True, separators=(",", ":"), allow_nan=False) + "\n")


def read_records(path: Path = DEFAULT_LOG_PATH) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    records: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(row, dict):
            records.append(row)
    return records


def _recent_duplicate(
    records: Iterable[dict[str, Any]],
    fingerprint: str,
    now: datetime,
    seconds: int = 300,
) -> Optional[str]:
    for row in reversed(list(records)):
        if row.get("type") != "candidate" or row.get("fingerprint") != fingerprint:
            continue
        created = _parse_ts(row.get("created_at"))
        if created and 0 <= (now - created).total_seconds() <= seconds:
            return str(row.get("candidate_id") or "") or None
        return None
    return None


def record_candidate(
    trade_meta: dict[str, Any],
    legs_payload: list[dict[str, Any]],
    *,
    consensus: Optional[dict[str, Any]] = None,
    effective_qty: Optional[int] = None,
    path: Path = DEFAULT_LOG_PATH,
    now: Optional[datetime] = None,
) -> Optional[str]:
    """Persist a fully formed candidate and return its ID; never raises."""
    try:
        if os.getenv("PYTEST_CURRENT_TEST") and Path(path) == DEFAULT_LOG_PATH:
            return None
        now = now or _utc_now()
        strategy = str(trade_meta.get("strategy") or "")
        underlying = str(trade_meta.get("underlying") or "")
        if strategy not in SUPPORTED_STRATEGIES or not underlying:
            return None
        snapshots_by_symbol = {
            str(row.get("symbol")): row
            for row in (trade_meta.get("leg_market_snapshots") or [])
            if isinstance(row, dict) and row.get("symbol")
        }
        legs: list[dict[str, Any]] = []
        for intent in legs_payload:
            symbol = str(intent.get("symbol") or "")
            market = snapshots_by_symbol.get(symbol, {})
            legs.append(
                {
                    "symbol": symbol,
                    "side": str(intent.get("side") or "").lower(),
                    "ratio_qty": int(_number(intent.get("ratio_qty")) or 1),
                    "position_intent": intent.get("position_intent"),
                    "bid": _number(market.get("bid")),
                    "ask": _number(market.get("ask")),
                    "mid": _number(market.get("mid")),
                    "delta": _number(market.get("delta")),
                    "strike": _number(market.get("strike")),
                    "right": market.get("right"),
                    "expiry": str(market.get("expiry") or trade_meta.get("expiry") or ""),
                }
            )
        fingerprint = _candidate_fingerprint(strategy, underlying, legs)
        existing = _recent_duplicate(read_records(path), fingerprint, now)
        if existing:
            return existing
        created_at = _iso(now)
        candidate_id = hashlib.sha256(f"{created_at}|{fingerprint}".encode("utf-8")).hexdigest()[:24]
        entry_credit = executable_entry_credit(legs)
        confidence = trade_meta.get("candidate_confidence")
        record = {
            "schema_version": SCHEMA_VERSION,
            "type": "candidate",
            "candidate_id": candidate_id,
            "fingerprint": fingerprint,
            "created_at": created_at,
            "strategy": strategy,
            "underlying": underlying,
            "expiry": str(trade_meta.get("expiry") or ""),
            "original_qty": int(_number(trade_meta.get("qty")) or 0),
            "effective_qty": int(effective_qty or _number(trade_meta.get("qty")) or 0),
            "quoted_mid_credit": _number(trade_meta.get("net_credit")),
            "executable_entry_credit": entry_credit,
            "entry_quote_complete": entry_credit is not None,
            "max_risk_per_contract": _number(trade_meta.get("max_risk_per_contract")),
            "profit_close_pct": _number(trade_meta.get("profit_close_pct")),
            "stop_loss_pct": _number(trade_meta.get("stop_loss_pct")),
            "candidate_confidence": confidence if isinstance(confidence, dict) else {},
            "shadow_consensus": consensus if isinstance(consensus, dict) else {},
            "vix_at_entry": _number(trade_meta.get("vix_at_entry")),
            "vix_term_ratio": _number(trade_meta.get("vix_term_ratio")),
            "iv_rank_at_entry": _number(trade_meta.get("iv_rank_at_entry")),
            "legs": legs,
            "quote_scope": "alpaca_indicative_modified_not_opra_nbbo",
            "execution_enabled": False,
            "can_submit_orders": False,
        }
        _append(record, path)
        return candidate_id
    except Exception:
        return None


def record_decision(
    candidate_id: Optional[str],
    decision: str,
    *,
    details: Optional[dict[str, Any]] = None,
    path: Path = DEFAULT_LOG_PATH,
    now: Optional[datetime] = None,
) -> None:
    """Append the candidate decision; telemetry failure never affects trading."""
    if not candidate_id:
        return
    try:
        _append(
            {
                "schema_version": SCHEMA_VERSION,
                "type": "decision",
                "candidate_id": candidate_id,
                "decided_at": _iso(now or _utc_now()),
                "decision": decision,
                "details": details or {},
                "execution_enabled": False,
                "can_submit_orders": False,
            },
            path,
        )
    except Exception:
        return


def _index(records: Iterable[dict[str, Any]]) -> tuple[dict[str, dict], dict[str, dict], dict[str, dict]]:
    candidates: dict[str, dict] = {}
    decisions: dict[str, dict] = {}
    outcomes: dict[str, dict] = {}
    for row in records:
        candidate_id = str(row.get("candidate_id") or "")
        if not candidate_id:
            continue
        if row.get("type") == "candidate":
            candidates[candidate_id] = row
        elif row.get("type") == "decision":
            decisions[candidate_id] = row
        elif row.get("type") == "outcome":
            outcomes[candidate_id] = row
    return candidates, decisions, outcomes


def _default_quote_map(candidates: Iterable[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Fetch current option snapshots in batches, never one request per leg."""
    import requests

    headers = _headers()
    symbols = sorted({
        str(leg.get("symbol") or "")
        for candidate in candidates
        for leg in (candidate.get("legs") or [])
        if leg.get("symbol")
    })
    if not symbols or not all(headers.values()):
        return {}
    captured_at = _utc_now()
    records: dict[str, dict[str, Any]] = {}
    for start in range(0, len(symbols), 100):
        chunk = symbols[start:start + 100]
        try:
            response = requests.get(
                ALPACA_OPTIONS_SNAPSHOT_URL,
                headers=headers,
                params={"symbols": ",".join(chunk), "feed": ALPACA_OPTIONS_FEED},
                timeout=15,
            )
            payload = response.json() if response.status_code == 200 else {}
        except Exception:
            payload = {}
        for symbol in chunk:
            parsed = parse_alpaca_option_snapshot(symbol, payload, captured_at)
            records[symbol] = {
                "quote": parsed.get("quote"),
                "provenance": parsed.get("provenance"),
            }
    return records


def _expiry_close_due(candidate: dict[str, Any], now: datetime) -> bool:
    try:
        expiry = date.fromisoformat(str(candidate.get("expiry")))
    except ValueError:
        return False
    local = now.astimezone(NY)
    return local.date() >= expiry and local.time() >= time(15, 45)


def _candidate_exit_thresholds(candidate: dict[str, Any], entry_credit: float) -> tuple[float, float]:
    profit_pct = _number(candidate.get("profit_close_pct"))
    stop_pct = _number(candidate.get("stop_loss_pct"))
    profit_pct = min(1.0, max(0.0, profit_pct if profit_pct is not None else 0.50))
    stop_pct = min(0.0, stop_pct if stop_pct is not None else -1.0)
    target_debit = entry_credit * (1.0 - profit_pct)
    stop_debit = entry_credit * (1.0 - stop_pct)
    return target_debit, stop_debit


def _pct_reason(prefix: str, value: Any) -> str:
    parsed = abs(_number(value) or 0.0) * 100
    rendered = str(int(parsed)) if parsed.is_integer() else f"{parsed:.1f}".rstrip("0").rstrip(".")
    return f"{prefix}_{rendered}pct_credit"


def mark_open_candidates(
    *,
    path: Path = DEFAULT_LOG_PATH,
    quote_fetcher_factory: Optional[Callable[[str, str], Callable[[str], Optional[dict]]]] = None,
    now: Optional[datetime] = None,
) -> dict[str, int]:
    """Mark every unresolved candidate and append outcomes at frozen exits."""
    now = now or _utc_now()
    records = read_records(path)
    candidates, _, outcomes = _index(records)
    stats = {"open": 0, "marked": 0, "quote_incomplete": 0, "resolved": 0}
    unresolved = [
        candidate for candidate_id, candidate in candidates.items()
        if candidate_id not in outcomes
        and _number(candidate.get("executable_entry_credit"))
        and int(_number(candidate.get("effective_qty")) or 0) > 0
    ]
    default_quotes = _default_quote_map(unresolved) if quote_fetcher_factory is None else {}
    for candidate_id, candidate in candidates.items():
        if candidate_id in outcomes:
            continue
        stats["open"] += 1
        entry_credit = _number(candidate.get("executable_entry_credit"))
        qty = int(_number(candidate.get("effective_qty")) or 0)
        if entry_credit is None or entry_credit <= 0 or qty <= 0:
            stats["quote_incomplete"] += 1
            continue
        if quote_fetcher_factory is None:
            fetcher = lambda symbol: default_quotes.get(symbol)
        else:
            fetcher = quote_fetcher_factory(candidate_id, str(candidate.get("underlying") or ""))
        marked_legs: list[dict[str, Any]] = []
        for leg in candidate.get("legs") or []:
            sample = fetcher(str(leg.get("symbol") or ""))
            quote = sample.get("quote") if isinstance(sample, dict) else None
            marked_legs.append(
                {
                    "symbol": leg.get("symbol"),
                    "side": leg.get("side"),
                    "ratio_qty": leg.get("ratio_qty"),
                    "bid": _number((quote or {}).get("bid")),
                    "ask": _number((quote or {}).get("ask")),
                    "quote_timestamp": (quote or {}).get("quote_timestamp"),
                    "quote_age_seconds": _number((quote or {}).get("quote_age_seconds")),
                    "provenance_status": ((sample or {}).get("provenance") or {}).get("status")
                    if isinstance(sample, dict)
                    else "unavailable",
                }
            )
        close_debit = executable_close_debit(marked_legs)
        quote_complete = close_debit is not None
        mark = {
            "schema_version": SCHEMA_VERSION,
            "type": "mark",
            "candidate_id": candidate_id,
            "marked_at": _iso(now),
            "quote_complete": quote_complete,
            "executable_close_debit": close_debit,
            "legs": marked_legs,
            "quote_scope": "alpaca_indicative_modified_not_opra_nbbo",
            "execution_enabled": False,
            "can_submit_orders": False,
        }
        _append(mark, path)
        stats["marked"] += 1
        if not quote_complete:
            stats["quote_incomplete"] += 1
            continue
        reason = None
        target_debit, stop_debit = _candidate_exit_thresholds(candidate, entry_credit)
        if close_debit <= target_debit:
            reason = _pct_reason("profit_target", candidate.get("profit_close_pct") or 0.50)
        elif close_debit >= stop_debit:
            reason = _pct_reason("stop", candidate.get("stop_loss_pct") or -1.0)
        elif _expiry_close_due(candidate, now):
            reason = "expiration_hard_close"
        if reason:
            pnl = round((entry_credit - close_debit) * 100 * qty, 2)
            _append(
                {
                    "schema_version": SCHEMA_VERSION,
                    "type": "outcome",
                    "candidate_id": candidate_id,
                    "resolved_at": _iso(now),
                    "reason": reason,
                    "entry_credit": entry_credit,
                    "closing_debit": close_debit,
                    "quantity": qty,
                    "pnl_before_fees": pnl,
                    "win": pnl > 0,
                    "fees_included": False,
                    "execution_enabled": False,
                    "can_submit_orders": False,
                },
                path,
            )
            stats["resolved"] += 1
    return stats


def wilson_interval(wins: int, total: int, z: float = 1.959963984540054) -> tuple[Optional[float], Optional[float]]:
    if total <= 0:
        return None, None
    p = wins / total
    denominator = 1 + z * z / total
    centre = p + z * z / (2 * total)
    margin = z * math.sqrt((p * (1 - p) + z * z / (4 * total)) / total)
    return max(0.0, (centre - margin) / denominator), min(1.0, (centre + margin) / denominator)


def _profit_factor(pnls: list[float]) -> Optional[float]:
    gross_profit = sum(value for value in pnls if value > 0)
    gross_loss = abs(sum(value for value in pnls if value < 0))
    if gross_loss == 0:
        return None if gross_profit == 0 else float("inf")
    return gross_profit / gross_loss


def _calibration(candidates: dict[str, dict], outcomes: dict[str, dict]) -> dict[str, Any]:
    pairs: list[tuple[float, float]] = []
    for candidate_id, outcome in outcomes.items():
        confidence = candidates.get(candidate_id, {}).get("candidate_confidence") or {}
        score = _number(confidence.get("score")) if isinstance(confidence, dict) else None
        if score is not None:
            pairs.append((max(0.0, min(1.0, score / 10.0)), 1.0 if outcome.get("win") else 0.0))
    if not pairs:
        return {"count": 0, "status": "insufficient_n", "brier": None, "constant_brier": None, "skill": None}
    actual_rate = mean(actual for _, actual in pairs)
    brier = mean((forecast - actual) ** 2 for forecast, actual in pairs)
    constant = mean((actual_rate - actual) ** 2 for _, actual in pairs)
    skill = None if constant == 0 else 1 - brier / constant
    return {
        "count": len(pairs),
        "status": "ok" if len(pairs) >= 30 else "insufficient_n",
        "brier": round(brier, 6),
        "constant_brier": round(constant, 6),
        "skill": round(skill, 6) if skill is not None else None,
    }


def _execution_cost_quality(candidate_rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Measure how much entry credit disappears from mid to executable quotes."""
    mid_rows = [
        row for row in candidate_rows
        if (_number(row.get("quoted_mid_credit")) or 0.0) > 0
    ]
    paired: list[dict[str, float]] = []
    for row in mid_rows:
        mid_credit = _number(row.get("quoted_mid_credit"))
        executable_credit = _number(row.get("executable_entry_credit"))
        if mid_credit is None or mid_credit <= 0 or executable_credit is None:
            continue
        edge_loss = max(0.0, mid_credit - executable_credit)
        paired.append(
            {
                "mid_credit": mid_credit,
                "executable_credit": executable_credit,
                "edge_loss": edge_loss,
                "edge_loss_pct_of_mid": edge_loss / mid_credit,
            }
        )
    coverage = len(paired) / len(mid_rows) if mid_rows else 0.0
    avg_loss = mean(item["edge_loss"] for item in paired) if paired else None
    avg_loss_pct = mean(item["edge_loss_pct_of_mid"] for item in paired) if paired else None
    worst_loss_pct = max((item["edge_loss_pct_of_mid"] for item in paired), default=None)
    blockers: list[str] = []
    status = "no_mid_quotes"
    if mid_rows:
        status = "ok"
        if coverage < 0.8:
            status = "incomplete_quote_coverage"
            blockers.append("Executable bid/ask entry coverage below 80%.")
        if avg_loss_pct is not None and avg_loss_pct > 0.15:
            status = "high_execution_friction"
            blockers.append("Average midpoint-to-executable credit loss exceeds 15%.")
        elif avg_loss_pct is not None and avg_loss_pct > 0.05 and status == "ok":
            status = "watch_execution_friction"
    return {
        "status": status,
        "candidate_count": len(candidate_rows),
        "mid_credit_candidate_count": len(mid_rows),
        "paired_mid_to_executable_count": len(paired),
        "paired_coverage": round(coverage, 4),
        "avg_entry_edge_loss_credit": round(avg_loss, 4) if avg_loss is not None else None,
        "avg_entry_edge_loss_pct_of_mid": round(avg_loss_pct, 4) if avg_loss_pct is not None else None,
        "worst_entry_edge_loss_pct_of_mid": round(worst_loss_pct, 4) if worst_loss_pct is not None else None,
        "benchmark": "arrival_mid_credit_vs_sell_bid_buy_ask_executable_entry_credit",
        "authority": "shadow_governance_only",
        "blockers": blockers,
    }


def _earned_confidence(
    candidate_count: int,
    resolved_count: int,
    distinct_dates: int,
    entry_coverage: float,
    mark_coverage: float,
    expectancy: Optional[float],
    profit_factor: Optional[float],
    calibration: dict[str, Any],
) -> dict[str, Any]:
    data_integrity = min(2.0, entry_coverage + mark_coverage)
    sample_support = min(2.0, resolved_count / 30 + distinct_dates / 20)
    calibration_score = 0.0
    if calibration.get("count", 0) >= 30:
        skill = _number(calibration.get("skill"))
        calibration_score = 2.0 if skill is not None and skill > 0 else 0.5
    expectancy_score = 0.0
    if resolved_count:
        expectancy_score += 0.5 if expectancy is not None and expectancy > 0 else 0.0
        expectancy_score += 0.5 if profit_factor is not None and profit_factor > 1 else 0.0
        if resolved_count >= 30 and expectancy_score == 1.0:
            expectancy_score = 2.0
    execution_fidelity = 1.0 if candidate_count and entry_coverage >= 0.8 and mark_coverage >= 0.8 else 0.5 if candidate_count else 0.0
    components = {
        "data_integrity": round(data_integrity, 2),
        "independent_sample_support": round(sample_support, 2),
        "calibration": round(calibration_score, 2),
        "expectancy_robustness": round(expectancy_score, 2),
        "execution_fidelity": round(execution_fidelity, 2),
    }
    raw = sum(components.values())
    cap = 8.0
    blockers: list[str] = ["OPRA NBBO history or equivalent executable quote evidence is required above 8/10."]
    if resolved_count < 10:
        cap = min(cap, 3.0)
        blockers.append(f"Resolve at least 10 candidates; current={resolved_count}.")
    elif resolved_count < 30 or distinct_dates < 20:
        cap = min(cap, 5.0)
        blockers.append(f"Reach 30 resolved candidates across 20 dates; current={resolved_count}/{distinct_dates}.")
    if expectancy is not None and expectancy < 0:
        cap = min(cap, 3.0)
        blockers.append("Conservative expectancy is negative.")
    if entry_coverage < 0.8 or mark_coverage < 0.8:
        cap = min(cap, 4.0)
        blockers.append("Executable-side quote coverage must reach 80% for entries and marks.")
    if calibration.get("count", 0) >= 30 and (_number(calibration.get("skill")) or 0) <= 0:
        cap = min(cap, 6.0)
        blockers.append("Candidate confidence does not beat a constant base-rate forecast.")
    score = round(min(raw, cap), 2)
    return {"score": score, "raw_score": round(raw, 2), "evidence_cap": cap, "components": components, "blockers": blockers}


def build_report(records: Iterable[dict[str, Any]], now: Optional[datetime] = None) -> dict[str, Any]:
    rows = list(records)
    candidates, decisions, outcomes = _index(rows)
    marks = [row for row in rows if row.get("type") == "mark"]
    candidate_rows = list(candidates.values())
    outcome_rows = list(outcomes.values())
    pnls = [float(row["pnl_before_fees"]) for row in outcome_rows if _number(row.get("pnl_before_fees")) is not None]
    wins = sum(1 for value in pnls if value > 0)
    lower, upper = wilson_interval(wins, len(pnls))
    entry_complete = sum(1 for row in candidate_rows if row.get("entry_quote_complete") is True)
    mark_complete = sum(1 for row in marks if row.get("quote_complete") is True)
    entry_coverage = entry_complete / len(candidate_rows) if candidate_rows else 0.0
    mark_coverage = mark_complete / len(marks) if marks else 0.0
    distinct_dates = {
        parsed.astimezone(NY).date().isoformat()
        for parsed in (_parse_ts(row.get("created_at")) for row in candidate_rows)
        if parsed
    }
    expectancy = mean(pnls) if pnls else None
    profit_factor = _profit_factor(pnls)
    calibration = _calibration(candidates, outcomes)
    execution_cost_quality = _execution_cost_quality(candidate_rows)
    confidence = _earned_confidence(
        len(candidate_rows),
        len(pnls),
        len(distinct_dates),
        entry_coverage,
        mark_coverage,
        expectancy,
        profit_factor,
        calibration,
    )
    decisions_by_name: dict[str, int] = {}
    for row in decisions.values():
        name = str(row.get("decision") or "unknown")
        decisions_by_name[name] = decisions_by_name.get(name, 0) + 1
    return {
        "provider": "options_shadow_twin",
        "schema_version": SCHEMA_VERSION,
        "generated_at": _iso(now or _utc_now()),
        "mode": "forward_only_read_only_counterfactual",
        "execution_enabled": False,
        "can_submit_orders": False,
        "candidate_count": len(candidate_rows),
        "decision_count": len(decisions),
        "decisions": decisions_by_name,
        "resolved_count": len(pnls),
        "open_count": max(0, len(candidate_rows) - len(outcomes)),
        "distinct_candidate_dates": len(distinct_dates),
        "entry_quote_coverage": round(entry_coverage, 4),
        "mark_quote_coverage": round(mark_coverage, 4),
        "performance": {
            "net_pnl_before_fees": round(sum(pnls), 2),
            "expectancy_before_fees": round(expectancy, 2) if expectancy is not None else None,
            "profit_factor_before_fees": round(profit_factor, 4) if profit_factor is not None and math.isfinite(profit_factor) else profit_factor,
            "win_rate": round(wins / len(pnls), 4) if pnls else None,
            "win_rate_wilson_95": [
                round(lower, 4) if lower is not None else None,
                round(upper, 4) if upper is not None else None,
            ],
            "fees_included": False,
        },
        "calibration": calibration,
        "execution_cost_quality": execution_cost_quality,
        "earned_confidence": confidence,
        "promotion_eligible": False,
        "promotion_policy": "human_review_only_after_all_preregistered_gates",
        "warnings": [
            "Alpaca indicative modified quotes are not OPRA NBBO.",
            "P&L excludes fees until broker-verified multi-leg fee evidence is available.",
            "Blocked-versus-submitted results are descriptive, not causal.",
            "This report cannot place orders or change strategy settings.",
        ],
    }


def write_report(report: dict[str, Any], path: Path = DEFAULT_REPORT_PATH) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(report, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")
    os.replace(temp, path)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--log-path", type=Path, default=DEFAULT_LOG_PATH)
    parser.add_argument("--report-path", type=Path, default=DEFAULT_REPORT_PATH)
    parser.add_argument("--report-only", action="store_true")
    parser.add_argument("--print", action="store_true", dest="do_print")
    args = parser.parse_args()
    stats = {"open": 0, "marked": 0, "quote_incomplete": 0, "resolved": 0}
    if not args.report_only:
        stats = mark_open_candidates(path=args.log_path)
    report = build_report(read_records(args.log_path))
    report["run_stats"] = stats
    write_report(report, args.report_path)
    if args.do_print:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        print(
            f"Options shadow twin: candidates={report['candidate_count']} "
            f"resolved={report['resolved_count']} confidence={report['earned_confidence']['score']}/10"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

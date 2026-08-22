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
    option_quote_scope,
    parse_alpaca_option_snapshot,
)
from scripts.options_confluence import build_confluence_analysis
from scripts.probability_calibration import chronological_holdout, probability_metrics
from scripts.tradier_options_data import (
    fetch_quotes as fetch_tradier_quotes,
    quote_is_fresh as tradier_quote_is_fresh,
    tradier_selected,
)


VIBE_HOME = Path.home() / ".vibe-trading"
DEFAULT_LOG_PATH = ROOT / "data" / "options_shadow_twin_log.jsonl"
DEFAULT_REPORT_PATH = VIBE_HOME / "reports" / "options-shadow-twin.json"
ENV_PATH = ROOT / "agent" / ".env"
NY = ZoneInfo("America/New_York")
SCHEMA_VERSION = 2
SUPPORTED_STRATEGIES = {"put_spread", "call_spread", "iron_condor", "iron_fly"}
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


def midpoint_close_debit(legs: Iterable[dict[str, Any]]) -> Optional[float]:
    """Debit if closing each leg at mid price — the frictionless benchmark."""
    total = 0.0
    found = False
    for leg in legs:
        if not _valid_market(leg.get("bid"), leg.get("ask")):
            return None
        ratio = max(1, int(_number(leg.get("ratio_qty")) or 1))
        side = str(leg.get("side") or "").lower()
        mid = (float(leg["bid"]) + float(leg["ask"])) / 2
        if side == "sell":
            total += mid * ratio
        elif side == "buy":
            total -= mid * ratio
        else:
            return None
        found = True
    return round(max(0.0, total), 4) if found else None


def iron_fly_structure_metrics(legs: Iterable[dict[str, Any]]) -> Optional[dict[str, float]]:
    """Validate a symmetric short iron fly and derive its executable risk."""
    rows = list(legs)
    if len(rows) != 4:
        return None

    def right(row: dict[str, Any]) -> str:
        value = str(row.get("right") or "").strip().lower()
        return "put" if value in {"p", "put"} else "call" if value in {"c", "call"} else ""

    def pick(side: str, option_right: str) -> Optional[dict[str, Any]]:
        matches = [
            row for row in rows
            if str(row.get("side") or "").lower() == side and right(row) == option_right
        ]
        return matches[0] if len(matches) == 1 else None

    short_put = pick("sell", "put")
    short_call = pick("sell", "call")
    long_put = pick("buy", "put")
    long_call = pick("buy", "call")
    if not all((short_put, short_call, long_put, long_call)):
        return None
    expiries = {str(row.get("expiry") or "") for row in rows}
    if len(expiries) != 1 or not next(iter(expiries)):
        return None

    body_put = _number(short_put.get("strike"))
    body_call = _number(short_call.get("strike"))
    lower = _number(long_put.get("strike"))
    upper = _number(long_call.get("strike"))
    if None in {body_put, body_call, lower, upper}:
        return None
    if not math.isclose(body_put, body_call, rel_tol=0.0, abs_tol=1e-6):
        return None
    body = float(body_put)
    lower_width = body - float(lower)
    upper_width = float(upper) - body
    if lower_width <= 0 or not math.isclose(lower_width, upper_width, rel_tol=0.0, abs_tol=1e-6):
        return None

    entry_credit = executable_entry_credit(rows)
    if entry_credit is None or entry_credit <= 0 or entry_credit >= lower_width:
        return None
    return {
        "body_strike": round(body, 4),
        "lower_wing_strike": round(float(lower), 4),
        "upper_wing_strike": round(float(upper), 4),
        "wing_width": round(lower_width, 4),
        "executable_entry_credit": round(entry_credit, 4),
        "lower_breakeven_at_expiry": round(body - entry_credit, 4),
        "upper_breakeven_at_expiry": round(body + entry_credit, 4),
        "max_profit_per_contract": round(entry_credit * 100, 2),
        "max_risk_per_contract": round((lower_width - entry_credit) * 100, 2),
    }


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


def _policy_cohort(strategy: str, trade_meta: dict[str, Any]) -> str:
    explicit = str(trade_meta.get("calibration_cohort") or trade_meta.get("strategy_version") or "").strip()
    if explicit:
        return explicit
    policy = {
        "strategy": strategy,
        "profit_close_pct": _number(trade_meta.get("profit_close_pct")),
        "stop_loss_pct": _number(trade_meta.get("stop_loss_pct")),
        "outcome": "profit_target_before_stop_or_expiry_executable_quotes",
    }
    digest = hashlib.sha256(
        json.dumps(policy, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()[:12]
    return f"options-policy-{digest}"


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
        contract_selected_at = _parse_ts(trade_meta.get("contract_selected_at")) or now
        if contract_selected_at > now:
            return None
        snapshots_by_symbol = {
            str(row.get("symbol")): row
            for row in (trade_meta.get("leg_market_snapshots") or [])
            if isinstance(row, dict) and row.get("symbol")
        }
        if any(
            (quote_at := _parse_ts(row.get("quote_timestamp"))) is not None and quote_at > now
            for row in snapshots_by_symbol.values()
        ):
            return None
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
                    "quote_provider": market.get("quote_provider") or "alpaca_options_snapshot_v1beta1",
                    "quote_scope": market.get("quote_scope") or option_quote_scope(provider="alpaca"),
                    "quote_timestamp": market.get("quote_timestamp"),
                }
            )
        structure_metrics: dict[str, float] = {}
        if strategy == "iron_fly":
            validated = iron_fly_structure_metrics(legs)
            if validated is None:
                return None
            structure_metrics = validated
        fingerprint = _candidate_fingerprint(strategy, underlying, legs)
        existing = _recent_duplicate(read_records(path), fingerprint, now)
        if existing:
            return existing
        created_at = _iso(now)
        candidate_id = hashlib.sha256(f"{created_at}|{fingerprint}".encode("utf-8")).hexdigest()[:24]
        entry_credit = executable_entry_credit(legs)
        confidence = trade_meta.get("candidate_confidence")
        confidence = confidence if isinstance(confidence, dict) else {}
        raw_probability = _number(
            trade_meta.get("raw_probability", confidence.get("probability"))
        )
        if raw_probability is not None and not 0.0 <= raw_probability <= 1.0:
            raw_probability = None
        leg_scopes = sorted({str(leg.get("quote_scope") or "unknown") for leg in legs})
        candidate_quote_scope = leg_scopes[0] if len(leg_scopes) == 1 else "mixed_or_unknown"
        record = {
            "schema_version": SCHEMA_VERSION,
            "type": "candidate",
            "candidate_id": candidate_id,
            "fingerprint": fingerprint,
            "created_at": created_at,
            "contract_selected_at": _iso(contract_selected_at),
            "evaluation_end_at": trade_meta.get("evaluation_end_at"),
            "setup_id": trade_meta.get("setup_id"),
            "parent_setup_id": trade_meta.get("parent_setup_id"),
            "source_strategy": trade_meta.get("source_strategy") or strategy,
            "expression_type": trade_meta.get("expression_type") or "primary",
            "decision_hash": trade_meta.get("decision_hash"),
            "strategy": strategy,
            "underlying": underlying,
            "expiry": str(trade_meta.get("expiry") or ""),
            "original_qty": int(_number(trade_meta.get("qty")) or 0),
            "effective_qty": int(effective_qty or _number(trade_meta.get("qty")) or 0),
            "quoted_mid_credit": _number(trade_meta.get("net_credit")),
            "executable_entry_credit": entry_credit,
            "entry_quote_complete": entry_credit is not None,
            "max_risk_per_contract": structure_metrics.get("max_risk_per_contract")
            if structure_metrics
            else _number(trade_meta.get("max_risk_per_contract")),
            "profit_close_pct": _number(trade_meta.get("profit_close_pct")),
            "stop_loss_pct": _number(trade_meta.get("stop_loss_pct")),
            "stop_policy": str(trade_meta.get("stop_policy") or "credit_multiple"),
            "setup_score": _number(confidence.get("score")),
            "raw_probability": raw_probability,
            "candidate_confidence": confidence,
            "calibration_cohort": _policy_cohort(strategy, trade_meta),
            "outcome_definition": "profit_target_before_stop_or_expiry_executable_quotes",
            "shadow_consensus": consensus if isinstance(consensus, dict) else {},
            "vix_at_entry": _number(trade_meta.get("vix_at_entry")),
            "vix_term_ratio": _number(trade_meta.get("vix_term_ratio")),
            "iv_rank_at_entry": _number(trade_meta.get("iv_rank_at_entry")),
            "volatility_edge": trade_meta.get("volatility_edge")
            if isinstance(trade_meta.get("volatility_edge"), dict)
            else {},
            "strategy_context": trade_meta.get("strategy_context")
            if isinstance(trade_meta.get("strategy_context"), dict)
            else {},
            "gate_states": trade_meta.get("gate_states")
            if isinstance(trade_meta.get("gate_states"), dict)
            else {},
            "warning_states": trade_meta.get("warning_states")
            if isinstance(trade_meta.get("warning_states"), list)
            else [],
            "spot_at_entry": _number(trade_meta.get("spot_at_entry")),
            "event_context": trade_meta.get("event_context")
            if isinstance(trade_meta.get("event_context"), dict)
            else {},
            "regime_context": trade_meta.get("regime_context")
            if isinstance(trade_meta.get("regime_context"), dict)
            else {},
            "evidence_authority": trade_meta.get("evidence_authority")
            or "read_only_counterfactual_no_execution",
            "structure_metrics": structure_metrics,
            "legs": legs,
            "quote_scope": candidate_quote_scope,
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
    symbols = sorted({
        str(leg.get("symbol") or "")
        for candidate in candidates
        for leg in (candidate.get("legs") or [])
        if leg.get("symbol")
    })
    if not symbols:
        return {}
    if tradier_selected():
        try:
            quotes = fetch_tradier_quotes(symbols)
        except Exception:
            return {}
        return {
            symbol: parsed
            for symbol, parsed in quotes.items()
            if tradier_quote_is_fresh(parsed)
        }

    import requests

    headers = _headers()
    if not all(headers.values()):
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
    explicit_end = _parse_ts(candidate.get("evaluation_end_at"))
    if explicit_end is not None:
        return now >= explicit_end
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
    if str(candidate.get("stop_policy") or "").lower() in {
        "none",
        "none_time_exit_only",
        "time_exit_only",
    }:
        return entry_credit * (1.0 - profit_pct), float("inf")
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
                    "quote_scope": ((sample or {}).get("provenance") or {}).get("quote_scope")
                    if isinstance(sample, dict)
                    else "unavailable",
                }
            )
        close_debit = executable_close_debit(marked_legs)
        quote_complete = close_debit is not None
        leg_scopes = sorted({str(leg.get("quote_scope") or "unknown") for leg in marked_legs})
        mark_scope = leg_scopes[0] if len(leg_scopes) == 1 else "mixed_or_unknown"
        mark = {
            "schema_version": SCHEMA_VERSION,
            "type": "mark",
            "candidate_id": candidate_id,
            "marked_at": _iso(now),
            "quote_complete": quote_complete,
            "executable_close_debit": close_debit,
            "legs": marked_legs,
            "quote_scope": mark_scope,
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
                    "quote_scope": mark_scope,
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


def _loss_asymmetry_stats(pnls: list[float]) -> dict[str, Any]:
    """Expose the win-rate hurdle created by average and tail loss severity."""
    wins = [value for value in pnls if value > 0]
    losses = [abs(value) for value in pnls if value < 0]
    avg_win = mean(wins) if wins else None
    avg_loss = mean(losses) if losses else None
    observed_win_rate = len(wins) / len(pnls) if pnls else None
    break_even = (
        avg_loss / (avg_win + avg_loss)
        if avg_win is not None and avg_loss is not None and avg_win + avg_loss > 0
        else None
    )
    gross_loss = sum(losses)
    largest_loss = max(losses) if losses else None
    tail_count = max(1, math.ceil(len(losses) * 0.20)) if losses else 0
    tail_cvar = mean(sorted(losses, reverse=True)[:tail_count]) if losses else None
    margin = observed_win_rate - break_even if observed_win_rate is not None and break_even is not None else None
    if len(pnls) < 10:
        status = "insufficient_n"
    elif break_even is None:
        status = "degenerate_payoff_sample"
    elif margin is not None and margin < 0:
        status = "win_rate_below_payoff_hurdle"
    elif gross_loss > 0 and largest_loss is not None and largest_loss / gross_loss >= 0.40:
        status = "tail_loss_concentrated"
    else:
        status = "balanced_observed_sample"
    return {
        "status": status,
        "observation_count": len(pnls),
        "winner_count": len(wins),
        "loser_count": len(losses),
        "average_win_before_fees": round(avg_win, 2) if avg_win is not None else None,
        "average_loss_before_fees": round(avg_loss, 2) if avg_loss is not None else None,
        "payoff_ratio": round(avg_win / avg_loss, 4) if avg_win is not None and avg_loss else None,
        "observed_win_rate": round(observed_win_rate, 4) if observed_win_rate is not None else None,
        "required_win_rate_to_break_even": round(break_even, 4) if break_even is not None else None,
        "win_rate_margin_over_break_even": round(margin, 4) if margin is not None else None,
        "largest_loss_before_fees": round(largest_loss, 2) if largest_loss is not None else None,
        "largest_loss_share_of_gross_loss": round(largest_loss / gross_loss, 4) if largest_loss is not None and gross_loss else None,
        "worst_20pct_loss_cvar_before_fees": round(tail_cvar, 2) if tail_cvar is not None else None,
        "authority": "shadow_governance_only",
    }


def _calibration(candidates: dict[str, dict], outcomes: dict[str, dict]) -> dict[str, Any]:
    probability_samples: list[dict[str, Any]] = []
    legacy_setup_samples: list[dict[str, Any]] = []
    for candidate_id, outcome in outcomes.items():
        candidate = candidates.get(candidate_id, {})
        confidence = candidate.get("candidate_confidence") or {}
        score = _number(confidence.get("score")) if isinstance(confidence, dict) else None
        raw_probability = _number(candidate.get("raw_probability"))
        timestamp = candidate.get("created_at") or outcome.get("resolved_at")
        actual = 1 if outcome.get("win") else 0
        if raw_probability is not None and 0.0 <= raw_probability <= 1.0:
            probability_samples.append(
                {
                    "id": candidate_id,
                    "timestamp": timestamp,
                    "probability": raw_probability,
                    "outcome": actual,
                    "strategy": candidate.get("strategy"),
                    "cohort": candidate.get("calibration_cohort") or "legacy-unversioned",
                }
            )
        if score is not None:
            legacy_setup_samples.append(
                {
                    "id": candidate_id,
                    "timestamp": timestamp,
                    "probability": max(0.0, min(1.0, score / 10.0)),
                    "outcome": actual,
                }
            )
    overall = probability_metrics(probability_samples)
    holdout = chronological_holdout(probability_samples)
    legacy = probability_metrics(legacy_setup_samples)
    by_strategy: dict[str, dict[str, Any]] = {}
    by_cohort: dict[str, dict[str, Any]] = {}
    for key, destination in (("strategy", by_strategy), ("cohort", by_cohort)):
        names = sorted({str(sample.get(key) or "unknown") for sample in probability_samples})
        for name in names:
            destination[name] = probability_metrics(
                sample for sample in probability_samples if str(sample.get(key) or "unknown") == name
            )
    return {
        "count": overall["sample_count"],
        "status": overall["status"],
        "brier": overall["brier_score"],
        "constant_brier": overall["base_rate_brier_score"],
        "skill": overall["brier_skill_vs_base_rate"],
        "raw_probability_metrics": overall,
        "chronological_holdout": holdout,
        "by_strategy": by_strategy,
        "by_policy_cohort": by_cohort,
        "legacy_setup_score_diagnostic": {
            **legacy,
            "authority": "diagnostic_only_setup_score_is_not_probability",
        },
        "probability_source_policy": "explicit_frozen_raw_probability_only",
    }


def _decision_funnel(
    candidates: dict[str, dict],
    decisions: dict[str, dict],
) -> dict[str, Any]:
    names = [str(row.get("decision") or "unknown").lower() for row in decisions.values()]
    no_fill_tokens = ("no_fill", "unfilled", "canceled", "cancelled", "expired", "rejected", "submission_failed")
    blocked = sum(name.startswith("blocked") or "manual_approval" in name for name in names)
    no_fill = sum(any(token in name for token in no_fill_tokens) for name in names)
    missing = max(0, len(candidates) - len(decisions))
    by_strategy: dict[str, dict[str, int]] = {}
    for strategy in sorted({str(row.get("strategy") or "unknown") for row in candidates.values()}):
        ids = {candidate_id for candidate_id, row in candidates.items() if str(row.get("strategy") or "unknown") == strategy}
        strategy_names = [
            str(decisions[candidate_id].get("decision") or "unknown").lower()
            for candidate_id in ids
            if candidate_id in decisions
        ]
        by_strategy[strategy] = {
            "candidates": len(ids),
            "decisions": len(strategy_names),
            "blocked": sum(name.startswith("blocked") or "manual_approval" in name for name in strategy_names),
            "no_fill_or_submission_failure": sum(any(token in name for token in no_fill_tokens) for name in strategy_names),
            "missing_decision": max(0, len(ids) - len(strategy_names)),
        }
    return {
        "candidate_count": len(candidates),
        "decision_count": len(decisions),
        "decision_coverage": round(len(decisions) / len(candidates), 4) if candidates else 0.0,
        "blocked_count": blocked,
        "no_fill_or_submission_failure_count": no_fill,
        "missing_decision_count": missing,
        "by_strategy": by_strategy,
        "warning": "Decision cohorts are descriptive; shadow outcomes remain counterfactual and are not broker fills.",
    }


def _normal_cdf(z: float) -> float:
    return 0.5 * math.erfc(-z / math.sqrt(2))


def _deflated_sharpe(pnls: list[float]) -> dict[str, Any]:
    """Bailey/Lopez de Prado deflated Sharpe Ratio.

    Accounts for non-normality (skewness, excess kurtosis) and converts the
    sample Sharpe to a probability that the true edge is positive.
    SR_benchmark = 0 (null: no edge).
    """
    n = len(pnls)
    if n < 4:
        return {"status": "insufficient_n", "n_observations": n, "dsr": None, "sr_per_trade": None}
    mu = mean(pnls)
    # Population moments for skewness/kurtosis; sample variance for SR std error.
    m2_pop = sum((x - mu) ** 2 for x in pnls) / n
    m3_pop = sum((x - mu) ** 3 for x in pnls) / n
    m4_pop = sum((x - mu) ** 4 for x in pnls) / n
    sigma_sample = math.sqrt(m2_pop * n / (n - 1))  # unbiased sample std
    if sigma_sample == 0:
        return {"status": "zero_variance", "n_observations": n, "dsr": None, "sr_per_trade": None}
    sr = mu / sigma_sample
    skew = m3_pop / (m2_pop ** 1.5) if m2_pop > 0 else 0.0
    kurt_excess = (m4_pop / (m2_pop ** 2) - 3) if m2_pop > 0 else 0.0
    # Variance of sample SR per Bailey/LdP (2014) eq. 8
    var_sr = (1.0 - skew * sr + (kurt_excess / 4.0) * sr ** 2) / (n - 1)
    se_sr = math.sqrt(max(0.0, var_sr))
    z = sr / se_sr if se_sr > 0 else 0.0
    dsr = _normal_cdf(z)
    return {
        "status": "ok" if n >= 30 else "low_n",
        "n_observations": n,
        "sr_per_trade": round(sr, 4),
        "skewness": round(skew, 4),
        "excess_kurtosis": round(kurt_excess, 4),
        "standard_error": round(se_sr, 4),
        "z_score": round(z, 4),
        "dsr": round(dsr, 4),
        "benchmark": "sr_benchmark_zero_null_no_edge",
        "authority": "shadow_governance_only",
    }


def _drawdown_stats(pnls: list[float]) -> dict[str, Any]:
    """Max consecutive losses and equity-curve drawdown from resolved P&L sequence."""
    if not pnls:
        return {"max_consecutive_losses": 0, "current_consecutive_losses": 0, "max_drawdown_before_fees": None}
    max_consec = 0
    cur_consec = 0
    for p in pnls:
        if p <= 0:
            cur_consec += 1
            max_consec = max(max_consec, cur_consec)
        else:
            cur_consec = 0
    current_consec = 0
    for p in reversed(pnls):
        if p <= 0:
            current_consec += 1
        else:
            break
    equity = 0.0
    peak = 0.0
    max_dd = 0.0
    for p in pnls:
        equity += p
        peak = max(peak, equity)
        max_dd = max(max_dd, peak - equity)
    return {
        "max_consecutive_losses": max_consec,
        "current_consecutive_losses": current_consec,
        "max_drawdown_before_fees": round(max_dd, 2),
    }


def _close_cost_quality(mark_rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Round-trip TCA: compare executable close debit vs midpoint close debit.

    Pairs each mark's stored executable_close_debit against the midpoint
    recomputed from the mark's leg bid/ask, then reports average friction.
    """
    paired: list[dict[str, float]] = []
    for mark in mark_rows:
        executable = _number(mark.get("executable_close_debit"))
        if executable is None:
            continue
        legs = mark.get("legs") or []
        mid_debit = midpoint_close_debit(legs)
        if mid_debit is None:
            continue
        friction = max(0.0, executable - mid_debit)
        friction_pct = friction / mid_debit if mid_debit > 0 else 0.0
        paired.append({"executable": executable, "mid": mid_debit, "friction": friction, "friction_pct": friction_pct})
    coverage = len(paired) / len(mark_rows) if mark_rows else 0.0
    avg_friction = mean(item["friction"] for item in paired) if paired else None
    avg_friction_pct = mean(item["friction_pct"] for item in paired) if paired else None
    worst_friction_pct = max((item["friction_pct"] for item in paired), default=None)
    blockers: list[str] = []
    if not paired:
        status = "no_complete_close_quotes"
    elif coverage < 0.8:
        status = "incomplete_close_coverage"
        blockers.append("Close quote coverage below 80%.")
    elif avg_friction_pct is not None and avg_friction_pct > 0.15:
        status = "high_close_friction"
        blockers.append("Average close midpoint-to-executable friction exceeds 15%.")
    elif avg_friction_pct is not None and avg_friction_pct > 0.05:
        status = "watch_close_friction"
    else:
        status = "ok"
    return {
        "status": status,
        "mark_count": len(mark_rows),
        "paired_count": len(paired),
        "paired_coverage": round(coverage, 4),
        "avg_close_friction_credit": round(avg_friction, 4) if avg_friction is not None else None,
        "avg_close_friction_pct_of_mid": round(avg_friction_pct, 4) if avg_friction_pct is not None else None,
        "worst_close_friction_pct_of_mid": round(worst_friction_pct, 4) if worst_friction_pct is not None else None,
        "benchmark": "midpoint_close_debit_vs_buy_short_at_ask_sell_long_at_bid",
        "authority": "shadow_governance_only",
        "blockers": blockers,
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
    loss_asymmetry: dict[str, Any],
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
    asymmetry_status = str(loss_asymmetry.get("status") or "")
    if asymmetry_status == "win_rate_below_payoff_hurdle":
        cap = min(cap, 3.0)
        blockers.append("Observed win rate is below the break-even hurdle implied by average win/loss size.")
    elif asymmetry_status == "tail_loss_concentrated":
        cap = min(cap, 5.0)
        blockers.append("Tail losses are too concentrated for promotion review.")
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
    decision_funnel = _decision_funnel(candidates, decisions)
    execution_cost_quality = _execution_cost_quality(candidate_rows)
    close_cost_quality = _close_cost_quality(marks)
    deflated_sharpe = _deflated_sharpe(pnls)
    drawdown = _drawdown_stats(pnls)
    loss_asymmetry = _loss_asymmetry_stats(pnls)
    confluence_analysis = build_confluence_analysis(candidates, outcomes)
    confidence = _earned_confidence(
        len(candidate_rows),
        len(pnls),
        len(distinct_dates),
        entry_coverage,
        mark_coverage,
        expectancy,
        profit_factor,
        calibration,
        loss_asymmetry,
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
        "decision_funnel": decision_funnel,
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
        "close_cost_quality": close_cost_quality,
        "deflated_sharpe": deflated_sharpe,
        "drawdown": drawdown,
        "loss_asymmetry": loss_asymmetry,
        "timeframe_confluence": confluence_analysis,
        "earned_confidence": confidence,
        "promotion_eligible": False,
        "promotion_policy": "human_review_only_after_all_preregistered_gates",
        "warnings": [
            "Alpaca indicative modified quotes are not OPRA NBBO.",
            "P&L excludes fees until broker-verified multi-leg fee evidence is available.",
            "Blocked-versus-submitted results are descriptive, not causal.",
            "Setup scores are ranking features and are never converted into calibrated probabilities.",
            "Timeframe and confluence cohorts are read-only attribution and cannot auto-promote a gate.",
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

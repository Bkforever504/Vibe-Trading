#!/usr/bin/env python3
"""Regrade frozen MNQ SMT-family shadow plans with Databento MBO evidence.

Timely alerts remain proxy discovery while the account lacks a live CME
license.  After the historical delay this job independently reproduces the
signal from raw-contract GLBX.MDP3 OHLCV and resolves it from executable-side,
packet-complete MNQ MBO quotes.  It has no broker imports or order authority.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import statistics
import sys
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.databento_mes_evidence import (
    fetch_historical_cache,
    index_future_front_contract,
    iter_mbo_quotes,
    normalize_ohlcv_1m,
    resample_completed_bars,
)
from scripts.mnq_smt_family_shadow import (
    FAMILY_ID,
    FRICTION_ROUND_TRIP,
    POINT_VALUE,
    STRATEGY_CONFIGS,
    TIME_EXIT,
    UNIVERSE_HASH,
    _load_universe,
    build_entry_plan,
)

DATA_DIR = ROOT / "data"
CACHE_DIR = DATA_DIR / "databento" / "mnq_smt_family"
OUTCOMES_PATH = DATA_DIR / "shadow_outcomes.jsonl"
ATTEMPT_LOG = DATA_DIR / "mnq_smt_family_databento_regrade_log.jsonl"
APPROVAL_PATH = ROOT / "research" / "approvals" / "MNQ_SMT_FAMILY_SHADOW_EVIDENCE_APPROVAL_2026-08-24.md"
APPROVAL_SHA256 = "ab852a4220196bdc42cc7c512349f90581318a22646b973309600201fcd8661a"
REGIME_LABELER_PATH = "research/preregistrations/MNQ_SMT_EVIDENCE_REGIME_LABELER_V1.md"
REGIME_LABELER_SHA256 = "71053de21f0bc235f85c7983254c937053f0b068ce5b75ba358c18b17e59169e"
ET = ZoneInfo("America/New_York")
HISTORICAL_DELAY = timedelta(hours=9)
RETRY_BACKOFF = timedelta(hours=24)
MAX_FAILURE_ATTEMPTS = 3
MAX_QUOTE_GAP_SECONDS = 30.0
MAX_QUOTE_AGE_SECONDS = 2.0
FIRST_POST_PREREGISTRATION_SESSION = date(2026, 8, 25)
ROOTS = ("MNQ", "NQ", "MES", "ES")


@dataclass
class RunBudget:
    limit_usd: float
    spent_usd: float = 0.0

    @property
    def remaining_usd(self) -> float:
        return max(0.0, self.limit_usd - self.spent_usd)

    def debit(self, amount: float) -> None:
        if not math.isfinite(amount) or amount < 0 or amount > self.remaining_usd + 1e-9:
            raise RuntimeError("databento_aggregate_run_cost_limit_exceeded")
        self.spent_usd += amount


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
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


def _append(path: Path, row: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(dict(row), sort_keys=True, separators=(",", ":")) + "\n")


def _parse(value: Any) -> datetime:
    parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("timestamp must be timezone-aware")
    return parsed.astimezone(timezone.utc)


def _safe_error(exc: Exception) -> str:
    message = re.sub(r"(?i)DATABENTO_API_KEY\s*=\s*\S+", "DATABENTO_API_KEY=[REDACTED]", str(exc))
    message = re.sub(r"\bdb-[A-Za-z0-9_-]{8,}\b", "[REDACTED_DATABENTO_KEY]", message)
    return f"{type(exc).__name__}:{message[:220]}"


def approval_valid(path: Path = APPROVAL_PATH) -> bool:
    try:
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError:
        return False
    return digest == APPROVAL_SHA256


def pending_plans(
    ledger_rows: Iterable[Mapping[str, Any]],
    outcome_rows: Iterable[Mapping[str, Any]],
    attempt_rows: Iterable[Mapping[str, Any]],
    *,
    now: datetime,
) -> list[tuple[dict[str, Any], dict[str, Any]]]:
    entries: dict[str, dict[str, Any]] = {}
    terminals: dict[str, dict[str, Any]] = {}
    for raw in ledger_rows:
        row = dict(raw)
        plan_id = str(row.get("plan_id") or "")
        kind = str(row.get("event_type") or row.get("type") or "").lower()
        if plan_id and kind == "entry":
            entries[plan_id] = row
        elif plan_id and (kind in {"exit", "resolved", "outcome", "closed"} or row.get("resolved_at")):
            terminals[plan_id] = row
    completed = {
        str(row.get("plan_id"))
        for row in outcome_rows
        if row.get("data_source") == "databento_glbx_mdp3_mbo"
    }
    completed.update(
        str(row.get("plan_id"))
        for row in attempt_rows
        if row.get("status") in {"qualified", "excluded"}
    )
    failures: dict[str, list[datetime]] = {}
    for row in attempt_rows:
        if row.get("status") != "failed_closed" or not row.get("plan_id"):
            continue
        try:
            failures.setdefault(str(row["plan_id"]), []).append(_parse(row.get("attempted_at")))
        except (TypeError, ValueError):
            continue
    result: list[tuple[dict[str, Any], dict[str, Any]]] = []
    for plan_id in sorted(set(entries) & set(terminals)):
        entry, terminal = entries[plan_id], terminals[plan_id]
        if plan_id in completed or entry.get("should_enter") is not True:
            continue
        prior = sorted(failures.get(plan_id, []))
        if len(prior) >= MAX_FAILURE_ATTEMPTS or (prior and now - prior[-1] < RETRY_BACKOFF):
            continue
        # Prefer the real market exit timestamp; resolved_at may be the later
        # wall-clock time at which a delayed proxy resolver happened to run.
        ended = _parse(terminal.get("exit_timestamp") or terminal.get("resolved_at") or terminal.get("timestamp"))
        if now - ended >= HISTORICAL_DELAY:
            result.append((entry, terminal))
    return result


def _upper(frame: Any, tz: ZoneInfo):
    renamed = frame.rename(columns={name: name.capitalize() for name in ("open", "high", "low", "close", "volume")})
    renamed.index = renamed.index.tz_convert(tz)
    return renamed


def _rth_hourly(frame_1m: Any, *, as_of: datetime):
    """Build complete 60-minute RTH buckets anchored at 09:30 ET."""
    import pandas as pd

    data = frame_1m.copy()
    data.index = data.index.tz_convert(ET)
    data = data.between_time("09:30", "15:59")
    pieces = []
    for session_day, rows in data.groupby(data.index.date):
        origin = pd.Timestamp(datetime.combine(session_day, time(9, 30), ET))
        bucket = ((rows.index - origin).total_seconds() // 3600).astype(int)
        grouped = rows.groupby(bucket).agg(
            open=("open", "first"), high=("high", "max"), low=("low", "min"),
            close=("close", "last"), volume=("volume", "sum"), symbol=("symbol", "first"),
            minute_count=("close", "count"),
        )
        grouped = grouped[grouped["minute_count"] == 60].drop(columns=["minute_count"])
        grouped.index = pd.DatetimeIndex([origin + pd.Timedelta(hours=int(value)) for value in grouped.index])
        pieces.append(grouped)
    if not pieces:
        return data.iloc[0:0]
    result = pd.concat(pieces).sort_index()
    cutoff = as_of.astimezone(ET)
    return result[result.index + pd.Timedelta(hours=1) <= cutoff]


def reproduce_plan(config: Any, frames: Mapping[str, Any], entry: Mapping[str, Any]) -> dict[str, Any]:
    _load_universe()
    labeler = ROOT / REGIME_LABELER_PATH
    if hashlib.sha256(labeler.read_bytes()).hexdigest() != REGIME_LABELER_SHA256:
        raise ValueError("frozen MNQ regime labeler hash mismatch")
    captured = _parse(entry.get("captured_at") or entry.get("timestamp"))
    session = date.fromisoformat(str(entry["session_date"]))
    data = {
        "mnq_5m": _upper(resample_completed_bars(frames["MNQ"], "5m", as_of=captured), ET),
        "mnq_1h": _upper(_rth_hourly(frames["MNQ"], as_of=captured), ET),
        "nq_1h": _upper(_rth_hourly(frames["NQ"], as_of=captured), ET),
        "mes_1h": _upper(_rth_hourly(frames["MES"], as_of=captured), ET),
        "es_1h": _upper(_rth_hourly(frames["ES"], as_of=captured), ET),
    }
    decision = build_entry_plan(config, data, session)
    if decision.get("should_enter") is not True:
        raise ValueError(f"Databento OHLCV did not reproduce frozen signal: {decision.get('reason')}")
    plan = dict(decision["plan"])
    original_direction = str(entry.get("direction") or entry.get("plan", {}).get("direction") or "")
    if plan.get("direction") != original_direction:
        raise ValueError("Databento OHLCV direction differs from timely discovery")
    detected = _parse(plan["actionable_at"])
    plan["signal_trigger_at"] = plan["actionable_at"]
    plan["actionable_at"] = max(captured, detected).isoformat().replace("+00:00", "Z")
    plan["regime_tags"], plan["regime_metrics"] = regime_labels(frames["MNQ"], as_of=max(captured, detected))
    return plan


def regime_labels(frame_1m: Any, *, as_of: datetime) -> tuple[list[str], dict[str, float]]:
    """Apply the frozen, causal evidence-stratification labeler."""
    bars = resample_completed_bars(frame_1m, "5m", as_of=as_of)
    closes = [float(value) for value in bars["close"].tail(24).tolist()]
    if len(closes) != 24 or any(not math.isfinite(value) or value <= 0 for value in closes):
        raise ValueError("24 complete positive MNQ five-minute closes required for regime labels")
    path = sum(abs(right - left) for left, right in zip(closes, closes[1:]))
    efficiency = abs(closes[-1] - closes[0]) / path if path > 0 else 0.0
    log_returns = [math.log(right / left) for left, right in zip(closes, closes[1:])]
    annualized_rv = statistics.stdev(log_returns) * math.sqrt(78 * 252)
    tags = ["trend" if efficiency >= 0.35 else "chop", "high_vol" if annualized_rv >= 0.22 else "low_vol"]
    return tags, {"directional_efficiency_24x5m": round(efficiency, 8),
                  "annualized_realized_vol_24x5m": round(annualized_rv, 8)}


def _quote_time(row: Mapping[str, Any]) -> datetime:
    value = row["ts_recv"]
    if hasattr(value, "to_pydatetime"):
        value = value.to_pydatetime()
    if not isinstance(value, datetime) or value.tzinfo is None:
        raise ValueError("MBO quote timestamp invalid")
    return value.astimezone(timezone.utc)


def resolve_mbo_quotes(
    quotes: Iterable[Mapping[str, Any]], *, direction: str, actionable_at: datetime,
    stop_price: float, t1_price: float, t2_price: float, forced_exit_at: datetime,
) -> dict[str, Any]:
    """Resolve the frozen half-at-T1/half-at-T2 plan using executable sides."""
    sign = 1.0 if direction == "long" else -1.0
    if direction not in {"long", "short"}:
        raise ValueError("invalid direction")
    entry = None
    entry_at = None
    first_exit = None
    final_exit = None
    dynamic_stop = float(stop_price)
    previous = None
    reason = ""
    for row in quotes:
        stamp = _quote_time(row)
        bid, ask = float(row["bid"]), float(row["ask"])
        if not all(math.isfinite(v) for v in (bid, ask)) or bid <= 0 or ask <= bid or ask - bid > 1.0:
            raise ValueError("MBO executable quote failed spread checks")
        if stamp < actionable_at:
            continue
        if final_exit is not None:
            continue  # exhaust iterator so late integrity failures quarantine the slice
        if previous is not None and (stamp - previous).total_seconds() > MAX_QUOTE_GAP_SECONDS:
            raise ValueError("MBO active-window quote continuity gap exceeded")
        previous = stamp
        if entry is None:
            if (stamp - actionable_at).total_seconds() > MAX_QUOTE_AGE_SECONDS:
                raise ValueError("MBO actionable entry quote exceeded age cap")
            entry, entry_at = (ask if direction == "long" else bid), stamp
            continue
        executable = bid if direction == "long" else ask
        if stamp >= forced_exit_at:
            if (stamp - forced_exit_at).total_seconds() > MAX_QUOTE_AGE_SECONDS:
                raise ValueError("MBO forced-exit quote exceeded age cap")
            final_exit, reason = (executable, stamp), "time_exit_16_30_et"
            continue
        if (executable <= dynamic_stop if direction == "long" else executable >= dynamic_stop):
            final_exit = (executable, stamp)
            reason = "stop_before_t1" if first_exit is None else "trail_stop_after_t1"
            continue
        if first_exit is None and (executable >= t1_price if direction == "long" else executable <= t1_price):
            first_exit = (executable, stamp)
            risk = abs(entry - stop_price)
            dynamic_stop = entry + sign * 0.25 * risk
        if first_exit is not None and (executable >= t2_price if direction == "long" else executable <= t2_price):
            final_exit, reason = (executable, stamp), "t2_after_t1"
    if entry is None or entry_at is None or final_exit is None:
        raise ValueError("MBO entry or terminal executable quote unavailable")
    exits = [final_exit[0], final_exit[0]] if first_exit is None else [first_exit[0], final_exit[0]]
    gross = sum(0.5 * sign * (price - entry) * POINT_VALUE for price in exits)
    return {
        "entry_fill_executable": entry,
        "entry_quote_at": entry_at.isoformat().replace("+00:00", "Z"),
        "exit_fill_executable": sum(exits) / 2,
        "exit_fills_executable": exits,
        "exit_quote_at": final_exit[1].isoformat().replace("+00:00", "Z"),
        "exit_reason": reason,
        "gross_dollar": gross,
    }


def build_outcome(
    *, entry: Mapping[str, Any], plan: Mapping[str, Any], resolved: Mapping[str, Any],
    manifests: Mapping[str, Mapping[str, Any]], now: datetime,
) -> dict[str, Any]:
    config = STRATEGY_CONFIGS[str(entry["strategy_id"])]
    session = date.fromisoformat(str(entry["session_date"]))
    contract = index_future_front_contract("MNQ", session)
    blockers: list[str] = []
    if session < FIRST_POST_PREREGISTRATION_SESSION:
        blockers.append("pre_preregistration_session")
    if not approval_valid():
        blockers.append("kenny_shadow_evidence_approval_missing")
    regime_tags = set(str(value) for value in (plan.get("regime_tags") or []))
    if len(regime_tags & {"trend", "chop"}) != 1 or len(regime_tags & {"high_vol", "low_vol"}) != 1:
        blockers.append("frozen_regime_labels_missing")
    gross = float(resolved["gross_dollar"])
    net = gross - FRICTION_ROUND_TRIP
    doubled = gross - 2 * FRICTION_ROUND_TRIP
    max_risk = abs(float(resolved["entry_fill_executable"]) - float(plan["stop_price"])) * POINT_VALUE
    if max_risk <= 0:
        raise ValueError("non-positive executable stop risk")
    captured = _parse(entry.get("captured_at") or entry.get("timestamp"))
    signal_at = _parse(plan["signal_trigger_at"])
    latency = max(0.0, (captured - signal_at).total_seconds())
    eligible = not blockers
    return {
        "schema_version": 2, "plan_id": entry["plan_id"], "candidate_id": config.strategy_id,
        "strategy_id": config.strategy_id, "family_id": FAMILY_ID, "spec_hash": config.spec_hash,
        "session_date": session.isoformat(), "regrade_version": 1,
        "regraded_at": now.isoformat().replace("+00:00", "Z"), "resolved_at": resolved["exit_quote_at"],
        "data_source": "databento_glbx_mdp3_mbo", "terminal_data_source": "databento_glbx_mdp3_mbo",
        "source_agreement": True, "evidence_tier": "databento_mbo_reconstructed_executable",
        "promotion_eligible": eligible, "evidence_blockers": blockers,
        "entry_fill_executable": resolved["entry_fill_executable"],
        "exit_fill_executable": resolved["exit_fill_executable"], "exit_fills_executable": resolved["exit_fills_executable"],
        "terminal_reason": resolved["exit_reason"], "pnl_before_fees": gross, "net_dollar": net,
        "outcome_r": net / max_risk, "doubled_cost_outcome_r": doubled / max_risk,
        "signal": 1.0 if plan["direction"] == "long" else -1.0,
        "alert_latency_seconds": latency, "alert_latency_fraction": latency / (7 * 3600),
        "regime_tags": sorted(regime_tags),
        "regime_labeler": {"version": "mnq-smt-evidence-regime-v1", "path": REGIME_LABELER_PATH,
                           "sha256": REGIME_LABELER_SHA256,
                           "metrics": dict(plan.get("regime_metrics") or {})},
        "universe": {"id": "mnq-smt-family", "version": "2026-08-24", "hash": UNIVERSE_HASH,
                     "raw_symbol": contract.raw_symbol, "expiry": contract.expiry.isoformat(), "roll_at": contract.roll_at.isoformat()},
        "data_integrity": {"independent_signal_reproduction": True, "backfill_status": "complete_for_plan",
                           "mbo_sha256": manifests["MNQ_mbo"].get("sha256"),
                           "ohlcv_sha256": {root: manifests[f"{root}_ohlcv"].get("sha256") for root in ROOTS}},
        "execution_enabled": False, "can_submit_orders": False, "orders_submitted": 0,
    }


def _download_for_plan(entry: Mapping[str, Any], *, budget: RunBudget, max_mbo_cost: float, max_ohlcv_cost: float):
    import databento as db

    session = date.fromisoformat(str(entry["session_date"]))
    end = datetime.combine(session, TIME_EXIT, ET).astimezone(timezone.utc) + timedelta(seconds=5)
    start = datetime.combine(session - timedelta(days=7), time.min, timezone.utc)
    frames: dict[str, Any] = {}
    manifests: dict[str, dict[str, Any]] = {}
    for root in ROOTS:
        manifest = fetch_historical_cache(
            schema="ohlcv-1m", start=start, end=end, root=root, cache_dir=CACHE_DIR,
            contract_date=session, max_cost_usd=min(max_ohlcv_cost, budget.remaining_usd), reserve_cost=budget.debit,
        )
        contract = index_future_front_contract(root, session)
        store = db.DBNStore.from_file(manifest["cache"])
        frames[root] = normalize_ohlcv_1m(store.to_df(), expected_raw_symbol=contract.raw_symbol)
        manifests[f"{root}_ohlcv"] = manifest
    mbo_start = datetime.combine(session, time.min, timezone.utc)
    mbo = fetch_historical_cache(
        schema="mbo", start=mbo_start, end=end, root="MNQ", cache_dir=CACHE_DIR,
        max_cost_usd=min(max_mbo_cost, budget.remaining_usd), reserve_cost=budget.debit,
    )
    manifests["MNQ_mbo"] = mbo
    return frames, Path(mbo["cache"]), manifests, index_future_front_contract("MNQ", session).raw_symbol


def run_once(
    *, download: bool, now: datetime | None = None, max_mbo_cost: float = 4.5,
    max_ohlcv_cost: float = 0.15, max_daily_cost: float = 5.0, max_plans: int = 4,
    outcomes_path: Path = OUTCOMES_PATH, attempt_log: Path = ATTEMPT_LOG,
) -> dict[str, Any]:
    now = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    attempts, outcomes = _read_jsonl(attempt_log), _read_jsonl(outcomes_path)
    spent_today = sum(float(row.get("estimated_download_cost_usd") or 0) for row in attempts
                      if row.get("attempted_at") and _parse(row["attempted_at"]).date() == now.date())
    budget = RunBudget(max_daily_cost, min(spent_today, max_daily_cost))
    pending: list[tuple[dict[str, Any], dict[str, Any]]] = []
    for config in STRATEGY_CONFIGS.values():
        pending.extend(pending_plans(_read_jsonl(config.log_path), outcomes, attempts, now=now))
    if not download:
        return {"status": "estimate_only_no_paid_calls", "pending_count": len(pending),
                "daily_cost_cap_usd": max_daily_cost, "daily_cost_remaining_usd": budget.remaining_usd,
                "execution_enabled": False, "can_submit_orders": False}
    qualified = excluded = failed = attempted = 0
    for entry, _terminal in pending[:max_plans]:
        if budget.remaining_usd <= 0:
            break
        attempted += 1
        cost_before = budget.spent_usd
        try:
            frames, mbo_path, manifests, raw_symbol = _download_for_plan(
                entry, budget=budget, max_mbo_cost=max_mbo_cost, max_ohlcv_cost=max_ohlcv_cost)
            config = STRATEGY_CONFIGS[str(entry["strategy_id"])]
            plan = reproduce_plan(config, frames, entry)
            import databento as db
            store = db.DBNStore.from_file(mbo_path)
            session = date.fromisoformat(str(entry["session_date"]))
            resolved = resolve_mbo_quotes(
                iter_mbo_quotes(iter(store), expected_raw_symbol=raw_symbol), direction=str(plan["direction"]),
                actionable_at=_parse(plan["actionable_at"]), stop_price=float(plan["stop_price"]),
                t1_price=float(plan["t1_price"]), t2_price=float(plan["t2_price"]),
                forced_exit_at=datetime.combine(session, TIME_EXIT, ET).astimezone(timezone.utc))
            row = build_outcome(entry=entry, plan=plan, resolved=resolved, manifests=manifests, now=now)
            _append(outcomes_path, row)
            status = "qualified" if row["promotion_eligible"] else "excluded"
            _append(attempt_log, {"plan_id": entry["plan_id"], "status": status,
                    "attempted_at": now.isoformat().replace("+00:00", "Z"),
                    "estimated_download_cost_usd": round(budget.spent_usd - cost_before, 6),
                    "execution_enabled": False, "can_submit_orders": False})
            qualified += int(row["promotion_eligible"])
            excluded += int(not row["promotion_eligible"])
            outcomes.append(row)
        except Exception as exc:
            _append(attempt_log, {"plan_id": entry.get("plan_id"), "status": "failed_closed",
                    "reason": _safe_error(exc), "attempted_at": now.isoformat().replace("+00:00", "Z"),
                    "estimated_download_cost_usd": round(budget.spent_usd - cost_before, 6),
                    "promotion_eligible": False, "execution_enabled": False, "can_submit_orders": False})
            failed += 1
    return {"status": "completed", "pending_count": len(pending), "attempted_count": attempted,
            "qualified_count": qualified, "excluded_count": excluded, "failed_closed_count": failed,
            "daily_cost_cap_usd": max_daily_cost, "daily_estimated_download_cost_usd": round(budget.spent_usd, 6),
            "daily_cost_remaining_usd": round(budget.remaining_usd, 6),
            "execution_enabled": False, "can_submit_orders": False}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--download", action="store_true")
    parser.add_argument("--max-mbo-cost", type=float, default=4.5)
    parser.add_argument("--max-ohlcv-cost", type=float, default=0.15)
    parser.add_argument("--max-daily-cost", type=float, default=5.0)
    parser.add_argument("--max-plans", type=int, default=4)
    args = parser.parse_args()
    print(json.dumps(run_once(download=args.download, max_mbo_cost=args.max_mbo_cost,
                              max_ohlcv_cost=args.max_ohlcv_cost, max_daily_cost=args.max_daily_cost,
                              max_plans=args.max_plans), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

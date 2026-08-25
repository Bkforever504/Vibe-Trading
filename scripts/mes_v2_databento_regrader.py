#!/usr/bin/env python3
"""Regrade completed MES v2 proxy plans with delayed Databento MBO evidence.

The timely scanner remains a non-executable discovery surface because the
current account has no GLBX.MDP3 live license.  This job runs only after the
historical availability delay and appends a new, versioned qualified outcome
when the frozen signal, raw eight-day-roll contract, and executable-side MBO
quotes all validate independently.
"""
from __future__ import annotations

import argparse
import json
import math
import re
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
    iter_mbo_quotes,
    mes_front_contract,
    normalize_ohlcv_1m,
    resample_completed_bars,
)


DATA_DIR = ROOT / "data"
CACHE_DIR = DATA_DIR / "databento" / "mes_v2_forward"
OUTCOMES_PATH = DATA_DIR / "shadow_outcomes.jsonl"
ATTEMPT_LOG = DATA_DIR / "mes_v2_databento_regrade_log.jsonl"
ET = ZoneInfo("America/New_York")
CT = ZoneInfo("America/Chicago")
# The current GLBX historical boundary trails real time by about eight hours.
# Nine hours gives a safety margin; a provider-side range rejection still
# fails closed and retries the next day.
HISTORICAL_DELAY = timedelta(hours=9)
RETRY_BACKOFF = timedelta(hours=24)
MAX_FAILURE_ATTEMPTS = 3
MAX_QUOTE_GAP_SECONDS = 30.0
MAX_TERMINAL_QUOTE_AGE_SECONDS = 2.0
POINT_VALUE = 5.0
MODEL_QUANTITY = 2  # two contracts are required to model the frozen 50% scale-out.

CONFIG = {
    "mes-orb-0932-vix-v2": {
        "ledger": DATA_DIR / "mes_orb_0932_vix_v2_shadow_log.jsonl",
        "family_id": "mes-opening-breakout",
        "spec_hash": "sha256:1b5b00351729d29d41f9b58cf3bbe7ad66d5edda594d29d405af72279dd4fd5b",
        "slippage_points_per_side": 0.25,
        "window_seconds": 145 * 60,
    },
    "mes-reopen-drift-v2": {
        "ledger": DATA_DIR / "mes_reopen_drift_v2_shadow_log.jsonl",
        "family_id": "mes-overnight-drift",
        "spec_hash": "sha256:3a345679af8d94402cd8a0d06406635f093aa843fa24dd1324d66429144f42ad",
        "slippage_points_per_side": 0.50,
        "window_seconds": 14 * 3600,
    },
}


@dataclass
class RunBudget:
    """Mutable aggregate download budget shared by every plan in one run."""

    limit_usd: float
    spent_usd: float = 0.0

    @property
    def remaining_usd(self) -> float:
        return max(0.0, self.limit_usd - self.spent_usd)

    def debit(self, amount: float) -> None:
        if not math.isfinite(amount) or amount < 0:
            raise ValueError("download cost debit must be finite and non-negative")
        if amount > self.remaining_usd + 1e-9:
            raise RuntimeError("databento_aggregate_run_cost_limit_exceeded")
        self.spent_usd += amount


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8-sig").splitlines():
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(row, dict):
            rows.append(row)
    return rows


def _append(path: Path, row: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(dict(row), separators=(",", ":"), sort_keys=True) + "\n")


def _safe_error(exc: Exception) -> str:
    message = str(exc)
    message = re.sub(r"(?i)DATABENTO_API_KEY\s*=\s*\S+", "DATABENTO_API_KEY=[REDACTED]", message)
    message = re.sub(r"\bdb-[A-Za-z0-9_-]{8,}\b", "[REDACTED_DATABENTO_KEY]", message)
    return f"{type(exc).__name__}:{message[:220]}"


def _parse(value: Any) -> datetime:
    parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("timestamp must be timezone-aware")
    return parsed.astimezone(timezone.utc)


def pending_plans(
    ledger_rows: Iterable[Mapping[str, Any]],
    outcome_rows: Iterable[Mapping[str, Any]],
    *,
    now: datetime,
    attempt_rows: Iterable[Mapping[str, Any]] = (),
    retry_backoff: timedelta = RETRY_BACKOFF,
) -> list[tuple[dict[str, Any], dict[str, Any]]]:
    entries: dict[str, dict[str, Any]] = {}
    terminals: dict[str, dict[str, Any]] = {}
    for raw in ledger_rows:
        row = dict(raw)
        plan_id = str(row.get("plan_id") or "")
        if not plan_id:
            continue
        kind = str(row.get("event_type") or row.get("type") or "").lower()
        if kind == "entry":
            entries[plan_id] = row
        elif kind in {"exit", "outcome", "resolved", "closed"} or row.get("resolved_at"):
            terminals[plan_id] = row
    already = {
        str(row.get("plan_id"))
        for row in outcome_rows
        if row.get("promotion_eligible") is True
    }
    failures: dict[str, list[datetime]] = {}
    for row in attempt_rows:
        if row.get("status") != "failed_closed" or not row.get("plan_id"):
            continue
        try:
            stamp = _parse(row.get("attempted_at"))
        except (TypeError, ValueError):
            continue
        failures.setdefault(str(row["plan_id"]), []).append(stamp)
    pending: list[tuple[dict[str, Any], dict[str, Any]]] = []
    for plan_id in sorted(set(entries) & set(terminals)):
        entry, terminal = entries[plan_id], terminals[plan_id]
        if plan_id in already or entry.get("should_enter") is not True:
            continue
        prior_failures = sorted(failures.get(plan_id, []))
        if len(prior_failures) >= MAX_FAILURE_ATTEMPTS:
            continue
        if prior_failures and now.astimezone(timezone.utc) - prior_failures[-1] < retry_backoff:
            continue
        # A resolver may run well after the market exit.  Historical
        # availability is measured from the actual exit, not job wall time.
        ended = _parse(terminal.get("exit_timestamp") or terminal.get("resolved_at") or terminal.get("timestamp"))
        if now.astimezone(timezone.utc) - ended < HISTORICAL_DELAY:
            continue
        pending.append((entry, terminal))
    return pending


def _quote_time(row: Mapping[str, Any]) -> datetime:
    value = row.get("ts_recv")
    if hasattr(value, "to_pydatetime"):
        value = value.to_pydatetime()
    if not isinstance(value, datetime):
        value = _parse(value)
    if value.tzinfo is None:
        raise ValueError("MBO quote timestamp is naive")
    return value.astimezone(timezone.utc)


def _valid_quote(row: Mapping[str, Any]) -> tuple[float, float]:
    bid, ask = float(row["bid"]), float(row["ask"])
    bid_size, ask_size = float(row["bid_size"]), float(row["ask_size"])
    if not all(math.isfinite(value) for value in (bid, ask, bid_size, ask_size)):
        raise ValueError("MBO quote contains non-finite values")
    if bid <= 0 or ask <= bid or bid_size < 1 or ask_size < 1 or ask - bid > 1.0:
        raise ValueError("MBO quote failed executable spread/size checks")
    return bid, ask


def resolve_mbo_quotes(
    quotes: Iterable[Mapping[str, Any]],
    *,
    strategy_id: str,
    direction: str,
    actionable_at: datetime,
    stop_price: float,
    target_one_distance: float,
    target_two_distance: float,
    forced_exit_at: datetime,
    atr: float | None = None,
) -> dict[str, Any]:
    """Apply frozen exits to packet-complete reconstructed MBO quotes."""
    if direction not in {"long", "short"}:
        raise ValueError("direction must be long or short")
    actionable_at = actionable_at.astimezone(timezone.utc)
    forced_exit_at = forced_exit_at.astimezone(timezone.utc)
    sign = 1.0 if direction == "long" else -1.0
    entry: float | None = None
    entry_at: datetime | None = None
    t1: float | None = None
    t2: float | None = None
    dynamic_stop = float(stop_price)
    first_exit: tuple[float, datetime] | None = None
    final_exit: tuple[float, datetime] | None = None
    reason = ""
    favorable_extreme: float | None = None
    previous_active_quote_at: datetime | None = None

    for row in quotes:
        stamp = _quote_time(row)
        bid, ask = _valid_quote(row)
        if stamp < actionable_at:
            continue
        if final_exit is not None:
            # Exhaust the guarded MBO iterator so late data-quality failures in
            # the evidence slice still quarantine the whole regrade.
            continue
        if previous_active_quote_at is not None:
            gap = (stamp - previous_active_quote_at).total_seconds()
            if gap > MAX_QUOTE_GAP_SECONDS:
                raise ValueError("MBO active-window quote continuity gap exceeded")
        previous_active_quote_at = stamp
        if entry is None:
            if (stamp - actionable_at).total_seconds() > 2:
                raise ValueError("MBO actionable entry quote exceeded the two-second age cap")
            entry = ask if direction == "long" else bid
            entry_at = stamp
            t1 = entry + sign * target_one_distance
            t2 = entry + sign * target_two_distance
            favorable_extreme = bid if direction == "long" else ask
            continue
        assert entry_at is not None and t1 is not None and t2 is not None
        executable_exit = bid if direction == "long" else ask
        favorable_extreme = (
            max(float(favorable_extreme), executable_exit)
            if direction == "long"
            else min(float(favorable_extreme), executable_exit)
        )

        if stamp >= forced_exit_at:
            if (stamp - forced_exit_at).total_seconds() > MAX_TERMINAL_QUOTE_AGE_SECONDS:
                raise ValueError("MBO forced-exit quote exceeded the two-second age cap")
            final_exit = (executable_exit, stamp)
            reason = "time_stop_12_00_et" if strategy_id == "mes-orb-0932-vix-v2" else "time_stop_08_30_et"
            continue

        stop_hit = executable_exit <= dynamic_stop if direction == "long" else executable_exit >= dynamic_stop
        if stop_hit:
            final_exit = (executable_exit, stamp)
            reason = "stop_before_t1" if first_exit is None else "trail_stop_after_t1"
            continue

        if first_exit is None:
            t1_hit = executable_exit >= t1 if direction == "long" else executable_exit <= t1
            if t1_hit:
                first_exit = (executable_exit, stamp)
                if strategy_id == "mes-orb-0932-vix-v2":
                    dynamic_stop = entry + sign * 0.25
                else:
                    dynamic_stop = entry + sign * 0.25 * float(atr or 0.0)

        if first_exit is not None:
            t2_hit = executable_exit >= t2 if direction == "long" else executable_exit <= t2
            if t2_hit:
                final_exit = (executable_exit, stamp)
                reason = "t2_after_t1"
                continue

        elapsed = stamp - entry_at
        favorable_points = sign * (float(favorable_extreme) - entry)
        stop_distance = abs(entry - stop_price)
        if strategy_id == "mes-orb-0932-vix-v2" and first_exit is None:
            if elapsed >= timedelta(minutes=15) and favorable_points >= 0.5 * stop_distance:
                dynamic_stop = entry
        elif strategy_id == "mes-reopen-drift-v2" and first_exit is None:
            if elapsed >= timedelta(hours=2) and favorable_points >= stop_distance:
                dynamic_stop = entry
            if elapsed >= timedelta(hours=4) and sign * (executable_exit - entry) <= -0.5 * stop_distance:
                final_exit = (executable_exit, stamp)
                reason = "four_hour_negative_half_r"
                continue

    if entry is None or entry_at is None:
        raise ValueError("MBO entry quote unavailable")
    if final_exit is None:
        raise ValueError("MBO terminal executable quote unavailable")
    if first_exit is None:
        exit_prices = [final_exit[0], final_exit[0]]
    else:
        exit_prices = [first_exit[0], final_exit[0]]
    gross = sum(sign * (price - entry) * POINT_VALUE for price in exit_prices)
    return {
        "entry_fill_executable": entry,
        "entry_quote_at": entry_at.isoformat().replace("+00:00", "Z"),
        "exit_fill_executable": sum(exit_prices) / len(exit_prices),
        "exit_fills_executable": exit_prices,
        "exit_quote_at": final_exit[1].isoformat().replace("+00:00", "Z"),
        "exit_reason": reason,
        "gross_dollar": gross,
        "quantity": MODEL_QUANTITY,
    }


def qualified_outcome(
    *,
    entry: Mapping[str, Any],
    official_plan: Mapping[str, Any],
    resolved: Mapping[str, Any],
    raw_symbol: str,
    mbo_manifest: Mapping[str, Any],
    ohlcv_manifest: Mapping[str, Any],
    now: datetime,
) -> dict[str, Any]:
    strategy_id = str(entry["strategy_id"])
    config = CONFIG[strategy_id]
    gross = float(resolved["gross_dollar"])
    slippage = float(config["slippage_points_per_side"]) * POINT_VALUE * MODEL_QUANTITY * 2
    commission = 0.35 * MODEL_QUANTITY * 2
    max_risk = abs(float(resolved["entry_fill_executable"]) - float(official_plan["stop_price"])) * POINT_VALUE * MODEL_QUANTITY
    if max_risk <= 0:
        raise ValueError("official stop risk is not positive")
    net = gross - slippage - commission
    doubled = gross - 2 * (slippage + commission)
    direction = str(official_plan["direction"])
    signal = 1.0 if direction == "long" else -1.0
    action_at = _parse(
        official_plan.get("signal_trigger_at")
        or official_plan.get("actionable_at")
        or official_plan.get("trigger", {}).get("actionable_at")
    )
    captured_at = _parse(entry.get("captured_at") or entry.get("timestamp"))
    latency_seconds = max(0.0, (captured_at - action_at).total_seconds())
    session_date = str(entry["session_date"])
    contract = mes_front_contract(date.fromisoformat(session_date))
    if raw_symbol != contract.raw_symbol:
        raise ValueError("raw contract violates frozen eight-day roll universe")
    return {
        "schema_version": 2,
        "plan_id": entry["plan_id"],
        "candidate_id": strategy_id,
        "strategy_id": strategy_id,
        "family_id": config["family_id"],
        "spec_hash": config["spec_hash"],
        "preregistration_schema": "hypothesis-v2",
        "session_date": session_date,
        "regrade_version": 2,
        "regraded_at": now.astimezone(timezone.utc).isoformat().replace("+00:00", "Z"),
        "resolved_at": resolved["exit_quote_at"],
        "data_source": "databento_glbx_mdp3_mbo",
        "terminal_data_source": "databento_glbx_mdp3_mbo",
        "source_agreement": True,
        "evidence_tier": "databento_mbo_executable",
        "terminal_evidence_tier": "databento_mbo_executable",
        "promotion_eligible": True,
        "evidence_blockers": [],
        "entry_fill_executable": resolved["entry_fill_executable"],
        "exit_fill_executable": resolved["exit_fill_executable"],
        "exit_fills_executable": resolved["exit_fills_executable"],
        "outcome_r": net / max_risk,
        "doubled_cost_outcome_r": doubled / max_risk,
        "forward_return_r": signal * gross / max_risk,
        "signal": signal,
        "pnl_before_fees": gross,
        "net_dollar": net,
        "quantity": MODEL_QUANTITY,
        "terminal_reason": resolved["exit_reason"],
        "alert_latency_seconds": latency_seconds,
        "alert_latency_fraction": latency_seconds / float(config["window_seconds"]),
        "regime_tags": ["trend"],
        "universe": {
            "id": "cme-mes-continuous",
            "version": "cme-mes-front-month-roll8-v1",
            "hash": "sha256:aabaf0268d8e08c686b4ea20d251550f6de0663d59ce363543e76e35595eb567",
            "membership_as_of": "2026-08-22",
            "drift_status": "unchanged",
            "raw_symbol": raw_symbol,
            "expiry": contract.expiry.isoformat(),
            "roll_at": contract.roll_at.isoformat(),
        },
        "data_integrity": {
            "source_repair_detected": True,
            "backfill_status": "complete_for_plan",
            "regrade_status": "complete_for_plan",
            "contaminated_outcomes_remaining": 0,
            "mbo_sha256": mbo_manifest.get("sha256"),
            "ohlcv_sha256": ohlcv_manifest.get("sha256"),
        },
        "execution_enabled": False,
        "can_submit_orders": False,
    }


def _upper(frame: Any, timezone_name: ZoneInfo):
    renamed = frame.rename(columns={name: name.capitalize() for name in ("open", "high", "low", "close", "volume")})
    renamed.index = renamed.index.tz_convert(timezone_name)
    return renamed


def _require_context(
    filters: Mapping[str, Any],
    *,
    source_key: str,
    timestamp_key: str,
    expected_source: str,
    captured_at: datetime,
) -> datetime:
    if filters.get(source_key) != expected_source:
        raise ValueError(f"point-in-time context source missing: {source_key}")
    if not filters.get(timestamp_key):
        raise ValueError(f"point-in-time context timestamp missing: {timestamp_key}")
    observed_at = _parse(filters[timestamp_key])
    if observed_at > captured_at:
        raise ValueError(f"point-in-time context is later than capture: {timestamp_key}")
    return observed_at


def _official_plan(strategy_id: str, entry: Mapping[str, Any], bars_1m: Any) -> dict[str, Any]:
    import pandas as pd

    if "cboe_official_VIX" not in str(entry.get("data_source") or ""):
        raise ValueError("timely signal did not preserve official CBOE VIX provenance")
    session = date.fromisoformat(str(entry["session_date"]))
    original_filters = entry.get("filters") if isinstance(entry.get("filters"), Mapping) else {}
    captured_at = _parse(entry.get("captured_at") or entry.get("timestamp"))
    _require_context(
        original_filters,
        source_key="vix_source",
        timestamp_key="vix_observed_at",
        expected_source="cboe_vix_history",
        captured_at=captured_at,
    )
    _require_context(
        original_filters,
        source_key="macro_source",
        timestamp_key="macro_observed_at",
        expected_source="market_catalyst_calendar",
        captured_at=captured_at,
    )
    if not original_filters.get("vix_observed_session"):
        raise ValueError("official CBOE VIX observed session is missing")
    vix_observed_session = date.fromisoformat(str(original_filters["vix_observed_session"]))
    if vix_observed_session > session:
        raise ValueError("official CBOE VIX observed session is non-causal")
    vix = float(original_filters.get("vix_prior_close"))
    vix_frame = pd.DataFrame({"Close": [vix]}, index=pd.DatetimeIndex([vix_observed_session]))
    action = captured_at
    if strategy_id == "mes-orb-0932-vix-v2":
        from scripts import mes_orb_0932_vix_v2_shadow as scanner

        _require_context(
            original_filters,
            source_key="hmm_source",
            timestamp_key="hmm_observed_at",
            expected_source="hmm_regime_report",
            captured_at=captured_at,
        )
        if "hmm_state" not in original_filters or "macro_blocked" not in original_filters:
            raise ValueError("ORB point-in-time HMM or macro decision is missing")

        two = _upper(resample_completed_bars(bars_1m, "2m", as_of=action), ET)
        five = _upper(resample_completed_bars(bars_1m, "5m", as_of=action), ET)
        decision = scanner.build_entry_plan(
            two,
            five,
            vix_frame,
            session,
            hmm_state=original_filters.get("hmm_state"),
            macro_blocked=bool(original_filters.get("macro_blocked")),
            macro_names=list(original_filters.get("macro_events") or []),
        )
    else:
        from scripts import mes_reopen_drift_v2_shadow as scanner

        if "macro_next_day_blocked" not in original_filters:
            raise ValueError("reopen point-in-time macro decision is missing")

        thirty = _upper(resample_completed_bars(bars_1m, "30m", as_of=action), CT)
        one_hour = _upper(resample_completed_bars(bars_1m, "1h", as_of=action), ET)
        five = _upper(resample_completed_bars(bars_1m, "5m", as_of=action), ET)
        decision = scanner.build_entry_plan(
            bars_30m=thirty,
            bars_1h=one_hour,
            bars_5m=five,
            vix_daily=vix_frame,
            session_date=session,
            macro_context=(
                bool(original_filters.get("macro_next_day_blocked")),
                list(original_filters.get("macro_events_next_day") or []),
            ),
        )
    if decision.get("should_enter") is not True:
        raise ValueError(f"Databento OHLCV did not reproduce the frozen signal: {decision.get('reason')}")
    plan = dict(decision["plan"])
    original_direction = str(entry.get("direction") or entry.get("plan", {}).get("direction") or "")
    if plan.get("direction") != original_direction:
        raise ValueError("Databento OHLCV direction differs from the timely discovery signal")
    signal_trigger = plan.get("actionable_at") or plan.get("trigger", {}).get("actionable_at")
    plan["signal_trigger_at"] = signal_trigger
    # Executable evidence starts when the alert and all causal context were
    # actually captured, never at an earlier retrospectively detected bar.
    plan["actionable_at"] = captured_at.isoformat().replace("+00:00", "Z")
    return plan


def _download_for_plan(
    entry: Mapping[str, Any],
    *,
    max_mbo_cost: float,
    max_ohlcv_cost: float,
    budget: RunBudget,
) -> tuple[Any, Any, dict[str, Any], dict[str, Any], str]:
    import databento as db

    session = date.fromisoformat(str(entry["session_date"]))
    strategy_id = str(entry["strategy_id"])
    action = _parse(entry.get("created_at") or entry.get("plan", {}).get("actionable_at") or entry.get("plan", {}).get("trigger", {}).get("actionable_at"))
    if strategy_id == "mes-orb-0932-vix-v2":
        forced_exit = datetime.combine(session, time(12, 0), ET).astimezone(timezone.utc)
    else:
        forced_exit = datetime.combine(session + timedelta(days=1), time(8, 30), ET).astimezone(timezone.utc)
    contract = mes_front_contract(session)
    lookback_start = max(session - timedelta(days=21), contract.roll_at)
    ohlcv_start = datetime.combine(lookback_start, time.min, timezone.utc)
    request_end = forced_exit + timedelta(seconds=5)
    mbo_start = datetime.combine(session, time.min, timezone.utc)
    ohlcv_manifest = fetch_historical_cache(
        schema="ohlcv-1m", start=ohlcv_start, end=request_end,
        cache_dir=CACHE_DIR,
        max_cost_usd=min(max_ohlcv_cost, budget.remaining_usd),
        reserve_cost=budget.debit,
    )
    mbo_manifest = fetch_historical_cache(
        schema="mbo", start=mbo_start, end=request_end,
        cache_dir=CACHE_DIR,
        max_cost_usd=min(max_mbo_cost, budget.remaining_usd),
        reserve_cost=budget.debit,
    )
    bars_store = db.DBNStore.from_file(ohlcv_manifest["cache"])
    bars = normalize_ohlcv_1m(bars_store.to_df(), expected_raw_symbol=contract.raw_symbol)
    return bars, Path(mbo_manifest["cache"]), ohlcv_manifest, mbo_manifest, contract.raw_symbol


def run_once(
    *,
    download: bool,
    now: datetime | None = None,
    max_mbo_cost: float = 2.0,
    max_ohlcv_cost: float = 0.25,
    max_daily_cost: float = 2.25,
    max_plans: int = 1,
    outcomes_path: Path = OUTCOMES_PATH,
    attempt_log: Path = ATTEMPT_LOG,
) -> dict[str, Any]:
    now = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    if max_daily_cost < 0 or max_plans < 1:
        raise ValueError("max_daily_cost must be non-negative and max_plans must be positive")
    outcomes = _read_jsonl(outcomes_path)
    attempts = _read_jsonl(attempt_log)
    today = now.date()
    spent_today = 0.0
    for attempt in attempts:
        stamp_value = attempt.get("attempted_at") or attempt.get("regraded_at")
        try:
            same_day = _parse(stamp_value).date() == today
        except (TypeError, ValueError):
            same_day = False
        if same_day:
            spent_today += max(0.0, float(attempt.get("estimated_download_cost_usd") or 0.0))
    budget = RunBudget(limit_usd=max_daily_cost, spent_usd=min(spent_today, max_daily_cost))
    pending: list[tuple[dict[str, Any], dict[str, Any]]] = []
    for config in CONFIG.values():
        pending.extend(
            pending_plans(
                _read_jsonl(config["ledger"]),
                outcomes,
                now=now,
                attempt_rows=attempts,
            )
        )
    if not download:
        return {
            "status": "estimate_only_no_paid_calls",
            "pending_count": len(pending),
            "max_plans_per_run": max_plans,
            "daily_cost_cap_usd": max_daily_cost,
            "daily_cost_remaining_usd": budget.remaining_usd,
            "execution_enabled": False,
            "can_submit_orders": False,
        }

    qualified = 0
    failed = 0
    attempted = 0
    for entry, _terminal in pending[:max_plans]:
        if budget.remaining_usd <= 0:
            break
        plan_id = str(entry["plan_id"])
        cost_before = budget.spent_usd
        attempted += 1
        try:
            bars, mbo_cache, ohlcv_manifest, mbo_manifest, raw_symbol = _download_for_plan(
                entry,
                max_mbo_cost=max_mbo_cost,
                max_ohlcv_cost=max_ohlcv_cost,
                budget=budget,
            )
            plan = _official_plan(str(entry["strategy_id"]), entry, bars)
            session = date.fromisoformat(str(entry["session_date"]))
            action = _parse(plan["actionable_at"])
            forced_exit = (
                datetime.combine(session, time(12, 0), ET)
                if entry["strategy_id"] == "mes-orb-0932-vix-v2"
                else datetime.combine(session + timedelta(days=1), time(8, 30), ET)
            )
            stop_distance = abs(float(plan["entry_price"]) - float(plan["stop_price"]))
            if entry["strategy_id"] == "mes-orb-0932-vix-v2":
                width = float(plan["opening_range"]["width"])
                t1_distance, t2_distance = width, 2 * width
            else:
                t1_distance, t2_distance = stop_distance, 2.5 * stop_distance
            import databento as db

            mbo_store = db.DBNStore.from_file(mbo_cache)
            resolved = resolve_mbo_quotes(
                iter_mbo_quotes(iter(mbo_store), expected_raw_symbol=raw_symbol),
                strategy_id=str(entry["strategy_id"]),
                direction=str(plan["direction"]),
                actionable_at=action,
                stop_price=float(plan["stop_price"]),
                target_one_distance=t1_distance,
                target_two_distance=t2_distance,
                forced_exit_at=forced_exit,
                atr=float(plan.get("atr_30m") or 0.0),
            )
            row = qualified_outcome(
                entry=entry, official_plan=plan, resolved=resolved,
                raw_symbol=raw_symbol, mbo_manifest=mbo_manifest,
                ohlcv_manifest=ohlcv_manifest, now=now,
            )
            _append(outcomes_path, row)
            _append(attempt_log, {
                "plan_id": plan_id,
                "status": "qualified",
                "regraded_at": row["regraded_at"],
                "estimated_download_cost_usd": round(budget.spent_usd - cost_before, 6),
                "execution_enabled": False,
                "can_submit_orders": False,
            })
            outcomes.append(row)
            qualified += 1
        except Exception as exc:
            _append(attempt_log, {
                "plan_id": plan_id,
                "status": "failed_closed",
                "reason": _safe_error(exc),
                "attempted_at": now.isoformat().replace("+00:00", "Z"),
                "estimated_download_cost_usd": round(budget.spent_usd - cost_before, 6),
                "promotion_eligible": False,
                "execution_enabled": False,
                "can_submit_orders": False,
            })
            failed += 1
    return {
        "status": "completed",
        "pending_count": len(pending),
        "attempted_count": attempted,
        "qualified_count": qualified,
        "failed_closed_count": failed,
        "max_plans_per_run": max_plans,
        "daily_cost_cap_usd": max_daily_cost,
        "daily_estimated_download_cost_usd": round(budget.spent_usd, 6),
        "daily_cost_remaining_usd": round(budget.remaining_usd, 6),
        "execution_enabled": False,
        "can_submit_orders": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--download", action="store_true", help="Allow cost-capped historical downloads")
    parser.add_argument("--max-mbo-cost", type=float, default=2.0)
    parser.add_argument("--max-ohlcv-cost", type=float, default=0.25)
    parser.add_argument("--max-daily-cost", type=float, default=2.25)
    parser.add_argument("--max-plans", type=int, default=1)
    args = parser.parse_args()
    print(json.dumps(run_once(
        download=args.download,
        max_mbo_cost=args.max_mbo_cost,
        max_ohlcv_cost=args.max_ohlcv_cost,
        max_daily_cost=args.max_daily_cost,
        max_plans=args.max_plans,
    ), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

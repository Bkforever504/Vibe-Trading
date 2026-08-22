#!/usr/bin/env python3
"""Normalize confirmed scanner events into a paper-consumer signal contract.

Discovery sources may nominate symbols, but only completed price/volume
sequences can create a signal. This module has no broker or order methods.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parent.parent
VIBE_HOME = Path.home() / ".vibe-trading"
REPORT_PATH = VIBE_HOME / "reports" / "trade-signal-generator.json"
LOG_PATH = ROOT / "data" / "trade_signal_generator_log.jsonl"
EVENT_GAP_PATH = VIBE_HOME / "reports" / "event-gap-continuation-shadow.json"
PREMARKET_RADAR_PATH = VIBE_HOME / "reports" / "premarket-opportunity-radar.json"
BOTTOM_REVERSAL_PATH = VIBE_HOME / "reports" / "bottom-reversal-investigator.json"
ALERT_STATE_PATH = VIBE_HOME / "state" / "trade-signal-generator-alerts.json"

SCHEMA_VERSION = 1
MAX_SOURCE_AGE_SECONDS = 8 * 60
MAX_TRIGGER_AGE_SECONDS = 12 * 60
MIN_REWARD_RISK = 1.5
APPROVED_DISCOVERY_SOURCES = {
    "premarket_radar",
    "social_trending",
    "deep_liquid_universe",
}


def _read_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _timestamp(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _finite(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _age_seconds(value: Any, now: datetime) -> float | None:
    parsed = _timestamp(value)
    if parsed is None:
        return None
    return max(0.0, (now - parsed).total_seconds())


def _radar_rows(report: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {
        str(row.get("symbol") or "").upper(): row
        for row in report.get("observations") or []
        if isinstance(row, dict) and row.get("symbol")
    }


def _approved_same_session_discovery(
    candidate: dict[str, Any],
    *,
    event_report: dict[str, Any],
    radar_report: dict[str, Any],
    symbol: str,
) -> tuple[bool, list[str]]:
    """Validate nomination provenance without granting it signal authority."""
    event_date = str(event_report.get("date") or "")
    provenance = candidate.get("discovery_provenance")
    if isinstance(provenance, dict):
        source_date = str(provenance.get("as_of") or "")
        sources = {
            str(source)
            for source in provenance.get("sources") or []
            if str(source) in APPROVED_DISCOVERY_SOURCES
        }
        if source_date == event_date and sources:
            return True, sorted(sources)

    # Backward compatibility for reports created before provenance was carried
    # into each candidate. The radar remains nomination-only.
    radar_row = _radar_rows(radar_report).get(symbol, {})
    if (
        str(radar_report.get("date") or "") == event_date
        and radar_row.get("lane") == "event_gap"
    ):
        return True, ["premarket_radar_legacy_join"]
    return False, []


def _valid_price_shape(direction: str, entry: float | None, stop: float | None, target: float | None) -> bool:
    if None in (entry, stop, target):
        return False
    if direction == "bullish":
        return bool(stop < entry < target)
    if direction == "bearish":
        return bool(target < entry < stop)
    return False


def _signal_id(candidate: dict[str, Any]) -> str:
    identity = "|".join(
        [
            "event_gap_v1",
            str(candidate.get("symbol") or ""),
            str(candidate.get("direction") or ""),
            str(candidate.get("entry_time") or ""),
            str(candidate.get("entry") or ""),
        ]
    )
    return hashlib.sha256(identity.encode("utf-8")).hexdigest()[:24]


def normalize_event_gap_signal(
    candidate: dict[str, Any],
    *,
    event_report: dict[str, Any],
    radar_report: dict[str, Any],
    now: datetime,
) -> dict[str, Any]:
    symbol = str(candidate.get("symbol") or "").upper()
    raw_direction = str(candidate.get("direction") or "").lower()
    direction = "bullish" if raw_direction in {"bull", "bullish"} else "bearish" if raw_direction in {"bear", "bearish"} else "unknown"
    entry = _finite(candidate.get("entry"))
    stop = _finite(candidate.get("stop"))
    target = _finite(candidate.get("target"))
    source_age = _age_seconds(event_report.get("generated_at"), now)
    trigger_age = _age_seconds(candidate.get("entry_time"), now)
    radar_row = _radar_rows(radar_report).get(symbol, {})
    discovery_current, discovery_sources = _approved_same_session_discovery(
        candidate,
        event_report=event_report,
        radar_report=radar_report,
        symbol=symbol,
    )
    risk = abs(entry - stop) if entry is not None and stop is not None else None
    reward = abs(target - entry) if target is not None and entry is not None else None
    reward_risk = reward / risk if reward is not None and risk not in (None, 0.0) else None
    outcome = candidate.get("post_entry_outcome") if isinstance(candidate.get("post_entry_outcome"), dict) else {}

    gates = {
        "candidate_mechanical_sequence_complete": bool(candidate.get("eligible")),
        "event_report_current": bool(source_age is not None and source_age <= MAX_SOURCE_AGE_SECONDS),
        "trigger_current": bool(trigger_age is not None and trigger_age <= MAX_TRIGGER_AGE_SECONDS),
        "same_session_approved_discovery": discovery_current,
        "price_shape_valid": _valid_price_shape(direction, entry, stop, target),
        "reward_risk_sufficient": bool(reward_risk is not None and reward_risk >= MIN_REWARD_RISK),
        "trade_not_already_resolved": outcome.get("status") in {None, "open"},
    }
    ready = all(gates.values())
    return {
        "schema_version": SCHEMA_VERSION,
        "signal_id": _signal_id(candidate),
        "generated_at": now.isoformat().replace("+00:00", "Z"),
        "symbol": symbol,
        "setup": "event_gap_or15_break_vwap_relative_volume",
        "direction": direction,
        "status": "paper_observation_ready" if ready else "blocked",
        "paper_consumable": ready,
        "entry_triggered_at": candidate.get("entry_time"),
        "entry": entry,
        "stop": stop,
        "targets": [{"name": "target_2r", "price": target, "reward_risk": reward_risk}],
        "risk_points": risk,
        "reward_risk": round(reward_risk, 4) if reward_risk is not None else None,
        "instrument_preference": "shares_or_defined_risk_debit_spread_after_separate_liquidity_check",
        "order_style": "patient_limit_only",
        "time_in_force": "day",
        "hard_gates": gates,
        "blockers": [name for name, passed in gates.items() if not passed],
        "source_health": {
            "event_report_generated_at": event_report.get("generated_at"),
            "event_report_age_seconds": round(source_age, 1) if source_age is not None else None,
            "trigger_age_seconds": round(trigger_age, 1) if trigger_age is not None else None,
            "radar_state": radar_row.get("state"),
            "radar_priority": radar_row.get("priority"),
            "discovery_sources": discovery_sources,
            "discovery_is_nomination_only": True,
        },
        "source_candidate": {
            "formula_version": candidate.get("formula_version"),
            "gap_pct": candidate.get("gap_pct"),
            "volume_ratio": candidate.get("volume_ratio"),
            "directional_relative_pct": candidate.get("directional_relative_pct"),
            "vwap_extension_pct": candidate.get("vwap_extension_pct"),
        },
        "execution_enabled": False,
        "can_submit_orders": False,
        "authority": "paper_consumer_input_only",
        "warning": "A signal is a bounded hypothesis, not a prediction or profitability guarantee.",
    }


def build_report(
    *,
    event_report: dict[str, Any] | None = None,
    radar_report: dict[str, Any] | None = None,
    bottom_report: dict[str, Any] | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    now = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    event_report = event_report if event_report is not None else _read_json(EVENT_GAP_PATH)
    radar_report = radar_report if radar_report is not None else _read_json(PREMARKET_RADAR_PATH)
    bottom_report = bottom_report if bottom_report is not None else _read_json(BOTTOM_REVERSAL_PATH)
    candidates = [row for row in event_report.get("candidates") or [] if isinstance(row, dict)]
    signals = [
        normalize_event_gap_signal(
            candidate,
            event_report=event_report,
            radar_report=radar_report,
            now=now,
        )
        for candidate in candidates
    ]
    signals.sort(key=lambda row: (not row["paper_consumable"], -(row.get("reward_risk") or 0.0), row["symbol"]))
    watchlist = [
        {
            "symbol": str(row.get("symbol") or "").upper(),
            "lane": row.get("lane"),
            "direction": row.get("direction"),
            "state": row.get("state"),
            "priority": row.get("priority"),
            "route": row.get("routed_shadow_playbook"),
            "paper_consumable": False,
            "authority": "discovery_only_until_completed_sequence",
        }
        for row in radar_report.get("observations") or []
        if isinstance(row, dict) and row.get("alertable")
    ]
    watchlist.extend(
        {
            "symbol": str(row.get("symbol") or "").upper(),
            "lane": "bottom_reversal",
            "direction": "bullish",
            "state": row.get("stage"),
            "priority": "high" if row.get("stage") == "armed_next_session" else "watch",
            "route": "bottom_reversal_next_session_trigger",
            "entry_plan": row.get("next_session_plan"),
            "paper_consumable": False,
            "authority": "armed_plan_only_until_next_session_price_liquidity_and_risk_revalidation",
        }
        for row in bottom_report.get("candidates") or []
        if isinstance(row, dict) and row.get("symbol")
    )
    event_age = _age_seconds(event_report.get("generated_at"), now)
    return {
        "schema_version": SCHEMA_VERSION,
        "provider": "trade_signal_generator",
        "generated_at": now.isoformat().replace("+00:00", "Z"),
        "date": str(event_report.get("date") or now.date().isoformat()),
        "mode": "paper_signal_contract",
        "signals": signals,
        "watchlist": watchlist,
        "ready_signals": [row for row in signals if row["paper_consumable"]],
        "blocked_signals": [row for row in signals if not row["paper_consumable"]],
        "counts": {
            "source_candidates": len(candidates),
            "ready": sum(bool(row["paper_consumable"]) for row in signals),
            "blocked": sum(not bool(row["paper_consumable"]) for row in signals),
        },
        "operational_health": {
            "status": "ok" if event_report and event_age is not None and event_age <= MAX_SOURCE_AGE_SECONDS else "degraded",
            "event_report_available": bool(event_report),
            "event_report_age_seconds": round(event_age, 1) if event_age is not None else None,
            "radar_report_available": bool(radar_report),
            "bottom_reversal_report_available": bool(bottom_report),
        },
        "execution_enabled": False,
        "can_submit_orders": False,
        "orders_submitted": 0,
        "authority": "paper_consumers_must_revalidate_every_gate",
    }


def validate_signal_for_consumer(signal: dict[str, Any], *, now: datetime | None = None) -> tuple[bool, list[str]]:
    now = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    blockers = list(signal.get("blockers") or [])
    if not signal.get("paper_consumable"):
        blockers.append("signal_not_paper_consumable")
    generated_age = _age_seconds(signal.get("generated_at"), now)
    trigger_age = _age_seconds(signal.get("entry_triggered_at"), now)
    if generated_age is None or generated_age > MAX_SOURCE_AGE_SECONDS:
        blockers.append("signal_artifact_stale")
    if trigger_age is None or trigger_age > MAX_TRIGGER_AGE_SECONDS:
        blockers.append("signal_trigger_stale")
    if signal.get("execution_enabled") is not False or signal.get("can_submit_orders") is not False:
        blockers.append("signal_authority_invariant_failed")
    return not blockers, sorted(set(blockers))


def load_signal_for_symbol(
    symbol: str,
    *,
    path: Path = REPORT_PATH,
    now: datetime | None = None,
) -> dict[str, Any]:
    report = _read_json(path)
    symbol = str(symbol or "").upper()
    for signal in report.get("ready_signals") or []:
        if isinstance(signal, dict) and str(signal.get("symbol") or "").upper() == symbol:
            valid, blockers = validate_signal_for_consumer(signal, now=now)
            return {**signal, "consumer_valid": valid, "consumer_blockers": blockers}
    return {
        "symbol": symbol,
        "consumer_valid": False,
        "consumer_blockers": ["no_ready_signal_for_symbol"],
        "execution_enabled": False,
        "can_submit_orders": False,
    }


def write_report(report: dict[str, Any], report_path: Path = REPORT_PATH, log_path: Path = LOG_PATH) -> None:
    report_path.parent.mkdir(parents=True, exist_ok=True)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = report_path.with_suffix(report_path.suffix + ".tmp")
    temporary.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(temporary, report_path)
    with log_path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(report, separators=(",", ":"), sort_keys=True) + "\n")


def _post_discord(message: str) -> bool:
    from scripts.shadow_alerts import webhook_url

    url = webhook_url()
    if not url:
        return False
    request = urllib.request.Request(
        url,
        data=json.dumps({"content": message}).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=10):
            return True
    except Exception:
        return False


def send_signal_alerts(
    report: dict[str, Any],
    *,
    state_path: Path = ALERT_STATE_PATH,
    sender: Any = _post_discord,
) -> int:
    state = _read_json(state_path)
    sent = state.get("sent") if isinstance(state.get("sent"), dict) else {}
    count = 0
    for signal in report.get("ready_signals") or []:
        signal_id = str(signal.get("signal_id") or "")
        if not signal_id or signal_id in sent:
            continue
        target = ((signal.get("targets") or [{}])[0]).get("price")
        message = (
            f"**Confirmed paper signal: {signal.get('symbol')} {signal.get('direction')}**\n"
            f"Setup=`{signal.get('setup')}` entry=`{signal.get('entry')}` stop=`{signal.get('stop')}` "
            f"target=`{target}` R:R=`{signal.get('reward_risk')}`\n"
            f"Signal=`{signal_id}` trigger=`{signal.get('entry_triggered_at')}`\n"
            "Paper-consumer input only. Revalidate price, liquidity, account risk, and broker state. No order placed."
        )
        if sender(message):
            sent[signal_id] = report.get("generated_at")
            count += 1
    state_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = state_path.with_suffix(state_path.suffix + ".tmp")
    temporary.write_text(json.dumps({"schema_version": 1, "sent": sent}, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(temporary, state_path)
    return count


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--event-report", type=Path, default=EVENT_GAP_PATH)
    parser.add_argument("--radar-report", type=Path, default=PREMARKET_RADAR_PATH)
    parser.add_argument("--bottom-report", type=Path, default=BOTTOM_REVERSAL_PATH)
    parser.add_argument("--report-path", type=Path, default=REPORT_PATH)
    parser.add_argument("--log-path", type=Path, default=LOG_PATH)
    parser.add_argument("--state-path", type=Path, default=ALERT_STATE_PATH)
    parser.add_argument("--no-alert", action="store_true")
    parser.add_argument("--print", action="store_true", dest="print_report")
    args = parser.parse_args()
    report = build_report(
        event_report=_read_json(args.event_report),
        radar_report=_read_json(args.radar_report),
        bottom_report=_read_json(args.bottom_report),
    )
    report["alerts_sent"] = 0 if args.no_alert else send_signal_alerts(report, state_path=args.state_path)
    write_report(report, args.report_path, args.log_path)
    if args.print_report:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        print(f"Trade signals: ready={report['counts']['ready']} blocked={report['counts']['blocked']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

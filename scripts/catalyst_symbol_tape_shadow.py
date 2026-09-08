#!/usr/bin/env python3
"""Observe verified catalyst stocks on completed one-minute bars (shadow only)."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Mapping

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.core_index_tape_watcher import (  # noqa: E402
    MARKET_TZ,
    NYSE_HOLIDAYS_2026,
    build_observation,
    fetch_completed_1m,
)
from scripts.premarket_opportunity_radar import BASE_UNIVERSE  # noqa: E402
from scripts import governed_shadow_alert  # noqa: E402

VIBE_HOME = Path.home() / ".vibe-trading"
SEC_REPORT_PATH = VIBE_HOME / "reports" / "sec-latest-filings-shadow.json"
RADAR_REPORT_PATH = VIBE_HOME / "reports" / "intraday-opportunity-radar.json"
REPORT_PATH = VIBE_HOME / "reports" / "catalyst-symbol-tape-shadow.json"
STATE_PATH = VIBE_HOME / "state" / "catalyst-symbol-tape-shadow.json"
EVENT_PATH = VIBE_HOME / "data" / "catalyst_symbol_tape_events.jsonl"
DELIVERY_EVENT_PATH = VIBE_HOME / "data" / "catalyst_symbol_tape_delivery_events.jsonl"
MAX_SYMBOLS = 12
MAX_EVENT_AGE = timedelta(hours=24)
MIN_RADAR_DOLLAR_VOLUME = 25_000_000.0
TAPE_CATALYST_FORMS = frozenset({
    "8-K", "6-K", "10-Q", "10-K", "20-F", "SC 13D", "SC 13G", "SC TO-I",
    "SC TO-T", "SC TO-C", "SC 14D9", "SC 13E3", "DEFM14A", "PREM14A",
    "425", "CB", "S-4", "F-4",
})


def _read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def _stamp(value: Any) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(str(value or "").replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    return parsed.astimezone(timezone.utc) if parsed.tzinfo else None


def select_verified_symbols(
    sec_report: Mapping[str, Any],
    radar_report: Mapping[str, Any],
    *,
    now: datetime,
    max_symbols: int = MAX_SYMBOLS,
) -> list[dict[str, Any]]:
    """Select recent, index-verified SEC catalysts with an explicit liquidity basis."""
    now = now.astimezone(timezone.utc)
    radar = {
        str(row.get("symbol") or "").upper(): row
        for row in radar_report.get("ranked_candidates") or []
        if isinstance(row, Mapping)
    }
    liquid_allowlist = set(BASE_UNIVERSE)
    selected: dict[str, dict[str, Any]] = {}
    for raw in (sec_report.get("events") or sec_report.get("catalysts") or []):
        row = raw if isinstance(raw, Mapping) else {}
        symbol = str(row.get("symbol") or "").upper()
        accepted = _stamp(row.get("event_at") or row.get("source_accepted_at") or row.get("accepted_at"))
        priority_value = str(row.get("priority") or ("high" if str(row.get("form") or "").split("/", 1)[0] in {"8-K", "6-K", "SC 13D", "SC 13G", "SC TO-I", "SC TO-T", "SC 14D9"} else "medium"))
        base_form = str(row.get("form") or "").upper().removesuffix("/A")
        if (
            not symbol
            or base_form not in TAPE_CATALYST_FORMS
            or row.get("source") != "sec_edgar_latest_atom"
            or row.get("verification_status") != "primary_index_verified"
            or (row.get("source_url") or row.get("canonical_url")) is None
            or row.get("collector_received_at") is None
            or priority_value not in {"high", "medium"}
            or accepted is None
            or not timedelta(0) <= now - accepted <= MAX_EVENT_AGE
        ):
            continue
        radar_row = radar.get(symbol, {})
        dollar_volume = radar_row.get("avg_dollar_volume_20d")
        liquid = symbol in liquid_allowlist or (
            isinstance(dollar_volume, (int, float))
            and not isinstance(dollar_volume, bool)
            and dollar_volume >= MIN_RADAR_DOLLAR_VOLUME
        )
        if not liquid:
            continue
        candidate = {
            "symbol": symbol,
            "accepted_at": accepted.isoformat().replace("+00:00", "Z"),
            "accession": row.get("accession"),
            "form": row.get("form"),
            "priority": priority_value,
            "source": row.get("source"),
            "source_url": row.get("source_url") or row.get("canonical_url"),
            "verification_status": row.get("verification_status"),
            "collector_received_at": row.get("collector_received_at"),
            "source_observed_at": row.get("source_observed_at") or row.get("document_verified_at"),
            "liquidity_basis": "base_liquid_universe" if symbol in liquid_allowlist else "radar_20d_dollar_volume",
        }
        prior = selected.get(symbol)
        if prior is None or candidate["accepted_at"] > prior["accepted_at"]:
            selected[symbol] = candidate
    priority = {"high": 0, "medium": 1}
    return sorted(
        selected.values(),
        key=lambda row: (priority.get(str(row["priority"]), 9), -(_stamp(row["accepted_at"]) or datetime.min.replace(tzinfo=timezone.utc)).timestamp(), row["symbol"]),
    )[:max(0, max_symbols)]


def build_report(
    *,
    now_et: datetime,
    sec_report: Mapping[str, Any],
    radar_report: Mapping[str, Any],
    previous_state: Mapping[str, Any] | None = None,
    fetcher=fetch_completed_1m,
) -> dict[str, Any]:
    clock = now_et.astimezone(MARKET_TZ)
    candidates = select_verified_symbols(sec_report, radar_report, now=clock.astimezone(timezone.utc))
    symbols = [row["symbol"] for row in candidates]
    catalyst_by_symbol = {row["symbol"]: row for row in candidates}
    prior_rows = (previous_state or {}).get("observations") or {}
    market_day = clock.weekday() < 5 and clock.date().isoformat() not in NYSE_HOLIDAYS_2026
    in_window = market_day and datetime.strptime("09:30", "%H:%M").time() <= clock.time() <= datetime.strptime("16:05", "%H:%M").time()
    bars: dict[str, list[dict[str, Any]]] = {}
    errors: list[str] = []
    feed = str(os.getenv("VIBE_TRADING_STOCK_FEED") or "iex").lower()
    feed = feed if feed in {"iex", "sip"} else "iex"
    if in_window and symbols:
        bars, errors = fetcher(symbols, now_et=clock, feed=feed)
    observations = []
    for symbol in symbols:
        observed = build_observation(
            symbol,
            bars.get(symbol, []),
            now_et=clock,
            previous=prior_rows.get(symbol) if isinstance(prior_rows, Mapping) else None,
        )
        observations.append({**observed, "primary_catalyst": catalyst_by_symbol[symbol]})
    status = "market_closed" if not market_day else "outside_rth" if not in_window else "no_verified_liquid_catalysts" if not symbols else "degraded" if errors else "ok"
    return {
        "schema_version": "catalyst-symbol-tape-shadow-v1",
        "provider": f"alpaca_{feed}_completed_1m_plus_sec_latest_atom",
        "generated_at": clock.astimezone(timezone.utc).isoformat().replace("+00:00", "Z"),
        "status": status,
        "symbols": symbols,
        "candidate_count": len(candidates),
        "observations": observations,
        "errors": errors,
        "source_status": sec_report.get("status") or "missing",
        "execution_enabled": False,
        "can_submit_orders": False,
        "warning": "Shadow early-warning evidence only. A separate deterministic plan, quote check, and completed-5m confirmation remain mandatory.",
    }


def _atomic(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(dict(payload), indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(path)


def format_alert(row: Mapping[str, Any]) -> str:
    catalyst = row.get("primary_catalyst") if isinstance(row.get("primary_catalyst"), Mapping) else {}
    return (
        f"**CATALYST TAPE {row.get('state')} | {row.get('symbol')} {row.get('direction')}**\n"
        f"SEC `{catalyst.get('form')}` accepted `{catalyst.get('accepted_at')}` | "
        f"completed 1m `{row.get('bar_completed_at')}`\n"
        f"Price `{row.get('last_price')}` | VWAP `{row.get('session_vwap')}` | "
        f"1m `{row.get('one_minute_return_bps')} bp` | window `{row.get('window_return_bps')} bp`\n"
        f"Primary source: {catalyst.get('source_url')}\n"
        "Shadow early-warning only. Wait for the separate deterministic plan and completed-5m review; no order placed."
    )


def persist(
    report: Mapping[str, Any], *, report_path: Path, state_path: Path, event_path: Path,
    alert: bool = False, sender: Callable[[str], Mapping[str, Any]] | None = None,
    delivery_event_path: Path = DELIVERY_EVENT_PATH,
) -> int:
    prior = _read_json(state_path)
    seen = set(prior.get("transition_ids") or [])
    delivered = set(prior.get("delivered_transition_ids") or [])
    pending = [dict(row) for row in prior.get("pending_alerts") or [] if isinstance(row, Mapping)]
    fresh = []
    for row in report.get("observations") or []:
        if not isinstance(row, Mapping) or row.get("transition") is not True:
            continue
        raw = "|".join(str(row.get(key) or "") for key in ("session_date", "symbol", "state", "direction", "bar_completed_at", "primary_catalyst"))
        transition_id = hashlib.sha256((raw + "|catalyst-symbol-tape-shadow-v1").encode()).hexdigest()
        if transition_id in seen:
            continue
        fresh.append({"transition_id": transition_id, **dict(row)})
        seen.add(transition_id)
    attempts = sent = failures = 0
    retry: list[dict[str, Any]] = []
    if alert:
        transport = sender or governed_shadow_alert.deliver
        by_id = {
            str(row.get("transition_id")): row for row in [*pending, *fresh]
            if row.get("transition_id") and row.get("alertable") is True
        }
        for transition_id, row in by_id.items():
            if transition_id in delivered:
                continue
            try:
                outcome = dict(transport(format_alert(row)))
            except Exception as exc:
                outcome = {"delivered": False, "attempts": 1, "error_class": type(exc).__name__}
            attempts += int(outcome.get("attempts") or 0)
            delivery_event_path.parent.mkdir(parents=True, exist_ok=True)
            with delivery_event_path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps({
                    "transition_id": transition_id,
                    "symbol": row.get("symbol"),
                    "bar_close_ts": row.get("bar_completed_at"),
                    "scanner_emit_ts": row.get("detected_at"),
                    "discord_message_id": outcome.get("discord_message_id"),
                    "discord_delivered_ts": outcome.get("discord_delivered_ts"),
                    "delivery_status": "delivered" if outcome.get("delivered") is True else "failed",
                    "delivery_result": outcome,
                    "execution_enabled": False,
                    "can_submit_orders": False,
                }, sort_keys=True, separators=(",", ":")) + "\n")
            if outcome.get("delivered") is True:
                delivered.add(transition_id)
                sent += 1
            else:
                failures += 1
                retry.append(row)
    else:
        retry = pending
    _atomic(report_path, {
        **dict(report), "new_transition_count": len(fresh), "notification_attempts": attempts,
        "alerts_sent": sent, "notification_failures": failures, "pending_delivery": len(retry),
    })
    state = {
        "schema_version": "catalyst-symbol-tape-state-v1",
        "generated_at": report.get("generated_at"),
        "observations": {str(row.get("symbol")): dict(row) for row in report.get("observations") or [] if isinstance(row, Mapping) and row.get("symbol")},
        "transition_ids": sorted(seen)[-5000:],
        "delivered_transition_ids": sorted(delivered)[-5000:],
        "pending_alerts": retry,
        "execution_enabled": False,
        "can_submit_orders": False,
    }
    _atomic(state_path, state)
    if fresh:
        event_path.parent.mkdir(parents=True, exist_ok=True)
        with event_path.open("a", encoding="utf-8") as handle:
            for row in fresh:
                handle.write(json.dumps(row, sort_keys=True, separators=(",", ":")) + "\n")
    return len(fresh)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sec-report", type=Path, default=SEC_REPORT_PATH)
    parser.add_argument("--radar-report", type=Path, default=RADAR_REPORT_PATH)
    parser.add_argument("--report", type=Path, default=REPORT_PATH)
    parser.add_argument("--state", type=Path, default=STATE_PATH)
    parser.add_argument("--events", type=Path, default=EVENT_PATH)
    parser.add_argument("--delivery-events", type=Path, default=DELIVERY_EVENT_PATH)
    parser.add_argument("--alert", action="store_true")
    args = parser.parse_args()
    report = build_report(
        now_et=datetime.now(MARKET_TZ),
        sec_report=_read_json(args.sec_report),
        radar_report=_read_json(args.radar_report),
        previous_state=_read_json(args.state),
    )
    report["new_transition_count"] = persist(
        report, report_path=args.report, state_path=args.state, event_path=args.events,
        alert=args.alert, delivery_event_path=args.delivery_events,
    )
    print(json.dumps({"status": report["status"], "symbols": report["symbols"], "new_transitions": report["new_transition_count"]}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

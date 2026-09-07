#!/usr/bin/env python3
"""Evaluate delivered Discord trade alerts from the first tradable 1m bar.

This is an execution-quality audit, not a backtest fill claim.  It deliberately
excludes the minute containing the Discord delivery, reprices a gap-through
entry at the next completed minute's open, and rejects plans whose invalidation
was reached before a post-delivery entry.  No broker or order API is imported.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import statistics
import sys
from collections import Counter, defaultdict
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping
from zoneinfo import ZoneInfo

import requests

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.intraday_opportunity_radar import _credentials
from scripts.alert_delivery_timing import delivered_at, first_complete_bar_after_delivery
from scripts.chart_aligned_shadow_learning import align_signal_to_chart, build_bplus_upgrade_nominations
from scripts.shadow_alert_intelligence import estimate_alert_half_life

ET = ZoneInfo("America/New_York")
VIBE_HOME = Path.home() / ".vibe-trading"
GOVERNED_EVENTS = VIBE_HOME / "data" / "governed_shadow_alert_events.jsonl"
DECISION_LEDGER = ROOT / "data" / "governed_shadow_decision_ledger.jsonl"
BPLUS_LOG = ROOT / "data" / "bplus_spotlight_log.jsonl"
APLUS_LOG = ROOT / "data" / "aplus_spotlight_log.jsonl"
DAILY_MAP_EVENTS = VIBE_HOME / "data" / "daily_level_map_alert_events.jsonl"
SPY_LEVEL_EVENTS = VIBE_HOME / "data" / "spy_level_reaction_alert_events.jsonl"
REPORT_PATH = VIBE_HOME / "reports" / "discord-alert-chart-review.json"
HISTORY_PATH = VIBE_HOME / "data" / "discord_alert_chart_review_history.jsonl"
HORIZON_MINUTES = 60


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    try:
        lines = path.read_text(encoding="utf-8-sig").splitlines()
    except OSError:
        return []
    output: list[dict[str, Any]] = []
    for line in lines:
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(row, dict):
            output.append(row)
    return output


def _timestamp(value: Any) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(str(value or "").replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _number(value: Any) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if math.isfinite(parsed) else None


def _session_close(stamp: datetime) -> datetime:
    return datetime.combine(stamp.astimezone(ET).date(), time(16, 0), ET).astimezone(timezone.utc)


def _delivery_context(event: Mapping[str, Any], candidate: Mapping[str, Any]) -> dict[str, Any]:
    exact = event.get("delivered_at") or event.get("discord_delivered_at")
    stamp = _timestamp(exact or event.get("attempted_at") or event.get("timestamp"))
    regime = dict(candidate.get("regime_bucket") or {}) if isinstance(candidate.get("regime_bucket"), Mapping) else {}
    if stamp:
        local = stamp.astimezone(ET)
        minute = local.hour * 60 + local.minute
        regime.setdefault("session_slot", next((label for start, finish, label in ((570, 600, "0930-1000"), (600, 660, "1000-1100"), (660, 840, "1100-1400"), (840, 960, "1400-1600")) if start <= minute < finish), "outside_rth"))
        regime.setdefault("day_of_week", local.strftime("%a").upper())
    regime.setdefault("vix_bucket", "missing")
    regime.setdefault("trend_bucket", "missing")
    return {"delivered_at": exact, "delivery_timestamp_quality": "exact" if exact else "attempt_only",
            "regime_bucket": regime}


def evaluate_alert(
    alert: Mapping[str, Any], bars: Iterable[Mapping[str, Any]], *, now: datetime,
) -> dict[str, Any]:
    """Chronologically replay one delivered plan from the next full minute."""
    sent = delivered_at(alert)
    direction = str(alert.get("direction") or "").upper()
    entry, stop, target = (_number(alert.get(key)) for key in ("entry", "stop", "target"))
    base = {
        **dict(alert),
        "entry_filled": False,
        "execution_enabled": False,
        "can_submit_orders": False,
        "limitations": "Completed 1m underlying proxy after Discord delivery; no option NBBO, spread, slippage model, fee, or executable fill claim.",
    }
    if sent is None or direction not in {"LONG", "SHORT"} or None in {entry, stop, target}:
        return {**base, "status": "invalid_alert_contract"}
    valid_geometry = (direction == "LONG" and stop < entry < target) or (direction == "SHORT" and target < entry < stop)
    if not valid_geometry:
        return {**base, "status": "invalid_geometry"}
    first_start = first_complete_bar_after_delivery(alert)
    if first_start is None:
        return {**base, "status": "invalid_alert_contract"}
    end = min(first_start + timedelta(minutes=HORIZON_MINUTES), _session_close(sent))
    cutoff = min(end, now.astimezone(timezone.utc).replace(second=0, microsecond=0))
    base.update({"first_eligible_bar": first_start.isoformat().replace("+00:00", "Z"),
                 "evaluation_end": end.isoformat().replace("+00:00", "Z")})
    if first_start >= end:
        return {**base, "status": "outside_regular_session"}
    normalized: list[dict[str, Any]] = []
    for raw in bars:
        stamp = _timestamp(raw.get("t") or raw.get("timestamp"))
        values = {key: _number(raw.get(key)) for key in ("o", "h", "l", "c")}
        if stamp is None or any(value is None for value in values.values()):
            continue
        if min(values.values()) <= 0 or not (values["l"] <= min(values["o"], values["c"]) <= max(values["o"], values["c"]) <= values["h"]):
            continue
        if first_start <= stamp and stamp + timedelta(minutes=1) <= cutoff:
            normalized.append({"t": stamp, **values})
    normalized.sort(key=lambda row: row["t"])
    # A missing minute is unknown price action, including on the sparse IEX feed.
    # Preserve only the uninterrupted prefix; an earlier terminal event is valid.
    contiguous = []
    expected = first_start
    for bar in normalized:
        if contiguous and bar["t"] == contiguous[-1]["t"] and bar == contiguous[-1]:
            continue
        if bar["t"] != expected:
            break
        contiguous.append(bar)
        expected += timedelta(minutes=1)
    normalized = contiguous
    unresolved = "pending_horizon" if cutoff < end and expected == cutoff else "incomplete_bar_history"
    if not normalized:
        return {**base, "status": unresolved if cutoff > first_start else "pending_horizon"}

    fill: float | None = None
    fill_index: int | None = None
    slipped = False
    for index, bar in enumerate(normalized):
        if direction == "LONG":
            if bar["o"] <= stop:
                return {**base, "status": "invalidated_before_entry"}
            if bar["o"] >= target:
                return {**base, "status": "past_target_before_entry"}
            if bar["o"] >= entry:
                fill, fill_index, slipped = bar["o"], index, bar["o"] > entry
                break
            entry_touched, invalidated = bar["h"] >= entry, bar["l"] <= stop
        else:
            if bar["o"] >= stop:
                return {**base, "status": "invalidated_before_entry"}
            if bar["o"] <= target:
                return {**base, "status": "past_target_before_entry"}
            if bar["o"] <= entry:
                fill, fill_index, slipped = bar["o"], index, bar["o"] < entry
                break
            entry_touched, invalidated = bar["l"] <= entry, bar["h"] >= stop
        if entry_touched and invalidated:
            return {**base, "status": "ambiguous_entry_invalidation"}
        if invalidated:
            return {**base, "status": "invalidated_before_entry"}
        if entry_touched:
            fill, fill_index = entry, index
            break
    if fill is None or fill_index is None:
        return {**base, "status": "never_triggered_after_delivery" if expected == end else unresolved}

    risk = (fill - stop) if direction == "LONG" else (stop - fill)
    reward = (target - fill) if direction == "LONG" else (fill - target)
    if risk <= 0:
        return {**base, "status": "invalid_fill_after_stop"}
    if reward <= 0:
        return {**base, "status": "past_target_before_entry"}
    terminal = "time_exit"
    exit_price = normalized[-1]["c"]
    resolved_at = normalized[-1]["t"] + timedelta(minutes=1)
    for bar in normalized[fill_index:]:
        # Once filled, a later open beyond the stop is observed adverse slippage.
        if bar["t"] > normalized[fill_index]["t"] and (bar["o"] <= stop if direction == "LONG" else bar["o"] >= stop):
            terminal, exit_price, resolved_at = "stop", bar["o"], bar["t"]
            break
        if bar["t"] > normalized[fill_index]["t"] and (bar["o"] >= target if direction == "LONG" else bar["o"] <= target):
            terminal, exit_price, resolved_at = "target", target, bar["t"]
            break
        stop_hit = bar["l"] <= stop if direction == "LONG" else bar["h"] >= stop
        target_hit = bar["h"] >= target if direction == "LONG" else bar["l"] <= target
        if stop_hit and target_hit:
            return {
                **base, "status": "ambiguous_exit", "entry_filled": True,
                "fill": round(fill, 4), "slipped_from_trigger": slipped,
            }
        if stop_hit:
            terminal, exit_price, resolved_at = "stop", stop, bar["t"] + timedelta(minutes=1)
            break
        if target_hit:
            terminal, exit_price, resolved_at = "target", target, bar["t"] + timedelta(minutes=1)
            break
    if terminal == "time_exit" and expected != end:
        return {**base, "status": unresolved, "entry_filled": True, "fill": round(fill, 4), "slipped_from_trigger": slipped}
    sign = 1.0 if direction == "LONG" else -1.0
    outcome_r = sign * (exit_price - fill) / risk
    return {
        **base,
        "status": "evaluated",
        "entry_filled": True,
        "first_eligible_bar": first_start.isoformat().replace("+00:00", "Z"),
        "fill_time": normalized[fill_index]["t"].isoformat().replace("+00:00", "Z"),
        "fill": round(fill, 4),
        "slipped_from_trigger": slipped,
        "terminal_event": terminal,
        "exit_underlying": round(exit_price, 4),
        "resolved_at": resolved_at.isoformat().replace("+00:00", "Z"),
        "outcome_r": round(outcome_r, 4),
        "won": outcome_r > 0,
    }


def delivered_alerts(session_date: str) -> list[dict[str, Any]]:
    decisions = {str(row.get("event_id")): row for row in _read_jsonl(DECISION_LEDGER)}
    alerts: list[dict[str, Any]] = []
    for event in _read_jsonl(GOVERNED_EVENTS):
        if not str(event.get("attempted_at") or "").startswith(session_date) or event.get("delivered") is not True:
            continue
        decision = decisions.get(str(event.get("event_id"))) or {}
        candidate = event.get("candidate") if isinstance(event.get("candidate"), Mapping) else decision.get("candidate") if isinstance(decision.get("candidate"), Mapping) else {}
        alerts.append({
            "alert_id": event.get("event_id"), "source": "governed", "attempted_at": event.get("attempted_at"),
            **{key: candidate.get(key) for key in ("symbol", "direction", "setup", "grade", "lane")},
            "entry": candidate.get("trigger"), "stop": candidate.get("stop"), "target": candidate.get("target"),
            "signal_available_at": candidate.get("bar_completed_at"),
            **_delivery_context(event, candidate),
        })
    for source_name, log in [(name, log) for name, path in (("bplus_spotlight", BPLUS_LOG), ("aplus_spotlight", APLUS_LOG)) for log in _read_jsonl(path)]:
        notification = log.get("notification") if isinstance(log.get("notification"), Mapping) else {}
        delivery_stamp = log.get("delivered_at") or log.get("timestamp")
        receipts = {str(row.get("fingerprint")): row for row in notification.get("results", []) if isinstance(row, Mapping)}
        if not str(delivery_stamp or "").startswith(session_date) or (notification.get("status") != "sent" and not receipts):
            continue
        for setup in log.get("setups") or []:
            if not isinstance(setup, Mapping):
                continue
            receipt = receipts.get(str(setup.get("fingerprint")))
            if receipts and (not receipt or not isinstance(receipt.get("result"), Mapping) or receipt["result"].get("sent") is not True):
                continue
            context = _delivery_context(receipt or log, setup)
            if not receipts:
                # Old batch completion stamps are not individual transport receipts.
                context["delivery_timestamp_quality"] = "batch_completion_only"
            alerts.append({
                "alert_id": setup.get("fingerprint"), "source": source_name, "attempted_at": delivery_stamp,
                "symbol": setup.get("symbol"),
                "direction": {"bullish": "LONG", "bearish": "SHORT", "long": "LONG", "short": "SHORT"}.get(str(setup.get("direction") or "").lower(), "UNKNOWN"),
                "setup": setup.get("setup"), "grade": setup.get("grade"), "lane": source_name.upper(),
                "entry": setup.get("entry"), "stop": setup.get("invalidation"), "target": setup.get("target"),
                "signal_available_at": setup.get("confirmation_completed_at"),
                **context,
            })
    for event in _read_jsonl(DAILY_MAP_EVENTS):
        if not str(event.get("attempted_at") or "").startswith(session_date) or event.get("delivered") is not True:
            continue
        if str(event.get("state") or "") != "CONFIRMED":
            continue
        alerts.append({
            "alert_id": event.get("event_id"), "source": "daily_map", "attempted_at": event.get("attempted_at"),
            "symbol": event.get("symbol"), "direction": event.get("direction"), "setup": "daily_map_3m_level_reaction",
            "grade": "SHADOW-3M", "lane": "DAILY_MAP_3M_SHADOW", "entry": event.get("trigger"),
            "stop": event.get("stop"), "target": event.get("target"), "signal_available_at": event.get("bar_completed_at"),
            **_delivery_context(event, event),
        })
    for event in _read_jsonl(SPY_LEVEL_EVENTS):
        attempted = event.get("delivered_at") or event.get("attempted_at")
        if not str(attempted or "").startswith(session_date) or event.get("delivered") is not True:
            continue
        if str(event.get("state") or "") not in {"ARMED", "CONFIRMED", "OBSERVE"}:
            continue
        alerts.append({
            "alert_id": event.get("event_id"), "source": "spy_mapped_level", "attempted_at": attempted,
            "delivered_at": attempted, "symbol": event.get("symbol") or "SPY", "direction": event.get("direction"),
            "setup": "spy_mapped_level_reaction", "grade": "SHADOW-LEVEL", "lane": "SPY_MAPPED_LEVEL_SHADOW",
            "entry": event.get("entry") or event.get("trigger"), "stop": event.get("stop") or event.get("invalidation"),
            "target": event.get("target") or event.get("next_target"), "signal_available_at": event.get("bar_completed_at"),
            "level": event.get("level"), "state": event.get("state"),
            **_delivery_context(event, event),
        })
    return alerts


def fetch_bars(symbols: Iterable[str], session_date: str) -> dict[str, list[dict[str, Any]]]:
    names = sorted({str(symbol).upper() for symbol in symbols if symbol})
    if not names:
        return {}
    day = date.fromisoformat(session_date)
    start = datetime.combine(day, time(9, 30), ET).astimezone(timezone.utc)
    end = datetime.combine(day, time(16, 1), ET).astimezone(timezone.utc)
    requested_feed = str(os.getenv("VIBE_TRADING_STOCK_FEED") or "iex").strip().lower()
    if requested_feed not in {"iex", "sip"}:
        raise ValueError("unsupported_stock_feed")
    params = {
            "symbols": ",".join(names), "timeframe": "1Min",
            "start": start.isoformat().replace("+00:00", "Z"), "end": end.isoformat().replace("+00:00", "Z"),
            "adjustment": "raw", "feed": requested_feed, "limit": 10000, "sort": "asc",
        }
    headers = _credentials()
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    seen_tokens: set[str] = set()
    while True:
        response = requests.get("https://data.alpaca.markets/v2/stocks/bars", headers=headers, params=dict(params), timeout=25)
        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload.get("bars"), Mapping):
            raise ValueError("missing_bars_response")
        for symbol, rows in payload["bars"].items():
            if not isinstance(rows, list):
                raise ValueError("invalid_bars_response")
            grouped[str(symbol).upper()].extend(rows)
        token = payload.get("next_page_token")
        if not token:
            return dict(grouped)
        if token in seen_tokens or len(seen_tokens) >= 1000:
            raise ValueError("incomplete_bar_pagination")
        seen_tokens.add(token)
        params["page_token"] = token


def _group_stats(rows: Iterable[Mapping[str, Any]], key: str) -> list[dict[str, Any]]:
    grouped: dict[str, list[float]] = defaultdict(list)
    for row in rows:
        if row.get("status") == "evaluated" and isinstance(row.get("outcome_r"), (int, float)):
            grouped[str(row.get(key) or "unknown")].append(float(row["outcome_r"]))
    return [
        {
            key: label, "count": len(values), "positive_pct": round(sum(value > 0 for value in values) / len(values) * 100, 2),
            "median_r": round(statistics.median(values), 4), "mean_r": round(statistics.mean(values), 4),
        }
        for label, values in sorted(grouped.items())
    ]


def build_report(session_date: str, *, now: datetime | None = None) -> dict[str, Any]:
    current = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    alerts = delivered_alerts(session_date)
    feed_error = None
    try:
        grouped = fetch_bars((row.get("symbol") for row in alerts), session_date) if alerts else {}
    except (requests.RequestException, ValueError, RuntimeError, OSError) as exc:
        grouped, feed_error = {}, type(exc).__name__
    reviewed = [evaluate_alert(row, grouped.get(str(row.get("symbol") or "").upper(), []), now=current) for row in alerts]
    # Count one underlying plan per 60-minute episode, across delivery channels.
    # Keep every message for the transport audit, but never multiply its evidence.
    unique: dict[tuple[Any, ...], dict[str, Any]] = {}
    latest_plan: dict[tuple[Any, ...], tuple[datetime, dict[str, Any]]] = {}
    for row in sorted(reviewed, key=lambda item: delivered_at(item) or datetime.min.replace(tzinfo=timezone.utc)):
        sent = delivered_at(row)
        identity = (session_date, row.get("symbol"), row.get("direction"), row.get("setup"), *(_number(row.get(key)) for key in ("entry", "stop", "target")))
        previous = latest_plan.get(identity)
        duplicate = sent is not None and previous is not None and sent - previous[0] < timedelta(minutes=HORIZON_MINUTES)
        if duplicate:
            row["duplicate_of"] = previous[1]["outcome_id"]
            row["outcome_id"] = previous[1]["outcome_id"]
        else:
            row["outcome_id"] = hashlib.sha256(json.dumps([identity, sent.isoformat() if sent else row.get("alert_id")], default=str).encode()).hexdigest()
            unique[(*identity, row["outcome_id"])] = row
            if sent:
                latest_plan[identity] = (sent, row)
        row["session_date"] = session_date
        row["calibration_eligible"] = not duplicate and row.get("status") == "evaluated" and row.get("delivery_timestamp_quality") == "exact"
    evaluated = [row for row in unique.values() if row.get("status") == "evaluated" and isinstance(row.get("outcome_r"), (int, float))]
    outcomes = [float(row["outcome_r"]) for row in evaluated]
    delivery_latencies = []
    for row in reviewed:
        sent, available = delivered_at(row), _timestamp(row.get("signal_available_at"))
        if sent is not None and available is not None:
            delivery_latencies.append((sent - available).total_seconds())
    requested_feed = str(os.getenv("VIBE_TRADING_STOCK_FEED") or "iex").strip().lower()
    provider = f"alpaca_{requested_feed}" if requested_feed in {"iex", "sip"} else ""
    chart_aligned: list[dict[str, Any]] = []
    for row in unique.values():
        aligned = align_signal_to_chart(
            {
                **row,
                "signal_id": row.get("outcome_id") or row.get("alert_id"),
                "family_key": row.get("setup"),
                "signal_at": row.get("signal_available_at"),
            },
            grouped.get(str(row.get("symbol") or "").upper(), []),
            provider=provider,
            provider_status="missing" if feed_error or not grouped else "available",
            horizon_bars=30,
        )
        aligned["outcome_id"] = row.get("outcome_id")
        chart_aligned.append(aligned)
        row["chart_alignment"] = aligned
    nomination_evidence = [
        item
        for prior in _read_jsonl(HISTORY_PATH)
        for item in prior.get("chart_aligned_outcomes") or []
        if isinstance(item, Mapping)
    ] + chart_aligned
    recalibration = build_bplus_upgrade_nominations(nomination_evidence, as_of=current)
    half_life_rows = []
    for item in nomination_evidence:
        path = item.get("delivery_path") if isinstance(item.get("delivery_path"), Mapping) else {}
        regime = item.get("regime_bucket") if isinstance(item.get("regime_bucket"), Mapping) else {}
        half_life_rows.append({
            "setup_family": item.get("family_key"),
            "regime": json.dumps(dict(regime), sort_keys=True, separators=(",", ":")),
            "resolved_at": item.get("horizon_resolved_at"),
            # A horizon ending with neither target nor stop is right-censored;
            # do not pretend the observed window was the setup's true lifetime.
            "valid_for_seconds": path.get("valid_for_seconds") if path.get("terminal_event") in {"target", "stop"} else None,
        })
    half_life_models = []
    cohorts = sorted({
        (str(row.get("setup_family") or ""), str(row.get("regime") or ""))
        for row in half_life_rows if row.get("setup_family") and row.get("regime")
    })
    for family, regime in cohorts:
        half_life_models.append(estimate_alert_half_life(
            half_life_rows,
            setup_family=family,
            regime=regime,
            as_of=current,
        ))
    return {
        "schema_version": "discord-alert-chart-review-v2",
        "provider": f"{provider or 'missing'}_completed_1m_signal_and_post_discord_alignment",
        "feed_status": "missing" if feed_error or (alerts and not grouped) else "available" if alerts else "not_requested",
        "feed_error_class": feed_error,
        "outcome_policy": "unique_plan_60m_episode_completed_contiguous_bars_gap_stop_open",
        "session_date": session_date,
        "generated_at": current.isoformat().replace("+00:00", "Z"),
        "chart_validation": {
            "reference": "TradingView one-minute SPY and QQQ charts",
            "status": "visually_cross_checked_2026-09-04" if session_date == "2026-09-04" else "not_manually_cross_checked",
            "timestamp_timezone": "America/New_York",
        },
        "summary": {
            "delivered_trade_alerts": len(reviewed), "unique_trade_candidates": len(unique),
            "duplicate_trade_alerts": len(reviewed) - len(unique), "evaluated": len(evaluated),
            "calibration_eligible": sum(row["calibration_eligible"] for row in reviewed),
            "positive_pct": round(sum(value > 0 for value in outcomes) / len(outcomes) * 100, 2) if outcomes else None,
            "median_r": round(statistics.median(outcomes), 4) if outcomes else None,
            "mean_r": round(statistics.mean(outcomes), 4) if outcomes else None,
            "status_counts": dict(sorted(Counter(str(row.get("status")) for row in reviewed).items())),
            "median_signal_to_discord_seconds": round(statistics.median(delivery_latencies), 3) if delivery_latencies else None,
        },
        "by_setup": _group_stats(unique.values(), "setup"),
        "by_grade": _group_stats(unique.values(), "grade"),
        "by_symbol": _group_stats(unique.values(), "symbol"),
        "chart_aligned_outcomes": chart_aligned,
        "bplus_to_aplus_nominations": recalibration,
        "alert_half_life_models": half_life_models,
        "alerts": reviewed,
        "execution_enabled": False,
        "can_submit_orders": False,
        "warning": "Execution-quality observation only. Results are underlying proxies and never option-contract returns or broker fills.",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--date", default=datetime.now(ET).date().isoformat())
    parser.add_argument("--report-path", type=Path, default=REPORT_PATH)
    parser.add_argument("--print", action="store_true", dest="print_report")
    args = parser.parse_args()
    report = build_report(args.date)
    args.report_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = args.report_path.with_suffix(args.report_path.suffix + ".tmp")
    temporary.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(args.report_path)
    history = {str(row.get("session_date") or ""): row for row in _read_jsonl(HISTORY_PATH) if row.get("session_date")}
    history[report["session_date"]] = report
    HISTORY_PATH.parent.mkdir(parents=True, exist_ok=True)
    history_temp = HISTORY_PATH.with_suffix(HISTORY_PATH.suffix + ".tmp")
    with history_temp.open("w", encoding="utf-8") as handle:
        for key in sorted(history):
            handle.write(json.dumps(history[key], sort_keys=True, separators=(",", ":")) + "\n")
    history_temp.replace(HISTORY_PATH)
    if args.print_report:
        print(json.dumps(report["summary"], indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Export one spreadsheet-friendly daily ledger across trading/context logs."""
from __future__ import annotations

import argparse
import csv
import json
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
VIBE_HOME = Path.home() / ".vibe-trading"
REPORT_DIR = VIBE_HOME / "reports"


def _read_json(path: Path) -> Any:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        raw = raw.strip()
        if not raw:
            continue
        try:
            row = json.loads(raw)
        except json.JSONDecodeError:
            continue
        if isinstance(row, dict):
            rows.append(row)
    return rows


def _event_date(row: dict[str, Any]) -> str:
    for key in ("date", "scan_date", "ts", "timestamp", "checked_at", "opened_at", "closed_at", "entry_date", "created_at"):
        value = row.get(key)
        if value:
            text = str(value)
            return text[:10]
    details = row.get("details") if isinstance(row.get("details"), dict) else {}
    if details.get("checked_at"):
        return str(details["checked_at"])[:10]
    return ""


def _short_json(value: Any, limit: int = 700) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        text = value
    else:
        text = json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)
    text = " ".join(text.split())
    return text[:limit]


def _base_event(day: str, source: str, event_type: str, row: dict[str, Any]) -> dict[str, Any]:
    return {
        "date": day,
        "timestamp": row.get("timestamp") or row.get("ts") or row.get("checked_at") or row.get("opened_at") or row.get("created_at") or row.get("date") or "",
        "source": source,
        "event_type": event_type,
        "strategy": "",
        "symbol": "",
        "side": "",
        "action": "",
        "mode": str(row.get("execution_mode") or row.get("mode") or ""),
        "status": str(row.get("status") or ""),
        "confidence": "",
        "pnl": "",
        "reason": "",
        "notional": "",
        "summary": "",
        "raw": "",
    }


def _matches_day(row: dict[str, Any], day: str) -> bool:
    return _event_date(row) == day


def _flip_events(day: str) -> list[dict[str, Any]]:
    rows = _read_json(VIBE_HOME / "flip-trades.json")
    if not isinstance(rows, list):
        return []
    events = []
    for trade in rows:
        if not isinstance(trade, dict) or not _matches_day(trade, day):
            continue
        event = _base_event(day, "flip_bot", "trade", trade)
        event.update({
            "strategy": trade.get("strategy", ""),
            "symbol": trade.get("symbol", ""),
            "side": trade.get("right", ""),
            "action": trade.get("exit_reason") or "opened",
            "mode": "alpaca",
            "status": trade.get("status", ""),
            "pnl": trade.get("pnl", ""),
            "reason": trade.get("catalyst", ""),
            "notional": trade.get("entry_price", ""),
            "summary": f"{trade.get('contracts', '')}x {trade.get('option_symbol', '')} {trade.get('status', '')}".strip(),
            "raw": _short_json(trade),
        })
        events.append(event)
    return events


def _iwm_events(day: str) -> list[dict[str, Any]]:
    payload = _read_json(VIBE_HOME / "options-trades.json")
    rows = payload.get("trades") if isinstance(payload, dict) else []
    if not isinstance(rows, list):
        return []
    events = []
    for trade in rows:
        if not isinstance(trade, dict) or not _matches_day(trade, day):
            continue
        confidence = trade.get("candidate_confidence") if isinstance(trade.get("candidate_confidence"), dict) else {}
        event = _base_event(day, "iwm_options_bot", "trade", trade)
        event.update({
            "strategy": trade.get("strategy", ""),
            "symbol": trade.get("underlying", ""),
            "action": trade.get("closing_reason") or trade.get("label") or trade.get("status", ""),
            "mode": "alpaca",
            "status": trade.get("status", ""),
            "confidence": confidence.get("score", ""),
            "notional": trade.get("net_credit", ""),
            "summary": f"{trade.get('qty', '')}x {trade.get('label', trade.get('strategy', ''))}".strip(),
            "raw": _short_json(trade),
        })
        events.append(event)
    return events


def _guard_events(day: str) -> list[dict[str, Any]]:
    events = []
    for source, path in (
        ("alpaca_execution_guard", VIBE_HOME / "guard-blocks.jsonl"),
        ("kalshi_execution_guard", VIBE_HOME / "kalshi-guard-blocks.jsonl"),
    ):
        for row in _read_jsonl(path):
            details = row.get("details") if isinstance(row.get("details"), dict) else {}
            merged = {**row, **details}
            if not _matches_day(merged, day):
                continue
            event = _base_event(day, source, "guard_block", merged)
            event.update({
                "strategy": merged.get("bot", ""),
                "symbol": merged.get("symbol") or merged.get("market_ticker") or "",
                "side": merged.get("side", ""),
                "action": merged.get("action", ""),
                "mode": "guard",
                "status": "blocked",
                "confidence": merged.get("confidence", ""),
                "reason": row.get("reason", ""),
                "notional": merged.get("estimated_notional") or merged.get("estimated_notional_dollars") or "",
                "summary": f"blocked: {row.get('reason', '')}",
                "raw": _short_json(row),
            })
            events.append(event)
    return events


def _shadow_events(day: str) -> list[dict[str, Any]]:
    sources = [
        ("rsi2_shadow", ROOT / "data" / "rsi2_shadow_log.jsonl"),
        ("kama_shadow", ROOT / "data" / "kama_shadow_log.jsonl"),
        ("williams_r_shadow", ROOT / "data" / "williams_r_shadow_log.jsonl"),
        ("momentum_shadow", ROOT / "data" / "momentum_shadow_log.jsonl"),
        ("qqq_gld_shadow", ROOT / "data" / "qqq_gld_shadow_log.jsonl"),
        ("ttm_squeeze_shadow", ROOT / "data" / "ttm_squeeze_shadow_log.jsonl"),
        ("wavetrend_shadow", ROOT / "data" / "wavetrend_shadow_log.jsonl"),
        ("smc_shadow", ROOT / "data" / "smc_shadow_log.jsonl"),
        ("flip_shadow_candidates", ROOT / "data" / "flip_shadow_candidates_log.jsonl"),
    ]
    events = []
    for source, path in sources:
        for row in _read_jsonl(path):
            if not _matches_day(row, day):
                continue
            primary = row.get("primary_setup") if isinstance(row.get("primary_setup"), dict) else {}
            event = _base_event(day, source, "shadow_signal", row)
            event.update({
                "strategy": row.get("strategy") or primary.get("name", ""),
                "symbol": row.get("symbol") or row.get("primary_symbol") or primary.get("symbol", ""),
                "action": row.get("action") or primary.get("action") or ",".join(row.get("holdings", []) if isinstance(row.get("holdings"), list) else []),
                "mode": row.get("execution_mode", "shadow_only"),
                "confidence": row.get("confidence") or primary.get("confidence", ""),
                "summary": _short_json(primary or {"holdings": row.get("holdings"), "selected": row.get("selected")}, 300),
                "raw": _short_json(row),
            })
            events.append(event)
    return events


def _context_events(day: str) -> list[dict[str, Any]]:
    sources = [
        ("preopen_sentiment", ROOT / "data" / "preopen_sentiment_log.jsonl", "sentiment_context"),
        ("social_trending", ROOT / "data" / "social_trending_symbols_log.jsonl", "social_context"),
        ("public_social_intake", ROOT / "data" / "public_social_intake_log.jsonl", "social_context"),
        ("deep_liquid_universe", ROOT / "data" / "deep_liquid_universe_scan_log.jsonl", "universe_context"),
        ("moondev_liquidation_context", ROOT / "data" / "moondev_liquidation_context_log.jsonl", "crypto_context"),
        ("limitless_market", ROOT / "data" / "limitless_market_scan_log.jsonl", "prediction_market_context"),
        ("pmxt_schema_probe", ROOT / "data" / "pmxt_market_schema_probe_log.jsonl", "prediction_market_context"),
        ("gex_scanner", ROOT / "data" / "gex_scan_log.jsonl", "options_context"),
        ("ivr_scanner", ROOT / "data" / "iv_history_log.jsonl", "options_context"),
        ("ivr_quality_report", ROOT / "data" / "ivr_quality_report_log.jsonl", "intelligence_review"),
        ("rv_iv_regime", ROOT / "data" / "rv_iv_regime_log.jsonl", "market_regime_context"),
        ("hurst_regime", ROOT / "data" / "hurst_regime_log.jsonl", "market_regime_context"),
        ("opening_range_breadth", ROOT / "data" / "opening_range_breadth_log.jsonl", "market_breadth_context"),
        ("relative_volume", ROOT / "data" / "relative_volume_scan_log.jsonl", "volume_context"),
        ("sec_insider_buying", ROOT / "data" / "sec_insider_buying_log.jsonl", "fundamental_context"),
        ("market_force_score", ROOT / "data" / "market_force_score_log.jsonl", "market_force_context"),
        ("distribution_days", ROOT / "data" / "distribution_day_log.jsonl", "market_regime_context"),
        ("market_breadth", ROOT / "data" / "market_breadth_uptrend_log.jsonl", "market_breadth_context"),
        ("sector_rotation", ROOT / "data" / "sector_rotation_rank_log.jsonl", "sector_rotation_context"),
        ("portfolio_concentration", ROOT / "data" / "portfolio_concentration_log.jsonl", "risk_context"),
        ("exposure_coach", ROOT / "data" / "exposure_coach_log.jsonl", "exposure_review"),
        ("bot_status_snapshot", ROOT / "data" / "bot_status_snapshot_log.jsonl", "status_review"),
        ("regime_memory", ROOT / "data" / "regime_memory_log.jsonl", "intelligence_review"),
        ("rejected_trade_intelligence", ROOT / "data" / "rejected_trade_intelligence_log.jsonl", "intelligence_review"),
        ("needs_review_queue", ROOT / "data" / "needs_review_queue_log.jsonl", "intelligence_review"),
        ("signal_stack_grades", ROOT / "data" / "signal_stack_grades_log.jsonl", "intelligence_review"),
        ("daily_eod_summary", ROOT / "data" / "daily_eod_summary_log.jsonl", "intelligence_review"),
        ("nightly_research_loop", ROOT / "data" / "nightly_research_queue_log.jsonl", "intelligence_review"),
        ("closed_trade_postmortem", ROOT / "data" / "closed_trade_postmortem_log.jsonl", "trade_review"),
        ("daily_outcome_review", ROOT / "data" / "daily_outcome_review_log.jsonl", "outcome_review"),
        ("flip_shadow_pnl_evaluator", ROOT / "data" / "flip_shadow_pnl_evaluation_log.jsonl", "shadow_outcome_review"),
        ("weekly_hot_instruments", ROOT / "data" / "weekly_hot_instrument_log.jsonl", "social_liquidity_review"),
    ]
    events = []
    for source, path, event_type in sources:
        for row in _read_jsonl(path):
            if not _matches_day(row, day):
                continue
            event = _base_event(day, source, event_type, row)
            if source == "social_trending":
                symbols = [item.get("symbol") for item in row.get("symbols", [])[:8] if isinstance(item, dict)]
                event.update({"action": row.get("intraday_slot_label", ""), "summary": "top: " + ",".join(symbols)})
            elif source == "public_social_intake":
                symbols = list((row.get("by_symbol") or {}).keys())[:8] if isinstance(row.get("by_symbol"), dict) else []
                event.update({
                    "action": f"new={row.get('new_observation_count', 0)}",
                    "summary": "reddit cashtags: " + ",".join(symbols),
                })
            elif source == "deep_liquid_universe":
                symbols = [item.get("symbol") for item in row.get("top_candidates", [])[:8] if isinstance(item, dict)]
                event.update({
                    "action": f"candidates={row.get('candidate_count', 0)}",
                    "summary": "top: " + ",".join(symbols),
                })
            elif source == "preopen_sentiment":
                event.update({"action": (row.get("aggregate") or {}).get("bias", ""), "summary": _short_json(row.get("aggregate"))})
            elif source == "limitless_market":
                event.update({"summary": f"markets={row.get('markets_scanned')} poly_arb={row.get('poly_arbitrage_count')} whales={row.get('whale_event_count')}"})
            elif source == "moondev_liquidation_context":
                liq = row.get("liquidations") if isinstance(row.get("liquidations"), dict) else {}
                event.update({
                    "action": row.get("market_bias") or row.get("status", ""),
                    "status": row.get("status", ""),
                    "summary": f"pressure={row.get('liquidation_pressure')} volume={liq.get('total_volume_usd')} hlp={(row.get('hlp_sentiment') or {}).get('bias') if isinstance(row.get('hlp_sentiment'), dict) else ''}",
                })
            elif source == "pmxt_schema_probe":
                event.update({
                    "action": row.get("recommendation", ""),
                    "summary": f"ok={row.get('ok_venue_count')} schema={row.get('avg_schema_score')} status={row.get('status')}",
                })
            elif source == "opening_range_breadth":
                aggregate = row.get("aggregate") if isinstance(row.get("aggregate"), dict) else {}
                event.update({"action": aggregate.get("bias", ""), "summary": _short_json(aggregate)})
            elif source == "rv_iv_regime":
                aggregate = row.get("aggregate") if isinstance(row.get("aggregate"), dict) else {}
                event.update({
                    "action": aggregate.get("bias", ""),
                    "confidence": aggregate.get("score", ""),
                    "summary": f"regime={aggregate.get('regime')} avg_ratio={aggregate.get('avg_ratio')} votes={_short_json(aggregate.get('votes'), 220)}",
                })
            elif source == "hurst_regime":
                aggregate = row.get("aggregate") if isinstance(row.get("aggregate"), dict) else {}
                event.update({
                    "action": aggregate.get("bias", ""),
                    "confidence": aggregate.get("score", ""),
                    "summary": f"regime={aggregate.get('regime')} avg_hurst={aggregate.get('avg_hurst')} votes={_short_json(aggregate.get('votes'), 220)}",
                })
            elif source == "relative_volume":
                symbols = [item.get("symbol") for item in row.get("unusual_symbols", [])[:8] if isinstance(item, dict)]
                event.update({"action": f"unusual={row.get('unusual_count', 0)}", "summary": "unusual: " + ",".join(symbols)})
            elif source == "sec_insider_buying":
                symbols = [item.get("symbol") for item in row.get("signals", [])[:8] if isinstance(item, dict)]
                event.update({"action": f"signals={row.get('signal_count', 0)}", "summary": "buys: " + ",".join(symbols)})
            elif source == "market_force_score":
                event.update({
                    "action": row.get("classification", ""),
                    "confidence": row.get("confidence", ""),
                    "summary": f"score={row.get('total_score')} coverage={(row.get('coverage') or {}).get('available_forces')}/{(row.get('coverage') or {}).get('total_forces')}",
                })
            elif source == "distribution_days":
                aggregate = row.get("aggregate") if isinstance(row.get("aggregate"), dict) else {}
                event.update({"action": aggregate.get("regime", ""), "summary": _short_json(aggregate)})
            elif source == "market_breadth":
                breadth = row.get("breadth") if isinstance(row.get("breadth"), dict) else {}
                event.update({
                    "action": breadth.get("uptrend_status", ""),
                    "summary": f"force={row.get('force_score')} above50={breadth.get('pct_above_50dma')} above200={breadth.get('pct_above_200dma')}",
                })
            elif source == "sector_rotation":
                rotation = row.get("rotation") if isinstance(row.get("rotation"), dict) else {}
                top = [item.get("symbol") for item in rotation.get("top5", [])[:5] if isinstance(item, dict)]
                event.update({
                    "action": rotation.get("leadership", ""),
                    "summary": f"force={row.get('force_score')} top={','.join(top)}",
                })
            elif source == "portfolio_concentration":
                concentration = row.get("concentration") if isinstance(row.get("concentration"), dict) else {}
                event.update({
                    "action": concentration.get("risk_level", ""),
                    "summary": (
                        f"gross={concentration.get('gross_pct_equity')}% "
                        f"beta={concentration.get('net_directional_beta_pct_equity')}% "
                        f"warnings={','.join(concentration.get('warnings', [])[:3])}"
                    ),
                })
            elif source == "exposure_coach":
                event.update({
                    "action": row.get("posture", ""),
                    "confidence": row.get("score", ""),
                    "summary": _short_json(row.get("advisory_settings"), 300),
                })
            elif source == "bot_status_snapshot":
                event.update({
                    "action": row.get("status", ""),
                    "confidence": (row.get("market_force") or {}).get("confidence", ""),
                    "summary": (
                        f"health={(row.get('health') or {}).get('status')} "
                        f"market={(row.get('market_force') or {}).get('classification')} "
                        f"exposure={(row.get('exposure') or {}).get('posture')}"
                    ),
                })
            elif source == "regime_memory":
                event.update({
                    "action": "enough_data" if row.get("enough_data") else "log_building",
                    "summary": f"days={row.get('day_count')} groups={len(row.get('regime_groups') or {})}",
                })
            elif source == "rejected_trade_intelligence":
                event.update({
                    "action": f"blocks={row.get('block_count', 0)}",
                    "summary": f"verdicts={_short_json(row.get('by_verdict'), 220)}",
                })
            elif source == "needs_review_queue":
                event.update({
                    "action": f"queue={row.get('queue_count', 0)}",
                    "summary": f"priorities={_short_json(row.get('by_priority'), 220)} reasons={_short_json(row.get('by_reason'), 220)}",
                })
            elif source == "signal_stack_grades":
                event.update({
                    "action": f"ready={row.get('promotion_ready_count', 0)}",
                    "summary": f"grades={_short_json(row.get('by_grade'), 220)} stages={_short_json(row.get('by_maturity_stage'), 220)}",
                })
            elif source == "daily_eod_summary":
                headline = row.get("plain_english", {}).get("headline") if isinstance(row.get("plain_english"), dict) else ""
                event.update({
                    "action": row.get("verdict", ""),
                    "summary": headline,
                })
            elif source == "nightly_research_loop":
                active = row.get("active_tasks") if isinstance(row.get("active_tasks"), list) else []
                first = active[0] if active and isinstance(active[0], dict) else {}
                event.update({
                    "action": f"active={len(active)}",
                    "confidence": row.get("max_active_tasks", ""),
                    "summary": first.get("title") or "No active nightly task.",
                })
            elif source == "closed_trade_postmortem":
                event.update({
                    "action": f"closed={row.get('closed_trade_count', 0)}",
                    "confidence": row.get("avg_score", ""),
                    "summary": _short_json(row.get("postmortems", [])[:3], 500),
                })
            elif source == "daily_outcome_review":
                event.update({
                    "action": row.get("verdict", ""),
                    "confidence": row.get("review_score", ""),
                    "summary": f"posture={row.get('posture')} pnl={(row.get('event_summary') or {}).get('realized_pnl')} blocks={(row.get('event_summary') or {}).get('guard_block_count')}",
                })
            elif source == "flip_shadow_pnl_evaluator":
                event.update({
                    "action": "evaluate_shadow_candidates",
                    "confidence": row.get("win_rate", ""),
                    "pnl": row.get("total_hypothetical_pnl", ""),
                    "summary": f"samples={row.get('sample_count')} completed={row.get('completed_count')} top={_short_json((row.get('top_trades') or [])[:3], 260)}",
                })
            elif source == "weekly_hot_instruments":
                event.update({
                    "action": f"priority={row.get('priority_count', 0)}",
                    "confidence": row.get("candidate_count", ""),
                    "summary": f"top={_short_json((row.get('hot_instruments') or [])[:5], 360)}",
                })
            else:
                event.update({"summary": _short_json(row, 300)})
            event["raw"] = _short_json(row)
            events.append(event)
    return events


def collect_events(day: str) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    for collector in (_flip_events, _iwm_events, _guard_events, _shadow_events, _context_events):
        events.extend(collector(day))
    events.sort(key=lambda event: (str(event.get("timestamp") or ""), event["source"], event["event_type"]))
    return events


def export_csv(events: list[dict[str, Any]], output_path: Path) -> Path:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = [
        "date", "timestamp", "source", "event_type", "strategy", "symbol", "side",
        "action", "mode", "status", "confidence", "pnl", "reason", "notional",
        "summary", "raw",
    ]
    with output_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for event in events:
            writer.writerow({key: event.get(key, "") for key in fieldnames})
    return output_path


def default_output_path(day: str) -> Path:
    return REPORT_DIR / f"daily-bot-activity-{day}.csv"


def print_summary(day: str, events: list[dict[str, Any]], path: Path) -> None:
    counts: dict[str, int] = {}
    for event in events:
        counts[event["event_type"]] = counts.get(event["event_type"], 0) + 1
    print(f"\nDaily Bot Activity CSV | {day}")
    print("=" * 72)
    print(f"events={len(events)} counts={counts}")
    print(f"CSV: {path}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--date", default=date.today().isoformat(), help="YYYY-MM-DD, default today")
    parser.add_argument("--output", type=Path, default=None)
    args = parser.parse_args()
    events = collect_events(args.date)
    output = args.output or default_output_path(args.date)
    export_csv(events, output)
    print_summary(args.date, events, output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

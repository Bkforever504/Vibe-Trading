#!/usr/bin/env python3
"""Generate a self-contained read-only Vibe Trading dashboard.

This script reads existing JSON/JSONL/CSV artifacts and writes one static HTML
file. It never calls a broker, starts a server, or changes bot settings.
"""
from __future__ import annotations

import argparse
import csv
import html
import json
import math
import os
import re
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

try:
    from options_reporting import dedupe_options_trade_records
except ModuleNotFoundError:
    from scripts.options_reporting import dedupe_options_trade_records

ROOT = Path(__file__).resolve().parent.parent
VIBE_HOME = Path.home() / ".vibe-trading"
REPORT_DIR = VIBE_HOME / "reports"
OUTPUT_PATH = VIBE_HOME / "dashboard.html"
ET = ZoneInfo("America/New_York")

FLIP_TRADES_PATH = VIBE_HOME / "flip-trades.json"
OPTIONS_TRADES_PATH = VIBE_HOME / "options-trades.json"
POSITION_SIZING_LOG = ROOT / "data" / "position_sizing_sanity_log.jsonl"
BOT_STATUS_LOG = ROOT / "data" / "bot_status_snapshot_log.jsonl"
SIGNAL_GRADES_LOG = ROOT / "data" / "signal_stack_grades_log.jsonl"
SOCIAL_REPLAY_QUEUE = ROOT / "data" / "social_replay_queue.jsonl"
PRIORITY_SWING_EVENT_LOG = ROOT / "data" / "priority_swing_observation_events.jsonl"
DATABENTO_CALL_LEDGER = VIBE_HOME / "data" / "databento_call_ledger.jsonl"
SOCIAL_GAP_MATCH_REPORT = ROOT / "research" / "social_trader_signal_gap_match_2026-09-01.json"
SESSION_FOCUS_SYMBOLS = ("NVDA", "GOOGL", "AAPL", "META")

REPORTS = {
    "agent_reach_research": REPORT_DIR / "agent-reach-trading-research.json",
    "bot_status": REPORT_DIR / "bot-status-snapshot.json",
    "daily_eod": REPORT_DIR / "daily-eod-summary.json",
    "grades": REPORT_DIR / "signal-stack-grades.json",
    "health": REPORT_DIR / "signal-stack-health.json",
    "leaderboard": REPORT_DIR / "signal-stack-leaderboard.json",
    "audit": REPORT_DIR / "execution-gate-audit.json",
    "review": REPORT_DIR / "needs-review-queue.json",
    "schedule": REPORT_DIR / "market-schedule-alignment.json",
    "hot": REPORT_DIR / "weekly-hot-instruments.json",
    "portfolio": REPORT_DIR / "portfolio-concentration.json",
    "shadow_pnl": REPORT_DIR / "flip-shadow-pnl-evaluator.json",
    "shadow_consensus": REPORT_DIR / "shadow-consensus-gate.json",
    "governed_shadow": REPORT_DIR / "governed-shadow-decisions.json",
    "governed_alert": REPORT_DIR / "governed-shadow-alert-delivery.json",
    "governed_lifecycle": REPORT_DIR / "governed-shadow-lifecycle.json",
    "governed_outcomes": REPORT_DIR / "governed-shadow-outcomes.json",
    "discord_chart_review": REPORT_DIR / "discord-alert-chart-review.json",
    "execution_readiness": REPORT_DIR / "execution-readiness.json",
    "latency_budget": REPORT_DIR / "latency-budget-scorecard.json",
    "statistical_governance": REPORT_DIR / "statistical-governance.json",
    "scanner_evidence": REPORT_DIR / "scanner-evidence-collection.json",
    "feed_reference": REPORT_DIR / "scanner-feed-reference-study.json",
    "governed_rules": REPORT_DIR / "governed-shadow-rule-updates.json",
    "institutional_confluence": REPORT_DIR / "institutional-confluence-shadow.json",
    "premarket_thesis": REPORT_DIR / "premarket-thesis-shadow.json",
    "candlestick_context": REPORT_DIR / "candlestick-context.json",
    "higher_timeframe": REPORT_DIR / "higher-timeframe-market-map.json",
    "market_catalyst": REPORT_DIR / "market-catalyst-calendar.json",
    "daily_edge": REPORT_DIR / "daily-edge-orchestrator.json",
    "options_heatmap": REPORT_DIR / "options-liquidation-heatmap.json",
    "options_quant_risk": REPORT_DIR / "options-quant-risk-budget.json",
    "kronos_forecast": REPORT_DIR / "kronos-market-forecast.json",
    "cheap_asymmetry": REPORT_DIR / "cheap-asymmetry-scanner.json",
    "learning": REPORT_DIR / "flip-bot-learning-report.json",
    "creator_watchlist": REPORT_DIR / "creator-watchlist-runner-scanner.json",
    "alpha_factory": REPORT_DIR / "nightly-alpha-factory.json",
    "loop_closure": REPORT_DIR / "loop-closure-report.json",
    "loop_readiness": REPORT_DIR / "loop-readiness-audit.json",
    "mahoraga": REPORT_DIR / "mahoraga-repo-intake-audit.json",
    "openalice": REPORT_DIR / "openalice-repo-intake-audit.json",
    "incentive_safety": REPORT_DIR / "agent-incentive-safety-audit.json",
    "activity": REPORT_DIR / "daily-bot-activity-2026-07-03.csv",
    "aplus_spotlight": REPORT_DIR / "aplus-spotlight.json",
    "bplus_spotlight": REPORT_DIR / "bplus-spotlight.json",
    "economic_ranking_regret": REPORT_DIR / "economic-ranking-regret.json",
    "aplus_contract_feasibility": REPORT_DIR / "aplus-contract-feasibility.json",
    "aplus_market_context": REPORT_DIR / "aplus-market-context.json",
    "footprint_evidence": REPORT_DIR / "footprint-evidence-shadow.json",
    "spy_level_reaction": REPORT_DIR / "spy-level-reaction-shadow.json",
    "spy_level_outcomes": REPORT_DIR / "spy-level-reaction-outcomes.json",
    "adversarial_audit": REPORT_DIR / "adversarial-strategy-audit.json",
    "elite_readiness": REPORT_DIR / "elite-bot-readiness-scorecard.json",
    "shadow_audit": REPORT_DIR / "shadow-logger-audit.json",
    "operational_gate": REPORT_DIR / "operational-readiness-gate.json",
    "premarket_readiness": REPORT_DIR / "premarket-operational-readiness.json",
    "multi_timeframe_edge": REPORT_DIR / "multi-timeframe-edge-tournament.json",
    "trader_barbie_3m": REPORT_DIR / "trader-barbie-3m-ce-lab.json",
    "strategy_concept_coverage": REPORT_DIR / "strategy-concept-coverage-audit.json",
    "uncovered_concept_tournament": REPORT_DIR / "uncovered-concept-tournament.json",
    "daily_rsi2_200sma": REPORT_DIR / "daily-rsi2-200sma-hold-tournament.json",
    "intraday_radar": REPORT_DIR / "intraday-opportunity-radar.json",
    "intraday_sector_posture": REPORT_DIR / "intraday-sector-posture.json",
    "intraday_lifecycle_shadow": REPORT_DIR / "intraday-trade-lifecycle-shadow.json",
    "simple_price_action_alerts": REPORT_DIR / "simple-price-action-alerts.json",
    "wolves_bbr_shadow": REPORT_DIR / "wolves-bbr-shadow.json",
    "banks_821_shadow": REPORT_DIR / "banks-821-control-shadow.json",
    "donchian_expansion_shadow": REPORT_DIR / "donchian-expansion-shadow.json",
    "donchian_expansion_forward_shadow": REPORT_DIR / "donchian-expansion-forward-shadow.json",
    "liquid_signal_chart_audit": REPORT_DIR / "liquid-signal-chart-audit.json",
    "spy_5m_0dte_orb": REPORT_DIR / "spy-5m-0dte-orb-shadow.json",
    "continuous_improvement": REPORT_DIR / "continuous-improvement-scorecard.json",
    "daily_move_coverage_review": REPORT_DIR / "daily-move-coverage-review.json",
    "priority_swing_observation": REPORT_DIR / "priority-swing-observation.json",
    "operational_runs": REPORT_DIR / "operational-run-health.json",
    "daily_level_map_shadow": REPORT_DIR / "daily-level-map-shadow.json",
}


def safe_float(value: Any, default: float = 0.0) -> float:
    try:
        if value in (None, ""):
            return default
        parsed = float(value)
        return parsed if math.isfinite(parsed) else default
    except (TypeError, ValueError):
        return default


def safe_int(value: Any, default: int = 0) -> int:
    try:
        if value in (None, ""):
            return default
        return int(float(value))
    except (TypeError, ValueError):
        return default


def money(value: Any, *, unknown: str = "n/a") -> str:
    if value in (None, ""):
        return unknown
    parsed = safe_float(value)
    sign = "-" if parsed < 0 else ""
    return f"{sign}${abs(parsed):,.2f}"


def pct(value: Any, *, scale: bool = False, unknown: str = "n/a") -> str:
    if value in (None, ""):
        return unknown
    parsed = safe_float(value)
    if scale:
        parsed *= 100
    return f"{parsed:,.1f}%"


def esc(value: Any) -> str:
    return html.escape(str(value if value is not None else ""))


def load_json(path: Path, fallback: Any) -> Any:
    if not path.exists():
        return fallback
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        return fallback


def read_jsonl_latest(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    latest: dict[str, Any] = {}
    try:
        for raw in path.read_text(encoding="utf-8-sig").splitlines():
            raw = raw.strip()
            if not raw:
                continue
            row = json.loads(raw)
            if isinstance(row, dict):
                latest = row
    except (OSError, json.JSONDecodeError):
        return latest
    return latest


def read_jsonl_rows(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    try:
        for raw in path.read_text(encoding="utf-8-sig").splitlines():
            raw = raw.strip()
            if not raw:
                continue
            row = json.loads(raw)
            if isinstance(row, dict):
                rows.append(row)
    except (OSError, json.JSONDecodeError):
        return rows
    return rows


def _date_key(value: Any) -> str:
    text = str(value or "")[:10]
    return text if re.match(r"^\d{4}-\d{2}-\d{2}$", text) else ""


def latest_activity_csv(report_dir: Path = REPORT_DIR) -> Path | None:
    files = sorted(report_dir.glob("daily-bot-activity-*.csv"), key=lambda p: p.name)
    return files[-1] if files else None


def load_activity(path: Path | None) -> list[dict[str, Any]]:
    if not path or not path.exists():
        return []
    try:
        with path.open("r", encoding="utf-8-sig", newline="") as f:
            return [dict(row) for row in csv.DictReader(f)]
    except OSError:
        return []


def cls_for_signed(value: Any) -> str:
    return "good" if safe_float(value) >= 0 else "bad"


def cls_for_grade(value: Any) -> str:
    grade = str(value or "").upper()
    if grade in {"A", "B"}:
        return "good"
    if grade in {"C", "D"}:
        return "warn"
    return "bad"


def cls_for_health(value: Any) -> str:
    text = str(value or "").lower()
    if text in {"ok", "fresh", "pass", "passed", "clear", "normal", "off"}:
        return "good"
    if text in {"stale", "aging", "watch", "action_required", "cautious"}:
        return "warn"
    return "bad"


def grade_counts_text(counts: dict[str, Any]) -> str:
    parts = [f"{key} {counts[key]}" for key in sorted(counts) if safe_int(counts.get(key)) > 0]
    return " / ".join(parts) if parts else "none"


def flip_trade_stats(trades: list[dict[str, Any]]) -> dict[str, Any]:
    closed = [t for t in trades if t.get("status") == "closed"]
    open_trades = [t for t in trades if t.get("status") != "closed"]
    pnls = [safe_float(t.get("pnl")) for t in closed if t.get("pnl") is not None]
    wins = [p for p in pnls if p > 0]
    post = [t for t in closed if str(t.get("entry_date") or "")[:10] >= "2026-06-29"]
    post_pnls = [safe_float(t.get("pnl")) for t in post if t.get("pnl") is not None]
    return {
        "total": len(trades),
        "closed": len(closed),
        "open": len(open_trades),
        "pnl": sum(pnls),
        "win_rate": len(wins) / len(pnls) if pnls else 0.0,
        "best": max(pnls) if pnls else None,
        "worst": min(pnls) if pnls else None,
        "post_count": len(post),
        "post_pnl": sum(post_pnls),
        "post_win_rate": len([p for p in post_pnls if p > 0]) / len(post_pnls) if post_pnls else 0.0,
    }


def parse_credit_pnl_estimate(trade: dict[str, Any]) -> float | None:
    if trade.get("pnl") not in (None, ""):
        return safe_float(trade.get("pnl"))
    reason = str(trade.get("closing_reason") or "")
    credit = safe_float(trade.get("net_credit"))
    qty = safe_float(trade.get("qty"), 1.0)
    if not reason or credit <= 0:
        return None
    match = re.search(r"([+-]?\d+(?:\.\d+)?)% of credit", reason)
    if not match:
        return None
    return round(credit * qty * 100 * safe_float(match.group(1)) / 100, 2)


def option_pnl_provenance(trade: dict[str, Any]) -> str:
    """Classify an options outcome without presenting an estimate as a fill."""
    if trade.get("pnl") not in (None, ""):
        return "reconciled"
    if parse_credit_pnl_estimate(trade) is not None:
        return "estimated_from_exit_rule"
    return "unreconciled"


def option_trade_stats(state: dict[str, Any], positions: list[dict[str, Any]]) -> dict[str, Any]:
    trades = state.get("trades") if isinstance(state.get("trades"), list) else []
    closed = [t for t in trades if t.get("status") == "closed"]
    open_trades = [t for t in trades if t.get("status") != "closed"]
    estimates = [parse_credit_pnl_estimate(t) for t in closed]
    known = [p for p in estimates if p is not None]
    unrealized = sum(safe_float(p.get("unrealized_pl")) for p in positions)
    wins = [p for p in known if p > 0]
    return {
        "total": len(trades),
        "closed": len(closed),
        "open": len(open_trades),
        "realized_est": sum(known),
        "unrealized": unrealized,
        "win_rate": len(wins) / len(known) if known else None,
        "known_pnl_count": len(known),
        "estimated_pnl_count": sum(1 for t in closed if option_pnl_provenance(t) == "estimated_from_exit_rule"),
        "reconciled_pnl_count": sum(1 for t in closed if option_pnl_provenance(t) == "reconciled"),
        "unreconciled_pnl_count": sum(1 for t in closed if option_pnl_provenance(t) == "unreconciled"),
    }


def iwm_open_unrealized(trade: dict[str, Any], positions_by_symbol: dict[str, dict[str, Any]]) -> float | None:
    legs = trade.get("legs") if isinstance(trade.get("legs"), list) else []
    if not legs:
        return None
    matched = [positions_by_symbol.get(str(leg)) for leg in legs]
    matched = [p for p in matched if p]
    if not matched:
        return None
    return round(sum(safe_float(p.get("unrealized_pl")) for p in matched), 2)


def cumulative_trade_series(
    trades: list[dict[str, Any]],
    pnl_getter,
    date_fields: tuple[str, ...],
) -> list[dict[str, Any]]:
    dated: list[tuple[str, float]] = []
    for trade in trades:
        pnl = pnl_getter(trade)
        if pnl is None:
            continue
        day = ""
        for field in date_fields:
            day = _date_key(trade.get(field))
            if day:
                break
        if day:
            dated.append((day, float(pnl)))
    cumulative = 0.0
    series: list[dict[str, Any]] = []
    for day, pnl in sorted(dated):
        cumulative += pnl
        series.append({"time": day, "value": round(cumulative, 2)})
    return series


def latest_value_by_day(rows: list[dict[str, Any]], value_getter) -> list[dict[str, Any]]:
    by_day: dict[str, float] = {}
    for row in rows:
        day = _date_key(row.get("date") or row.get("timestamp") or row.get("generated_at"))
        value = value_getter(row)
        if day and value is not None:
            by_day[day] = round(float(value), 2)
    return [{"time": day, "value": value} for day, value in sorted(by_day.items())]


def build_chart_data(model: dict[str, Any]) -> dict[str, Any]:
    flip_trades = model["flip_trades"] if isinstance(model["flip_trades"], list) else []
    options_state = model["options_state"] if isinstance(model["options_state"], dict) else {}
    option_trades = options_state.get("trades") if isinstance(options_state.get("trades"), list) else []
    bot_rows = read_jsonl_rows(BOT_STATUS_LOG)
    grade_rows = read_jsonl_rows(SIGNAL_GRADES_LOG)
    hot = model["hot"] if isinstance(model["hot"], dict) else {}
    hot_instruments = hot.get("hot_instruments") if isinstance(hot.get("hot_instruments"), list) else []

    account_equity = latest_value_by_day(
        bot_rows,
        lambda row: (row.get("account") or {}).get("equity") if isinstance(row.get("account"), dict) else None,
    )
    health_error = latest_value_by_day(
        bot_rows,
        lambda row: (row.get("health") or {}).get("error") if isinstance(row.get("health"), dict) else None,
    )
    health_stale = latest_value_by_day(
        bot_rows,
        lambda row: (row.get("health") or {}).get("stale") if isinstance(row.get("health"), dict) else None,
    )
    ops_a = latest_value_by_day(
        grade_rows,
        lambda row: (row.get("by_ops_grade") or {}).get("A") if isinstance(row.get("by_ops_grade"), dict) else None,
    )
    evidence_f = latest_value_by_day(
        grade_rows,
        lambda row: (row.get("by_grade") or {}).get("F") if isinstance(row.get("by_grade"), dict) else None,
    )

    hot_ranked = []
    for item in hot_instruments[:12]:
        if not isinstance(item, dict):
            continue
        hot_ranked.append({
            "symbol": str(item.get("symbol") or ""),
            "hot_score": round(safe_float(item.get("hot_score")), 2),
            "hypothetical_pnl": round(safe_float(item.get("total_hypothetical_pnl")), 2),
            "best_return_pct": round(safe_float(item.get("best_shadow_return_pct")), 2),
            "action": str(item.get("action") or ""),
        })

    return {
        "accountEquity": account_equity,
        "flipPnl": cumulative_trade_series(
            flip_trades,
            lambda trade: safe_float(trade.get("pnl")) if trade.get("pnl") not in (None, "") else None,
            ("exit_date", "entry_date"),
        ),
        "iwmPnl": cumulative_trade_series(
            option_trades,
            parse_credit_pnl_estimate,
            ("closed_at", "opened_at"),
        ),
        "healthError": health_error,
        "healthStale": health_stale,
        "opsA": ops_a,
        "evidenceF": evidence_f,
        "hotRanked": hot_ranked,
    }


def load_model(paths: dict[str, Path] = REPORTS) -> dict[str, Any]:
    portfolio = load_json(paths["portfolio"], {})
    positions = []
    if isinstance(portfolio, dict):
        concentration = portfolio.get("concentration") if isinstance(portfolio.get("concentration"), dict) else {}
        positions = concentration.get("positions") if isinstance(concentration.get("positions"), list) else []
    activity_path = latest_activity_csv()
    options_state = load_json(OPTIONS_TRADES_PATH, {})
    if isinstance(options_state, dict) and isinstance(options_state.get("trades"), list):
        options_state = {**options_state, "trades": dedupe_options_trade_records(options_state["trades"])}
    model = {
        "generated_at": datetime.now(timezone.utc).astimezone().strftime("%Y-%m-%d %H:%M:%S %Z"),
        "bot_status": load_json(paths["bot_status"], {}),
        "daily_eod": load_json(paths["daily_eod"], {}),
        "grades": load_json(paths["grades"], {}),
        "health": load_json(paths["health"], {}),
        "leaderboard": load_json(paths["leaderboard"], {}),
        "audit": load_json(paths["audit"], {}),
        "review": load_json(paths["review"], {}),
        "schedule": load_json(paths["schedule"], {}),
        "hot": load_json(paths["hot"], {}),
        "portfolio": portfolio,
        "positions": positions,
        "position_sizing": read_jsonl_latest(POSITION_SIZING_LOG),
        "shadow_pnl": load_json(paths["shadow_pnl"], {}),
        "shadow_consensus": load_json(paths["shadow_consensus"], {}),
        "governed_shadow": load_json(paths["governed_shadow"], {}),
        "governed_alert": load_json(paths["governed_alert"], {}),
        "governed_lifecycle": load_json(paths["governed_lifecycle"], {}),
        "governed_outcomes": load_json(paths["governed_outcomes"], {}),
        "discord_chart_review": load_json(paths.get("discord_chart_review", REPORTS["discord_chart_review"]), {}),
        "execution_readiness": load_json(paths.get("execution_readiness", REPORTS["execution_readiness"]), {}),
        "latency_budget": load_json(paths.get("latency_budget", REPORTS["latency_budget"]), {}),
        "statistical_governance": load_json(paths.get("statistical_governance", REPORTS["statistical_governance"]), {}),
        "scanner_evidence": load_json(paths.get("scanner_evidence", REPORTS["scanner_evidence"]), {}),
        "feed_reference": load_json(paths.get("feed_reference", REPORTS["feed_reference"]), {}),
        "governed_rules": load_json(paths["governed_rules"], {}),
        "institutional_confluence": load_json(paths["institutional_confluence"], {}),
        "premarket_thesis": load_json(paths.get("premarket_thesis", REPORTS["premarket_thesis"]), {}),
        "databento_call_ledger": read_jsonl_rows(
            paths.get("databento_call_ledger", DATABENTO_CALL_LEDGER)
        ),
        "candlestick_context": load_json(paths["candlestick_context"], {}),
        "higher_timeframe": load_json(paths["higher_timeframe"], {}),
        "market_catalyst": load_json(paths["market_catalyst"], {}),
        "daily_edge": load_json(paths["daily_edge"], {}),
        "options_heatmap": load_json(paths["options_heatmap"], {}),
        "options_quant_risk": load_json(paths["options_quant_risk"], {}),
        "kronos_forecast": load_json(paths["kronos_forecast"], {}),
        "cheap_asymmetry": load_json(paths["cheap_asymmetry"], {}),
        "learning": load_json(paths["learning"], {}),
        "creator_watchlist": load_json(paths["creator_watchlist"], {}),
        "alpha_factory": load_json(paths["alpha_factory"], {}),
        "loop_closure": load_json(paths["loop_closure"], {}),
        "loop_readiness": load_json(paths["loop_readiness"], {}),
        "mahoraga": load_json(paths["mahoraga"], {}),
        "openalice": load_json(paths["openalice"], {}),
        "incentive_safety": load_json(paths["incentive_safety"], {}),
        "activity": load_activity(activity_path),
        "activity_path": activity_path,
        "flip_trades": load_json(FLIP_TRADES_PATH, []),
        "options_state": options_state,
        "spy_level_reaction": load_json(paths["spy_level_reaction"], {}),
        "spy_level_outcomes": load_json(paths["spy_level_outcomes"], {}),
        "adversarial_audit": load_json(paths["adversarial_audit"], {}),
        "elite_readiness": load_json(paths["elite_readiness"], {}),
        "shadow_audit": load_json(paths["shadow_audit"], {}),
        "operational_gate": load_json(paths["operational_gate"], {}),
        "premarket_readiness": load_json(paths["premarket_readiness"], {}),
        "aplus_spotlight": load_json(paths["aplus_spotlight"], {}),
        "bplus_spotlight": load_json(paths["bplus_spotlight"], {}),
        "economic_ranking_regret": load_json(paths["economic_ranking_regret"], {}),
        "aplus_contract_feasibility": load_json(paths["aplus_contract_feasibility"], {}),
        "aplus_market_context": load_json(paths["aplus_market_context"], {}),
        "footprint_evidence": load_json(paths["footprint_evidence"], {}),
        "multi_timeframe_edge": load_json(paths["multi_timeframe_edge"], {}),
        "trader_barbie_3m": load_json(paths["trader_barbie_3m"], {}),
        "strategy_concept_coverage": load_json(paths["strategy_concept_coverage"], {}),
        "uncovered_concept_tournament": load_json(paths["uncovered_concept_tournament"], {}),
        "daily_rsi2_200sma": load_json(paths["daily_rsi2_200sma"], {}),
        "intraday_radar": load_json(paths["intraday_radar"], {}),
        "intraday_sector_posture": load_json(paths["intraday_sector_posture"], {}),
        "intraday_lifecycle_shadow": load_json(paths["intraday_lifecycle_shadow"], {}),
        "simple_price_action_alerts": load_json(paths["simple_price_action_alerts"], {}),
        "wolves_bbr_shadow": load_json(paths["wolves_bbr_shadow"], {}),
        "banks_821_shadow": load_json(paths["banks_821_shadow"], {}),
        "donchian_expansion_shadow": load_json(paths["donchian_expansion_shadow"], {}),
        "donchian_expansion_forward_shadow": load_json(paths["donchian_expansion_forward_shadow"], {}),
        "liquid_signal_chart_audit": load_json(paths["liquid_signal_chart_audit"], {}),
        "spy_5m_0dte_orb": load_json(paths["spy_5m_0dte_orb"], {}),
        "continuous_improvement": load_json(paths["continuous_improvement"], {}),
        "daily_move_coverage_review": load_json(
            paths.get("daily_move_coverage_review", REPORTS["daily_move_coverage_review"]), {}
        ),
        "priority_swing_observation": load_json(
            paths.get("priority_swing_observation", REPORTS["priority_swing_observation"]), {}
        ),
        "priority_swing_events": read_jsonl_rows(PRIORITY_SWING_EVENT_LOG),
        "operational_runs": load_json(paths["operational_runs"], {}),
        "daily_level_map_shadow": load_json(
            paths.get("daily_level_map_shadow", REPORTS["daily_level_map_shadow"]), {}
        ),
        "agent_reach_research": load_json(paths["agent_reach_research"], {}),
        "social_replay_queue": read_jsonl_rows(SOCIAL_REPLAY_QUEUE),
        "social_gap_match": load_json(SOCIAL_GAP_MATCH_REPORT, {}),
    }
    model["positions_by_symbol"] = {str(pos.get("symbol")): pos for pos in positions if isinstance(pos, dict)}
    model["chart_data"] = build_chart_data(model)
    return model


def stat_card(label: str, value: str, sub: str = "", tone: str = "") -> str:
    return f"""
      <div class="stat {tone}">
        <span>{esc(label)}</span>
        <strong>{value}</strong>
        <small>{esc(sub)}</small>
      </div>"""


def render_continuous_improvement(model: dict[str, Any]) -> str:
    data = model.get("continuous_improvement") if isinstance(model.get("continuous_improvement"), dict) else {}
    if not data:
        return section("Daily Learning Accountability", "<p class='muted'>No scorecard yet.</p>", "Shadow-only · no automatic tuning or promotion")
    daily = data.get("daily") if isinstance(data.get("daily"), dict) else {}
    change = data.get("change_vs_previous_session") if isinstance(data.get("change_vs_previous_session"), dict) else {}
    grade = str(daily.get("grade") or "—")
    tone = "good" if grade == "A" else "warn" if grade in {"B", "C"} else "bad"
    delivery = daily.get("delivery_success_pct")
    p95 = daily.get("p95_alert_latency_seconds")
    stats = (
        '<div class="stat-grid">'
        + stat_card("Daily Grade", grade, "measurement, not performance", tone)
        + stat_card("Scorecard Date", str(data.get("date") or "—"), f"generated {data.get('generated_at') or '—'}")
        + stat_card("Core Alerts", str(safe_int(daily.get("core_index_events"))), ", ".join(daily.get("core_symbols_seen") or []) or "none")
        + stat_card("Discord", f"{delivery:.1f}%" if isinstance(delivery, (int, float)) else "—", f"{safe_int(daily.get('discord_delivered'))}/{safe_int(daily.get('discord_attempts'))} delivered", "bad" if safe_int(daily.get("discord_failures")) else "")
        + stat_card("P95 Alert Lag", f"{p95:.0f}s" if isinstance(p95, (int, float)) else "—", f"late alerts {safe_int(daily.get('late_alert_count'))}", "bad" if isinstance(p95, (int, float)) and p95 > 180 else "")
        + stat_card("Discovery Recall", f"{safe_float(daily.get('source_discovery_recall_pct')):.1f}%" if daily.get("source_discovery_recall_pct") is not None else "—", f"Δ {change.get('discovery_recall_pct_delta') if change.get('discovery_recall_pct_delta') is not None else '—'}")
        + stat_card("Actionable Early", f"{safe_float(daily.get('actionable_early_recall_pct')):.1f}%" if daily.get("actionable_early_recall_pct") is not None else "—", "covered-source denominator")
        + '</div>'
    )
    failure_rows = []
    for row in data.get("failures") or []:
        failure_rows.append(
            f"<tr><td><strong>{esc(row.get('stage'))}</strong></td><td>{esc(row.get('severity'))}</td>"
            f"<td class='muted small'>{esc(row.get('lesson'))}</td></tr>"
        )
    failures = (
        "<h3>Failures that must be closed</h3><div class='table-wrap'><table><thead><tr><th>Stage</th><th>Severity</th><th>Required lesson</th></tr></thead><tbody>"
        + ("".join(failure_rows) or "<tr><td colspan='3'>No critical gap detected in the current evidence.</td></tr>")
        + "</tbody></table></div>"
    )
    lesson_rows = []
    for row in data.get("retained_lessons") or []:
        lesson_rows.append(
            f"<tr><td><strong>{esc(row.get('pattern'))}</strong></td><td>{esc(row.get('acceptance'))}</td>"
            f"<td class='muted small'>{esc(row.get('entry_policy'))}</td><td>{esc(row.get('status'))}</td></tr>"
        )
    lessons = (
        "<h3>Rules retained from reviewed trades</h3><div class='table-wrap'><table><thead><tr><th>Pattern</th><th>Mechanical acceptance</th><th>Alert/entry policy</th><th>Status</th></tr></thead><tbody>"
        + "".join(lesson_rows)
        + "</tbody></table></div>"
    )
    return section("Daily Learning Accountability", stats + failures + lessons, "Every radar cycle · Shadow-only · Human promotion required")


def section(title: str, body: str, subtitle: str = "") -> str:
    sub = f"<p>{esc(subtitle)}</p>" if subtitle else ""
    return f"""
    <section class="panel">
      <div class="section-head"><h2>{esc(title)}</h2>{sub}</div>
      {body}
    </section>"""


def _current_aplus_setups(data: dict[str, Any], now: datetime | None = None) -> list[dict[str, Any]]:
    now = (now or datetime.now(ET)).astimezone(ET)
    if str(data.get("date") or "") != now.date().isoformat():
        return []
    generated_text = str(data.get("generated_at") or "")
    try:
        generated = datetime.fromisoformat(generated_text.replace("Z", "+00:00"))
    except ValueError:
        return []
    if generated.tzinfo is None:
        generated = generated.replace(tzinfo=timezone.utc)
    age_minutes = (now.astimezone(timezone.utc) - generated.astimezone(timezone.utc)).total_seconds() / 60.0
    if not -2.0 <= age_minutes <= 20.0:
        return []
    setups = data.get("setups")
    return [row for row in setups if isinstance(row, dict)] if isinstance(setups, list) else []


def _render_spotlight_cards(setups: list[dict[str, Any]], *, wrapper_cls: str) -> str:
    cards: list[str] = []
    for setup in setups[:12]:
        direction = str(setup.get("direction") or "").lower()
        dir_cls = "dir-bull" if direction.startswith("bull") else "dir-bear" if direction.startswith("bear") else ""
        arrow = "▲" if dir_cls == "dir-bull" else "▼" if dir_cls == "dir-bear" else "◆"
        entry = safe_float(setup.get("entry"), 0.0)
        stop = safe_float(setup.get("invalidation"), 0.0)
        target = safe_float(setup.get("target"), 0.0)
        risk = safe_float(setup.get("risk_per_share"), 0.0)
        reward = safe_float(setup.get("reward_per_share"), 0.0)
        rr = (reward / risk) if risk else 0.0
        setup_name = str(setup.get("setup") or "").replace("_", " ").title() or "Setup"
        score = safe_float(setup.get("score"), 0.0)
        grade = esc(str(setup.get("grade") or ""))
        grade_suffix = f" · {grade}" if grade else ""
        context = setup.get("market_context") if isinstance(setup.get("market_context"), dict) else {}
        sector = str(context.get("sector_etf") or context.get("sector") or "context unavailable")
        alignment = str(context.get("sector_alignment") or "unavailable")
        qqq_spy = context.get("qqq_vs_spy_pct")
        qqq_text = f"QQQ-SPY {safe_float(qqq_spy):+.3f}%" if qqq_spy is not None else "QQQ-SPY unavailable"
        cards.append(
            f"""
        <div class="{wrapper_cls}-card">
          <div class="row-title"><span class="{dir_cls}">{arrow} {esc(str(setup.get('symbol') or '?'))}</span>
            <span style="font-size:12px;opacity:0.85">· {esc(setup_name)}{grade_suffix} · score {score:.1f}</span></div>
          <div class="lvl"><span>Entry</span><b>{entry:.2f}</b></div>
          <div class="lvl"><span>Stop</span><b>{stop:.2f}</b></div>
          <div class="lvl"><span>Target 2R</span><b>{target:.2f}</b></div>
          <div class="lvl"><span>Risk / R:R</span><b>${risk:.2f} · {rr:.2f}R</b></div>
          <div class="lvl"><span>Context</span><b>{esc(sector)} · {esc(alignment)}</b></div>
          <div class="lvl"><span>Intermarket</span><b>{esc(qqq_text)}</b></div>
          <div class="lvl"><span>Evidence gate</span><b>{esc(str(setup.get('evidence_state') or 'candidate_only'))}</b></div>
          <div class="lvl"><span>Calibration / contract</span><b>{esc(str(setup.get('calibration_status') or 'unavailable'))} · {esc(str(setup.get('contract_status') or 'unavailable'))}</b></div>
          <div class="lvl"><span>Footprint evidence</span><b>{esc(str(setup.get('footprint_source_quality') or 'proxy_or_unavailable'))}</b></div>
        </div>"""
        )
    return "".join(cards)


def render_aplus_spotlight(model: dict[str, Any]) -> str:
    data = model.get("aplus_spotlight") if isinstance(model.get("aplus_spotlight"), dict) else {}
    setups = _current_aplus_setups(data)
    if not setups:
        return """
    <div class="aplus-spotlight aplus-idle">
      <div class="aplus-head"><span>A+ Setup Spotlight</span><span class="aplus-count">0</span></div>
      <div class="aplus-sub">No confirmed A+ setups are live. Spotlight will flash red the moment score >= 93 confirms.</div>
    </div>"""
    generated = esc(str(data.get("generated_at") or ""))
    return f"""
    <div class="aplus-spotlight">
      <div class="aplus-head">
        <span>★ A+ Setup Spotlight ★</span>
        <span class="aplus-count">{len(setups)}</span>
      </div>
      <div class="aplus-sub">A+ candidates: confirmed 5m · grade A · score >= 93. Evidence gate must pass before executable shadow readiness · updated {generated}</div>
      <div class="aplus-list">{_render_spotlight_cards(setups, wrapper_cls='aplus')}</div>
    </div>"""


def render_bplus_spotlight(model: dict[str, Any]) -> str:
    data = model.get("bplus_spotlight") if isinstance(model.get("bplus_spotlight"), dict) else {}
    setups = _current_aplus_setups(data)
    if not setups:
        return """
    <div class="bplus-spotlight bplus-idle">
      <div class="bplus-head"><span>B+ Setup Watch</span><span class="bplus-count">0</span></div>
      <div class="bplus-sub">No confirmed B+ / A- setups are live. Watch will glow amber when score >= 75 confirms.</div>
    </div>"""


def render_multi_timeframe_edge(model: dict[str, Any]) -> str:
    """Show research candidates without allowing historical tests to influence ranks."""
    data = model.get("multi_timeframe_edge") if isinstance(model.get("multi_timeframe_edge"), dict) else {}
    if not data:
        return section(
            "Multi-Timeframe Edge Lab",
            '<div class="empty">Tournament report unavailable. Scanner ranks are unchanged.</div>',
            "Historical research only · no rank, alert, sizing, or order authority",
        )
    robust = data.get("cross_market_robust_pairs") if isinstance(data.get("cross_market_robust_pairs"), list) else []
    top = data.get("top_20_research_results") if isinstance(data.get("top_20_research_results"), list) else []
    rows: list[str] = []
    for item in top[:8]:
        if not isinstance(item, dict):
            continue
        metrics = item.get("metrics") if isinstance(item.get("metrics"), dict) else {}
        expectancy = metrics.get("expectancy")
        pf = metrics.get("profit_factor")
        rows.append(
            "<tr>"
            f"<td>{esc(item.get('market'))}</td>"
            f"<td>{esc(item.get('family'))}</td>"
            f"<td>{safe_int(item.get('timeframe_minutes'))}m</td>"
            f"<td>{safe_int(metrics.get('trades'))}</td>"
            f"<td>{money(expectancy)}</td>"
            f"<td>{safe_float(pf):.2f}</td>"
            f"<td>{'forward shadow' if item.get('cross_market_robust') else 'rejected / research'}</td>"
            "</tr>"
        )
    body = (
        '<div class="stats">'
        + stat_card("Trials", str(safe_int(data.get("new_attempt_count"))), "SPY + QQQ")
        + stat_card("Corrected survivors", str(len(robust)), "must pass both markets", "good" if robust else "warn")
        + stat_card("Rank effect", "NONE", "historical selection-contaminated")
        + "</div>"
        + '<div class="table-wrap"><table><thead><tr><th>Market</th><th>Family</th><th>TF</th><th>Trades</th><th>Net expectancy</th><th>PF</th><th>Status</th></tr></thead><tbody>'
        + ("".join(rows) or '<tr><td colspan="7">No evaluated trials found.</td></tr>')
        + "</tbody></table></div>"
        + f'<p class="muted">Verdict: {esc(data.get("verdict") or "unavailable")}. A historical survivor can only enter a separately measured forward-shadow lane.</p>'
    )
    return section(
        "Multi-Timeframe Edge Lab",
        body,
        "Controlled family × timeframe tournament · doubled-friction, walk-forward, and cumulative multiple-testing gates",
    )


def render_trader_barbie_3m(model: dict[str, Any]) -> str:
    """Render the screenshot-matched 15m-context/3m-entry research lane."""
    data = model.get("trader_barbie_3m") if isinstance(model.get("trader_barbie_3m"), dict) else {}
    if not data:
        return section(
            "Trader Barbie 3m CE Lab",
            '<div class="empty">3-minute research report unavailable. Live ranks are unchanged.</div>',
            "15m context · 3m CE execution · 30-minute maximum hold",
        )
    lanes = data.get("lanes") if isinstance(data.get("lanes"), list) else []
    coverage = data.get("coverage") if isinstance(data.get("coverage"), dict) else {}
    rows: list[str] = []
    for lane in lanes:
        if not isinstance(lane, dict):
            continue
        metrics = lane.get("aggregate") if isinstance(lane.get("aggregate"), dict) else {}
        stress = lane.get("double_friction") if isinstance(lane.get("double_friction"), dict) else {}
        rows.append(
            "<tr>"
            f"<td>{esc(lane.get('lane'))}</td>"
            f"<td>{safe_int(metrics.get('trades'))}</td>"
            f"<td>{safe_float(metrics.get('expectancy_r')):+.3f}R</td>"
            f"<td>{safe_float(metrics.get('profit_factor')):.2f}</td>"
            f"<td>{pct(metrics.get('win_rate'), scale=True)}</td>"
            f"<td>{safe_float(stress.get('expectancy_r')):+.3f}R</td>"
            f"<td>{'SPY gate pass' if lane.get('spy_statistical_gate_pass') else 'rejected / observe'}</td>"
            "</tr>"
        )
    body = (
        '<div class="stats">'
        + stat_card("Complete RTH days", str(safe_int(coverage.get("complete_rth_days"))), "strict 390-minute sessions")
        + stat_card("Context events", str(safe_int(data.get("context_event_count"))), "15m sweep + CE")
        + stat_card("Rank effect", "NONE", "SPY-only historical research")
        + "</div>"
        + '<div class="table-wrap"><table><thead><tr><th>Lane</th><th>Trades</th><th>Net expectancy</th><th>PF</th><th>Win</th><th>8 bps expectancy</th><th>Status</th></tr></thead><tbody>'
        + ("".join(rows) or '<tr><td colspan="7">No lanes evaluated.</td></tr>')
        + "</tbody></table></div>"
        + f'<p class="muted">Verdict: {esc(data.get("verdict") or "unavailable")}. “Failed 2” remains a documented proxy; QQQ 1-minute confirmation and new forward evidence are still missing.</p>'
    )
    return section(
        "Trader Barbie 3m CE Lab",
        body,
        "First CE cross vs failed-first/second recross vs second recross + STRAT 2 · maximum 30-minute hold",
    )


def render_daily_rsi2_challenger(model: dict[str, Any]) -> str:
    """Show the source-matched daily futures challenger without confusing it with intraday alerts."""
    data = model.get("daily_rsi2_200sma") if isinstance(model.get("daily_rsi2_200sma"), dict) else {}
    if not data:
        return section(
            "Daily RSI(2) Pullback Challenger",
            '<div class="empty">Research report unavailable. It has no scanner or execution effect.</div>',
            "Daily ES/NQ underlying research · distinct from intraday options setups",
        )
    rows: list[str] = []
    for item in data.get("results") or []:
        if not isinstance(item, dict):
            continue
        oos = ((item.get("trade_metrics") or {}).get("out_of_sample_2025_plus") or {})
        rows.append(
            "<tr>"
            f"<td>{esc(item.get('instrument'))}</td>"
            f"<td>{safe_int(oos.get('trades'))}</td>"
            f"<td>{pct(oos.get('win_rate'), scale=True)}</td>"
            f"<td>{safe_float(oos.get('average_return_pct')):+.3f}%</td>"
            f"<td>{safe_float(oos.get('profit_factor')):.2f}</td>"
            f"<td>{esc(item.get('status'))}</td>"
            "</tr>"
        )
    summary = data.get("out_of_sample_summary") if isinstance(data.get("out_of_sample_summary"), dict) else {}
    body = (
        '<div class="stats">'
        + stat_card("OOS instruments", str(safe_int(summary.get("evaluated_instruments"))), "ES + NQ continuous data")
        + stat_card("Minimum OOS trades", str(safe_int(summary.get("minimum_oos_trades"))), "2025 onward")
        + stat_card("Rank effect", "NONE", "daily research only")
        + "</div>"
        + '<div class="table-wrap"><table><thead><tr><th>Instrument</th><th>OOS trades</th><th>Win</th><th>Avg underlying return</th><th>PF</th><th>Data</th></tr></thead><tbody>'
        + ("".join(rows) or '<tr><td colspan="6">No evaluated instruments.</td></tr>')
        + "</tbody></table></div>"
        + f'<p class="muted">{esc(data.get("promotion_status") or "promotion blocked")}. This is a daily underlying test, not an options-P&L claim.</p>'
    )
    return section(
        "Daily RSI(2) Pullback Challenger",
        body,
        "Exact supplied rules: RSI(2) < 10 above 200-day SMA; exit RSI(2) > 70 or ten sessions · no live authority",
    )


def render_strategy_discovery_coverage(model: dict[str, Any]) -> str:
    """Expose missing concept evidence so strategy discovery cannot silently stop."""
    coverage = model.get("strategy_concept_coverage") if isinstance(model.get("strategy_concept_coverage"), dict) else {}
    tournament = model.get("uncovered_concept_tournament") if isinstance(model.get("uncovered_concept_tournament"), dict) else {}
    if not coverage:
        return section(
            "Strategy Discovery Coverage",
            '<div class="empty">Concept evidence audit unavailable. Do not interpret implementation count as test coverage.</div>',
            "Persistent inventory of tested, proxy-only, untested, and data-blocked concepts",
        )
    queue = coverage.get("priority_queue") if isinstance(coverage.get("priority_queue"), list) else []
    queue_rows: list[str] = []
    for item in queue[:10]:
        if not isinstance(item, dict):
            continue
        queue_rows.append(
            "<tr>"
            f"<td>{esc(item.get('id'))}</td>"
            f"<td>{esc(item.get('evidence_status'))}</td>"
            f"<td>{esc(item.get('data_readiness'))}</td>"
            f"<td>{safe_int(item.get('priority_score'))}</td>"
            f"<td>{esc(item.get('gap') or item.get('next_experiment') or 'isolated tournament required')}</td>"
            "</tr>"
        )
    trial_rows: list[str] = []
    for item in (tournament.get("top_research_results") if isinstance(tournament.get("top_research_results"), list) else [])[:8]:
        if not isinstance(item, dict):
            continue
        metrics = item.get("aggregate") if isinstance(item.get("aggregate"), dict) else {}
        trial_rows.append(
            "<tr>"
            f"<td>{esc(item.get('market'))}</td>"
            f"<td>{safe_int(item.get('timeframe_minutes'))}m</td>"
            f"<td>{esc(item.get('family'))}</td>"
            f"<td>{safe_int(metrics.get('trades'))}</td>"
            f"<td>{money(metrics.get('expectancy'))}</td>"
            f"<td>{safe_float(metrics.get('profit_factor')):.2f}</td>"
            f"<td>{'forward shadow' if item.get('cross_market_robust') else 'research only'}</td>"
            "</tr>"
        )
    body = (
        '<div class="stats">'
        + stat_card("Named concepts", str(safe_int(coverage.get("taxonomy_pattern_count"))), "taxonomy inventory")
        + stat_card("Isolated coverage", pct(coverage.get("isolated_test_coverage_pct")), "implementation does not count")
        + stat_card("Data-ready gaps", str(safe_int(coverage.get("data_ready_untested_count"))), "priority tournament queue", "warn")
        + stat_card("Rank effect", "NONE", "until forward gates pass")
        + "</div>"
        + '<h3>Highest-priority evidence gaps</h3><div class="table-wrap"><table><thead><tr><th>Concept</th><th>Evidence</th><th>Data</th><th>Priority</th><th>Gap / next experiment</th></tr></thead><tbody>'
        + ("".join(queue_rows) or '<tr><td colspan="5">No queued gaps.</td></tr>')
        + "</tbody></table></div>"
        + '<h3>Current uncovered-concept tournament</h3><div class="table-wrap"><table><thead><tr><th>Market</th><th>TF</th><th>Family</th><th>Trades</th><th>Net expectancy</th><th>PF</th><th>Status</th></tr></thead><tbody>'
        + ("".join(trial_rows) or '<tr><td colspan="7">Tournament report pending.</td></tr>')
        + "</tbody></table></div>"
        + f'<p class="muted">Coverage verdict: {esc(coverage.get("verdict") or "unavailable")}. Tournament verdict: {esc(tournament.get("verdict") or "pending")}. Proxy results never validate the named concept.</p>'
    )
    return section(
        "Strategy Discovery Coverage",
        body,
        "Persistent concept audit + preregistered tournament queue · prevents implemented-but-untested strategies from being forgotten",
    )
    generated = esc(str(data.get("generated_at") or ""))
    return f"""
    <div class="bplus-spotlight">
      <div class="bplus-head">
        <span>⚡ B+ Setup Watch ⚡</span>
        <span class="bplus-count">{len(setups)}</span>
      </div>
      <div class="bplus-sub">Confirmed 5m · grade B+ / A- · score >= 75 · actionable rank · updated {generated}</div>
      <div class="bplus-list">{_render_spotlight_cards(setups, wrapper_cls='bplus')}</div>
    </div>"""


def render_preconfirmation_heads_up(model: dict[str, Any]) -> str:
    radar = model.get("intraday_radar") if isinstance(model.get("intraday_radar"), dict) else {}
    rows = [row for row in radar.get("preconfirmation_heads_up") or [] if isinstance(row, dict)]
    if not rows:
        return """
    <div class="panel" style="margin-bottom:16px"><strong>Early heads-up</strong><br><span class="muted">No liquid pre-confirmation watches are live. This lane never creates an order or overrides the completed-bar gate.</span></div>"""
    cards = "".join(
        f"<div class='card'><strong>{esc(str(row.get('symbol') or '?'))}</strong> · {esc(str(row.get('direction') or '?').upper())} · "
        f"{esc(str(row.get('setup') or 'structure watch').replace('_', ' '))}<br>"
        f"score {safe_float(row.get('score')):.1f} · waiting for completed 5m confirmation · watch only</div>"
        for row in rows[:8]
    )
    return f"""
    <div class="panel" style="margin-bottom:16px;border-color:#60a5fa">
      <strong>Early heads-up · watch only</strong>
      <div class="muted" style="margin:5px 0 10px">Liquid candidates awaiting a completed 5-minute confirmation. No rank, sizing, order, or execution authority.</div>
      <div class="grid">{cards}</div>
    </div>"""


def render_simulated_alert_feed(model: dict[str, Any]) -> str:
    """Expose every current paper-trading alert with its exact decision contract."""
    data = model.get("simple_price_action_alerts") if isinstance(model.get("simple_price_action_alerts"), dict) else {}
    signals = [row for row in data.get("signals") or [] if isinstance(row, dict)]
    confirmed = [row for row in signals if row.get("state") == "CONFIRMED"]
    watching = [row for row in signals if row.get("state") == "WAIT"]
    disqualified_priority = [
        row for row in signals
        if row.get("state") == "INVALID" and row.get("observation_visible") is True
    ]
    if not data:
        return "<div class='panel'><strong>Simulated alert feed</strong><br><span class='muted'>No fresh alert artifact. The intraday runner will generate it before each dashboard refresh.</span></div>"
    rows = []
    for row in (confirmed + watching + disqualified_priority)[:24]:
        state = str(row.get("state") or "WAIT")
        cls = "good" if state == "CONFIRMED" else "bad" if state == "INVALID" else "warn"
        label = "SHADOW ENTRY" if state == "CONFIRMED" else "OBSERVE / DISQUALIFIED" if state == "INVALID" else "WATCH"
        proxies = [str(value) for value in row.get("index_proxy_for") or []]
        symbol_label = str(row.get("symbol") or "?")
        if proxies:
            symbol_label += " / " + "/".join(proxies)
        lane = str(row.get("lane") or "STANDARD_SHADOW").replace("_", " ")
        rows.append(
            "<tr>"
            f"<td><span class='{cls}'><b>{esc(label)}</b></span></td>"
            f"<td>{esc(symbol_label)}</td><td>{esc(lane)}</td><td>{esc(str(row.get('direction') or '?'))}</td>"
            f"<td>{'YES' if row.get('observation_visible') is True else 'CURRENT'}</td>"
            f"<td>{'YES' if row.get('execution_review_eligible') is True else 'NO'}</td>"
            f"<td>{esc(str(row.get('grade') or '--'))} / {safe_float(row.get('score')):.1f}</td>"
            f"<td>{safe_float(row.get('trigger')):.4f}</td><td>{safe_float(row.get('stop')):.4f}</td><td>{safe_float(row.get('target')):.4f}</td>"
            f"<td>{esc(str(row.get('bar_completed_at') or 'waiting')[:19])}</td>"
            f"<td>{esc(str(row.get('decisive_reason') or ''))}</td></tr>"
        )
    table = "".join(rows) or "<tr><td colspan='12'>No shadow entries, active watches, or priority observations in this snapshot.</td></tr>"
    counts = data.get("counts") if isinstance(data.get("counts"), dict) else {}
    attempts = safe_int(data.get("notification_attempts"))
    failures = safe_int(data.get("notification_failures"))
    sent = safe_int(data.get("alerts_sent"))
    event_rows = []
    for event in reversed([item for item in data.get("recent_events") or [] if isinstance(item, dict)]):
        if str(event.get("lane") or "") != "CORE_INDEX_SHADOW":
            continue
        proxies = [str(value) for value in event.get("index_proxy_for") or []]
        event_symbol = str(event.get("symbol") or "?")
        if proxies:
            event_symbol += " / " + "/".join(proxies)
        delivery = "sent" if event.get("discord_delivered") else "failed - retry pending"
        event_rows.append(
            "<tr>"
            f"<td>{esc(str(event.get('detected_at') or '')[:19])}</td><td>{esc(event_symbol)}</td>"
            f"<td>{esc(str(event.get('state') or ''))}</td><td>{esc(str(event.get('direction') or ''))}</td>"
            f"<td>{safe_float(event.get('trigger')):.4f}</td><td>{safe_float(event.get('stop')):.4f}</td>"
            f"<td>{safe_float(event.get('target')):.4f}</td><td>{esc(delivery)}</td></tr>"
        )
        if len(event_rows) >= 12:
            break
    history = (
        "<div class='muted' style='margin:12px 0 6px'>Persistent core-index event history</div>"
        "<table class='data'><thead><tr><th>Detected</th><th>Symbol / proxy</th><th>State</th><th>Side</th><th>Trigger</th><th>Stop</th><th>Target</th><th>Discord</th></tr></thead><tbody>"
        + ("".join(event_rows) or "<tr><td colspan='8'>No core-index transitions recorded yet.</td></tr>")
        + "</tbody></table>"
    )
    return (
        "<div class='panel' style='margin-bottom:16px;border-color:#22c55e'><strong>Simulated real-time alert feed</strong>"
        "<div class='muted' style='margin:5px 0 10px'>Observed and execution-eligible are separate. Green = governed simulated shadow entry after completed 5m confirmation. Yellow = visible watch before confirmation. Red priority rows remain visible as disqualified observations. Priority visibility never bypasses evidence or risk gates; no broker order is sent.</div>"
        f"<div class='stats'>{stat_card('Shadow entries', str(safe_int(counts.get('CONFIRMED'))), 'green completed-bar alerts', 'good')}{stat_card('Active watches', str(safe_int(counts.get('WAIT'))), 'yellow heads-up alerts', 'warn')}{stat_card('Discord delivery', f'{sent}/{attempts}', f'{failures} failed and pending retry', 'bad' if failures else 'good')}{stat_card('Invalidated', str(safe_int(counts.get('INVALID'))), 'red stand-aside states')}</div>"
        "<table class='data'><thead><tr><th>Alert</th><th>Symbol / proxy</th><th>Lane</th><th>Side</th><th>Observed</th><th>Execution-eligible</th><th>Grade / Score</th><th>Trigger</th><th>Stop</th><th>2R target</th><th>Bar complete</th><th>Why</th></tr></thead><tbody>"
        + table + "</tbody></table>" + history + "</div>"
    )


def render_session_focus(model: dict[str, Any]) -> str:
    """Pin the declared liquid focus universe without overriding scanner gates."""
    radar = model.get("intraday_radar") if isinstance(model.get("intraday_radar"), dict) else {}
    rows_by_symbol = {
        str(row.get("symbol") or "").upper(): row
        for row in radar.get("ranked_candidates") or [] if isinstance(row, dict)
    }
    rows = []
    for symbol in SESSION_FOCUS_SYMBOLS:
        row = rows_by_symbol.get(symbol)
        if not row:
            rows.append(f"<tr><td><b>{symbol}</b></td><td colspan='6' class='bad'>Missing from current radar — coverage fault</td></tr>")
            continue
        gates = row.get("hard_gates") if isinstance(row.get("hard_gates"), dict) else {}
        pending = ", ".join(key.replace("_", " ") for key, passed in gates.items() if passed is False) or "none"
        levels = row.get("trade_levels") if isinstance(row.get("trade_levels"), dict) else {}
        state = str(row.get("confirmation_stage") or row.get("state") or "unknown").replace("_", " ")
        rows.append(
            "<tr>"
            f"<td><b>{symbol}</b></td><td>{esc(str(row.get('direction') or '?').upper())}</td>"
            f"<td>{esc(str(row.get('grade') or '--'))} / {safe_float(row.get('score')):.1f}</td>"
            f"<td>{safe_float(row.get('price')):.2f}</td><td>{esc(state)}</td>"
            f"<td>{safe_float(levels.get('confirmation_trigger')):.2f} / {safe_float(levels.get('invalidation')):.2f} / {safe_float(levels.get('target_2r')):.2f}</td>"
            f"<td>{esc(pending)}</td></tr>"
        )
    return (
        "<div class='panel' style='margin-bottom:16px;border-color:#60a5fa'><strong>Today’s liquid focus · simulated only</strong>"
        "<div class='muted' style='margin:5px 0 10px'>NVDA, GOOGL, AAPL, and META are explicitly pinned for every radar cycle. They remain visible even when filtered; a focus designation never bypasses a completed 5-minute confirmation, quote check, or liquidity gate.</div>"
        "<table class='data'><thead><tr><th>Symbol</th><th>Current side</th><th>Grade / score</th><th>Last</th><th>State</th><th>Trigger / stop / 2R</th><th>Pending gates</th></tr></thead><tbody>"
        + "".join(rows) + "</tbody></table>"
        "<p class='muted'>Paper-management template only after a green alert: document the entry quote, then simulate a 30–40% premium trim and a runner with a predeclared stop. It is not an automatic order instruction.</p></div>"
    )


def render_intraday_posture_and_lifecycle(model: dict[str, Any]) -> str:
    posture_report = model.get("intraday_sector_posture") if isinstance(model.get("intraday_sector_posture"), dict) else {}
    posture = posture_report.get("posture") if isinstance(posture_report.get("posture"), dict) else {}
    lifecycle_report = model.get("intraday_lifecycle_shadow") if isinstance(model.get("intraday_lifecycle_shadow"), dict) else {}
    plans = [row for row in lifecycle_report.get("plans") or [] if isinstance(row, dict)]
    posture_text = (
        f"{esc(str(posture.get('state') or 'unavailable').replace('_', ' '))} · "
        f"{safe_int(posture.get('positive_count'))} positive / {safe_int(posture.get('negative_count'))} negative"
    )
    leader_text = ", ".join(
        f"{esc(str(row.get('etf') or '?'))} {safe_float(row.get('session_return_pct')):+.2f}%"
        for row in (posture.get("leaders") or [])[:3] if isinstance(row, dict)
    ) or "unavailable"
    plan_cards = "".join(
        f"<div class='card'><strong>{esc(str(row.get('symbol') or '?'))}</strong> · {esc(str(row.get('direction') or '').upper())} · lane {safe_int(row.get('lane_rank'))} · {esc(str(row.get('grade') or ''))}<br>"
        f"{esc(str(row.get('setup') or 'confirmed structure').replace('_', ' '))}<br>"
        f"entry {safe_float(row.get('entry')):.2f} · initial stop {safe_float(row.get('initial_stop')):.2f} · 2R {safe_float(row.get('target_2r')):.2f}<br>"
        f"30m experiment checkpoint {esc(str(row.get('time_stop_at') or ''))}<br>"
        f"<b>{esc(str((row.get('decision_contract') or {}).get('outcome') or 'do_not_take').replace('_', ' '))}</b><br>"
        "<span class='muted'>shadow experiment only — no alert or order authority</span></div>"
        for row in plans[:8]
    ) or "<div class='card'>No completed-bar lifecycle plans in this snapshot.</div>"
    return f"""
    <div class="panel" style="margin-bottom:16px;border-color:#60a5fa">
      <strong>Confirmed watches first · posture + lifecycle shadow</strong>
      <div class="muted" style="margin:5px 0 10px">{posture_text} · leaders: {leader_text}</div>
      <div class="grid">{plan_cards}</div>
    </div>"""


def render_aplus_evidence_contract(model: dict[str, Any]) -> str:
    """Make A+ evidence debt visible instead of silently upgrading a score."""
    radar = model.get("intraday_radar") if isinstance(model.get("intraday_radar"), dict) else {}
    coverage = radar.get("coverage") if isinstance(radar.get("coverage"), dict) else {}
    rows = [row for row in radar.get("ranked_candidates") or [] if isinstance(row, dict)]
    incomplete = [
        row for row in rows
        if (row.get("a_plus_evidence") or {}).get("classification") == "evidence_incomplete"
    ]
    examples = "".join(
        f"<div class='card'><strong>{esc(str(row.get('symbol') or '?'))}</strong> · "
        f"missing {esc(', '.join((row.get('a_plus_evidence') or {}).get('missing_required_fields') or [])[:180])}</div>"
        for row in incomplete[:3]
    )
    return f"""
    <div class="panel" style="margin-bottom:16px;border-color:#f59e0b">
      <strong>A+ evidence contract · fail closed</strong>
      <div class="muted" style="margin:5px 0 10px">{safe_int(coverage.get('a_plus_process_candidate_count'))} fully evidenced process candidates · {safe_int(coverage.get('a_plus_evidence_incomplete_count'))} candidates carrying explicit evidence debt. A discovery score, publisher headline, IEX quote, or volume-pace proxy never earns the A+ label by itself.</div>
      <div class="grid">{examples or "<div class='card'>No A+ evidence record is available from this radar snapshot.</div>"}</div>
    </div>"""


def render_liquid_review_escalations(model: dict[str, Any]) -> str:
    radar = model.get("intraday_radar") if isinstance(model.get("intraday_radar"), dict) else {}
    rows = [row for row in radar.get("liquid_review_escalations") or [] if isinstance(row, dict)]
    if not rows:
        return ""
    cards = "".join(
        f"<div class='card'><strong>{esc(str(row.get('symbol') or '?'))}</strong> · {esc(str(row.get('direction') or '?').upper())}<br>"
        f"completed 5m {esc(str(row.get('setup') or 'setup').replace('_', ' '))} · score {safe_float(row.get('score')):.1f}<br>"
        f"<span class='bad'>Quote-quality review required</span> · not ranked or actionable</div>"
        for row in rows[:8]
    )
    return f"""
    <div class="panel" style="margin-bottom:16px;border-color:#f59e0b">
      <strong>Liquid setup · quote-quality review</strong>
      <div class="muted" style="margin:5px 0 10px">Completed-bar setup in a liquid name was blocked only by the underlying quote gate. Visible for data review, never an order or an execution recommendation.</div>
      <div class="grid">{cards}</div>
    </div>"""


def render_wolves_bbr_shadow(model: dict[str, Any]) -> str:
    """Show source-matched BBR observations without granting rank authority."""
    data = model.get("wolves_bbr_shadow") if isinstance(model.get("wolves_bbr_shadow"), dict) else {}
    coverage = data.get("coverage") if isinstance(data.get("coverage"), dict) else {}
    hits = data.get("confluence_hits") if isinstance(data.get("confluence_hits"), list) else []
    rows = []
    for hit in hits[:8]:
        if not isinstance(hit, dict):
            continue
        ema = hit.get("ema") if isinstance(hit.get("ema"), dict) else {}
        rows.append(
            "<tr>"
            f"<td>{esc(hit.get('symbol'))}</td><td>{esc(hit.get('direction'))}</td>"
            f"<td>{esc(str(hit.get('behavior') or '').replace('_', ' '))}</td>"
            f"<td>{safe_float(hit.get('last_close')):.4f}</td><td>{esc(hit.get('ema_alignment'))}</td>"
            f"<td>{safe_float(ema.get('ema200')):.4f}</td><td>{esc(hit.get('last_completed_bar_at'))}</td>"
            "</tr>"
        )
    return section(
        "Wolves BBR Confluence · Shadow",
        f"""
        <div class=\"stat-grid compact\">
          {stat_card("Radar candidates", str(safe_int(coverage.get("radar_symbols_considered"))), "same-day candidates checked", "")}
          {stat_card("Complete level maps", str(safe_int(coverage.get("observations_complete"))), "prior day + premarket + EMA history", "")}
          {stat_card("Liquid-core data debt", str(safe_int(coverage.get("liquid_core_coverage_debt_count"))), "missing chart history is visible, never imputed", "warn")}
          {stat_card("BBR observations", str(safe_int(coverage.get("confluence_hits"))), "completed 5m break/hold + EMA stack", "warn")}
          {stat_card("Promotion", "BLOCKED", "no rank, alert, sizing, or execution effect", "bad")}
        </div>
        <div class=\"table-wrap\"><table><thead><tr><th>Symbol</th><th>Direction</th><th>Behavior</th><th>Close</th><th>EMA context</th><th>200 EMA</th><th>Completed bar</th></tr></thead>
        <tbody>{''.join(rows) or '<tr><td colspan="7">No source-matched BBR confluence in the completed data. Missing premarket data is reported as incomplete rather than guessed.</td></tr>'}</tbody></table></div>
        """,
        "Prior-day/premarket levels + completed 5m 200/8/13/48 EMA stack · source-matched observation only · public strategy rules remain incomplete · no order authority",
    )


def render_banks_821_shadow(model: dict[str, Any]) -> str:
    data = model.get("banks_821_shadow") if isinstance(model.get("banks_821_shadow"), dict) else {}
    coverage = data.get("coverage") if isinstance(data.get("coverage"), dict) else {}
    hits = data.get("confluence_hits") if isinstance(data.get("confluence_hits"), list) else []
    rows = "".join(
        f"<tr><td>{esc(row.get('symbol'))}</td><td>{esc(row.get('direction'))}</td><td>{safe_float((row.get('ema') or {}).get('ema8')):.4f} / {safe_float((row.get('ema') or {}).get('ema21')):.4f}</td><td>{esc(row.get('last_completed_bar_at'))}</td></tr>"
        for row in hits[:8] if isinstance(row, dict)
    )
    rows_html = rows or (
        '<tr><td colspan="4">No mechanical proxy hit. Ranging 8/21, weak momentum, '
        'chop, or no retest are explicit no-trades.</td></tr>'
    )
    return section(
        "Banks 8/21 Control · Shadow",
        f"<div class='stat-grid compact'>{stat_card('Observed', str(safe_int(coverage.get('observed'))), 'completed 5m history', '')}{stat_card('Proxy hits', str(safe_int(coverage.get('hits'))), 'not validated', 'warn')}{stat_card('Promotion', 'BLOCKED', 'separate tournament required', 'bad')}</div><div class='table-wrap'><table><thead><tr><th>Symbol</th><th>Direction</th><th>EMA 8 / 21</th><th>Completed bar</th></tr></thead><tbody>{rows_html}</tbody></table></div>",
        "Public checklist translated into declared assumptions · no rank, alert, sizing, or execution authority",
    )


def render_donchian_expansion_shadow(model: dict[str, Any]) -> str:
    """Render candidate coverage without confusing it for a trade signal."""
    data = model.get("donchian_expansion_shadow") if isinstance(model.get("donchian_expansion_shadow"), dict) else {}
    coverage = data.get("coverage") if isinstance(data.get("coverage"), dict) else {}
    forward = model.get("donchian_expansion_forward_shadow") if isinstance(model.get("donchian_expansion_forward_shadow"), dict) else {}
    forward_summary = forward.get("summary") if isinstance(forward.get("summary"), dict) else {}
    hits = data.get("rankings") if isinstance(data.get("rankings"), list) else []
    rows = "".join(
        "<tr>"
        f"<td>{esc(row.get('symbol'))}</td><td>{esc(row.get('direction'))}</td>"
        f"<td>{safe_float((row.get('evidence') or {}).get('volume_multiple_vs_prior_20_completed_bars')):.2f}x</td>"
        f"<td>{safe_float((row.get('evidence') or {}).get('close_location')):.2f}</td>"
        f"<td>{safe_float((row.get('evidence') or {}).get('true_range_multiple_vs_prior_atr_14')):.2f}x</td>"
        f"<td>{esc(row.get('last_completed_bar_at'))}</td></tr>"
        for row in hits[:8] if isinstance(row, dict)
    )
    rows_html = rows or (
        '<tr><td colspan="6">No strict completed-bar expansion. This is candidate coverage '
        'only—not an entry or an alert.</td></tr>'
    )
    return section(
        "Donchian Expansion · Shadow",
        f"<div class='stat-grid compact'>{stat_card('Observed', str(safe_int(coverage.get('observed'))), 'completed RTH 5m bars only', '')}{stat_card('Strict expansions', str(safe_int(coverage.get('strict_hits'))), '20-bar break + RVOL + close + range', 'warn')}{stat_card('Resolved forward', str(safe_int(forward_summary.get('resolved'))), 'next-bar-open, stop-first, 2R / 60m', '')}{stat_card('Mean net R', esc(str(forward_summary.get('mean_net_r_after_costs') if forward_summary.get('mean_net_r_after_costs') is not None else 'pending')), 'fixed slippage stress; not fill evidence', 'warn')}{stat_card('Promotion', 'BLOCKED', 'walk-forward and shadow evaluation required', 'bad')}</div><div class='table-wrap'><table><thead><tr><th>Symbol</th><th>Direction</th><th>RVOL</th><th>Close location</th><th>TR / ATR</th><th>Completed bar</th></tr></thead><tbody>{rows_html}</tbody></table></div>",
        "Prior-20-bar Donchian break + 1.25x prior completed-bar volume + strong close + 1.20x prior ATR range · forward audit uses next-bar open, signal-bar stop, 2R / 60m and 5 bp/side stress · no execution authority",
    )


def render_liquid_signal_chart_audit(model: dict[str, Any]) -> str:
    """Render post-signal raw-chart follow-through without implying fills."""
    data = model.get("liquid_signal_chart_audit") if isinstance(model.get("liquid_signal_chart_audit"), dict) else {}
    summary = data.get("summary") if isinstance(data.get("summary"), dict) else {}
    rows = []
    for signal in (data.get("signals") or [])[:10]:
        if not isinstance(signal, dict):
            continue
        rows.append("<tr>" + f"<td>{esc(signal.get('symbol'))}</td><td>{esc(signal.get('direction'))}</td><td>{esc(str(signal.get('setup') or '').replace('_', ' '))}</td><td>{safe_float(signal.get('forward_5m_return_pct')):+.3f}%</td><td>{safe_float(signal.get('forward_30m_return_pct')):+.3f}%</td><td>{safe_float(signal.get('mfe_pct_60m_or_available')):+.3f}%</td><td>{safe_float(signal.get('mae_pct_60m_or_available')):+.3f}%</td><td>{esc(signal.get('signal_bar_completed_at'))}</td>" + "</tr>")
    return section(
        "Liquid Signal Chart Audit",
        f"""<div class=\"stat-grid compact\">{stat_card("Liquid confirmations", str(safe_int(summary.get("liquid_confirmed_signals"))), "first point-in-time completed 5m signal", "")}{stat_card("Chart-resolved", str(safe_int(summary.get("chart_resolved_signals"))), "actual completed 5m bars", "")}{stat_card("Mean 30m path", pct(summary.get("resolved_30m_mean_return_pct")), "direction-adjusted underlying observation", "warn")}{stat_card("Orders", "NONE", "no fills or options P/L inferred", "bad")}</div><div class=\"table-wrap\"><table><thead><tr><th>Symbol</th><th>Direction</th><th>Pattern</th><th>5m</th><th>30m</th><th>MFE</th><th>MAE</th><th>Signal bar</th></tr></thead><tbody>{''.join(rows) or '<tr><td colspan="8">No liquid confirmed signals have a chart outcome yet.</td></tr>'}</tbody></table></div>""",
        "Actual completed underlying 5m chart path after the first scanner confirmation · no assumed fill, contract, slippage, or profit · outcome audit only",
    )


def render_spy_level_reaction(model: dict[str, Any]) -> str:
    """Render the explicit pre-mapped SPY level-reaction monitor as context only."""
    data = model.get("spy_level_reaction") if isinstance(model.get("spy_level_reaction"), dict) else {}
    level_map = data.get("level_map") if isinstance(data.get("level_map"), dict) else {}
    levels = level_map.get("levels") if isinstance(level_map.get("levels"), list) else []
    reactions = data.get("reactions") if isinstance(data.get("reactions"), list) else []
    lifecycles = data.get("level_lifecycles") if isinstance(data.get("level_lifecycles"), list) else []
    health = str(data.get("operational_health") or "unavailable")
    rows: list[str] = []
    for reaction in reactions[:8]:
        if not isinstance(reaction, dict):
            continue
        features = reaction.get("spy0dte_features") if isinstance(reaction.get("spy0dte_features"), dict) else {}
        status = str(reaction.get("status") or "unknown")
        touch = f"{esc(features.get('touch_sequence') or 'unavailable')} ({safe_int(features.get('touch_count'))})"
        rsi = features.get("rsi_14_completed_5m")
        rsi_text = f"{safe_float(rsi):.1f}" if rsi is not None else esc(features.get("rsi_14_status") or "unavailable")
        speed = features.get("atr_normalized_approach_speed")
        speed_text = f"{safe_float(speed):+.2f} ATR" if speed is not None else "unavailable"
        window = "eligible" if features.get("early_session_eligible") is True else "after cutoff" if features.get("early_session_eligible") is False else "unavailable"
        rows.append(
            "<tr>"
            f"<td>{esc(reaction.get('level_name'))}</td>"
            f"<td>{safe_float(reaction.get('level')):.2f}</td>"
            f"<td>{esc(reaction.get('direction'))}</td>"
            f"<td><span class='{cls_for_health(status)}'>{esc(status)}</span></td>"
            f"<td>{safe_float(reaction.get('reaction_points')):.2f}</td>"
            f"<td>{touch}</td>"
            f"<td>{rsi_text}</td>"
            f"<td>{speed_text}</td>"
            f"<td>{window}</td>"
            f"<td>{esc(reaction.get('observed_at'))}</td>"
            "</tr>"
        )
    map_text = ", ".join(
        f"{esc(level.get('name'))} {safe_float(level.get('price')):.2f}"
        for level in levels[:7]
        if isinstance(level, dict)
    ) or "No completed-session levels yet."
    summary = data.get("summary") if isinstance(data.get("summary"), dict) else {}
    feature_contract = data.get("spy0dte_feature_contract") if isinstance(data.get("spy0dte_feature_contract"), dict) else {}
    gap = data.get("gap_context") if isinstance(data.get("gap_context"), dict) else {}
    breadth = data.get("breadth_context") if isinstance(data.get("breadth_context"), dict) else {}
    intermarket = data.get("intermarket_context") if isinstance(data.get("intermarket_context"), dict) else {}
    leaders = intermarket.get("sector_leaders") if isinstance(intermarket.get("sector_leaders"), list) else []
    leader_text = ", ".join(
        f"{esc(item.get('etf'))} {safe_float(item.get('vs_spy_pct')):+.3f}%"
        for item in leaders[:3] if isinstance(item, dict)
    ) or "unavailable"
    qqq_vs_spy = intermarket.get("qqq_vs_spy_pct")
    qqq_text = f"{safe_float(qqq_vs_spy):+.3f}%" if qqq_vs_spy is not None else "unavailable"
    lifecycle_rows: list[str] = []
    for lifecycle in lifecycles[:8]:
        if not isinstance(lifecycle, dict):
            continue
        lifecycle_rows.append(
            "<tr>"
            f"<td>{esc(lifecycle.get('level_name'))}</td>"
            f"<td>{safe_float(lifecycle.get('level')):.2f}</td>"
            f"<td><span class='{cls_for_health(str(lifecycle.get('state') or 'unknown'))}'>{esc(lifecycle.get('state'))}</span></td>"
            f"<td>{safe_int(lifecycle.get('touch_count'))}</td>"
            f"<td>{esc(lifecycle.get('current_side'))}</td>"
            f"<td>{esc(lifecycle.get('state_observed_at'))}</td>"
            "</tr>"
        )
    return section(
        "SPY Mapped-Level Reactions",
        f"""
        <div class="stat-grid compact">
          {stat_card("Monitor", health.upper(), "completed 5m only", cls_for_health(health))}
          {stat_card("Confirmed", str(safe_int(summary.get('confirmed_reactions'))), "$0.40-$0.80 underlying reaction", "good")}
          {stat_card("No-Chase", str(safe_int(summary.get('extended_no_chase'))), "> $0.80 reaction is not upgraded", "warn")}
          {stat_card("SPY0DTE Features", "SHADOW", f"completed 5m RSI · cutoff {feature_contract.get('early_session_cutoff_et') or '11:15'} ET", "warn")}
          {stat_card("Gap Path", str(gap.get('fill_bucket') or 'unavailable'), "realized path, never a fill prediction", "")}
          {stat_card("Breadth", str(breadth.get('regime') or 'unavailable'), "frozen challenger, not a gate", "")}
          {stat_card("QQQ-SPY", qqq_text, str(intermarket.get('qqq_spy_regime') or 'unavailable'), "")}
          {stat_card("Level Lifecycle", str(safe_int(summary.get('active_level_lifecycles'))), "descriptive completed-bar states", "")}
        </div>
        <p><strong>Mapped levels:</strong> {map_text}</p>
        <p><strong>Sector leaders vs SPY:</strong> {leader_text}</p>
        <div class="table-wrap"><table>
          <thead><tr><th>Level</th><th>Price</th><th>Direction</th><th>State</th><th>Reaction</th><th>Touch</th><th>RSI(14)</th><th>30m speed</th><th>Window</th><th>Completed bar</th></tr></thead>
          <tbody>{''.join(rows) or '<tr><td colspan="10">No completed-bar level reaction is active. Wait at mapped support/resistance; do not chase a move already extended.</td></tr>'}</tbody>
        </table></div>
        <h3>Level Lifecycle Context</h3>
        <div class="table-wrap"><table>
          <thead><tr><th>Level</th><th>Price</th><th>Lifecycle</th><th>Touches</th><th>Last side</th><th>Observed</th></tr></thead>
          <tbody>{''.join(lifecycle_rows) or '<tr><td colspan="6">No completed-bar lifecycle state is available yet.</td></tr>'}</tbody>
        </table></div>
        """,
        "Independent completed-bar level lifecycle · descriptive context only, never A+ scoring, alert, sizing, or order authority · underlying SPY move is not an options-premium prediction",
    )


def render_spy_level_outcomes(model: dict[str, Any]) -> str:
    """Render frozen gap/breadth/intermarket slices without promoting them."""
    data = model.get("spy_level_outcomes") if isinstance(model.get("spy_level_outcomes"), dict) else {}
    summary = data.get("summary") if isinstance(data.get("summary"), dict) else {}
    contract = summary.get("contract_feasibility") if isinstance(summary.get("contract_feasibility"), dict) else {}
    premium_plan = summary.get("fixed_premium_proxy_plan") if isinstance(summary.get("fixed_premium_proxy_plan"), dict) else {}
    feature_slices = summary.get("spy0dte_candidate_feature_slices") if isinstance(summary.get("spy0dte_candidate_feature_slices"), dict) else {}
    slices = summary.get("gap_time_to_fill_slices") if isinstance(summary.get("gap_time_to_fill_slices"), list) else []
    rows: list[str] = []
    for item in slices:
        if not isinstance(item, dict):
            continue
        rows.append(
            "<tr>"
            f"<td>{esc(item.get('bucket'))}</td>"
            f"<td>{safe_int(item.get('sample_count'))}</td>"
            f"<td>{safe_float(item.get('win_rate')) * 100:.1f}%</td>"
            f"<td>{safe_float(item.get('mean_terminal_outcome_points')):+.2f}</td>"
            f"<td>{safe_float(item.get('mean_mfe_points')):+.2f}</td>"
            f"<td>{safe_float(item.get('mean_mae_points')):+.2f}</td>"
            "</tr>"
        )
    blockers = ", ".join(str(item).replace("_", " ") for item in summary.get("promotion_blockers") or []) or "collecting forward observations"
    captured_features = ", ".join(
        f"{key.replace('_', ' ')} ({sum(safe_int(item.get('sample_count')) for item in values if isinstance(item, dict))})"
        for key, values in sorted(feature_slices.items())
        if isinstance(values, list)
    ) or "none captured yet"
    return section(
        "SPY Context Outcome Research",
        f"""
        <div class="stat-grid compact">
          {stat_card("Resolved", str(safe_int(summary.get('resolved_count'))), "60-minute underlying proxy", "")}
          {stat_card("Minimum / Bucket", str(data.get('minimum_bucket_sample') or 30), "separate dates and regimes required", "warn")}
          {stat_card("Contract Quotes", str(contract.get('status') or 'unavailable').replace('_', ' '), str(contract.get('reason') or 'NBBO required'), "bad")}
          {stat_card("+20% / -12.5%", str(premium_plan.get('status') or 'not available').replace('_', ' '), "not an option result", "warn")}
          {stat_card("Promotion", "BLOCKED", "no execution authority", "bad")}
        </div>
        <p><strong>Gap time-to-fill slices:</strong> frozen at observation time. They describe outcomes; they never forecast that a gap will fill.</p>
        <div class="table-wrap"><table>
          <thead><tr><th>Gap bucket</th><th>N</th><th>Win rate</th><th>Mean terminal pts</th><th>Mean MFE</th><th>Mean MAE</th></tr></thead>
          <tbody>{''.join(rows) or '<tr><td colspan="6">No resolved 60-minute observations yet. The ledger is collecting completed-bar reactions first.</td></tr>'}</tbody>
        </table></div>
        <p><strong>Promotion blockers:</strong> {esc(blockers)}</p>
        <p><strong>Frozen SPY0DTE feature slices:</strong> {esc(captured_features)}. These are collected for comparison only.</p>
        """,
        "Shadow-only outcome slices · fixed premium labels are non-executable until timestamped bid/ask NBBO exists · breadth and QQQ/SPY-sector context remain challengers · not option P&L or a live signal",
    )


def render_overfit_guard(model: dict[str, Any]) -> str:
    """Make the fail-closed evidence state visible beside attractive setup cards."""
    audit = model.get("adversarial_audit") if isinstance(model.get("adversarial_audit"), dict) else {}
    readiness = model.get("elite_readiness") if isinstance(model.get("elite_readiness"), dict) else {}
    summary = audit.get("summary") if isinstance(audit.get("summary"), dict) else {}
    blockers: list[str] = []
    for subject in audit.get("subjects") or []:
        if not isinstance(subject, dict) or subject.get("passed") is True:
            continue
        name = str(subject.get("subject_id") or "candidate")
        failed = ", ".join(str(item).replace("_", " ") for item in (subject.get("failed_checks") or [])[:3])
        blockers.append(f"{name}: {failed or 'audit incomplete'}")
    readiness_status = str(readiness.get("status") or "evidence_building")
    score = readiness.get("overall_score")
    verdict = "BLOCKED" if safe_int(summary.get("blocked_count")) or readiness_status != "verified_elite" else "HUMAN REVIEW ONLY"
    tone = "bad" if verdict == "BLOCKED" else "warn"
    return section(
        "Overfit Guard",
        f"""
        <div class="stat-grid compact">
          {stat_card("Evidence State", verdict, "never grants order authority", tone)}
          {stat_card("Adversarial Audits", f"{safe_int(summary.get('passed_count'))} pass / {safe_int(summary.get('blocked_count'))} blocked", "missing evidence fails closed", tone)}
          {stat_card("System Readiness", f"{safe_float(score):.1f}/10" if score is not None else "unavailable", readiness_status.replace('_', ' '), tone)}
        </div>
        <p><strong>Why blocked:</strong> {esc('; '.join(blockers) or 'No completed adversarial manifest is available, so promotion remains blocked.')}</p>
        <p><strong>Required before any human review:</strong> frozen rules, point-in-time timestamps, independent review, chronological forward outcomes, cost stress, parameter-neighbor and regime stability, and a positive bootstrap lower bound.</p>
        """,
        "Fail-closed governance · scores and social labels are research only · no automatic promotion or order authority",
    )


def render_operational_gate(model: dict[str, Any]) -> str:
    data = model.get("operational_gate") if isinstance(model.get("operational_gate"), dict) else {}
    premarket = model.get("premarket_readiness") if isinstance(model.get("premarket_readiness"), dict) else {}
    passed = data.get("operational_prerequisite_passed") is True
    status = str(data.get("status") or "missing")
    observed = safe_int(data.get("observed_sessions_in_window"))
    passing = safe_int(data.get("passing_sessions_in_window"))
    required = safe_int(data.get("required_passing_sessions")) or 5
    current = data.get("current_session") if isinstance(data.get("current_session"), dict) else {}
    blockers = data.get("blockers") if isinstance(data.get("blockers"), list) else []
    premarket_status = str(premarket.get("status") or "missing")
    premarket_blockers = premarket.get("blockers") if isinstance(premarket.get("blockers"), list) else []
    return section(
        "Operational Readiness Gate",
        f"""
        <div class="stat-grid compact">
          {stat_card("Five-Session Gate", "PASS" if passed else "BLOCKED", "operational prerequisite only", "good" if passed else "bad")}
          {stat_card("Pre-open Gate", premarket_status.replace('_', ' ').upper(), "radar · RVOL · SEC · dashboard", "good" if premarket_status == "ready_for_shadow_observation" else "bad")}
          {stat_card("Clean Sessions", f"{passing}/{required}", f"observed {observed}", "good" if passed else "warn")}
          {stat_card("Radar Coverage", "clean" if current.get('radar_coverage_clean') else "not clean", str(current.get('session_date') or 'no session'), "good" if current.get('radar_coverage_clean') else "bad")}
          {stat_card("Signal Stack", "clean" if current.get('signal_stack_clean') else "not clean", "zero stale/missing/error required", "good" if current.get('signal_stack_clean') else "bad")}
        </div>
        <p><strong>Status:</strong> {esc(status)}. <strong>Blockers:</strong> {esc('; '.join(str(item) for item in blockers) or 'none')}</p>
        <p><strong>Pre-open blockers:</strong> {esc('; '.join(str(item) for item in premarket_blockers) or 'none')}</p>
        """,
        "Fail-closed · no live authority · operational integrity does not prove profitability",
    )


def render_operational_runs(model: dict[str, Any]) -> str:
    """Render machine-readable run evidence; unknown state never appears green."""
    data = model.get("operational_runs") if isinstance(model.get("operational_runs"), dict) else {}
    summary = data.get("summary") if isinstance(data.get("summary"), dict) else {}
    components = data.get("components") if isinstance(data.get("components"), list) else []
    if not components and isinstance(data.get("latest_runs"), list):
        components = data["latest_runs"]

    table_rows: list[str] = []
    open_breakers = 0
    explicit_successes = 0
    now = datetime.now(timezone.utc)

    def parse_utc(value: Any) -> datetime | None:
        try:
            parsed = datetime.fromisoformat(str(value or "").replace("Z", "+00:00"))
        except (TypeError, ValueError):
            return None
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)

    for item in components:
        if not isinstance(item, dict):
            continue
        breaker = item.get("breaker") if isinstance(item.get("breaker"), dict) else {}
        breaker_state = str(item.get("breaker_state") or breaker.get("state") or "UNKNOWN").upper()
        status = str(item.get("status") or "unknown").lower()
        finished = parse_utc(item.get("finished_at"))
        observed = parse_utc(item.get("data_as_of"))
        try:
            exit_ok = int(item.get("exit_code")) == 0
            freshness_sla = max(1, int(item.get("freshness_sla_seconds") or 900))
        except (TypeError, ValueError):
            exit_ok = False
            freshness_sla = 900
        current_age = (now - observed).total_seconds() if observed else None
        healthy = (
            item.get("schema_version") == "run-envelope-v1"
            and status in {"success", "completed", "ok"}
            and breaker_state == "CLOSED"
            and not item.get("failure_class")
            and finished is not None
            and observed is not None
            and exit_ok
            and current_age is not None
            and -5 <= current_age <= freshness_sla
        )
        explicit_successes += int(healthy)
        open_breakers += int(breaker_state == "OPEN")
        tone = "good" if healthy else "warn" if status in {"running", "pending", "unknown"} and breaker_state != "OPEN" else "bad"
        breaker_tone = "good" if breaker_state == "CLOSED" else "bad" if breaker_state == "OPEN" else "warn"
        evidence = str(item.get("error") or item.get("last_reason") or item.get("detail") or "")[:300]
        table_rows.append(
            "<tr>"
            f"<td><strong>{esc(item.get('component') or item.get('scanner') or 'unknown')}</strong><small>{esc(item.get('run_id') or '')}</small></td>"
            f"<td><span class='{tone}'>{esc(status)}</span></td>"
            f"<td><span class='{breaker_tone}'>{esc(breaker_state)}</span></td>"
            f"<td>{esc(item.get('last_success_at') or 'never')}</td>"
            f"<td>{esc(item.get('data_as_of') or 'unknown')}<small>age {esc(item.get('freshness_seconds') if item.get('freshness_seconds') is not None else 'unknown')}s</small></td>"
            f"<td>{esc(item.get('duration_ms') if item.get('duration_ms') is not None else 'n/a')} ms</td>"
            f"<td>{safe_int(item.get('input_count'))} / {safe_int(item.get('output_count'))}</td>"
            f"<td>{safe_int(item.get('alerts_delivered'))}/{safe_int(item.get('alerts_attempted'))}</td>"
            f"<td>{esc(item.get('failure_class') or 'none')}<small>{esc(evidence)}</small></td>"
            f"<td>{esc(item.get('next_action') or 'none')}</td>"
            "</tr>"
        )

    top_status = str(data.get("status") or "unknown").lower()
    summary_status = str(summary.get("status") or "unknown").lower()
    schema_ok = data.get("schema_version") == "run-envelope-v1"
    declared_consistent = top_status == summary_status and top_status in {"healthy", "success", "ok"}
    all_explicit = bool(components) and explicit_successes == len(components) and open_breakers == 0
    overall = "HEALTHY" if schema_ok and declared_consistent and all_explicit else "ATTENTION"
    overall_tone = "good" if overall == "HEALTHY" else "bad"
    return section(
        "Operational Run Evidence",
        f"""
        <div class="stat-grid compact">
          {stat_card("Run State", overall, "explicit success + closed breaker required", overall_tone)}
          {stat_card("Components", str(len(components)), f"{explicit_successes} explicit successes", "good" if all_explicit else "warn")}
          {stat_card("Open Breakers", str(open_breakers), "persistent component-level state", "good" if open_breakers == 0 and components else "bad")}
          {stat_card("Schema", str(data.get('schema_version') or 'missing'), "run-envelope-v1 expected", "good" if str(data.get('schema_version')) in {'1', 'run-envelope-v1'} else "warn")}
        </div>
        <div class="table-wrap"><table><thead><tr><th>Component</th><th>Status</th><th>Breaker</th><th>Last Success</th><th>Data</th><th>Duration</th><th>In/Out</th><th>Alerts</th><th>Failure Evidence</th><th>Next Action</th></tr></thead><tbody>{''.join(table_rows) or '<tr><td colspan="10">No normalized run envelopes found. Operational state is unknown and therefore not green.</td></tr>'}</tbody></table></div>
        """,
        "Evidence-linked diagnostics · timeout, partial output, stale data, and delivery failures never count as success",
    )


def render_daily_level_map_shadow(model: dict[str, Any]) -> str:
    """Render daily-map/3m confluence evidence without inventing proprietary levels."""
    data = model.get("daily_level_map_shadow") if isinstance(model.get("daily_level_map_shadow"), dict) else {}
    candidates: Any = data.get("symbols")
    if not isinstance(candidates, list):
        for alias in ("rows", "setups", "candidates"):
            if isinstance(data.get(alias), list):
                candidates = data[alias]
                break
    rows = candidates if isinstance(candidates, list) else []
    allowed_states = {"PREMARKET", "DORMANT", "WATCH", "ARMED", "CONFIRMED", "LATE", "INVALIDATED"}
    state_counts = Counter()
    rendered_rows: list[str] = []
    valid_rows = 0
    fresh_rows = 0
    now = datetime.now(timezone.utc)

    def parse_utc(value: Any) -> datetime | None:
        try:
            parsed = datetime.fromisoformat(str(value or "").replace("Z", "+00:00"))
        except (TypeError, ValueError):
            return None
        if parsed.tzinfo is None:
            return None
        return parsed.astimezone(timezone.utc)

    def first(mapping: dict[str, Any], *names: str) -> Any:
        for name in names:
            value = mapping.get(name)
            if value not in (None, ""):
                return value
        return None

    def choose(primary: Any, fallback: Any) -> Any:
        return fallback if primary in (None, "") else primary

    try:
        freshness_sla = max(1, int(data.get("freshness_sla_seconds") or 900))
    except (TypeError, ValueError):
        freshness_sla = 900

    for raw in rows:
        if not isinstance(raw, dict):
            continue
        daily = raw.get("daily_context") if isinstance(raw.get("daily_context"), dict) else {}
        level = raw.get("nearest_level") if isinstance(raw.get("nearest_level"), dict) else {}
        confirmation = raw.get("confirmation_3m") if isinstance(raw.get("confirmation_3m"), dict) else {}
        symbol = str(first(raw, "symbol", "ticker") or "").upper()
        bias = str(choose(first(raw, "daily_bias"), first(daily, "bias", "daily_bias")) or "unknown")
        state = str(choose(first(confirmation, "state", "status"), first(raw, "state_3m", "confirmation_state", "state")) or "UNKNOWN").upper()
        state_counts[state] += 1
        price = choose(first(level, "price", "level_price", "value"), first(raw, "nearest_level_price", "level_price"))
        level_type = choose(first(level, "type", "level_type", "name"), first(raw, "nearest_level_type", "level_type"))
        source = choose(first(level, "source", "source_name"), first(raw, "level_source"))
        provenance = choose(first(level, "provenance", "provenance_label", "method"), first(raw, "level_provenance"))
        distance = choose(first(level, "distance_points", "distance", "distance_pct"), first(raw, "distance_points", "distance", "distance_pct"))
        trigger = choose(first(confirmation, "trigger", "trigger_price", "trigger_rule"), first(raw, "trigger", "trigger_price"))
        invalidation = choose(first(confirmation, "invalidation", "invalidation_price", "invalidation_rule"), first(raw, "invalidation", "invalidation_price"))
        next_target = choose(first(confirmation, "next_target", "target", "target_price"), first(raw, "next_target", "target"))
        observed_raw = choose(first(confirmation, "bar_completed_at", "observed_at", "updated_at", "data_as_of"), first(raw, "bar_completed_at", "observed_at", "updated_at", "data_as_of"))
        observed = parse_utc(observed_raw)
        age = (now - observed).total_seconds() if observed else None
        row_fresh = age is not None and -60 <= age <= freshness_sla
        required_values = (symbol, bias, price, level_type, source, provenance, distance, trigger)
        if state not in {"PREMARKET", "DORMANT"}:
            required_values += (invalidation, next_target)
        required_present = all(value not in (None, "", "unknown") for value in required_values)
        row_valid = required_present and state in allowed_states and observed is not None
        valid_rows += int(row_valid)
        fresh_rows += int(row_fresh)
        state_tone = "good" if state == "CONFIRMED" and row_valid and row_fresh else "warn" if state in {"PREMARKET", "DORMANT", "WATCH", "ARMED"} and row_valid and row_fresh else "bad"
        provenance_text = f"{source} · {provenance}"
        freshness_text = f"{max(0, int(age))}s old" if age is not None else "timestamp missing/invalid"
        rendered_rows.append(
            "<tr>"
            f"<td><strong>{esc(symbol or 'unknown')}</strong><small>{esc(raw.get('session_date') or data.get('session_date') or '')}</small></td>"
            f"<td>{esc(bias)}</td>"
            f"<td><strong>{esc(price if price is not None else 'unknown')}</strong><small>{esc(level_type or 'unknown')}</small></td>"
            f"<td>{esc(provenance_text)}</td>"
            f"<td>{esc(distance if distance is not None else 'unknown')}</td>"
            f"<td><span class='{state_tone}'>{esc(state)}</span><small>{'fresh' if row_fresh else 'STALE / UNKNOWN'}</small></td>"
            f"<td>{esc(trigger if trigger is not None else 'unknown')}</td>"
            f"<td>{esc(invalidation if invalidation is not None else 'unknown')}</td>"
            f"<td>{esc(next_target if next_target is not None else 'unknown')}</td>"
            f"<td>{esc(observed_raw or 'unknown')}<small>{esc(freshness_text)}</small></td>"
            "</tr>"
        )

    generated = parse_utc(data.get("generated_at"))
    report_age = (now - generated).total_seconds() if generated else None
    report_fresh = report_age is not None and -60 <= report_age <= freshness_sla
    schema_ok = data.get("schema_version") == "daily-level-map-shadow-v1"
    status_ok = str(data.get("status") or "").lower() in {"healthy", "success", "completed", "ok"}
    shadow_only = data.get("shadow_only") is True and data.get("execution_enabled") is False and data.get("can_submit_orders") is False
    coverage = data.get("coverage") if isinstance(data.get("coverage"), dict) else {}
    session_state = str(data.get("session_state") or ("rth" if coverage.get("completed_3m_expected_now") is True else "unknown")).lower()
    confirmation_expected = coverage.get("completed_3m_expected_now") is True
    coverage_complete = safe_int(coverage.get("available")) == safe_int(coverage.get("requested")) and safe_int(coverage.get("requested")) > 0
    all_rows_valid = bool(rows) and valid_rows == len(rows)
    all_rows_fresh = bool(rows) and fresh_rows == len(rows)
    overall_ok = confirmation_expected and schema_ok and status_ok and shadow_only and report_fresh and all_rows_valid and all_rows_fresh
    premarket_ready = schema_ok and status_ok and shadow_only and report_fresh and coverage_complete and session_state == "premarket"
    postmarket_complete = schema_ok and status_ok and shadow_only and report_fresh and coverage_complete and session_state == "postmarket"
    overall = "READY" if overall_ok else "PREMARKET READY / 3M WAITING" if premarket_ready else "POSTMARKET / SESSION COMPLETE" if postmarket_complete else "ATTENTION"

    return section(
        "Daily Map & 3m Confluence",
        f"""
        <div class="stat-grid compact">
          {stat_card("Map State", overall, "fresh, complete evidence required after 9:33 ET", "good" if overall_ok else "warn" if premarket_ready or postmarket_complete else "bad")}
          {stat_card("Symbols", str(len(rows)), f"{valid_rows} structurally valid", "good" if all_rows_valid else "bad")}
          {stat_card("WATCH", str(state_counts['WATCH']), "approaching mapped level", "warn")}
          {stat_card("ARMED", str(state_counts['ARMED']), "daily aligned at level", "warn")}
          {stat_card("CONFIRMED", str(state_counts['CONFIRMED']), "completed 3m confirmation", "good" if state_counts['CONFIRMED'] else "")}
          {stat_card("PREMARKET", str(state_counts['PREMARKET']), "daily map ready; RTH 3m pending", "warn" if state_counts['PREMARKET'] else "")}
          {stat_card("Late / Invalid", str(state_counts['LATE'] + state_counts['INVALIDATED']), "do not chase / setup failed", "bad" if state_counts['LATE'] + state_counts['INVALIDATED'] else "")}
        </div>
        <p class="muted"><strong>SHADOW SIMULATION ONLY · NO ORDERS:</strong> This display maps transparent, provenance-labeled levels. It does not infer or reproduce proprietary formulas.</p>
        <div class="table-wrap"><table><thead><tr><th>Symbol</th><th>Daily Bias</th><th>Nearest Level</th><th>Source / Provenance</th><th>Distance</th><th>3m State</th><th>Trigger</th><th>Invalidation</th><th>Next Target</th><th>Evidence Time</th></tr></thead><tbody>{''.join(rendered_rows) or '<tr><td colspan="10">No valid daily-map report found. State is unknown and therefore ATTENTION—not green.</td></tr>'}</tbody></table></div>
        """,
        f"Report {esc(data.get('generated_at') or 'missing')} · SLA {freshness_sla}s · schema {esc(data.get('schema_version') or 'missing')}",
    )


def render_priority_universe_recall(model: dict[str, Any]) -> str:
    """Render fixed-universe observation coverage without inventing outcomes."""
    data = model.get("daily_move_coverage_review") if isinstance(model.get("daily_move_coverage_review"), dict) else {}
    coverage = data.get("priority_universe_coverage") if isinstance(data.get("priority_universe_coverage"), dict) else {}
    rows = coverage.get("symbols") if isinstance(coverage.get("symbols"), list) else []
    moves = {
        str(row.get("symbol") or "").upper(): row
        for row in data.get("moves") or []
        if isinstance(row, dict) and row.get("symbol")
    }
    try:
        sla = max(1, int(data.get("freshness_sla_seconds") or 129600))
    except (TypeError, ValueError):
        sla = 129600
    try:
        generated = datetime.fromisoformat(str(data.get("generated_at") or "").replace("Z", "+00:00"))
        generated = generated.astimezone(timezone.utc) if generated.tzinfo else None
    except (TypeError, ValueError):
        generated = None
    age = (datetime.now(timezone.utc) - generated).total_seconds() if generated else None
    fresh = age is not None and -60 <= age <= sla
    authority_ok = data.get("execution_enabled") is False and data.get("can_submit_orders") is False
    schema_ok = data.get("schema_version") == 5
    valid_rows = [row for row in rows if isinstance(row, dict) and row.get("symbol")]
    evaluated_count = sum(row.get("evaluated") is True for row in valid_rows)
    debt_count = sum(bool(row.get("coverage_debt")) for row in valid_rows)
    execution_eligible_count = 0
    body_rows: list[str] = []
    for row in valid_rows:
        symbol = str(row.get("symbol") or "").upper()
        move = moves.get(symbol, {})
        stages = move.get("stages") if isinstance(move.get("stages"), dict) else {}
        execution_eligible = stages.get("execution_qualified") is True
        execution_eligible_count += int(execution_eligible)
        observed = row.get("evaluated") is True
        debt = str(row.get("coverage_debt") or "none")
        outcome = str(row.get("outcome_status") or "unknown")
        body_rows.append(
            "<tr>"
            f"<td><strong>{esc(symbol)}</strong></td>"
            f"<td class='{('good' if observed else 'bad')}'>{'OBSERVED' if observed else 'MISSING'}</td>"
            f"<td class='{('good' if execution_eligible else 'warn')}'>{'YES' if execution_eligible else 'NO / UNKNOWN'}</td>"
            f"<td>{esc(outcome)}</td><td class='{('bad' if debt != 'none' else '')}'>{esc(debt)}</td>"
            "</tr>"
        )
    structurally_valid = bool(valid_rows) and len(valid_rows) == len(rows)
    ready = schema_ok and authority_ok and fresh and structurally_valid and debt_count == 0
    status = "COMPLETE" if ready else "ATTENTION"
    freshness = f"{max(0, int(age))}s old" if age is not None else "timestamp missing"
    recall_reason = str(coverage.get("recall_not_computable_reason") or "not supplied")
    return section(
        "Priority-Universe Recall",
        f"""
        <div class="stat-grid compact">
          {stat_card("Coverage", status, freshness, "good" if ready else "bad")}
          {stat_card("Observed / evaluated", f"{evaluated_count}/{len(valid_rows)}", "fixed priority denominator", "good" if debt_count == 0 and valid_rows else "warn")}
          {stat_card("Execution-eligible", str(execution_eligible_count), "separate gated stage; not observation", "warn")}
          {stat_card("Coverage debt", str(debt_count), "missing symbols remain explicit", "bad" if debt_count else "good")}
        </div>
        <p class="muted"><strong>Recall not computable:</strong> {esc(recall_reason)}. Symbols absent from the bounded mover provider have unknown outcomes, not “no move.”</p>
        <div class="table-wrap"><table><thead><tr><th>Symbol</th><th>Observed / evaluated</th><th>Execution-eligible</th><th>Outcome scope</th><th>Coverage debt</th></tr></thead><tbody>{''.join(body_rows) or '<tr><td colspan="5" class="bad">Priority coverage missing — ATTENTION</td></tr>'}</tbody></table></div>
        <p class="muted"><strong>Observation only:</strong> evaluation does not authorize an entry. No fill or option premium is inferred. No P/L or profitability is inferred.</p>
        """,
        f"Generated {esc(data.get('generated_at') or 'missing')} · {'fresh' if fresh else 'STALE / UNKNOWN'} · shadow-only authority required",
    )


def render_priority_swing_observation(model: dict[str, Any]) -> str:
    """Render persistent daily swing states as observation, never performance."""
    data = model.get("priority_swing_observation") if isinstance(model.get("priority_swing_observation"), dict) else {}
    observations = [row for row in data.get("observations") or [] if isinstance(row, dict)]
    transitions = [row for row in model.get("priority_swing_events") or [] if isinstance(row, dict)]
    transitions.extend(row for row in data.get("transition_events") or [] if isinstance(row, dict))
    priority = [str(value).upper() for value in data.get("priority_symbols") or [] if value]
    now = datetime.now(timezone.utc)

    def timestamp(value: Any) -> datetime | None:
        try:
            parsed = datetime.fromisoformat(str(value or "").replace("Z", "+00:00"))
        except (TypeError, ValueError):
            return None
        return parsed.astimezone(timezone.utc) if parsed.tzinfo else None

    try:
        sla = max(1, int(data.get("freshness_sla_seconds") or 129600))
    except (TypeError, ValueError):
        sla = 129600
    generated = timestamp(data.get("generated_at"))
    report_age = (now - generated).total_seconds() if generated else None
    fresh = report_age is not None and -60 <= report_age <= sla
    authority_ok = data.get("execution_enabled") is False and data.get("can_submit_orders") is False
    schema_ok = data.get("schema_version") == "priority-swing-observation-v1" and data.get("provider") == "priority_swing_observation"
    by_symbol = {str(row.get("symbol") or "").upper(): row for row in observations if row.get("symbol")}
    missing = [symbol for symbol in priority if symbol not in by_symbol]
    summary = data.get("summary") if isinstance(data.get("summary"), dict) else {}
    evidence_missing = [
        symbol for symbol, row in by_symbol.items()
        if not isinstance(row.get("completed_daily_evidence"), dict)
        or row.get("completed_daily_evidence", {}).get("status") != "available"
    ]
    allowed_states = {"WATCH", "ARMED", "CONFIRMED", "INVALIDATED"}
    rows: list[str] = []
    eligible_count = 0
    for symbol in priority or sorted(by_symbol):
        row = by_symbol.get(symbol)
        if row is None:
            rows.append(f"<tr><td><strong>{esc(symbol)}</strong></td><td colspan='8' class='bad'>MISSING — persistent state coverage fault</td></tr>")
            continue
        state = str(row.get("state") or "UNKNOWN").upper()
        eligible = row.get("strict_execution_eligible") is True
        eligible_count += int(eligible)
        matching = [event for event in transitions if str(event.get("symbol") or "").upper() == symbol]
        matching.sort(key=lambda event: timestamp(event.get("observed_at")) or datetime.min.replace(tzinfo=timezone.utc))
        last = matching[-1] if matching else {}
        transitioned = timestamp(last.get("observed_at"))
        state_age = (now - transitioned).total_seconds() if transitioned else None
        transition_text = (
            f"{last.get('previous_state')} → {last.get('state')}"
            if last else f"{row.get('previous_state') or 'unknown'} → {state} (timestamp unavailable)"
        )
        blockers = ", ".join(str(value) for value in row.get("blockers") or []) or "none"
        row_authority = row.get("execution_enabled") is False and row.get("can_submit_orders") is False
        state_valid = state in allowed_states
        tone = "good" if state == "CONFIRMED" and eligible and row_authority else "bad" if state == "INVALIDATED" or not state_valid or not row_authority else "warn"
        rows.append(
            "<tr>"
            f"<td><strong>{esc(symbol)}</strong><small>{esc(row.get('setup_family') or 'unknown')}</small></td>"
            f"<td class='{tone}'>{esc(state)}</td><td>{'YES' if row.get('continuing_setup') is True else 'NO'}</td>"
            f"<td>{'YES' if eligible else 'NO'}</td><td>{esc(row.get('validation_status') or 'unknown')}</td>"
            f"<td>{esc(row.get('trigger') if row.get('trigger') is not None else 'unknown')} / {esc(row.get('invalidation') if row.get('invalidation') is not None else 'unknown')}</td>"
            f"<td>{esc(transition_text)}</td><td>{esc(f'{int(state_age)}s' if state_age is not None and state_age >= 0 else 'unknown')}</td>"
            f"<td>{esc(blockers)}</td></tr>"
        )
    state_rows_valid = all(str(row.get("state") or "").upper() in allowed_states for row in observations)
    producer_errors = safe_int(summary.get("errors"), len(data.get("errors") or []))
    complete = (
        bool(priority) and not missing and not evidence_missing and len(by_symbol) == len(priority)
        and safe_int(summary.get("symbols_observed"), len(by_symbol)) == len(priority)
        and producer_errors == 0
    )
    ready = schema_ok and authority_ok and fresh and complete and state_rows_valid
    status = "CURRENT" if ready else "ATTENTION"
    age_text = f"{max(0, int(report_age))}s old" if report_age is not None else "timestamp missing"
    return section(
        "Persistent Swing Lifecycle",
        f"""
        <div class="stat-grid compact">
          {stat_card("Lifecycle", status, age_text, "good" if ready else "bad")}
          {stat_card("Priority states", f"{len(by_symbol)}/{len(priority)}", "persistent across daily refreshes", "good" if complete else "bad")}
          {stat_card("Execution-eligible", str(eligible_count), "strict gated field; observation is separate", "warn")}
          {stat_card("Missing / errored", str(len(set(missing + evidence_missing)) + producer_errors), ", ".join(sorted(set(missing + evidence_missing))) or "none", "bad" if missing or evidence_missing or producer_errors else "good")}
        </div>
        <div class="table-wrap"><table><thead><tr><th>Symbol / setup</th><th>State</th><th>Continuing</th><th>Execution-eligible</th><th>Validation</th><th>Trigger / invalidation</th><th>Last transition</th><th>State age</th><th>Blockers</th></tr></thead><tbody>{''.join(rows) or '<tr><td colspan="9" class="bad">Persistent swing lifecycle missing — ATTENTION</td></tr>'}</tbody></table></div>
        <p class="muted"><strong>Shadow observation only:</strong> WATCH, ARMED, or CONFIRMED describes lifecycle state, not a return. No fills are assumed. No P/L or profitability is inferred.</p>
        """,
        f"Generated {esc(data.get('generated_at') or 'missing')} · {'fresh' if fresh else 'STALE / UNKNOWN'} · source {esc(data.get('universe_source') or 'missing')}",
    )


def render_overview(model: dict[str, Any]) -> str:
    bot_status = model["bot_status"] if isinstance(model["bot_status"], dict) else {}
    account = bot_status.get("account") if isinstance(bot_status.get("account"), dict) else {}
    audit = model["audit"] if isinstance(model["audit"], dict) else {}
    daily = model["daily_eod"] if isinstance(model["daily_eod"], dict) else {}
    health = bot_status.get("health") if isinstance(bot_status.get("health"), dict) else {}
    market = bot_status.get("market_force") if isinstance(bot_status.get("market_force"), dict) else {}
    exposure = bot_status.get("exposure") if isinstance(bot_status.get("exposure"), dict) else {}
    review = model["review"] if isinstance(model["review"], dict) else {}
    return f"""
    <div class="stat-grid hero-grid">
      {stat_card("Account Equity", money(account.get("equity")), f"day {money(account.get('day_change'))}", cls_for_signed(account.get("day_change")))}
      {stat_card("Execution Audit", "PASS" if audit.get("passed") else "CHECK", f"{safe_int(audit.get('registered_signal_count'))} signals / {safe_int(audit.get('issue_count'))} issues", "good" if audit.get("passed") else "bad")}
      {stat_card("Stack Verdict", str(daily.get("verdict") or "unknown"), str((daily.get("plain_english") or {}).get("headline", "")), cls_for_health(daily.get("verdict")))}
      {stat_card("Health", str(health.get("status") or "unknown"), f"OK {safe_int(health.get('ok'))} / stale {safe_int(health.get('stale'))} / error {safe_int(health.get('error'))}", cls_for_health(health.get("status")))}
      {stat_card("Market Force", str(market.get("classification") or "unknown"), f"score {safe_float(market.get('score')):g} / conf {safe_float(market.get('confidence')):g}", cls_for_health(market.get("classification")))}
      {stat_card("Exposure", str(exposure.get("posture") or "unknown"), f"score {safe_float(exposure.get('score')):g}", cls_for_health(exposure.get("posture")))}
      {stat_card("Needs Review", str(safe_int(review.get("queue_count"))), grade_counts_text(review.get("by_reason", {}) if isinstance(review.get("by_reason"), dict) else {}), "warn" if safe_int(review.get("queue_count")) else "good")}
      {stat_card("Generated", str(model["generated_at"]), "static HTML, no server", "")}
    </div>"""


def render_risk_state(model: dict[str, Any]) -> str:
    bot_status = model["bot_status"] if isinstance(model["bot_status"], dict) else {}
    portfolio = bot_status.get("portfolio_concentration") if isinstance(bot_status.get("portfolio_concentration"), dict) else {}
    guard = bot_status.get("guard_blocks") if isinstance(bot_status.get("guard_blocks"), dict) else {}
    sizing = model["position_sizing"] if isinstance(model["position_sizing"], dict) else {}
    limits = sizing.get("configured_limits") if isinstance(sizing.get("configured_limits"), dict) else {}
    candidate = sizing.get("candidate_sizing") if isinstance(sizing.get("candidate_sizing"), dict) else {}
    post = sizing.get("post_config") if isinstance(sizing.get("post_config"), dict) else {}
    return section(
        "Risk State",
        f"""
        <div class="stat-grid compact">
          {stat_card("Kill Switch", "OFF", "no active portfolio kill file reported", "good")}
          {stat_card("Max Contracts", str(safe_int(limits.get("max_contracts")) or 5), f"post-fix max seen {safe_int(post.get('max_contracts_seen'))}", "good")}
          {stat_card("Max Risk", pct(limits.get("max_risk_pct"), scale=True), f"risk budget {money(candidate.get('risk_budget'))}", "good")}
          {stat_card("Guard Blocks", str(safe_int(guard.get("alpaca")) + safe_int(guard.get("kalshi"))), f"Alpaca {safe_int(guard.get('alpaca'))} / Kalshi {safe_int(guard.get('kalshi'))}", "warn")}
          {stat_card("Concentration", str(portfolio.get("risk_level") or "unknown"), f"{safe_float(portfolio.get('gross_pct_equity')):.2f}% gross equity", cls_for_health(portfolio.get("risk_level")))}
          {stat_card("Tail Loss Post-Fix", pct((post.get("tail_bounds") or {}).get("empirical_tail_rate"), scale=True), "empirical 50% loss-rate bound", "good")}
        </div>
        """,
        "Risk controls are surfaced for review only. This dashboard does not unlock execution.",
    )


def render_bot_health(model: dict[str, Any]) -> str:
    grades_items = (model["grades"] or {}).get("items", []) if isinstance(model.get("grades"), dict) else []
    by_name = {item.get("name"): item for item in grades_items if isinstance(item, dict)}
    flip_stats = flip_trade_stats(model["flip_trades"] if isinstance(model["flip_trades"], list) else [])
    opt_state = model["options_state"] if isinstance(model["options_state"], dict) else {}
    opt_stats = option_trade_stats(opt_state, model["positions"])
    flip_grade = by_name.get("Flip Bot", {})
    iwm_grade = by_name.get("IWM Options Bot", {})
    rows = [
        ("Flip Bot", flip_stats, flip_grade, money(flip_stats["pnl"]), money(flip_stats["post_pnl"]), pct(flip_stats["post_win_rate"], scale=True)),
        ("IWM Options Bot", opt_stats, iwm_grade, money(opt_stats["realized_est"]) + " est.", money(opt_stats["unrealized"]), pct(opt_stats["win_rate"], scale=True)),
    ]
    body = []
    for name, stats, grade, pnl_text, open_text, wr_text in rows:
        post = grade.get("post_config") if isinstance(grade.get("post_config"), dict) else {}
        evidence = post.get("grade") if name == "Flip Bot" and post else grade.get("evidence_grade") or grade.get("grade")
        body.append(
            "<tr>"
            f"<td><strong>{esc(name)}</strong><small>{esc(grade.get('mode') or 'paper/read-only')}</small></td>"
            f"<td>{safe_int(stats.get('total'))}</td>"
            f"<td>{safe_int(stats.get('open'))}</td>"
            f"<td>{safe_int(stats.get('closed'))}</td>"
            f"<td class=\"{cls_for_signed(stats.get('pnl', stats.get('realized_est', 0)))}\">{pnl_text}</td>"
            f"<td>{open_text}</td>"
            f"<td>{wr_text}</td>"
            f"<td class=\"{cls_for_grade(grade.get('ops_grade'))}\">{esc(grade.get('ops_grade') or 'n/a')}</td>"
            f"<td class=\"{cls_for_grade(evidence)}\">{esc(evidence or 'n/a')}</td>"
            f"<td>{esc(', '.join(str(w) for w in (grade.get('warnings') or [])[:2]))}</td>"
            "</tr>"
        )
    return section(
        "Bot Health And P/L",
        f"""
        <div class="table-wrap">
          <table>
            <thead><tr><th>Bot</th><th>Total</th><th>Open</th><th>Closed</th><th>Realized P/L</th><th>Open/Post-Fix P/L</th><th>Win</th><th>Ops</th><th>Evidence</th><th>Notes</th></tr></thead>
            <tbody>{''.join(body)}</tbody>
          </table>
        </div>
        """,
        "Flip Bot uses exact ledger P/L. IWM realized P/L is estimated when the state file only stores credit and close reason.",
    )


def render_chart_panel(model: dict[str, Any]) -> str:
    hot_items = (model.get("chart_data") or {}).get("hotRanked", [])
    max_hot = max((safe_float(item.get("hot_score")) for item in hot_items), default=1.0) or 1.0
    hot_rows = []
    for item in hot_items[:10]:
        width = max(2.0, min(100.0, safe_float(item.get("hot_score")) / max_hot * 100))
        hot_rows.append(
            "<div class=\"rank-row\">"
            f"<span class=\"rank-symbol\">{esc(item.get('symbol'))}</span>"
            "<span class=\"rank-track\">"
            f"<i style=\"width:{width:.1f}%\"></i>"
            "</span>"
            f"<span class=\"rank-score\">{safe_float(item.get('hot_score')):.2f}</span>"
            f"<span class=\"rank-meta {cls_for_signed(item.get('hypothetical_pnl'))}\">{money(item.get('hypothetical_pnl'))}</span>"
            "</div>"
        )
    return f"""
    <div class="chart-grid">
      <div class="panel chart-panel">
        <h3>Account Equity</h3>
        <div id="chart-account-equity" class="chart-box" data-chart="account-equity"></div>
        <p class="chart-note">Equity snapshots from bot status logs.</p>
      </div>
      <div class="panel chart-panel">
        <h3>Bot Cumulative P/L</h3>
        <div id="chart-bot-pnl" class="chart-box" data-chart="bot-pnl"></div>
        <p class="chart-note">Flip exact ledger P/L and IWM estimated realized P/L.</p>
      </div>
      <div class="panel chart-panel">
        <h3>Health + Grade Trend</h3>
        <div id="chart-health-grades" class="chart-box" data-chart="health-grades"></div>
        <p class="chart-note">Stale/error scanner counts and grade distribution snapshots.</p>
      </div>
      <div class="panel chart-panel">
        <h3>Hot Ticker Ranking</h3>
        <div class="rank-chart">{''.join(hot_rows) or '<p class="chart-note">No hot ticker report loaded.</p>'}</div>
        <p class="chart-note">Hot score is context only; green/red value is hypothetical shadow P/L.</p>
      </div>
    </div>"""


def render_daily_pnl(model: dict[str, Any]) -> str:
    by_day: dict[str, list[dict]] = {}
    unreconciled: list[dict[str, str]] = []

    for trade in model["flip_trades"] if isinstance(model["flip_trades"], list) else []:
        pnl = safe_float(trade.get("pnl")) if trade.get("pnl") not in (None, "") else None
        day = str(trade.get("exit_date") or trade.get("entry_date") or "")[:10]
        if not day or pnl is None:
            continue
        by_day.setdefault(day, []).append({
            "symbol": str(trade.get("symbol") or ""),
            "bot": "Flip Bot",
            "pnl": pnl,
            "detail": str(trade.get("exit_reason") or trade.get("status") or ""),
        })

    state = model["options_state"] if isinstance(model["options_state"], dict) else {}
    for trade in state.get("trades") if isinstance(state.get("trades"), list) else []:
        if trade.get("status") != "closed":
            continue
        pnl = parse_credit_pnl_estimate(trade)
        day = str(trade.get("closed_at") or trade.get("opened_at") or "")[:10]
        provenance = option_pnl_provenance(trade)
        symbol = str(trade.get("label") or trade.get("underlying") or "IWM")
        if not day:
            continue
        if pnl is None:
            unreconciled.append({
                "day": day,
                "symbol": symbol,
                "detail": str(trade.get("closing_reason") or "closing fill / debit missing"),
            })
            continue
        by_day.setdefault(day, []).append({
            "symbol": symbol,
            "bot": "IWM Bot",
            "pnl": pnl,
            "detail": f"{'Exact ledger' if provenance == 'reconciled' else 'Estimated from exit rule'} · {str(trade.get('closing_reason') or '')}",
        })

    if not by_day and not unreconciled:
        return section("Daily P/L by Symbol", "<p style='color:var(--muted);padding:12px'>No closed trades found.</p>")

    rows = []
    running_total = 0.0
    for day in sorted(by_day.keys(), reverse=True):
        trades = by_day[day]
        day_total = sum(t["pnl"] for t in trades)
        running_total += day_total
        tone = "pos" if day_total >= 0 else "neg"
        rows.append(
            f'<tr class="day-header">'
            f'<td colspan="3"><strong>{esc(day)}</strong></td>'
            f'<td class="{cls_for_signed(day_total)}"><strong>{money(day_total)}</strong></td>'
            f'<td class="muted">running: {money(running_total)}</td>'
            f'</tr>'
        )
        for t in sorted(trades, key=lambda x: x["pnl"], reverse=True):
            rows.append(
                f'<tr>'
                f'<td></td>'
                f'<td><strong>{esc(t["symbol"])}</strong></td>'
                f'<td class="muted">{esc(t["bot"])}</td>'
                f'<td class="{cls_for_signed(t["pnl"])}">{money(t["pnl"])}</td>'
                f'<td class="muted small">{esc(t["detail"][:60])}</td>'
                f'</tr>'
            )

    table = (
        '<div class="table-wrap">'
        '<table><thead><tr>'
        '<th>Date</th><th>Symbol</th><th>Bot</th><th>P/L</th><th>Detail</th>'
        '</tr></thead><tbody>'
        + "".join(rows)
        + "</tbody></table></div>"
    )
    reconciliation = ""
    if unreconciled:
        missing_rows = "".join(
            f"<tr><td>{esc(item['day'])}</td><td><strong>{esc(item['symbol'])}</strong></td>"
            f"<td class='bad'>UNRECONCILED</td><td class='muted small'>{esc(item['detail'][:100])}</td></tr>"
            for item in unreconciled
        )
        reconciliation = (
            "<h3>Excluded from P/L until reconciled</h3><div class='table-wrap'><table><thead>"
            "<tr><th>Date</th><th>Symbol</th><th>Status</th><th>Missing evidence</th></tr></thead><tbody>"
            + missing_rows + "</tbody></table></div>"
        )
    return section(
        "Daily P/L by Symbol",
        table + reconciliation,
        "Flip = exact ledger P/L · options are labeled reconciled, estimated, or excluded",
    )


def render_flip_trades(model: dict[str, Any]) -> str:
    rows = []
    for trade in model["flip_trades"] if isinstance(model["flip_trades"], list) else []:
        pnl = safe_float(trade.get("pnl")) if trade.get("pnl") is not None else None
        rows.append(
            "<tr>"
            f"<td>{esc(trade.get('entry_date'))}</td>"
            f"<td><strong>{esc(trade.get('symbol'))}</strong><small>{esc(trade.get('option_symbol'))}</small></td>"
            f"<td>{esc(trade.get('strategy'))}</td>"
            f"<td>{esc(trade.get('right'))}</td>"
            f"<td>{safe_int(trade.get('contracts'))}</td>"
            f"<td>{money(safe_float(trade.get('entry_price')) * 100, unknown='n/a')}</td>"
            f"<td>{money(safe_float(trade.get('exit_price')) * 100, unknown='open')}</td>"
            f"<td class=\"{cls_for_signed(pnl)}\">{money(pnl)}</td>"
            f"<td>{esc(trade.get('exit_reason') or trade.get('status'))}</td>"
            "</tr>"
        )
    return section(
        "Flip Bot Trades",
        f"""<div class="table-wrap trades"><table><thead><tr><th>Entry</th><th>Contract</th><th>Strategy</th><th>Side</th><th>Qty</th><th>Entry</th><th>Exit</th><th>P/L</th><th>Exit Reason</th></tr></thead><tbody>{''.join(rows) or '<tr><td colspan="9">No Flip trades found.</td></tr>'}</tbody></table></div>""",
        "All recorded Flip Bot trades, including the pre-fix 69-contract artifact for historical honesty.",
    )


def render_iwm_trades(model: dict[str, Any]) -> str:
    state = model["options_state"] if isinstance(model["options_state"], dict) else {}
    trades = state.get("trades") if isinstance(state.get("trades"), list) else []
    positions_by_symbol = model["positions_by_symbol"]
    rows = []
    for trade in trades:
        est = parse_credit_pnl_estimate(trade)
        open_unrealized = iwm_open_unrealized(trade, positions_by_symbol) if trade.get("status") != "closed" else None
        pnl_value = est if est is not None else open_unrealized
        pnl_label = money(pnl_value) + (" est." if est is not None and trade.get("pnl") in (None, "") else "")
        confidence = trade.get("candidate_confidence") if isinstance(trade.get("candidate_confidence"), dict) else {}
        rows.append(
            "<tr>"
            f"<td>{esc(str(trade.get('opened_at') or '')[:10])}</td>"
            f"<td><strong>{esc(trade.get('label') or trade.get('underlying'))}</strong><small>{esc(', '.join(str(x) for x in (trade.get('legs') or [])[:4]))}</small></td>"
            f"<td>{esc(trade.get('strategy'))}</td>"
            f"<td>{esc(trade.get('status'))}</td>"
            f"<td>{safe_int(trade.get('qty'), 1)}</td>"
            f"<td>{money(safe_float(trade.get('net_credit')) * 100, unknown='n/a')}</td>"
            f"<td>{money(safe_float(trade.get('max_risk_per_contract')), unknown='n/a')}</td>"
            f"<td class=\"{cls_for_signed(pnl_value)}\">{pnl_label}</td>"
            f"<td>{safe_float(confidence.get('score')):g}</td>"
            f"<td>{esc(trade.get('closing_reason') or trade.get('expiry') or '')}</td>"
            "</tr>"
        )
    return section(
        "IWM / Options Bot Trades",
        f"""<div class="table-wrap trades"><table><thead><tr><th>Opened</th><th>Trade</th><th>Strategy</th><th>Status</th><th>Qty</th><th>Credit</th><th>Max Risk</th><th>P/L</th><th>Conf</th><th>Close / Expiry</th></tr></thead><tbody>{''.join(rows) or '<tr><td colspan="10">No options trades found.</td></tr>'}</tbody></table></div>""",
        "Closed P/L is estimated from credit and close reason when broker-realized P/L is not stored.",
    )


def render_shadow_and_health(model: dict[str, Any]) -> str:
    health = model["health"] if isinstance(model["health"], dict) else {}
    summary = health.get("summary") if isinstance(health.get("summary"), dict) else {}
    items = health.get("items") if isinstance(health.get("items"), list) else []
    shadow_audit = model.get("shadow_audit") if isinstance(model.get("shadow_audit"), dict) else {}
    audit_summary = shadow_audit.get("summary") if isinstance(shadow_audit.get("summary"), dict) else {}
    eligible = safe_int(audit_summary.get("performance_eligible_count"))
    quarantined = safe_int(audit_summary.get("performance_quarantined_count"))
    eligibility_contract_present = "performance_quarantined_count" in audit_summary
    problem_rows = []
    for item in items:
        status = str(item.get("health") or "")
        if status == "ok" and len(problem_rows) >= 10:
            continue
        warnings = item.get("warnings") if isinstance(item.get("warnings"), list) else []
        problem_rows.append(
            "<tr>"
            f"<td><strong>{esc(item.get('name'))}</strong><small>{esc(item.get('task'))}</small></td>"
            f"<td class=\"{cls_for_health(status)}\">{esc(status)}</td>"
            f"<td>{esc(item.get('kind'))}</td>"
            f"<td>{esc(item.get('latest_date'))}</td>"
            f"<td>{safe_int(item.get('row_count'))}</td>"
            f"<td>{esc('; '.join(str(w) for w in warnings[:2]))}</td>"
            "</tr>"
        )
        if len(problem_rows) >= 18:
            break
    return section(
        "Shadow Loggers And Signal Health",
        f"""
        <div class="stat-grid compact">
          {stat_card("OK", str(safe_int(summary.get("ok"))), "fresh or acceptable", "good")}
          {stat_card("Stale", str(safe_int(summary.get("stale"))), "needs follow-up", "warn")}
          {stat_card("Error", str(safe_int(summary.get("error"))), "data/feed problem", "bad" if safe_int(summary.get("error")) else "good")}
          {stat_card("Missing", str(safe_int(summary.get("missing"))), "no log found", "bad" if safe_int(summary.get("missing")) else "good")}
          {stat_card("Performance Eligible", str(eligible), "independently resolved outcomes", "good" if eligibility_contract_present else "bad")}
          {stat_card("Evidence Quarantined", str(quarantined) if eligibility_contract_present else "unknown", "visible, excluded from performance/promotion", "warn" if eligibility_contract_present else "bad")}
        </div>
        <p><strong>Fail-closed evidence policy:</strong> raw streams remain visible; streams without independently resolved outcomes cannot support performance or promotion claims.</p>
        <div class="table-wrap">
          <table><thead><tr><th>Logger / Scanner</th><th>Health</th><th>Kind</th><th>Latest</th><th>Rows</th><th>Warnings</th></tr></thead><tbody>{''.join(problem_rows)}</tbody></table>
        </div>
        """,
    )


def render_market_mastery(model: dict[str, Any]) -> str:
    catalyst = model.get("market_catalyst") if isinstance(model.get("market_catalyst"), dict) else {}
    candlesticks = model.get("candlestick_context") if isinstance(model.get("candlestick_context"), dict) else {}
    higher_timeframe = model.get("higher_timeframe") if isinstance(model.get("higher_timeframe"), dict) else {}
    today = catalyst.get("today") if isinstance(catalyst.get("today"), dict) else {}
    candle_items = candlesticks.get("items") if isinstance(candlesticks.get("items"), list) else []
    htf_items = higher_timeframe.get("items") if isinstance(higher_timeframe.get("items"), list) else []
    candle_summary = candlesticks.get("summary") if isinstance(candlesticks.get("summary"), dict) else {}
    htf_summary = higher_timeframe.get("summary") if isinstance(higher_timeframe.get("summary"), dict) else {}
    htf_by_symbol = {
        str(item.get("symbol")).upper(): item
        for item in htf_items
        if isinstance(item, dict) and item.get("symbol")
    }

    events = today.get("events") if isinstance(today.get("events"), list) else []
    event_text = ", ".join(
        f"{event.get('time_et', 'time n/a')} {event.get('name', 'event')} ({event.get('impact', 'impact n/a')})"
        for event in events[:3]
        if isinstance(event, dict)
    ) or "No scheduled catalyst report found."
    vetoes = today.get("vetoes") if isinstance(today.get("vetoes"), list) else []
    veto_text = ", ".join(str(veto) for veto in vetoes) if vetoes else "none"

    rows = []
    for item in candle_items[:12]:
        if not isinstance(item, dict):
            continue
        symbol = str(item.get("symbol") or "").upper()
        htf = htf_by_symbol.get(symbol, {})
        candle_playbooks = item.get("allowed_playbooks") if isinstance(item.get("allowed_playbooks"), list) else []
        htf_playbooks = htf.get("allowed_playbooks") if isinstance(htf.get("allowed_playbooks"), list) else []
        shared = sorted(set(map(str, candle_playbooks)).intersection(map(str, htf_playbooks)))
        if not shared:
            shared = sorted(set(map(str, candle_playbooks or htf_playbooks)))
        rows.append(
            "<tr>"
            f"<td>{esc(symbol)}</td>"
            f"<td><span class='{cls_for_health(item.get('bias'))}'>{esc(item.get('bias', 'n/a'))}</span></td>"
            f"<td>{esc(item.get('primary_signal', 'none'))}</td>"
            f"<td><span class='{cls_for_health(htf.get('primary_bias'))}'>{esc(htf.get('primary_bias', 'n/a'))}</span></td>"
            f"<td>{esc(htf.get('intraday_alignment', 'n/a'))}</td>"
            f"<td>{esc(', '.join(shared) if shared else 'stand_aside')}</td>"
            "</tr>"
        )

    return section(
        "Market Mastery",
        f"""
        <div class="stat-grid compact">
          <div class="stat"><span>Catalyst Risk</span><strong>{esc(today.get("max_impact", "n/a"))}</strong><small>{esc(today.get("date", ""))}</small></div>
          <div class="stat"><span>Events</span><strong>{safe_int(len(events))}</strong><small>{esc(event_text)}</small></div>
          <div class="stat"><span>Vetoes</span><strong>{safe_int(len(vetoes))}</strong><small>{esc(veto_text)}</small></div>
          <div class="stat"><span>Candles</span><strong>{esc(grade_counts_text(candle_summary))}</strong><small>pattern context, not execution</small></div>
          <div class="stat"><span>HTF Map</span><strong>{esc(grade_counts_text(htf_summary))}</strong><small>daily/weekly/intraday alignment</small></div>
        </div>
        <div class="table-wrap">
          <table>
            <thead><tr><th>Symbol</th><th>Candle Bias</th><th>Pattern</th><th>HTF Bias</th><th>Alignment</th><th>Allowed Playbook</th></tr></thead>
            <tbody>{''.join(rows) or '<tr><td colspan="6">No market mastery rows found. Run candlestick, higher timeframe, and catalyst scanners.</td></tr>'}</tbody>
          </table>
        </div>
        """,
        "Read-only · candlestick bible context + higher timeframe map + catalyst vetoes",
    )


def render_daily_edge(model: dict[str, Any]) -> str:
    data = model.get("daily_edge") if isinstance(model.get("daily_edge"), dict) else {}
    if not data:
        return section(
            "Daily Edge Orchestrator",
            "<p style='color:var(--muted);padding:12px'>No report - run scripts/daily_edge_orchestrator.py first.</p>",
            "Morning targets, runners, no-trade explanations, exit capture, and scanner leadership",
        )
    summary = data.get("summary") if isinstance(data.get("summary"), dict) else {}
    blockers = data.get("global_blockers") if isinstance(data.get("global_blockers"), list) else []
    targets = data.get("morning_targets") if isinstance(data.get("morning_targets"), list) else []
    runners = data.get("runner_detection") if isinstance(data.get("runner_detection"), list) else []
    no_trades = data.get("no_trade_explanations") if isinstance(data.get("no_trade_explanations"), list) else []
    exits = data.get("exit_accountability") if isinstance(data.get("exit_accountability"), list) else []
    leaders = data.get("scanner_leadership") if isinstance(data.get("scanner_leadership"), list) else []

    target_rows = []
    for row in targets[:8]:
        if not isinstance(row, dict):
            continue
        target_rows.append(
            "<tr>"
            f"<td>{esc(row.get('symbol'))}</td>"
            f"<td><span class='{cls_for_health(row.get('lane'))}'>{esc(row.get('lane'))}</span></td>"
            f"<td>{esc(row.get('score'))}</td>"
            f"<td>{esc(', '.join(map(str, row.get('allowed_playbooks') or [])))}</td>"
            f"<td>{esc(', '.join(map(str, row.get('reasons') or [])))}</td>"
            f"<td>{esc(', '.join(map(str, row.get('blockers') or [])))}</td>"
            "</tr>"
        )

    runner_rows = []
    for row in runners[:8]:
        if not isinstance(row, dict):
            continue
        runner_rows.append(
            "<tr>"
            f"<td>{esc(row.get('symbol'))}</td>"
            f"<td>{esc(row.get('state'))}</td>"
            f"<td>{pct(row.get('best_return_pct'))}</td>"
            f"<td>{esc(row.get('pattern'))}</td>"
            "</tr>"
        )

    review_rows = []
    for row in (no_trades[:5] + exits[:5]):
        if not isinstance(row, dict):
            continue
        label = row.get("primary_reason") or row.get("verdict") or "review"
        detail = row.get("why") or row.get("lesson") or ""
        review_rows.append(
            "<tr>"
            f"<td>{esc(row.get('symbol'))}</td>"
            f"<td>{esc(label)}</td>"
            f"<td>{esc(detail)}</td>"
            "</tr>"
        )

    leader_rows = []
    for row in leaders[:8]:
        if not isinstance(row, dict):
            continue
        leader_rows.append(
            "<tr>"
            f"<td>{esc(row.get('name'))}</td>"
            f"<td>{esc(row.get('recommended_use'))}</td>"
            f"<td>{esc(row.get('score'))}</td>"
            f"<td>{esc(', '.join(map(str, row.get('blockers') or [])))}</td>"
            "</tr>"
        )

    return section(
        "Daily Edge Orchestrator",
        f"""
        <div class="stat-grid compact">
          <div class="stat"><span>Precision Watch</span><strong>{safe_int(summary.get("precision_watch_count"))}</strong><small>best morning target lane</small></div>
          <div class="stat"><span>Runners</span><strong>{safe_int(summary.get("runner_count"))}</strong><small>active shadow runner detection</small></div>
          <div class="stat"><span>No-Trade Reasons</span><strong>{safe_int(summary.get("no_trade_explanation_count"))}</strong><small>skip accountability</small></div>
          <div class="stat"><span>Poor Capture</span><strong>{safe_int(summary.get("poor_capture_count"))}</strong><small>exit accountability</small></div>
          <div class="stat"><span>Flip Focus</span><strong>{esc(summary.get("flip_execution_symbol") or "SPY")}</strong><small>promoted execution benchmark</small></div>
          <div class="stat"><span>Flip Win Rate</span><strong>{pct(summary.get("flip_rolling_win_rate"), scale=True)}</strong><small>post-hardening closed trades</small></div>
          <div class="stat"><span>Flip Net P&amp;L</span><strong>{money(summary.get("flip_rolling_net_pnl"))}</strong><small>post-hardening paper evidence</small></div>
          <div class="stat"><span>Global Blockers</span><strong>{safe_int(len(blockers))}</strong><small>{esc(', '.join(map(str, blockers)) or 'none')}</small></div>
        </div>
        <div class="split">
          <div class="table-wrap"><table><thead><tr><th>Symbol</th><th>Lane</th><th>Score</th><th>Playbooks</th><th>Reasons</th><th>Blockers</th></tr></thead><tbody>{''.join(target_rows) or '<tr><td colspan="6">No morning targets.</td></tr>'}</tbody></table></div>
          <div class="table-wrap"><table><thead><tr><th>Symbol</th><th>Runner State</th><th>Best Return</th><th>Pattern</th></tr></thead><tbody>{''.join(runner_rows) or '<tr><td colspan="4">No active runners.</td></tr>'}</tbody></table></div>
        </div>
        <div class="split" style="margin-top:12px">
          <div class="table-wrap"><table><thead><tr><th>Symbol</th><th>Review</th><th>Explanation</th></tr></thead><tbody>{''.join(review_rows) or '<tr><td colspan="3">No no-trade or exit reviews.</td></tr>'}</tbody></table></div>
          <div class="table-wrap"><table><thead><tr><th>Scanner</th><th>Use</th><th>Score</th><th>Blockers</th></tr></thead><tbody>{''.join(leader_rows) or '<tr><td colspan="4">No scanner leadership rows.</td></tr>'}</tbody></table></div>
        </div>
        """,
        "One daily view: target -> runner -> skip/trade -> exit quality -> scanner trust",
    )


def render_kronos_forecast(model: dict[str, Any]) -> str:
    data = model.get("kronos_forecast") if isinstance(model.get("kronos_forecast"), dict) else {}
    if not data:
        return section(
            "Kronos Market Forecaster",
            "<p style='color:var(--muted);padding:12px'>No report - run scripts/kronos_market_forecaster.py first.</p>",
            "Foundation-model K-line forecast context; shadow only",
        )
    summary = data.get("summary") if isinstance(data.get("summary"), dict) else {}
    items = data.get("items") if isinstance(data.get("items"), list) else []
    rows = []
    for row in items[:10]:
        if not isinstance(row, dict):
            continue
        status = str(row.get("status") or "unknown")
        direction = str(row.get("forecast_direction") or "unknown")
        rows.append(
            "<tr>"
            f"<td>{esc(row.get('symbol'))}</td>"
            f"<td><span class='{cls_for_health(status)}'>{esc(status)}</span></td>"
            f"<td><span class='{cls_for_health(direction)}'>{esc(direction)}</span></td>"
            f"<td>{pct(row.get('forecast_return_pct'))}</td>"
            f"<td>{pct(row.get('max_drawdown_pct'))}</td>"
            f"<td>{esc(row.get('recommended_use'))}</td>"
            "</tr>"
        )
    return section(
        "Kronos Market Forecaster",
        f"""
        <div class="stat-grid compact">
          <div class="stat"><span>OK</span><strong>{safe_int(summary.get("ok"))}</strong><small>forecast rows</small></div>
          <div class="stat"><span>Bullish</span><strong>{safe_int(summary.get("bullish"))}</strong><small>Kronos context</small></div>
          <div class="stat"><span>Bearish</span><strong>{safe_int(summary.get("bearish"))}</strong><small>Kronos context</small></div>
          <div class="stat"><span>Unavailable</span><strong>{safe_int(summary.get("unavailable"))}</strong><small>setup or inference required</small></div>
        </div>
        <div class="table-wrap">
          <table><thead><tr><th>Symbol</th><th>Status</th><th>Direction</th><th>Forecast Return</th><th>Drawdown</th><th>Use</th></tr></thead><tbody>{''.join(rows) or '<tr><td colspan="6">No Kronos forecast rows.</td></tr>'}</tbody></table>
        </div>
        """,
        "Read-only · optional Kronos inference · no execution authority",
    )


def render_shadow_consensus(model: dict[str, Any]) -> str:
    consensus = model["shadow_consensus"] if isinstance(model.get("shadow_consensus"), dict) else {}
    summary = consensus.get("summary") if isinstance(consensus.get("summary"), dict) else {}
    decisions = consensus.get("decisions") if isinstance(consensus.get("decisions"), list) else []
    rows = []
    for row in decisions[:12]:
        blockers = row.get("blockers") if isinstance(row.get("blockers"), list) else []
        reasons = row.get("reasons") if isinstance(row.get("reasons"), list) else []
        recommendation = str(row.get("recommendation") or "")
        tone = {
            "approve": "good",
            "size_down": "warn",
            "needs_review": "warn",
            "stand_aside": "bad",
        }.get(recommendation, "")
        rows.append(
            "<tr>"
            f"<td><strong>{esc(row.get('symbol'))}</strong><small>{esc(row.get('market_direction'))}</small></td>"
            f"<td class=\"{tone}\">{esc(recommendation)}</td>"
            f"<td>{safe_int(row.get('consensus_score'))}</td>"
            f"<td>{esc(row.get('options_playbook'))}</td>"
            f"<td>{esc('; '.join(str(reason) for reason in reasons[:2]))}</td>"
            f"<td>{esc('; '.join(str(blocker) for blocker in blockers[:3]))}</td>"
            "</tr>"
        )
    return section(
        "Shadow Consensus Gate",
        f"""
        <div class="stat-grid compact">
          {stat_card("Approve", str(safe_int(summary.get("approve"))), "advice only", "warn" if safe_int(summary.get("approve")) else "")}
          {stat_card("Size Down", str(safe_int(summary.get("size_down"))), "edge exists, not promoted", "warn" if safe_int(summary.get("size_down")) else "")}
          {stat_card("Review", str(safe_int(summary.get("needs_review"))), "needs human check", "warn" if safe_int(summary.get("needs_review")) else "")}
          {stat_card("Stand Aside", str(safe_int(summary.get("stand_aside"))), "blocked or weak", "bad" if safe_int(summary.get("stand_aside")) else "good")}
        </div>
        <div class="table-wrap">
          <table><thead><tr><th>Symbol</th><th>Advice</th><th>Score</th><th>Playbook</th><th>Reasons</th><th>Blockers</th></tr></thead><tbody>{''.join(rows) or '<tr><td colspan="6">No consensus report yet.</td></tr>'}</tbody></table>
        </div>
        """,
        "Read-only advisor · Does not submit orders · Kill switch and execution guard stay authoritative",
    )


def render_scanner_evidence(model: dict[str, Any]) -> str:
    data = model.get('scanner_evidence') or {}
    summary = data.get('summary') or {}
    reference = model.get('feed_reference') or {}
    counts = reference.get('status_by_feed') or {}
    iex = (counts.get('iex') or {}).get('evaluated')
    sip = (counts.get('sip') or {}).get('evaluated')
    rows = ''.join(f"<tr><td>{esc(name)}</td><td>{esc(row.get('status'))}</td><td>{esc(row.get('capture_timing') or 'unknown')}</td><td>{esc(row.get('source_generated_at') or 'unknown')}</td></tr>" for name, row in (data.get('source_provenance') or {}).items())
    return section('Scanner Evidence Collection',
        f"<p>Snapshot {esc(data.get('snapshot_id') or 'missing')} · captured {esc(data.get('captured_at') or 'unknown')}</p>"
        f"<p>Ranked candidates: {safe_int(summary.get('ranked_candidates'))}; accepted: {safe_int(summary.get('accepted_decisions'))}; rejected: {safe_int(summary.get('rejected_decisions'))}; final quote checks: {safe_int(summary.get('quote_gate_checks'))}.</p>"
        f"<p>Historical reference session {esc(reference.get('session_date') or 'missing')}: evaluated unique alerts IEX={esc(iex) if iex is not None else 'missing'}, SIP={esc(sip) if sip is not None else 'missing'}. Not live SIP entitlement, actual fills, or promotion evidence.</p>"
        f"<div class='table-wrap'><table><thead><tr><th>Existing source</th><th>Status</th><th>Capture timing</th><th>Source time</th></tr></thead><tbody>{rows}</tbody></table></div><p>All thresholds remain human-reviewed. Late snapshots cannot establish point-in-time information availability.</p>")


def _dashboard_timestamp(value: Any) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(str(value or "").replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None:
        return None
    return parsed.astimezone(timezone.utc)


def _databento_budget() -> float | None:
    raw = os.getenv("DATABENTO_DAILY_USD_BUDGET", "").strip()
    if not raw:
        env_path = ROOT / "agent" / ".env"
        try:
            for line in env_path.read_text(encoding="utf-8", errors="ignore").splitlines():
                if line.startswith("DATABENTO_DAILY_USD_BUDGET="):
                    raw = line.split("=", 1)[1].strip()
                    break
        except OSError:
            pass
    try:
        value = float(raw or "5.00")
    except ValueError:
        return None
    return value if math.isfinite(value) and value >= 0 else None


def _current_premarket_theses(report: dict[str, Any], now: datetime) -> list[dict[str, Any]]:
    current: list[dict[str, Any]] = []
    now_et = now.astimezone(ET)
    for thesis in report.get("theses") or []:
        if not isinstance(thesis, dict):
            continue
        expiry = _dashboard_timestamp(thesis.get("expires_at"))
        if expiry is None and thesis.get("expires_at_et"):
            generated = _dashboard_timestamp(
                thesis.get("generated_at") or thesis.get("as_of") or report.get("generated_at")
            )
            try:
                hour, minute = (int(value) for value in str(thesis["expires_at_et"]).split(":", 1))
                expiry_day = (generated or now).astimezone(ET).date()
                expiry = datetime.combine(expiry_day, datetime.min.time(), ET).replace(
                    hour=hour, minute=minute
                ).astimezone(timezone.utc)
            except (TypeError, ValueError):
                expiry = None
        if expiry is not None and now.astimezone(timezone.utc) < expiry:
            current.append(thesis)
    return current


def nbbo_dashboard_state(model: dict[str, Any], *, now: datetime | None = None) -> dict[str, Any]:
    """Reduce audited NBBO artifacts to display-safe dashboard facts."""
    now = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    ledger = [row for row in (model.get("databento_call_ledger") or []) if isinstance(row, dict)]
    today_rows = []
    for row in ledger:
        stamp = _dashboard_timestamp(
            row.get("timestamp") or row.get("requested_at") or row.get("generated_at")
        )
        if stamp is not None and stamp.astimezone(ET).date() == now.astimezone(ET).date():
            today_rows.append((stamp, row))
    today_rows.sort(key=lambda pair: pair[0])
    latest_ledger = today_rows[-1][1] if today_rows else {}
    known_costs = [
        safe_float(row.get("cost_usd"))
        for _, row in today_rows
        if row.get("cost_usd") not in (None, "")
    ]
    budget = _databento_budget()
    cost = round(sum(known_costs), 6) if known_costs else None
    remaining = round(max(0.0, budget - cost), 6) if budget is not None and cost is not None else None

    confluence = model.get("institutional_confluence")
    confluence = confluence if isinstance(confluence, dict) else {}
    flows: list[dict[str, Any]] = []
    unusual: list[dict[str, Any]] = []
    for card in confluence.get("cards") or []:
        if not isinstance(card, dict):
            continue
        for source in card.get("sources") or []:
            if not isinstance(source, dict) or source.get("name") != "nbbo_options_flow":
                continue
            flows.append({
                "symbol": card.get("symbol"),
                "direction": source.get("direction") or (source.get("facts") or {}).get("directional_flow_bias"),
                "status": source.get("status") or "missing",
                "available": source.get("available") is True,
                "fresh": source.get("fresh") is True,
                "age_seconds": source.get("age_seconds"),
                "observed_at": source.get("observed_at"),
            })
            facts = source.get("facts") if isinstance(source.get("facts"), dict) else {}
            for item in facts.get("unusual_prints") or []:
                if isinstance(item, dict):
                    unusual.append({**item, "underlying": item.get("underlying") or card.get("symbol")})

    premarket = model.get("premarket_thesis")
    premarket = premarket if isinstance(premarket, dict) else {}
    theses = _current_premarket_theses(premarket, now)
    for thesis in theses:
        evidence = thesis.get("evidence") if isinstance(thesis.get("evidence"), dict) else {}
        for item in thesis.get("unusual_prints") or evidence.get("unusual_prints") or []:
            if isinstance(item, dict):
                unusual.append({**item, "underlying": item.get("underlying") or thesis.get("symbol")})

    latest_status = str(latest_ledger.get("status") or "").lower()
    if latest_status in {"success", "cached"}:
        latest_status = "ok"
    if latest_status == "cache_hit":
        latest_status = "ok"
    if not latest_status and any(flow["available"] and flow["fresh"] for flow in flows):
        latest_status = "ok"
    if not latest_status:
        candidate_status = str(premarket.get("nbbo_status") or premarket.get("feed_status") or "").lower()
        latest_status = candidate_status if candidate_status in {
            "ok", "not_configured", "budget_exceeded", "timeout", "missing"
        } or candidate_status.startswith("http_") else "missing"

    return {
        "status": latest_status,
        "cost_usd": cost,
        "budget_usd": budget,
        "remaining_usd": remaining,
        "ledger_calls_today": len(today_rows),
        "flows": flows,
        "unusual_prints": unusual[-20:][::-1],
        "theses": theses,
    }


def render_nbbo_options_flow(model: dict[str, Any], *, now: datetime | None = None) -> str:
    state = nbbo_dashboard_state(model, now=now)
    status = str(state["status"] or "missing")
    ok = status == "ok"
    flow_rows = []
    if ok:
        for row in state["flows"]:
            age = row.get("age_seconds")
            freshness = "fresh" if row.get("fresh") and isinstance(age, (int, float)) and age <= 60 else "stale"
            flow_rows.append(
                f"<tr><td><strong>{esc(row.get('symbol') or 'missing')}</strong></td>"
                f"<td>{esc(row.get('direction') or 'NEUTRAL')}</td><td>{esc(row.get('status'))}</td>"
                f"<td class='{'good' if freshness == 'fresh' else 'bad'}'>{esc(freshness)}</td>"
                f"<td>{esc(round(float(age), 1)) if isinstance(age, (int, float)) else 'missing'}</td></tr>"
            )
    flow_body = "".join(flow_rows) or (
        f"<tr><td colspan='5'>NBBO status: {esc(status)}. No flow bias is inferred.</td></tr>"
    )

    print_rows = []
    if ok:
        for item in state["unusual_prints"]:
            premium = item.get("premium") or item.get("premium_usd")
            print_rows.append(
                f"<tr><td>{esc(item.get('observed_at') or item.get('event_at') or 'missing')}</td>"
                f"<td>{esc(item.get('underlying') or 'missing')}</td>"
                f"<td>{esc(item.get('symbol') or item.get('contract') or 'missing')}</td>"
                f"<td>{esc(item.get('side') or item.get('right') or 'unknown')}</td>"
                f"<td>{esc(item.get('strike') if item.get('strike') is not None else 'missing')}</td>"
                f"<td>{esc(item.get('size') if item.get('size') is not None else 'missing')}</td>"
                f"<td>{money(premium)}</td></tr>"
            )
    print_body = "".join(print_rows) or (
        f"<tr><td colspan='7'>{'No unusual prints in the current audited evidence.' if ok else 'Unavailable while NBBO status is ' + esc(status) + '.'}</td></tr>"
    )

    thesis_rows = []
    if ok:
        for thesis in state["theses"]:
            numeric = thesis.get("evidence_numeric") if isinstance(thesis.get("evidence_numeric"), dict) else {}
            thesis_rows.append(
                f"<tr><td><strong>{esc(thesis.get('symbol'))}</strong></td>"
                f"<td>{esc(thesis.get('direction') or 'NO_BIAS')}</td><td>{esc(thesis.get('conviction') or 'low')}</td>"
                f"<td>{esc(thesis.get('evidence_summary') or 'numeric evidence recorded')}</td>"
                f"<td>{esc(numeric.get('put_call_dollar_premium_ratio') if numeric.get('put_call_dollar_premium_ratio') is not None else 'missing')}</td>"
                f"<td>{esc(numeric.get('skew_5pct') if numeric.get('skew_5pct') is not None else 'missing')}</td></tr>"
            )
    thesis_body = "".join(thesis_rows) or (
        f"<tr><td colspan='6'>{'No unexpired premarket thesis card.' if ok else 'No thesis numbers displayed because NBBO is ' + esc(status) + '.'}</td></tr>"
    )

    cost_text = money(state["cost_usd"]) if state["cost_usd"] is not None else "missing"
    remaining_text = money(state["remaining_usd"]) if state["remaining_usd"] is not None else "missing"
    budget_text = money(state["budget_usd"]) if state["budget_usd"] is not None else "missing"
    return section(
        "NBBO Options Flow",
        f"""
        <div class='stat-grid compact'>
          {stat_card('API status', status.upper(), 'missing is never converted to OHLCV', 'good' if ok else 'bad')}
          {stat_card("Today's cost", cost_text, f"{safe_int(state['ledger_calls_today'])} audited calls", '')}
          {stat_card('Daily budget', budget_text, 'hard cap from DATABENTO_DAILY_USD_BUDGET', '')}
          {stat_card('Remaining', remaining_text, 'missing when ledger cost is unknown', 'warn' if state['remaining_usd'] is None else '')}
          {stat_card('Fresh limit', '60s', 'older quotes are stale', 'good')}
          {stat_card('Authority', 'CRITIC ONLY', 'may veto; cannot approve or execute', 'good')}
        </div>
        <h3>Latest per-symbol flow</h3>
        <div class='table-wrap'><table><thead><tr><th>Symbol</th><th>Bias</th><th>Status</th><th>Freshness</th><th>Age seconds</th></tr></thead><tbody>{flow_body}</tbody></table></div>
        <h3>Unusual prints · last 20 audited</h3>
        <div class='table-wrap'><table><thead><tr><th>Observed</th><th>Underlying</th><th>Contract</th><th>Side</th><th>Strike</th><th>Size</th><th>Premium</th></tr></thead><tbody>{print_body}</tbody></table></div>
        <h3>Unexpired premarket thesis</h3>
        <div class='table-wrap'><table><thead><tr><th>Symbol</th><th>Direction</th><th>Conviction</th><th>Evidence</th><th>Put/call $</th><th>5% skew</th></tr></thead><tbody>{thesis_body}</tbody></table></div>
        """,
        "Databento OPRA evidence · display-safe audit fields only · no raw provider payloads · no order authority",
    )


def render_latency_budget(model: dict[str, Any]) -> str:
    data = model.get("latency_budget") or {}
    gap = data.get("historical_gap") if isinstance(data.get("historical_gap"), dict) else {}
    proof = data.get("paired_pipeline_proof") if isinstance(data.get("paired_pipeline_proof"), dict) else {}
    rows = []
    for source, stages in (data.get("by_source") or {}).items():
        for stage, values in stages.items():
            cells = [source, stage, values.get("count"), values.get("p50"), values.get("p90"), values.get("p99"), values.get("target"), values.get("status")]
            rows.append("<tr>" + "".join(f"<td>{esc(value) if value is not None else '—'}</td>" for value in cells) + "</tr>")
    body = ''.join(rows) or '<tr><td colspan="8">Exact delivery receipts unavailable.</td></tr>'
    ci = proof.get('ci95_seconds') or [None, None]
    cards = (stat_card('Pre-instrumentation', str(safe_int(gap.get('pre_instrumentation_rows'))), 'Discord IDs absent; no timestamps imputed', 'warn')
             + stat_card('Paired samples', str(safe_int(proof.get('paired_samples'))), f"minimum {safe_int(proof.get('minimum_paired_samples'))}", '')
             + stat_card('Bootstrap verdict', str(proof.get('status') or 'missing'), f"95% CI {ci[0]} to {ci[1]} sec", 'good' if proof.get('status') == 'improvement_supported' else 'warn'))
    return section("Latency Budget", f"<div class='stat-grid compact'>{cards}</div><p>{esc(data.get('status') or 'missing')} · last {safe_int(data.get('sessions_reviewed'))} observed receipt dates. Seconds; Discord-assigned message timestamp, not user read time. Missing is not zero.</p><div class='table-wrap'><table><thead><tr><th>Source</th><th>Stage</th><th>N</th><th>p50</th><th>p90</th><th>p99</th><th>Target p90</th><th>Status</th></tr></thead><tbody>{body}</tbody></table></div>")


def render_statistical_governance(model: dict[str, Any]) -> str:
    data = model.get("statistical_governance") if isinstance(model.get("statistical_governance"), dict) else {}
    signals = data.get("signals") if isinstance(data.get("signals"), list) else []
    proof = data.get("latency_proof") if isinstance(data.get("latency_proof"), dict) else {}
    rows = []
    for row in signals:
        if not isinstance(row, dict):
            continue
        confidence = row.get("confidence_intervals") if isinstance(row.get("confidence_intervals"), dict) else {}
        def metric(name: str, fallback: Any) -> str:
            item = confidence.get(name) if isinstance(confidence.get(name), dict) else {}
            if item.get("ci_low") is None:
                return f"{fallback if fallback is not None else '—'} (n={safe_int(item.get('n', row.get('n_outcomes')))}; insufficient)"
            return f"{item.get('point'):.4f} [{item.get('ci_low'):.4f}, {item.get('ci_high'):.4f}]"
        cells = [row.get("signal_id"), row.get("family_key"), row.get("status"),
                 row.get("n", row.get("n_outcomes")), row.get("t", row.get("n_trials")),
                 metric("sharpe", row.get("sharpe")), row.get("deflated_sharpe"),
                 row.get("psr"), row.get("pbo"), row.get("reason")]
        rows.append("<tr>" + "".join(f"<td>{esc(value) if value is not None else '—'}</td>" for value in cells) + "</tr>")
    body = "".join(rows) or '<tr><td colspan="10">No statistical gate history. Promotion remains blocked.</td></tr>'
    result = proof.get("result") if isinstance(proof.get("result"), dict) else {}
    ci = [result.get("diff_ci_low"), result.get("diff_ci_high")]
    cards = (
        stat_card("Gate status", str(data.get("status") or "missing"), "human review required", "warn")
        + stat_card("Signals evaluated", str(len(signals)), "latest persisted result per signal", "")
        + stat_card("Latency proof", str(proof.get("status") or "missing"),
                    f"paired n={safe_int(proof.get('paired_samples'))}; 95% CI {ci[0]} to {ci[1]} ms", "good" if proof.get("status") == "improvement_supported" else "warn")
    )
    return section("Statistical Promotion Gate", f"<div class='stat-grid compact'>{cards}</div><p>DSR/PSR/PBO are nomination evidence only. Family assignments and every promotion decision require human review. Missing evidence fails closed; no baseline is never inferred.</p><div class='table-wrap'><table><thead><tr><th>Signal</th><th>Family</th><th>Status</th><th>N</th><th>Trials</th><th>Sharpe CI</th><th>DSR</th><th>PSR</th><th>PBO</th><th>Reason</th></tr></thead><tbody>{body}</tbody></table></div>", "Read-only · no automatic promotion, demotion, parameter change, or order authority")


def render_execution_readiness(model: dict[str, Any]) -> str:
    data = model.get("execution_readiness") if isinstance(model.get("execution_readiness"), dict) else {}
    criteria = data.get("criteria") if isinstance(data.get("criteria"), list) else []
    rows = "".join(
        f"<tr><td><strong>{esc(row.get('name'))}</strong></td><td class='{('good' if row.get('status') == 'PASS' else 'warn' if row.get('status') == 'PENDING' else 'bad')}'>{esc(row.get('status'))}</td><td>{safe_int(row.get('observed')) if row.get('observed') is not None else '—'} / {safe_int(row.get('required')) if row.get('required') is not None else '—'}</td><td>{safe_int(row.get('days_remaining'))}</td></tr>"
        for row in criteria if isinstance(row, dict)
    )
    rows_html = rows or '<tr><td colspan="4">No readiness report yet.</td></tr>'
    return section(
        "Live-Execution Readiness · Draft",
        f"<div class='stat-grid compact'>{stat_card('Overall', str(data.get('status') or 'PENDING'), 'human promotion only', 'good' if data.get('status') == 'PASS' else 'bad')}{stat_card('Automatic promotion', 'OFF', 'scorecard cannot change configuration', 'good')}{stat_card('Order authority', 'NONE', 'shadow reports only', 'good')}</div><div class='table-wrap'><table><thead><tr><th>Criterion</th><th>Status</th><th>Observed / Required</th><th>Remaining</th></tr></thead><tbody>{rows_html}</tbody></table></div>",
        "Passing evidence still requires explicit human review and a strategy-specific configuration change; this panel cannot enable execution.",
    )


def render_governed_shadow_decision(model: dict[str, Any]) -> str:
    """Show every decision made by the deterministic, no-order policy."""
    data = model.get("governed_shadow") if isinstance(model.get("governed_shadow"), dict) else {}
    delivery = model.get("governed_alert") if isinstance(model.get("governed_alert"), dict) else {}
    lifecycle = model.get("governed_lifecycle") if isinstance(model.get("governed_lifecycle"), dict) else {}
    outcomes = model.get("governed_outcomes") if isinstance(model.get("governed_outcomes"), dict) else {}
    chart_review = model.get("discord_chart_review") if isinstance(model.get("discord_chart_review"), dict) else {}
    chart_summary = chart_review.get("summary") if isinstance(chart_review.get("summary"), dict) else {}
    chart_status = chart_summary.get("status_counts") if isinstance(chart_summary.get("status_counts"), dict) else {}
    rules = model.get("governed_rules") if isinstance(model.get("governed_rules"), dict) else {}
    confluence = model.get("institutional_confluence") if isinstance(model.get("institutional_confluence"), dict) else {}
    confluence_summary = confluence.get("summary") if isinstance(confluence.get("summary"), dict) else {}
    confluence_cards = confluence.get("cards") if isinstance(confluence.get("cards"), list) else []
    summary = data.get("summary") if isinstance(data.get("summary"), dict) else {}
    decisions = data.get("decisions") if isinstance(data.get("decisions"), list) else []
    rows: list[str] = []
    for row in decisions[:16]:
        candidate = row.get("candidate") if isinstance(row.get("candidate"), dict) else {}
        decision = str(row.get("decision") or "unknown")
        tone = "good" if decision == "shadow_accepted" else "bad" if decision == "shadow_rejected" else "warn"
        blockers = row.get("blockers") if isinstance(row.get("blockers"), list) else []
        evidence = row.get("evidence_cards") if isinstance(row.get("evidence_cards"), list) else []
        rows.append(
            "<tr>"
            f"<td><strong>{esc(candidate.get('symbol'))}</strong><small>{esc(candidate.get('setup'))}</small></td>"
            f"<td>{esc(candidate.get('direction'))}</td>"
            f"<td>{money(candidate.get('trigger'))}<small>stop {money(candidate.get('stop'))} · target {money(candidate.get('target'))}</small></td>"
            f"<td class='{tone}'>{esc(decision)}</td>"
            f"<td>{esc('; '.join(str(item) for item in blockers[:3])) or '—'}</td>"
            f"<td>{len(evidence)} hashed cards</td>"
            "</tr>"
        )
    reasons = summary.get("rejected_by_reason") if isinstance(summary.get("rejected_by_reason"), dict) else {}
    reason_text = ", ".join(f"{key}: {safe_int(value)}" for key, value in sorted(reasons.items())) or "none"
    confluence_rows: list[str] = []
    for card in confluence_cards[:12]:
        if not isinstance(card, dict):
            continue
        repeat = card.get("repeat_confirmation") if isinstance(card.get("repeat_confirmation"), dict) else {}
        sources = card.get("sources") if isinstance(card.get("sources"), list) else []
        source_text = ", ".join(
            f"{source.get('name')}={'fresh' if source.get('available') and source.get('fresh') else source.get('reason') or source.get('status') or 'unavailable'}"
            for source in sources if isinstance(source, dict)
        )
        recommendation = str(card.get("recommendation") or "missing")
        tone = "good" if recommendation == "confluence_observed" else "bad" if recommendation == "contradiction_observed" else "warn"
        confluence_rows.append(
            "<tr>"
            f"<td><strong>{esc(card.get('symbol'))}</strong><small>{esc(card.get('direction'))}</small></td>"
            f"<td class='{tone}'>{esc(recommendation)}</td>"
            f"<td>{safe_int(card.get('independent_sources_available'))} / {safe_int(card.get('independent_sources_required_for_confluence'))}</td>"
            f"<td>{safe_int(repeat.get('count'))}<small>{esc(repeat.get('span_minutes'))} min · {'qualified' if repeat.get('qualifies') else 'not qualified'}</small></td>"
            f"<td class='muted small'>{esc(source_text)}</td>"
            "</tr>"
        )
    return section(
        "Governed Shadow Decision Gate",
        f"""
        <div class="stat-grid compact">
          {stat_card("Confirmed", str(safe_int(summary.get("confirmed_candidates"))), "scanner candidates", "")}
          {stat_card("Simulated", str(safe_int(summary.get("shadow_accepted"))), "shadow ledger only", "good" if safe_int(summary.get("shadow_accepted")) else "")}
          {stat_card("Rejected", str(safe_int(summary.get("shadow_rejected"))), "still visible and replayed", "warn" if safe_int(summary.get("shadow_rejected")) else "")}
          {stat_card("New ledger rows", str(safe_int(summary.get("new_ledger_events"))), "append-only evidence", "")}
        </div>
        <div class="stat-grid compact">
          {stat_card("Alerts delivered", str(safe_int(delivery.get("alerts_sent"))), f"{safe_int(delivery.get('pending_delivery'))} pending · {safe_int(delivery.get('dashboard_only'))} dashboard-only", "bad" if safe_int(delivery.get("delivery_failures")) else "good")}
          {stat_card("Sim lifecycles", str(safe_int(lifecycle.get("accepted_for_simulation"))), "accepted decisions only", "")}
          {stat_card("Outcomes", str(safe_int(outcomes.get("total_reconciled"))), f"{safe_int(outcomes.get('still_pending_or_missing_bars'))} pending · {safe_int(outcomes.get('after_session_ineligible'))} after-session excluded", "warn" if safe_int(outcomes.get("still_pending_or_missing_bars")) or safe_int(outcomes.get("after_session_ineligible")) else "")}
          {stat_card("Rule nominations", str(safe_int(rules.get("review_nominations"))), f"{safe_int(rules.get('rule_families'))} families evaluated", "")}
        </div>
        <h3 style="margin-top:18px">Post-Discord 1m Chart Review</h3>
        <div class="stat-grid compact">
          {stat_card("Delivered plans", str(safe_int(chart_summary.get("delivered_trade_alerts"))), f"{safe_int(chart_summary.get('unique_trade_candidates'))} unique", "")}
          {stat_card("Evaluated", str(safe_int(chart_summary.get("evaluated"))), "first full minute after delivery", "")}
          {stat_card("Positive", pct(chart_summary.get("positive_pct")), "underlying R proxy", "good" if safe_float(chart_summary.get("positive_pct")) >= 50 else "warn")}
          {stat_card("Median R", f"{safe_float(chart_summary.get('median_r')):+.2f}R", "after actual Discord timestamp", "good" if safe_float(chart_summary.get("median_r")) > 0 else "bad")}
          {stat_card("Invalid before entry", str(safe_int(chart_status.get("invalidated_before_entry"))), "late plans rejected", "warn" if safe_int(chart_status.get("invalidated_before_entry")) else "good")}
          {stat_card("Duplicates", str(safe_int(chart_summary.get("duplicate_trade_alerts"))), "same setup sent more than once", "warn" if safe_int(chart_summary.get("duplicate_trade_alerts")) else "good")}
        </div>
        <p class="muted small" style="padding:4px 0 10px">Completed 1m underlying bars beginning after Discord delivery; gap-through entries are repriced and stop-before-entry plans are rejected. This is not option-contract P&amp;L.</p>
        <p class="muted small" style="padding:4px 0 10px">Rejection reasons: {esc(reason_text)}</p>
        <div class="table-wrap"><table><thead><tr><th>Symbol / Setup</th><th>Side</th><th>Levels</th><th>Decision</th><th>Blockers</th><th>Evidence</th></tr></thead><tbody>{''.join(rows) or '<tr><td colspan="6">No completed-bar candidates recorded yet.</td></tr>'}</tbody></table></div>
        <h3 style="margin-top:18px">Institutional Confluence · Fail-Honest Source Coverage</h3>
        <div class="stat-grid compact">
          {stat_card("Confluence", str(safe_int(confluence_summary.get('confluence_observed'))), "2+ fresh independent sources", "good" if safe_int(confluence_summary.get('confluence_observed')) else "")}
          {stat_card("Insufficient", str(safe_int(confluence_summary.get('insufficient_independent_evidence'))), "alerts remain visible", "warn" if safe_int(confluence_summary.get('insufficient_independent_evidence')) else "")}
          {stat_card("Contradictions", str(safe_int(confluence_summary.get('contradictions'))), "critic evidence only", "bad" if safe_int(confluence_summary.get('contradictions')) else "good")}
          {stat_card("Repeat confirmed", str(safe_int(confluence_summary.get('repeat_confirmed'))), "3 bars over 5+ minutes", "")}
        </div>
        <div class="table-wrap"><table><thead><tr><th>Symbol</th><th>Assessment</th><th>Independent</th><th>Repeat bars</th><th>Source status</th></tr></thead><tbody>{''.join(confluence_rows) or '<tr><td colspan="5">No confluence evidence report yet.</td></tr>'}</tbody></table></div>
        """,
        "Deterministic evidence policy · all candidates logged · simulated positions only · no broker or order authority",
    )


def render_options_heatmap(model: dict[str, Any]) -> str:
    data = model.get("options_heatmap") if isinstance(model.get("options_heatmap"), dict) else {}
    if not data:
        return section("Options Liquidation Heat Map", "<p style='color:var(--muted);padding:12px'>No report - run scripts/options_liquidation_heatmap.py first.</p>")
    results = data.get("results") if isinstance(data.get("results"), list) else []
    ok = [row for row in results if isinstance(row, dict) and row.get("status") == "ok"]
    cards = (
        stat_card("Symbols", str(safe_int(data.get("ok_count"))), f"of {safe_int(data.get('symbol_count'))} mapped")
        + stat_card("Near Heat", str(safe_int(data.get("near_major_heat_zone_count"))), "spot near high OI/volume zone", "warn" if safe_int(data.get("near_major_heat_zone_count")) else "good")
        + stat_card("Execution", "OFF", "read-only context", "good" if not data.get("can_submit_orders") else "bad")
        + stat_card("Book Type", "PROXY", "public chain, not forced liquidation book", "warn")
    )
    rows = []
    for row in ok[:12]:
        above = row.get("nearest_heat_zone_above") if isinstance(row.get("nearest_heat_zone_above"), dict) else {}
        below = row.get("nearest_heat_zone_below") if isinstance(row.get("nearest_heat_zone_below"), dict) else {}
        top = row.get("top_heat_zones") if isinstance(row.get("top_heat_zones"), list) else []
        gex = row.get("gex_wall") if isinstance(row.get("gex_wall"), dict) else {}
        labels = row.get("condition_labels") if isinstance(row.get("condition_labels"), list) else []
        rows.append(
            "<tr>"
            f"<td><strong>{esc(row.get('symbol'))}</strong><small>spot {money(row.get('spot'))}</small></td>"
            f"<td class='{cls_for_health(row.get('front_heat_state'))}'>{esc(row.get('front_heat_state'))}</td>"
            f"<td>{pct(row.get('front_implied_move_pct'))}</td>"
            f"<td>{esc(row.get('front_put_call_open_interest_ratio'))}</td>"
            f"<td><strong>{esc(below.get('strike', ''))}</strong><small>{esc(below.get('bias', ''))}</small></td>"
            f"<td><strong>{esc(above.get('strike', ''))}</strong><small>{esc(above.get('bias', ''))}</small></td>"
            f"<td>{esc(gex.get('strike', ''))}<small>{esc(gex.get('bias', ''))}</small></td>"
            f"<td class='muted small'>{esc(', '.join(str(item) for item in labels[:4]))}</td>"
            f"<td class='muted small'>{esc(', '.join(str(zone.get('strike')) for zone in top[:3] if isinstance(zone, dict)))}</td>"
            "</tr>"
        )
    unavailable = [row for row in results if isinstance(row, dict) and row.get("status") != "ok"]
    unavailable_html = ""
    if unavailable:
        unavailable_html = "<p class='muted small' style='padding:10px 0 0'>Unavailable: " + esc(
            ", ".join(f"{row.get('symbol')}={row.get('reason')}" for row in unavailable[:5])
        ) + "</p>"
    body = (
        '<div class="grid-3" style="margin-bottom:16px">' + cards + "</div>"
        + '<div class="table-wrap"><table><thead><tr>'
        '<th>Symbol</th><th>Heat State</th><th>Front Move</th><th>P/C OI</th><th>Below Zone</th><th>Above Zone</th><th>GEX Wall</th><th>Labels</th><th>Top Heat</th>'
        '</tr></thead><tbody>'
        + ("".join(rows) or "<tr><td colspan='9'>No heat-map rows available.</td></tr>")
        + "</tbody></table></div>"
        + unavailable_html
    )
    return section("Options Liquidation Heat Map", body, "Public OI/volume heat zones + optional GEX wall - context only")


def render_options_quant_risk(model: dict[str, Any]) -> str:
    data = model.get("options_quant_risk") if isinstance(model.get("options_quant_risk"), dict) else {}
    if not data:
        return section("Options Quant Risk Budget", "<p style='color:var(--muted);padding:12px'>No report - run scripts/options_quant_risk_budget.py first.</p>")
    summary = data.get("summary") if isinstance(data.get("summary"), dict) else {}
    groups = data.get("groups") if isinstance(data.get("groups"), dict) else {}
    cards = (
        stat_card("Samples", str(safe_int(summary.get("closed_trade_samples"))), "closed option trades with P/L estimate")
        + stat_card("Global Cap", pct(summary.get("global_final_risk_cap_fraction"), scale=True), str(summary.get("global_action") or ""), cls_for_health(summary.get("global_action")))
        + stat_card("Execution", "OFF", "read-only allocator", "good" if not data.get("can_submit_orders") else "bad")
        + stat_card("Methods", "Kelly+MC", "GARCH / heatmap / Sortino throttle", "good")
    )
    rows = []
    for key in ("global", "strategy:put_spread", "strategy:call_spread", "strategy:iron_condor", "symbol:IWM", "symbol:SPY", "symbol:QQQ", "symbol:AAPL", "symbol:NVDA", "symbol:TSLA", "symbol:PLTR"):
        row = groups.get(key)
        if not isinstance(row, dict):
            continue
        mc = row.get("monte_carlo") if isinstance(row.get("monte_carlo"), dict) else {}
        rows.append(
            "<tr>"
            f"<td><strong>{esc(key)}</strong><small>{esc(row.get('action'))}</small></td>"
            f"<td>{safe_int(row.get('sample_size'))}</td>"
            f"<td>{pct(row.get('bayesian_win_rate'), scale=True)}</td>"
            f"<td>{pct(row.get('raw_kelly_fraction'), scale=True)}</td>"
            f"<td>{pct(row.get('final_risk_cap_fraction'), scale=True)}</td>"
            f"<td>{money(row.get('final_risk_cap_dollars'))}</td>"
            f"<td>{money(mc.get('p95_drawdown_dollars'))}</td>"
            f"<td>{esc(row.get('sortino_per_trade'))}</td>"
            f"<td>{esc(row.get('garch_multiplier'))} / {esc(row.get('heatmap_multiplier'))}</td>"
            "</tr>"
        )
    body = (
        '<div class="grid-3" style="margin-bottom:16px">' + cards + "</div>"
        + '<div class="table-wrap"><table><thead><tr>'
        '<th>Group</th><th>N</th><th>Bayes WR</th><th>Kelly</th><th>Risk Cap</th><th>Cap $</th><th>MC p95 DD</th><th>Sortino</th><th>GARCH/Heat</th>'
        '</tr></thead><tbody>'
        + ("".join(rows) or "<tr><td colspan='9'>No quant risk groups available.</td></tr>")
        + "</tbody></table></div>"
    )
    return section("Options Quant Risk Budget", body, "Fractional Kelly + Monte Carlo survival + GARCH/heat-map throttle; sizing context only")


def render_grades(model: dict[str, Any]) -> str:
    grades = model["grades"] if isinstance(model["grades"], dict) else {}
    items = grades.get("items") if isinstance(grades.get("items"), list) else []
    rows = []
    for item in items[:18]:
        warnings = item.get("warnings") if isinstance(item.get("warnings"), list) else []
        rows.append(
            "<tr>"
            f"<td><strong>{esc(item.get('name'))}</strong><small>{esc(item.get('category'))}</small></td>"
            f"<td class=\"{cls_for_grade(item.get('ops_grade'))}\">{esc(item.get('ops_grade'))}</td>"
            f"<td class=\"{cls_for_grade(item.get('grade'))}\">{esc(item.get('grade'))}</td>"
            f"<td>{esc(item.get('freshness'))}</td>"
            f"<td>{safe_int(item.get('sample_count'))}</td>"
            f"<td>{safe_int(item.get('signal_count'))}</td>"
            f"<td>{esc(item.get('maturity_stage'))}</td>"
            f"<td>{esc(', '.join(str(w) for w in warnings[:2]))}</td>"
            "</tr>"
        )
    return section(
        "Daily Grades",
        f"""
        <div class="stat-grid compact">
          {stat_card("Evidence", grade_counts_text(grades.get("by_grade", {}) if isinstance(grades.get("by_grade"), dict) else {}), "sample maturity and usefulness")}
          {stat_card("Ops", grade_counts_text(grades.get("by_ops_grade", {}) if isinstance(grades.get("by_ops_grade"), dict) else {}), "logging and freshness")}
          {stat_card("Promotion Ready", str(safe_int(grades.get("promotion_ready_count"))), "requires manual rules review", "good" if not safe_int(grades.get("promotion_ready_count")) else "warn")}
        </div>
        <div class="table-wrap"><table><thead><tr><th>Component</th><th>Ops</th><th>Evidence</th><th>Fresh</th><th>Rows</th><th>Signals</th><th>Stage</th><th>Warnings</th></tr></thead><tbody>{''.join(rows)}</tbody></table></div>
        """,
    )


def render_hot_and_missed(model: dict[str, Any]) -> str:
    hot = model["hot"] if isinstance(model["hot"], dict) else {}
    instruments = hot.get("hot_instruments") if isinstance(hot.get("hot_instruments"), list) else []
    hot_rows = []
    missed_rows = []
    for item in instruments[:20]:
        row = (
            "<tr>"
            f"<td><strong>{esc(item.get('symbol'))}</strong><small>{esc(item.get('bucket'))}</small></td>"
            f"<td>{safe_float(item.get('hot_score')):.2f}</td>"
            f"<td>{safe_int(item.get('social_day_count'))}</td>"
            f"<td>{safe_int(item.get('shadow_sample_count'))}</td>"
            f"<td>{pct(item.get('shadow_win_rate'), scale=True)}</td>"
            f"<td class=\"{cls_for_signed(item.get('total_hypothetical_pnl'))}\">{money(item.get('total_hypothetical_pnl'))}</td>"
            f"<td>{pct(item.get('best_shadow_return_pct'))}</td>"
            f"<td>{esc(item.get('action'))}</td>"
            "</tr>"
        )
        if str(item.get("action")) == "priority_shadow_review":
            hot_rows.append(row)
        elif safe_float(item.get("hot_score")) >= 6:
            missed_rows.append(row)
    return section(
        "Hot Tickers And Missed Bangers",
        f"""
        <div class="split">
          <div>
            <h3>Priority Hot Tickers</h3>
            <div class="table-wrap"><table><thead><tr><th>Symbol</th><th>Hot</th><th>Social Days</th><th>Shadow</th><th>Win</th><th>Hyp. P/L</th><th>Best</th><th>Action</th></tr></thead><tbody>{''.join(hot_rows) or '<tr><td colspan="8">No priority hot tickers.</td></tr>'}</tbody></table></div>
          </div>
          <div>
            <h3>Missed / Watch Bangers</h3>
            <div class="table-wrap"><table><thead><tr><th>Symbol</th><th>Hot</th><th>Social Days</th><th>Shadow</th><th>Win</th><th>Hyp. P/L</th><th>Best</th><th>Action</th></tr></thead><tbody>{''.join(missed_rows[:12]) or '<tr><td colspan="8">0 in current report.</td></tr>'}</tbody></table></div>
          </div>
        </div>
        """,
        "Hot score is context, not a trade trigger. Promotion still needs 30 trading days and completed shadow evidence.",
    )


def render_cheap_asymmetry(model: dict[str, Any]) -> str:
    data = model.get("cheap_asymmetry") if isinstance(model.get("cheap_asymmetry"), dict) else {}
    if not data:
        return section("Cheap Asymmetry Scanner", "<p style='color:var(--muted);padding:12px'>No scan data found — run scripts/cheap_asymmetry_scanner.py first.</p>")
    summary = data.get("summary") if isinstance(data.get("summary"), dict) else {}
    candidates = data.get("top_candidates") if isinstance(data.get("top_candidates"), list) else []
    goal_count = safe_int(summary.get("goal_match_count"))
    goal_tone = "good" if goal_count > 0 else "warn"
    cards = (
        stat_card("Candidates", str(safe_int(data.get("candidate_count"))), f"date {esc(str(data.get('date', ''))[:10])}")
        + stat_card("Goal Matches", str(goal_count), "cost $10-50 + 500%+ captured", goal_tone)
        + stat_card("Rejected", str(safe_int(data.get("rejected_count"))), "below thresholds")
    )
    rows = []
    for item in candidates[:15]:
        gm = item.get("goal_match")
        badge = '<span class="badge-ok">GOAL</span>' if gm else ""
        best_ret = safe_float(item.get("best_return_pct"))
        cap_eff = safe_float(item.get("capture_efficiency"))
        ret_cls = cls_for_signed(best_ret)
        eff_cls = cls_for_signed(cap_eff - 0.5)
        labels_str = esc(", ".join((item.get("labels") or []))[:60])
        rows.append(
            "<tr>"
            f"<td><strong>{esc(item.get('symbol'))}</strong> {badge}</td>"
            f"<td>{esc(item.get('right'))}</td>"
            f"<td class='mono'>${safe_float(item.get('cost')):.0f}</td>"
            f"<td class='mono'>${safe_float(item.get('best_credit')):.0f}</td>"
            f"<td class='{ret_cls}'>{best_ret:.1f}%</td>"
            f"<td class='{eff_cls}'>{cap_eff:.2f}</td>"
            f"<td class='mono'>{safe_int(item.get('spread_cents'))}¢</td>"
            f"<td class='muted small'>{labels_str}</td>"
            "</tr>"
        )
    table = (
        '<div class="grid-3" style="margin-bottom:16px">' + cards + "</div>"
        + '<div class="table-wrap"><table><thead><tr>'
        '<th>Symbol</th><th>Side</th><th>Cost</th><th>Best Credit</th>'
        '<th>Best Ret%</th><th>Cap Eff</th><th>Spread</th><th>Labels</th>'
        '</tr></thead><tbody>'
        + ("".join(rows) or "<tr><td colspan='8'>No candidates.</td></tr>")
        + "</tbody></table></div>"
    )
    return section(
        "Cheap Asymmetry Scanner",
        table,
        "Read-only · $10–$50 cost · 200%+ best return · Goal match = 500%+ captured · No execution",
    )


def render_learning(model: dict[str, Any]) -> str:
    data = model.get("learning") if isinstance(model.get("learning"), dict) else {}
    if not data:
        return section("Flip Bot Learning", "<p style='color:var(--muted);padding:12px'>No report — run scripts/flip_bot_learning_report.py first.</p>")
    actual = data.get("actual") if isinstance(data.get("actual"), dict) else {}
    recent_regime = data.get("recent_regime") if isinstance(data.get("recent_regime"), dict) else {}
    trailing_5 = recent_regime.get("trailing_5") if isinstance(recent_regime.get("trailing_5"), dict) else {}
    trailing_10 = recent_regime.get("trailing_10") if isinstance(recent_regime.get("trailing_10"), dict) else {}
    lessons = data.get("lessons") if isinstance(data.get("lessons"), list) else []
    readiness = data.get("scanner_readiness") if isinstance(data.get("scanner_readiness"), dict) else {}
    high = [l for l in lessons if l.get("severity") == "high"]
    medium = [l for l in lessons if l.get("severity") == "medium"]
    net = safe_float(actual.get("net_pnl"))
    net_cls = cls_for_signed(net)
    cards = (
        stat_card("Closed Trades", str(safe_int(actual.get("closed_count"))), f"date {esc(str(data.get('date', ''))[:10])}")
        + stat_card("Net P/L", money(net), f"win rate {pct(safe_float(actual.get('win_rate')), scale=True)}", "good" if net > 0 else "warn")
        + stat_card("Lessons", str(len(lessons)), f"high={len(high)} medium={len(medium)}", "warn" if high else "")
        + stat_card("Promo-Ready", str(safe_int(readiness.get("promotion_ready_count"))), "scanners ready for candidate review")
        + stat_card("Recent 5-Trade P/L", money(safe_float(trailing_5.get("net_pnl"))), str(trailing_5.get("status") or "no evidence"), "bad" if trailing_5.get("status") == "degraded_pause_new_entries" else "")
        + stat_card("Recent 10-Trade P/L", money(safe_float(trailing_10.get("net_pnl"))), str(trailing_10.get("status") or "no evidence"), "bad" if trailing_10.get("status") == "degraded_pause_new_entries" else "")
    )
    rows = []
    for l in lessons:
        sev = esc(l.get("severity", ""))
        sev_cls = "bad" if sev == "high" else "warn"
        rows.append(
            "<tr>"
            f"<td class='{sev_cls}'><strong>{sev}</strong></td>"
            f"<td>{esc(l.get('type'))}</td>"
            f"<td><strong>{esc(l.get('symbol'))}</strong></td>"
            f"<td class='muted small'>{esc(l.get('lesson', ''))}</td>"
            "</tr>"
        )
    next_actions = data.get("next_learning_actions") if isinstance(data.get("next_learning_actions"), list) else []
    actions_html = "".join(f"<li>{esc(a)}</li>" for a in next_actions)
    body = (
        '<div class="grid-3" style="margin-bottom:16px">' + cards + "</div>"
        + '<div class="table-wrap"><table><thead><tr><th>Severity</th><th>Type</th><th>Symbol</th><th>Lesson</th></tr></thead><tbody>'
        + ("".join(rows) or "<tr><td colspan='4'>No lessons detected.</td></tr>")
        + "</tbody></table></div>"
        + (f'<ul style="margin-top:12px;color:var(--muted)">{actions_html}</ul>' if actions_html else "")
    )
    regime_note = str(recent_regime.get("alert_policy") or "")
    return section("Flip Bot Learning", body, f"Read-only · {regime_note or 'Evidence only'}")


def render_social_replay_queue(model: dict[str, Any]) -> str:
    queue = model.get("social_replay_queue") or []
    research = model.get("agent_reach_research") or {}
    gap = model.get("social_gap_match") or {}
    by_class = research.get("by_classification") or {}
    by_platform = research.get("by_platform") or {}
    channel_status = research.get("channel_status") or {}
    summary = gap.get("summary") or {}
    stats_html = (
        stat_card("Replay Queue", str(len(queue)), "eligible: symbol+direction+entry+stop+target+timeframe+published_at")
        + stat_card("Sources Collected", str(research.get("cumulative_source_count") or 0), "cumulative Agent-Reach intake")
        + stat_card("Preregistration Candidates", str(len(research.get("preregistration_candidates") or [])), "reproducible + validated rules")
        + stat_card("Rejected Marketing", str(len(research.get("rejected_marketing_claims") or [])), "promotional_only, no execution authority", "warn" if research.get("rejected_marketing_claims") else "")
        + stat_card("Extracted Signals", str(summary.get("extracted_count", 0)), f"{summary.get('missing',0)} missing / {summary.get('partial',0)} partial / {summary.get('already_have',0)} already have")
        + stat_card("New Shadow Backlog", str(summary.get("new_backlog_shadow_entries", 0)), "added to signal_registry as research_backlog stubs")
    )
    channel_bits = " · ".join(f"{k}: {v}" for k, v in sorted(channel_status.items()))
    platform_bits = " / ".join(f"{k}={v}" for k, v in sorted(by_platform.items())) or "none"
    classification_bits = " / ".join(f"{k}={v}" for k, v in sorted(by_class.items())) or "none"
    if not queue:
        queue_html = (
            "<p class='muted'>No replay-ready callouts yet. Callout enters the queue only when the source explicitly supplies "
            "one symbol, direction, entry zone, stop, target, timeframe, and publication time. All configured "
            "social snapshots today are rejected marketing / research-lead only.</p>"
        )
    else:
        rows = []
        for r in queue[-25:][::-1]:
            entry = f"{r.get('entry_zone_low','?')}-{r.get('entry_zone_high','?')}" if r.get('entry_zone_high') is not None else str(r.get('entry_zone_low','?'))
            targets = ", ".join(str(t) for t in (r.get('targets') or [])[:3]) or "n/a"
            author = esc(str(r.get('author') or 'n/a'))
            url = esc(str(r.get('url') or ''))
            src = f"<a href='{url}' target='_blank'>{esc(str(r.get('platform') or '?'))}</a>" if url else esc(str(r.get('platform') or '?'))
            verified = "✓ indep" if r.get('independent_verification') else "unverified"
            rows.append(
                "<tr>"
                f"<td>{esc(str(r.get('queued_at') or '')[:19])}</td>"
                f"<td>{esc(str(r.get('symbol') or '?'))}</td>"
                f"<td>{esc(str(r.get('direction') or '?'))}</td>"
                f"<td>{esc(entry)}</td>"
                f"<td>{esc(str(r.get('stop') or '?'))}</td>"
                f"<td>{esc(targets)}</td>"
                f"<td>{esc(str(r.get('timeframe') or '?'))}</td>"
                f"<td>{src} {author}</td>"
                f"<td>{esc(verified)}</td>"
                "</tr>"
            )
        queue_html = (
            "<table class='data'><thead><tr>"
            "<th>Queued</th><th>Sym</th><th>Dir</th><th>Entry</th><th>Stop</th><th>Targets</th><th>TF</th><th>Source</th><th>Verified</th>"
            "</tr></thead><tbody>" + "".join(rows) + "</tbody></table>"
        )
    body = (
        f"<div class='stats'>{stats_html}</div>"
        f"<p class='muted'><strong>Channel status:</strong> {esc(channel_bits)}</p>"
        f"<p class='muted'><strong>By platform:</strong> {esc(platform_bits)} · <strong>By classification:</strong> {esc(classification_bits)}</p>"
        + queue_html
        + "<p class='muted' style='margin-top:12px'>Shadow-only research intake. Never a trade recommendation. "
        "Every callout requires exact preregistration and cost-aware replay before promotion consideration. "
        f"See <code>{esc(str(SOCIAL_GAP_MATCH_REPORT.relative_to(ROOT)))}</code> for extracted-signal-to-registry gap match.</p>"
    )
    return body


def render_spy_5m_0dte_orb(model: dict[str, Any]) -> str:
    """Render the frozen ORB challenger without turning it into an alert."""
    data = model.get("spy_5m_0dte_orb") or {}
    if not data:
        return "<p class='muted'>No replay report yet. This challenger needs supplied, timestamped option bid/ask quotes; it will not assume fills.</p>"
    outcomes = data.get("outcomes") or []
    rows = []
    for item in outcomes[-20:][::-1]:
        outcome = item.get("option_outcome") or {}
        rows.append(
            "<tr>"
            f"<td>{esc(str(item.get('date') or '?'))}</td><td>{esc(str(item.get('direction') or '?'))}</td>"
            f"<td>{esc(str(item.get('signal_bar_completed_at') or '')[:19])}</td>"
            f"<td>{esc(str(outcome.get('outcome') or outcome.get('reason') or outcome.get('status') or '?'))}</td>"
            f"<td>{esc(str(outcome.get('net_return_pct_after_commission') or 'n/a'))}</td></tr>"
        )
    cards = (
        stat_card("ORB Signals", str(data.get("signal_count") or 0), "first completed 5m-range break only")
        + stat_card("Quote Paths", str(data.get("resolved_option_quote_paths") or 0), "entry ask / exit bid only")
        + stat_card("Authority", "SHADOW", "no rank, alert, sizing, or execution authority", "warn")
    )
    blockers = "; ".join(str(x) for x in (data.get("promotion_blockers") or []))
    table = "" if not rows else "<table class='data'><thead><tr><th>Date</th><th>Side</th><th>Decision</th><th>Replay result</th><th>Net %</th></tr></thead><tbody>" + "".join(rows) + "</tbody></table>"
    return f"<div class='stats'>{cards}</div>{table}<p class='muted'>Frozen challenger: M/W/F, 09:30–09:35 ET range, first closed-minute break. {esc(blockers)}</p>"


def render_creator_watchlist(model: dict[str, Any]) -> str:
    data = model.get("creator_watchlist") if isinstance(model.get("creator_watchlist"), dict) else {}
    if not data:
        return section("Creator Watchlist", "<p style='color:var(--muted);padding:12px'>No report — run scripts/creator_watchlist_runner_scanner.py first.</p>")
    summary = data.get("summary") if isinstance(data.get("summary"), dict) else {}
    results = data.get("watchlist_results") if isinstance(data.get("watchlist_results"), list) else []
    cards = (
        stat_card("Symbols", str(safe_int(summary.get("symbol_count"))), f"date {esc(str(data.get('date', ''))[:10])}")
        + stat_card("Runners", str(safe_int(summary.get("runner_count"))), "50%+ shadow return confirmed", "good" if safe_int(summary.get("runner_count")) else "")
        + stat_card("Cheap Asymmetry", str(safe_int(summary.get("cheap_asymmetry_count"))), "$10-50 cost overlap detected")
        + stat_card("Promo-Ready", str(safe_int(summary.get("promotion_ready_count"))), "30d + 10 samples required")
    )
    verdict_cls = {
        "strong_runner_confirmed": "good",
        "runner_confirmed": "good",
        "shadow_seen_no_runner": "warn",
        "needs_shadow_evidence": "muted",
    }
    rows = []
    for row in results[:20]:
        v = str(row.get("verdict", ""))
        ret = safe_float(row.get("best_return_pct"))
        cheap = row.get("cheap_asymmetry_detected")
        cheap_badge = '<span class="badge-ok">CHEAP</span>' if cheap else ""
        rows.append(
            "<tr>"
            f"<td><strong>{esc(row.get('symbol'))}</strong> {cheap_badge}</td>"
            f"<td class='{cls_for_signed(ret)}'>{ret:.1f}%</td>"
            f"<td>{safe_int(row.get('shadow_sample_count'))}</td>"
            f"<td class='{verdict_cls.get(v, '')}'>{esc(v)}</td>"
            f"<td class='muted small'>{esc(', '.join(row.get('creators') or []))[:40]}</td>"
            "</tr>"
        )
    body = (
        '<div class="grid-3" style="margin-bottom:16px">' + cards + "</div>"
        + '<div class="table-wrap"><table><thead><tr>'
        '<th>Symbol</th><th>Best Ret%</th><th>Shadow Samples</th><th>Verdict</th><th>Creators</th>'
        '</tr></thead><tbody>'
        + ("".join(rows) or "<tr><td colspan='5'>No watchlist results.</td></tr>")
        + "</tbody></table></div>"
        + f'<p class="muted small" style="padding:8px 0">{esc(data.get("promotion_note", ""))}</p>'
    )
    return section("Creator Watchlist", body, "Read-only · Discovery lane · No creator claim routes to orders")


def render_nightly_alpha(model: dict[str, Any]) -> str:
    data = model.get("alpha_factory") if isinstance(model.get("alpha_factory"), dict) else {}
    if not data:
        return section("Nightly Alpha Factory", "<p style='color:var(--muted);padding:12px'>No report — run scripts/nightly_alpha_factory.py first.</p>")
    governance = data.get("governance") if isinstance(data.get("governance"), dict) else {}
    promotion = data.get("promotion_summary") if isinstance(data.get("promotion_summary"), dict) else {}
    queue = data.get("opportunity_queue") if isinstance(data.get("opportunity_queue"), list) else []
    blockers = governance.get("blockers") if isinstance(governance.get("blockers"), list) else []
    next_task = (data.get("claude_handoff") or {}).get("next_task") if isinstance(data.get("claude_handoff"), dict) else {}
    promo_count = safe_int(promotion.get("promotion_ready_count"))
    cards = (
        stat_card("Headline", str(safe_int(len(queue))), esc(str(data.get("headline", ""))[:80]))
        + stat_card("Promoted", str(promo_count), "30d + 10 samples + dual review", "good" if promo_count else "")
        + stat_card("Blockers", str(len(blockers)), "unresolved before any promotion", "warn" if blockers else "good")
        + stat_card("Date", esc(str(data.get("date", ""))[:10]), "factory run date")
    )
    verdict_cls = {
        "observe_only": "muted",
        "promote": "good",
        "reject": "bad",
    }
    rows = []
    for item in queue[:15]:
        approval = str(item.get("approval", "observe_only"))
        ret = safe_float(item.get("best_return_pct"))
        rows.append(
            "<tr>"
            f"<td><strong>{esc(item.get('symbol'))}</strong></td>"
            f"<td class='{cls_for_signed(ret)}'>{ret:.1f}%</td>"
            f"<td class='muted small'>{esc(item.get('source', ''))}</td>"
            f"<td class='{verdict_cls.get(approval, '')}'>{esc(approval)}</td>"
            f"<td class='muted small'>{esc(item.get('reason', ''))}</td>"
            "</tr>"
        )
    blocker_html = "".join(f"<li class='warn'>{esc(b)}</li>" for b in blockers)
    next_html = ""
    if isinstance(next_task, dict) and next_task.get("title"):
        next_html = f'<p style="padding:8px 0"><strong>Next task:</strong> <span class="muted">{esc(next_task.get("title", ""))}</span> — {esc(next_task.get("instructions", "")[:120])}</p>'
    body = (
        '<div class="grid-3" style="margin-bottom:16px">' + cards + "</div>"
        + (f'<ul style="margin:0 0 12px">{blocker_html}</ul>' if blocker_html else "")
        + next_html
        + '<div class="table-wrap"><table><thead><tr>'
        '<th>Symbol</th><th>Best Ret%</th><th>Source</th><th>Approval</th><th>Reason</th>'
        '</tr></thead><tbody>'
        + ("".join(rows) or "<tr><td colspan='5'>No ideas queued.</td></tr>")
        + "</tbody></table></div>"
    )
    return section("Nightly Alpha Factory", body, "Read-only coordinator · Builder cannot approve its own signal · No orders")


def render_loop_closure(model: dict[str, Any]) -> str:
    data = model.get("loop_closure") if isinstance(model.get("loop_closure"), dict) else {}
    if not data:
        return section("Loop Closure", "<p style='color:var(--muted);padding:12px'>No report - run scripts/loop_closure_report.py first.</p>")
    summary = data.get("summary") if isinstance(data.get("summary"), dict) else {}
    gate = data.get("next_day_gate") if isinstance(data.get("next_day_gate"), dict) else {}
    trades = data.get("trade_explanations") if isinstance(data.get("trade_explanations"), list) else []
    skips = data.get("no_trade_explanations") if isinstance(data.get("no_trade_explanations"), list) else []
    scoreboard = data.get("promotion_scoreboard") if isinstance(data.get("promotion_scoreboard"), list) else []
    gate_blockers = gate.get("blockers") if isinstance(gate.get("blockers"), list) else []
    cards = (
        stat_card("Closed P/L", money(summary.get("closed_trade_pnl")), f"date {esc(str(data.get('date', ''))[:10])}", cls_for_signed(summary.get("closed_trade_pnl")))
        + stat_card("Trade Explanations", str(safe_int(summary.get("trade_explanation_count"))), f"lessons {safe_int(summary.get('lesson_needed_count'))}")
        + stat_card("No-Trade Reasons", str(safe_int(summary.get("no_trade_count"))), "skip decisions explained")
        + stat_card("Next Gate", "OPEN" if gate.get("can_promote_scanner") else "BLOCKED", ", ".join(str(b) for b in gate_blockers[:2]), "good" if gate.get("can_promote_scanner") else "warn")
    )

    state_cls = {"closed_clean": "good", "lesson_needed": "warn", "entry_filter_review": "bad"}
    trade_rows = []
    for row in trades[:10]:
        quality = row.get("exit_quality") if isinstance(row.get("exit_quality"), dict) else {}
        trade_rows.append(
            "<tr>"
            f"<td><strong>{esc(row.get('symbol'))}</strong><small>{esc(row.get('bot'))}</small></td>"
            f"<td>{esc(row.get('strategy'))}</td>"
            f"<td class='{cls_for_signed(row.get('pnl'))}'>{money(row.get('pnl'))}</td>"
            f"<td>{pct(quality.get('capture_efficiency'), scale=True)}</td>"
            f"<td>{pct(quality.get('giveback_pct'))}</td>"
            f"<td class='{state_cls.get(str(row.get('loop_state')), '')}'>{esc(row.get('loop_state'))}</td>"
            f"<td class='muted small'>{esc(row.get('lesson'))}</td>"
            "</tr>"
        )

    skip_rows = []
    for row in skips[:10]:
        skip_rows.append(
            "<tr>"
            f"<td><strong>{esc(row.get('symbol'))}</strong><small>{esc(row.get('bot'))}</small></td>"
            f"<td>{esc(row.get('strategy'))}</td>"
            f"<td>{esc(row.get('primary_reason'))}</td>"
            f"<td class='mono'>{safe_int(row.get('count'))}</td>"
            f"<td class='muted small'>{esc(row.get('explanation'))}</td>"
            "</tr>"
        )

    promo_cls = {"review_candidate": "good", "near_review": "warn", "blocked": "bad"}
    promo_rows = []
    for row in scoreboard[:12]:
        blockers = row.get("blockers") if isinstance(row.get("blockers"), list) else []
        state = str(row.get("promotion_state") or "")
        promo_rows.append(
            "<tr>"
            f"<td><strong>{esc(row.get('name'))}</strong><small>{esc(row.get('category'))}</small></td>"
            f"<td class='{promo_cls.get(state, '')}'>{esc(state)}</td>"
            f"<td class='mono'>{safe_float(row.get('close_to_live_score')):.1f}</td>"
            f"<td>{safe_int(row.get('sample_count'))}</td>"
            f"<td>{safe_int(row.get('signal_count'))}</td>"
            f"<td class='muted small'>{esc(', '.join(str(b) for b in blockers[:3]))}</td>"
            "</tr>"
        )

    blockers_html = "".join(f"<li class='warn'>{esc(blocker)}</li>" for blocker in gate_blockers)
    body = (
        '<div class="grid-3" style="margin-bottom:16px">' + cards + "</div>"
        + (f"<ul style='margin:0 0 12px'>{blockers_html}</ul>" if blockers_html else "")
        + f"<p class='muted small' style='padding:0 0 12px'>{esc(gate.get('tomorrow_focus', ''))}</p>"
        + '<div class="split" style="margin-bottom:12px">'
        + '<div class="table-wrap"><table><thead><tr><th>Trade</th><th>Strategy</th><th>P/L</th><th>Capture</th><th>Giveback</th><th>State</th><th>Lesson</th></tr></thead><tbody>'
        + ("".join(trade_rows) or "<tr><td colspan='7'>No closed trade explanations.</td></tr>")
        + "</tbody></table></div>"
        + '<div class="table-wrap"><table><thead><tr><th>Skipped</th><th>Strategy</th><th>Reason</th><th>Count</th><th>Explanation</th></tr></thead><tbody>'
        + ("".join(skip_rows) or "<tr><td colspan='5'>No no-trade reasons logged.</td></tr>")
        + "</tbody></table></div></div>"
        + '<div class="table-wrap"><table><thead><tr><th>Scanner</th><th>State</th><th>Score</th><th>Samples</th><th>Signals</th><th>Blockers</th></tr></thead><tbody>'
        + ("".join(promo_rows) or "<tr><td colspan='6'>No promotion scoreboard rows.</td></tr>")
        + "</tbody></table></div>"
    )
    return section("Loop Closure", body, "scanner -> decision -> trade/no-trade -> exit quality -> P/L explanation -> lesson -> next-day gate")


def render_loop_readiness(model: dict[str, Any]) -> str:
    data = model.get("loop_readiness") if isinstance(model.get("loop_readiness"), dict) else {}
    if not data:
        return section("Loop Readiness", "<p style='color:var(--muted);padding:12px'>No report — run scripts/loop_readiness_audit.py first.</p>")
    summary = data.get("summary") if isinstance(data.get("summary"), dict) else {}
    by_level = summary.get("by_level") if isinstance(summary.get("by_level"), dict) else {}
    items = data.get("items") if isinstance(data.get("items"), list) else []
    exec_count = safe_int(summary.get("execution_capable_count"))
    cards = (
        stat_card("Total Loops", str(safe_int(summary.get("total_loops"))), f"date {esc(str(data.get('date', ''))[:10])}")
        + stat_card("L1 Report-Only", str(safe_int(by_level.get("L1"))), "log-and-report, no action")
        + stat_card("L2 Assisted", str(safe_int(by_level.get("L2"))), "human gate required", "warn" if safe_int(by_level.get("L2")) else "")
        + stat_card("Exec-Capable", str(exec_count), "L3 unattended blocked for trading", "warn" if exec_count else "")
    )
    level_cls = {"L0": "muted", "L1": "", "L2": "warn", "L3": "bad"}
    rows = []
    for item in items[:25]:
        lvl = str(item.get("loop_level", "L0"))
        score = safe_int(item.get("readiness_score"))
        cautions = item.get("cautions") if isinstance(item.get("cautions"), list) else []
        rows.append(
            "<tr>"
            f"<td><strong>{esc(item.get('id') or item.get('name'))}</strong></td>"
            f"<td class='{level_cls.get(lvl, '')}'>{esc(lvl)}</td>"
            f"<td class='mono'>{score}</td>"
            f"<td class='muted small'>{esc(', '.join(cautions[:3]))}</td>"
            f"<td class='muted small'>{esc(str(item.get('next_step', ''))[:80])}</td>"
            "</tr>"
        )
    body = (
        '<div class="grid-3" style="margin-bottom:16px">' + cards + "</div>"
        + '<div class="table-wrap"><table><thead><tr>'
        '<th>Loop</th><th>Level</th><th>Score</th><th>Cautions</th><th>Next Step</th>'
        '</tr></thead><tbody>'
        + ("".join(rows) or "<tr><td colspan='5'>No loops scored.</td></tr>")
        + "</tbody></table></div>"
    )
    return section("Loop Readiness", body, "L0=draft · L1=report-only · L2=human-gated · L3=unattended (blocked for trading)")


def render_mahoraga(model: dict[str, Any]) -> str:
    data = model.get("mahoraga") if isinstance(model.get("mahoraga"), dict) else {}
    if not data:
        return section("Mahoraga Intake", "<p style='color:var(--muted);padding:12px'>No report — run scripts/mahoraga_repo_intake_audit.py first.</p>")
    summary = data.get("summary") if isinstance(data.get("summary"), dict) else {}
    queue = data.get("upgrade_queue") if isinstance(data.get("upgrade_queue"), list) else []
    items = data.get("items") if isinstance(data.get("items"), list) else []
    actions = summary.get("actions") if isinstance(summary.get("actions"), dict) else {}
    rejected = [k for k in actions if "reject" in k]
    adopted = sum(actions.get(k, 0) for k in actions if "reject" not in k and k != "study_only")
    cards = (
        stat_card("Ideas Reviewed", str(safe_int(summary.get("selected_count"))), f"date {esc(str(data.get('date', ''))[:10])}")
        + stat_card("Queue", str(len(queue)), f"top: {esc(str(summary.get('top_candidate', 'none')))}", "good" if queue else "")
        + stat_card("Adopted", str(adopted), "adopt/convert/extend patterns")
        + stat_card("Rejected", str(sum(actions.get(k, 0) for k in rejected)), "exec import, 25% sizing, social→orders", "warn" if rejected else "")
    )
    action_cls = {
        "adopt_design_pattern": "good",
        "convert_to_read_only_tool": "good",
        "extend_existing_tool": "good",
        "study_only": "",
        "reject_execution_import": "bad",
        "reject_risk_setting": "bad",
        "reject_social_to_order": "bad",
    }
    rows = []
    for item in items[:15]:
        action = str(item.get("recommended_action", ""))
        conf = safe_int(item.get("confidence_score"))
        risk = safe_int(item.get("risk_score"))
        rows.append(
            "<tr>"
            f"<td><strong>{esc(item.get('idea_id'))}</strong></td>"
            f"<td class='{action_cls.get(action, '')}'>{esc(action)}</td>"
            f"<td class='mono'>{conf}</td>"
            f"<td class='{cls_for_signed(risk * -1)}'>{risk}</td>"
            f"<td class='muted small'>{esc(str(item.get('next_local_tool', ''))[:40])}</td>"
            "</tr>"
        )
    body = (
        '<div class="grid-3" style="margin-bottom:16px">' + cards + "</div>"
        + '<div class="table-wrap"><table><thead><tr>'
        '<th>Idea</th><th>Action</th><th>Confidence</th><th>Risk</th><th>Next Tool</th>'
        '</tr></thead><tbody>'
        + ("".join(rows) or "<tr><td colspan='5'>No ideas scored.</td></tr>")
        + "</tbody></table></div>"
    )
    return section("Mahoraga Intake", body, "Read-only repo intake · No code imported · Rejected: exec worker, 25% sizing, social→orders")


def render_openalice(model: dict[str, Any]) -> str:
    data = model.get("openalice") if isinstance(model.get("openalice"), dict) else {}
    if not data:
        return section("OpenAlice Intake", "<p style='color:var(--muted);padding:12px'>No report — run scripts/openalice_repo_intake_audit.py first.</p>")
    summary = data.get("summary") if isinstance(data.get("summary"), dict) else {}
    queue = data.get("local_upgrade_queue") if isinstance(data.get("local_upgrade_queue"), list) else []
    items = data.get("items") if isinstance(data.get("items"), list) else []
    actions = summary.get("actions") if isinstance(summary.get("actions"), dict) else {}
    adopted = sum(actions.get(k, 0) for k in actions if "reject" not in k and k != "study_only")
    rejected = sum(actions.get(k, 0) for k in actions if "reject" in k)
    cards = (
        stat_card("Ideas Reviewed", str(safe_int(summary.get("selected_count"))), f"date {esc(str(data.get('date', ''))[:10])}")
        + stat_card("Queue", str(len(queue)), f"top: {esc(str(summary.get('top_candidate', 'none')))}", "good" if queue else "")
        + stat_card("Adopted", str(adopted), "adopt/convert/extend patterns")
        + stat_card("Rejected", str(rejected), "broker conn · exec plumbing · agent CLI · AGPL import", "warn" if rejected else "")
    )
    action_cls = {
        "adopt_design_pattern": "good",
        "convert_to_read_only_tool": "good",
        "extend_existing_tool": "good",
        "study_only": "",
    }
    rows = []
    for item in items[:15]:
        action = str(item.get("recommended_action", ""))
        conf = safe_int(item.get("confidence_score"))
        risk = safe_int(item.get("risk_score"))
        rows.append(
            "<tr>"
            f"<td><strong>{esc(item.get('idea_id'))}</strong></td>"
            f"<td class='{action_cls.get(action, 'bad' if 'reject' in action else '')}'>{esc(action)}</td>"
            f"<td class='mono'>{conf}</td>"
            f"<td class='{cls_for_signed(risk * -1)}'>{risk}</td>"
            f"<td class='muted small'>{esc(str(item.get('next_local_tool', ''))[:40])}</td>"
            "</tr>"
        )
    body = (
        '<div class="grid-3" style="margin-bottom:16px">' + cards + "</div>"
        + '<div class="table-wrap"><table><thead><tr>'
        '<th>Idea</th><th>Action</th><th>Confidence</th><th>Risk</th><th>Next Tool</th>'
        '</tr></thead><tbody>'
        + ("".join(rows) or "<tr><td colspan='5'>No ideas scored.</td></tr>")
        + "</tbody></table></div>"
    )
    return section("OpenAlice Intake", body, "Read-only · No code imported · Rejected: broker conn, exec plumbing, agent CLI, AGPL import")


def render_incentive_safety(model: dict[str, Any]) -> str:
    data = model.get("incentive_safety") if isinstance(model.get("incentive_safety"), dict) else {}
    if not data:
        return section("Incentive Safety", "<p style='color:var(--muted);padding:12px'>No report — run scripts/agent_incentive_safety_audit.py first.</p>")
    summary = data.get("summary") if isinstance(data.get("summary"), dict) else {}
    items = data.get("items") if isinstance(data.get("items"), list) else []
    passed = bool(data.get("passed"))
    high = safe_int(summary.get("high_risk_count"))
    medium = safe_int(summary.get("medium_risk_count"))
    exec_cap = safe_int(summary.get("execution_capable_count"))
    cards = (
        stat_card("Components", str(safe_int(summary.get("total_components"))), f"date {esc(str(data.get('date', ''))[:10])}")
        + stat_card("Status", "PASS" if passed else "FAIL", "0 high-risk required for promotion", "good" if passed else "bad")
        + stat_card("High Risk", str(high), "self-approval · dangerous objectives · no stop condition", "bad" if high else "good")
        + stat_card("Exec-Capable", str(exec_cap), f"medium risk flags: {medium}", "warn" if medium else "")
    )
    risk_cls = {"high": "bad", "medium": "warn", "low": "good"}
    rows = []
    for item in items[:20]:
        lvl = str(item.get("risk_level", "low"))
        issues = item.get("issues") if isinstance(item.get("issues"), list) else []
        issue_types = ", ".join(str(i.get("type", "")) for i in issues[:2])
        rows.append(
            "<tr>"
            f"<td><strong>{esc(item.get('id') or item.get('name'))}</strong></td>"
            f"<td class='{risk_cls.get(lvl, '')}'>{esc(lvl)}</td>"
            f"<td class='mono'>{safe_int(item.get('risk_score'))}</td>"
            f"<td>{'yes' if item.get('execution_capable') else ''}</td>"
            f"<td class='muted small'>{esc(issue_types[:60])}</td>"
            "</tr>"
        )
    body = (
        '<div class="grid-3" style="margin-bottom:16px">' + cards + "</div>"
        + '<div class="table-wrap"><table><thead><tr>'
        '<th>Component</th><th>Risk Level</th><th>Score</th><th>Exec?</th><th>Issues</th>'
        '</tr></thead><tbody>'
        + ("".join(rows) or "<tr><td colspan='5'>No components audited.</td></tr>")
        + "</tbody></table></div>"
    )
    return section("Incentive Safety", body, "Agents-of-Chaos governance · High risk blocks promotion · Builder cannot self-approve")


def render_review_and_activity(model: dict[str, Any]) -> str:
    review = model["review"] if isinstance(model["review"], dict) else {}
    items = review.get("items") if isinstance(review.get("items"), list) else []
    activity = model["activity"] if isinstance(model["activity"], list) else []
    by_type = Counter(str(row.get("event_type") or "unknown") for row in activity)
    review_rows = []
    for item in items[:10]:
        review_rows.append(
            "<tr>"
            f"<td>{esc(item.get('date'))}</td>"
            f"<td>{esc(item.get('bot'))}</td>"
            f"<td><strong>{esc(item.get('symbol') or item.get('market_ticker'))}</strong></td>"
            f"<td>{esc(item.get('reason'))}</td>"
            f"<td>{esc(item.get('verdict'))}</td>"
            f"<td>{esc(item.get('next_action'))}</td>"
            "</tr>"
        )
    activity_rows = []
    for key, count in by_type.most_common(10):
        activity_rows.append(f"<tr><td>{esc(key)}</td><td>{count}</td></tr>")
    return section(
        "Needs Review And Daily Activity",
        f"""
        <div class="split">
          <div class="table-wrap"><table><thead><tr><th>Date</th><th>Bot</th><th>Symbol</th><th>Reason</th><th>Verdict</th><th>Next Action</th></tr></thead><tbody>{''.join(review_rows) or '<tr><td colspan="6">No review items.</td></tr>'}</tbody></table></div>
          <div class="table-wrap"><table><thead><tr><th>Activity Type</th><th>Count</th></tr></thead><tbody>{''.join(activity_rows) or '<tr><td colspan="2">No daily activity CSV found.</td></tr>'}</tbody></table></div>
        </div>
        """,
    )


def render_positions(model: dict[str, Any]) -> str:
    rows = []
    for pos in model["positions"]:
        rows.append(
            "<tr>"
            f"<td><strong>{esc(pos.get('symbol'))}</strong><small>{esc(pos.get('underlying'))}</small></td>"
            f"<td>{esc(pos.get('qty'))}</td>"
            f"<td>{money(pos.get('market_value'))}</td>"
            f"<td>{money(pos.get('cost_basis'))}</td>"
            f"<td class=\"{cls_for_signed(pos.get('unrealized_pl'))}\">{money(pos.get('unrealized_pl'))}</td>"
            f"<td>{pct(safe_float(pos.get('unrealized_plpc')) * 100)}</td>"
            f"<td>{esc(pos.get('direction'))}</td>"
            "</tr>"
        )
    return section(
        "Open Positions",
        f"""<div class="table-wrap"><table><thead><tr><th>Symbol</th><th>Qty</th><th>Market Value</th><th>Cost Basis</th><th>Unrealized</th><th>Unrealized %</th><th>Direction</th></tr></thead><tbody>{''.join(rows) or '<tr><td colspan="7">No open positions found.</td></tr>'}</tbody></table></div>""",
    )


def render_html(model: dict[str, Any]) -> str:
    title = "Vibe Trading"
    nav_links = [
        ("#overview",  "Overview"),
        ("#pnl",       "P/L"),
        ("#charts",    "Charts"),
        ("#risk",      "Risk"),
        ("#bots",      "Bots"),
        ("#flip",      "Flip Trades"),
        ("#iwm",       "IWM Trades"),
        ("#positions", "Positions"),
        ("#daily-map", "Daily Map"),
        ("#ops-runs",  "Run Evidence"),
        ("#health",    "Health"),
        ("#alerts",    "Sim Alerts"),
        ("#focus",     "Focus"),
        ("#priority-recall", "Priority Recall"),
        ("#swing-lifecycle", "Swing Lifecycle"),
        ("#mastery",   "Mastery"),
        ("#heatmap",   "Heat Map"),
        ("#kronos",    "Kronos"),
        ("#consensus", "Consensus"),
        ("#grades",    "Grades"),
        ("#hot",       "Hot Tickers"),
        ("#asymmetry", "Asymmetry"),
        ("#learning",  "Learning"),
        ("#improvement", "Daily Accountability"),
        ("#watchlist", "Watchlist"),
        ("#social",    "Social Replay"),
        ("#orb",       "5m ORB Replay"),
        ("#alpha",     "Alpha"),
        ("#closure",   "Closure"),
        ("#loops",     "Loops"),
        ("#mahoraga",  "Mahoraga"),
        ("#openalice", "OpenAlice"),
        ("#incentive", "Incentives"),
        ("#review",    "Review"),
    ]
    nav_html = "".join(f'<a href="{href}">{label}</a>' for href, label in nav_links)
    chart_json = json.dumps(model.get("chart_data", {}), separators=(",", ":"), ensure_ascii=False).replace("</", "<\\/")
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{title} · Control Room</title>
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&family=JetBrains+Mono:wght@400;600&display=swap" rel="stylesheet">
  <style>
    :root {{
      --bg:      #0D1117;
      --surface: #161B22;
      --raised:  #1C2128;
      --border:  #30363D;
      --border2: #21262D;
      --ink:     #E6EDF3;
      --muted:   #7D8590;
      --dim:     #484F58;
      --green:   #3FB950;
      --green-bg:#0D2D1A;
      --red:     #F85149;
      --red-bg:  #2D1215;
      --amber:   #D29922;
      --amber-bg:#2B1F08;
      --blue:    #58A6FF;
      --blue-bg: #0D1F33;
      --mono:    "JetBrains Mono", "Fira Code", monospace;
      --sans:    "Inter", ui-sans-serif, system-ui, sans-serif;
      --nav-h:   52px;
      --radius:  8px;
    }}
    *, *::before, *::after {{ box-sizing: border-box; margin: 0; }}

    /* ── Base ── */
    html {{ scroll-behavior: smooth; scroll-padding-top: calc(var(--nav-h) + 12px); }}
    body {{ background: var(--bg); color: var(--ink); font-family: var(--sans); font-size: 14px; line-height: 1.5; }}
    a {{ color: var(--blue); text-decoration: none; }}
    a:hover {{ text-decoration: underline; }}

    /* ── Nav ── */
    nav {{
      position: sticky; top: 0; z-index: 100;
      height: var(--nav-h);
      background: rgba(13,17,23,.92);
      backdrop-filter: blur(12px);
      border-bottom: 1px solid var(--border2);
      display: flex; align-items: center;
      padding: 0 24px; gap: 4px;
    }}
    .nav-brand {{
      font-family: var(--mono); font-size: 13px; font-weight: 600;
      color: var(--green); letter-spacing: .06em;
      margin-right: 20px; white-space: nowrap; flex-shrink: 0;
    }}
    nav a {{
      padding: 6px 10px; border-radius: 6px; font-size: 12px;
      font-weight: 500; color: var(--muted); white-space: nowrap;
    }}
    nav a:hover {{ background: var(--raised); color: var(--ink); text-decoration: none; }}
    .nav-ts {{
      margin-left: auto; font-family: var(--mono); font-size: 11px;
      color: var(--dim); white-space: nowrap; flex-shrink: 0;
    }}
    .pulse {{
      display: inline-block; width: 7px; height: 7px; border-radius: 50%;
      background: var(--green); box-shadow: 0 0 0 3px rgba(63,185,80,.20);
      margin-right: 6px; vertical-align: middle;
    }}

    /* ── Layout ── */
    main {{ max-width: 1520px; margin: 0 auto; padding: 28px 24px 60px; }}
    .page-header {{ padding: 10px 0 28px; border-bottom: 1px solid var(--border2); margin-bottom: 28px; }}
    .page-header h1 {{
      font-family: var(--mono); font-size: clamp(28px, 3.5vw, 48px);
      font-weight: 600; color: var(--ink); letter-spacing: .02em; line-height: 1.1;
    }}
    .page-header p {{ color: var(--muted); font-size: 13px; margin-top: 6px; }}

    /* ── Sections ── */
    .section {{ margin-top: 32px; scroll-margin-top: calc(var(--nav-h) + 8px); }}
    .section-label {{
      display: flex; align-items: center; gap: 12px;
      margin-bottom: 14px; padding-bottom: 10px;
      border-bottom: 1px solid var(--border2);
    }}
    .section-label h2 {{
      font-size: 13px; font-weight: 600; text-transform: uppercase;
      letter-spacing: .08em; color: var(--muted);
    }}
    .section-label p {{ font-size: 12px; color: var(--dim); }}
    .section-label .badge {{
      font-family: var(--mono); font-size: 10px; font-weight: 600;
      padding: 2px 7px; border-radius: 4px; border: 1px solid var(--border);
      color: var(--muted); background: var(--raised); flex-shrink: 0;
    }}

    /* ── Panel ── */
    .panel {{
      background: var(--surface);
      border: 1px solid var(--border);
      border-radius: var(--radius);
      padding: 20px;
      margin-bottom: 12px;
    }}
    .panel h3 {{
      font-size: 11px; font-weight: 600; text-transform: uppercase;
      letter-spacing: .08em; color: var(--muted); margin-bottom: 12px;
    }}

    /* Charts */
    .chart-grid {{ display:grid; grid-template-columns:repeat(2,minmax(0,1fr)); gap:12px; }}
    .chart-panel {{ min-height:330px; }}
    .chart-box {{ height:245px; width:100%; border:1px solid var(--border2); border-radius:6px; background:#0B0F14; overflow:hidden; }}
    .chart-note {{ font-size:11px; color:var(--dim); margin-top:9px; }}
    .chart-fallback {{
      height:100%; display:grid; place-items:center; padding:18px;
      text-align:center; color:var(--muted); font-size:12px;
    }}
    .rank-chart {{ display:grid; gap:9px; padding:6px 0 2px; }}
    .rank-row {{ display:grid; grid-template-columns:54px minmax(0,1fr) 58px 96px; gap:10px; align-items:center; }}
    .rank-symbol {{ font-family:var(--mono); color:var(--ink); font-weight:600; }}
    .rank-track {{ height:10px; border-radius:999px; background:#0B0F14; border:1px solid var(--border2); overflow:hidden; }}
    .rank-track i {{ display:block; height:100%; background:linear-gradient(90deg,var(--blue),var(--green)); border-radius:999px; }}
    .rank-score, .rank-meta {{ font-family:var(--mono); font-size:12px; text-align:right; }}

    /* ── Stat cards ── */
    .stat-grid {{ display: grid; gap: 8px; }}
    .g4 {{ grid-template-columns: repeat(4, minmax(0,1fr)); }}
    .g6 {{ grid-template-columns: repeat(6, minmax(0,1fr)); }}
    .g8 {{ grid-template-columns: repeat(8, minmax(0,1fr)); }}
    .stat {{
      background: var(--raised); border: 1px solid var(--border2);
      border-radius: 6px; padding: 14px 16px; min-height: 90px;
      display: flex; flex-direction: column; justify-content: space-between;
    }}
    .stat-label {{
      font-size: 11px; font-weight: 600; text-transform: uppercase;
      letter-spacing: .07em; color: var(--muted);
    }}
    .stat-value {{
      font-family: var(--mono); font-size: 24px; font-weight: 600;
      color: var(--ink); line-height: 1.1; margin-top: 8px;
      overflow-wrap: anywhere;
    }}
    .stat-sub {{
      font-size: 11px; color: var(--dim); margin-top: 6px; line-height: 1.3;
    }}
    .stat.good .stat-value {{ color: var(--green); }}
    .stat.bad  .stat-value {{ color: var(--red); }}
    .stat.warn .stat-value {{ color: var(--amber); }}
    .stat.good {{ border-left: 2px solid var(--green); }}
    .stat.bad  {{ border-left: 2px solid var(--red); }}
    .stat.warn {{ border-left: 2px solid var(--amber); }}

    /* ── Split ── */
    .split {{ display: grid; grid-template-columns: 1fr 1fr; gap: 12px; }}
    .split > * {{ min-width: 0; }}

    /* ── Tables ── */
    .table-wrap {{
      overflow-x: auto; border: 1px solid var(--border);
      border-radius: var(--radius); background: var(--surface);
    }}
    table {{ width: 100%; border-collapse: collapse; font-size: 13px; min-width: 600px; }}
    thead th {{
      background: var(--raised); color: var(--muted);
      font-size: 10px; font-weight: 600; text-transform: uppercase;
      letter-spacing: .07em; padding: 10px 12px;
      text-align: left; white-space: nowrap;
      position: sticky; top: 0; z-index: 1;
      border-bottom: 1px solid var(--border);
    }}
    tbody tr {{ border-top: 1px solid var(--border2); }}
    tbody tr:hover {{ background: var(--raised); }}
    td {{ padding: 9px 12px; vertical-align: top; color: var(--ink); }}
    td strong {{ display: block; font-weight: 600; white-space: nowrap; }}
    td small {{ display: block; color: var(--muted); font-size: 11px; margin-top: 2px; }}
    td.mono {{ font-family: var(--mono); font-size: 12px; }}
    .trades table {{ min-width: 900px; }}

    /* ── Status colors on cells ── */
    .good {{ color: var(--green); }}
    .bad  {{ color: var(--red); }}
    .warn {{ color: var(--amber); }}

    /* ── Collapsible trade tables ── */
    details {{ margin-top: 10px; }}
    summary {{
      cursor: pointer; user-select: none;
      display: inline-flex; align-items: center; gap: 8px;
      font-size: 12px; font-weight: 600; color: var(--blue);
      padding: 6px 0; list-style: none;
    }}
    summary::-webkit-details-marker {{ display: none; }}
    summary::before {{
      content: "▶"; font-size: 9px; transition: transform .15s;
      color: var(--dim);
    }}
    details[open] summary::before {{ transform: rotate(90deg); }}

    /* ── Status badge ── */
    .day-header td {{ background:var(--raised); border-top:2px solid var(--border); padding-top:8px; padding-bottom:4px; }}
    .muted {{ color:var(--muted) !important; }}
    .small {{ font-size:11px; }}
    .badge-ok   {{ display:inline-block; padding:2px 7px; border-radius:4px; font-size:10px; font-weight:700; background:var(--green-bg); color:var(--green); }}
    .badge-warn {{ display:inline-block; padding:2px 7px; border-radius:4px; font-size:10px; font-weight:700; background:var(--amber-bg); color:var(--amber); }}
    .badge-bad  {{ display:inline-block; padding:2px 7px; border-radius:4px; font-size:10px; font-weight:700; background:var(--red-bg);   color:var(--red); }}
    .badge-info {{ display:inline-block; padding:2px 7px; border-radius:4px; font-size:10px; font-weight:700; background:var(--blue-bg);  color:var(--blue); }}

    /* ── Section divider ── */
    .divider {{ height:1px; background:var(--border2); margin: 28px 0; }}

    /* ── Footer ── */
    footer {{
      margin-top: 40px; padding-top: 20px;
      border-top: 1px solid var(--border2);
      font-size: 11px; color: var(--dim); text-align: center; line-height: 1.8;
    }}

    /* ── Responsive ── */
    @media (max-width: 1100px) {{
      .g8 {{ grid-template-columns: repeat(4, minmax(0,1fr)); }}
      .g6 {{ grid-template-columns: repeat(3, minmax(0,1fr)); }}
    }}
    @media (max-width: 780px) {{
      .g4, .g6, .g8 {{ grid-template-columns: repeat(2, minmax(0,1fr)); }}
      .split, .chart-grid {{ grid-template-columns: 1fr; }}
      nav a {{ display: none; }}
      nav a:nth-child(-n+5) {{ display: block; }}
    }}
    @media (max-width: 480px) {{
      main {{ padding: 16px 12px 40px; }}
      .g4, .g6, .g8 {{ grid-template-columns: 1fr; }}
    }}

    /* ── Override old section/stat_card helpers ── */
    .section-head {{ display:none; }}
    .section-head ~ * {{ }}
    .panel .section-head {{ display:flex; margin-bottom:12px; }}
    .panel .section-head h2 {{
      font-size:13px; font-weight:600; color:var(--ink);
      text-transform:none; letter-spacing:0;
    }}
    .panel .section-head p {{ font-size:12px; color:var(--dim); max-width:600px; }}
    .stat span   {{ font-size:10px; font-weight:600; text-transform:uppercase; letter-spacing:.07em; color:var(--muted); }}
    .stat strong {{ font-family:var(--mono); font-size:22px; font-weight:600; color:var(--ink); display:block; margin-top:6px; line-height:1.1; overflow-wrap:anywhere; }}
    .stat small  {{ font-size:11px; color:var(--dim); display:block; margin-top:5px; line-height:1.3; }}
    .stat {{ background:var(--raised); border:1px solid var(--border2); border-radius:6px; padding:14px 16px; min-height:88px; }}
    .stat.good strong {{ color:var(--green); }}
    .stat.bad  strong {{ color:var(--red); }}
    .stat.warn strong {{ color:var(--amber); }}
    .stat.good {{ border-left:2px solid var(--green); }}
    .stat.bad  {{ border-left:2px solid var(--red); }}
    .stat.warn {{ border-left:2px solid var(--amber); }}
    .stat-grid {{ display:grid; gap:8px; }}
    .hero-grid {{ grid-template-columns:repeat(4,minmax(0,1fr)); }}
    .compact   {{ grid-template-columns:repeat(6,minmax(0,1fr)); }}
    .table-wrap {{ overflow-x:auto; border:1px solid var(--border); border-radius:var(--radius); background:var(--surface); }}
    .panel {{ background:var(--surface); border:1px solid var(--border); border-radius:var(--radius); padding:20px; margin-bottom:12px; }}
    /* === A+ SPOTLIGHT === */
    @keyframes aplus-pulse {{
      0%,100% {{ box-shadow: 0 0 0 0 rgba(229,57,53,0.55), 0 0 32px rgba(229,57,53,0.35); }}
      50%     {{ box-shadow: 0 0 0 8px rgba(229,57,53,0.00), 0 0 48px rgba(229,57,53,0.55); }}
    }}
    @keyframes aplus-shimmer {{
      0%   {{ background-position: 0% 50%; }}
      100% {{ background-position: 200% 50%; }}
    }}
    .aplus-spotlight {{
      background: linear-gradient(120deg,#7f0d0d 0%,#e53935 25%,#ffab00 50%,#e53935 75%,#7f0d0d 100%);
      background-size: 200% 200%;
      animation: aplus-shimmer 6s linear infinite, aplus-pulse 2.4s ease-in-out infinite;
      border-radius: var(--radius);
      padding: 20px 24px;
      margin-bottom: 16px;
      color: #fff;
      border: 2px solid #fff3;
    }}
    .aplus-spotlight .aplus-head {{
      display:flex; align-items:center; justify-content:space-between; gap:16px;
      font-family: var(--sans); font-weight: 900;
      font-size: 26px; letter-spacing: 1.5px; text-transform: uppercase;
      text-shadow: 0 2px 10px rgba(0,0,0,0.55);
    }}
    .aplus-spotlight .aplus-count {{
      font-size: 44px; font-weight: 900; line-height: 1;
      padding: 4px 16px; border-radius: 12px;
      background: rgba(0,0,0,0.35); border: 2px solid #fff;
    }}
    .aplus-spotlight .aplus-list {{
      display: grid; grid-template-columns: repeat(auto-fit,minmax(260px,1fr)); gap: 12px; margin-top: 16px;
    }}
    .aplus-spotlight .aplus-card {{
      background: rgba(0,0,0,0.35); border: 1px solid rgba(255,255,255,0.25); border-radius: 10px;
      padding: 12px 14px; font-family: var(--mono, ui-monospace, Menlo, monospace); font-size: 13px;
    }}
    .aplus-spotlight .aplus-card .row-title {{
      font-family: var(--sans); font-size: 18px; font-weight: 800; letter-spacing: 0.5px;
      display:flex; align-items:center; gap:8px; margin-bottom:6px;
    }}
    .aplus-spotlight .aplus-card .dir-bull {{ color: #7fff9c; }}
    .aplus-spotlight .aplus-card .dir-bear {{ color: #ffb0b0; }}
    .aplus-spotlight .aplus-card .lvl {{ display:flex; justify-content:space-between; padding: 2px 0; }}
    .aplus-spotlight .aplus-card .lvl b {{ color: #ffe082; }}
    .aplus-spotlight .aplus-empty {{
      font-family: var(--sans); font-size: 14px; opacity: 0.9; margin-top: 8px;
    }}
    .aplus-spotlight .aplus-sub {{
      font-family: var(--sans); font-size: 12px; opacity: 0.85; margin-top: 4px;
    }}
    /* Dim spotlight to a slim badge when no A+ setup is live */
    .aplus-spotlight.aplus-idle {{
      background: linear-gradient(120deg,#1e293b,#111827);
      animation: none; border: 1px solid var(--border); color: var(--dim);
    }}
    .aplus-spotlight.aplus-idle .aplus-head {{ font-size:14px; letter-spacing:1px; }}
    .aplus-spotlight.aplus-idle .aplus-count {{ font-size:14px; background:transparent; border:1px solid var(--border); color:var(--dim); }}
    /* === B+ SPOTLIGHT (amber, second tier) === */
    @keyframes bplus-glow {{
      0%,100% {{ box-shadow: 0 0 0 0 rgba(255,179,0,0.35), 0 0 22px rgba(255,179,0,0.30); }}
      50%     {{ box-shadow: 0 0 0 6px rgba(255,179,0,0.00), 0 0 30px rgba(255,179,0,0.45); }}
    }}
    .bplus-spotlight {{
      background: linear-gradient(120deg,#3a2a05 0%,#ffb300 45%,#ffca28 55%,#3a2a05 100%);
      background-size: 200% 200%;
      animation: aplus-shimmer 8s linear infinite, bplus-glow 3.2s ease-in-out infinite;
      border-radius: var(--radius);
      padding: 16px 22px;
      margin-bottom: 16px;
      color: #1a1200;
      border: 2px solid #fff5;
    }}
    .bplus-spotlight .bplus-head {{
      display:flex; align-items:center; justify-content:space-between; gap:16px;
      font-family: var(--sans); font-weight: 900;
      font-size: 22px; letter-spacing: 1.2px; text-transform: uppercase;
      text-shadow: 0 1px 4px rgba(0,0,0,0.35);
    }}
    .bplus-spotlight .bplus-count {{
      font-size: 34px; font-weight: 900; line-height: 1;
      padding: 3px 14px; border-radius: 10px;
      background: rgba(0,0,0,0.30); color:#fff; border: 2px solid #fff;
    }}
    .bplus-spotlight .bplus-list {{
      display: grid; grid-template-columns: repeat(auto-fit,minmax(240px,1fr)); gap: 10px; margin-top: 12px;
    }}
    .bplus-spotlight .bplus-card {{
      background: rgba(0,0,0,0.32); border: 1px solid rgba(255,255,255,0.25); border-radius: 10px;
      padding: 10px 12px; font-family: var(--mono, ui-monospace, Menlo, monospace); font-size: 13px; color:#fff;
    }}
    .bplus-spotlight .bplus-card .row-title {{
      font-family: var(--sans); font-size: 16px; font-weight: 800; letter-spacing: 0.4px;
      display:flex; align-items:center; gap:8px; margin-bottom:4px; color:#fff;
    }}
    .bplus-spotlight .bplus-card .dir-bull {{ color: #7fff9c; }}
    .bplus-spotlight .bplus-card .dir-bear {{ color: #ffb0b0; }}
    .bplus-spotlight .bplus-card .lvl {{ display:flex; justify-content:space-between; padding: 2px 0; }}
    .bplus-spotlight .bplus-card .lvl b {{ color: #ffe082; }}
    .bplus-spotlight .bplus-sub {{
      font-family: var(--sans); font-size: 12px; opacity: 0.9; margin-top: 4px; color:#1a1200;
    }}
    .bplus-spotlight.bplus-idle {{
      background: linear-gradient(120deg,#1e293b,#111827);
      animation: none; border: 1px solid var(--border); color: var(--dim);
    }}
    .bplus-spotlight.bplus-idle .bplus-head {{ font-size:14px; letter-spacing:1px; color:var(--dim); }}
    .bplus-spotlight.bplus-idle .bplus-count {{ font-size:14px; background:transparent; border:1px solid var(--border); color:var(--dim); }}
    .bplus-spotlight.bplus-idle .bplus-sub {{ color:var(--dim); }}
  </style>
</head>
<body>
  <nav>
    <span class="nav-brand"><span class="pulse"></span>VIBE&nbsp;TRADING</span>
    {nav_html}
    <span class="nav-ts">Generated {esc(model['generated_at'])}</span>
  </nav>

  <main>
    <div class="page-header">
      <h1>Control Room</h1>
      <p>Read-only · No execution controls · No broker calls · Regenerate: <code>python scripts/generate_dashboard.py</code></p>
    </div>

    {render_overfit_guard(model)}
    {render_operational_gate(model)}

    {render_aplus_spotlight(model)}

    {render_bplus_spotlight(model)}

    <div id="alerts" class="section">
      <div class="section-label"><h2>Simulated Real-Time Alerts</h2><p>Five-minute refresh · Paper entries and watches · No broker execution</p></div>
      {render_simulated_alert_feed(model)}
    </div>

    <div id="focus" class="section">
      <div class="section-label"><h2>Today’s Focus</h2><p>Liquid names pinned from the session plan · Scanner gates remain mandatory</p></div>
      {render_session_focus(model)}
    </div>

    <div id="priority-recall" class="section">
      <div class="section-label"><h2>Priority-Universe Recall</h2><p>Fixed observation denominator · explicit missing coverage · execution eligibility kept separate</p></div>
      {render_priority_universe_recall(model)}
    </div>

    <div id="swing-lifecycle" class="section">
      <div class="section-label"><h2>Persistent Swing Lifecycle</h2><p>Daily state continuity · last transition and age · strict eligibility remains separate</p></div>
      {render_priority_swing_observation(model)}
    </div>

    <div id="daily-map" class="section">
      <div class="section-label"><h2>Daily Map &amp; 3m Confluence</h2><p>Daily directional context · transparent mapped levels · completed 3-minute confirmation</p></div>
      {render_daily_level_map_shadow(model)}
    </div>

    {render_preconfirmation_heads_up(model)}

    {render_intraday_posture_and_lifecycle(model)}

    {render_aplus_evidence_contract(model)}

    {render_liquid_review_escalations(model)}

    {render_wolves_bbr_shadow(model)}

    {render_banks_821_shadow(model)}

    {render_donchian_expansion_shadow(model)}

    {render_liquid_signal_chart_audit(model)}

    {render_multi_timeframe_edge(model)}

    {render_trader_barbie_3m(model)}

    {render_daily_rsi2_challenger(model)}

    {render_strategy_discovery_coverage(model)}

    {render_spy_level_reaction(model)}

    {render_spy_level_outcomes(model)}

    <div id="overview" class="section">
      <div class="section-label"><h2>Overview</h2><p>Account, audit, market force, and daily verdict</p></div>
      <div class="panel">{render_overview(model)}</div>
    </div>

    <div id="pnl" class="section">
      <div class="section-label"><h2>Daily P/L by Symbol</h2><p>Every closed trade grouped by date — newest first</p></div>
      <div class="panel">{render_daily_pnl(model)}</div>
    </div>

    <div id="charts" class="section">
      <div class="section-label"><h2>Charts</h2><p>Interactive visual layer powered by TradingView Lightweight Charts when available</p><span class="badge">read-only</span></div>
      {render_chart_panel(model)}
    </div>

    <div id="risk" class="section">
      <div class="section-label"><h2>Risk State</h2><p>Kill switches, contract caps, guard blocks, tail loss</p></div>
      {render_risk_state(model)}
    </div>

    <div id="bots" class="section">
      <div class="section-label"><h2>Bot Health &amp; P/L</h2><p>All-time and post-config performance for each bot</p></div>
      {render_bot_health(model)}
    </div>

    <div id="flip" class="section">
      <div class="section-label"><h2>Flip Bot Trades</h2><p>All recorded entries — pre-fix artifact included for historical honesty</p></div>
      <div class="panel">
        <details open>
          <summary>Show all Flip Bot trades</summary>
          {render_flip_trades(model)}
        </details>
      </div>
    </div>

    <div id="iwm" class="section">
      <div class="section-label"><h2>IWM / Options Bot Trades</h2><p>Estimated P/L from credit and close reason when broker P/L not stored</p></div>
      <div class="panel">
        <details open>
          <summary>Show all IWM trades</summary>
          {render_iwm_trades(model)}
        </details>
      </div>
    </div>

    <div id="positions" class="section">
      <div class="section-label"><h2>Open Positions</h2><p>Live from last bot status snapshot</p></div>
      {render_positions(model)}
    </div>

    <div id="ops-runs" class="section">
      <div class="section-label"><h2>Operational Run Evidence</h2><p>Machine-readable completion, freshness, delivery, and persistent breaker state</p></div>
      {render_operational_runs(model)}
    </div>

    <div id="health" class="section">
      <div class="section-label"><h2>Signal Health</h2><p>Shadow loggers and scanner freshness</p></div>
      {render_shadow_and_health(model)}
    </div>

    <div id="edge" class="section">
      <div class="section-label"><h2>Daily Edge Orchestrator</h2><p>Morning targets, runners, skip reasons, exit capture, and scanner leadership</p></div>
      {render_daily_edge(model)}
    </div>

    <div id="mastery" class="section">
      <div class="section-label"><h2>Market Mastery</h2><p>Candlestick context, higher timeframe map, and catalyst vetoes</p></div>
      {render_market_mastery(model)}
    </div>

    <div id="heatmap" class="section">
      <div class="section-label"><h2>Options Liquidation Heat Map</h2><p>Public option-chain heat zones, pin risk, and GEX context; read-only</p></div>
      {render_options_heatmap(model)}
    </div>

    <div id="quant-risk" class="section">
      <div class="section-label"><h2>Options Quant Risk Budget</h2><p>Fractional Kelly, Monte Carlo, Sortino, GARCH, and heat-map sizing throttle</p></div>
      {render_options_quant_risk(model)}
    </div>

    <div id="kronos" class="section">
      <div class="section-label"><h2>Kronos Market Forecaster</h2><p>Foundation-model K-line forecast context; shadow only</p></div>
      {render_kronos_forecast(model)}
    </div>

    <div id="consensus" class="section">
      <div class="section-label"><h2>Shadow Consensus Gate</h2><p>Read-only trade advisor: filter, size, playbook, and review guidance</p></div>
      {render_shadow_consensus(model)}
    </div>

    <div id="governed" class="section">
      <div class="section-label"><h2>Governed Shadow Decisions</h2><p>Completed-bar evidence → deterministic policy → simulated decision ledger</p></div>
      {render_governed_shadow_decision(model)}
    </div>

    {render_execution_readiness(model)}
    {render_statistical_governance(model)}
    {render_latency_budget(model)}
    {render_scanner_evidence(model)}

    <div id="grades" class="section">
      <div class="section-label"><h2>Daily Grades</h2><p>Evidence and ops grades — promotion gate requires 30 days + 10 samples</p></div>
      {render_grades(model)}
    </div>

    <div id="hot" class="section">
      <div class="section-label"><h2>Hot Tickers &amp; Missed Bangers</h2><p>Hot score is context only — not a trade trigger</p></div>
      {render_hot_and_missed(model)}
    </div>

    <div id="asymmetry" class="section">
      <div class="section-label"><h2>Cheap Asymmetry Scanner</h2><p>Read-only · $10-$50 cost, 200%+ best return, 500%+ = goal match</p></div>
      {render_cheap_asymmetry(model)}
    </div>

    <div id="learning" class="section">
      <div class="section-label"><h2>Flip Bot Learning</h2><p>Read-only · Daily lessons from closed trades, postmortems, and shadow scans</p></div>
      {render_learning(model)}
    </div>

    <div id="improvement" class="section">
      <div class="section-label"><h2>Daily Learning Accountability</h2><p>Scanner → alert → delivery → timeliness → retained lesson</p></div>
      {render_continuous_improvement(model)}
    </div>

    <div id="watchlist" class="section">
      <div class="section-label"><h2>Creator Watchlist</h2><p>Read-only · Screenshot claims scored against independent shadow evidence</p></div>
      {render_creator_watchlist(model)}
    </div>

    <div id="social" class="section">
      <div class="section-label"><h2>Social Replay Queue</h2><p>Shadow-only · Callouts require symbol+direction+entry+stop+target+timeframe+published_at · No execution authority</p></div>
      {render_social_replay_queue(model)}
    </div>

    <div id="orb" class="section">
      <div class="section-label"><h2>SPY 5-Minute 0DTE ORB Replay</h2><p>Frozen challenger · Quote-aware replay only · No trade alert or order authority</p></div>
      {render_spy_5m_0dte_orb(model)}
    </div>

    <div id="alpha" class="section">
      <div class="section-label"><h2>Nightly Alpha Factory</h2><p>Read-only · Ideas scored nightly · Builder cannot approve its own signal</p></div>
      {render_nightly_alpha(model)}
    </div>

    <div id="closure" class="section">
      <div class="section-label"><h2>Loop Closure</h2><p>Daily decision chain: scanner, decision, trade/no-trade, exit quality, lesson, next gate</p></div>
      {render_loop_closure(model)}
    </div>

    <div id="loops" class="section">
      <div class="section-label"><h2>Loop Readiness</h2><p>L0–L3 governance · L3 unattended blocked for trading</p></div>
      {render_loop_readiness(model)}
    </div>

    <div id="mahoraga" class="section">
      <div class="section-label"><h2>Mahoraga Intake</h2><p>Read-only · Upstream repo ideas scored and governed before any local adoption</p></div>
      {render_mahoraga(model)}
    </div>

    <div id="openalice" class="section">
      <div class="section-label"><h2>OpenAlice Intake</h2><p>Read-only · Issue board and inbox patterns scored before local adoption</p></div>
      {render_openalice(model)}
    </div>

    <div id="incentive" class="section">
      <div class="section-label"><h2>Incentive Safety</h2><p>Agents-of-Chaos governance · High risk blocks promotion · Builder cannot self-approve</p></div>
      {render_incentive_safety(model)}
    </div>

    <div id="review" class="section">
      <div class="section-label"><h2>Needs Review &amp; Daily Activity</h2><p>Guard block queue and event breakdown</p></div>
      {render_review_and_activity(model)}
    </div>

    <footer>
      No execution controls · No server · No broker calls<br>
      Generated from local JSON/JSONL reports in <code>~/.vibe-trading/reports/</code><br>
      Vibe Trading Control Room · {esc(model['generated_at'])}
    </footer>
  </main>
  <script id="chart-data" type="application/json">{chart_json}</script>
  <script src="https://unpkg.com/lightweight-charts@5.2.0/dist/lightweight-charts.standalone.production.js"></script>
  <script>
    (function () {{
      const dataEl = document.getElementById('chart-data');
      const chartData = dataEl ? JSON.parse(dataEl.textContent || '{{}}') : {{}};
      const palette = {{
        bg: '#0B0F14',
        text: '#E6EDF3',
        muted: '#7D8590',
        grid: '#21262D',
        green: '#3FB950',
        red: '#F85149',
        amber: '#D29922',
        blue: '#58A6FF'
      }};

      function fallback(id, message) {{
        const node = document.getElementById(id);
        if (node) node.innerHTML = '<div class="chart-fallback">' + message + '</div>';
      }}

      function makeChart(id) {{
        const node = document.getElementById(id);
        if (!node || !window.LightweightCharts) return null;
        return LightweightCharts.createChart(node, {{
          autoSize: true,
          layout: {{ background: {{ color: palette.bg }}, textColor: palette.muted, fontFamily: 'Inter, sans-serif' }},
          grid: {{ vertLines: {{ color: palette.grid }}, horzLines: {{ color: palette.grid }} }},
          rightPriceScale: {{ borderColor: palette.grid }},
          timeScale: {{ borderColor: palette.grid, timeVisible: false }},
          crosshair: {{ mode: LightweightCharts.CrosshairMode.Normal }}
        }});
      }}

      function addLine(chart, options) {{
        if (chart.addLineSeries) return chart.addLineSeries(options);
        return chart.addSeries(LightweightCharts.LineSeries, options);
      }}

      function addHistogram(chart, options) {{
        if (chart.addHistogramSeries) return chart.addHistogramSeries(options);
        return chart.addSeries(LightweightCharts.HistogramSeries, options);
      }}

      function setSeries(series, rows) {{
        if (!series || !rows || rows.length === 0) return false;
        series.setData(rows);
        return true;
      }}

      function renderCharts() {{
        if (!window.LightweightCharts) {{
          ['chart-account-equity','chart-bot-pnl','chart-health-grades'].forEach(id => fallback(id, 'Lightweight Charts did not load. Tables remain available below.'));
          return;
        }}

        const account = makeChart('chart-account-equity');
        if (account) {{
          const line = addLine(account, {{ color: palette.blue, lineWidth: 2, priceFormat: {{ type: 'price', precision: 2, minMove: 0.01 }} }});
          if (!setSeries(line, chartData.accountEquity)) fallback('chart-account-equity', 'No account equity series found yet.');
          account.timeScale().fitContent();
        }}

        const pnl = makeChart('chart-bot-pnl');
        if (pnl) {{
          const flip = addLine(pnl, {{ color: palette.green, lineWidth: 2, title: 'Flip Bot' }});
          const iwm = addLine(pnl, {{ color: palette.amber, lineWidth: 2, title: 'IWM Options' }});
          const hasFlip = setSeries(flip, chartData.flipPnl);
          const hasIwm = setSeries(iwm, chartData.iwmPnl);
          if (!hasFlip && !hasIwm) fallback('chart-bot-pnl', 'No bot P/L series found yet.');
          pnl.timeScale().fitContent();
        }}

        const health = makeChart('chart-health-grades');
        if (health) {{
          const stale = addHistogram(health, {{ color: 'rgba(210,153,34,.78)', title: 'stale' }});
          const err = addHistogram(health, {{ color: 'rgba(248,81,73,.78)', title: 'error' }});
          const ops = addLine(health, {{ color: palette.green, lineWidth: 2, title: 'ops A' }});
          const evf = addLine(health, {{ color: palette.red, lineWidth: 2, title: 'evidence F' }});
          const hasStale = setSeries(stale, chartData.healthStale);
          const hasErr = setSeries(err, chartData.healthError);
          const hasOps = setSeries(ops, chartData.opsA);
          const hasEvf = setSeries(evf, chartData.evidenceF);
          if (!hasStale && !hasErr && !hasOps && !hasEvf) fallback('chart-health-grades', 'No health or grade trend series found yet.');
          health.timeScale().fitContent();
        }}
      }}

      if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', renderCharts);
      else renderCharts();
    }})();
  </script>
</body>
</html>
"""


def write_dashboard(html_text: str, output_path: Path = OUTPUT_PATH) -> Path:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(html_text, encoding="utf-8")
    return output_path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=OUTPUT_PATH)
    args = parser.parse_args()

    model = load_model()
    output = write_dashboard(render_html(model), args.output)
    print(f"Wrote {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

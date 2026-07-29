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
import re
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

try:
    from options_reporting import dedupe_options_trade_records
except ModuleNotFoundError:
    from scripts.options_reporting import dedupe_options_trade_records

ROOT = Path(__file__).resolve().parent.parent
VIBE_HOME = Path.home() / ".vibe-trading"
REPORT_DIR = VIBE_HOME / "reports"
OUTPUT_PATH = VIBE_HOME / "dashboard.html"

FLIP_TRADES_PATH = VIBE_HOME / "flip-trades.json"
OPTIONS_TRADES_PATH = VIBE_HOME / "options-trades.json"
POSITION_SIZING_LOG = ROOT / "data" / "position_sizing_sanity_log.jsonl"
BOT_STATUS_LOG = ROOT / "data" / "bot_status_snapshot_log.jsonl"
SIGNAL_GRADES_LOG = ROOT / "data" / "signal_stack_grades_log.jsonl"

REPORTS = {
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


def section(title: str, body: str, subtitle: str = "") -> str:
    sub = f"<p>{esc(subtitle)}</p>" if subtitle else ""
    return f"""
    <section class="panel">
      <div class="section-head"><h2>{esc(title)}</h2>{sub}</div>
      {body}
    </section>"""


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
        if not day or pnl is None:
            continue
        by_day.setdefault(day, []).append({
            "symbol": str(trade.get("label") or trade.get("underlying") or "IWM"),
            "bot": "IWM Bot",
            "pnl": pnl,
            "detail": str(trade.get("closing_reason") or ""),
        })

    if not by_day:
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
    return section(
        "Daily P/L by Symbol",
        table,
        "Closed trades only · Flip Bot uses realized P/L · IWM Bot uses credit estimate when broker P/L absent",
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
        </div>
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
    return section("Flip Bot Learning", body, "Read-only · No execution · Evidence only")


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
        ("#health",    "Health"),
        ("#mastery",   "Mastery"),
        ("#heatmap",   "Heat Map"),
        ("#kronos",    "Kronos"),
        ("#consensus", "Consensus"),
        ("#grades",    "Grades"),
        ("#hot",       "Hot Tickers"),
        ("#asymmetry", "Asymmetry"),
        ("#learning",  "Learning"),
        ("#watchlist", "Watchlist"),
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

    <div id="watchlist" class="section">
      <div class="section-label"><h2>Creator Watchlist</h2><p>Read-only · Screenshot claims scored against independent shadow evidence</p></div>
      {render_creator_watchlist(model)}
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

#!/usr/bin/env python3
"""Read-only health report for the new signal stack.

Checks:
- Windows Task Scheduler status for each signal task.
- Latest JSONL row for each expected log.
- Missing/stale/error rows.

No trading. No broker calls. Safe to run any time.
"""
from __future__ import annotations

import argparse
import json
import subprocess
from datetime import date, datetime, timedelta
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
REPORT_DIR = Path.home() / ".vibe-trading" / "reports"
REPORT_PATH = REPORT_DIR / "signal-stack-health.json"
FLIP_TRADES_PATH = Path.home() / ".vibe-trading" / "flip-trades.json"
FLIP_SHADOW_PATH = ROOT / "data" / "flip_shadow_candidates_log.jsonl"

STALENESS_THRESHOLDS = {
    "orb_continuation": {"max_days_without_entry": 5, "max_days_without_close": 10},
    "noise_area_vwap": {"max_days_without_entry": 7, "max_days_without_close": 14},
    "orb_extension_reversal": {"max_days_without_entry": 7},
    "paper_challenger": {"max_days_without_entry": 5},
}
STRATEGY_ACTIVATION_DATES = {
    "orb_continuation": date(2026, 7, 1),
    "noise_area_vwap": date(2026, 7, 16),
    "orb_extension_reversal": date(2026, 7, 17),
    "paper_challenger": date(2026, 7, 16),
}


SIGNALS = [
    {
        "name": "Strat 30m",
        "task": r"\VibeTrade\Strat30mContinuationShadow",
        "log": ROOT / "data" / "strat_30m_continuation_shadow_log.jsonl",
        "kind": "intraday",
    },
    {
        "name": "CZT Order Flow",
        "task": r"\VibeTrade\CZTOrderFlowShadow",
        "log": ROOT / "data" / "czt_order_flow_shadow_log.jsonl",
        "kind": "intraday",
    },
    {
        "name": "GEX Scanner",
        "task": r"\VibeTrade\GEXScanner",
        "log": ROOT / "data" / "gex_scan_log.jsonl",
        "kind": "morning",
    },
    {
        "name": "Schedule Align",
        "task": r"\VibeTrade\MarketScheduleAlignment",
        "log": ROOT / "data" / "market_schedule_alignment_log.jsonl",
        "kind": "morning",
    },
    {
        "name": "IVR Scanner",
        "task": r"\VibeTrade\IVRScanner",
        "log": ROOT / "data" / "iv_history_log.jsonl",
        "kind": "morning",
    },
    {
        "name": "IVR Quality",
        "task": r"\VibeTrade\IVRQualityReport",
        "log": ROOT / "data" / "ivr_quality_report_log.jsonl",
        "kind": "evening",
    },
    {
        "name": "RV/IV Regime",
        "task": r"\VibeTrade\RVIVRegimeScanner",
        "log": ROOT / "data" / "rv_iv_regime_log.jsonl",
        "kind": "morning",
    },
    {
        "name": "Hurst Regime",
        "task": r"\VibeTrade\HurstRegimeScanner",
        "log": ROOT / "data" / "hurst_regime_log.jsonl",
        "kind": "morning",
    },
    {
        "name": "Opening Range",
        "task": r"\VibeTrade\OpeningRangeBreadthScanner",
        "log": ROOT / "data" / "opening_range_breadth_log.jsonl",
        "kind": "morning",
    },
    {
        "name": "Premarket EMA Retest",
        "task": r"\VibeTrade\PremarketEMARetestShadow",
        "log": ROOT / "data" / "premarket_ema_retest_shadow_log.jsonl",
        "kind": "intraday",
    },
    {
        "name": "Relative Volume",
        "task": r"\VibeTrade\RelativeVolumeScanner",
        "log": ROOT / "data" / "relative_volume_scan_log.jsonl",
        "kind": "close",
    },
    {
        "name": "SEC Insider",
        "task": r"\VibeTrade\SECInsiderBuyingScanner",
        "log": ROOT / "data" / "sec_insider_buying_log.jsonl",
        "kind": "evening",
    },
    {
        "name": "Market Force",
        "task": r"\VibeTrade\MarketForceScore",
        "log": ROOT / "data" / "market_force_score_log.jsonl",
        "kind": "evening",
    },
    {
        "name": "Distribution",
        "task": r"\VibeTrade\DistributionDayScanner",
        "log": ROOT / "data" / "distribution_day_log.jsonl",
        "kind": "close",
    },
    {
        "name": "Breadth",
        "task": r"\VibeTrade\MarketBreadthUptrendScanner",
        "log": ROOT / "data" / "market_breadth_uptrend_log.jsonl",
        "kind": "close",
    },
    {
        "name": "Sector Rotation",
        "task": r"\VibeTrade\SectorRotationRanker",
        "log": ROOT / "data" / "sector_rotation_rank_log.jsonl",
        "kind": "close",
    },
    {
        "name": "Exposure Coach",
        "task": r"\VibeTrade\ExposureCoach",
        "log": ROOT / "data" / "exposure_coach_log.jsonl",
        "kind": "evening",
    },
    {
        "name": "Portfolio Risk",
        "task": r"\VibeTrade\PortfolioConcentrationMonitor",
        "log": ROOT / "data" / "portfolio_concentration_log.jsonl",
        "kind": "intraday",
    },
    {
        "name": "Bot Status",
        "task": r"\VibeTrade\BotStatusSnapshot",
        "log": ROOT / "data" / "bot_status_snapshot_log.jsonl",
        "kind": "evening",
    },
    {
        "name": "Regime Memory",
        "task": r"\VibeTrade\RegimeMemoryReport",
        "log": ROOT / "data" / "regime_memory_log.jsonl",
        "kind": "evening",
    },
    {
        "name": "Rejected Trades",
        "task": r"\VibeTrade\RejectedTradeIntelligence",
        "log": ROOT / "data" / "rejected_trade_intelligence_log.jsonl",
        "kind": "evening",
    },
    {
        "name": "Needs Review",
        "task": r"\VibeTrade\NeedsReviewQueue",
        "log": ROOT / "data" / "needs_review_queue_log.jsonl",
        "kind": "evening",
    },
    {
        "name": "Grades",
        "task": r"\VibeTrade\SignalStackGrades",
        "log": ROOT / "data" / "signal_stack_grades_log.jsonl",
        "kind": "evening",
    },
    {
        "name": "EOD Summary",
        "task": r"\VibeTrade\DailyEODSummary",
        "log": ROOT / "data" / "daily_eod_summary_log.jsonl",
        "kind": "evening",
    },
    {
        "name": "Nightly Loop",
        "task": r"\VibeTrade\NightlyResearchLoop",
        "log": ROOT / "data" / "nightly_research_queue_log.jsonl",
        "kind": "evening",
    },
    {
        "name": "Postmortem",
        "task": r"\VibeTrade\ClosedTradePostmortem",
        "log": ROOT / "data" / "closed_trade_postmortem_log.jsonl",
        "kind": "evening",
    },
    {
        "name": "Outcome Review",
        "task": r"\VibeTrade\DailyOutcomeReviewer",
        "log": ROOT / "data" / "daily_outcome_review_log.jsonl",
        "kind": "evening",
    },
    {
        "name": "Challenge Sim",
        "task": r"\VibeTrade\ChallengeAccountSimulator",
        "log": ROOT / "data" / "challenge_account_simulator_log.jsonl",
        "kind": "evening",
    },
    {
        "name": "Flip Shadow PnL",
        "task": r"\VibeTrade\FlipShadowPnLEvaluator",
        "log": ROOT / "data" / "flip_shadow_pnl_evaluation_log.jsonl",
        "kind": "evening",
    },
    {
        "name": "Flip Bot Learning",
        "task": r"\VibeTrade\FlipBotLearningReport",
        "log": ROOT / "data" / "flip_bot_learning_log.jsonl",
        "kind": "evening",
    },
    {
        "name": "Loop Closure",
        "task": r"\VibeTrade\LoopClosureReport",
        "log": ROOT / "data" / "loop_closure_report_log.jsonl",
        "kind": "evening",
    },
    {
        "name": "Weekly Hot Instruments",
        "task": r"\VibeTrade\WeeklyHotInstrumentReport",
        "log": ROOT / "data" / "weekly_hot_instrument_log.jsonl",
        "kind": "evening",
    },
    {
        "name": "Public Social Intake",
        "task": r"\VibeTrade\PublicSocialIntake",
        "log": ROOT / "data" / "public_social_intake_log.jsonl",
        "kind": "morning",
    },
    {
        "name": "Geopolitical Risk",
        "task": r"\VibeTrade\IntradayRiskRefresh",
        "log": ROOT / "data" / "geopolitical_risk_context_log.jsonl",
        "kind": "intraday",
    },
    {
        "name": "Deep Liquid Universe",
        "task": r"\VibeTrade\DeepLiquidUniverseScanner",
        "log": ROOT / "data" / "deep_liquid_universe_scan_log.jsonl",
        "kind": "intraday",
    },
    {
        "name": "TTM Squeeze",
        "task": r"\VibeTrade\TTMSqueezeShadowLogger",
        "log": ROOT / "data" / "ttm_squeeze_shadow_log.jsonl",
        "kind": "close",
    },
    {
        "name": "WaveTrend",
        "task": r"\VibeTrade\WaveTrendShadowLogger",
        "log": ROOT / "data" / "wavetrend_shadow_log.jsonl",
        "kind": "close",
    },
    {
        "name": "MFI Shadow",
        "task": r"\VibeTrade\MFIShadowLogger",
        "log": ROOT / "data" / "mfi_shadow_log.jsonl",
        "kind": "close",
    },
    {
        "name": "SMC",
        "task": r"\VibeTrade\SMCShadowLogger",
        "log": ROOT / "data" / "smc_shadow_log.jsonl",
        "kind": "close",
    },
    {
        "name": "Prediction Microstructure",
        "task": r"\VibeTrade\PredictionMarketMicrostructure",
        "log": ROOT / "data" / "prediction_market_microstructure_log.jsonl",
        "kind": "evening",
    },
    {
        "name": "MoonDev Liquidations",
        "task": r"\VibeTrade\MoonDevLiquidationContext",
        "log": ROOT / "data" / "moondev_liquidation_context_log.jsonl",
        "kind": "evening",
    },
    {
        "name": "Options Liquidity Gate",
        "task": r"\VibeTrade\OptionsLiquidityFeasibility",
        "log": ROOT / "data" / "options_liquidity_feasibility_log.jsonl",
        "kind": "evening",
    },
    {
        "name": "Options Surface Intelligence",
        "task": r"\VibeTrade\OptionsSurfaceIntelligence",
        "log": ROOT / "data" / "options_surface_intelligence_log.jsonl",
        "kind": "evening",
    },
    {
        "name": "Daily Options Universe",
        "task": r"\VibeTrade\DailyOptionsUniverseRanker",
        "log": ROOT / "data" / "daily_options_universe_ranker_log.jsonl",
        "kind": "evening",
    },
    {
        "name": "Flip Exit Quality",
        "task": r"\VibeTrade\FlipExitQualityReport",
        "log": ROOT / "data" / "flip_exit_quality_log.jsonl",
        "kind": "evening",
    },
    {
        "name": "Flip Exit Policy",
        "task": r"\VibeTrade\FlipExitPolicyComparison",
        "log": ROOT / "data" / "flip_exit_policy_comparison_log.jsonl",
        "kind": "evening",
    },
    {
        "name": "Flip Feature Ablation",
        "task": r"\VibeTrade\FlipFeatureAblationReport",
        "log": ROOT / "data" / "flip_feature_ablation_log.jsonl",
        "kind": "evening",
    },
    {
        "name": "Flip Equity Curve",
        "task": r"\VibeTrade\FlipEquityCurveReport",
        "log": ROOT / "data" / "flip_equity_curve_log.jsonl",
        "kind": "evening",
    },
    {
        "name": "Edge Trial Ledger",
        "task": r"\VibeTrade\EdgeTrialLedgerReport",
        "log": ROOT / "data" / "edge_trial_ledger_report_log.jsonl",
        "kind": "evening",
    },
    {
        "name": "Elite Bot Scorecard",
        "task": r"\VibeTrade\EliteBotReadinessScorecard",
        "log": ROOT / "data" / "elite_bot_readiness_scorecard_log.jsonl",
        "kind": "evening",
    },
    {
        "name": "Adaptive Options",
        "task": r"\VibeTrade\AdaptiveOptionsShadowPlaybook",
        "log": ROOT / "data" / "adaptive_options_shadow_playbook_log.jsonl",
        "kind": "intraday",
    },
    {
        "name": "Shadow Consensus Gate",
        "task": r"\VibeTrade\ShadowConsensusGate",
        "log": ROOT / "data" / "shadow_consensus_gate_log.jsonl",
        "kind": "intraday",
    },
    {
        "name": "Market Catalyst Calendar",
        "task": r"\VibeTrade\MarketCatalystCalendar",
        "log": ROOT / "data" / "market_catalyst_calendar_log.jsonl",
        "kind": "morning",
    },
    {
        "name": "Higher Timeframe Map",
        "task": r"\VibeTrade\HigherTimeframeMarketMap",
        "log": ROOT / "data" / "higher_timeframe_market_map_log.jsonl",
        "kind": "morning",
    },
    {
        "name": "Candlestick Context",
        "task": r"\VibeTrade\CandlestickContextScanner",
        "log": ROOT / "data" / "candlestick_context_log.jsonl",
        "kind": "intraday",
    },
    {
        "name": "Daily Edge Orchestrator",
        "task": r"\VibeTrade\DailyEdgeOrchestrator",
        "log": ROOT / "data" / "daily_edge_orchestrator_log.jsonl",
        "kind": "intraday",
    },
    {
        "name": "Kronos Market Forecaster",
        "task": r"\VibeTrade\KronosMarketForecaster",
        "log": ROOT / "data" / "kronos_market_forecast_log.jsonl",
        "kind": "intraday",
    },
    {
        "name": "Polymarket Weather Bot",
        "task": r"\VibeTrade\PolymarketWeatherBot",
        "log": ROOT / "data" / "polymarket_weather_log.jsonl",
        "kind": "intraday",
    },
    {
        "name": "Flip Decision Missed Banger",
        "task": r"\VibeTrade\FlipDecisionMissedBangerReview",
        "log": ROOT / "data" / "flip_decision_missed_banger_review_log.jsonl",
        "kind": "evening",
    },
    {
        "name": "Outcome Science",
        "task": r"\VibeTrade\OutcomeScienceReport",
        "log": ROOT / "data" / "outcome_science_report_log.jsonl",
        "kind": "evening",
    },
    {
        "name": "Research Utilization",
        "task": r"\VibeTrade\ResearchAssetUtilizationAudit",
        "log": ROOT / "data" / "research_asset_utilization_log.jsonl",
        "kind": "evening",
    },
    {
        "name": "Behavior Watchdog",
        "task": r"\VibeTrade\BotBehaviorRegressionWatchdog",
        "log": ROOT / "data" / "bot_behavior_regression_watchdog_log.jsonl",
        "kind": "intraday",
    },
]


def _latest_jsonl(path: Path) -> tuple[dict | None, int, str | None]:
    if not path.exists():
        return None, 0, "missing"
    rows = []
    bad_lines = 0
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            bad_lines += 1
            continue
        if isinstance(row, dict):
            rows.append(row)
    if not rows:
        return None, 0, "empty" if bad_lines == 0 else f"invalid_json_lines={bad_lines}"
    warning = f"invalid_json_lines={bad_lines}" if bad_lines else None
    return rows[-1], len(rows), warning


def _task_status(task_name: str) -> dict:
    try:
        proc = subprocess.run(
            ["schtasks", "/Query", "/TN", task_name, "/FO", "LIST"],
            check=False,
            capture_output=True,
            text=True,
            timeout=15,
        )
    except Exception as exc:
        return {"available": False, "status": "unknown", "error": str(exc)[:160]}
    if proc.returncode != 0:
        return {
            "available": False,
            "status": "missing",
            "error": (proc.stderr or proc.stdout).strip()[:160],
        }
    parsed = {}
    for raw in proc.stdout.splitlines():
        if ":" not in raw:
            continue
        key, value = raw.split(":", 1)
        parsed[key.strip().lower().replace(" ", "_")] = value.strip()
    return {
        "available": True,
        "status": parsed.get("status", "unknown"),
        "next_run_time": parsed.get("next_run_time", ""),
        "last_run_time": parsed.get("last_run_time", ""),
    }


def _row_has_errors(row: dict | None) -> list[str]:
    if not row:
        return []
    errors: list[str] = []
    if row.get("status") == "market_closed":
        return []
    scans = row.get("scans")
    if isinstance(scans, list):
        for scan in scans:
            if isinstance(scan, dict) and scan.get("status") == "error":
                errors.append(f"{scan.get('symbol', '?')}: {scan.get('error', 'error')}")
    for key in ("primary", "comparison"):
        section = row.get(key)
        if isinstance(section, dict) and section.get("error"):
            errors.append(f"{key}: {section.get('error')}")
    return errors


def _last_weekday(d: date) -> date:
    """Return d, or the most recent Friday if d is Sat/Sun."""
    dow = d.weekday()  # 0=Mon … 6=Sun
    if dow == 5:
        return d - timedelta(days=1)
    if dow == 6:
        return d - timedelta(days=2)
    return d


def _is_before_today(latest_date: str, today_str: str) -> bool:
    return bool(latest_date) and latest_date < today_str


def _parse_task_datetime(value: str) -> datetime | None:
    value = (value or "").strip()
    if not value or value.upper() == "N/A":
        return None
    for fmt in ("%m/%d/%Y %I:%M:%S %p", "%m/%d/%Y %I:%M %p"):
        try:
            return datetime.strptime(value, fmt)
        except ValueError:
            continue
    return None


def _pending_scheduled_run_today(task: dict, today: date, now: datetime) -> bool:
    next_run = _parse_task_datetime(str(task.get("next_run_time", "")))
    return bool(next_run and next_run.date() == today and next_run > now)


def _read_records(path: Path) -> list[dict]:
    if not path.exists():
        return []
    try:
        if path.suffix.lower() == ".json":
            payload = json.loads(path.read_text(encoding="utf-8-sig"))
            if isinstance(payload, list):
                return [row for row in payload if isinstance(row, dict)]
            if isinstance(payload, dict):
                rows = payload.get("trades") or payload.get("positions") or []
                return [row for row in rows if isinstance(row, dict)]
    except (OSError, json.JSONDecodeError):
        return []
    rows = []
    for raw in path.read_text(encoding="utf-8-sig").splitlines():
        try:
            row = json.loads(raw)
        except json.JSONDecodeError:
            continue
        if isinstance(row, dict):
            rows.append(row)
    return rows


def _event_day(value: object) -> date | None:
    text = str(value or "")[:10]
    try:
        return date.fromisoformat(text)
    except ValueError:
        return None


def _business_days_since(then: date, today: date) -> int:
    if then >= today:
        return 0
    cursor = then + timedelta(days=1)
    count = 0
    while cursor <= today:
        if cursor.weekday() < 5:
            count += 1
        cursor += timedelta(days=1)
    return count


def _canonical_strategy(row: dict) -> str | None:
    if row.get("execution_lane") == "paper_challenger":
        return "paper_challenger"
    strategy = str(row.get("strategy") or "")
    if strategy == "noise_area_vwap":
        return "noise_area_vwap"
    if strategy == "orb_extension_reversal":
        return "orb_extension_reversal"
    if strategy in {"0dte", "orb_15m_retest", "bull_trend", "bear_trend"}:
        return "orb_continuation"
    return None


def build_strategy_staleness(
    *,
    today: date,
    trades_path: Path = FLIP_TRADES_PATH,
    shadow_path: Path = FLIP_SHADOW_PATH,
) -> dict:
    events: dict[str, dict[str, list[date]]] = {
        name: {"entry": [], "close": []} for name in STALENESS_THRESHOLDS
    }
    for row in _read_records(trades_path):
        strategy = _canonical_strategy(row)
        if not strategy:
            continue
        entry_day = _event_day(row.get("entry_at") or row.get("entry_date"))
        close_day = _event_day(row.get("exit_at") or row.get("exit_date"))
        if entry_day:
            events[strategy]["entry"].append(entry_day)
        if close_day:
            events[strategy]["close"].append(close_day)
    for row in _read_records(shadow_path):
        strategy = _canonical_strategy(row)
        if not strategy:
            continue
        event_day = _event_day(row.get("scanned_at") or row.get("date"))
        if not event_day:
            continue
        if row.get("event_type") == "shadow_entry":
            events[strategy]["entry"].append(event_day)
        elif row.get("event_type") == "shadow_exit":
            events[strategy]["close"].append(event_day)

    output = {}
    for strategy, thresholds in STALENESS_THRESHOLDS.items():
        entries = events[strategy]["entry"]
        closes = events[strategy]["close"]
        last_entry = max(entries) if entries else None
        last_close = max(closes) if closes else None
        days_entry = _business_days_since(last_entry, today) if last_entry else None
        days_close = _business_days_since(last_close, today) if last_close else None
        reasons = []
        activation_day = STRATEGY_ACTIVATION_DATES.get(strategy)
        activation_age = _business_days_since(activation_day, today) if activation_day else None
        if days_entry is not None and days_entry > thresholds["max_days_without_entry"]:
            reasons.append(f"no_entry_for_{days_entry}_business_days")
        elif days_entry is None and activation_age is not None and activation_age > thresholds["max_days_without_entry"]:
            reasons.append(f"zero_entries_since_activation_{activation_age}_business_days")
        max_close = thresholds.get("max_days_without_close")
        if max_close is not None and days_close is not None and days_close > max_close:
            reasons.append(f"no_close_for_{days_close}_business_days")
        output[strategy] = {
            "last_entry_date": last_entry.isoformat() if last_entry else None,
            "last_close_date": last_close.isoformat() if last_close else None,
            "days_since_last_entry": days_entry,
            "days_since_last_close": days_close,
            "alert": bool(reasons),
            "reasons": reasons,
            "note": "no_observations_yet" if not entries else None,
            "activation_date": activation_day.isoformat() if activation_day else None,
            "thresholds": thresholds,
        }
    return output


def build_report(today: date | None = None, now: datetime | None = None) -> dict:
    today = today or date.today()
    now = now or datetime.now()
    today_str = _last_weekday(today).isoformat()
    items = []
    for signal in SIGNALS:
        latest, row_count, parse_warning = _latest_jsonl(signal["log"])
        task = _task_status(signal["task"])
        latest_row = latest or {}
        latest_date = str(
            latest_row.get("date")
            or latest_row.get("generated_at", "")[:10]
            or latest_row.get("scanned_at", "")[:10]
            or ""
        )
        errors = _row_has_errors(latest)
        stale_before_today = _is_before_today(latest_date, today_str)
        pending_today = stale_before_today and _pending_scheduled_run_today(task, today, now)
        task_disabled = task.get("status") == "Disabled"
        if task_disabled:
            # A deliberately disabled producer cannot be "stale"; it is not
            # expected to emit output. Tracked separately so it stays visible.
            health = "disabled"
        elif latest is None:
            health = "missing"
        elif pending_today:
            health = "ok"
        elif stale_before_today:
            health = "stale"
        elif errors:
            health = "error"
        else:
            health = "ok"
        warnings = []
        if parse_warning:
            warnings.append(parse_warning)
        if task.get("status") != "Ready":
            warnings.append(f"task_status={task.get('status')}")
        if pending_today:
            warnings.append(f"pending_today latest_date={latest_date}")
        elif stale_before_today:
            warnings.append(f"latest_date={latest_date}")
        warnings.extend(errors)
        items.append({
            "name": signal["name"],
            "kind": signal["kind"],
            "task": signal["task"],
            "task_status": task,
            "log_path": str(signal["log"]),
            "row_count": row_count,
            "latest_date": latest_date,
            "health": health,
            "warnings": warnings,
        })
    summary = {
        "ok": sum(1 for item in items if item["health"] == "ok"),
        "stale": sum(1 for item in items if item["health"] == "stale"),
        "missing": sum(1 for item in items if item["health"] == "missing"),
        "error": sum(1 for item in items if item["health"] == "error"),
        "disabled": sum(1 for item in items if item["health"] == "disabled"),
    }
    strategy_staleness = build_strategy_staleness(today=today)
    return {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "date": today_str,
        "summary": summary,
        "items": items,
        "strategy_staleness_status": (
            "ALERT" if any(row["alert"] for row in strategy_staleness.values()) else "OK"
        ),
        "strategy_staleness": strategy_staleness,
    }


def write_report(report: dict, path: Path = REPORT_PATH) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def print_report(report: dict) -> None:
    print("\nSignal Stack Health | " + report["date"])
    print("=" * 72)
    print(
        f"OK={report['summary']['ok']}  "
        f"STALE={report['summary']['stale']}  "
        f"MISSING={report['summary']['missing']}  "
        f"ERROR={report['summary']['error']}  "
        f"DISABLED={report['summary'].get('disabled', 0)}"
    )
    print()
    for item in report["items"]:
        task = item["task_status"]
        warn = "; ".join(item["warnings"]) if item["warnings"] else "-"
        print(
            f"{item['name']:<16} health={item['health']:<7} "
            f"task={task.get('status', '?'):<8} rows={item['row_count']:<3} "
            f"latest={item['latest_date'] or '-':<10} next={task.get('next_run_time', '-')}"
        )
        if warn != "-":
            print(f"  warnings: {warn}")
    print(f"\nStrategy staleness: {report.get('strategy_staleness_status', 'UNKNOWN')}")
    for name, row in (report.get("strategy_staleness") or {}).items():
        note = ",".join(row.get("reasons") or []) or row.get("note") or "current"
        print(
            f"  {name:<24} entry_days={str(row.get('days_since_last_entry')):<4} "
            f"close_days={str(row.get('days_since_last_close')):<4} "
            f"alert={str(row.get('alert')):<5} {note}"
        )
    print(f"\nJSON: {REPORT_PATH}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Check new signal stack task/log health.")
    parser.add_argument("--no-write", action="store_true", help="Do not write JSON report.")
    args = parser.parse_args()
    report = build_report()
    print_report(report)
    if not args.no_write:
        write_report(report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

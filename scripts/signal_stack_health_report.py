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
from datetime import date, datetime, time, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo


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
        "name": "Pattern Grader",
        "task": r"\VibeTrade\PatternGrader-Scanner-Intraday",
        "log": ROOT / "data" / "pattern_grader_log.jsonl",
        "activity_path": REPORT_DIR / "pattern-grader-grades.json",
        "kind": "intraday",
        "require_successful_task": True,
        "max_hours_since_last_row": 6,
        "require_activity_after_last_run": True,
    },
    {
        "name": "Pattern Outcomes",
        "task": r"\PatternGrader-OutcomeResolver",
        "log": ROOT / "data" / "pattern_grader_outcomes.jsonl",
        "kind": "close",
        "require_successful_task": True,
        "max_hours_since_last_row": 26,
        "require_activity_after_last_run": True,
    },
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
        "name": "Equity Swing Continuation",
        "task": r"\VibeTrade\EquityIgnitionContinuationShadow",
        "log": ROOT / "data" / "equity_ignition_continuation_shadow_log.jsonl",
        "kind": "close",
    },
    {
        "name": "Equity Swing Revalidate",
        "task": r"\VibeTrade\EquityIgnitionContinuationRevalidate",
        "log": ROOT / "data" / "equity_ignition_continuation_shadow_log.jsonl",
        "kind": "morning",
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


def _row_date(row: dict) -> str:
    return str(
        row.get("date")
        or str(row.get("generated_at") or "")[:10]
        or str(row.get("scanned_at") or "")[:10]
        or str(row.get("resolved_at") or "")[:10]
        or str(row.get("timestamp") or "")[:10]
        or ""
    )


def _latest_jsonl(path: Path, preferred_date: str | None = None) -> tuple[dict | None, int, str | None]:
    if not path.exists():
        return None, 0, "missing"
    rows = []
    preferred_rows = []
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
            if preferred_date and _row_date(row) == preferred_date:
                preferred_rows.append(row)
    if not rows:
        return None, 0, "empty" if bad_lines == 0 else f"invalid_json_lines={bad_lines}"
    warning = f"invalid_json_lines={bad_lines}" if bad_lines else None
    return (preferred_rows[-1] if preferred_rows else rows[-1]), len(rows), warning


def _task_status(task_name: str) -> dict:
    try:
        proc = subprocess.run(
            ["schtasks", "/Query", "/TN", task_name, "/FO", "LIST", "/V"],
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
        "last_result": parsed.get("last_result", ""),
    }


def _task_failed(task: dict) -> bool:
    """Return True only for a completed, non-zero task result.

    Task Scheduler uses 0x41301/267009 while a task is running. A task that
    has never run also has a non-success sentinel, so require a real last-run
    timestamp before failing it closed.
    """
    if not task.get("available") or task.get("status") == "Running":
        return False
    last_run = _parse_task_datetime(str(task.get("last_run_time", "")))
    if last_run is None or last_run.year <= 1999:
        return False
    raw = str(task.get("last_result", "")).strip()
    try:
        result = int(raw, 0)
    except ValueError:
        return bool(raw and raw.upper() not in {"N/A", "THE OPERATION COMPLETED SUCCESSFULLY."})
    return result != 0


def _latest_row_timestamp(row: dict | None) -> datetime | None:
    """Extract wall-clock timestamp from a JSONL row across the schemas we log."""
    if not row:
        return None
    for key in (
        "resolved_at", "generated_at", "scanned_at", "timestamp", "logged_at",
        "observed_at", "bar_close_ts", "trigger_bar_ts",
    ):
        raw = row.get(key)
        if not raw:
            continue
        text = str(raw).replace("Z", "+00:00")
        try:
            parsed = datetime.fromisoformat(text)
        except ValueError:
            continue
        if parsed.tzinfo is not None:
            # Health windows are defined in the deployment's Chicago wall clock.
            # Converting through the host timezone made identical evidence stale
            # on Windows but fresh on Linux CI.
            parsed = parsed.astimezone(ZoneInfo("America/Chicago")).replace(tzinfo=None)
        return parsed
    return None


def _json_document(path: Path | None) -> dict | None:
    if path is None:
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def _hours_since(then: datetime | None, now: datetime) -> float | None:
    if then is None:
        return None
    return max(0.0, (now - then).total_seconds() / 3600.0)


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


def _nth_weekday(year: int, month: int, weekday: int, occurrence: int) -> date:
    first = date(year, month, 1)
    offset = (weekday - first.weekday()) % 7
    return first + timedelta(days=offset + 7 * (occurrence - 1))


def _last_weekday_of_month(year: int, month: int, weekday: int) -> date:
    if month == 12:
        cursor = date(year + 1, 1, 1) - timedelta(days=1)
    else:
        cursor = date(year, month + 1, 1) - timedelta(days=1)
    return cursor - timedelta(days=(cursor.weekday() - weekday) % 7)


def _observed_fixed_holiday(day: date) -> date:
    if day.weekday() == 5:
        return day - timedelta(days=1)
    if day.weekday() == 6:
        return day + timedelta(days=1)
    return day


def _easter_sunday(year: int) -> date:
    """Return Gregorian Easter using the Meeus/Jones/Butcher algorithm."""
    a = year % 19
    b, c = divmod(year, 100)
    d, e = divmod(b, 4)
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i, k = divmod(c, 4)
    ell = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * ell) // 451
    month = (h + ell - 7 * m + 114) // 31
    day = (h + ell - 7 * m + 114) % 31 + 1
    return date(year, month, day)


def _nyse_full_day_holidays(year: int) -> frozenset[date]:
    holidays = {
        _observed_fixed_holiday(date(year, 1, 1)),
        _nth_weekday(year, 1, 0, 3),
        _nth_weekday(year, 2, 0, 3),
        _easter_sunday(year) - timedelta(days=2),
        _last_weekday_of_month(year, 5, 0),
        _observed_fixed_holiday(date(year, 7, 4)),
        _nth_weekday(year, 9, 0, 1),
        _nth_weekday(year, 11, 3, 4),
        _observed_fixed_holiday(date(year, 12, 25)),
    }
    if year >= 2022:
        holidays.add(_observed_fixed_holiday(date(year, 6, 19)))
    next_new_year = _observed_fixed_holiday(date(year + 1, 1, 1))
    if next_new_year.year == year:
        holidays.add(next_new_year)
    return frozenset(holidays)


def is_expected_market_session(day: date) -> bool:
    """Whether US equities are expected to have a regular/early-close session.

    Only full-day NYSE closures are excluded. Early closes remain expected
    sessions because producers should still emit rows on those dates. This is
    public so other operational coverage gates can reuse the same calendar.
    """
    return day.weekday() < 5 and day not in _nyse_full_day_holidays(day.year)


def _last_expected_market_session(d: date) -> date:
    cursor = d
    while not is_expected_market_session(cursor):
        cursor -= timedelta(days=1)
    return cursor


def _market_session_hours_since(then: datetime | None, now: datetime) -> float | None:
    """Elapsed regular-session hours, excluding nights/weekends/holidays.

    Task Scheduler and normalized row timestamps use local wall time on this
    deployment (America/Chicago), where regular trading is 08:30-15:00.
    """
    if then is None:
        return None
    if then >= now:
        return 0.0
    total_seconds = 0.0
    cursor = then.date()
    while cursor <= now.date():
        if is_expected_market_session(cursor):
            session_open = datetime.combine(cursor, time(8, 30))
            session_close = datetime.combine(cursor, time(15, 0))
            start = max(then, session_open)
            end = min(now, session_close)
            if end > start:
                total_seconds += (end - start).total_seconds()
        cursor += timedelta(days=1)
    return total_seconds / 3600.0


def _is_expected_activity_run(kind: str, run_at: datetime) -> bool:
    """Whether a task run occurred in its normal data-producing window."""
    if not is_expected_market_session(run_at.date()):
        return False
    minute = run_at.hour * 60 + run_at.minute
    windows = {
        "morning": (4 * 60, 14 * 60),
        "intraday": (8 * 60, 15 * 60 + 30),
        "close": (14 * 60 + 30, 18 * 60 + 30),
        "evening": (14 * 60 + 30, 23 * 60 + 59),
    }
    start, end = windows.get(kind, (0, 23 * 60 + 59))
    return start <= minute <= end


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
    today_str = _last_expected_market_session(today).isoformat()
    items = []
    for signal in SIGNALS:
        latest, row_count, parse_warning = _latest_jsonl(signal["log"], preferred_date=today_str)
        task = _task_status(signal["task"])
        latest_row = latest or {}
        latest_date = _row_date(latest_row)
        errors = _row_has_errors(latest)
        try:
            latest_day = date.fromisoformat(latest_date)
        except ValueError:
            latest_day = None
        non_session_row_cannot_clear_gap = bool(
            latest_day
            and latest_date > today_str
            and not is_expected_market_session(latest_day)
            and str(signal.get("kind")) in {"morning", "intraday", "close"}
        )
        stale_before_today = _is_before_today(latest_date, today_str) or non_session_row_cannot_clear_gap
        pending_today = stale_before_today and _pending_scheduled_run_today(task, today, now)
        task_disabled = task.get("status") == "Disabled"
        task_required = bool(signal.get("require_successful_task"))
        task_unavailable = task_required and not task.get("available")
        task_failed = task_required and _task_failed(task)

        # Stale-outcome detection: a task can exit 0 and still stop producing.
        # Guard against the "healthy while broken" case by inspecting the last
        # row's own timestamp and comparing to when the task last ran.
        max_activity_hours = signal.get("max_hours_since_last_row")
        activity_path = signal.get("activity_path")
        activity_document = _json_document(activity_path) if isinstance(activity_path, Path) else None
        latest_row_ts = _latest_row_timestamp(activity_document or latest)
        activity_hours = _market_session_hours_since(latest_row_ts, now)
        stale_activity = (
            max_activity_hours is not None
            and (latest is None or (activity_hours is not None and activity_hours > max_activity_hours))
        )
        last_run_ts = _parse_task_datetime(str(task.get("last_run_time", "")))
        run_hours = _hours_since(last_run_ts, now)
        empty_after_run = (
            bool(signal.get("require_activity_after_last_run"))
            and last_run_ts is not None
            and _is_expected_activity_run(str(signal.get("kind", "")), last_run_ts)
            and (latest_row_ts is None or latest_row_ts < last_run_ts - timedelta(minutes=5))
            and run_hours is not None
            and run_hours < 24
        )

        if task_disabled:
            # A deliberately disabled producer cannot be "stale"; it is not
            # expected to emit output. Tracked separately so it stays visible.
            health = "disabled"
        elif task_unavailable or task_failed:
            health = "error"
        elif latest is None:
            health = "missing"
        elif empty_after_run:
            health = "error"
        elif stale_activity:
            health = "stale"
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
        if task_unavailable:
            warnings.append("required_task_unavailable")
        if task_failed:
            warnings.append(f"task_last_result={task.get('last_result')}")
        if pending_today:
            warnings.append(f"pending_today latest_date={latest_date}")
        elif stale_before_today:
            warnings.append(f"latest_date={latest_date} expected_session={today_str}")
        if empty_after_run:
            warnings.append(
                f"empty_after_last_run last_run={task.get('last_run_time') or '?'} "
                f"latest_row_ts={latest_row_ts.isoformat(timespec='seconds') if latest_row_ts else 'none'}"
            )
        if stale_activity and not empty_after_run:
            hours_text = f"{activity_hours:.1f}" if activity_hours is not None else "none"
            warnings.append(
                f"no_new_rows_in={hours_text}h max_allowed={max_activity_hours}h"
            )
        warnings.extend(errors)
        items.append({
            "name": signal["name"],
            "kind": signal["kind"],
            "task": signal["task"],
            "task_status": task,
            "log_path": str(signal["log"]),
            "activity_path": str(activity_path) if activity_path else None,
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
